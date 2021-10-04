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

sessions = {}


# TODO: заменить на логирование
def log(out: str):
    print(str(out))


# TODO: попробовать переписать асинхронно
async def send_request_to_market(
        bot: Bot,
        url: str,
        params: dict = None,
        return_error: bool = False,
        error_recursion: bool = False
) -> dict:
    """
    Запросы к market.csgo.
    Перед каждым запросом проверяется, онлайн ли бот.
    Если в процессе запроста появляется ошибка, то возвращается её сообшение внутри словаря в ключе 'error'.
    """

    def get_bot_session(_bot: Bot) -> requests.Session:
        global sessions
        if _bot.id in sessions:
            return sessions[_bot.id]
        else:
            _session = requests.session()
            sessions[_bot.id] = _session
            return _session

    async def ping(_bot: Bot, _session: requests.Session):
        if (dt.now() - _bot.last_ping_pong) >= ping_pong_delta:
            pinged = False
            while not pinged:
                _response = _session.get(
                    url='https://market.csgo.com/api/v2/ping',
                    params={'key': _bot.secret_key}
                ).json()
                pinged = _response.get('success', False)
                log('in ping')
                log(_response)
                if not pinged:
                    await asyncio.sleep(10)
            await bot.update(last_ping_pong=dt.now())

    session = get_bot_session(bot)
    if params is None:
        params = {}
    if 'key' not in params:
        params['key'] = bot.secret_key

    success = False
    response = {}

    try:

        while not success:
            await ping(bot, session)
            response = session.get(url=url, params=params).json()
            if 'error' in response and return_error:
                return response
            log('in response')
            log(response)
            success = response.get('success', False)
            if not success:
                await asyncio.sleep(10)
            return response

    except Exception as e:
        if error_recursion:
            log(e)
            await asyncio.sleep(10)
            await send_request_to_market(bot, url, params, return_error, error_recursion)
        else:
            raise e


async def bot_balance(bot: Bot):
    response = await send_request_to_market(
        bot,
        'https://market.csgo.com/api/v2/get-money',
        return_error=True
    )
    if 'error' in response:
        await asyncio.sleep(10)
        await bot_balance(bot)
    return response.get('money', 0)


async def bot_update_database_with_inventory(bot: Bot, use_current_items: str = 'hold'):
    """
    Берём данные об инвентаре аккаунта из api и добавляем их в базу данных.
    Если current_items == "hold", то предметы не учавствуют в торгах и назодятся "на удержании".
    Если current_items == "for_sale" то предметы учавствуют в торгах если есть возможность их обменивать.
    """
    try:
        await send_request_to_market(
            bot,
            'https://market.csgo.com/api/v2/update-inventory/'
        )
        await asyncio.sleep(10)
        response = await send_request_to_market(
            bot,
            'https://market.csgo.com/api/v2/my-inventory/'
        )
    except Exception as e:
        log(e)
        return

    for item in response.get('items', []):

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

    _items = await Item.objects.filter(item_group=group).exclude(state='hold')
    items = {
        'for_buy': [],
        'ordered': [],
        'for_sale': [],
        'on_sale': []
    }
    for item in _items:
        items[item.state].append(item)

    if group.state == 'active':
        task_buy = asyncio.create_task(_group_buy(bot, group))

        task_sell = asyncio.create_task(_sell(
            bot, items['for_sale']
        ))

        await task_buy
        await task_sell

    if group.state == 'sell':

        task_sell = asyncio.create_task(_sell(
            bot, items['for_sale']
        ))

        task_delete_orders = asyncio.create_task(_delete_orders(
            bot, items['ordered']
        ))

        await task_delete_orders
        await task_sell
        await group.update(state='disabled')

    if group.state == 'buy':
        task_delete_sale_offers = asyncio.create_task(_delete_sale_offers(
            bot, items['on_sale']
        ))

        task_buy_group = asyncio.create_task(_group_buy(bot, group))

        await task_delete_sale_offers
        await task_buy_group

        await group.update(state='disabled')

    if group.state == 'hold':

        task_delete_sale_offers = asyncio.create_task(_delete_sale_offers(
            bot, items['on_sale']
        ))

        task_delete_orders = asyncio.create_task(_delete_orders(
            bot, items['ordered']
        ))

        await task_delete_orders
        await task_delete_sale_offers

        await Item.objects.filter(item_group=group).filter(state__in=['on_sale', 'ordered']).update(state='hold')
        await group.update(state='disabled')

    if group.state == 'delete':
        task_delete_sale_offers = asyncio.create_task(_delete_sale_offers(
            bot, items['on_sale']
        ))

        task_delete_orders = asyncio.create_task(_delete_orders(
            bot, items['ordered']
        ))

        await task_delete_orders
        await task_delete_sale_offers

        await Item.objects.exclude(state='hold').delete(item_group=group)
        await group.delete()

    await bot.update(state='circle_ended')


