# Discord ↔ Telegram Ticket Bridge + Web Editor

Бот для Discord, которым можно управлять из Telegram **и через веб-редактор**:
- тикет-панель с кнопками **Order** и **Support**;
- создание приватных тикетов;
- уведомления в Telegram;
- bridge сообщений ticket ↔ Telegram;
- редактор постов с live preview и публикацией в Discord.

## Что добавлено по твоему запросу

Теперь есть сайт-редактор:
- live-preview поста в стиле Discord;
- сохранение шаблона по имени;
- загрузка шаблона;
- публикация в Discord в выбранный `channel_id`;
- режим `ticket panel` (публикация с кнопками Order/Support).

URL редактора после запуска:

```text
http://localhost:8080
```

## Telegram команды

- `/panel <channel_id> title|description|image_url?`
- `/post <channel_id> title|description|color_hex|image_url?`
- `/post_save <name> <channel_id> title|description|color_hex|image_url?`
- `/post_send <name>`
- `/post_edit <name> <field> <value>`
  - поля: `title`, `description`, `color`, `image`, `channel_id`, `panel`
- `/post_show <name>`
- `/post_list`

## Пример шаблона поста (как на скрине)

```text
/post_save zenbuilds_ticket 123456789012345678 ZENBUILDS TICKET CENTER|🎁: We work with projects of any complexity and are ready to create something amazing for you\n\n💬: Our staff will provide the most comfortable communication with an individual approach to the client\n\n📋: You can try yourself as a builder in our team, we will welcome high quality specialists|2ECC71|https://example.com/zenbuilds.jpg
```

## Установка

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
```

## Настройки `.env`

Обязательно:
- `DISCORD_TOKEN`
- `TELEGRAM_TOKEN`
- `TELEGRAM_CHAT_ID`

Опционально:
- `SUPPORT_ROLE_ID`
- `TICKET_CATEGORY_ID`
- `ORDER_CHANNEL_PREFIX`
- `SUPPORT_CHANNEL_PREFIX`
- `STATE_FILE`
- `POSTS_FILE`
- `WEB_HOST` (по умолчанию `0.0.0.0`)
- `WEB_PORT` (по умолчанию `8080`)
- `EDITOR_HTML_PATH` (по умолчанию `web/editor.html`)

## Запуск

```bash
python src/bot.py
```

После запуска:
- Telegram bot работает как раньше;
- Discord bot работает как раньше;
- веб-редактор доступен на `http://localhost:8080`.
