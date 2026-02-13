import asyncio
import json
import logging
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path

import discord
from aiohttp import web
from discord import ButtonStyle
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
    if raw is None or raw == "":
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
USER_LINKS_FILE = Path(os.getenv("USER_LINKS_FILE", "state/user_links.json"))
WEB_HOST = os.getenv("WEB_HOST", "0.0.0.0")
WEB_PORT = env_int("WEB_PORT", 8080) or 8080
EDITOR_HTML_PATH = Path(os.getenv("EDITOR_HTML_PATH", "web/editor.html"))


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
    is_ticket_panel: bool = False

    order_label: str = "ORDER"
    order_emoji: str = "🧾"
    order_style: str = "success"

    support_label: str = "SUPPORT"
    support_emoji: str = "🛟"
    support_style: str = "primary"

    split_enabled: bool = False
    split_title: str = ""
    split_description: str = ""
    split_color_hex: str = "2ECC71"

    auto_order_message: str = "Спасибо за заказ! Опишите задачу и бюджет."
    auto_support_message: str = "Спасибо за обращение в саппорт! Опишите проблему подробно."


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

    def list_posts(self) -> list[SavedPost]:
        return [self._posts[name] for name in sorted(self._posts.keys())]


class UserLinkStore(JsonStore):
    def __init__(self, path: Path):
        super().__init__(path)
        self.discord_to_tg: dict[int, int] = {}
        self.tg_to_discord: dict[int, int] = {}
        self.load()

    def load(self) -> None:
        data = self._load()
        self.discord_to_tg = {int(k): int(v) for k, v in data.get("discord_to_tg", {}).items()}
        self.tg_to_discord = {int(k): int(v) for k, v in data.get("tg_to_discord", {}).items()}

    def save(self) -> None:
        self._save(
            {
                "discord_to_tg": self.discord_to_tg,
                "tg_to_discord": self.tg_to_discord,
            }
        )

    def link(self, discord_user_id: int, tg_chat_id: int, tg_user_id: int) -> None:
        self.discord_to_tg[discord_user_id] = tg_chat_id
        self.tg_to_discord[tg_user_id] = discord_user_id
        self.save()

    def get_tg_chat_by_discord(self, discord_user_id: int) -> int | None:
        return self.discord_to_tg.get(discord_user_id)


def parse_channel_id(raw: str) -> int:
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError("channel_id должен быть числом") from exc


def style_from_name(name: str) -> ButtonStyle:
    mapping = {
        "primary": ButtonStyle.primary,
        "secondary": ButtonStyle.secondary,
        "success": ButtonStyle.success,
        "danger": ButtonStyle.danger,
        "link": ButtonStyle.secondary,
    }
    return mapping.get(name.lower(), ButtonStyle.secondary)


def sanitize_channel_name(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9\-_]", "-", value).strip("-").lower()
    return cleaned or "user"


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

        await interaction.response.send_message("Тикет закрывается…", ephemeral=True)
        await self.bot.notify_telegram(
            f"🔒 Тикет закрыт: #{interaction.channel.name}",
            opener_discord_id=binding.opener_discord_id,
        )
        self.bot.ticket_store.remove(interaction.channel.id)
        await interaction.channel.delete(reason="Ticket closed")


