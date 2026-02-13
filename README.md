# Discord ↔ Telegram Ticket Bridge

Бот для Discord, которым можно управлять из Telegram:
- тикет-панель с 2 кнопками: **Order** и **Support**;
- создание приватных тикетов в Discord;
- уведомления о новых/закрытых тикетах в Telegram;
- переписка в тикете из Telegram (через темы forum topic);
- публикация и **редактирование** кастомных Discord-постов из Telegram.

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

5. **Редактор постов из Telegram (с сохранением)**
   - `/post_save <name> <channel_id> title|description|color_hex|image_url?` — сохранить шаблон и сразу отправить
   - `/post_edit <name> <field> <value>` — изменить шаблон (title/description/color/image/channel_id)
   - `/post_send <name>` — заново опубликовать шаблон
   - `/post_show <name>` — показать текущий шаблон
   - `/post_list` — список шаблонов

## Примеры (просто текстом)

### 1) Пример поста под тикет-центр как на скрине

```text
/post_save zenbuilds_ticket 123456789012345678 ZENBUILDS TICKET CENTER|🎁: We work with projects of any complexity and are ready to create something amazing for you\n\n💬: Our staff will provide the most comfortable communication with an individual approach to the client\n\n📋: You can try yourself as a builder in our team, we will welcome high quality specialists|2ECC71|https://example.com/zenbuilds.jpg
```

### 2) Режим редактора: правка того же шаблона из Telegram

```text
/post_edit zenbuilds_ticket description 🎁: Мы делаем проекты любой сложности\n\n💬: Саппорт отвечает быстро и по делу\n\n📋: Открыты к сотрудничеству с опытными билдерами
/post_edit zenbuilds_ticket color 00B894
/post_edit zenbuilds_ticket image https://example.com/new-image.jpg
/post_show zenbuilds_ticket
/post_send zenbuilds_ticket
```

### 3) Перенос шаблона в другой канал

```text
/post_edit zenbuilds_ticket channel_id 987654321098765432
/post_send zenbuilds_ticket
```

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
- `STATE_FILE` — json-хранилище связок тикетов
- `POSTS_FILE` — json-хранилище сохранённых шаблонов постов

## Запуск

```bash
python src/bot.py
```

## Важно

- Для bridge через темы в Telegram используй supergroup с включенными Topics.
- Если topics выключены, бот отправит уведомления в основной чат.
- Команды Telegram теперь безопасны для кейсов, где `update.message` отсутствует.
