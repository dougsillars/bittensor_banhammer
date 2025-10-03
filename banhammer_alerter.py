import discord
from discord.ext import commands
from datetime import datetime, timezone
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()
BOT_TOKEN = os.getenv('discord')
MOD_CHANNEL_NAME = "mod_alerts"

intents = discord.Intents.default()
intents.members = True  # needed to check members across servers
intents.message_content = True  # Required for message content
intents.guilds = True
intents.bans = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Helper function to find #mod-alerts channel
def get_mod_alert_channel(guild: discord.Guild):
    for channel in guild.text_channels:
        if channel.name == MOD_CHANNEL_NAME:
            return channel
    return None

@bot.event
async def on_member_ban(guild: discord.Guild, user: discord.User):
    # Get the audit log to see who banned the user and the reason
    banner = None
    reason = None
    async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.ban):
        if entry.target.id == user.id:
            banner = entry.user
            reason = entry.reason
            print(entry, banner, reason)
            break

    # Prepare data
    ban_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    origin_guild_name = guild.name

    # Iterate through all servers the bot is in
    for g in bot.guilds:
        print("checking:", g.name)
        if g.id == guild.id:
            continue  # skip the server where the ban occurred

        # Check if banned user is in this server
        try:
            member = await g.fetch_member(user.id)  # ✅ await the coroutine
        except discord.NotFound:
            member = None
        if member:
            print("member of: ", g.name)
            channel = get_mod_alert_channel(g)
            print(channel)
            if channel:
                embed = discord.Embed(
                    title="🚨 Cross-Server Ban Alert",
                    color=discord.Color.red(),
                    timestamp=datetime.utcnow()
                )
                embed.add_field(name="Banned User", value=f"<@{user.id}> (`{user.id}`)", inline=False)
                embed.add_field(name="Banned From", value=f"{origin_guild_name}", inline=False)
                embed.add_field(name="Banned By:", value=f"{banner} (`{banner.id}`)" if banner else "Unknown", inline=False)
                embed.add_field(name="Reason", value=reason if reason else "No reason provided", inline=False)
                embed.set_footer(text=f"Ban detected: {ban_time}")
                print(embed)
                await channel.send(embed=embed)
        else:
            print("member not found")
# Run the bot
bot.run(BOT_TOKEN)
