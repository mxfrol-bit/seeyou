"""
Railway Webhook Server
"""
import logging
import os

from aiohttp import web
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from dotenv import load_dotenv

from bot import dp, bot

load_dotenv()
logger = logging.getLogger(__name__)

WEBHOOK_HOST = os.getenv("WEBHOOK_HOST")
WEBHOOK_PATH = f"/webhook/{os.getenv('TELEGRAM_BOT_TOKEN')}"
WEBHOOK_URL  = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"
PORT = int(os.getenv("PORT", 8080))


async def on_startup(app: web.Application):
    await bot.set_webhook(WEBHOOK_URL, drop_pending_updates=True)
    logger.info(f"✅ Webhook set: {WEBHOOK_URL}")


def main():
    app = web.Application()
    app.on_startup.append(on_startup)
    # on_shutdown убран намеренно — не удаляем webhook при редеплое
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)
    web.run_app(app, host="0.0.0.0", port=PORT)


if __name__ == "__main__":
    main()
