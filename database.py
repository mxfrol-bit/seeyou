"""
Supabase Database Layer
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
        _client = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
    return _client


async def upsert_user(telegram_id: int, username: str = None, first_name: str = None) -> dict:
    try:
        existing = get_db().table("users").select("id").eq("telegram_id", telegram_id).execute()
        is_new = len(existing.data) == 0

        get_db().table("users").upsert({
            "telegram_id": telegram_id,
            "username": username,
            "first_name": first_name,
            "updated_at": datetime.utcnow().isoformat(),
        }, on_conflict="telegram_id").execute()

        return {"is_new": is_new}
    except Exception as e:
        logger.error(f"upsert_user error: {e}")
        return {"is_new": False}


async def create_tryon(telegram_id: int, user_photo_url: str, item_url: str, item_source: str) -> Optional[int]:
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


async def complete_tryon(tryon_id: int, tryon_result_url: Optional[str], description: Optional[str], status: str = "done"):
    try:
        get_db().table("tryons").update({
            "tryon_result_url": tryon_result_url,
            "description": description,
            "status": status,
            "completed_at": datetime.utcnow().isoformat(),
        }).eq("id", tryon_id).execute()
    except Exception as e:
        logger.error(f"complete_tryon error: {e}")


async def save_rating(tryon_id: int, rating: int):
    try:
        get_db().table("tryons").update({"rating": rating}).eq("id", tryon_id).execute()
    except Exception as e:
        logger.error(f"save_rating error: {e}")


async def get_user_history(telegram_id: int, limit: int = 5):
    try:
        result = get_db().table("tryons") \
            .select("id, item_url, item_source, tryon_result_url, status, rating, created_at") \
            .eq("telegram_id", telegram_id) \
            .eq("status", "done") \
            .order("created_at", desc=True) \
            .limit(limit) \
            .execute()
        return result.data
    except Exception as e:
        logger.error(f"get_user_history error: {e}")
        return []


async def get_user_stats(telegram_id: int) -> Optional[dict]:
    try:
        tryons = get_db().table("tryons") \
            .select("status, rating, created_at") \
            .eq("telegram_id", telegram_id) \
            .execute()

        user = get_db().table("users") \
            .select("created_at") \
            .eq("telegram_id", telegram_id) \
            .execute()

        if not tryons.data:
            return None

        total = len(tryons.data)
        done = sum(1 for t in tryons.data if t["status"] == "done")
        ratings = [t["rating"] for t in tryons.data if t.get("rating")]
        avg = round(sum(ratings) / len(ratings), 1) if ratings else None
        since = user.data[0]["created_at"][:10] if user.data else "—"

        return {"total": total, "done": done, "avg_rating": avg, "since": since}
    except Exception as e:
        logger.error(f"get_user_stats error: {e}")
        return None