class TicketOpenView(discord.ui.View):
    def __init__(self, bot: "BridgeBot", post: SavedPost | None = None):
        super().__init__(timeout=None)
        self.bot = bot
        self.post = post or SavedPost(
            name="default",
            channel_id=0,
            title="",
            description="",
        )

        self.add_item(
            discord.ui.Button(
                label=self.post.order_label,
                emoji=self.post.order_emoji,
                style=style_from_name(self.post.order_style),
                custom_id=f"order_btn:{self.post.name}",
            )
        )
        self.add_item(
            discord.ui.Button(
                label=self.post.support_label,
                emoji=self.post.support_emoji,
                style=style_from_name(self.post.support_style),
                custom_id=f"support_btn:{self.post.name}",
            )
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not interaction.data:
            return False
        custom_id = str(interaction.data.get("custom_id", ""))
        if custom_id.startswith("order_btn:"):
            await self.bot.create_ticket(interaction, "order", self.post)
            return False
        if custom_id.startswith("support_btn:"):
            await self.bot.create_ticket(interaction, "support", self.post)
            return False
        return True


class BridgeBot(commands.Bot):
    def __init__(
        self,
        ticket_store: TicketStore,
        post_store: PostStore,
        user_link_store: UserLinkStore,
    ):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)
        self.ticket_store = ticket_store
        self.post_store = post_store
        self.user_link_store = user_link_store
        self.tg_app: Application | None = None

    async def setup_hook(self) -> None:
        self.add_view(CloseTicketButton(self))

    async def notify_telegram(
        self,
        text: str,
        thread_id: int | None = None,
        opener_discord_id: int | None = None,
    ) -> None:
        if not self.tg_app:
            return

        chats: set[int] = set()
        if TELEGRAM_CHAT_ID:
            chats.add(TELEGRAM_CHAT_ID)
        if opener_discord_id is not None:
            linked = self.user_link_store.get_tg_chat_by_discord(opener_discord_id)
            if linked:
                chats.add(linked)

        for chat_id in chats:
            try:
                await self.tg_app.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    message_thread_id=thread_id if chat_id == TELEGRAM_CHAT_ID else None,
                    disable_web_page_preview=True,
                )
            except Exception:
                logger.exception("Failed to notify Telegram chat_id=%s", chat_id)

    async def ensure_forum_thread(self, title: str) -> int | None:
        if not self.tg_app or TELEGRAM_CHAT_ID is None:
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

    async def create_ticket(
        self,
        interaction: discord.Interaction,
        ticket_type: str,
        post: SavedPost | None = None,
    ) -> None:
        if not interaction.guild or not interaction.channel or not interaction.user:
            return
        await interaction.response.defer(ephemeral=True)

        member = interaction.user
        display = sanitize_channel_name(member.display_name)
        prefix = ORDER_PREFIX if ticket_type == "order" else SUPPORT_PREFIX
        channel_name = f"{prefix}-{display}"[:95]

        category = (
            interaction.guild.get_channel(TICKET_CATEGORY_ID)
            if TICKET_CATEGORY_ID
            else interaction.channel.category
        )
        support_role = interaction.guild.get_role(SUPPORT_ROLE_ID) if SUPPORT_ROLE_ID else None
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

        auto_message = ""
        if post:
            auto_message = (
                post.auto_order_message
                if ticket_type == "order"
                else post.auto_support_message
            )

        base_embed = discord.Embed(
            title=f"{ticket_type.title()} ticket",
            description=(
                f"Привет, {member.mention}! Опишите задачу, саппорт скоро ответит.\n"
                f"{auto_message}" if auto_message else f"Привет, {member.mention}! Опишите задачу, саппорт скоро ответит."
            ),
            color=0x5865F2,
        )
        mention = f"{member.mention} {support_role.mention}" if support_role else member.mention
        await ticket_channel.send(content=mention, embed=base_embed, view=CloseTicketButton(self))

        await self.notify_telegram(
            (
                f"🆕 Открыт тикет: {ticket_type.upper()}\n"
                f"Пользователь: {member.display_name} ({member.id})\n"
                f"Канал: #{ticket_channel.name} ({ticket_channel.id})"
            ),
            thread_id=thread_id,
            opener_discord_id=member.id,
        )
        await interaction.followup.send(f"Тикет создан: {ticket_channel.mention}", ephemeral=True)

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        binding = self.ticket_store.get(message.channel.id)
        if binding:
            text = f"💬 Discord #{message.channel.name}\n{message.author.display_name}: {message.content}"
            await self.notify_telegram(
                text,
                thread_id=binding.telegram_thread_id,
                opener_discord_id=binding.opener_discord_id,
            )
        await self.process_commands(message)


def post_to_embeds(post: SavedPost) -> list[discord.Embed]:
    main_color = int(post.color_hex.strip("#"), 16)
    embeds = [
        discord.Embed(title=post.title, description=post.description, color=main_color)
    ]
    if post.image_url:
        embeds[0].set_image(url=post.image_url)

    if post.split_enabled and (post.split_title or post.split_description):
        split_color = int(post.split_color_hex.strip("#"), 16)
        embeds.append(
            discord.Embed(
                title=post.split_title or "Продолжение",
                description=post.split_description,
                color=split_color,
            )
        )
    return embeds


async def publish_saved_post(bot: BridgeBot, post: SavedPost) -> discord.Message:
    channel = bot.get_channel(post.channel_id)
    if not isinstance(channel, discord.TextChannel):
        raise ValueError(f"Канал {post.channel_id} не найден")

    embeds = post_to_embeds(post)
    if post.is_ticket_panel:
        view = TicketOpenView(bot, post)
        return await channel.send(embeds=embeds, view=view)
    return await channel.send(embeds=embeds)


