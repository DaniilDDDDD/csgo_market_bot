import asyncio
from databases import Database

from core.database import database, metadata, engine

from market.background_tasks import give_items, take_items, bots_states_check, update_orders_price
from telegram_bot.bot import updater


async def main():
    """Все асинхронные задачи"""

    task_bots_states_check = asyncio.create_task(bots_states_check())
    # task_take_items = asyncio.create_task(take_items())
    # task_give_items = asyncio.create_task(give_items())
    # task_update_orders_price = asyncio.create_task(update_orders_price())

    await task_bots_states_check
    # await task_take_items
    # await task_give_items
    # await task_update_orders_price


async def database_connect(db: Database):
    if not db.is_connected:
        await db.connect()


async def database_disconnect(db: Database):
    if db.is_connected:
        await db.disconnect()


if __name__ == '__main__':
    """Инициализация базы данных"""
    metadata.create_all(engine)

    asyncio.run(database_connect(database))

    # updater.start_polling()

    # запуск параллельных задач
    # TODO: проверить, запускаются ли фоновые задачи
    asyncio.run(main())

    # database.disconnect()
