# 👗 WB Try-On Bot

Telegram-бот для виртуальной примерки одежды с Wildberries.

## Стек
| | |
|---|---|
| Bot | aiogram 3.x |
| Hosting | Railway (webhook) |
| DB | Supabase (PostgreSQL) |
| AI описание | Claude claude-sonnet-4-20250514 (Anthropic) |
| AI примерка | FAL.ai `fal-ai/fashn/tryon/v1.5` |
| Face restore | FAL.ai `fal-ai/face-swap` |
| Fallback | Replicate `cuuupid/idm-vton` |
| Landing | HTML (landing.html) |

## Архитектура
```
User → Telegram
         │
         ▼
    aiogram Bot (FSM + меню)
         │
         ├── WBScraper ──► WB CDN ──► URL изображения
         ├── database.py ──► Supabase
         └── TryOnService
                  ├─► Claude Vision ──► описание стилиста
                  └─► FAL fashn/tryon v1.5
                            └─► FAL face-swap ──► лицо 1:1
```

## Команды бота
| Команда | Действие |
|---|---|
| `/start` | Начать / онбординг |
| `/menu` | Главное меню |
| `/history` | История примерок |

## Кнопки меню
- 👗 Примерить
- 📜 История
- 📊 Моя статистика
- ℹ️ Как это работает
- ⚙️ Сменить фото
- 💬 Обратная связь

## Деплой на Railway

### 1. Supabase — создай таблицы
```
Supabase → SQL Editor → выполни supabase_schema.sql
```

### 2. Railway Variables
```
TELEGRAM_BOT_TOKEN
ANTHROPIC_API_KEY
FAL_KEY
SUPABASE_URL
SUPABASE_KEY        ← service_role ключ
WEBHOOK_HOST        ← https://yourapp.up.railway.app
PORT                ← 8080
DEV_TELEGRAM_ID     ← твой Telegram ID (для фидбека)
REPLICATE_API_TOKEN ← опционально (fallback)
```

### 3. После деплоя
Railway автоматически регистрирует webhook при старте.
Бот сразу готов к работе.

## Стоимость одной примерки
| | |
|---|---|
| Claude Vision | ~$0.01–0.02 |
| FAL fashn/tryon v1.5 | ~$0.05–0.08 |
| FAL face-swap | ~$0.02–0.03 |
| **Итого** | **~$0.08–0.13** |

## Файлы
```
├── bot.py                — основной бот, FSM, меню, онбординг
├── tryon_service.py      — AI пайплайн (try-on + face swap)
├── wb_scraper.py         — парсинг WB CDN
├── database.py           — Supabase CRUD
├── server.py             — Railway webhook сервер
├── supabase_schema.sql   — SQL схема БД
├── landing.html          — лендинг сайт
├── Procfile              — railway up
└── requirements.txt
```
