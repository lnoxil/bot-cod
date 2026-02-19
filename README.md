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
- `/bind_discord_user <discord_user_id> <tg_user_id> [chat_id]` (admin)
- `/add_notify_user <tg_user_id> [chat_id]` (admin, получать все уведомления)
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

- при закрытии тикета бот сохраняет полный диалог + вложения (скриншоты, txt, doc/docx и др.) и отправляет архив в Telegram;
- диалог сохраняется в `dialog.txt` и `dialog.docx`;
- после закрытия приходит сообщение с 3 кнопками оценки: "Заказ успешно", "Нейтрально", "Не выполнен"; после нажатия кнопки остальные исчезают.
- редактор поддерживает настраиваемые кнопки панели (`panel_buttons`) с действием `order`/`support`/`url` и размещением по рядам (`row 0..4`) — можно собирать layout ближе к референсу.
- в описании поста поддерживаются теги кнопок: `{{btn:Текст|order|success|inline|🛒}}`, `{{btn:Get Support|support|secondary|row1}}`, `{{btn:Verify|url|secondary|bottom||https://site.com}}` — тег в тексте превращается в рабочую кнопку компонента (под сообщением) и привязывается к действию бота/URL.
- даже если `ticket panel` выключен, но в описании есть `{{btn:...}}`, бот всё равно прикрепит рабочие кнопки к сообщению.
- важно: Discord API не умеет вставлять интерактивные кнопки прямо внутрь текста embed, поэтому реальные кнопки всегда отображаются блоком components под embed (это ограничение Discord).
- по API Discord: интерактивные кнопки отправляются как `message components` и рендерятся отдельным блоком под сообщением; встроить кликабельную кнопку прямо внутрь текста embed нельзя.
  - см. Discord Developer Docs: Message Components / Action Rows (https://discord.com/developers/docs/components/overview).

- добавлен режим layout для embed: **sidebar** (текущий вид с цветной полосой слева), **window** (один большой блок с секциями) и **container** (большие контейнеры как в референсе).
- режим `window` теперь собирает `extra_blocks` как `embed fields` (`inline=False`) в одном embed, чтобы структура была как в референсе: заголовок/описание + секции ниже в одном сообщении.
- режим `container` теперь собирает контент в один большой embed-контейнер и автоматически делит длинный текст на continuation embeds, чтобы текст не обрезался по лимитам Discord.
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

## Запуск на Linux (Ubuntu 24.04 LTS)
1. Установить Python и venv:
```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip
```

2. Клонировать проект и установить зависимости:
```bash
git clone <YOUR_REPO_URL>
cd bot-cod
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .
```

3. Заполнить переменные окружения:
```bash
cp .env.example .env
nano .env
```

4. Запустить бота:
```bash
source .venv/bin/activate
python src/bot.py
```

5. (Опционально) Автозапуск через systemd:
```ini
# /etc/systemd/system/bridge-bot.service
[Unit]
Description=Discord Telegram Bridge Bot
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/bot-cod
Environment=PYTHONUNBUFFERED=1
ExecStart=/home/ubuntu/bot-cod/.venv/bin/python /home/ubuntu/bot-cod/src/bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable bridge-bot
sudo systemctl start bridge-bot
sudo systemctl status bridge-bot
journalctl -u bridge-bot -f
```

Редактор: `http://localhost:8080`

## Запуск на VDS через Docker
Да, можно. На вашем Ubuntu VDS бот отлично запускается в контейнере.

1. Установить Docker + Compose plugin:
```bash
sudo apt update
sudo apt install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo $VERSION_CODENAME) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

2. Создать `Dockerfile` в корне проекта:
```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY web ./web
COPY .env.example ./.env.example

RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir .

CMD ["python", "src/bot.py"]
```

3. Создать `docker-compose.yml`:
```yaml
services:
  bridge-bot:
    build: .
    container_name: bridge-bot
    restart: unless-stopped
    env_file:
      - .env
    ports:
      - "8080:8080"
    volumes:
      - ./state:/app/state
```

4. Подготовить `.env` и запустить:
```bash
cp .env.example .env
nano .env
docker compose up -d --build
```

5. Проверка и логи:
```bash
docker compose ps
docker compose logs -f
```

Редактор будет доступен снаружи по адресу: `http://<VDS_IP>:8080`.

Открыть порт на сервере (если включен firewall):
```bash
sudo ufw allow 8080/tcp
```


Дополнительно в редакторе:
- вкладка **ORDER/SUPPORT ticket** для редактирования авто-сообщений тикетов;
- поддержка шаблона `{user}` (в Discord заменится на упоминание пользователя);
- кнопка **Link** в toolbar: выделяешь текст → вставляешь URL → получаешь кликабельную ссылку `[текст](url)`;
- превью ticket-сообщений справа (ORDER/SUPPORT).