async def _sell(bot: Bot, items_for_sale: List[Item]):
    """
    Выставление предмета на продажу.
    Берём id предмета из инвентаря.
    """

    if items_for_sale:

        log('in sell')

        log('my inventory')
        try:
            inventory = await send_request_to_market(
                bot,
                'https://market.csgo.com/api/v2/my-inventory/'
            )
            inventory = inventory.get('items', [])
        except Exception as e:
            log(e)
            return

        items_with_id = []

        # Добавляем market_id предметам, которые выставляем на продажу
        # classid и instanceid имеются, так как мы продаём предметы, купленные и полученные ботом
        for item in items_for_sale:
            for _item in inventory:
                if item.classid == _item['classid'] and item.instanceid == _item['instanceid']:
                    item.market_id = _item['id']
                    items_with_id.append(item)

        log('items with ids:')
        log(items_with_id)

        for item in items_with_id:

            log('item sell with update price')

            # цена формируется на основании цены других предметов
            # (цена саого дешёвого предмета уменьшается на 1)
            response = await send_request_to_market(
                bot,
                'https://market.csgo.com/api/v2/search-item-by-hash-name',
                {
                    'hash_name': item.market_hash_name
                },
                error_recursion=True
            )

            response = await send_request_to_market(
                bot,
                'https://market.csgo.com/api/v2/add-to-sale',
                {
                    'id': item.market_id,
                    'price': (response['data'][0]['price'] - 1),
                    'cur': 'RUB'
                },
                error_recursion=True,
                return_error=True
            )
            if 'error' in response:
                await send_request_to_market(
                    bot,
                    'https://market.csgo.com/api/v2/update-inventory/',
                    error_recursion=True
                )
                await item.update(state='for_sale')
            else:
                await item.update(
                    state='on_sale',
                    market_id=item.market_id,
                    sell_for=(response['data'][0]['price'] - 1)
                )


async def _group_buy(bot: Bot, group: ItemGroup):
    if group.to_order_amount > 0:

        items = await send_request_to_market(
            bot,
            'https://market.csgo.com/api/v2/search-item-by-hash-name',
            params={
                'hash_name': group.market_hash_name
            },
            error_recursion=True,
            return_error=True
        )
        if 'error' in items:
            log(items['error'])
            return

        response = await send_request_to_market(
            bot,
            'https://market.csgo.com/api/v2/get-list-items-info',
            params={
                'list_hash_name[]': group.market_hash_name
            },
            error_recursion=True
        )
        # средняя цена продажи премета (в копейках)
        if not response['data']:
            return
        average_price = (int(response['data'][group.market_hash_name]['average']) + 1) * 100
        # используем ограниченное количество предметов, так как их очень много

        for i in items['data'][:group.amount]:
            # нужно дозаказать определённое число предметов
            if group.to_order_amount <= 0:
                break

            item = await Item.objects.get_or_none(
                classid=i['class'],
                instanceid=i['instance'],
                state__in=['for_buy', 'ordered']
            )

            if item and item.state == 'ordered':
                continue

            response = await send_request_to_market(
                bot,
                f"https://market.csgo.com/api/BestBuyOffer/{i['class']}_{i['instance']}/",
                error_recursion=True,
                return_error=True
            )
            if 'error' in response:
                # если нет других ордеров на покупку этого предмета, то выставляем по цене, равной 80% от средней цены
                _buy_for = int(average_price * 0.8)

            else:
                best_offer = int(response.get('best_offer'))
                if best_offer < int(i.get('price') * 0.8):
                    _buy_for = best_offer + 1
                else:
                    _buy_for = int(i.get('price') * 0.8)

            if await bot_balance(bot) * 100 - _buy_for >= 100:
                try:
                    response = await send_request_to_market(
                        bot,
                        f"https://market.csgo.com/api/InsertOrder/{i['class']}/{i['instance']}/{_buy_for}//",
                        return_error=True
                    )

                    if 'error' in response:
                        log(f'error during ordering: {response.get("error")}')
                        continue

                    else:
                        if not item:
                            await Item.objects.create(
                                item_group=group,
                                market_hash_name=group.market_hash_name,
                                classid=i['class'],
                                instanceid=i['instance'],
                                state='ordered',
                                buy_for=_buy_for,
                                ordered_for=_buy_for
                            )
                            group.to_order_amount -= 1
                        else:
                            await item.update(state='ordered', buy_for=_buy_for, ordered_for=_buy_for)

                except Exception as e:
                    log(e)
                    continue

        await group.update(to_order_amount=group.to_order_amount)


async def _delete_orders(bot: Bot, ordered_items: List[Item]):
    for item in ordered_items:
        log(f'in delete orders for item with id {item.id}')
        response = await send_request_to_market(
            bot,
            f'https://market.csgo.com/api/ProcessOrder/{item.classid}/{item.instanceid}/0/',
            return_error=True,
            error_recursion=True
        )
        if 'error' in response:
            log(response['error'])
            if response['error'] == 'same_price':
                continue
            elif response['error'] == 'internal':
                await asyncio.sleep(20)
                await _delete_orders(bot, [item])

        await item.update(state='for_buy')

    await ordered_items[0].item_group.update(
        to_order_amount=ordered_items[0].item_group.to_order_amount + len(ordered_items)
    )


async def _delete_sale_offers(bot, on_sale_items: List[Item]):
    for item in on_sale_items:
        response = await send_request_to_market(
            bot,
            'https://market.csgo.com/api/v2/set-price',
            {
                'price': 0,
                'item_id': item.market_id,
                'cur': 'RUB'
            },
            return_error=True,
            error_recursion=True
        )
        if 'error' in response:
            log(f'item {item.id} is not on sale!')
            await item.update(state='hold')
            continue

        await item.update(state='for_sale')


# функции для обработчиков комманд
async def hold_item(item: Item):
    if item.state == 'ordered':
        await _delete_orders(
            item.item_group.bot, [item]
        )
        await item.item_group.update(to_order_amount=item.item_group.to_order_amount + 1)
    elif item.state == 'on_sale':
        await _delete_sale_offers(
            item.item_group.bot, [item]
        )
    await item.update(state='hold')


async def delete_item(item: Item):
    if item.state == 'ordered':
        await _delete_orders(
            item.item_group.bot, [item]
        )
        await item.item_group.update(to_order_amount=item.item_group.to_order_amount + 1)
    elif item.state == 'on_sale':
        await _delete_sale_offers(
            item.item_group.bot, [item]
        )
    await item.item_group.update(
        amount=item.item_group.amount - 1,
        to_order_amount=item.item_group.to_order_amount - 1
    )
    await item.delete()
