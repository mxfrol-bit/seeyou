"""
Supabase Database Layer
Таблицы:
  - users   — telegram пользователи
  - tryons  — история примерок
"""
import logging
import os
from datetime import datetime
from typing import Optional

from supabase import create_client, Client

logger = logging.getLogger(__name__)

_client: Optional[Client] = None


def get_db() -> Client:
    global _client
    if _client is None:
        _client = create_client(
            os.getenv("SUPABASE_URL"),
            os.getenv("SUPABASE_KEY"),
        )
    return _client


# ─── Users ────────────────────────────────────────────────────────────────────

async def upsert_user(telegram_id: int, username: str = None, first_name: str = None):
    """Создаёт или обновляет пользователя"""
    try:
        get_db().table("users").upsert({
            "telegram_id": telegram_id,
            "username": username,
            "first_name": first_name,
            "updated_at": datetime.utcnow().isoformat(),
        }, on_conflict="telegram_id").execute()
    except Exception as e:
        logger.error(f"upsert_user error: {e}")


# ─── Try-ons ──────────────────────────────────────────────────────────────────

async def create_tryon(
    telegram_id: int,
    user_photo_url: str,
    item_url: str,
    item_source: str,  # 'wb_link' | 'photo'
) -> Optional[int]:
    """Создаёт запись примерки, возвращает id"""
    try:
        result = get_db().table("tryons").insert({
            "telegram_id": telegram_id,
            "user_photo_url": user_photo_url,
            "item_url": item_url,
            "item_source": item_source,
            "status": "pending",
            "created_at": datetime.utcnow().isoformat(),
        }).execute()
        return result.data[0]["id"]
    except Exception as e:
        logger.error(f"create_tryon error: {e}")
        return None


async def complete_tryon(
    tryon_id: int,
    tryon_result_url: Optional[str],
    description: Optional[str],
    status: str = "done",  # 'done' | 'failed'
):
    """Обновляет запись с результатом"""
    try:
        get_db().table("tryons").update({
            "tryon_result_url": tryon_result_url,
            "description": description,
            "status": status,
            "completed_at": datetime.utcnow().isoformat(),
        }).eq("id", tryon_id).execute()
    except Exception as e:
        logger.error(f"complete_tryon error: {e}")


async def get_user_history(telegram_id: int, limit: int = 5):
    """Последние примерки пользователя"""
    try:
        result = get_db().table("tryons") \
            .select("id, item_url, item_source, tryon_result_url, status, created_at") \
            .eq("telegram_id", telegram_id) \
            .eq("status", "done") \
            .order("created_at", desc=True) \
            .limit(limit) \
            .execute()
        return result.data
    except Exception as e:
        logger.error(f"get_user_history error: {e}")
        return []
