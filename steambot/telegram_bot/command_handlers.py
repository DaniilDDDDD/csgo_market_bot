import os
import pathlib
import json
import asyncio
from dotenv import load_dotenv

from telegram.ext import CommandHandler

from market.models import Bot, ItemGroup, Item
from market.bot import send_request_until_success, hold_item

load_dotenv()

bot_name = os.environ.get('BOT_NAME')
basedir = pathlib.Path(__file__).parent.parent.absolute()


def check_args(context, update, arguments: dict):
    try:
        for arg in context.args:
            key_value = arg.partition('=')
            assert key_value[0] != '' and key_value[2] != ''
            key, value = key_value[0], key_value[2]
            if key in arguments:
                arguments[key] = value

        for key, value in arguments.items():
            assert value != '--'

        return arguments
    except AssertionError:
        context.bot.send_message(chat_id=update.effective_chat.id, text='Wrong arguments passed!')
        return None


def help(update, context):
    """
/help
    Документация бота.
    """

    result = f'Документация Бота {bot_name}.\n'
    result += 'Все функции принимают аргументы в виде <key>=<value>.\n'

    result += help.__doc__
    result += market_bot_inventory.__doc__

    result += list_bot.__doc__
    result += create_bot.__doc__
    result += set_bot_status.__doc__

    result += list_item_group.__doc__
    result += create_item_group.__doc__
    result += set_item_group_state.__doc__

    result += list_item.__doc__
    result += add_item_to_group.__doc__
    result += set_item_state.__doc__

    context.bot.send_message(chat_id=update.effective_chat.id, text=result)


def start(update, context):
    context.bot.send_message(chat_id=update.effective_chat.id, text="I'm bot that abusing market.csgo!")


def market_bot_inventory(update, context):
    """
/market_bot_inventory
    Инвентарь, полученный с маркета.
    Аргументы:
        <id> - id бота.
    """

    async def get_bot(id: int) -> Bot:
        _bot = await Bot.objects.get(id=id)
        assert _bot
        return _bot

    arguments = {
        'id': '--'
    }
    arguments = check_args(context, update, arguments)
    if not arguments:
        return

    try:
        bot = asyncio.run(get_bot(**arguments))
    except AssertionError:
        context.bot.send_message(chat_id=update.effective_chat.id, text='Bot with this "id" does not exists!')
        return

    response = asyncio.run(send_request_until_success(
        bot,
        'https://market.csgo.com/api/v2/my-inventory/'
    )).json()
    context.bot.send_message(chat_id=update.effective_chat.id, text=response.get('items'))


def list_bot(update, context):
    """
/list_bot
    Список всех ботов.
    """

    bots = asyncio.run(Bot.objects.all())

    if not bots:
        context.bot.send_message(chat_id=update.effective_chat.id, text='Ботов нет.')
        return

    result = 'Все боты:\n\n'
    for bot in bots:
        result += str(bot) + '\n\n'

    context.bot.send_message(chat_id=update.effective_chat.id, text=result)


def create_bot(update, context):
    """
/create_bot
    Создание бота.
    Аргументы:
        <api_key>- api ключ аккаунта,
        <username> - username аккаунта,
        <password> - password аккаунта,
        <steamid> - steamid аккаунта,
        <shared_secret> - секрет из steam guard authenticator,
        <identity_secret> - секрет из steam guard authenticator
        <description> - описание бота.
    """

    async def create_bot_in_db(
            api_key: str,
            username: str,
            password: str,
            steamguard_file: str,
            description: str
    ) -> Bot:
        _bot = await Bot.objects.get_or_create(
            api_key=api_key,
            username=username,
            password=password,
            steamguard_file=steamguard_file,
            state='paused',
            description=description
        )
        return _bot

    arguments = {
        'api_key': '--',
        'username': '--',
        'password': '--',
        'steamid': '--',
        'shared_secret': '--',
        'identity_secret': '--',
        'description': 'Some csgo.market bot.'
    }
    arguments = check_args(context, update, arguments)
    if not arguments:
        return

    bot = asyncio.run(create_bot_in_db(
        api_key=arguments['api_key'],
        username=arguments['username'],
        password=arguments['password'],
        steamguard_file=f'{basedir}/steam_guards/steam_guard_{arguments["steamid"]}.json',
        description=arguments['description']
    ))

    data = {
        "steamid": arguments['steamid'],
        "shared_secret": arguments['shared_secret'],
        "identity_secret": arguments['identity_secret']
    }
    with open(bot.steamguard_file, "w", encoding="utf-8") as file:
        json.dump(data, file)

    context.bot.send_message(chat_id=update.effective_chat.id, text=str(bot))


