"""
Wildberries Product Image Scraper
Получает URL первого изображения товара по ссылке WB (без парсинга HTML)
"""
import logging
import re
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


class WBScraper:

    async def get_product_image(self, url: str) -> Optional[str]:
        article = self._extract_article(url)
        if not article:
            logger.warning(f"Cannot extract article from: {url}")
            return None
        return await self._build_image_url(article)

    def _extract_article(self, url: str) -> Optional[str]:
        match = re.search(r"/catalog/(\d+)/", url)
        if match:
            return match.group(1)
        match = re.search(r"(\d{7,10})", url)
        return match.group(1) if match else None

    async def _build_image_url(self, article: str) -> Optional[str]:
        try:
            art_int = int(article)
            vol    = art_int // 100000
            part   = art_int // 1000
            basket = self._get_basket(vol)

            for ext in ("jpg", "webp"):
                img_url = (
                    f"https://basket-{basket:02d}.wbbasket.ru"
                    f"/vol{vol}/part{part}/{article}/images/big/1.{ext}"
                )
                async with httpx.AsyncClient(timeout=8) as client:
                    resp = await client.head(img_url)
                    if resp.status_code == 200:
                        return img_url

            logger.warning(f"Image not found for article {article}")
            return None
        except Exception as e:
            logger.error(f"WB scraper error for {article}: {e}")
            return None

    def _get_basket(self, vol: int) -> int:
        thresholds = [
            (143,1),(287,2),(431,3),(719,4),(1007,5),(1061,6),(1115,7),
            (1169,8),(1313,9),(1601,10),(1655,11),(1919,12),(2045,13),
            (2189,14),(2405,15),(2621,16),(2837,17),(3053,18),(3269,19),
        ]
        for threshold, basket in thresholds:
            if vol <= threshold:
                return basket
        return 20
