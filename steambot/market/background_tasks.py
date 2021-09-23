import asyncio
from steampy.utils import GameOptions

from steampy.client import SteamClient, Asset, TradeOfferState

from .models import Bot, Item, ItemGroup

from .bot import bot_work, send_request_to_market, bot_balance, log

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

        bots = await Bot.objects.exclude(state__in=['in_circle', 'paused']).all()

        tasks = []

        for bot in bots:
            if bot.state == 'circle_ended':
                tasks.append(asyncio.create_task(bot_work(bot)))

            if bot.state == 'sell':
                # меняем статусы, делаем один оборот и уходим на паузу
                tasks.append(asyncio.create_task(bot_sell(bot)))
                tasks.append(asyncio.create_task(bot_work(bot)))
                await bot.update(state='paused')

            if bot.state == 'buy':
                # меняем статусы, делаем один оборот и уходим на паузу
                tasks.append(asyncio.create_task(bot_buy(bot)))
                tasks.append(asyncio.create_task(bot_work(bot)))
                await bot.update(state='paused')

            if bot.state == 'hold':
                # меняем статусы, делаем один оборот и уходим на паузу
                tasks.append(asyncio.create_task(bot_hold(bot)))
                tasks.append(asyncio.create_task(bot_work(bot)))
                await bot.update(state='paused')

            if bot.state == 'destroy':
                await bot.update(state='destroyed')

            if bot.state == 'destroyed':
                tasks.append(asyncio.create_task(bot_delete(bot)))

        for task in tasks:
            await task


async def bot_delete(bot: Bot):
    steam_client = await get_bot_steam_client(bot)
    steam_client.logout()
    steam_clients.pop(bot.id)
    groups = await ItemGroup.objects.filter(bot=bot).all()
    await Item.objects.delete(item_group__in=groups)
    await ItemGroup.objects.delete(bot=bot)
    try:
        await send_request_to_market(
            bot,
            'https://market.csgo.com/api/v2/go-offline'
        )
    except Exception as e:
        # при отсутствии запростов бот автоматически уйдёт в оффлайн через 3 минуты
        log(e)

    await bot.delete()


async def bot_sell(bot: Bot):
    groups = await ItemGroup.objects.filter(bot=bot).filter(state__in=['active', 'buy']).all()
    for group in groups:
        await group.update(state='sell')


async def bot_buy(bot: Bot):
    groups = await ItemGroup.objects.filter(bot=bot).filter(state__in=['active', 'sell']).all()
    for group in groups:
        await group.update(state='buy')


async def bot_hold(bot: Bot):
    groups = await ItemGroup.objects.filter(bot=bot).filter(state__in=['active', 'buy', 'sell']).all()
    for group in groups:
        await group.update(state='hold')


async def update_orders_price():
    """
    Обновление цен на автоматическую покупку предмета:
    если появляется ордер от другого пользователя, который автоматически покупает предмет, но за большую сумму,
    то обновляему ордер, чтобы наш был дороже, дабы ордер был удовлетворён ранее
    """
    while True:
        items = await Item.objects.select_related(Item.item_group.bot).filter(state='ordered').all()
        await asyncio.sleep(10)

        for item in items:

            try:
                response = await send_request_to_market(
                    item.item_group.bot,
                    f'https://market.csgo.com/api/BestBuyOffer/{item.classid}_{item.instanceid}/'
                )
                best_offer = int(response.get('best_offer'))

                if (
                        best_offer >= item.ordered_for
                        and (best_offer + 1) < item.sell_for * 0.90
                        and (best_offer + 1) < await bot_balance(item.item_group.bot) * 100
                ) or (
                        # если цена продажи предмета более 500 рублей, то при отмене самого большого ордера на продажу,
                        # исходящего не от нас и отличающегося от нашего холтя бы на 3%,
                        # сменяем цену на цену этого ордера + 1
                        item.ordered_for - best_offer > item.sell_for * 0.03
                        and item.sell_for > 50000
                ):
                    response = await send_request_to_market(
                        item.item_group.bot,
                        f'https://market.csgo.com/api/UpdateOrder/'
                        f'{item.classid}/{item.instanceid}/{best_offer + 1}/',
                        return_error=True
                    )
                    if 'error' in response:
                        log(f'order with item with id {item.id} can not be changed now')
                        await asyncio.sleep(20)
                        continue
                    await item.update(ordered_for=(best_offer + 1))

            except Exception as e:
                log(e)
                await asyncio.sleep(10)
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
            log(e)
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

        log(f'In take_items for bot with id {_bot.id}')

        steam_client = await get_bot_steam_client(_bot)

        offers = steam_client.get_trade_offers()

        for offer in offers['response']['trade_offers_received']:
            log(offer)
            # если донат, то принимаем (так как при покупке от нас не требуется никаких предметов)
            if is_donation(offer):
                steam_client.accept_trade_offer(offer['tradeofferid'])
                for i in offer['items_to_receive']:
                    # обновляем базу данных, выставляя статусы для купленных вещей
                    # (for_sale, потому что продаются лишь обмениваемые вещи)
                    item = await Item.objects.get(classid=i['classid'], instanceid=i['instanceid'])
                    if item:
                        await item.update(state='for_sale')

    while True:

        bots = await Bot.objects.exclude(state='destroyed').all()
        for bot in bots:
            await accept_donation_offers(bot)

        log('Inventory update')

        for bot in bots:
            await send_request_to_market(
                bot,
                'https://market.csgo.com/api/v2/update-inventory/',
                error_recursion=True
            )

        await asyncio.sleep(30)


async def give_items():
    """
    Отправляем пользователю купленные у нас вещи.
    """

    async def send_trades(_bot: Bot):
        log('In give_items')

        steam_client = await get_bot_steam_client(_bot)

        # используется отдельный запрос к market.csgo, так как при отсутствии предметоа на передачу возвращается ошибка

        response = await send_request_to_market(
            _bot,
            'https://market.csgo.com/api/v2/trade-request-give-p2p-all',
            params={'key': _bot.secret_key},
            error_recursion=True
        )
        if 'error' in response:
            response['offers'] = []

        log(response)
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
                    log(_e)
                    continue

            # обновляем статусы проданых (переданных) предметов
            try:
                response = await send_request_to_market(
                    _bot,
                    'https://market.csgo.com/api/v2/items',
                    error_recursion=True
                )

                for item in response.get('items', []):
                    if item.get('status') == '2':
                        _item = await Item.objects.get(classid=item.get('classid'), instanceid=item.get('instanceid'))
                        await _item.update(state='for_buy')
            except Exception as _e:
                log(_e)

    while True:

        bots = await Bot.objects.exclude(state='destroyed').all()
        for bot in bots:
            await send_trades(bot)

        log('Inventory update')
        for bot in bots:
            await send_request_to_market(
                bot,
                'https://market.csgo.com/api/v2/update-inventory/',
                error_recursion=True
            )

        await asyncio.sleep(30)
