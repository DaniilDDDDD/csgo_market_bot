import asyncio
import requests
from typing import List
from steampy.utils import GameOptions

from steampy.client import SteamClient, Asset, TradeOfferState

from .models import Bot, Item, ItemGroup

from .bot import bot_work, send_request_until_success, bot_balance

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
    steam_client = get_bot_steam_client(bot)
    steam_client.logout()
    steam_clients.pop(bot.id)
    groups = await ItemGroup.objects.filter(bot=bot).all()
    await Item.objects.delete(item_group__in=groups)
    await ItemGroup.objects.delete(bot=bot)
    await send_request_until_success(
        bot,
        'https://market.csgo.com/api/v2/go-offline'
    )
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
    items = await Item.objects.filter(state='ordered').all()

    for item in items:

        response = await send_request_until_success(
            item.item_group.bot,
            f'https://market.csgo.com/api/BestBuyOffer/{item.classid}_{item.instanceid}/'
        )

        if response.get('best_offer') > item.ordered_for \
                and (response.get('best_offer') + 1) < item.sell_for * 0.90 \
                and (response.get('best_offer') + 1) < await bot_balance(item.item_group.bot):
            await send_request_until_success(
                item.item_group.bot,
                f'https://market.csgo.com/api/UpdateOrder/'
                f'{item.classid}/{item.instanceid}/{response.get("best_offer") + 1}/'
            )
            await item.update(ordered_for=(response.get("best_offer") + 1))

    await asyncio.sleep(10)


def get_bot_steam_client(bot: Bot) -> SteamClient:
    """
    Получение steam-клиента, работающего с данными бота.
    """
    if bot.id in steam_clients:
        return steam_clients[bot.id]
    else:
        steam_client = SteamClient(bot.api_key)
        steam_client.login(
            bot.username,
            bot.password,
            bot.steamguard_file
        )
        steam_clients[bot.id] = steam_client
        return steam_client


async def trades_confirmation():
    """
    Проход по всем Item и подтверждение обмена при наличии ссылки на обмен.
    Ссылка не трейд не нужна, так как бот маркета сам предлагает обмен.
    """

    while True:
        bots = await Bot.objects.exclude(state='destroyed').all()
        tasks = []
        for bot in bots:
            tasks.append(asyncio.create_task(give_items(bot)))
            tasks.append(asyncio.create_task(take_items(bot)))
            await asyncio.sleep(30)

        for task in tasks:
            await task


async def take_items(bot: Bot):
    """
    Принимаем трейды с купленными нами вещами
    """

    def is_donation(_offer: dict) -> bool:
        return _offer.get('items_to_receive') \
               and not _offer.get('items_to_give') \
               and _offer['trade_offer_state'] == TradeOfferState.Active \
               and not _offer['is_our_offer']

    steam_client = get_bot_steam_client(bot)

    offers = steam_client.get_trade_offers()
    for offer in offers['response']['trade_offers_received']:
        # если донат, то принимаем (так как при покупке от нас не требуется никаких предметов)
        if is_donation(offer):
            steam_client.accept_trade_offer(offer['tradeofferid'])
            for i in offer['items_to_receive']:
                # обновляем базу данных, выставляя статусы для купленных вещей
                # (for_sale, потому что продаются лишь обмениваемые вещи)
                item = await Item.objects.get(classid=i['classid'], instanceid=i['instanceid'])
                if item:
                    await item.update(state='for_sale')


async def give_items(bot: Bot):
    """
    Отправляем пользователю купленные у нас вещи.
    """
    steam_client = get_bot_steam_client(bot)

    response = await send_request_until_success(
        bot,
        'https://market.csgo.com/api/v2/trade-request-give-p2p-all'
    )
    offers = response.get('offers')

    for offer in offers:
        steam_client.make_offer_with_url(
            message=offer['tradeoffermessage'],
            items_from_me=[Asset(asset['assetid'], game) for asset in offer['items']],
            items_from_them=[],
            trade_offer_url=f"https://steamcommunity.com/tradeoffer/new/"
                            f"?partner={offer['partner']}&token={offer['token']}"
        )

    response = await send_request_until_success(
        bot,
        'https://market.csgo.com/api/v2/items'
    )

    for item in response.get('items', []):
        if item.get('status') == '2':
            _item = await Item.objects.get(classid=item.get('classid'), instanceid=item.get('instanceid'))
            await _item.update(state='for_buy')
