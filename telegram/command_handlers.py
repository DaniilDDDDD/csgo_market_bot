import os
import json
import pathlib

from telegram.ext import CommandHandler

from ..main import basedir

from market.models import Bot, ItemGroup, Item



# async functions write with asyncio.run inside

def start(update, context):
    context.bot.send_message(chat_id=update.effective_chat.id, text="I'm bot that abusing csgo.market")
start_handler = CommandHandler('start', start)


def help(update, context):
    with open('D:/SteamBot/telegram/help.txt', 'r') as file:
        data = file.read()
        context.bot.send_message(chat_id=update.effective_chat.id, text=data)
help_handler = CommandHandler('help', help)

# аргументы приходят в context.args из входящего сообщения после комманды через пробел
def test(update, context):
    context.bot.send_message(chat_id=update.effective_chat.id, text=context.args)
test_handler = CommandHandler('test', test)

def create_bot(update, context):
    """
    Принимать аргументы в виде '<key>=<value>'
    Аргументы:
    api_key: str,
    username: str,
    password: str,
    steamid: str,
    shared_secret: str,
    identity_secret: str
    Последние три агрумента сохраняются в файл в папку steam_guards/, а название в формате steam_guard_<steam_id>.json
    """

    async def create_bot_in_db(
        api_key: str,
        username: str,
        password: str,
        steamguard_file: str
    ):

        bot = await Bot.objects.get_or_create(
            api_key=api_key,
            username=username,
            password=password,
            steamguard_file=steamguard_file,
            state='created'
        )

    data = {
        "steamid": context.args[3],
        "shared_secret": context.args[4],
        "identity_secret": context.args[5]
    }
    with open(f"{basedir}/steamguards/steam_guard_{context.args[3]}.json", "w", encoding="utf-8") as file:
        json.dump(data, file)



    context.bot.send_message(chat_id=update.effective_chat.id, text=context.args)
test_handler = CommandHandler('create_bot', create_bot)
