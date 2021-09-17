import os
import datetime
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


async def bot_balance(bot: Bot):
    response = await send_request_until_success(
        bot,
        'https://market.csgo.com/api/v2/get-money'
    )
    return response.get('money', 0)

# TODO: переписать через requests.Session()
async def send_request_until_success(bot: Bot, url: str, params: dict = None) -> dict:
    async def ping(_bot: Bot):
        if (dt.now() - _bot.last_ping_pong) >= ping_pong_delta:
            pinged = False
            while not pinged:
                _response = requests.get(
                    url='https://market.csgo.com/api/v2/ping',
                    params={'key': _bot.secret_key}
                ).json()
                pinged = _response.get('success', False)
                print('in ping')
                print(_response)
                if not pinged:
                    await asyncio.sleep(10)
            await bot.update(last_ping_pong=datetime.datetime.now())

    if params is None:
        params = {}
    if 'key' not in params:
        params['key'] = bot.secret_key

    success = False
    response = {}
    while not success:
        await ping(bot)
        response = requests.get(url=url, params=params).json()
        print('in response')
        print(response)
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

    await send_request_until_success(
        bot,
        'https://market.csgo.com/api/v2/update-inventory/'
    )

    response = await send_request_until_success(
        bot,
        'https://market.csgo.com/api/v2/my-inventory/'
    )
    for item in response.get('items'):

        group = await ItemGroup.objects.get_or_create(
            state='disabled',
            bot=bot,
            market_hash_name=item.get('market_hash_name', None),
            classid=item.get('classid', None),
            instanceid=item.get('instanceid', None)
        )

        state = use_current_items
        trade_timestamp = dt.now() - trade_lock_delta
        if item.get('tradable', 0) != 1 and state == 'for_sale':
            state = 'untradable'
            trade_timestamp = dt.now()
        elif item.get('tradable', 0) != 1 and state == 'hold':
            trade_timestamp = dt.now()

        await Item.objects.get_or_create(
            state=state,
            item_group=group,
            market_id=item.get('id', None),
            market_hash_name=item.get('market_hash_name', None),
            classid=item.get('classid'),
            instanceid=item.get('instanceid'),
            trade_timestamp=trade_timestamp,
            sell_for=item.get('market_price'),
            buy_for=item.get('market_price') * 0.85
        )


async def bot_work(bot: Bot):
    """Проверка бота на ативность происходит в главном потоке, при получении из базы"""
    item_groups = await ItemGroup.objects.filter(bot=bot).exclude(state='disabled').all()
    tasks = [asyncio.create_task(bot_round_group(bot, item_group)) for item_group in item_groups]
    for task in tasks:
        await task


# делает один оборот
async def bot_round_group(bot: Bot, group: ItemGroup):
    await bot.update(state='in_circle')

    if group.state == 'active':
        items_list = await Item.objects.filter(item_group=group).exclude(state='hold').all()
        items = {
            'ordered': [],
            'for_buy': [],
            'for_sale': [],
            'on_sale': []
        }
        for item in items_list:
            items[item.state].append(item)

        task_sell = asyncio.create_task(sell(
            bot, items['for_sale']
        ))

        task_buy = asyncio.create_task(buy(
            bot, items['for_buy'], items['ordered']
        ))

        await task_sell
        await task_buy

    if group.state == 'sell':
        task_sell_all = asyncio.create_task(sell_group(bot, group))
        await task_sell_all
        await group.update(state='disabled')

    if group.state == 'buy':
        task_buy_all = asyncio.create_task(buy_group(bot, group))
        await task_buy_all
        await group.update(state='disabled')

    if group.state == 'hold':
        task_hold_all = asyncio.create_task(hold_group(bot, group))
        await task_hold_all
        await group.update(state='disabled')

    if group.state == 'delete':
        task_delete_group = asyncio.create_task(delete_group(bot, group))
        await task_delete_group

    await bot.update(state='circle_ended')


async def sell(bot: Bot, items_for_sale: List[Item]):
    """
    Выставление предмета на продажу.
    Берём id предмета из инвентаря.
    """

    inventory = await send_request_until_success(
        bot,
        'https://market.csgo.com/api/v2/my-inventory/'
    )
    inventory = inventory.get('items')

    items_with_id = []

    for item in items_for_sale:
        for _item in inventory:
            if item.classid == _item['classid'] and item.instanceid == _item['instanceid']:
                await item.update(market_id=_item['id'], state='on_sale')
                items_with_id.append(item)

    for item in items_with_id:
        await send_request_until_success(
            bot,
            'https://market.csgo.com/api/v2/add-to-sale',
            {
                'id': item.market_id,
                'price': item.sell_for,
                'cur': 'RUB'
            }
        )