def set_bot_status(update, context):
    """
/set_bot_status
    Установко боту нового статуса.
    Принимает два аргумента:
        <id> - id бота,
        <state> - новый статус бота.
    """

    async def change_bot_state_in_db(id: int, state: str):
        _bot = await Bot.objects.get(id=id)
        assert _bot
        await _bot.update(state=state)
        return _bot

    arguments = {
        'id': '--',
        'state': '--'
    }

    arguments = check_args(context, update, arguments)
    if not arguments:
        return

    try:
        bot = asyncio.run(change_bot_state_in_db(**arguments))
    except AssertionError:
        context.bot.send_message(chat_id=update.effective_chat.id, text='Bot with this "id" does not exists!')
        return

    context.bot.send_message(chat_id=update.effective_chat.id, text=str(bot))


def list_item_group(update, context):
    """
/list_item_group
    Список групп предметов.
    """
    item_groups = asyncio.run(ItemGroup.objects.all())

    if not item_groups:
        context.bot.send_message(chat_id=update.effective_chat.id, text='Групп предметов нет.')
        return

    result = 'Все группы предметов:\n\n'
    for item_group in item_groups:
        result += str(item_group) + '\n\n'

    context.bot.send_message(chat_id=update.effective_chat.id, text=result)


def create_item_group(update, context):
    """
/create_item_group
    Создание группы предметов.
    Принимает аргументыЖ
        <bot> - id бота, которому принадлежит данная группа,
        <state> - состояние ('active' по умолчанию),
        <market_hash_name> - хэш-название предмета с маркета,
        <classid> - classid предмета,
        <instanceid> - instanceid предмета,
        <amount> - количество предметов в обороте
        <buy_for> - цена покупки предмета из этой грцппы,
        <sell_for> - цена продажи предмета из этой грцппы.
    """

    async def create_item_group_in_db(
            bot: int,
            amount: int,
            buy_for: int,
            sell_for: int,
            classid: int,
            instanceid: int,
            market_hash_name: str = '',
            state: str = 'active'
    ) -> ItemGroup:
        _bot = await Bot.objects.get(id=bot)
        assert _bot
        _group = await ItemGroup.objects.get_or_create(
            bot=_bot,
            state=state,
            market_hash_name=market_hash_name,
            classid=classid,
            instanceid=instanceid
        )
        assert _group
        for i in range(int(amount)):
            _item = await Item.objects.create(
                item_group=_group,
                buy_for=buy_for,
                sell_for=sell_for,
                state='for_buy',
                market_hash_name=market_hash_name,
                classid=classid,
                instanceid=instanceid
            )
            assert _item
        return _group

    arguments = {
        'bot': '--',
        'state': 'disabled',
        'amount': '--',
        'buy_for': '--',
        'sell_for': '--',
        'market_hash_name': None,
        'classid': None,
        'instanceid': None
    }
    arguments = check_args(context, update, arguments)
    if not arguments:
        return

    group = asyncio.run(create_item_group_in_db(**arguments))

    context.bot.send_message(chat_id=update.effective_chat.id, text=str(group))


def set_item_group_state(update, context):
    """
/set_item_group_state
    Установка группе предметов нового статуса.
    Принимает два аргумента:
        <id> - id бота,
        <state> - новый статус бота.
    """

    async def set_item_group_state_in_db(id: int, state: str) -> ItemGroup:
        _group = await ItemGroup.objects.get(id=id)
        assert _group
        await _group.update(state=state)
        return _group

    arguments = {
        'id': '--',
        'state': '--'
    }
    arguments = check_args(context, update, arguments)
    if not arguments:
        return

    try:
        group = asyncio.run(set_item_group_state_in_db(**arguments))
    except AssertionError:
        context.bot.send_message(chat_id=update.effective_chat.id, text='Item group with this "id" does not exists!')
        return

    context.bot.send_message(chat_id=update.effective_chat.id, text=str(group))


