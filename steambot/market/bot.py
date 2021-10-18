import os
import logging
import asyncio
import requests
from dotenv import load_dotenv
from datetime import datetime as dt, timedelta as delta

from .models import Bot, ItemGroup
from logs.logger import log

load_dotenv()

logger_name = str(__file__)[str(__file__)[: str(__file__).rfind('\\')].rfind('\\'):]
module_logger = logging.getLogger(logger_name)

update_inventory_delta = delta(minutes=int(os.environ.get('UPDATE_INVENTORY_DELTA')))
trade_lock_delta = delta(days=7)
ping_pong_delta = delta(minutes=3)


sessions = {}


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
                log(f'Ping:\n{_response}')
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
            log(f'Response:\n{response}')
            success = response.get('success', False)
            if not success:
                await asyncio.sleep(10)
            return response

    except Exception as e:
        if error_recursion:
            log(e, 'ERROR')
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


async def bot_update_inventory(bot: Bot):
    if (dt.now() - bot.state_check_timestamp) >= update_inventory_delta:
        response = await send_request_to_market(
            bot,
            'https://market.csgo.com/api/v2/update-inventory/',
            error_recursion=True,
            return_error=True
        )
        if 'error' in response:
            await bot.update(state_check_timestamp=dt.now())

    else:
        return


async def bot_work(bot: Bot):
    """Проверка бота на ативность происходит в главном потоке, при получении из базы"""

    item_groups = await ItemGroup.objects.filter(bot=bot).exclude(state__in=['disabled', 'active']).all()

    tasks = [asyncio.create_task(bot_group_states_check(bot, item_group)) for item_group in item_groups]
    for task in tasks:
        await task


# делает один оборот
async def bot_group_states_check(bot: Bot, group: ItemGroup):
    if group.state == 'sell':
        task_delete_orders = asyncio.create_task(_delete_orders(
            bot, group
        ))
        await task_delete_orders

    if group.state == 'buy':
        task_delete_sale_offers = asyncio.create_task(_delete_sale_offers(
            bot, group
        ))
        await task_delete_sale_offers

    if group.state == 'hold':
        task_delete_sale_offers = asyncio.create_task(_delete_sale_offers(
            bot, group
        ))

        task_delete_orders = asyncio.create_task(_delete_orders(
            bot, group
        ))

        await task_delete_orders
        await task_delete_sale_offers

        await group.update(state='disabled')

    if group.state == 'delete':
        task_delete_sale_offers = asyncio.create_task(_delete_sale_offers(
            bot, group
        ))

        task_delete_orders = asyncio.create_task(_delete_orders(
            bot, group
        ))

        await task_delete_orders
        await task_delete_sale_offers
        await group.delete()


async def _group_buy(bot: Bot, group: ItemGroup):
    log(f'In _group_buy for group {group.market_hash_name} with to_order_amount {group.to_order_amount}')
    if group.to_order_amount > 0:

        log(f'In buy group with market_hash_name {group.market_hash_name}:\n')

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
            log(items["error"], 'ERROR')
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
        # если доступных предметов меньше чем заказанных, то заказываются все доступные предметы
        if group.amount > len(items['data']):
            group.amount = len(items['data'])

        for i in items['data'][:group.amount]:
            # нужно дозаказать определённое число предметов
            if group.to_order_amount <= 0:
                break

            response = await send_request_to_market(
                bot,
                f"https://market.csgo.com/api/BestBuyOffer/{i['class']}_{i['instance']}/",
                error_recursion=True,
                return_error=True
            )
            if 'error' in response:
                log(response['error'], 'ERROR')
                # если нет других ордеров на покупку этого предмета, то выставляем по цене, равной 40% от средней цены
                _buy_for = int(average_price * 0.4)

            else:
                best_offer = int(response.get('best_offer'))
                if int(i.get('price') * 0.8) > best_offer > int(i.get('price') * 0.4):
                    _buy_for = best_offer + 1
                # если все остальные ордеры слишком жадные, то создаём такой, чтобы цена была более привлекательной
                elif int(i.get('price') * 0.8) > best_offer and best_offer < int(i.get('price') * 0.4):
                    _buy_for = int(i.get('price') * 0.5)
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
                        log(response['error'], 'ERROR')
                        continue

                    else:
                        group.to_order_amount -= 1

                except Exception as e:
                    log(e, 'ERROR')
                    continue

        await group.update(to_order_amount=group.to_order_amount)


