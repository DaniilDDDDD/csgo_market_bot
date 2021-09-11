import os
import logging
import asyncio
from dotenv import load_dotenv
from telegram.ext import Updater
from databases import Database

from core.database import database, metadata, engine

from telegram_bot.command_handlers import (
    start_handler, help_handler, market_bot_inventory_handler,
    list_bot_handler, create_bot_handler, set_bot_status_handler,
    list_item_group_handler, create_item_group_handler, set_item_group_state_handler, set_item_group_price_handler,
    list_item_handler, add_item_to_group_handler, set_item_state_handler, set_item_price_handler
)

load_dotenv()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

bot_name = os.environ.get('BOT_NAME')

updater = Updater(token=os.environ.get('TELEGRAM_TOKEN'), use_context=True)
dispatcher = updater.dispatcher

dispatcher.add_handler(start_handler)
dispatcher.add_handler(help_handler)
dispatcher.add_handler(market_bot_inventory_handler)

dispatcher.add_handler(list_bot_handler)
dispatcher.add_handler(create_bot_handler)
dispatcher.add_handler(set_bot_status_handler)

dispatcher.add_handler(list_item_group_handler)
dispatcher.add_handler(create_item_group_handler)
dispatcher.add_handler(set_item_group_state_handler)
dispatcher.add_handler(set_item_group_price_handler)

dispatcher.add_handler(list_item_handler)
dispatcher.add_handler(add_item_to_group_handler)
dispatcher.add_handler(set_item_state_handler)
dispatcher.add_handler(set_item_price_handler)


async def database_connect(db: Database):
    if not db.is_connected:
        await db.connect()


async def database_disconnect(db: Database):
    if db.is_connected:
        await db.disconnect()


if __name__ == '__main__':
    metadata.create_all(engine)

    # async functions write with asyncio.run inside

    asyncio.run(database_connect(database))

    updater.start_polling()

    # asyncio.run(database_disconnect(database))
