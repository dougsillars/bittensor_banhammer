import discord
from discord.ext import commands
import asyncpg
from datetime import datetime, timezone
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()
BOT_TOKEN = os.getenv('discord')
MOD_CHANNEL_NAME = "mod_alerts"
POSTGRES_USER = os.getenv('postgres_user')
POSTGRES_PASSWORD = os.getenv('postgres_password')
POSTGRES_DB = "discordbot"
POSTGRES_HOST = "localhost"

intents = discord.Intents.default()
intents.members = True  # needed to check members across servers
intents.message_content = True  # Required for message content
intents.guilds = True
intents.bans = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Example: create a global pool on bot startup
bot.pg_pool = None

# --- Guild autoban settings (could later be replaced with a database) ---
autoban_settings = {}  # guild.id -> "off" | "on" | "scam"

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    
    # Create a connection pool
    bot.pg_pool = await asyncpg.create_pool(
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
        database=POSTGRES_DB,
        host=POSTGRES_HOST,
        min_size=1,
        max_size=5
    )
    print("Connected to Postgres!")

    # Load existing guild settings into memory
    async with bot.pg_pool.acquire() as conn:
        rows = await conn.fetch("SELECT guild_id, autoban_mode FROM guild_settings;")
        for row in rows:
            autoban_settings[row['guild_id']] = row['autoban_mode']
    print(f"Loaded {len(autoban_settings)} guild settings into memory.")



# Helper function to find #mod-alerts channel
def get_mod_alert_channel(guild: discord.Guild):
    for channel in guild.text_channels:
        if channel.name == MOD_CHANNEL_NAME:
            return channel
    return None

# --- Command to set autoban mode ---
@bot.command(name="autoban")
@commands.has_permissions(administrator=True)
async def set_autoban(ctx, mode: str):
    mode = mode.lower()
    if mode not in ["off", "on", "scam"]:
        await ctx.send("Usage: `!autoban off|on|scam`")
        return

    autoban_settings[ctx.guild.id] = mode
    # Insert or update the database
    async with bot.pg_pool.acquire() as conn:
        result = await conn.execute("""
            INSERT INTO guild_settings (guild_id, autoban_mode)
            VALUES ($1, $2)
            ON CONFLICT (guild_id) DO UPDATE
            SET autoban_mode = EXCLUDED.autoban_mode
        """, ctx.guild.id, mode)

    await ctx.send(f"✅ Autoban mode set to **{mode.upper()}** for this server.")
    print("DB result:", result)
@set_autoban.error
async def set_autoban_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("Usage: `!autoban off|on|scam`")
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send("You need **Administrator** permissions to set autoban mode.")

#command to get the autoban value
@bot.command(name="getautoban")
async def get_autoban(ctx):
    mode = autoban_settings.get(ctx.guild.id, "off")
    await ctx.send(f"Current autoban mode for this server is **{mode.upper()}**.")

#command to search bans
@bot.command(name="searchban")
@commands.has_permissions(administrator=True)
async def search_ban(ctx, user_id: int):
    """Search the ban_records table for a specific user ID."""
    async with bot.pg_pool.acquire() as conn:
        record = await conn.fetchrow("""
            SELECT user_id, origin_guild_id, banner_id, reason, ban_time
            FROM ban_records
            WHERE user_id = $1
            ORDER BY ban_time DESC
            LIMIT 1
        """, user_id)

    if not record:
        await ctx.send(f"❌ No ban record found for user ID `{user_id}`.")
        return

    # Get readable info
    origin_guild = bot.get_guild(record["origin_guild_id"])
    guild_name = origin_guild.name if origin_guild else f"Unknown ({record['origin_guild_id']})"

    banner_name = "Unknown"
    if record["banner_id"]:
        banner_user = bot.get_user(record["banner_id"])
        if banner_user:
            banner_name = f"{banner_user} (`{record['banner_id']}`)"
        else:
            banner_name = f"Unknown (`{record['banner_id']}`)"

    reason = record["reason"] or "No reason provided"
    ban_time = record["ban_time"].strftime("%Y-%m-%d %H:%M UTC")

    embed = discord.Embed(
        title="🔍 Ban Record Found",
        color=discord.Color.orange(),
        timestamp=datetime.utcnow()
    )
    embed.add_field(name="User ID", value=f"`{record['user_id']}`", inline=False)
    embed.add_field(name="Origin Server", value=guild_name, inline=False)
    embed.add_field(name="Banned By", value=banner_name, inline=False)
    embed.add_field(name="Reason", value=reason, inline=False)
    embed.add_field(name="Ban Time", value=ban_time, inline=False)
    await ctx.send(embed=embed)

