# Market CS GO bot
Trading bot, using market.csgo.
Works with [market.csgo API](https://market.csgo.com/docs) and [market.csgo APIv2](https://market.csgo.com/docs-v2).
Bot can be controlled with telegram bot.
Docs for TelegramBot can be accessed by sending command ```/help``` to bot.

## Getting started
Firstly you must create your own telegram bot using official [documentation](https://core.telegram.org/bots#3-how-do-i-create-a-bot).
Then fork repository with project from [GitHub](https://github.com/DaniilDDDDD/csgo_market_bot).
Then create ```.env``` file where define variables:
* TELEGRAM_TOKEN - telegram token of your bot
* BOT_NAME - create name for your bot
* SUPERUSER - here you must set your telegram id to have superuser rights (you can read about by sending ```/help``` command to bot)

Then go to ```/core``` directory and run ```python "main.py"```
