import asyncio
import json
import logging
import os
from dataclasses import asdict, dataclass
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from telegram import BotCommand, Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("bridge")


def env_int(name: str, default: int | None = None) -> int | None:
    raw = os.getenv(name)
    if raw is None:
        return default
    return int(raw)


DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = env_int("TELEGRAM_CHAT_ID")
SUPPORT_ROLE_ID = env_int("SUPPORT_ROLE_ID")
TICKET_CATEGORY_ID = env_int("TICKET_CATEGORY_ID")
ORDER_PREFIX = os.getenv("ORDER_CHANNEL_PREFIX", "order")
SUPPORT_PREFIX = os.getenv("SUPPORT_CHANNEL_PREFIX", "support")
STATE_FILE = Path(os.getenv("STATE_FILE", "state/tickets.json"))
POSTS_FILE = Path(os.getenv("POSTS_FILE", "state/posts.json"))

if not DISCORD_TOKEN or not TELEGRAM_TOKEN or TELEGRAM_CHAT_ID is None:
    raise RuntimeError(
        "Set DISCORD_TOKEN, TELEGRAM_TOKEN and TELEGRAM_CHAT_ID in .env before запуск."
    )


@dataclass
class TicketBinding:
    ticket_channel_id: int
    opener_discord_id: int
    ticket_type: str
    telegram_thread_id: int | None = None


@dataclass
class SavedPost:
    name: str
    channel_id: int
    title: str
    description: str
    color_hex: str = "2ECC71"
    image_url: str | None = None
    last_message_id: int | None = None


class JsonStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> dict:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self, payload: dict) -> None:
        self.path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )


class TicketStore(JsonStore):
    def __init__(self, path: Path):
        super().__init__(path)
        self._bindings: dict[int, TicketBinding] = {}
        self.load()

    def load(self) -> None:
        payload = self._load()
        self._bindings = {
            int(cid): TicketBinding(**binding) for cid, binding in payload.items()
        }

    def save(self) -> None:
        payload = {cid: asdict(binding) for cid, binding in self._bindings.items()}
        self._save(payload)

    def set(self, binding: TicketBinding) -> None:
        self._bindings[binding.ticket_channel_id] = binding
        self.save()

    def get(self, channel_id: int) -> TicketBinding | None:
        return self._bindings.get(channel_id)

    def remove(self, channel_id: int) -> None:
        self._bindings.pop(channel_id, None)
        self.save()


class PostStore(JsonStore):
    def __init__(self, path: Path):
        super().__init__(path)
        self._posts: dict[str, SavedPost] = {}
        self.load()

    def load(self) -> None:
        payload = self._load()
        self._posts = {name: SavedPost(**post) for name, post in payload.items()}

    def save(self) -> None:
        payload = {name: asdict(post) for name, post in self._posts.items()}
        self._save(payload)

    def set(self, post: SavedPost) -> None:
        self._posts[post.name] = post
        self.save()

    def get(self, name: str) -> SavedPost | None:
        return self._posts.get(name)

    def list_names(self) -> list[str]:
        return sorted(self._posts.keys())


