"""
WB Virtual Try-On Bot
Railway (webhook) + Supabase (история)
"""
import asyncio
import logging
import os

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message
from dotenv import load_dotenv

from database import upsert_user, create_tryon, complete_tryon, get_user_history
from tryon_service import TryOnService
from wb_scraper import WBScraper

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

bot = Bot(token=os.getenv("TELEGRAM_BOT_TOKEN"))
dp = Dispatcher(storage=MemoryStorage())
tryon_service = TryOnService()
wb_scraper = WBScraper()


class TryOnStates(StatesGroup):
    waiting_user_photo = State()
    waiting_item = State()
    processing = State()


# ─── /start ──────────────────────────────────────────────────────────────────

@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await upsert_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
    )
    await message.answer(
        "👗 <b>Виртуальная примерка с Wildberries</b>\n\n"
        "Пришли своё фото в полный рост — примерю на тебе любую вещь с WB!\n\n"
        "📸 <b>Шаг 1:</b> Пришли своё фото:",
        parse_mode="HTML"
    )
    await state.set_state(TryOnStates.waiting_user_photo)


@dp.message(Command("reset"))
async def cmd_reset(message: Message, state: FSMContext):
    await state.clear()
    await cmd_start(message, state)


@dp.message(Command("history"))
async def cmd_history(message: Message):
    history = await get_user_history(message.from_user.id, limit=5)
    if not history:
        await message.answer("У тебя пока нет примерок. Отправь /start чтобы начать!")
        return

    await message.answer(f"🕓 <b>Твои последние {len(history)} примерок:</b>", parse_mode="HTML")
    for item in history:
        source = "🔗 WB" if item["item_source"] == "wb_link" else "📷 Фото"
        date = item["created_at"][:10]
        if item.get("tryon_result_url"):
            await message.answer_photo(
                item["tryon_result_url"],
                caption=f"{source} · {date}"
            )


# ─── Шаг 1: Фото пользователя ────────────────────────────────────────────────

@dp.message(TryOnStates.waiting_user_photo, F.photo)
async def receive_user_photo(message: Message, state: FSMContext):
    photo = message.photo[-1]
    file = await bot.get_file(photo.file_id)
    file_url = f"https://api.telegram.org/file/bot{os.getenv('TELEGRAM_BOT_TOKEN')}/{file.file_path}"

    await state.update_data(user_photo_url=file_url)
    await message.answer(
        "✅ Фото сохранено!\n\n"
        "📦 <b>Шаг 2:</b> Теперь отправь:\n"
        "• 🔗 <b>Ссылку на товар с WB</b>\n"
        "• 📷 <b>Фото вещи</b>\n\n"
        "<i>Пример: https://www.wildberries.ru/catalog/12345678/detail.aspx</i>",
        parse_mode="HTML"
    )
    await state.set_state(TryOnStates.waiting_item)


@dp.message(TryOnStates.waiting_user_photo)
async def wrong_photo(message: Message):
    await message.answer("📸 Пришли фото (не файл и не текст)")


# ─── Шаг 2: Товар ────────────────────────────────────────────────────────────

@dp.message(TryOnStates.waiting_item, F.text)
async def receive_wb_link(message: Message, state: FSMContext):
    url = message.text.strip()
    if "wildberries.ru" not in url and "wb.ru" not in url:
        await message.answer(
            "❌ Это не ссылка с Wildberries.\n\n"
            "Пример: <code>https://www.wildberries.ru/catalog/12345678/detail.aspx</code>\n\n"
            "Или пришли фото вещи 📷",
            parse_mode="HTML"
        )
        return

    processing_msg = await message.answer("⏳ Загружаю товар с WB...")
    item_image_url = await wb_scraper.get_product_image(url)

    if not item_image_url:
        await processing_msg.edit_text(
            "❌ Не удалось получить фото товара.\n"
            "Попробуй прислать фото вещи напрямую 📷"
        )
        return

    await processing_msg.edit_text("🔮 Запускаю примерку... (~60 сек)")
    data = await state.get_data()
    await run_tryon(
        message, processing_msg,
        data["user_photo_url"], item_image_url,
        item_source="wb_link", state=state
    )


@dp.message(TryOnStates.waiting_item, F.photo)
async def receive_item_photo(message: Message, state: FSMContext):
    processing_msg = await message.answer("🔮 Запускаю примерку... (~60 сек)")
    photo = message.photo[-1]
    file = await bot.get_file(photo.file_id)
    item_image_url = f"https://api.telegram.org/file/bot{os.getenv('TELEGRAM_BOT_TOKEN')}/{file.file_path}"
    data = await state.get_data()
    await run_tryon(
        message, processing_msg,
        data["user_photo_url"], item_image_url,
        item_source="photo", state=state
    )


@dp.message(TryOnStates.processing)
async def still_processing(message: Message):
    await message.answer("⏳ Ещё обрабатываю... подожди")


# ─── Ядро ────────────────────────────────────────────────────────────────────

async def run_tryon(
    message: Message,
    processing_msg,
    user_photo_url: str,
    item_image_url: str,
    item_source: str,
    state: FSMContext,
):
    await state.set_state(TryOnStates.processing)

    # Создаём запись в БД
    tryon_id = await create_tryon(
        telegram_id=message.from_user.id,
        user_photo_url=user_photo_url,
        item_url=item_image_url,
        item_source=item_source,
    )

    try:
        results = await tryon_service.run(user_photo_url, item_image_url)
        await processing_msg.delete()

        # Сохраняем результат в БД
        await complete_tryon(
            tryon_id=tryon_id,
            tryon_result_url=results.get("tryon_image_url"),
            description=results.get("description"),
            status="done" if (results.get("tryon_image_url") or results.get("description")) else "failed",
        )

        if results.get("description"):
            await message.answer(
                f"🪞 <b>Стилист говорит:</b>\n\n{results['description']}",
                parse_mode="HTML"
            )

        if results.get("tryon_image_url"):
            await message.answer_photo(
                results["tryon_image_url"],
                caption="✨ Виртуальная примерка готова!"
            )
        elif not results.get("description"):
            await message.answer("❌ Не удалось сгенерировать примерку. Попробуй другое фото.")

        await message.answer(
            "Хочешь примерить что-то ещё?\n"
            "• Пришли новую ссылку или фото вещи\n"
            "• /reset — сменить своё фото\n"
            "• /history — история примерок"
        )
        await state.set_state(TryOnStates.waiting_item)

    except Exception as e:
        logger.error(f"TryOn error: {e}", exc_info=True)
        await complete_tryon(tryon_id=tryon_id, tryon_result_url=None, description=None, status="failed")
        await processing_msg.edit_text("❌ Что-то пошло не так. Попробуй ещё раз или /reset")
        await state.set_state(TryOnStates.waiting_item)
