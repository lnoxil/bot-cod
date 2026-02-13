# Discord ↔ Telegram Ticket Bridge + Advanced Web Editor

Сделано под твой запрос:
- полноценный редактор поста на сайте с live preview;
- форматирование выделенного текста (bold/italic/underline/strike/code/quote);
- фото можно ставить сверху или снизу;
- градиент для боковой линии и кнопок (preview + авто-подбор цвета в Discord embed);
- кнопки ORDER/SUPPORT полностью настраиваемые (цвет/текст/emoji);
- добавление дополнительных блоков поста через `+` (одной публикацией отправляются все блоки);
- персональные Telegram уведомления (бот пишет человеку, а не в общий чат);
- роли Telegram: `admin`, `manager`, `builder`, `viewer`;
- заказы/тикеты отправляются в ЛС привязанным пользователям и staff ролям;
- канал тикета в Discord создается с ником пользователя.

## Важное изменение
`TELEGRAM_CHAT_ID` убран из конфигурации.
Теперь используется персональная маршрутизация через привязки и роли.

## Telegram команды
- `/start`
- `/bind_discord <discord_user_id>` — привязать Telegram чат к Discord пользователю
- `/set_role <tg_user_id> <admin|manager|builder|viewer>` — назначить роль (только TG_ADMIN_IDS)
- `/my_role`
- `/post_save <name> <channel_id> title|description|color_hex|image_url?`
- `/post_send <name>`
- `/reply_ticket <discord_channel_id> <text>`

## .env
```env
DISCORD_TOKEN=
TELEGRAM_TOKEN=
TG_ADMIN_IDS=123456789,987654321
```

Остальное см. в `.env.example`.

## Запуск
```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
python src/bot.py
```

Редактор: `http://localhost:8080`
