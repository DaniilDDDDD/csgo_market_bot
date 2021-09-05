import os
import logging
from telegram.ext import Updater

from ..core.database import database, metadata, engine

from dotenv import load_dotenv

from command_handlers import start_handler, help_handler, test_handler, create_bot_handler

load_dotenv()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

updater = Updater(token=os.environ.get('TELEGRAM_TOKEN'), use_context=True)
dispatcher = updater.dispatcher

dispatcher.add_handler(start_handler)
dispatcher.add_handler(help_handler)
dispatcher.add_handler(test_handler)
dispatcher.add_handler(create_bot_handler)


if __name__ == '__main__':
    metadata.create_all(engine)
    database.connect()

    updater.start_polling()

    database.disconnect()