async def buy(bot: Bot, items_for_buy: List[Item], items_ordered: List[Item]):
    """Создание ордера на покупку первого (из доступных) вещей (Item) если на балансе хватает денег"""
    if not items_ordered:
        item = items_for_buy[0]

        response = await send_request_until_success(
            bot,
            'https://market.csgo.com/api/v2/search-item-by-hash-name',
            {
                'hash_name': item.market_hash_name
            }
        )
        response = response.get('data')[0]
        if item.sell_for is None or item.buy_for is None:
            await item.update(
                classid=response.get('class'),
                instanceid=response.get('instance'),
                sell_for=response.get('price'),
                buy_for=response.get('price') * 0.87,
                ordered_for=response.get('price') * 0.87
            )
        else:
            await item.update(classid=response.get('class'), instanceid=response.get('instance'))

        if await bot_balance(bot) * 100 - item.buy_for >= 100:
            print('in buy')
            await send_request_until_success(
                bot,
                f'https://market.csgo.com/api/InsertOrder/{item.classid}/{item.instanceid}/{item.buy_for}//'
            )
            await item.update(state='ordered')


async def sell_group(bot: Bot, group: ItemGroup):
    items_list = await Item.objects.filter(item_group=group).exclude(state='hold').all()
    items = {
        'ordered': [],
        'for_buy': [],
        'for_sale': [],
        'on_sale': []
    }
    for item in items_list:
        items[item.state].append(item)

    task_sell = asyncio.create_task(sell(
        bot, items['for_sale']
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


async def hold_group(bot: Bot, group: ItemGroup):
    items_list = await Item.objects.filter(item_group=group).exclude(state='hold').all()
    items = {
        'ordered': [],
        'for_buy': [],
        'for_sale': [],
        'on_sale': []
    }
    for item in items_list:
        items[item.state].append(item)

    task_delete_sale_offers = asyncio.create_task(delete_sale_offers(
        bot, items['on_sale']
    ))

    task_delete_orders = asyncio.create_task(delete_orders(
        bot, items['ordered']
    ))

    await task_delete_orders
    await task_delete_sale_offers

    for item in items_list:
        await item.update(state='hold')


async def delete_group(bot: Bot, group: ItemGroup):
    items_list = await Item.objects.filter(item_group=group).exclude(state='hold').all()
    items = {
        'ordered': [],
        'for_buy': [],
        'for_sale': [],
        'on_sale': []
    }
    for item in items_list:
        items[item.state].append(item)

    task_delete_sale_offers = asyncio.create_task(delete_sale_offers(
        bot, items['on_sale']
    ))

    task_delete_orders = asyncio.create_task(delete_orders(
        bot, items['ordered']
    ))

    await task_delete_orders
    await task_delete_sale_offers

    await Item.objects.exclude(state='hold').delete(item_group=group)
    await group.delete()


async def delete_orders(bot: Bot, ordered_items: List[Item]):
    for item in ordered_items:
        await send_request_until_success(
            bot,
            f'https://market.csgo.com/api/ProcessOrder/{item.classid}/{item.instanceid}/0/'
        )
        await item.update(state='for_buy')


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
        await item.update(state='for_sale')


async def hold_item(item: Item):
    if item.state == 'ordered':
        task_delete_order = asyncio.create_task(delete_orders(
            item.item_group.bot, [item]
        ))
        await task_delete_order
    elif item.state == 'on_sale':
        task_delete_offer = asyncio.create_task(delete_sale_offers(
            item.item_group.bot, [item]
        ))
        await task_delete_offer
    await item.update(state='hold')


async def delete_item(item: Item):
    if item.state == 'hold':
        return
    if item.state == 'ordered':
        task_delete_order = asyncio.create_task(delete_orders(
            item.item_group.bot, [item]
        ))
        await task_delete_order
    elif item.state == 'on_sale':
        task_delete_offer = asyncio.create_task(delete_sale_offers(
            item.item_group.bot, [item]
        ))
        await task_delete_offer
    await item.delete()