async def _group_sell(bot: Bot):
    group_names = await ItemGroup.objects.filter(bot=bot).exclude(
        state__in=['disabled', 'buy', 'hold']
    ).values_list(
        fields='market_hash_name',
        flatten=True
    )

    inventory = await send_request_to_market(
        bot,
        'https://market.csgo.com/api/v2/my-inventory/'
    )
    inventory = inventory.get('items', [])

    for item in inventory:
        if item['market_hash_name'] in group_names:

            response = await send_request_to_market(
                bot,
                'https://market.csgo.com/api/v2/search-item-by-hash-name',
                {
                    'hash_name': item['market_hash_name']
                },
                error_recursion=True
            )
            sell_for = response['data'][0]['price'] - 1

            response = await send_request_to_market(
                bot,
                'https://market.csgo.com/api/v2/add-to-sale',
                {
                    'id': item['id'],
                    'price': sell_for,
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


async def _delete_orders(bot: Bot, group: ItemGroup):
    """
    Удаляет все ордеры, созданные данной группой.
    """
    if group.to_order_amount < group.amount:
        log(f'In deleting all orders for group with market_hash_name {group.market_hash_name}:')

        items = await send_request_to_market(
            bot,
            'https://market.csgo.com/api/GetOrders//',
            error_recursion=True,
            return_error=True
        )
        if 'error' in items or items['Orders'] == "No orders":
            log(items.get('error', items.get('Orders')))
            return
        else:
            for item in items['Orders']:
                if item['i_market_hash_name'] == group.market_hash_name:

                    response = await send_request_to_market(
                        bot,
                        f'https://market.csgo.com/api/ProcessOrder/{item["i_classid"]}/{item["i_instanceid"]}/0/',
                        return_error=True,
                        error_recursion=True
                    )
                    if 'error' in response:
                        log(response['error'], 'ERROR')
                        if response['error'] == 'same_price':
                            continue
                        elif response['error'] == 'internal':
                            await asyncio.sleep(20)
                            await _delete_orders(bot, group)

                    else:
                        group.to_order_amount += 1

        await group.update(
            to_order_amount=group.to_order_amount)


async def _delete_sale_offers(bot: Bot, group: ItemGroup):
    """
    Удаляет все продложения, выставленные данной группой.
    """
    items = await send_request_to_market(
        bot,
        'https://market.csgo.com/api/v2/items',
        return_error=True,
        error_recursion=True
    )
    if not items['items'] or 'error' in items:
        log(f'No items in active of this group!')
        return

    left_items = False
    for item in items['items']:
        if item['status'] == '1' and item['market_hash_name']:
            response = await send_request_to_market(
                bot,
                'https://market.csgo.com/api/v2/set-price',
                {
                    'item_id': item['item_id'],
                    'price': 0,
                    'cur': 'RUB'
                }
            )
            if 'error' in response:
                log(response['error'], 'ERROR')
                left_items = True
    if left_items:
        await _delete_sale_offers(bot, group)


# # функции для обработчиков комманд
# async def hold_item(item: Item):
#     if item.state == 'ordered':
#         await _delete_orders(
#             item.item_group.bot, [item], item.item_group
#         )
#         await item.item_group.update(to_order_amount=item.item_group.to_order_amount + 1)
#     elif item.state == 'on_sale':
#         await _delete_sale_offers(
#             item.item_group.bot, [item]
#         )
#     await item.update(state='hold')
#
#
# async def delete_item(item: Item):
#     if item.state == 'ordered':
#         await _delete_orders(
#             item.item_group.bot, [item], item.item_group
#         )
#         await item.item_group.update(to_order_amount=item.item_group.to_order_amount + 1)
#     elif item.state == 'on_sale':
#         await _delete_sale_offers(
#             item.item_group.bot, [item]
#         )
#     await item.item_group.update(
#         amount=item.item_group.amount - 1,
#         to_order_amount=item.item_group.to_order_amount - 1
#     )
#     await item.delete()
