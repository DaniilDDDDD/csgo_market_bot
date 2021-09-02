import telegram
from .database import database, metadata, engine
import asyncio

async def main():
    '''Все асинхронные задачи'''
    pass

if __name__ == '__main__':
    '''Инициализация базы данных'''
    metadata.create_all(engine)
    database.connect()

    # запуск параллельных задач
    asyncio.run(main())


    database.disconnect()