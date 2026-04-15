"""
WB Virtual Try-On Bot — Full Featured
Railway (webhook) + Supabase + Полное меню + Обучение
"""
import asyncio
import logging
import os

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from dotenv import load_dotenv

from database import upsert_user, create_tryon, complete_tryon, get_user_history, get_user_stats
from tryon_service import TryOnService
from wb_scraper import WBScraper

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

bot = Bot(token=os.getenv("TELEGRAM_BOT_TOKEN"))
dp = Dispatcher(storage=MemoryStorage())
tryon_service = TryOnService()
wb_scraper = WBScraper()


class States(StatesGroup):
    # Onboarding
    onboarding_photo    = State()
    # Main flow
    waiting_user_photo  = State()
    waiting_item        = State()
    processing          = State()
    # Feedback
    waiting_feedback    = State()


# ─── Keyboards ────────────────────────────────────────────────────────────────

def main_menu_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="👗 Примерить"), KeyboardButton(text="📜 История")],
        [KeyboardButton(text="📊 Моя статистика"), KeyboardButton(text="ℹ️ Как это работает")],
        [KeyboardButton(text="⚙️ Сменить фото"), KeyboardButton(text="💬 Обратная связь")],
    ], resize_keyboard=True)


def tryon_result_kb(tryon_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="👍 Огонь!", callback_data=f"rate:5:{tryon_id}"),
            InlineKeyboardButton(text="👎 Криво", callback_data=f"rate:1:{tryon_id}"),
        ],
        [InlineKeyboardButton(text="👗 Примерить ещё", callback_data="tryon_more")],
        [InlineKeyboardButton(text="📤 Поделиться", callback_data=f"share:{tryon_id}")],
    ])


def cancel_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="❌ Отмена")]
    ], resize_keyboard=True, one_time_keyboard=True)


# ─── /start + Onboarding ─────────────────────────────────────────────────────

@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user = await upsert_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
    )

    name = message.from_user.first_name or "красотка"

    if user and user.get("is_new"):
        # Новый пользователь — онбординг
        await message.answer(
            f"👋 Привет, <b>{name}</b>!\n\n"
            f"Я — <b>WB Try-On</b>, твой виртуальный стилист.\n\n"
            f"Как это работает:\n"
            f"1️⃣ Пришли <b>своё фото</b> в полный рост\n"
            f"2️⃣ Скинь <b>ссылку с WB</b> или фото вещи\n"
            f"3️⃣ Получи <b>виртуальную примерку</b> + совет стилиста\n\n"
            f"Всё бесплатно, результат через ~30 секунд 🔥\n\n"
            f"📸 Начнём! Пришли своё фото в полный рост:",
            parse_mode="HTML",
            reply_markup=cancel_kb()
        )
        await state.set_state(States.onboarding_photo)
    else:
        # Возвращающийся пользователь
        await message.answer(
            f"👗 Привет, <b>{name}</b>! Рада видеть снова.\n\n"
            f"Что хочешь примерить сегодня?",
            parse_mode="HTML",
            reply_markup=main_menu_kb()
        )


@dp.message(States.onboarding_photo, F.photo)
async def onboarding_photo(message: Message, state: FSMContext):
    photo = message.photo[-1]
    file = await bot.get_file(photo.file_id)
    file_url = f"https://api.telegram.org/file/bot{os.getenv('TELEGRAM_BOT_TOKEN')}/{file.file_path}"
    await state.update_data(user_photo_url=file_url)

    await message.answer(
        "✅ <b>Отлично!</b> Фото сохранено.\n\n"
        "Теперь пришли:\n"
        "• 🔗 <b>Ссылку на товар с WB</b>\n"
        "• 📷 <b>Фото вещи</b> которую хочешь примерить\n\n"
        "<i>Пример: https://www.wildberries.ru/catalog/12345678/detail.aspx</i>",
        parse_mode="HTML",
        reply_markup=cancel_kb()
    )
    await state.set_state(States.waiting_item)


# ─── Главное меню ─────────────────────────────────────────────────────────────

@dp.message(F.text == "👗 Примерить")
async def menu_tryon(message: Message, state: FSMContext):
    data = await state.get_data()
    if data.get("user_photo_url"):
        await message.answer(
            "📦 Пришли ссылку с WB или фото вещи:",
            reply_markup=cancel_kb()
        )
        await state.set_state(States.waiting_item)
    else:
        await message.answer(
            "📸 Сначала пришли своё фото в полный рост:",
            reply_markup=cancel_kb()
        )
        await state.set_state(States.waiting_user_photo)


@dp.message(F.text == "📜 История")
async def menu_history(message: Message):
    await show_history(message)


