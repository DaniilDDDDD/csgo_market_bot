import asyncio
from steampy.utils import GameOptions

from steampy.client import SteamClient, Asset, TradeOfferState

from .models import Bot, Item, ItemGroup

from .bot import bot_work, send_request_to_market, bot_balance, log, _delete_sale_offers, _delete_orders

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

        log('In bots_states_check')

        for bot in bots:
            log(f'Bot {bot.id}')
            if bot.state == 'circle_ended':
                await bot_work(bot)

            elif bot.state == 'sell':
                await ItemGroup.objects.filter(bot=bot).filter(state__in=['active', 'buy']).update(state='sell')

                await bot_work(bot)

            elif bot.state == 'buy':
                await ItemGroup.objects.filter(bot=bot).filter(state__in=['active', 'sell']).update(state='buy')

                await bot_work(bot)

            elif bot.state == 'hold':
                await ItemGroup.objects.filter(bot=bot).filter(state__in=['active', 'buy', 'sell']).update(state='hold')

                await bot_work(bot)

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
                        await Item.objects.filter(item_group=group).filter(state='ordered').all(),
                        group
                    ))

                    await task_delete_orders
                    await task_delete_sale_offers

                    await Item.objects.exclude(state='hold').delete(item_group=group)
                    await group.delete()

                await bot.delete()

        await asyncio.sleep(10)


async def update_orders_price():
    """
    Обновление цен на автоматическую покупку предмета:
    если появляется ордер от другого пользователя, который автоматически покупает предмет, но за большую сумму,
    то обновляему ордер, чтобы наш был дороже, дабы ордер был удовлетворён ранее
    """
    while True:

        log('In update_orders_price')

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
                if response['date']:
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
                    log('in update order')
                    response = await send_request_to_market(
                        item.item_group.bot,
                        f'https://market.csgo.com/api/UpdateOrder/'
                        f'{item.classid}/{item.instanceid}/{best_offer + 1}/',
                        return_error=True
                    )
                    if 'error' in response:
                        log(f'order with item with id {item.id} can not be changed now')
                        continue
                    await item.update(ordered_for=(best_offer + 1), sell_for=item.sell_for)

            except Exception as e:
                log(e)
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
                for key, value in offer['items_to_receive'].items():
                    # обновляем базу данных, выставляя статусы для купленных вещей
                    # (for_sale, потому что продаются лишь обмениваемые вещи)
                    item = await Item.objects.select_related(Item.item_group).get_or_none(
                        classid=value['classid'], instanceid=value['instanceid']
                    )
                    if item:
                        await item.item_group.update(to_order_amount=item.item_group.to_order_amount + 1)
                        await item.update(state='for_sale')
                        await send_request_to_market(
                            bot,
                            f'https://market.csgo.com/api/ProcessOrder/{item.classid}/{item.instanceid}/0/',
                            return_error=True,
                            error_recursion=True
                        )

        if offers['response']['trade_offers_received']:
            log('Inventory update')
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
                log(e)
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

            # обновляем статусы проданых (переданных) предметов
            response = await send_request_to_market(
                _bot,
                'https://market.csgo.com/api/v2/items',
                error_recursion=True
            )

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

            for item in response.get('items', []):
                if item.get('status') == '2':
                    await Item.objects.delete(
                        classid=item.get('classid'),
                        instanceid=item.get('instanceid'),
                        market_hash_name=item.get('market_hash_name')
                    )

        log('Inventory update')
        await send_request_to_market(
            bot,
            'https://market.csgo.com/api/v2/update-inventory/',
            error_recursion=True
        )

    while True:

        log('In give_items')

        bots = await Bot.objects.exclude(state='destroyed').all()
        tasks = []
        for bot in bots:
            tasks.append(asyncio.create_task(send_trades(bot)))

        for task in tasks:
            await task

        await asyncio.sleep(30)
