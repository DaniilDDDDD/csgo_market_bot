import asyncio
from databases import Database

from core.database import database, metadata, engine

from telegram_bot.bot import updater



async def database_connect(db: Database):
    if not db.is_connected:
        await db.connect()


async def database_disconnect(db: Database):
    if db.is_connected:
        await db.disconnect()


async def main():



if __name__ == '__main__':
    metadata.create_all(engine)

    # async functions write with asyncio.run inside

    asyncio.run(database_connect(database))

    updater.start_polling()

    asyncio.run(main())
