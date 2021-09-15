from typing import Optional
import datetime
from datetime import timedelta as delta

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
    state_check_timestamp: datetime.datetime = ormar.DateTime(default=datetime.datetime.now())

    last_ping_pong: datetime.datetime = ormar.DateTime(default=datetime.datetime.now() - delta(minutes=3))

    secret_key: set = ormar.String(nullable=False, unique=True, max_length=1000)

    api_key: str = ormar.String(nullable=False, unique=True, max_length=1000)
    username: str = ormar.String(nullable=False, unique=True, max_length=300)
    password: str = ormar.String(nullable=False, max_length=300)
    steamguard_file: str = ormar.String(nullable=False, unique=True, max_length=300)

    def __str__(self):
        return f"Bot's id is {self.id}.\n" \
               f"Bot's state is {self.state}.\n" \
               f"Bot's account username is {self.username}.\n" \
               f"Bot's description:\n" \
               f"{self.description}"


class ItemGroup(ormar.Model):
    class Meta:
        metadata = metadata
        database = database

    id: int = ormar.Integer(primary_key=True)

    state: str = ormar.String(nullable=False, max_length=100)

    bot: Bot = ormar.ForeignKey(Bot, nullable=False)

    market_hash_name: str = ormar.String(nullable=True, max_length=1000)

    def __str__(self):
        return f"Group of items id is {self.id}.\n" \
               f"Group's state is {self.state}.\n" \
               f"Group belongs to bot with id {self.bot.id}.\n" \
               f"Group contains items with market hash name {getattr(self, 'market_hash_name', 'None')}."


# конкретный предмет
class Item(ormar.Model):
    class Meta:
        metadata = metadata
        database = database

    id: int = ormar.Integer(primary_key=True)

    state: str = ormar.String(nullable=False, max_length=100)

    item_group: ItemGroup = ormar.ForeignKey(ItemGroup, nullable=True)

    # начало задержки возможности обмена
    trade_timestamp: datetime.datetime = ormar.DateTime(default=datetime.datetime.now)

    # продавать за...
    sell_for: int = ormar.Integer(nullable=True, minimum=1)

    # покупать за...
    buy_for: int = ormar.Integer(nullable=True, minimum=1)

    # цена заказа
    ordered_for: int = ormar.Integer(nullable=True, minimum=1)

    # Данные маркета
    market_id: int = ormar.Integer(nullable=True, unique=True)
    market_hash_name: str = ormar.String(nullable=True, max_length=1000)
    classid: int = ormar.Integer(nullable=True)
    instanceid: int = ormar.Integer(nullable=True)

    def __str__(self):
        return f"Market item id is {self.id}.\n" \
               f"Item state is {self.state}.\n" \
               f"Item's market hash name is {self.market_hash_name}" \
               f"Item belongs to group of items with id {self.item_group.id}.\n" \
               f"Item would be bought for {self.buy_for} and sold for {self.sell_for}.\n" \
               f"If item is bought it's id on market is {self.market_id}, classid is {self.classid}, " \
               f"instanceid is {self.instanceid}."
