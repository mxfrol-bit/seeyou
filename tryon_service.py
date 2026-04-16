"""
TryOn Service — двухэтапный пайплайн с сохранением лица
  1. Claude Vision → описание стилиста
  2. FAL fashn/tryon → примерка одежды
  3. FAL fal-ai/face-swap → оригинальное лицо 1-в-1
     fallback: Replicate IDM-VTON
"""
import asyncio
import base64
import logging
import os
from typing import Optional

import httpx
import anthropic
from PIL import Image, ImageOps
import io

logger = logging.getLogger(__name__)

FAL_BASE = "https://queue.fal.run"


def _fal_headers(key: str) -> dict:
    return {"Authorization": f"Key {key}", "Content-Type": "application/json"}



async def _prepare_model_image(image_url: str) -> str:
    """
    Скачивает фото, добавляет padding снизу 20% чтобы ноги не обрезались,
    возвращает base64 data URL.
    """
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(image_url)
        img = Image.open(io.BytesIO(resp.content)).convert("RGB")

    w, h = img.size
    # Добавляем 20% высоты снизу нейтральным цветом
    pad = int(h * 0.2)
    new_img = Image.new("RGB", (w, h + pad), (200, 200, 200))
    new_img.paste(img, (0, 0))

    buf = io.BytesIO()
    new_img.save(buf, format="JPEG", quality=95)
    b64 = base64.b64encode(buf.getvalue()).decode()
    return f"data:image/jpeg;base64,{b64}"

