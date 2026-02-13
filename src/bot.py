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


class TicketStore:
    def __init__(self, path: Path):
        self.path = path
        self._bindings: dict[int, TicketBinding] = {}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self._bindings = {
            int(cid): TicketBinding(**binding) for cid, binding in payload.items()
        }

    def save(self) -> None:
        payload = {cid: asdict(binding) for cid, binding in self._bindings.items()}
        self.path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def set(self, binding: TicketBinding) -> None:
        self._bindings[binding.ticket_channel_id] = binding
        self.save()

    def get(self, channel_id: int) -> TicketBinding | None:
        return self._bindings.get(channel_id)

    def remove(self, channel_id: int) -> None:
        self._bindings.pop(channel_id, None)
        self.save()


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
        binding = self.bot.store.get(interaction.channel.id)
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
        await self.bot.notify_telegram(
            f"🔒 Тикет закрыт: #{interaction.channel.name}"
        )
        self.bot.store.remove(interaction.channel.id)
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
    def __init__(self, store: TicketStore):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)
        self.store = store
        self.tg_app: Application | None = None

    async def setup_hook(self) -> None:
        self.add_view(TicketOpenView(self))
        self.add_view(CloseTicketButton(self))

        @self.tree.command(name="send_ticket_panel", description="Опубликовать тикет-панель")
        @app_commands.describe(
            channel="Канал, куда отправить пост",
            title="Заголовок",
            description="Описание",
            image_url="URL картинки",
        )
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
            for _, binding in self.store._bindings.items():
                ch = self.get_channel(binding.ticket_channel_id)
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
            logger.warning(
                "Forum topic create failed (chat may not support topics), fallback to main chat"
            )
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
        support_role = (
            interaction.guild.get_role(SUPPORT_ROLE_ID) if SUPPORT_ROLE_ID else None
        )

        prefix = ORDER_PREFIX if ticket_type == "order" else SUPPORT_PREFIX
        channel_name = f"{prefix}-{member.name}".lower().replace(" ", "-")

        overwrites: dict[discord.Role | discord.Member, discord.PermissionOverwrite] = {
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            member: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True
            ),
            interaction.guild.me: discord.PermissionOverwrite(
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
        self.store.set(
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
        await ticket_channel.send(
            content=f"{member.mention} {' '.join([support_role.mention] if support_role else [])}",
            embed=embed,
            view=CloseTicketButton(self),
        )

        await self.notify_telegram(
            (
                f"🆕 Новый {ticket_type.upper()} тикет\n"
                f"Клиент: {member} ({member.id})\n"
                f"Канал: #{ticket_channel.name} ({ticket_channel.id})"
            ),
            thread_id=thread_id,
        )
        await interaction.followup.send(
            f"Тикет создан: {ticket_channel.mention}", ephemeral=True
        )

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        binding = self.store.get(message.channel.id)
        if binding:
            text = f"💬 Discord #{message.channel.name}\n{message.author.display_name}: {message.content}"
            await self.notify_telegram(text, thread_id=binding.telegram_thread_id)
        await self.process_commands(message)


async def tg_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Готово. Команды:\n"
        "/post <channel_id> <title>|<description>|<color_hex>|<image_url?>\n"
        "/panel <channel_id> <title>|<description>|<image_url?>"
    )


def parse_pipe_payload(raw: str, min_parts: int) -> list[str]:
    parts = [p.strip() for p in raw.split("|")]
    if len(parts) < min_parts:
        raise ValueError("Недостаточно аргументов")
    return parts


async def tg_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    bot: BridgeBot = context.application.bot_data["discord_bot"]
    if len(context.args) < 2:
        await update.message.reply_text("Пример: /panel 123456789 title|desc|image_url")
        return

    channel_id = int(context.args[0])
    payload = " ".join(context.args[1:])
    parts = parse_pipe_payload(payload, 2)
    title, description = parts[0], parts[1]
    image_url = parts[2] if len(parts) > 2 else None

    channel = bot.get_channel(channel_id)
    if not isinstance(channel, discord.TextChannel):
        await update.message.reply_text("Канал не найден")
        return

    embed = discord.Embed(title=title, description=description, color=0x2ECC71)
    if image_url:
        embed.set_image(url=image_url)
    await channel.send(embed=embed, view=TicketOpenView(bot))
    await update.message.reply_text("Панель отправлена в Discord ✅")


async def tg_post(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    bot: BridgeBot = context.application.bot_data["discord_bot"]
    if len(context.args) < 2:
        await update.message.reply_text(
            "Пример: /post 123 title|desc|ff9900|https://img..."
        )
        return

    channel_id = int(context.args[0])
    payload = " ".join(context.args[1:])
    title, description, color_hex, *rest = parse_pipe_payload(payload, 3)
    image_url = rest[0] if rest else None
    color = int(color_hex.strip("#"), 16)

    channel = bot.get_channel(channel_id)
    if not isinstance(channel, discord.TextChannel):
        await update.message.reply_text("Канал не найден")
        return

    embed = discord.Embed(title=title, description=description, color=color)
    if image_url:
        embed.set_image(url=image_url)
    await channel.send(embed=embed)
    await update.message.reply_text("Пост отправлен ✅")


async def tg_bridge_to_discord(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return
    bot: BridgeBot = context.application.bot_data["discord_bot"]

    for channel_id, binding in bot.store._bindings.items():
        if binding.telegram_thread_id == update.message.message_thread_id:
            ch = bot.get_channel(channel_id)
            if isinstance(ch, discord.TextChannel):
                await ch.send(f"📨 TG {update.effective_user.full_name}: {update.message.text}")
            break


async def run() -> None:
    store = TicketStore(STATE_FILE)
    d_bot = BridgeBot(store)

    tg_app = Application.builder().token(TELEGRAM_TOKEN).build()
    d_bot.tg_app = tg_app
    tg_app.bot_data["discord_bot"] = d_bot

    tg_app.add_handler(CommandHandler("start", tg_start))
    tg_app.add_handler(CommandHandler("panel", tg_panel))
    tg_app.add_handler(CommandHandler("post", tg_post))
    tg_app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), tg_bridge_to_discord))

    await tg_app.bot.set_my_commands(
        [
            BotCommand("start", "Показать команды"),
            BotCommand("panel", "Отправить тикет-панель"),
            BotCommand("post", "Кастомный пост в Discord"),
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