@dp.message(F.text == "📊 Моя статистика")
async def menu_stats(message: Message):
    stats = await get_user_stats(message.from_user.id)
    if not stats:
        await message.answer("Ещё нет данных — попробуй примерку!", reply_markup=main_menu_kb())
        return

    await message.answer(
        f"📊 <b>Твоя статистика</b>\n\n"
        f"👗 Всего примерок: <b>{stats['total']}</b>\n"
        f"✅ Успешных: <b>{stats['done']}</b>\n"
        f"⭐ Средняя оценка: <b>{stats['avg_rating'] or '—'}</b>\n"
        f"🗓 С нами с: <b>{stats['since']}</b>",
        parse_mode="HTML",
        reply_markup=main_menu_kb()
    )


@dp.message(F.text == "ℹ️ Как это работает")
async def menu_howto(message: Message):
    await message.answer(
        "🤖 <b>Как работает WB Try-On</b>\n\n"
        "<b>Шаг 1 — Твоё фото</b>\n"
        "Пришли фото в полный рост. Лучше всего работает:\n"
        "• Нейтральный фон\n"
        "• Хорошее освещение\n"
        "• Видно всё тело от головы до ног\n\n"
        "<b>Шаг 2 — Вещь с WB</b>\n"
        "Скопируй ссылку на товар с Wildberries и пришли мне. Или пришли фото вещи напрямую.\n\n"
        "<b>Шаг 3 — Результат</b>\n"
        "Через ~30–60 секунд ты получишь:\n"
        "• 🖼 Фото примерки с сохранением твоего лица\n"
        "• 💬 Комментарий AI-стилиста\n\n"
        "<b>Советы для лучшего результата:</b>\n"
        "✓ Фото анфас работает лучше чем сбоку\n"
        "✓ Обтягивающая одежда на фото — лучше посадка\n"
        "✓ Фото одежды на белом фоне — точнее примерка\n"
        "✓ Верх и низ примеряй отдельно",
        parse_mode="HTML",
        reply_markup=main_menu_kb()
    )


@dp.message(F.text == "⚙️ Сменить фото")
async def menu_change_photo(message: Message, state: FSMContext):
    await state.set_state(States.waiting_user_photo)
    await message.answer(
        "📸 Пришли новое фото в полный рост:",
        reply_markup=cancel_kb()
    )


@dp.message(F.text == "💬 Обратная связь")
async def menu_feedback(message: Message, state: FSMContext):
    await state.set_state(States.waiting_feedback)
    await message.answer(
        "💬 Напиши своё пожелание или баг — я передам разработчику:",
        reply_markup=cancel_kb()
    )


@dp.message(States.waiting_feedback)
async def receive_feedback(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено.", reply_markup=main_menu_kb())
        return

    # Отправляем разработчику
    dev_id = os.getenv("DEV_TELEGRAM_ID")
    if dev_id:
        try:
            await bot.send_message(
                dev_id,
                f"📩 Фидбек от @{message.from_user.username} (id:{message.from_user.id}):\n\n{message.text}"
            )
        except Exception:
            pass

    await state.clear()
    await message.answer(
        "✅ Спасибо! Твой отзыв получен 🙏",
        reply_markup=main_menu_kb()
    )


@dp.message(F.text == "❌ Отмена")
async def cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Отменено.", reply_markup=main_menu_kb())


# ─── Шаг 1: Фото пользователя ────────────────────────────────────────────────

@dp.message(States.waiting_user_photo, F.photo)
async def receive_user_photo(message: Message, state: FSMContext):
    photo = message.photo[-1]
    file = await bot.get_file(photo.file_id)
    file_url = f"https://api.telegram.org/file/bot{os.getenv('TELEGRAM_BOT_TOKEN')}/{file.file_path}"
    await state.update_data(user_photo_url=file_url)

    await message.answer(
        "✅ Фото сохранено!\n\n"
        "📦 Теперь пришли:\n"
        "• 🔗 Ссылку на товар с WB\n"
        "• 📷 Фото вещи",
        parse_mode="HTML",
        reply_markup=cancel_kb()
    )
    await state.set_state(States.waiting_item)


@dp.message(States.waiting_user_photo, F.text != "❌ Отмена")
async def wrong_photo(message: Message):
    await message.answer("📸 Пришли фото в полный рост (не файл и не текст)")


# ─── Шаг 2: Товар ────────────────────────────────────────────────────────────

@dp.message(States.waiting_item, F.text)
async def receive_wb_link(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено.", reply_markup=main_menu_kb())
        return

    url = message.text.strip()
    if "wildberries.ru" not in url and "wb.ru" not in url:
        await message.answer(
            "❌ Это не ссылка с Wildberries.\n\n"
            "Пример: <code>https://www.wildberries.ru/catalog/12345678/detail.aspx</code>\n\n"
            "Или пришли фото вещи 📷",
            parse_mode="HTML"
        )
        return

    processing_msg = await message.answer("⏳ Загружаю товар с WB...", reply_markup=ReplyKeyboardRemove())
    item_image_url = await wb_scraper.get_product_image(url)

    if not item_image_url:
        await processing_msg.edit_text("❌ Не удалось получить фото товара. Пришли фото вещи напрямую 📷")
        return

    await processing_msg.edit_text("🔮 Запускаю примерку...\n\n⏱ Обычно занимает 30–60 секунд")
    data = await state.get_data()
    await run_tryon(message, processing_msg, data["user_photo_url"], item_image_url, "wb_link", state)


@dp.message(States.waiting_item, F.photo)
async def receive_item_photo(message: Message, state: FSMContext):
    processing_msg = await message.answer("🔮 Запускаю примерку...\n\n⏱ Обычно занимает 30–60 секунд", reply_markup=ReplyKeyboardRemove())
    photo = message.photo[-1]
    file = await bot.get_file(photo.file_id)
    item_image_url = f"https://api.telegram.org/file/bot{os.getenv('TELEGRAM_BOT_TOKEN')}/{file.file_path}"
    data = await state.get_data()
    await run_tryon(message, processing_msg, data["user_photo_url"], item_image_url, "photo", state)


@dp.message(States.processing)
async def still_processing(message: Message):
    await message.answer("⏳ Ещё обрабатываю... чуть подожди 🙏")


# ─── Callbacks ────────────────────────────────────────────────────────────────

@dp.callback_query(F.data.startswith("rate:"))
async def cb_rate(call: CallbackQuery):
    _, rating, tryon_id = call.data.split(":")
    from database import save_rating
    await save_rating(int(tryon_id), int(rating))
    emoji = "🔥" if int(rating) >= 4 else "📝"
    await call.answer(f"{emoji} Спасибо за оценку!")
    await call.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👗 Примерить ещё", callback_data="tryon_more")],
    ]))


