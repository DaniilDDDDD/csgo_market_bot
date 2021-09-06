import os
import asyncio
import requests
from typing import List
from dotenv import load_dotenv
from datetime import datetime as dt, timedelta as delta

from .models import Bot, Item, ItemGroup

load_dotenv()

state_check_delta = delta(minutes=int(os.environ.get('STATE_CHECK_TIMEDELTA')))
trade_lock_delta = delta(days=7)
ping_pong_delta = delta(minutes=3)


def ping(bot: Bot):
    if (dt.now() - bot.last_ping_pong) >= ping_pong_delta:
        success = False
        while not success:
            success = requests.get('https://market.csgo.com/api/v2/ping', params={'key': bot.api_key}).json().get(
                'success', False)


def bot_balance(bot: Bot):
    bot.balance = requests.get('https://market.csgo.com/api/v2/get-money', params={'key': bot.api_key}).json().get(
        'money', 0)
    return bot.balance


async def bot_state(bot: Bot) -> str:
    if (dt.now() - bot.state_check_timestamp) >= state_check_delta:
        bot = await Bot.objects.get(id=bot.id)
        bot.state_check_timestamp = dt.now()
    return bot.state


async def send_request_until_success(bot: Bot, url: str, params: dict = {}):
    success = False
    response = {}
    if 'key' not in params:
        params['key'] = bot.api_key
    while not success:
        ping(bot)
        response = requests.get(url=url, params=params).json()
        success = response.get('success', False)
        if not success:
            await asyncio.sleep(10)
    return response


async def bot_update_database_with_inventory(bot: Bot, use_current_items: str = 'hold'):
    """
    Берём данные об инвентаре аккаунта из api и добавляем их в базу данных.
    Если current_items == "hold", то предметы не учавствуют в торгах и назодятся "на удержании".
    Если current_items == "for_sale" то предметы учавствуют в торгах если есть возможность их обменивать.
    """

    response = await send_request_until_success(
        bot,
        'https://market.csgo.com/api/v2/my-inventory/'
    )
    for item in response.get('items'):

        group = await ItemGroup.objects.get_or_create(
            state='disabled',
            bot=bot,
            market_hash_name=item.get('market_hash_name', ''),
            classid=item.get('classid'),
            instanceid=item.get('instanceid')
        )

        state = use_current_items
        trade_timestamp = dt.now() - trade_lock_delta
        if item.get('tradable', 0) != 1 and state == 'for_sale':
            state = 'untradable'
            trade_timestamp = dt.now()
        elif item.get('tradable', 0) != 1 and state == 'hold':
            trade_timestamp = dt.now()

        skin = await Item.objects.get_or_create(
            state=state,
            item_group=group,
            market_id=item.get('id'),
            market_hash_name=item.get('market_hash_name', ''),
            classid=item.get('classid'),
            instanceid=item.get('instanceid'),
            trade_timestamp=trade_timestamp
        )


# def bot_start(bot: Bot):
#     '''Создание бота, но предметы в инвентаре отсутствуют в базе по умолчанию (а значит и не учавствуют в торгах))'''
#     steam_client = SteamClient(bot.api_key)
#     steam_client.login(
#         bot.username,
#         bot.password,
#         bot.steamguard_file
#     )
#     return steam_client

# def bot_stop(steam_client: SteamClient):
#     steam_client.logout()

async def bot_work(bot: Bot):
    """Проверка бота на кативность происходит в главном потоке, при получении из базы"""
    item_groups = await ItemGroup.objects.filter(bot=bot).exclude(state='disabled').all()
    tasks = [asyncio.create_task(bot_round_group(bot, item_group)) for item_group in item_groups]
    for task in tasks:
        await task
    return


# делает один оборот
async def bot_round_group(bot: Bot, group: ItemGroup):
    bot.state = 'in_circle'

    if group.state == 'active':
        items_list = await Item.objects.filter(item_group=group).exclude(state='hold').all()
        items = {
            'ordered': [],
            'untradable': [],
            'for_buy': [],
            'for_sale': [],
            'on_sale': []
        }
        for item in items_list:
            items[item.state].append(item)

        task_sell = asyncio.create_task(sell(
            bot, items['untradable'], items['for_sale']
        ))

        task_buy = asyncio.create_task(buy(
            bot, items['for_buy'], items['ordered']
        ))

        await task_sell
        await task_buy

    if group.state == 'sell':
        task_sell_all = asyncio.create_task(sell_group(bot, group))
        await task_sell_all
        group.state = 'disabled'

    if group.state == 'buy':
        task_buy_all = asyncio.create_task(buy_group(bot, group))
        await task_buy_all
        group.state = 'disabled'

    bot.state = 'circle_ended'


async def sell(bot: Bot, items_untradable: List[Item], items_for_sale: List[Item]):
    """
    Выставление предмета на продажу.
    У предметов (Item) должен быть id, так как они присутствуют в инвентаре.
    """
    for item in items_untradable:
        if (dt.now() - item.trade_timestamp) > trade_lock_delta:
            item.state = 'for_sale'
            items_for_sale.append(item)

    for item in items_for_sale:
        await send_request_until_success(
            bot,
            'https://market.csgo.com/api/v2/add-to-sale',
            {
                'id': item.market_id,
                'price': item.sell_for,
                'cur': 'RUB'
            }
        )
        item.state = 'on_sale'


async def buy(bot: Bot, items_for_buy: List[Item], items_ordered: List[Item]):
    """Создание ордера на покупку первого (из доступных) вещей (Item) если на балансе хватает денег"""
    if not items_ordered:
        item = items_for_buy[0]

        await send_request_until_success(
            bot,
            f'https://market.csgo.com/api/InsertOrder/{item.classid}/{item.instanceid}/{item.buy_for}//'
        )
        item.state = 'ordered'


async def sell_group(bot: Bot, group: ItemGroup):
    items_list = await Item.objects.filter(item_group=group).exclude(state='hold').all()
    items = {
        'ordered': [],
        'untradable': [],
        'for_buy': [],
        'for_sale': [],
        'on_sale': []
    }
    for item in items_list:
        items[item.state].append(item)

    task_sell = asyncio.create_task(sell(
        bot, items['untradable'], items['for_sale']
    ))

    task_delete_orders = asyncio.create_task(delete_orders(
        bot, items['ordered']
    ))

    await task_delete_orders
    await task_sell


async def buy_group(bot: Bot, group: ItemGroup):
    items_list = await Item.objects.filter(item_group=group).exclude(state='hold').all()
    items = {
        'ordered': [],
        'untradable': [],
        'for_buy': [],
        'for_sale': [],
        'on_sale': []
    }
    for item in items_list:
        items[item.state].append(item)

    task_buy = asyncio.create_task(buy(
        bot, items['for_buy'], items['ordered']
    ))

    task_delete_sale_offers = asyncio.create_task(delete_sale_offers(
        bot, items['on_sale']
    ))

    await task_buy
    await task_delete_sale_offers


async def delete_orders(bot: Bot, ordered_items: List[Item]):
    for item in ordered_items:
        await send_request_until_success(
            bot,
            f'https://market.csgo.com/api/ProcessOrder/{item.classid}/{item.instanceid}/0/'
        )
        item.state = 'for_buy'


async def delete_sale_offers(bot, on_sale_items: List[Item]):
    for item in on_sale_items:
        await send_request_until_success(
            bot,
            'https://market.csgo.com/api/v2/set-price',
            {
                'price': 0,
                'item_id': item.market_id,
                'cur': 'RUB'
            }
        )
        item.state = 'for_sale'