def parse_pipe_payload(raw: str, min_parts: int) -> list[str]:
    parts = [p.strip() for p in raw.split("|")]
    if len(parts) < min_parts:
        raise ValueError("Недостаточно аргументов")
    return parts


async def tg_reply(update: Update, text: str) -> None:
    msg = update.effective_message
    if msg:
        await msg.reply_text(text)


async def tg_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await tg_reply(
        update,
        "Команды:\n"
        "/bind_discord <discord_user_id> - привязать Telegram к Discord пользователю\n"
        "/post_save <name> <channel_id> title|description|color_hex|image_url?\n"
        "/post_send <name>\n"
        "/post_edit <name> <field> <value> (title, description, color, image, channel_id, panel)",
    )


async def tg_bind_discord(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    bot: BridgeBot = context.application.bot_data["discord_bot"]
    if not update.effective_chat or not update.effective_user:
        return
    if len(context.args) != 1:
        await tg_reply(update, "Пример: /bind_discord 123456789012345678")
        return
    try:
        discord_user_id = int(context.args[0])
        bot.user_link_store.link(
            discord_user_id=discord_user_id,
            tg_chat_id=update.effective_chat.id,
            tg_user_id=update.effective_user.id,
        )
        await tg_reply(update, f"Привязано ✅ Discord {discord_user_id} -> TG chat {update.effective_chat.id}")
    except Exception as exc:
        await tg_reply(update, f"Ошибка: {exc}")


async def tg_post_save(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    bot: BridgeBot = context.application.bot_data["discord_bot"]
    if len(context.args) < 3:
        await tg_reply(update, "Пример: /post_save name 123 title|desc|2ECC71|https://img")
        return
    try:
        name = context.args[0].strip().lower()
        channel_id = parse_channel_id(context.args[1])
        title, description, color_hex, *rest = parse_pipe_payload(" ".join(context.args[2:]), 3)
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
        await tg_reply(update, f"Сохранено и отправлено ✅\nchannel_id={channel_id}\nmessage_id={msg.id}")
    except Exception as exc:
        await tg_reply(update, f"Ошибка: {exc}")


async def tg_post_send(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    bot: BridgeBot = context.application.bot_data["discord_bot"]
    if len(context.args) != 1:
        await tg_reply(update, "Пример: /post_send name")
        return
    post = bot.post_store.get(context.args[0].strip().lower())
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


async def tg_post_edit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    bot: BridgeBot = context.application.bot_data["discord_bot"]
    if len(context.args) < 3:
        await tg_reply(update, "Пример: /post_edit name field value")
        return
    name = context.args[0].strip().lower()
    field = context.args[1].strip().lower()
    value = " ".join(context.args[2:]).strip()
    post = bot.post_store.get(name)
    if not post:
        await tg_reply(update, "Шаблон не найден")
        return

    if field == "title":
        post.title = value
    elif field == "description":
        post.description = value
    elif field == "color":
        post.color_hex = value
    elif field == "image":
        post.image_url = value if value not in {"-", "none", "null"} else None
    elif field == "channel_id":
        post.channel_id = parse_channel_id(value)
    elif field == "panel":
        post.is_ticket_panel = value.lower() in {"1", "true", "yes", "on"}
    else:
        await tg_reply(update, "Неизвестное поле")
        return

    bot.post_store.set(post)
    await tg_reply(update, "Шаблон обновлен ✅")


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


def parse_post_from_json(data: dict) -> SavedPost:
    post = SavedPost(
        name=str(data["name"]).strip().lower(),
        channel_id=parse_channel_id(str(data["channel_id"])),
        title=str(data.get("title", "")),
        description=str(data.get("description", "")),
        color_hex=str(data.get("color_hex", "2ECC71")),
        image_url=str(data.get("image_url", "")).strip() or None,
        is_ticket_panel=bool(data.get("is_ticket_panel", False)),
        order_label=str(data.get("order_label", "ORDER")),
        order_emoji=str(data.get("order_emoji", "🧾")),
        order_style=str(data.get("order_style", "success")),
        support_label=str(data.get("support_label", "SUPPORT")),
        support_emoji=str(data.get("support_emoji", "🛟")),
        support_style=str(data.get("support_style", "primary")),
        split_enabled=bool(data.get("split_enabled", False)),
        split_title=str(data.get("split_title", "")),
        split_description=str(data.get("split_description", "")),
        split_color_hex=str(data.get("split_color_hex", "2ECC71")),
        auto_order_message=str(data.get("auto_order_message", "")),
        auto_support_message=str(data.get("auto_support_message", "")),
        last_message_id=(
            int(data["last_message_id"])
            if data.get("last_message_id") not in {None, ""}
            else None
        ),
    )
    int(post.color_hex.strip("#"), 16)
    int(post.split_color_hex.strip("#"), 16)
    return post


async def web_index(request: web.Request) -> web.Response:
    return web.Response(text=EDITOR_HTML_PATH.read_text(encoding="utf-8"), content_type="text/html")


async def web_list_posts(request: web.Request) -> web.Response:
    bot: BridgeBot = request.app["bot"]
    return web.json_response([asdict(post) for post in bot.post_store.list_posts()])


async def web_get_post(request: web.Request) -> web.Response:
    bot: BridgeBot = request.app["bot"]
    post = bot.post_store.get(request.match_info["name"])
    if not post:
        return web.json_response({"error": "not_found"}, status=404)
    return web.json_response(asdict(post))


async def web_save_post(request: web.Request) -> web.Response:
    bot: BridgeBot = request.app["bot"]
    try:
        post = parse_post_from_json(await request.json())
        bot.post_store.set(post)
        return web.json_response({"ok": True, "post": asdict(post)})
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=400)


async def web_publish_post(request: web.Request) -> web.Response:
    bot: BridgeBot = request.app["bot"]
    name = request.match_info["name"]
    post = bot.post_store.get(name)
    if not post:
        return web.json_response({"error": "not_found"}, status=404)
    try:
        msg = await publish_saved_post(bot, post)
        post.last_message_id = msg.id
        bot.post_store.set(post)
        return web.json_response({"ok": True, "channel_id": post.channel_id, "message_id": msg.id})
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=400)


async def start_web_server(bot: BridgeBot) -> web.AppRunner:
    app = web.Application()
    app["bot"] = bot
    app.router.add_get("/", web_index)
    app.router.add_get("/api/posts", web_list_posts)
    app.router.add_get("/api/posts/{name}", web_get_post)
    app.router.add_post("/api/posts/save", web_save_post)
    app.router.add_post("/api/posts/{name}/publish", web_publish_post)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, WEB_HOST, WEB_PORT).start()
    logger.info("Web editor started on http://%s:%s", WEB_HOST, WEB_PORT)
    return runner


