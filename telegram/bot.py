import os
import logging
from telegram.ext import Updater

from dotenv import load_dotenv

from command_handlers import start_handler, help_handler, test_handler

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


if __name__ == '__main__':
    updater.start_polling()
    