import logging
import asyncio
from steampy.utils import GameOptions

from steampy.client import SteamClient, Asset, TradeOfferState

from .models import Bot, Item, ItemGroup

from .bot import (bot_work, send_request_to_market, bot_balance,
                  _delete_sale_offers, _delete_orders, _group_buy, _group_sell)
from logs.logger import log

logger_name = str(__file__)[str(__file__)[: str(__file__).rfind('\\')].rfind('\\'):]
module_logger = logging.getLogger(logger_name)

game = GameOptions.CS
steam_clients = {}


async def bots_states_check():
    """
    Отсюда происходит запуск раскручивания ботов:
    Если у бота статус 'in_circle' или 'paused', то его не трогаем;
    Если у бота статус 'circle_ended', то запускаем его следующий оборот;
    Если у бота статус 'destroy', то бот подготавливается к удалению из базы данных вместе с его группами предметов;
    Если у бота статус 'destroyed', то бот удаляется из базы данных вместе с его группами предметов;
    Если у бота статус 'sell', то у всех его групп предметов ставится статус 'sell';
    Если у бота статус 'buy', то у всех его групп предметов ставится статус 'buy'.
    """
    while True:

        bots = await Bot.objects.exclude(state='paused').all()

        log('In bots_states_check:')

        tasks = []
        for bot in bots:
            log(f'Bot {bot.id}:')
            if bot.state == 'active':
                tasks.append(asyncio.create_task(bot_work(bot)))

            elif bot.state == 'sell':
                await ItemGroup.objects.filter(bot=bot).filter(state__in=['active', 'buy']).update(state='sell')

                tasks.append(asyncio.create_task(bot_work(bot)))

            elif bot.state == 'buy':
                await ItemGroup.objects.filter(bot=bot).filter(state__in=['active', 'sell']).update(state='buy')

                tasks.append(asyncio.create_task(bot_work(bot)))

            elif bot.state == 'hold':
                await ItemGroup.objects.filter(bot=bot).filter(state__in=['active', 'buy', 'sell']).update(state='hold')

                tasks.append(asyncio.create_task(bot_work(bot)))

            elif bot.state == 'destroy':
                await bot.update(state='destroyed')

            elif bot.state == 'destroyed':
                steam_client = await get_bot_steam_client(bot)
                steam_client.logout()
                steam_clients.pop(bot.id)
                groups = await ItemGroup.objects.filter(bot=bot).all()

                for group in groups:
                    task_delete_sale_offers = asyncio.create_task(_delete_sale_offers(
                        bot,
                        await Item.objects.filter(item_group=group).filter(state='on_sale').all()
                    ))

                    task_delete_orders = asyncio.create_task(_delete_orders(
                        bot,
                        group
                    ))

                    await task_delete_orders
                    await task_delete_sale_offers

                    await Item.objects.exclude(state='hold').delete(item_group=group)
                    await group.delete()

                await bot.delete()

        for task in tasks:
            await task

        await asyncio.sleep(10)


async def sell():
    """
    Продаём предметы, доступные для продажи
    """

    log('In sell tradable items:')

    while True:

        bots = await Bot.objects.filter(state__in=['active', 'sell']).all()

        tasks = [asyncio.create_task(_group_sell(_bot)) for _bot in bots]
        for task in tasks:
            await task

        await asyncio.sleep(10)


async def buy():
    log('In buy items:')

    async def bot_buy(bot: Bot):
        groups = await ItemGroup.objects.exclude(state__in=['disabled', 'sell', 'hold']).all()
        _tasks = [asyncio.create_task(_group_buy(bot, _group)) for _group in groups]
        for _task in _tasks:
            await _task

    while True:

        bots = await Bot.objects.filter(state__in=['active', 'buy']).all()

        tasks = [asyncio.create_task(bot_buy(_bot)) for _bot in bots]
        for task in tasks:
            await task

        await asyncio.sleep(30)