#remove user from the banned DB
#alert all servers that it was removed
@bot.command(name="removeban")
@commands.has_permissions(administrator=True)
async def remove_ban(ctx, user_id: int):
    """Remove a ban record from the database and alert all servers."""

    async with bot.pg_pool.acquire() as conn:
        # Check if record exists
        record = await conn.fetchrow("""
            SELECT user_id, origin_guild_id, banner_id, reason, ban_time
            FROM ban_records
            WHERE user_id = $1
            ORDER BY ban_time DESC
            LIMIT 1
        """, user_id)

        if not record:
            await ctx.send(f"❌ No ban record found for user ID `{user_id}`.")
            return

        # Delete all records for that user
        deleted = await conn.execute("""
            DELETE FROM ban_records
            WHERE user_id = $1
        """, user_id)

    # Notify the command server
    embed = discord.Embed(
        title="✅ Ban Record Removed",
        description=f"User ID `{user_id}` has been removed from the ban database.",
        color=discord.Color.green(),
        timestamp=datetime.utcnow()
    )
    embed.add_field(name="Deleted Records", value=deleted, inline=False)
    await ctx.send(embed=embed)

    # --- Broadcast to all servers ---
    # Customize the alert format as you like
    alert_embed = discord.Embed(
        title="🚨 Cross-Server Ban Removal Alert",
        color=discord.Color.green(),
        timestamp=datetime.utcnow()
    )

    user_mention = f"<@{user_id}>"
    origin_guild_name = "Unknown"
    if record["origin_guild_id"]:
        origin_guild = bot.get_guild(record["origin_guild_id"])
        if origin_guild:
            origin_guild_name = origin_guild.name

    alert_embed.add_field(name="Unbanned User", value=f"{user_mention} (`{user_id}`)", inline=False)
    alert_embed.add_field(name="Origin Server", value=origin_guild_name, inline=False)
    alert_embed.add_field(name="Removed By", value=f"{ctx.author} (`{ctx.author.id}`)", inline=False)
    alert_embed.set_footer(text="Ban record removed from shared database")

    # Send alert to a specific channel in each server
    # (replace CHANNEL_ID_HERE with your actual alert channel ID)

    for guild in bot.guilds:
        # Try to find a channel named "ban-alerts"
        channel = discord.utils.get(guild.text_channels, name=MOD_CHANNEL_NAME)
        if channel and channel.permissions_for(guild.me).send_messages:
            try:
                await channel.send(embed=alert_embed)
            except Exception as e:
                print(f"Failed to send alert to {guild.name}: {e}")

    print(f"✅ Unban alert broadcasted for user {user_id}")


# --- Main handler for bans ---
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


    # Check if this ban is already in the database
    async with bot.pg_pool.acquire() as conn:
        exists = await conn.fetchval("""
            SELECT 1 FROM ban_records
            WHERE user_id = $1 AND origin_guild_id = $2
        """, user.id, guild.id)

        if exists:
            print(f"User {user.id} already recorded as banned from {guild.name}. Skipping.")
            return  # already processed, do nothing

        # Insert the new ban record
        await conn.execute("""
            INSERT INTO ban_records (user_id, origin_guild_id, banner_id, reason)
            VALUES ($1, $2, $3, $4)
        """, user.id, guild.id, banner.id if banner else None, reason)

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
                print(f"{user.id} banned from {origin_guild_name} by {banner} for {reason}")
                await channel.send(embed=embed)
                
                # Check the guild's autoban setting
                mode = autoban_settings.get(g.id, "off")
                should_ban = False

                if mode == "on":
                    should_ban = True
                elif mode == "scam" and reason and "scam" in reason.lower():
                    should_ban = True

                if should_ban:
                    try:
                        await g.ban(user, reason=f"[Auto-ban from {origin_guild_name}] {reason or 'No reason provided'}")
                        await channel.send(f"🤖 Auto-banned <@{user.id}> due to setting: **{mode.upper()}**")
                    except discord.Forbidden:
                        await channel.send("⚠️ I don’t have permission to ban this user.")
                    except Exception as e:
                        await channel.send(f"⚠️ Failed to autoban: `{e}`")
        else:
            print("member not found")

#on user join - see if they are in the ban list
@bot.event
async def on_member_join(member: discord.Member):
    """Check if a joining user has been banned elsewhere."""
    user_id = member.id
    guild = member.guild

    # Skip bots
    if member.bot:
        return

    # --- Query database for any prior bans ---
    async with bot.pg_pool.acquire() as conn:
        record = await conn.fetchrow("""
            SELECT user_id, origin_guild_id, banner_id, reason, ban_time
            FROM ban_records
            WHERE user_id = $1
            ORDER BY ban_time DESC
            LIMIT 1
        """, user_id)

    if not record:
        return  # user has no prior bans

    reason = record["reason"] or "No reason provided"
    origin_guild = bot.get_guild(record["origin_guild_id"])
    origin_name = origin_guild.name if origin_guild else f"Guild {record['origin_guild_id']}"
    ban_time = record["ban_time"].strftime("%Y-%m-%d %H:%M UTC")

    # --- Get guild's autoban setting ---
    mode = autoban_settings.get(guild.id, "off")
    should_ban = False

    if mode == "on":
        should_ban = True
    elif mode == "scam" and "scam" in reason.lower():
        should_ban = True

    # --- Always alert mods ---
    channel = get_mod_alert_channel(guild)
    if channel:
        embed = discord.Embed(
            title="⚠️ User with Prior Ban Joined",
            color=discord.Color.orange(),
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="User", value=f"<@{user_id}> (`{user_id}`)", inline=False)
        embed.add_field(name="Origin Server", value=origin_name, inline=False)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.add_field(name="Original Ban Time", value=ban_time, inline=False)
        embed.add_field(name="Current Autoban Mode", value=mode.upper(), inline=False)
        await channel.send(embed=embed)

    # --- Apply autoban if mode requires it ---
    if should_ban:
        ban_reason = f"[Auto-ban on join] Previously banned from {origin_name}: {reason}"
        try:
            await guild.ban(member, reason=ban_reason)
            if channel:
                await channel.send(f"🤖 Auto-banned <@{user_id}> due to mode: **{mode.upper()}**")
        except discord.Forbidden:
            if channel:
                await channel.send(f"⚠️ I don’t have permission to ban <@{user_id}>.")
        except Exception as e:
            if channel:
                await channel.send(f"⚠️ Failed to autoban <@{user_id}>: `{e}`")


# Run the bot
bot.run(BOT_TOKEN)