def list_item(update, context):
    """
/list_item
    Список всех предметов.
    """

    items = asyncio.run(Item.objects.all())

    if not items:
        context.bot.send_message(chat_id=update.effective_chat.id, text='Предметов нет.')
        return

    result = 'Все предметы:\n\n'
    for item in items:
        result += str(item) + '\n\n'

    context.bot.send_message(chat_id=update.effective_chat.id, text=result)


def add_item_to_group(update, context):
    """
/add_item_to_group
    Добавляет предмет к группе.
    Принимает аргументы:
        <item_group> - группа предметов,
        <state> - статус,
        <buy_for> - за столько покупать предмет,
        <sell_for> - за столько подавать предмет,
        <market_id> - id конкретного предемета с маркета,
        <market_hash_name> - имя предмета,
        <classid> - classid предмета,
        <instanceid> - instance id предмета.
    """

    async def create_item_in_db(
            item_group: int,
            buy_for: int,
            sell_for: int,
            state: str,
            market_id: int = None,
            market_hash_name: str = None,
            classid: int = None,
            instanceid: int = None
    ) -> Item:
        _group = await ItemGroup.objects.get(id=item_group)
        assert _group
        _item = await Item.objects.get_or_create(
            item_group=_group,
            state=state,
            buy_for=buy_for,
            sell_for=sell_for,
            market_id=market_id,
            market_hash_name=market_hash_name,
            classid=classid,
            instanceid=instanceid
        )
        return _item

    arguments = {
        'item_group': '--',
        'state': 'hold',
        'buy_for': '--',
        'sell_for': '--',
        'market_id': None,
        'market_hash_name': None,
        'classid': None,
        'instanceid': None
    }
    arguments = check_args(context, update, arguments)
    if not arguments:
        return

    if arguments['market_id'] == '':
        arguments.pop('market_id')

    try:
        item = asyncio.run(create_item_in_db(**arguments))
    except AssertionError:
        context.bot.send_message(chat_id=update.effective_chat.id, text='Item group with this "id" does not exists!')
        return

    context.bot.send_message(chat_id=update.effective_chat.id, text=str(item))


def set_item_state(update, context):
    """
/set_item_state
    Установка предмету новыого статуса.
    Принимает аргументы:
        <id> - id бота,
        <state> - новый статус бота.
    """

    arguments = {
        'id': '--',
        'state': '--'
    }
    arguments = check_args(context, update, arguments)
    if not arguments:
        return

    try:
        item = asyncio.run(Item.objects.get(id=arguments['id']))
        assert item
    except AssertionError:
        context.bot.send_message(chat_id=update.effective_chat.id, text='Item with this "id" does not exists!')
        return

    if arguments['state'] == 'hold':
        asyncio.run(hold_item(item))
    context.bot.send_message(chat_id=update.effective_chat.id, text=str(item))


start_handler = CommandHandler('start', start)
help_handler = CommandHandler('help', help)
market_bot_inventory_handler = CommandHandler('market_bot_inventory', market_bot_inventory)

list_bot_handler = CommandHandler('list_bot', list_bot)
create_bot_handler = CommandHandler('create_bot', create_bot)
set_bot_status_handler = CommandHandler('set_bot_status', set_bot_status)

list_item_group_handler = CommandHandler('list_item_group', list_item_group)
create_item_group_handler = CommandHandler('create_item_group', create_item_group)
set_item_group_state_handler = CommandHandler('set_item_group_state', set_item_group_state)

list_item_handler = CommandHandler('list_item', list_item)
add_item_to_group_handler = CommandHandler('add_item_to_group', add_item_to_group)
set_item_state_handler = CommandHandler('set_item_state', set_item_state)
