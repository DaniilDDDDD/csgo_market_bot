import os
from dotenv import load_dotenv
from telegram.ext import Updater

from telegram_bot.command_handlers import (
    start_handler, help_handler, market_bot_inventory_handler,
    list_user_handler, add_user_handler, delete_user_handler,
    list_bot_handler, create_bot_handler, set_bot_status_handler, update_bot_market_secret_handler,
    list_item_group_handler, create_item_group_handler, set_item_group_state_handler,
    # list_item_handler, list_group_items_handler, add_item_to_group_handler, set_item_state_handler
)

load_dotenv()

bot_name = os.environ.get('BOT_NAME')

updater = Updater(token=os.environ.get('TELEGRAM_TOKEN'), use_context=True)
dispatcher = updater.dispatcher

dispatcher.add_handler(start_handler)
dispatcher.add_handler(help_handler)
dispatcher.add_handler(market_bot_inventory_handler)

dispatcher.add_handler(list_user_handler)
dispatcher.add_handler(add_user_handler)
dispatcher.add_handler(delete_user_handler)

dispatcher.add_handler(list_bot_handler)
dispatcher.add_handler(create_bot_handler)
dispatcher.add_handler(set_bot_status_handler)
dispatcher.add_handler(update_bot_market_secret_handler)

dispatcher.add_handler(list_item_group_handler)
dispatcher.add_handler(create_item_group_handler)
dispatcher.add_handler(set_item_group_state_handler)
#
# dispatcher.add_handler(list_item_handler)
# dispatcher.add_handler(list_group_items_handler)
# dispatcher.add_handler(add_item_to_group_handler)
# dispatcher.add_handler(set_item_state_handler)
