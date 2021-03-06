import os
import pathlib
import json
import asyncio
from dotenv import load_dotenv
from functools import wraps

from telegram.ext import CommandHandler

from market.models import Bot, ItemGroup, User
from market.utils import send_request_to_market, delete_orders

load_dotenv()

bot_name = os.environ.get('BOT_NAME')
basedir = pathlib.Path(__file__).parent.parent.absolute()


def restriction(handler_function):
    """
    Проверяет, находится ли пользователь в списке дозволенных к обслуживанию.
    """

    async def _allowed_users() -> list:
        """
        Так как пользователей не много, то можно проходить по всем.
        """
        allowed_users = [int(os.environ.get('SUPERUSER'))]
        users = list(await User.objects.values_list('id', flatten=True))
        allowed_users.extend(users)
        return allowed_users

    @wraps(handler_function)
    def wrapper(update, context):
        user_id = update.effective_user.id
        if user_id in asyncio.run(_allowed_users()):
            handler_function(update, context)
        else:
            context.bot.send_message(
                chat_id=update.effective_chat.id,
                text='Access denied!'
            )
            return

    return wrapper


def check_args(context, update, arguments: dict):
    try:
        for arg in context.args:
            key_value = arg.partition('=')
            assert key_value[0] != '' and key_value[2] != ''
            key, value = key_value[0], key_value[2]
            if key in arguments:
                if key == 'market_hash_name':
                    value = value.replace('_', ' ')
                arguments[key] = value

        for key, value in arguments.items():
            assert value != '--'

        return arguments
    except AssertionError:
        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text='Wrong arguments passed!'
        )
        return None


@restriction
def help(update, context):
    """
/help
    Документация бота.
    """

    result = f'Документация Бота {bot_name}.\n'
    result += 'Все функции принимают аргументы в виде <key>=<value>.\n\n'

    result += help.__doc__
    result += market_bot_inventory.__doc__

    result += list_user.__doc__
    result += add_user.__doc__
    result += delete_user.__doc__

    result += list_bot.__doc__
    result += create_bot.__doc__
    result += set_bot_status.__doc__
    result += update_bot_market_secret.__doc__

    result += list_item_group.__doc__
    result += create_item_group.__doc__
    result += set_item_group_state_amount.__doc__

    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=result
    )


@restriction
def start(update, context):
    """
/start
    Бот работает лишь с заранее добавленными пользователями.
    """
    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="I am trade bot working with market.csgo!"
    )


@restriction
def market_bot_inventory(update, context):
    """
/market_bot_inventory
    Инвентарь, полученный с маркета
    (отображаются предметы, доступные для продажи).
    Аргументы:
        <id> - id бота.
    """

    async def get_bot(id: int) -> Bot:
        _bot = await Bot.objects.get_or_none(id=id)
        assert _bot
        return _bot

    arguments = {
        'id': '--'
    }
    arguments = check_args(context, update, arguments)
    if not arguments:
        return

    try:
        bot = asyncio.run(get_bot(**arguments))
    except AssertionError:
        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text='Bot with this "id" does not exists!'
        )
        return

    response = asyncio.run(send_request_to_market(
        bot,
        'https://market.csgo.com/api/v2/my-inventory/'
    ))
    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=response.get('items')
    )


@restriction
def list_user(update, context):
    """
/list_user
    Список пользователей бота.
    """
    users = asyncio.run(User.objects.all())

    if len(users) <= 1:
        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text='You are the only user except superuser!'
        )
        return

    result = 'All users:\n\n'
    for user in users:
        result += str(user) + '\n\n'

    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=result
    )


@restriction
def add_user(update, context):
    """
/add_user
    Добавляет пользователя к обслуживаемым ботом.
    Данная функция доступна только для суперпользователя.
    Принимает один аргумент <id> - telegram id нового пользователя.
    """

    async def add_user_in_db(id: int) -> User:
        return await User.objects.get_or_create(id=id)

    if update.effective_user.id == int(os.environ.get('SUPERUSER')):
        arguments = {
            'id': '--'
        }
        arguments = check_args(context, update, arguments)
        if not arguments:
            return
        user = asyncio.run(add_user_in_db(**arguments))
        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=str(user)
        )
    else:
        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="You are not allowed to add users!"
        )


