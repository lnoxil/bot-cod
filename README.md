# Discord ↔ Telegram Ticket Bridge + Advanced Web Editor

Исправления по уведомлениям:
- уведомления о новых ORDER/SUPPORT тикетах теперь идут в Telegram **привязанному пользователю**,
- также идут staff-ролям (admin/manager, и builder для ORDER),
- добавлен self-registration в Telegram через `/register_me`.

## Почему раньше могло не приходить
Если пользователь/роль не были привязаны к реальному `chat_id`, бот не знал куда слать DM.
Теперь можно зарегистрировать чат напрямую и это сохраняется.

## Telegram команды
- `/start`
- `/bind_discord <discord_user_id>`
- `/register_me <admin|manager|builder|viewer>`
- `/set_role <tg_user_id> <admin|manager|builder|viewer> [chat_id]`
- `/my_role`
- `/post_save <name> <channel_id> title|description|color_hex|image_url?`
- `/post_send <name>`
- `/reply_ticket <discord_channel_id> <text>`

## Рекомендуемый сценарий настройки уведомлений
1. Каждый сотрудник пишет боту в личку `/register_me manager` или `/register_me builder`.
2. Клиент пишет боту в личку и делает `/bind_discord <его_discord_id>`.
3. При открытии тикета уведомления уходят в ЛС нужным людям.

- в Telegram формируется единое сообщение-дайджест по тикету (последние 5 сообщений клиента), которое редактируется при изменении/удалении сообщений в Discord.

## .env
```env
DISCORD_TOKEN=
TELEGRAM_TOKEN=
TG_ADMIN_IDS=123456789,987654321
```

## Запуск
```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
python src/bot.py
```

Редактор: `http://localhost:8080`


Дополнительно в редакторе:
- вкладка **ORDER/SUPPORT ticket** для редактирования авто-сообщений тикетов;
- поддержка шаблона `{user}` (в Discord заменится на упоминание пользователя);
- кнопка **Link** в toolbar: выделяешь текст → вставляешь URL → получаешь кликабельную ссылку `[текст](url)`;
- превью ticket-сообщений справа (ORDER/SUPPORT).
