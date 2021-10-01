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

    if group.state == 'active':

        task_buy = asyncio.create_task(_group_buy(bot, group))

        task_sell = asyncio.create_task(_sell(
            bot, await Item.objects.filter(item_group=group).filter(state='for_sale').all()
        ))

        await task_buy
        await task_sell

    if group.state == 'sell':
        task_sell_all = asyncio.create_task(_sell_group(bot, group))
        await task_sell_all
        await group.update(state='disabled')

    if group.state == 'buy':
        task_buy_all = asyncio.create_task(_buy_group(bot, group))
        await task_buy_all
        await group.update(state='disabled')

    if group.state == 'hold':
        task_hold_all = asyncio.create_task(_hold_group(bot, group))
        await task_hold_all
        await group.update(state='disabled')

    if group.state == 'delete':
        task_delete_group = asyncio.create_task(delete_group(bot, group))
        await task_delete_group

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

            await item.update(
                state='on_sale',
                market_id=item.market_id,
                sell_for=(response['data'][0]['price'] - 1)
            )

            response = await send_request_to_market(
                bot,
                'https://market.csgo.com/api/v2/add-to-sale',
                {
                    'id': item.market_id,
                    'price': item.sell_for,
                    'cur': 'RUB'
                },
                return_error=True
            )
            if 'error' in response:
                await send_request_to_market(
                    bot,
                    'https://market.csgo.com/api/v2/update-inventory/',
                    error_recursion=True
                )
                await item.update(state='for_sale')


async def _buy(bot: Bot, items_for_buy: List[Item], items_ordered: List[Item]):
    """Создание ордера на покупку первого (из доступных) вещей (Item) если на балансе хватает денег"""

    if not items_ordered and items_for_buy:
        item = items_for_buy[0]

        response = await send_request_to_market(
            bot,
            'https://market.csgo.com/api/v2/search-item-by-hash-name',
            {
                'hash_name': item.market_hash_name
            },
            error_recursion=True
        )
        # Берём первый, самый дешёвый предмет
        item_info = response.get('data')[0]

        response = await send_request_to_market(
            bot,
            f"https://market.csgo.com/api/BestBuyOffer/{item_info.get('class')}_{item_info.get('instance')}/",
            error_recursion=True,
            return_error=True
        )
        if 'error' in response:
            _buy_for = (item_info.get('price') // 100) * 80

        else:
            best_offer = int(response.get('best_offer'))
            if best_offer < (item_info.get('price') // 100) * 80:
                _buy_for = best_offer + 1
            else:
                _buy_for = (item_info.get('price') // 100) * 80

        await item.update(
            classid=item_info.get('class'),
            instanceid=item_info.get('instance'),
            buy_for=_buy_for,
            ordered_for=_buy_for,
            sell_for=(item_info.get('price') - 1),
            state='ordered'
        )

        if await bot_balance(bot) * 100 - item.buy_for >= 100:
            log('in buy')
            try:
                response = await send_request_to_market(
                    bot,
                    f'https://market.csgo.com/api/InsertOrder/{item.classid}/{item.instanceid}/{item.buy_for}//',
                    return_error=True
                )
                if 'error' in response:
                    log(f'error during ordering: {response.get("error")}')
                    await item.update(state='for_buy')
                    return
            except Exception as e:
                log(e)
                await item.update(state='for_buy')
                return
        else:
            await item.update(state='for_buy')


async def _group_buy(bot: Bot, group: ItemGroup):
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

    for i in items['data']:
        item = await Item.objects.get_or_none(classid=i['class'], instance=i['instance'])

        if not item or item.state == 'for_buy':

            response = await send_request_to_market(
                bot,
                f"https://market.csgo.com/api/BestBuyOffer/{i['class']}_{i['instance']}/",
                error_recursion=True,
                return_error=True
            )
            if 'error' in response:
                _buy_for = (i.get('price') // 100) * 80

            else:
                best_offer = int(response.get('best_offer'))
                if best_offer < (i.get('price') // 100) * 80:
                    _buy_for = best_offer + 1
                else:
                    _buy_for = (i.get('price') // 100) * 80

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
                                instance=i['instance'],
                                state='ordered',
                                buy_for=_buy_for,
                                ordered_for=_buy_for
                            )
                        elif item.state == 'for_buy':
                            await item.update(buy_for=_buy_for, ordered_for=_buy_for, state='ordered')

                except Exception as e:
                    log(e)
                    continue


async def _sell_group(bot: Bot, group: ItemGroup):
    items_list = await Item.objects.filter(item_group=group).exclude(state='hold').all()
    items = {
        'ordered': [],
        'for_buy': [],
        'for_sale': [],
        'on_sale': []
    }
    for item in items_list:
        items[item.state].append(item)

    task_sell = asyncio.create_task(_sell(
        bot, items['for_sale']
    ))

    task_delete_orders = asyncio.create_task(_delete_orders(
        bot, items['ordered']
    ))

    await task_delete_orders
    await task_sell


async def _buy_group(bot: Bot, group: ItemGroup):
    items_list = await Item.objects.filter(item_group=group).exclude(state='hold').all()
    items = {
        'ordered': [],
        'for_buy': [],
        'for_sale': [],
        'on_sale': []
    }
    for item in items_list:
        items[item.state].append(item)

    task_buy = asyncio.create_task(_buy(
        bot, items['for_buy'], items['ordered']
    ))

    task_delete_sale_offers = asyncio.create_task(_delete_sale_offers(
        bot, items['on_sale']
    ))

    await task_buy
    await task_delete_sale_offers


async def _hold_group(bot: Bot, group: ItemGroup):
    items_list = await Item.objects.filter(item_group=group).exclude(state='hold').all()
    items = {
        'ordered': [],
        'for_buy': [],
        'for_sale': [],
        'on_sale': []
    }
    for item in items_list:
        items[item.state].append(item)

    task_delete_sale_offers = asyncio.create_task(_delete_sale_offers(
        bot, items['on_sale']
    ))

    task_delete_orders = asyncio.create_task(_delete_orders(
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


async def hold_item(item: Item):
    if item.state == 'ordered':
        await _delete_orders(
            item.item_group.bot, [item]
        )
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
    elif item.state == 'on_sale':
        await _delete_sale_offers(
            item.item_group.bot, [item]
        )
    await item.delete()