def validate_env() -> None:
    if not DISCORD_TOKEN or not TELEGRAM_TOKEN:
        raise RuntimeError("Set DISCORD_TOKEN and TELEGRAM_TOKEN in .env")


async def run() -> None:
    validate_env()
    ticket_store = TicketStore(STATE_FILE)
    post_store = PostStore(POSTS_FILE)
    user_link_store = UserLinkStore(USER_LINKS_FILE)
    d_bot = BridgeBot(ticket_store, post_store, user_link_store)

    tg_app = Application.builder().token(TELEGRAM_TOKEN).build()
    d_bot.tg_app = tg_app
    tg_app.bot_data["discord_bot"] = d_bot

    tg_app.add_handler(CommandHandler("start", tg_start))
    tg_app.add_handler(CommandHandler("bind_discord", tg_bind_discord))
    tg_app.add_handler(CommandHandler("post_save", tg_post_save))
    tg_app.add_handler(CommandHandler("post_send", tg_post_send))
    tg_app.add_handler(CommandHandler("post_edit", tg_post_edit))
    tg_app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), tg_bridge_to_discord))
    tg_app.add_error_handler(tg_error_handler)

    await tg_app.bot.set_my_commands(
        [
            BotCommand("start", "Показать команды"),
            BotCommand("bind_discord", "Привязать Discord user к Telegram"),
            BotCommand("post_save", "Сохранить шаблон и отправить"),
            BotCommand("post_send", "Опубликовать сохраненный шаблон"),
            BotCommand("post_edit", "Редактировать сохраненный шаблон"),
        ]
    )

    await tg_app.initialize()
    await tg_app.start()
    await tg_app.updater.start_polling()
    web_runner = await start_web_server(d_bot)

    discord_task = asyncio.create_task(d_bot.start(DISCORD_TOKEN))
    logger.info("Discord + Telegram + Web editor started")

    try:
        await discord_task
    finally:
        await web_runner.cleanup()
        await tg_app.updater.stop()
        await tg_app.stop()
        await tg_app.shutdown()


if __name__ == "__main__":
    asyncio.run(run())
