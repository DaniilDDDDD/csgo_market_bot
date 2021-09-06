import os
import pathlib
import json
import asyncio
from dotenv import load_dotenv

from telegram.ext import CommandHandler

from market.models import Bot, ItemGroup, Item

load_dotenv()

bot_name = os.environ.get('BOT_NAME')
basedir = pathlib.Path(__file__).parent.parent.absolute()


def check_args(context_arguments: dict, arguments: dict):
    for arg in context_arguments:
        key_value = arg.partition('=')
        assert key_value[0] != '' and key_value[2] != ''
        key, value = key_value[0], key_value[2]
        if key in arguments:
            arguments[key] = value

    for key, value in arguments.items():
        assert value


def help(update, context):
    """
/help
    Документация бота.
    """

    result = f'Документация Бота {bot_name}.\n'
    result += 'Все функции принимают аргументы в виде <key>=<value>.\n'

    result += help.__doc__
    result += create_bot.__doc__
    result += set_bot_status.__doc__
    result += create_item_group.__doc__
    result += set_item_group_state.__doc__
    result += add_item_to_group.__doc__

    context.bot.send_message(chat_id=update.effective_chat.id, text=result)


def start(update, context):
    context.bot.send_message(chat_id=update.effective_chat.id, text="I'm bot that abusing market.csgo!")


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
            state='created',
            description=description
        )
        return _bot

    arguments = {
        'api_key': None,
        'username': None,
        'password': None,
        'steamid': None,
        'shared_secret': None,
        'identity_secret': None,
        'description': 'Some csgo.market bot.'
    }
    try:
        check_args(context.args, arguments)
    except AssertionError:
        context.bot.send_message(chat_id=update.effective_chat.id, text='Wrong arguments passed!')
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

    # TODO: Переделать возвращаемую информацию
    context.bot.send_message(chat_id=update.effective_chat.id, text=bot.json())


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
        _bot.state = state
        return _bot

    arguments = {
        'id': None,
        'state': None
    }

    try:
        check_args(context.args, arguments)
    except AssertionError:
        context.bot.send_message(chat_id=update.effective_chat.id, text='Wrong arguments passed!')
        return

    try:
        bot = asyncio.run(change_bot_state_in_db(**arguments))
    except AssertionError:
        context.bot.send_message(chat_id=update.effective_chat.id, text='Bot with this "id" does not exists!')
        return

    # TODO: Переделать возвращаемую информацию
    context.bot.send_message(chat_id=update.effective_chat.id, text=bot.json())


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

    async def create_item_graip_in_db(
            bot: Bot,
            amount: int,
            buy_for: int,
            sell_for: int,
            classid: int,
            instanceid: int,
            market_hash_name: str = '',
            state: str = 'active'
    ) -> ItemGroup:
        _group = await ItemGroup.objects.get_or_create(
            bot=bot,
            state=state,
            market_hash_name=market_hash_name,
            classid=classid,
            instanceid=instanceid
        )

        for i in range(amount):
            await Item.objects.get_or_create(
                item_group=_group,
                buy_for=buy_for,
                sell_for=sell_for,
                state='for_buy',
                market_hash_name=market_hash_name,
                classid=classid,
                instanceid=instanceid
            )
        return _group

    arguments = {
        'bot': None,
        'state': 'disabled',
        'amount': None,
        'buy_for': None,
        'sell_for': None,
        'market_hash_name': '',
        'classid': None,
        'instanceid': None
    }
    try:
        check_args(context.args, arguments)
    except AssertionError:
        context.bot.send_message(chat_id=update.effective_chat.id, text='Wrong arguments passed!')
        return

    group = asyncio.run(create_item_graip_in_db(**arguments))
    # TODO: Переделать возвращаемую информацию
    context.bot.send_message(chat_id=update.effective_chat.id, text=group.json())


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
        _group.state = state
        return _group

    arguments = {
        'id': None,
        'state': None
    }
    try:
        check_args(context.args, arguments)
    except AssertionError:
        context.bot.send_message(chat_id=update.effective_chat.id, text='Wrong arguments passed!')
        return

    try:
        group = asyncio.run(set_item_group_state_in_db(**arguments))
    except AssertionError:
        context.bot.send_message(chat_id=update.effective_chat.id, text='Item group with this "id" does not exists!')
        return

    # TODO: Переделать возвращаемую информацию
    context.bot.send_message(chat_id=update.effective_chat.id, text=group.json())


def add_item_to_group(update, context):
    """
/add_item_to_group
    Добавляет предмет к группе.
    Принимает аргументы:
        <item_group> - ,
        <state> - ,
        <buy_for> - ,
        <sell_for> - ,
        <market_id> - ,
    """

    async def create_item_in_db(
            item_group: int,
            buy_for: int,
            sell_for: int,
            state: str,
            market_id: int = None
    ) -> Item:
        _group = await ItemGroup.objects.get(id=item_group)
        assert _group
        _item = await Item.objects.get_or_create(
            state=state,
            buy_for=buy_for,
            sell_for=sell_for,
            market_id=market_id
        )
        return _item

    arguments = {
        'item_group': None,
        'state': 'hold',
        'buy_for': None,
        'sell_for': None,
        'market_id': ''
    }
    try:
        check_args(context.args, arguments)
    except AssertionError:
        context.bot.send_message(chat_id=update.effective_chat.id, text='Wrong arguments passed!')
        return

    if arguments['market_id'] == '':
        arguments.pop('market_id')

    try:
        item = asyncio.run(create_item_in_db(**arguments))
    except AssertionError:
        context.bot.send_message(chat_id=update.effective_chat.id, text='Item group with this "id" does not exists!')
        return

    context.bot.send_message(chat_id=update.effective_chat.id, text=item.json())


# TODO: set_item_state

start_handler = CommandHandler('start', start)
help_handler = CommandHandler('help', help)
create_bot_handler = CommandHandler('create_bot', create_bot)
set_bot_status_handler = CommandHandler('set_bot_status', set_bot_status)
create_item_group_handler = CommandHandler('create_item_group', create_item_group)
set_item_group_state_handler = CommandHandler('set_item_group_state', set_item_group_state)
add_item_to_group_handler = CommandHandler('add_item_to_group', add_item_to_group)
