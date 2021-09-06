import asyncio
from databases import Database

from core.database import database, metadata, engine

from market.background_tasks import trades_confirmation, bots_states_check


async def main():
    """Все асинхронные задачи"""
    task_trades = asyncio.create_task(trades_confirmation())
    task_states_check = asyncio.create_task(bots_states_check())

    await task_trades
    await task_states_check


async def database_connect(db: Database):
    if not db.is_connected:
        await db.connect()


async def database_disconnect(db: Database):
    if db.is_connected:
        await db.disconnect()


if __name__ == '__main__':
    """Инициализация базы данных"""
    metadata.create_all(engine)
    database.connect()
    # запуск параллельных задач
    asyncio.run(main())
    # database.disconnect()
