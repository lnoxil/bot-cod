# Discord ↔ Telegram Ticket Bridge + Full Web Editor

Что теперь есть:
- Полный web-редактор постов с live preview (`http://localhost:8080`)
- Форматирование текста (bold/italic/underline/strike/code/quote)
- Настройка кнопок ticket panel: текст, emoji, цвет
- Split пост на 2 части (второй embed с отдельным цветом/текстом)
- Публикация в Discord из редактора
- Авто-сообщения внутри ORDER / SUPPORT тикета
- Привязка Telegram к конкретному Discord пользователю (`/bind_discord`)
- Уведомления по тикетам в общий Telegram чат + персонально привязанному пользователю

## Важные команды в Telegram
- `/bind_discord <discord_user_id>`
- `/post_save <name> <channel_id> title|description|color_hex|image_url?`
- `/post_send <name>`
- `/post_edit <name> <field> <value>`

## Запуск
```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
python src/bot.py
```

## Веб-редактор
Открой:
```text
http://localhost:8080
```

В редакторе можно:
- редактировать markdown-стиль текста кнопками при выделении;
- менять цвета и подписи ORDER/SUPPORT;
- включать split-mode (2 части поста);
- задать auto-тексты для ORDER/SUPPORT тикетов;
- сохранять шаблон и публиковать в Discord.