class TryOnService:
    def __init__(self):
        self.anthropic = anthropic.AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        self.fal_key = os.getenv("FAL_KEY")
        self.replicate_token = os.getenv("REPLICATE_API_TOKEN")

    async def run(self, user_photo_url: str, item_image_url: str) -> dict:
        desc_task = self._get_claude_description(user_photo_url, item_image_url)
        img_task  = self._get_tryon_with_face(user_photo_url, item_image_url)
        results = await asyncio.gather(desc_task, img_task, return_exceptions=True)

        if isinstance(results[0], Exception):
            logger.error(f"Claude failed: {results[0]}")
        if isinstance(results[1], Exception):
            logger.error(f"Image pipeline failed: {results[1]}")

        return {
            "description":    results[0] if not isinstance(results[0], Exception) else None,
            "tryon_image_url": results[1] if not isinstance(results[1], Exception) else None,
        }

    # ─── Claude Vision ────────────────────────────────────────────────────────

    async def _get_claude_description(self, user_photo_url: str, item_image_url: str) -> str:
        async with httpx.AsyncClient(timeout=20) as client:
            user_bytes = (await client.get(user_photo_url)).content
            item_bytes = (await client.get(item_image_url)).content

        response = await self.anthropic.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=700,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": _media(user_bytes), "data": _b64(user_bytes)}},
                    {"type": "image", "source": {"type": "base64", "media_type": _media(item_bytes), "data": _b64(item_bytes)}},
                    {"type": "text", "text": (
                        "Ты — опытный стилист. Фото человека + фото одежды.\n\n"
                        "Опиши:\n"
                        "1. Посадка и силуэт — как сядет на эту фигуру\n"
                        "2. Сочетание — подходит к стилю, с чем носить\n"
                        "3. Оценка образа — от 1 до 10 с объяснением\n\n"
                        "Пиши живо, как стилист другу. На русском. Без вступлений."
                    )}
                ]
            }]
        )
        return response.content[0].text

    # ─── Image Pipeline ───────────────────────────────────────────────────────

    async def _get_tryon_with_face(self, user_photo_url: str, item_image_url: str) -> Optional[str]:
        # Шаг 1: примерка одежды
        try:
            tryon_url = await self._fal_tryon(user_photo_url, item_image_url)
        except Exception as e:
            logger.warning(f"FAL tryon failed: {e}, trying Replicate")
            try:
                tryon_url = await self._replicate_tryon(user_photo_url, item_image_url)
            except Exception as e2:
                logger.error(f"Replicate also failed: {e2}")
                return None

        logger.info(f"Step 1 done: {tryon_url}")

        # Шаг 2: восстанавливаем оригинальное лицо
        try:
            final_url = await self._fal_face_swap(
                base_image_url=tryon_url,
                face_image_url=user_photo_url,
            )
            logger.info(f"Step 2 done: {final_url}")
            return final_url
        except Exception as e:
            logger.warning(f"Face swap failed: {e} — returning tryon without face restore")
            return tryon_url

    # ─── FAL fashn/tryon ──────────────────────────────────────────────────────

    async def _fal_tryon(self, user_photo_url: str, item_image_url: str) -> str:
        prepared = await _prepare_model_image(user_photo_url)
        async with httpx.AsyncClient(timeout=180) as client:
            resp = await client.post(
                f"{FAL_BASE}/fal-ai/fashn/tryon/v1.5",
                headers=_fal_headers(self.fal_key),
                json={
                    "model_image": prepared,
                    "garment_image": item_image_url,
                    "category": "auto",
                    "nsfw_filter": False,
                    "mode": "quality",
                    "garment_photo_type": "auto",
                    "num_inference_steps": 50,
                    "guidance_scale": 2.0,
                    "restore_background": True,
                    "restore_clothes": False,
                    "adjust_hands": True,
                    "long_top": False,
                    "cover_feet": False,
                    "flat_lay": False,
                    "output_format": "jpeg",
                }
            )
            resp.raise_for_status()
            job = resp.json()
            return await self._fal_poll(client, job["status_url"], job["request_id"], "fal-ai/fashn/tryon/v1.5")

    # ─── FAL face-swap ────────────────────────────────────────────────────────

    async def _fal_face_swap(self, base_image_url: str, face_image_url: str) -> str:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{FAL_BASE}/fal-ai/face-swap",
                headers=_fal_headers(self.fal_key),
                json={
                    "base_image_url": base_image_url,
                    "face_image_url": face_image_url,
                    "face_index": 0,
                    "face_restore": True,
                    "interpolation": 1.0,
                }
            )
            resp.raise_for_status()
            job = resp.json()
            return await self._fal_poll(client, job["status_url"], job["request_id"], "fal-ai/face-swap")

    # ─── FAL polling ─────────────────────────────────────────────────────────

    async def _fal_poll(self, client, status_url: str, request_id: str, model: str, max_polls=90) -> str:
        for i in range(max_polls):
            await asyncio.sleep(2)
            s = (await client.get(status_url, headers=_fal_headers(self.fal_key))).json()
            logger.info(f"[{model}] poll {i+1} status={s.get('status')} keys={list(s.keys())}")

            if s.get("status") == "COMPLETED":
                logger.info(f"[{model}] COMPLETED, fetching response_url")
                response_url = s.get("response_url")
                if not response_url:
                    raise RuntimeError(f"[{model}] No response_url in status: {s}")

                r = (await client.get(response_url, headers=_fal_headers(self.fal_key))).json()
                logger.info(f"[{model}] result keys: {list(r.keys()) if isinstance(r, dict) else type(r)}")

                if isinstance(r, dict):
                    if "image" in r:
                        img = r["image"]
                        return img["url"] if isinstance(img, dict) else img
                    if "images" in r:
                        img = r["images"][0]
                        return img["url"] if isinstance(img, dict) else img
                    if "output" in r:
                        out = r["output"]
                        if isinstance(out, str): return out
                        if isinstance(out, list): return out[0]
                if isinstance(r, list):
                    return r[0] if isinstance(r[0], str) else r[0]["url"]
                if isinstance(r, str):
                    return r

                raise RuntimeError(f"[{model}] Cannot extract URL from result: {r}")

            elif s.get("status") == "FAILED":
                raise RuntimeError(f"{model} failed: {s.get('error')}")

        raise TimeoutError(f"{model} timed out")

    # ─── Replicate IDM-VTON fallback ─────────────────────────────────────────

    async def _replicate_tryon(self, user_photo_url: str, item_image_url: str) -> str:
        async with httpx.AsyncClient(timeout=180) as client:
            resp = await client.post(
                "https://api.replicate.com/v1/predictions",
                headers={"Authorization": f"Bearer {self.replicate_token}", "Content-Type": "application/json", "Prefer": "wait=60"},
                json={"version": "c871bb9b046607b680449ecbae55fd8c6d945e0a1948644bf2361b3d021d3ff4",
                      "input": {
                    "human_img": user_photo_url,
                    "garm_img": item_image_url,
                    "garment_des": "clothing item",
                    "is_checked": True,
                    "is_checked_crop": False,
                    "denoise_steps": 40,
                    "seed": 42,
                }}
            )
            resp.raise_for_status()
            pred = resp.json()
            if pred.get("status") == "succeeded":
                out = pred["output"]
                return out if isinstance(out, str) else out[0]

            poll_url = pred["urls"]["get"]
            for _ in range(40):
                await asyncio.sleep(3)
                pred = (await client.get(poll_url, headers={"Authorization": f"Bearer {self.replicate_token}"})).json()
                if pred["status"] == "succeeded":
                    out = pred["output"]
                    return out if isinstance(out, str) else out[0]
                elif pred["status"] in ("failed", "canceled"):
                    raise RuntimeError(f"Replicate: {pred.get('error')}")

        raise TimeoutError("Replicate timed out")


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()

def _media(data: bytes) -> str:
    if data[:3] == b"\xff\xd8\xff": return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n": return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP": return "image/webp"
    return "image/jpeg"
