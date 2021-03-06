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

    update_inventory_timestamp: datetime.datetime = ormar.DateTime(
        default=datetime.datetime.now()
    )

    last_ping_pong: datetime.datetime = ormar.DateTime(
        default=datetime.datetime.now() - delta(minutes=3)
    )

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

    market_hash_name: str = ormar.String(nullable=True, max_length=1000, unique=True)

    # дабы предмет не был продан за невыгодную цену и бот ущёл в минус
    min_sell_price: int = ormar.Integer(default=0, minimum=0)

    # количество предметов, участвующих в обороте
    amount: int = ormar.Integer(default=1, minimum=0)
    # количество предметов, оставшихся для создания ордера
    to_order_amount: int = ormar.Integer(default=amount, minimum=0)

    def __str__(self):
        return f"Group of items id is {self.id}.\n" \
               f"Group's state is {self.state}.\n" \
               f"Group belongs to bot with id {self.bot.id}.\n" \
               f"Group contains items with market hash name" \
               f" {getattr(self, 'market_hash_name', 'None')}.\n" \
               f"Group rounds {self.amount} items."


# конкретный предмет
class Item(ormar.Model):
    class Meta:
        metadata = metadata
        database = database

    id: int = ormar.Integer(primary_key=True)

    state: str = ormar.String(nullable=False, max_length=100)

    item_group: ItemGroup = ormar.ForeignKey(ItemGroup, nullable=True)

    # продавать за...
    sell_for: int = ormar.Integer(nullable=True, minimum=1)

    # покупать за...
    buy_for: int = ormar.Integer(nullable=True, minimum=1)

    # цена заказа
    ordered_for: int = ormar.Integer(nullable=True, minimum=1)

    # Данные маркета
    market_id: str = ormar.String(max_length=200, nullable=True, unique=True)
    market_hash_name: str = ormar.String(max_length=1000, nullable=True)
    classid: str = ormar.String(max_length=200, nullable=True)
    instanceid: str = ormar.String(max_length=200, nullable=True)

    def __str__(self):
        return f"Market item id is {self.id}.\n" \
               f"Item state is {self.state}.\n" \
               f"Item's market hash name is {getattr(self, 'market_hash_name', 'None')}\n" \
               f"Item belongs to group of items with id {self.item_group.id}.\n" \
               f"Item would be bought for {self.ordered_for} and sold for {self.sell_for}.\n" \
               f"If item is bought it's id on market is {getattr(self, 'market_id', 'None')}, " \
               f"classid is {getattr(self, 'classid', 'None')}, " \
               f"instanceid is {getattr(self, 'instanceid', 'None')}."


class User(ormar.Model):
    class Meta:
        metadata = metadata
        database = database

    id: int = ormar.Integer(primary_key=True)

    def __str__(self):
        return f"User, with id {self.id} allowed to control bot."