# TODO: переписать через получение списка ордеров от маркета
async def update_orders_price():
    """
    Обновление цен на автоматическую покупку предмета:
    если появляется ордер от другого пользователя, который автоматически покупает предмет, но за большую сумму,
    то обновляему ордер, чтобы наш был дороже, дабы ордер был удовлетворён ранее
    """
    while True:

        log('In update_orders_price:')

        items = await Item.objects.select_related(Item.item_group.bot).filter(state='ordered').all()
        await asyncio.sleep(10)

        for item in items:

            try:
                response = await send_request_to_market(
                    item.item_group.bot,
                    f'https://market.csgo.com/api/BestBuyOffer/{item.classid}_{item.instanceid}/',
                    return_error=True
                )
                if 'error' in response:
                    continue
                else:
                    best_offer = int(response.get('best_offer'))

                response = await send_request_to_market(
                    item.item_group.bot,
                    'https://market.csgo.com/api/v2/search-item-by-hash-name',
                    {
                        'hash_name': item.market_hash_name
                    },
                    error_recursion=True
                )
                if response['data']:
                    item.sell_for = response['data'][0]['price'] - 1
                else:
                    continue

                if (
                        best_offer >= item.ordered_for
                        and (best_offer + 1) < int(item.sell_for * 0.9)
                        and (best_offer + 1) < await bot_balance(item.item_group.bot) * 100
                ) or (
                        # если цена продажи предмета более 500 рублей, то при отмене самого большого ордера на продажу,
                        # исходящего не от нас и отличающегося от нашего холтя бы на 3%,
                        # сменяем цену на цену этого ордера + 1
                        item.ordered_for - best_offer > int(item.sell_for * 0.03)
                        and item.sell_for > 50000
                ):
                    log('In update order:')
                    response = await send_request_to_market(
                        item.item_group.bot,
                        f'https://market.csgo.com/api/UpdateOrder/'
                        f'{item.classid}/{item.instanceid}/{best_offer + 1}/',
                        return_error=True
                    )
                    if 'error' in response:
                        log(f'Order with item with id {item.id} can not be changed now!', 'ERROR')
                        continue
                    await item.update(ordered_for=(best_offer + 1), sell_for=item.sell_for)

            except Exception as e:
                log(e, 'ERROR')
                continue


async def get_bot_steam_client(bot: Bot) -> SteamClient:
    """
    Получение steam-клиента, работающего с данными бота.
    """
    if bot.id in steam_clients:
        return steam_clients[bot.id]
    else:
        try:
            steam_client = SteamClient(bot.api_key)
            steam_client.login(
                bot.username,
                bot.password,
                bot.steamguard_file
            )
            steam_clients[bot.id] = steam_client
            return steam_client
        except Exception as e:
            log(e, 'ERROR')
            await asyncio.sleep(10)
            await get_bot_steam_client(bot)


async def take_items():
    """
    Принимаем трейды с купленными нами вещами
    """

    def is_donation(_offer: dict) -> bool:
        return _offer.get('items_to_receive') \
               and not _offer.get('items_to_give') \
               and _offer['trade_offer_state'] == TradeOfferState.Active \
               and not _offer['is_our_offer']

    async def accept_donation_offers(_bot: Bot):

        log(f'In take_items for bot with id {_bot.id}:')

        steam_client = await get_bot_steam_client(_bot)

        offers = steam_client.get_trade_offers()

        for offer in offers['response']['trade_offers_received']:
            log(f'Incoming trade offers:\n{offer}')
            # если донат, то принимаем (так как при покупке от нас не требуется никаких предметов)
            if is_donation(offer):
                print(offer['items_to_receive'])
                steam_client.accept_trade_offer(offer['tradeofferid'])
                for key, value in offer['items_to_receive'].items():

                    group = await ItemGroup.objects.get(market_hash_name=value['market_hash_name'])
                    await group.update(to_order_amount=group.to_order_amount + 1)

        if offers['response']['trade_offers_received']:
            log('Inventory update:')
            await send_request_to_market(
                bot,
                'https://market.csgo.com/api/v2/update-inventory/',
                error_recursion=True
            )

    while True:

        bots = await Bot.objects.exclude(state='destroyed').all()
        for bot in bots:
            try:
                await accept_donation_offers(bot)
            except Exception as e:
                log(e, 'ERROR')
                continue

        await asyncio.sleep(30)


async def give_items():
    """
    Отправляем пользователю купленные у нас вещи.
    """

    async def send_trades(_bot: Bot):

        steam_client = await get_bot_steam_client(_bot)

        response = await send_request_to_market(
            _bot,
            'https://market.csgo.com/api/v2/trade-request-give-p2p-all',
            params={'key': _bot.secret_key},
            error_recursion=True,
            return_error=True
        )
        if 'error' in response:
            response['offers'] = []

        offers = response['offers']

        if offers:

            for offer in offers:
                try:
                    steam_client.make_offer_with_url(
                        message=offer['tradeoffermessage'],
                        items_from_me=[Asset(asset['assetid'], game) for asset in offer['items']],
                        items_from_them=[],
                        trade_offer_url=f"https://steamcommunity.com/tradeoffer/new/"
                                        f"?partner={offer['partner']}&token={offer['token']}"
                    )
                except Exception as _e:
                    log(_e, 'ERROR')

        log('Inventory update:')
        await send_request_to_market(
            bot,
            'https://market.csgo.com/api/v2/update-inventory/',
            error_recursion=True
        )

    while True:

        log('In give_items:')

        bots = await Bot.objects.exclude(state='destroyed').all()
        tasks = []
        for bot in bots:
            tasks.append(asyncio.create_task(send_trades(bot)))

        for task in tasks:
            await task

        await asyncio.sleep(30)
