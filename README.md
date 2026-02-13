# Discord ↔ Telegram Ticket Bridge

Бот для Discord, которым можно управлять из Telegram:
- тикет-панель с 2 кнопками: **Order** и **Support**;
- создание приватных тикетов в Discord;
- уведомления о новых/закрытых тикетах в Telegram;
- переписка в тикете из Telegram (через темы forum topic);
- публикация кастомных Discord-постов из Telegram.

## Возможности

1. **Панель тикетов**
   - Slash-команда в Discord: `/send_ticket_panel`
   - Telegram-команда: `/panel <channel_id> title|description|image_url?`

2. **Тикеты**
   - Кнопка `Order` создаёт канал `order-username`
   - Кнопка `Support` создаёт канал `support-username`
   - В канал добавляется кнопка `Close ticket`

3. **Уведомления в Telegram**
   - При создании тикета
   - При закрытии тикета

4. **Bridge сообщений**
   - Сообщения из Discord-тикета летят в Telegram topic
   - Ответ в Telegram topic летит обратно в Discord-тикет

5. **Кастомные посты из Telegram**
   - `/post <channel_id> title|description|color_hex|image_url?`

## Установка

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
```

Заполни `.env`:
- `DISCORD_TOKEN` — токен Discord бота
- `TELEGRAM_TOKEN` — токен Telegram бота
- `TELEGRAM_CHAT_ID` — чат/канал для уведомлений
- `SUPPORT_ROLE_ID` (опц.) — роль саппорта в Discord
- `TICKET_CATEGORY_ID` (опц.) — категория, где создавать тикеты

## Запуск

```bash
python src/bot.py
```

## Важно

- Для bridge через темы в Telegram используй supergroup с включенными Topics.
- Если topics выключены, бот отправит уведомления в основной чат.
- Для красивых постов используй Discord embed (title/description/color/image).