@restriction
def delete_user(update, context):
    """
/delete_user
    Удалить пользователя.
    Данная команда доступна лишь суперпользователю.
    Принимает один аргумент <id> - telegram id удаляемого пользователя.
    """

    if update.effective_user.id == int(os.environ.get('SUPERUSER')):
        arguments = {
            'id': '--'
        }
        arguments = check_args(context, update, arguments)
        if not arguments:
            return
        asyncio.run(User.objects.delete(**arguments))
        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text='User deleted!'
        )
    else:
        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="You are not allowed to delete users!"
        )


@restriction
def list_bot(update, context):
    """
/list_bot
    Список всех ботов.
    """

    bots = asyncio.run(Bot.objects.all())

    if not bots:
        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text='Ботов нет.'
        )
        return

    result = 'Все боты:\n\n'
    for bot in bots:
        result += str(bot) + '\n\n'

    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=result
    )


@restriction
def create_bot(update, context):
    """
/create_bot
    Создание бота, имитирующего клиента steam.
    Аргументы:
        <secret_key> - секретный ключ маркета,
        <api_key> - api ключ аккаунта,
        <username> - username аккаунта,
        <password> - password аккаунта,
        <steamid> - steamid аккаунта,
        <shared_secret> - секрет из steam guard authenticator,
        <identity_secret> - секрет из steam guard authenticator
        <description> - описание бота.
    """

    async def create_bot_in_db(
            secret_key: str,
            api_key: str,
            username: str,
            password: str,
            steamguard_file: str,
            description: str
    ) -> Bot:
        _bot = await Bot.objects.get_or_create(
            secret_key=secret_key,
            api_key=api_key,
            username=username,
            password=password,
            steamguard_file=steamguard_file,
            state='paused',
            description=description
        )
        return _bot

    arguments = {
        'secret_key': '--',
        'api_key': '--',
        'username': '--',
        'password': '--',
        'steamid': '--',
        'shared_secret': '--',
        'identity_secret': '--',
        'description': 'Some csgo.market bot.'
    }
    arguments = check_args(context, update, arguments)
    if not arguments:
        return

    bot = asyncio.run(create_bot_in_db(
        secret_key=arguments['secret_key'],
        api_key=arguments['api_key'],
        username=arguments['username'],
        password=arguments['password'],
        steamguard_file=f'{basedir}/steam_guards/'
                        f'steam_guard_{arguments["steamid"]}.json',
        description=arguments['description']
    ))

    data = {
        "steamid": arguments['steamid'],
        "shared_secret": arguments['shared_secret'],
        "identity_secret": arguments['identity_secret']
    }
    with open(bot.steamguard_file, "w", encoding="utf-8") as file:
        json.dump(data, file)

    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=str(bot)
    )


@restriction
def set_bot_status(update, context):
    """
/set_bot_status
    Установко боту нового статуса.
    Возможные статусы:
        active - активация бота;
        paused - остановка работы бота;
        destroyed - удалить бота;
        sell - продавать все дотсупные для прожади предметы и не покупать ничего;
        buy - покупать предметы и не продавать ничего;
        hold - не продавать и не покупать ничего.
    Аргумаенты:
        <id> - id бота,
        <state> - новый статус бота.
    """

    async def change_bot_state_in_db(id: int, state: str) -> Bot:
        _bot = await Bot.objects.get_or_none(id=id)
        assert _bot
        await _bot.update(state=state)
        return _bot

    arguments = {
        'id': '--',
        'state': '--'
    }

    arguments = check_args(context, update, arguments)
    if not arguments:
        return

    try:
        bot = asyncio.run(change_bot_state_in_db(**arguments))
    except AssertionError:
        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text='Bot with this "id" does not exists!'
        )
        return

    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=str(bot)
    )


@restriction
def update_bot_market_secret(update, context):
    """
/update_bot_market_secret
    Обновление скеретного ключа от API маркета.
    Аргументы:
        <id> - id бота,
        <secret_key> - секретный ключ.
    """

    async def update_secret(
            _id: int,
            _secret_key: str
    ) -> Bot:
        _bot = await Bot.objects.get_or_none(id=_id)
        assert _bot
        await _bot.update(secret_key=_secret_key)
        return _bot

    arguments = {
        'id': '--',
        'state': '--'
    }
    arguments = check_args(context, update, arguments)
    if not arguments:
        return

    bot = asyncio.run(update_secret(**arguments))

    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=str(bot)
    )