class CloseTicketButton(discord.ui.View):
    def __init__(self, bot: "BridgeBot"):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(
        label="Close ticket",
        style=discord.ButtonStyle.danger,
        custom_id="ticket_close",
        emoji="🗑️",
    )
    async def close_ticket(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        if not interaction.channel:
            return
        binding = self.bot.ticket_store.get(interaction.channel.id)
        if binding is None:
            await interaction.response.send_message(
                "Этот канал не привязан к тикету.", ephemeral=True
            )
            return

        if (
            isinstance(interaction.user, discord.Member)
            and SUPPORT_ROLE_ID
            and SUPPORT_ROLE_ID not in [r.id for r in interaction.user.roles]
            and interaction.user.id != binding.opener_discord_id
        ):
            await interaction.response.send_message(
                "Закрыть тикет может саппорт или создатель.", ephemeral=True
            )
            return

        await interaction.response.send_message("Тикет закрывается…", ephemeral=True)
        await self.bot.notify_telegram(f"🔒 Тикет закрыт: #{interaction.channel.name}")
        self.bot.ticket_store.remove(interaction.channel.id)
        await interaction.channel.delete(reason="Ticket closed")


class TicketOpenView(discord.ui.View):
    def __init__(self, bot: "BridgeBot"):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(
        label="Order",
        style=discord.ButtonStyle.success,
        custom_id="ticket_order",
        emoji="🧾",
    )
    async def open_order(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        await self.bot.create_ticket(interaction, "order")

    @discord.ui.button(
        label="Support",
        style=discord.ButtonStyle.primary,
        custom_id="ticket_support",
        emoji="🛟",
    )
    async def open_support(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        await self.bot.create_ticket(interaction, "support")


class BridgeBot(commands.Bot):
    def __init__(self, ticket_store: TicketStore, post_store: PostStore):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)
        self.ticket_store = ticket_store
        self.post_store = post_store
        self.tg_app: Application | None = None

    async def setup_hook(self) -> None:
        self.add_view(TicketOpenView(self))
        self.add_view(CloseTicketButton(self))

        @self.tree.command(name="send_ticket_panel", description="Опубликовать тикет-панель")
        async def send_ticket_panel(
            interaction: discord.Interaction,
            channel: discord.TextChannel,
            title: str,
            description: str,
            image_url: str | None = None,
        ) -> None:
            if not interaction.user.guild_permissions.manage_channels:
                await interaction.response.send_message(
                    "Нужны права Manage Channels", ephemeral=True
                )
                return

            embed = discord.Embed(title=title, description=description, color=0x2ECC71)
            embed.set_footer(text="Нажмите кнопку ниже")
            if image_url:
                embed.set_image(url=image_url)
            await channel.send(embed=embed, view=TicketOpenView(self))
            await interaction.response.send_message("Панель отправлена ✅", ephemeral=True)

        @self.tree.command(name="ticket_status", description="Показать активные тикеты")
        async def ticket_status(interaction: discord.Interaction) -> None:
            lines = []
            for binding in self.ticket_store._bindings.values():
                lines.append(
                    f"• {binding.ticket_type} | <#{binding.ticket_channel_id}> | tg_thread={binding.telegram_thread_id or '-'}"
                )
            txt = "\n".join(lines) if lines else "Активных тикетов нет."
            await interaction.response.send_message(txt, ephemeral=True)

        await self.tree.sync()
        logger.info("Discord slash commands synced")

    async def notify_telegram(self, text: str, thread_id: int | None = None) -> None:
        if not self.tg_app:
            return
        try:
            await self.tg_app.bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text=text,
                message_thread_id=thread_id,
                disable_web_page_preview=True,
            )
        except Exception:
            logger.exception("Failed to notify Telegram")

    async def ensure_forum_thread(self, title: str) -> int | None:
        if not self.tg_app:
            return None
        try:
            topic = await self.tg_app.bot.create_forum_topic(
                chat_id=TELEGRAM_CHAT_ID,
                name=title,
            )
            return topic.message_thread_id
        except Exception:
            logger.warning("Forum topic unavailable, fallback to main chat")
            return None

    async def create_ticket(self, interaction: discord.Interaction, ticket_type: str) -> None:
        if not interaction.guild or not interaction.channel or not interaction.user:
            return
        await interaction.response.defer(ephemeral=True)

        member = interaction.user
        category = (
            interaction.guild.get_channel(TICKET_CATEGORY_ID)
            if TICKET_CATEGORY_ID
            else interaction.channel.category
        )
        support_role = interaction.guild.get_role(SUPPORT_ROLE_ID) if SUPPORT_ROLE_ID else None

        prefix = ORDER_PREFIX if ticket_type == "order" else SUPPORT_PREFIX
        channel_name = f"{prefix}-{member.name}".lower().replace(" ", "-")

        me = interaction.guild.me
        if not me:
            await interaction.followup.send("Ошибка: не найден bot member.", ephemeral=True)
            return

        overwrites: dict[discord.Role | discord.Member, discord.PermissionOverwrite] = {
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            member: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True
            ),
            me: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, manage_channels=True
            ),
        }
        if support_role:
            overwrites[support_role] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True
            )

        ticket_channel = await interaction.guild.create_text_channel(
            name=channel_name,
            category=category if isinstance(category, discord.CategoryChannel) else None,
            overwrites=overwrites,
            topic=f"{ticket_type} ticket opened by {member} ({member.id})",
            reason="New ticket",
        )

        thread_id = await self.ensure_forum_thread(
            f"{ticket_type.upper()} | {member.display_name} | #{ticket_channel.id}"
        )
        self.ticket_store.set(
            TicketBinding(
                ticket_channel_id=ticket_channel.id,
                opener_discord_id=member.id,
                ticket_type=ticket_type,
                telegram_thread_id=thread_id,
            )
        )

        embed = discord.Embed(
            title=f"{ticket_type.title()} ticket",
            description=(
                f"Привет, {member.mention}! Опишите задачу, саппорт скоро ответит.\n"
                "Можно отвечать прямо из Telegram-канала саппорта."
            ),
            color=0x5865F2,
        )
        mention = f"{member.mention} {support_role.mention}" if support_role else member.mention
        await ticket_channel.send(content=mention, embed=embed, view=CloseTicketButton(self))

        await self.notify_telegram(
            (
                f"🆕 Новый {ticket_type.upper()} тикет\n"
                f"Клиент: {member} ({member.id})\n"
                f"Канал: #{ticket_channel.name} ({ticket_channel.id})"
            ),
            thread_id=thread_id,
        )
        await interaction.followup.send(f"Тикет создан: {ticket_channel.mention}", ephemeral=True)

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        binding = self.ticket_store.get(message.channel.id)
        if binding:
            text = f"💬 Discord #{message.channel.name}\n{message.author.display_name}: {message.content}"
            await self.notify_telegram(text, thread_id=binding.telegram_thread_id)
        await self.process_commands(message)


