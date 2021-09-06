from typing import Optional
import datetime

import ormar
from core.database import database, metadata


class Bot(ormar.Model):
    class Meta:
        metadata = metadata
        database = database

    id: int = ormar.Integer(primary_key=True)
    description: Optional[str] = ormar.Text(nullable=True)

    """
    'created', 'in_circle', 'paused', 'destroyed', 'sell', 'buy'
    """

    state: str = ormar.String(nullable=False, max_length=100)
    state_check_timestamp: datetime.datetime = ormar.DateTime(default=datetime.datetime.now)

    last_ping_pong: datetime.datetime = ormar.DateTime(default=datetime.datetime.now)

    api_key: str = ormar.String(nullable=False, unique=True, max_length=1000)
    username: str = ormar.String(nullable=False, unique=True, max_length=300)
    password: str = ormar.String(nullable=False, max_length=300)
    steamguard_file: str = ormar.String(nullable=False, unique=True, max_length=300)


class ItemGroup(ormar.Model):
    class Meta:
        metadata = metadata
        database = database

    id: int = ormar.Integer(primary_key=True)

    state: str = ormar.String(nullable=False, max_length=100)

    bot: Bot = ormar.ForeignKey(Bot, nullable=False)

    market_hash_name: str = ormar.String(nullable=True, max_length=1000)
    classid: int = ormar.Integer(nullable=True)
    instanceid: int = ormar.Integer(nullable=True)

    # покупать столько...
    buy_count: int = ormar.Integer(nullable=False, minimum=0, default=0)

    # продавать столько...
    sell_count: int = ormar.Integer(nullable=False, minimum=0, default=0)


# конкретный предмет
class Item(ormar.Model):
    class Meta:
        metadata = metadata
        database = database

    id: int = ormar.Integer(primary_key=True)

    state: str = ormar.String(nullable=False, max_length=100)

    item_group: ItemGroup = ormar.ForeignKey(ItemGroup, nullable=False)

    # начало задержки возможности обмена
    trade_timestamp: datetime.datetime = ormar.DateTime(default=datetime.datetime.now)

    # покупать за...
    buy_for: int = ormar.Integer(nullable=True, minimum=1)

    # продавать за...
    sell_for: int = ormar.Integer(nullable=True, minimum=1)

    # Данные маркета
    market_id: int = ormar.Integer(nullable=True, unique=True)
    market_hash_name: str = ormar.String(nullable=True, max_length=1000)
    classid: int = ormar.Integer(nullable=True)
    instanceid: int = ormar.Integer(nullable=True)
