import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os
import io
import datetime

# -------------------
# CẤU HÌNH
# -------------------
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

CONFIG_FILE = "ticket_config.json"
TICKET_DATA = "ticket_data.json"

LOG_CHANNEL_ID = 1445656196999811193  # 🔹 ID kênh log
CATEGORY_ID = 1445062576148054119     # 🔹 ID category chứa ticket

# -------------------
# HÀM LƯU / LOAD JSON
# -------------------
def load_json(file, default):
    if os.path.exists(file):
        with open(file, "r", encoding="utf-8") as f:
            return json.load(f)
    return default

def save_json(file, data):
    with open(file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

# -------------------
# QUẢN LÝ TICKET
# -------------------
def add_ticket(channel_id, user_id):
    data = load_json(TICKET_DATA, {})
    data[str(channel_id)] = {
        "user_id": user_id,
        "created_at": datetime.datetime.utcnow().isoformat(),
        "active": False
    }
    save_json(TICKET_DATA, data)

def set_active(channel_id):
    data = load_json(TICKET_DATA, {})
    if str(channel_id) in data:
        data[str(channel_id)]["active"] = True
        save_json(TICKET_DATA, data)

# -------------------
# VIEW ĐÓNG TICKET
# -------------------
class CloseTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔒 Đóng Ticket", style=discord.ButtonStyle.red)
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = interaction.channel
        guild = interaction.guild

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True),
        }
        await channel.edit(overwrites=overwrites, name=f"closed-{channel.name}")

        await interaction.response.send_message("✅ Ticket đã được đóng!", ephemeral=True)

        log_channel = guild.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            embed = discord.Embed(
                title="🔒 Ticket Đóng",
                description=f"Ticket {channel.mention} đã bị đóng bởi {interaction.user.mention}",
                color=discord.Color.red()
            )
            await log_channel.send(embed=embed)

# -------------------
# VIEW MENU TICKET
# -------------------
class TicketView(discord.ui.View):
    def __init__(self, config):
        super().__init__(timeout=None)
        for btn in config["buttons"]:
            self.add_item(TicketButton(btn["label"], btn["role_id"], config["category_id"]))

class TicketButton(discord.ui.Button):
    def __init__(self, label, role_id, category_id):
        super().__init__(label=label, style=discord.ButtonStyle.green)
        self.role_id = role_id
        self.category_id = category_id

    async def callback(self, interaction: discord.Interaction):
        guild = interaction.guild
        category = guild.get_channel(self.category_id)

        if category is None or not isinstance(category, discord.CategoryChannel):
            return await interaction.response.send_message("❌ Category không hợp lệ!", ephemeral=True)

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True),
        }

        channel = await guild.create_text_channel(
            name=f"ticket-{interaction.user.name}",
            overwrites=overwrites,
            category=category
        )

        # Lưu ticket
        add_ticket(channel.id, interaction.user.id)

        # Ping role
        role = guild.get_role(self.role_id)
        if role:
            await channel.send(f"{interaction.user.mention} đã mở ticket! Ping {role.mention}")

        # Gửi nút đóng ticket
        await channel.send("🔒 Nhấn nút dưới để đóng ticket:", view=CloseTicketView())

        await interaction.response.send_message(f"✅ Ticket đã tạo: {channel.mention}", ephemeral=True)

        # Log
        log_channel = guild.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            embed = discord.Embed(
                title="🎫 Ticket Được Tạo",
                description=f"Người tạo: {interaction.user.mention}\nLoại: **{self.label}**\nKênh: {channel.mention}",
                color=discord.Color.green()
            )
            await log_channel.send(embed=embed)

# -------------------
# BACKGROUND CHECK
# -------------------
@tasks.loop(minutes=5)
async def check_tickets():
    data = load_json(TICKET_DATA, {})
    now = datetime.datetime.utcnow()

    for channel_id, info in list(data.items()):
        created = datetime.datetime.fromisoformat(info["created_at"])
        user_id = info["user_id"]
        active = info.get("active", False)

        if not active and (now - created).total_seconds() > 6 * 3600:  # 6h
            for guild in bot.guilds:
                member = guild.get_member(int(user_id))
                if member:
                    try:
                        until = discord.utils.utcnow() + datetime.timedelta(days=1)
                        await member.timeout(until, reason="Spam ticket không có lý do")
                        log_channel = guild.get_channel(LOG_CHANNEL_ID)
                        if log_channel:
                            await log_channel.send(
                                f"⚠️ {member.mention} đã bị mute 1 ngày vì tạo ticket không có lý do!"
                            )
                    except Exception as e:
                        print(f"Lỗi mute: {e}")
            del data[channel_id]
    save_json(TICKET_DATA, data)

# -------------------
# EVENTS
# -------------------
@bot.event
async def on_message(message):
    if message.author.bot:
        return
    data = load_json(TICKET_DATA, {})
    if str(message.channel.id) in data:
        set_active(message.channel.id)
    await bot.process_commands(message)

@bot.event
async def on_ready():
    check_tickets.start()
    try:
        await bot.tree.sync()
    except Exception as e:
        print(e)
    print(f"✅ Bot {bot.user} đã online")

# -------------------
# SLASH COMMANDS
# -------------------
@bot.tree.command(name="setup", description="Thêm nút vào menu ticket")
@app_commands.describe(label="Tên nút", role="Role sẽ ping khi mở ticket")
async def setup(interaction: discord.Interaction, label: str, role: discord.Role):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ Bạn không có quyền dùng lệnh này!", ephemeral=True)

    config = load_json(CONFIG_FILE, {"buttons": [], "category_id": CATEGORY_ID})
    config["buttons"].append({"label": label, "role_id": role.id})
    save_json(CONFIG_FILE, config)

    await interaction.response.send_message(
        f"✅ Đã thêm nút `{label}` ping {role.mention}!", ephemeral=True
    )

@bot.tree.command(name="taoticket", description="Gửi menu ticket đã setup")
async def taoticket(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ Chỉ admin mới dùng được!", ephemeral=True)

    config = load_json(CONFIG_FILE, {"buttons": [], "category_id": CATEGORY_ID})
    if not config["buttons"]:
        return await interaction.response.send_message("❌ Chưa có nút nào!", ephemeral=True)

    view = TicketView(config)
    await interaction.channel.send("🎫 Nhấn nút bên dưới để tạo ticket LƯU Ý! NẾU TẠO TICKET KHÔNG LÝ DO THÌ SẼ BỊ MUTE 1DAY:", view=view)
    await interaction.response.send_message("✅ Menu ticket đã gửi!", ephemeral=True)

# -------------------
# RUN
# -------------------
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    print("Hãy set biến môi trường DISCORD_TOKEN.")
else:
    bot.run(TOKEN)
