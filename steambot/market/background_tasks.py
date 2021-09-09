import asyncio
from typing import List

from steampy.client import SteamClient

from .models import Bot, Item, ItemGroup

from .bot import bot_work, send_request_until_success, bot_balance

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
                tasks.append(asyncio.create_task(bot_sell(bot)))
                await bot.update(state='paused')

            if bot.state == 'buy':
                tasks.append(asyncio.create_task(bot_buy(bot)))
                await bot.update(state='paused')

            if bot.state == 'hold':
                tasks.append(asyncio.create_task(bot_hold(bot)))
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

        for task in tasks:
            await task


async def give_items(bot: Bot):
    """
    Отдаём боту маркета купленные у нас вещи.
    """

    while True:

        response = await send_request_until_success(
            bot,
            'https://market.csgo.com/api/v2/trade-request-give'
        )

        steam_client = get_bot_steam_client(bot)
        try:
            # TODO: добавить защиту от попытки получить лишние предметы (т.к. отдаём боту маркета, то пока не страшно)
            steam_client.accept_trade_offer(response.get('trade', ''))

            # обновляем инвентарь

            await send_request_until_success(
                bot,
                'https://market.csgo.com/api/v2/update-inventory/'
            )

        except Exception:
            continue

        items = await Item.objects.filter(market_id__in=response.get('items', [])).all()

        for item in items:
            await item.update(state='for_buy', market_id=None)

        await asyncio.sleep(60)


async def take_items(bot: Bot):
    """
    Принимаем от бота купленнын нами вещи.
    """
    while True:

        inventory_before_update = await send_request_until_success(
            bot,
            'https://market.csgo.com/api/v2/my-inventory/'
        ).get('items', [])

        response = await send_request_until_success(
            bot,
            'https://market.csgo.com/api/v2/trade-request-take'
        )

        steam_client = get_bot_steam_client(bot)
        try:
            # TODO: добавить защиту от попытки получить лишние предметы (т.к. отдаём боту маркета, то пока не страшно)
            steam_client.accept_trade_offer(response.get('trade', ''))

            # обновляем инвентарь
            await send_request_until_success(
                bot,
                'https://market.csgo.com/api/v2/update-inventory/'
            )

        except Exception:
            continue

        await update_bought_items(bot, response.get('items', []), inventory_before_update)

        await asyncio.sleep(60)


async def update_bought_items(bot: Bot, items: List[str], inventory_before_update: List[dict]):
    """
    Проставляем market_id и market_hash_name для каждой полученной вещи (Item).
    Обновляем статусы.
    """

    inventory = await send_request_until_success(
        bot,
        'https://market.csgo.com/api/v2/my-inventory/'
    ).get('items', [])

    for elem in inventory:
        for e in inventory_before_update:
            if e['id'] == elem['id']:
                elem = None

    added_items = [item for item in inventory if item is not None]

    for elem in items:
        class_id, instance_id = int(elem.partition('_')[0]), int(elem.partition('_')[2])

        # объект единственный так как более одной вещи за раз заказать нельзя
        item = await Item.objects.filter(state='ordered').filter(class_id=class_id).filter(
            instance_id=instance_id).first()

        await item.update(ordered_for=item.buy_for)

        for i in range(len(added_items)):
            if added_items[i]['classid'] == item.classid and added_items[i]['instanceid'] == item.instanceid:
                await item.update(
                    market_id=added_items[i]['id'],
                    market_hash_name=added_items[i]['market_hash_name']
                )
                added_items.pop(i)
