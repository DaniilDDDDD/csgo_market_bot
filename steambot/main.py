import asyncio
from databases import Database

from core.database import database, metadata, engine

from telegram_bot.bot import updater
from market.background_tasks import update_orders_price, bots_states_check, give_items, take_items


async def database_connect(db: Database):
    if not db.is_connected:
        await db.connect()


async def database_disconnect(db: Database):
    if db.is_connected:
        await db.disconnect()


async def main():
    await bots_states_check()
    await take_items()
    await give_items()
    await update_orders_price()


if __name__ == '__main__':
    metadata.create_all(engine)

    # async functions write with asyncio.run inside

    asyncio.run(database_connect(database))

    updater.start_polling()

    asyncio.run(main())
