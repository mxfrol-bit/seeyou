-- WB Try-On Bot — Supabase Schema (v2)
-- Выполни в Supabase → SQL Editor

create table if not exists users (
  id           bigserial primary key,
  telegram_id  bigint unique not null,
  username     text,
  first_name   text,
  created_at   timestamptz default now(),
  updated_at   timestamptz default now()
);

create table if not exists tryons (
  id               bigserial primary key,
  telegram_id      bigint references users(telegram_id) on delete cascade,
  user_photo_url   text not null,
  item_url         text not null,
  item_source      text not null check (item_source in ('wb_link', 'photo')),
  tryon_result_url text,
  description      text,
  rating           int check (rating between 1 and 5),
  status           text not null default 'pending'
                     check (status in ('pending', 'done', 'failed')),
  created_at       timestamptz default now(),
  completed_at     timestamptz
);

create index if not exists tryons_telegram_id_idx on tryons(telegram_id);
create index if not exists tryons_status_idx      on tryons(status);
create index if not exists tryons_created_at_idx  on tryons(created_at desc);

-- Если таблицы уже есть, добавь только колонку rating:
-- alter table tryons add column if not exists rating int check (rating between 1 and 5);