@restriction
def list_item_group(update, context):
    """
/list_item_group
    Список групп предметов.
    """
    item_groups = asyncio.run(ItemGroup.objects.all())

    if not item_groups:
        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text='Групп предметов нет.'
        )
        return

    result = 'Все группы предметов:\n\n'
    for item_group in item_groups:
        result += str(item_group) + '\n\n'

    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=result
    )


@restriction
def create_item_group(update, context):
    """
/create_item_group
    Создание группы предметов.
    Принимает аргументы:
        <bot> - id бота, которому принадлежит данная группа,
        <state> - состояние ('active' по умолчанию),
        <market_hash_name> - хэш-название предмета с маркета (все пробелы заменить на '_'),
        <amount> - количество предметов в обороте.
    """

    async def create_item_group_in_db(
            bot: int,
            market_hash_name: str = None,
            state: str = 'active',
            amount: int = 1
    ) -> ItemGroup:
        _bot = await Bot.objects.get_or_none(id=bot)
        assert _bot
        _group = await ItemGroup.objects.create(
            bot=_bot,
            state=state,
            market_hash_name=market_hash_name,
            amount=int(amount),
            to_order_amount=int(amount)
        )
        return _group

    arguments = {
        'bot': '--',
        'state': 'active',
        'market_hash_name': None,
        'amount': 1
    }
    arguments = check_args(context, update, arguments)
    if not arguments:
        return

    group = asyncio.run(create_item_group_in_db(**arguments))

    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=str(group)
    )


@restriction
def set_item_group_state_amount(update, context):
    """
/set_item_group_state_amount
    Установка группе предметов нового статуса или изменение количества предметов для заказа.
    Возможные статусы:
        active - группа предметов "работате";
        sell - продавать предметы группы и не покупать;
        buy - продавать предметы группы и не покупать;
        hold - не продавать и не покупать предметы;
        delete - удалить группу предметов.
    Принимает два аргумента:
        <id> - id группы,
        <state> - новый статус группы,
        <amount> - количество предметов в обороте.
    """

    async def set_item_group_state_in_db(
            id: int,
            state: str,
            amount: int = None
    ) -> ItemGroup:
        _group = await ItemGroup.objects.select_related(
            ItemGroup.bot
        ).get_or_none(
            id=id
        )
        assert _group

        if not state:
            state = _group.state

        if amount:
            amount = int(amount)

            if amount > _group.amount:
                await _group.update(
                    state=state,
                    amount=amount,
                    to_order_amount=_group.to_order_amount + (
                            amount - _group.amount
                    )
                )

            elif amount < _group.amount:
                if amount >= _group.amount - _group.to_order_amount:
                    await _group.update(
                        state=state,
                        amount=amount,
                        to_order_amount=_group.to_order_amount
                    )
                else:

                    await _group.update(
                        state=state,
                        amount=amount,
                        to_order_amount=amount
                    )

                    await delete_orders(_group.bot, _group)

            else:
                await _group.update(state=state)

        else:
            await _group.update(state=state)

        return _group

    arguments = {
        'id': '--',
        'state': None,
        'amount': None
    }
    arguments = check_args(context, update, arguments)
    if not arguments:
        return

    try:
        group = asyncio.run(
            set_item_group_state_in_db(**arguments)
        )
    except AssertionError:
        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text='Item group with this "id" does not exists!'
        )
        return

    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=str(group)
    )


start_handler = CommandHandler('start', start)
help_handler = CommandHandler('help', help)
market_bot_inventory_handler = CommandHandler(
    'market_bot_inventory',
    market_bot_inventory
)

list_user_handler = CommandHandler('list_user', list_user)
add_user_handler = CommandHandler('add_user', add_user)
delete_user_handler = CommandHandler('delete_user', delete_user)

list_bot_handler = CommandHandler('list_bot', list_bot)
create_bot_handler = CommandHandler('create_bot', create_bot)
set_bot_status_handler = CommandHandler(
    'set_bot_status',
    set_bot_status
)
update_bot_market_secret_handler = CommandHandler(
    'update_bot_market_secret',
    update_bot_market_secret
)

list_item_group_handler = CommandHandler(
    'list_item_group',
    list_item_group
)
create_item_group_handler = CommandHandler(
    'create_item_group',
    create_item_group
)
set_item_group_state_handler = CommandHandler(
    'set_item_group_state_amount',
    set_item_group_state_amount
)