@dp.callback_query(F.data == "tryon_more")
async def cb_more(call: CallbackQuery, state: FSMContext):
    await call.answer()
    data = await state.get_data()
    if data.get("user_photo_url"):
        await call.message.answer("📦 Пришли ссылку с WB или фото вещи:", reply_markup=cancel_kb())
        await state.set_state(States.waiting_item)
    else:
        await call.message.answer("📸 Сначала пришли своё фото:", reply_markup=cancel_kb())
        await state.set_state(States.waiting_user_photo)


@dp.callback_query(F.data.startswith("share:"))
async def cb_share(call: CallbackQuery):
    await call.answer("Скопируй фото и поделись в историях! 📱", show_alert=True)


# ─── Ядро ────────────────────────────────────────────────────────────────────

async def run_tryon(message, processing_msg, user_photo_url, item_image_url, item_source, state):
    await state.set_state(States.processing)

    tryon_id = await create_tryon(
        telegram_id=message.from_user.id,
        user_photo_url=user_photo_url,
        item_url=item_image_url,
        item_source=item_source,
    )

    try:
        results = await tryon_service.run(user_photo_url, item_image_url)
        await processing_msg.delete()

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
                caption="✨ Виртуальная примерка готова!",
                reply_markup=tryon_result_kb(tryon_id)
            )
        elif not results.get("description"):
            await message.answer(
                "❌ Не удалось сгенерировать примерку. Попробуй другое фото или вещь.",
                reply_markup=main_menu_kb()
            )
            await state.set_state(States.waiting_item)
            return

        await message.answer(
            "Хочешь примерить что-то ещё?",
            reply_markup=main_menu_kb()
        )
        await state.set_state(States.waiting_item)

    except Exception as e:
        logger.error(f"TryOn error: {e}", exc_info=True)
        await complete_tryon(tryon_id=tryon_id, tryon_result_url=None, description=None, status="failed")
        await processing_msg.edit_text("❌ Что-то пошло не так. Попробуй ещё раз.")
        await message.answer("Выбери действие:", reply_markup=main_menu_kb())
        await state.set_state(States.waiting_item)


# ─── Helpers ─────────────────────────────────────────────────────────────────

async def show_history(message: Message):
    history = await get_user_history(message.from_user.id, limit=5)
    if not history:
        await message.answer("У тебя пока нет примерок. Нажми 👗 Примерить!", reply_markup=main_menu_kb())
        return

    await message.answer(f"🕓 <b>Последние примерки:</b>", parse_mode="HTML")
    for item in history:
        source = "🔗 WB" if item["item_source"] == "wb_link" else "📷 Фото"
        date = item["created_at"][:10]
        rating = f"⭐ {item['rating']}" if item.get("rating") else ""
        if item.get("tryon_result_url"):
            await message.answer_photo(
                item["tryon_result_url"],
                caption=f"{source} · {date} {rating}"
            )
    await message.answer("Выбери действие:", reply_markup=main_menu_kb())


@dp.message(Command("history"))
async def cmd_history(message: Message):
    await show_history(message)


@dp.message(Command("menu"))
async def cmd_menu(message: Message):
    await message.answer("Главное меню:", reply_markup=main_menu_kb())
