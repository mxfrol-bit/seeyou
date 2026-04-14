# 👗 WB Virtual Try-On Bot

Telegram-бот для виртуальной примерки одежды с Wildberries.

## Архитектура

```
User → Telegram
         │
         ▼
    aiogram Bot (FSM)
         │
         ├── WBScraper ──► WB CDN ──► URL изображения товара
         │
         ├── database.py ──► Supabase (users + tryons)
         │
         └── TryOnService (asyncio.gather)
                  │
                  ├─► Claude Vision ──► описание стилиста
                  │
                  └─► FAL fashn/tryon ──► примерка
                            │
                            └─► FAL face-swap ──► лицо 1-в-1
                                  (fallback: Replicate IDM-VTON)
```

## Стек
| | |
|---|---|
| Bot | aiogram 3.x |
| Hosting | Railway (webhook) |
| DB | Supabase (PostgreSQL) |
| AI описание | Claude claude-sonnet-4-20250514 |
| AI примерка | FAL.ai `fashn/tryon` |
| Face restore | FAL.ai `fal-ai/face-swap` |
| Fallback | Replicate `cuuupid/idm-vton` |

## Быстрый старт

### 1. Supabase — создай таблицы
```
Supabase → SQL Editor → выполни supabase_schema.sql
```

### 2. Установка
```bash
pip install -r requirements.txt
cp .env.example .env
# Заполни все ключи в .env
```

### 3. Локальный тест (polling)
```bash
python bot.py
```

### 4. Продакшн Railway (webhook)
```bash
railway login
railway new
railway up
# В Railway Dashboard → Variables → добавь все переменные из .env
# WEBHOOK_HOST = https://yourapp.up.railway.app
```

## Команды бота
| Команда | Действие |
|---|---|
| `/start` | Начать, загрузить своё фото |
| `/reset` | Сменить своё фото |
| `/history` | Последние 5 примерок |

## Стоимость одной примерки
| | |
|---|---|
| Claude Vision | ~$0.01–0.02 |
| FAL fashn/tryon | ~$0.05–0.08 |
| FAL face-swap | ~$0.02–0.03 |
| **Итого** | **~$0.08–0.13** |
