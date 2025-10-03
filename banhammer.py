import discord
from discord.ext import commands, tasks
import json
import os
import asyncio
from dotenv import load_dotenv


# Load environment variables from .env file
load_dotenv()
BOT_TOKEN = os.getenv('discord')
QUARANTINE_ROLE_NAME = "Quarantine"
MOD_CHANNEL_NAME = "mod_alerts"
SERVER_WORDS_FILE = "server_banned_words.json"

# Universal banned words (applied to all servers)
UNIVERSAL_BANNED_WORDS = ["mod", "admin", "staff"]

# ----- Load server-specific banned words -----
def load_server_words():
    if os.path.exists(SERVER_WORDS_FILE):
        with open(SERVER_WORDS_FILE, "r") as f:
            return json.load(f)
    return {}

def save_server_words(data):
    with open(SERVER_WORDS_FILE, "w") as f:
        json.dump(data, f, indent=2)

server_banned_words = load_server_words()

# ----- Bot Setup -----
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ----- Quarantine Check -----
async def check_banned_words(member):
    guild_id = str(member.guild.id)
    server_words = server_banned_words.get(guild_id, [])
    words_to_check = [w.lower() for w in UNIVERSAL_BANNED_WORDS + server_words]

    # Fetch user profile for bio
    try:
        user_profile = await bot.fetch_user(member.id)
        bio = getattr(user_profile, "bio", "") or ""
    except:
        bio = ""

    text_to_check = f"{member.display_name} {bio}".lower()
    return any(word in text_to_check for word in words_to_check)

async def quarantine_member(member):
    quarantine_role = discord.utils.get(member.guild.roles, name=QUARANTINE_ROLE_NAME)
    if quarantine_role and quarantine_role not in member.roles:
        await member.add_roles(quarantine_role)

    # Send message to moderator channel
    mod_channel = discord.utils.get(member.guild.text_channels, name=MOD_CHANNEL_NAME)
    if mod_channel:
        embed = discord.Embed(
            title="Member Quarantined",
            description=f"{member.mention} has been quarantined for potential banned words.",
            color=discord.Color.orange()
        )
        embed.add_field(name="Display Name", value=member.display_name, inline=False)
        bio_text = getattr(await bot.fetch_user(member.id), "bio", "None")
        embed.add_field(name="Bio", value=bio_text, inline=False)

        # Buttons
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="Unquarantine", style=discord.ButtonStyle.green, custom_id=f"unq_{member.id}"))
        view.add_item(discord.ui.Button(label="Ban", style=discord.ButtonStyle.red, custom_id=f"ban_{member.id}"))
        await mod_channel.send(embed=embed, view=view)

# ----- Event: Member Join -----
@bot.event
async def on_member_join(member):
    if await check_banned_words(member):
        await quarantine_member(member)

# ----- Scan existing members on startup -----
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    for guild in bot.guilds:
        print(f"Scanning existing members in {guild.name}...")
        for member in guild.members:
            if await check_banned_words(member):
                await quarantine_member(member)
        print(f"Finished scanning {guild.name}")

# ----- Button Interaction -----
@bot.event
async def on_interaction(interaction: discord.Interaction):
    custom_id = interaction.data.get("custom_id")
    if not custom_id:
        return

    if custom_id.startswith("unq_") or custom_id.startswith("ban_"):
        member_id = int(custom_id.split("_")[1])
        guild = interaction.guild
        member = guild.get_member(member_id)
        if not member:
            await interaction.response.send_message("Member not found", ephemeral=True)
            return

        if custom_id.startswith("unq_"):
            quarantine_role = discord.utils.get(guild.roles, name=QUARANTINE_ROLE_NAME)
            if quarantine_role in member.roles:
                await member.remove_roles(quarantine_role)
            await interaction.response.send_message(f"{member.display_name} removed from quarantine.", ephemeral=True)

        elif custom_id.startswith("ban_"):
            await member.ban(reason="Banned by moderator")
            await interaction.response.send_message(f"{member.display_name} has been banned.", ephemeral=True)

# ----- Admin Commands -----
@bot.command()
@commands.has_permissions(administrator=True)
async def addword(ctx, *, word):
    guild_id = str(ctx.guild.id)
    server_banned_words.setdefault(guild_id, [])
    if word.lower() not in server_banned_words[guild_id]:
        server_banned_words[guild_id].append(word.lower())
        save_server_words(server_banned_words)
        await ctx.send(f"Added server banned word: {word}")
    else:
        await ctx.send(f"Word already in server list: {word}")

@bot.command()
@commands.has_permissions(administrator=True)
async def removeword(ctx, *, word):
    guild_id = str(ctx.guild.id)
    if guild_id in server_banned_words and word.lower() in server_banned_words[guild_id]:
        server_banned_words[guild_id].remove(word.lower())
        save_server_words(server_banned_words)
        await ctx.send(f"Removed server banned word: {word}")
    else:
        await ctx.send(f"Word not found in server list: {word}")

@bot.command()
@commands.has_permissions(administrator=True)
async def listwords(ctx):
    guild_id = str(ctx.guild.id)
    words = server_banned_words.get(guild_id, [])
    await ctx.send(f"Server banned words: {', '.join(words) if words else 'None'}")

# ----- Run -----
bot.run(BOT_TOKEN)