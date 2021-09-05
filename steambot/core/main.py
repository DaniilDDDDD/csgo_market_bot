import asyncio
import pathlib

from core.database import database, metadata, engine

from market.background_tasks import trades_confirmation, bots_states_check

basedir = pathlib.Path(__file__).parent.resolve()

async def main():
    '''Все асинхронные задачи'''
    task_trades = asyncio.create_task(trades_confirmation())
    task_states_check = asyncio.create_task(bots_states_check())

    await task_trades
    await task_states_check


if __name__ == '__main__':
    '''Инициализация базы данных'''
    metadata.create_all(engine)
    database.connect()
    # запуск параллельных задач
    asyncio.run(main())
    database.disconnect()