def parse_pipe_payload(raw: str, min_parts: int) -> list[str]:
    parts = [p.strip() for p in raw.split("|")]
    if len(parts) < min_parts:
        raise ValueError("Недостаточно аргументов")
    return parts


async def tg_reply(update: Update, text: str) -> None:
    msg = update.effective_message
    if msg:
        await msg.reply_text(text)


def parse_channel_id(raw: str) -> int:
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError("channel_id должен быть числом") from exc


def post_to_embed(post: SavedPost) -> discord.Embed:
    color = int(post.color_hex.strip("#"), 16)
    embed = discord.Embed(title=post.title, description=post.description, color=color)
    if post.image_url:
        embed.set_image(url=post.image_url)
    return embed


async def publish_saved_post(bot: BridgeBot, post: SavedPost) -> discord.Message:
    channel = bot.get_channel(post.channel_id)
    if not isinstance(channel, discord.TextChannel):
        raise ValueError(f"Канал {post.channel_id} не найден")

    embed = post_to_embed(post)
    return await channel.send(embed=embed)


async def tg_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await tg_reply(
        update,
        "Готово. Команды:\n"
        "/panel <channel_id> title|description|image_url?\n"
        "/post <channel_id> title|description|color_hex|image_url?\n"
        "/post_save <name> <channel_id> title|description|color_hex|image_url?\n"
        "/post_send <name>\n"
        "/post_edit <name> <field> <value> (field: title, description, color, image, channel_id)\n"
        "/post_show <name>\n"
        "/post_list",
    )


async def tg_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    bot: BridgeBot = context.application.bot_data["discord_bot"]
    if len(context.args) < 2:
        await tg_reply(update, "Пример: /panel 123456789 title|desc|image_url")
        return

    try:
        channel_id = parse_channel_id(context.args[0])
        payload = " ".join(context.args[1:])
        parts = parse_pipe_payload(payload, 2)
        title, description = parts[0], parts[1]
        image_url = parts[2] if len(parts) > 2 and parts[2] else None

        channel = bot.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            await tg_reply(update, "Канал не найден")
            return

        embed = discord.Embed(title=title, description=description, color=0x2ECC71)
        if image_url:
            embed.set_image(url=image_url)
        await channel.send(embed=embed, view=TicketOpenView(bot))
        await tg_reply(update, "Панель отправлена в Discord ✅")
    except Exception as exc:
        await tg_reply(update, f"Ошибка: {exc}")


