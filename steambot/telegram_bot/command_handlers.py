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


def help(update, context):
    """
/help
    Документация бота.
    """
    # with open(f'{basedir}/telegram_bot/help.txt', 'r') as file:
    #     data = file.read()
    #     context.bot.send_message(chat_id=update.effective_chat.id, text=data)

    result = f'Документация Бота {bot_name}.\n'
    result += 'Все функции принимают аргументы в виде <key>=<value>.\n'

    result += help.__doc__
    result += create_bot.__doc__
    result += set_bot_status.__doc__

    context.bot.send_message(chat_id=update.effective_chat.id, text=result)


help_handler = CommandHandler('help', help)


def start(update, context):
    context.bot.send_message(chat_id=update.effective_chat.id, text="I'm bot that abusing csgo.market")


start_handler = CommandHandler('start', start)


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
        for arg in context.args:
            key_value = arg.partition('=')
            assert key_value[0] != '' and key_value[2] != ''
            key, value = key_value[0], key_value[2]
            arguments[key] = value

        for key, value in arguments.items():
            assert value

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


create_bot_handler = CommandHandler('create_bot', create_bot)


def set_bot_status(update, context):
    """
/set_bot_status
    Установко боту нового статуса.
    Принимает два аргумента:
        <id> - id бота,
        <state> - новый статус бота.
    """

    async def delete_bot_from_db(pk: int, state: str):
        _bot = await Bot.objects.get(id=pk)
        _bot.state = state
        return _bot

    try:
        assert len(context.args) == 2
        key_value_id = context.args[0].partition('=')
        assert key_value_id[0] != '' and key_value_id[2] != ''
        key_id, value_id = key_value_id[0], key_value_id[2]

        key_value_state = context.args[1].partition('=')
        assert key_value_state[0] != '' and key_value_state[2] != ''
        key_state, value_state = key_value_state[0], key_value_state[2]

        bot = asyncio.run(delete_bot_from_db(value_id, value_state))

        # TODO: Переделать возвращаемую информацию
        context.bot.send_message(chat_id=update.effective_chat.id, text=bot.json())

    except AssertionError:
        context.bot.send_message(chat_id=update.effective_chat.id, text='Wrong arguments passed!')


set_bot_status_handler = CommandHandler('set_bot_status', set_bot_status)
