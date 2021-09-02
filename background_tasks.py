import asyncio
import requests
from typing import List
from sqlalchemy.sql.elements import Null

from steampy.client import SteamClient

from .models import Bot, Item, ItemGroup

from .bot import bot_work


async def bots_states_check():
    '''
    Отсюда происходит запуск раскручивания ботов:
    Если у бота статус 'in_circle' или 'paused', то его не трогаем;
    Если у бота статус 'circle_ended', то запускаем его следующий оборот;
    Если у бота статус 'destroy', то бот подготавливается к удалению из базы данных вместе с его группами предметов;
    Если у бота статус 'destroyed', то бот удаляется из базы данных вместе с его группами предметов;
    Если у бота статус 'sell', то у всех его групп предметов ставится статус 'sell';
    Если у бота статус 'buy', то у всех его групп предметов ставится статус 'buy'.
    '''
    while True:

        bots = await Bot.objects.exclude(state__in=['in_circle', 'paused']).all()

        tasks = []

        for bot in bots:
            if bot.state == 'circle_ended':
                tasks.append(asyncio.create_task(bot_work(bot)))

            if bot.state == 'sell':
                tasks.append(asyncio.create_task(bot_sell(bot)))
                bot.state = 'paused'

            if bot.state == 'buy':
                tasks.append(asyncio.create_task(bot_buy(bot)))
                bot.state = 'paused'

            if bot.state == 'destroy':
                bot.state = 'destroyed'

            if bot.state == 'destroyed':
                tasks.append(asyncio.create_task(bot_delete(bot)))
            
        for task in tasks:
            await task
                
            

async def bot_delete(bot: Bot):
    steam_client = get_bot_steam_client(bot)
    steam_client.logout()
    groups = await ItemGroup.objects.filter(bot=bot).all()
    await Item.objects.delete(item_group__in=groups)
    await ItemGroup.objects.delete(bot=bot)
    await bot.delete()

async def bot_sell(bot: Bot):
    groups = await ItemGroup.objects.filter(bot=bot).filter(state__in=['active', 'buy']).all()
    for group in groups:
        group.state = 'sell'

async def bot_buy(bot: Bot):
    groups = await ItemGroup.objects.filter(bot=bot).filter(state__in=['active', 'sell']).all()
    for group in groups:
        group.state = 'buy'




steam_clients = {}

def get_bot_steam_client(bot: Bot) -> SteamClient:
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
    '''
    Проход по всем Item и подтверждение обмена при наличии ссылки на обмен.
    Ссылка не трейд не нужна, так как бот маркета сам предлагает обмен.
    '''
    while True:
        bots = await Bot.objects.exclude(state='destroyed').all()
        pass


async def give_items(bot: Bot):
    '''
    Отдаём боту маркета купленные у нас вещи.
    '''
    while True:
        
        success = False
        response = ''
        while not success:
            url = 'https://market.csgo.com/api/v2/trade-request-give'
            params = {
                'key': bot.api_key
            }
            response = requests.get(url=url, params=params).json()
            success = response.get('success', False)
            if not success:
                await asyncio.sleep(10)

        steam_client = get_bot_steam_client(bot)
        try:
            # TODO: добавить защиту от попытки получить лишние предметы (т.к. отдаём боту маркета, то пока не страшно)
            steam_client.accept_trade_offer(response.get('trade', ''))

            # обновляем инвентарь
            success = False
            response = ''
            while not success:
                url = 'https://market.csgo.com/api/v2/update-inventory/'
                params = {
                    'key': bot.api_key
                }
                response = requests.get(url=url, params=params).json()
                success = response.get('success', False)
                if not success:
                    await asyncio.sleep(10)

        except Exception:
            continue

        items = Item.objects.filter(market_id__in=response.get('items', [])).all()

        for item in items:
            item.market_id = None
            item.state = 'for_buy'

        await asyncio.sleep(60)


async def take_items(bot: Bot):
    '''
    Принимаем от бота купленныен нами вещи.
    '''
    while True:

        success = False
        response = ''
        while not success:
            url = 'https://market.csgo.com/api/v2/trade-request-take'
            params = {
                'key': bot.api_key
            }
            response = requests.get(url=url, params=params).json()
            success = response.get('success', False)
            if not success:
                await asyncio.sleep(10)
        
        steam_client = get_bot_steam_client(bot)
        try:
            # TODO: добавить защиту от попытки получить лишние предметы (т.к. отдаём боту маркета, то пока не страшно)
            steam_client.accept_trade_offer(response.get('trade', ''))

            # обновляем инвентарь
            success = False
            response = ''
            while not success:
                url = 'https://market.csgo.com/api/v2/update-inventory/'
                params = {
                    'key': bot.api_key
                }
                response = requests.get(url=url, params=params).json()
                success = response.get('success', False)
                if not success:
                    await asyncio.sleep(10)

        except Exception:
            continue
            
        await update_bought_items(response.get('items', []))

        await asyncio.sleep(60)


async def update_bought_items(items: List[str]):
    
    for elem in items:
        class_id, instance_id = elem.partition('_')[0], elem.partition('_')[2]

        item = Item.objects.filter(class_id=class_id).filter(instance_id=instance_id).all()
        pass