async def tg_post(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    bot: BridgeBot = context.application.bot_data["discord_bot"]
    if len(context.args) < 2:
        await tg_reply(update, "Пример: /post 123 title|desc|ff9900|https://img...")
        return

    try:
        channel_id = parse_channel_id(context.args[0])
        payload = " ".join(context.args[1:])
        title, description, color_hex, *rest = parse_pipe_payload(payload, 3)
        image_url = rest[0] if rest and rest[0] else None
        post = SavedPost(
            name="temp",
            channel_id=channel_id,
            title=title,
            description=description,
            color_hex=color_hex,
            image_url=image_url,
        )
        channel = bot.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            await tg_reply(update, "Канал не найден")
            return
        await channel.send(embed=post_to_embed(post))
        await tg_reply(update, "Пост отправлен ✅")
    except Exception as exc:
        await tg_reply(update, f"Ошибка: {exc}")


async def tg_post_save(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    bot: BridgeBot = context.application.bot_data["discord_bot"]
    if len(context.args) < 3:
        await tg_reply(
            update,
            "Пример: /post_save zen_panel 123 title|desc|2ECC71|https://img...",
        )
        return

    try:
        name = context.args[0].strip().lower()
        channel_id = parse_channel_id(context.args[1])
        payload = " ".join(context.args[2:])
        title, description, color_hex, *rest = parse_pipe_payload(payload, 3)
        image_url = rest[0] if rest and rest[0] else None

        post = SavedPost(
            name=name,
            channel_id=channel_id,
            title=title,
            description=description,
            color_hex=color_hex,
            image_url=image_url,
        )
        msg = await publish_saved_post(bot, post)
        post.last_message_id = msg.id
        bot.post_store.set(post)
        await tg_reply(
            update,
            f"Сохранено и отправлено ✅\nname={post.name}\nchannel_id={post.channel_id}\nmessage_id={post.last_message_id}",
        )
    except Exception as exc:
        await tg_reply(update, f"Ошибка: {exc}")


async def tg_post_send(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    bot: BridgeBot = context.application.bot_data["discord_bot"]
    if len(context.args) != 1:
        await tg_reply(update, "Пример: /post_send zen_panel")
        return

    name = context.args[0].strip().lower()
    post = bot.post_store.get(name)
    if not post:
        await tg_reply(update, "Шаблон не найден")
        return

    try:
        msg = await publish_saved_post(bot, post)
        post.last_message_id = msg.id
        bot.post_store.set(post)
        await tg_reply(update, f"Опубликовано ✅\nchannel_id={post.channel_id}\nmessage_id={msg.id}")
    except Exception as exc:
        await tg_reply(update, f"Ошибка: {exc}")


async def tg_post_show(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    bot: BridgeBot = context.application.bot_data["discord_bot"]
    if len(context.args) != 1:
        await tg_reply(update, "Пример: /post_show zen_panel")
        return

    name = context.args[0].strip().lower()
    post = bot.post_store.get(name)
    if not post:
        await tg_reply(update, "Шаблон не найден")
        return

    await tg_reply(
        update,
        (
            f"name={post.name}\n"
            f"channel_id={post.channel_id}\n"
            f"title={post.title}\n"
            f"description={post.description}\n"
            f"color=#{post.color_hex.strip('#')}\n"
            f"image={post.image_url or '-'}\n"
            f"last_message_id={post.last_message_id or '-'}"
        ),
    )


async def tg_post_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    bot: BridgeBot = context.application.bot_data["discord_bot"]
    names = bot.post_store.list_names()
    if not names:
        await tg_reply(update, "Шаблонов пока нет")
        return
    await tg_reply(update, "Шаблоны:\n" + "\n".join(f"- {name}" for name in names))


async def tg_post_edit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    bot: BridgeBot = context.application.bot_data["discord_bot"]
    if len(context.args) < 3:
        await tg_reply(
            update,
            "Пример: /post_edit zen_panel description Новый текст\n"
            "Доступные поля: title, description, color, image, channel_id",
        )
        return

    name = context.args[0].strip().lower()
    field = context.args[1].strip().lower()
    value = " ".join(context.args[2:]).strip()
    post = bot.post_store.get(name)
    if not post:
        await tg_reply(update, "Шаблон не найден")
        return

    try:
        if field == "title":
            post.title = value
        elif field == "description":
            post.description = value
        elif field == "color":
            int(value.strip("#"), 16)
            post.color_hex = value
        elif field == "image":
            post.image_url = value if value not in {"-", "none", "null"} else None
        elif field == "channel_id":
            post.channel_id = parse_channel_id(value)
        else:
            await tg_reply(update, "Неизвестное поле")
            return

        bot.post_store.set(post)

        edited = False
        if post.last_message_id:
            channel = bot.get_channel(post.channel_id)
            if isinstance(channel, discord.TextChannel):
                try:
                    old_msg = await channel.fetch_message(post.last_message_id)
                    await old_msg.edit(embed=post_to_embed(post))
                    edited = True
                except Exception:
                    logger.warning("Cannot edit existing Discord message, maybe moved/deleted")

        status = "и обновлен в Discord" if edited else "(шаблон обновлен, без редактирования старого сообщения)"
        await tg_reply(update, f"Шаблон обновлен ✅ {status}")
    except Exception as exc:
        await tg_reply(update, f"Ошибка: {exc}")


async def tg_bridge_to_discord(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return
    bot: BridgeBot = context.application.bot_data["discord_bot"]

    for channel_id, binding in bot.ticket_store._bindings.items():
        if binding.telegram_thread_id == update.message.message_thread_id:
            ch = bot.get_channel(channel_id)
            if isinstance(ch, discord.TextChannel):
                username = update.effective_user.full_name if update.effective_user else "Telegram user"
                await ch.send(f"📨 TG {username}: {update.message.text}")
            break


async def tg_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Telegram handler error", exc_info=context.error)
    if isinstance(update, Update):
        await tg_reply(update, f"Ошибка обработки команды: {context.error}")


async def run() -> None:
    ticket_store = TicketStore(STATE_FILE)
    post_store = PostStore(POSTS_FILE)
    d_bot = BridgeBot(ticket_store, post_store)

    tg_app = Application.builder().token(TELEGRAM_TOKEN).build()
    d_bot.tg_app = tg_app
    tg_app.bot_data["discord_bot"] = d_bot

    tg_app.add_handler(CommandHandler("start", tg_start))
    tg_app.add_handler(CommandHandler("panel", tg_panel))
    tg_app.add_handler(CommandHandler("post", tg_post))
    tg_app.add_handler(CommandHandler("post_save", tg_post_save))
    tg_app.add_handler(CommandHandler("post_send", tg_post_send))
    tg_app.add_handler(CommandHandler("post_show", tg_post_show))
    tg_app.add_handler(CommandHandler("post_list", tg_post_list))
    tg_app.add_handler(CommandHandler("post_edit", tg_post_edit))
    tg_app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), tg_bridge_to_discord))
    tg_app.add_error_handler(tg_error_handler)

    await tg_app.bot.set_my_commands(
        [
            BotCommand("start", "Показать команды"),
            BotCommand("panel", "Отправить тикет-панель"),
            BotCommand("post", "Одноразовый пост в Discord"),
            BotCommand("post_save", "Сохранить шаблон и отправить"),
            BotCommand("post_send", "Опубликовать сохраненный шаблон"),
            BotCommand("post_edit", "Редактировать сохраненный шаблон"),
            BotCommand("post_show", "Показать шаблон"),
            BotCommand("post_list", "Список шаблонов"),
        ]
    )

    await tg_app.initialize()
    await tg_app.start()
    await tg_app.updater.start_polling()

    discord_task = asyncio.create_task(d_bot.start(DISCORD_TOKEN))
    logger.info("Both bots started")

    try:
        await discord_task
    finally:
        await tg_app.updater.stop()
        await tg_app.stop()
        await tg_app.shutdown()


if __name__ == "__main__":
    asyncio.run(run())
