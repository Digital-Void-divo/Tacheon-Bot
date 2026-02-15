import discord
from discord import app_commands
import random
import os
import asyncio
from datetime import datetime, timedelta, UTC

# Bot setup
intents = discord.Intents.default()
intents.message_content = True  # Needed to detect bump/boop messages
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# Bump/Boop tracking
bump_timer = None
boop_timer = None
bump_stats = {"count": 0, "last_user": None, "last_time": None}
boop_stats = {"count": 0, "last_user": None, "last_time": None}

# Configuration (set these via environment variables or hardcode)
BUMP_CHANNEL_ID = int(os.getenv('BUMP_CHANNEL_ID', '0'))  # Set in Railway
BUMP_ROLE_ID = int(os.getenv('BUMP_ROLE_ID', '0'))  # Set in Railway
BUMP_REMINDER_IMAGE = os.getenv('BUMP_REMINDER_IMAGE', '')  # URL to image
BUMP_THANKYOU_IMAGE = os.getenv('BUMP_THANKYOU_IMAGE', '')  # URL to image
BOOP_REMINDER_IMAGE = os.getenv('BOOP_REMINDER_IMAGE', '')  # URL to image
BOOP_THANKYOU_IMAGE = os.getenv('BOOP_THANKYOU_IMAGE', '')  # URL to image

# Your lists of responses
JOKES = [
    "Why do programmers prefer dark mode? Because light attracts bugs! 🐛",
    "Why did the developer go broke? Because they used up all their cache! 💸",
    "How many programmers does it take to change a light bulb? None, that's a hardware problem! 💡",
    "Why do Java developers wear glasses? Because they can't C#! 👓",
    "A SQL query walks into a bar, walks up to two tables and asks... 'Can I join you?' 🍺",
]

FACTS = [
    "Honey never spoils. Archaeologists have found 3000-year-old honey in Egyptian tombs that's still edible! 🍯",
    "Octopuses have three hearts and blue blood! 🐙",
    "Bananas are berries, but strawberries aren't! 🍌",
    "A group of flamingos is called a 'flamboyance'! 🦩",
    "The shortest war in history lasted only 38-45 minutes (Anglo-Zanzibar War, 1896)! ⚔️",
]

QUOTES = [
    "The only way to do great work is to love what you do. - Steve Jobs",
    "Code is like humor. When you have to explain it, it's bad. - Cory House",
    "First, solve the problem. Then, write the code. - John Johnson",
    "Simplicity is the soul of efficiency. - Austin Freeman",
    "Make it work, make it right, make it fast. - Kent Beck",
]

@tree.command(name="joke", description="Get a random programming joke")
async def joke(interaction: discord.Interaction):
    embed = discord.Embed(
        description=random.choice(JOKES),
        color=discord.Color.blue()
    )
    await interaction.response.send_message(embed=embed)

@tree.command(name="fact", description="Get a random fun fact")
async def fact(interaction: discord.Interaction):
    embed = discord.Embed(
        description=random.choice(FACTS),
        color=discord.Color.green()
    )
    await interaction.response.send_message(embed=embed)

@tree.command(name="quote", description="Get a random inspirational quote")
async def quote(interaction: discord.Interaction):
    embed = discord.Embed(
        description=random.choice(QUOTES),
        color=discord.Color.gold()
    )
    await interaction.response.send_message(embed=embed)

# Bump/Boop Timer Functions
async def start_bump_timer():
    """Start 2-hour timer for bump reminder"""
    global bump_timer
    if bump_timer:
        bump_timer.cancel()
    
    await asyncio.sleep(2 * 60 * 60)  # 2 hours
    
    # Post reminder
    if BUMP_CHANNEL_ID:
        channel = client.get_channel(BUMP_CHANNEL_ID)
        if channel:
            role_mention = f"<@&{BUMP_ROLE_ID}>" if BUMP_ROLE_ID else ""
            
            embed = discord.Embed(
                title="📢 Ready to Bump!",
                description=f"{role_mention}\n\nTime to bump the server on Disboard!\nUse `/bump` in this channel.",
                color=discord.Color.blue()
            )
            
            if BUMP_REMINDER_IMAGE:
                embed.set_image(url=BUMP_REMINDER_IMAGE)
            
            await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions(roles=True))

async def start_boop_timer():
    """Start 2-hour timer for boop reminder"""
    global boop_timer
    if boop_timer:
        boop_timer.cancel()
    
    await asyncio.sleep(2 * 60 * 60)  # 2 hours
    
    # Post reminder
    if BUMP_CHANNEL_ID:
        channel = client.get_channel(BUMP_CHANNEL_ID)
        if channel:
            role_mention = f"<@&{BUMP_ROLE_ID}>" if BUMP_ROLE_ID else ""
            
            embed = discord.Embed(
                title="📢 Ready to Boop!",
                description=f"{role_mention}\n\nTime to boop the server on Unfocused!\nUse `/boop` in this channel.",
                color=discord.Color.purple()
            )
            
            if BOOP_REMINDER_IMAGE:
                embed.set_image(url=BOOP_REMINDER_IMAGE)
            
            await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions(roles=True))

@client.event
async def on_message(message):
    """Detect Disboard bump and Unfocused boop success messages"""
    global bump_timer, boop_timer
    
    # Ignore messages from our own bot
    if message.author == client.user:
        return
    
    # Detect Disboard bump success (bot ID: 302050872383242240)
    if message.author.id == 302050872383242240:
        if message.embeds and len(message.embeds) > 0:
            embed = message.embeds[0]
            if embed.description and "Bump done!" in embed.description:
                user = message.interaction_metadata.user if message.interaction_metadata else None
                
                if user:
                    # Update stats
                    bump_stats["count"] += 1
                    bump_stats["last_user"] = user.id
                    bump_stats["last_time"] = datetime.now(UTC)
                    
                    # Post thank you
                    if BUMP_CHANNEL_ID:
                        channel = client.get_channel(BUMP_CHANNEL_ID)
                        if channel:
                            thank_embed = discord.Embed(
                                title="✅ Bump Successful!",
                                description=f"Thanks {user.mention} for bumping the server! 🎉\n\nNext bump available in 2 hours.",
                                color=discord.Color.green()
                            )
                            
                            if BUMP_THANKYOU_IMAGE:
                                thank_embed.set_image(url=BUMP_THANKYOU_IMAGE)
                            
                            await channel.send(embed=thank_embed)
                    
                    # Start timer
                    if bump_timer:
                        bump_timer.cancel()
                    bump_timer = asyncio.create_task(start_bump_timer())
    
    # Detect Unfocused boop success (bot ID: 835255643157168168)
    elif message.author.id == 835255643157168168:
        if message.embeds and len(message.embeds) > 0:
            embed = message.embeds[0]
            if embed.title and "Boop Success!" in embed.title:
                user = message.interaction_metadata.user if message.interaction_metadata else None
                
                if user:
                    # Update stats
                    boop_stats["count"] += 1
                    boop_stats["last_user"] = user.id
                    boop_stats["last_time"] = datetime.now(UTC)
                    
                    # Post thank you
                    if BUMP_CHANNEL_ID:
                        channel = client.get_channel(BUMP_CHANNEL_ID)
                        if channel:
                            thank_embed = discord.Embed(
                                title="✅ Boop Successful!",
                                description=f"Thanks {user.mention} for booping the server! 🎉\n\nNext boop available in 2 hours.",
                                color=discord.Color.green()
                            )
                            
                            if BOOP_THANKYOU_IMAGE:
                                thank_embed.set_image(url=BOOP_THANKYOU_IMAGE)
                            
                            await channel.send(embed=thank_embed)
                    
                    # Start timer
                    if boop_timer:
                        boop_timer.cancel()
                    boop_timer = asyncio.create_task(start_boop_timer())

@tree.command(name="bump_status", description="Check bump and boop timer status")
async def bump_status(interaction: discord.Interaction):
    """Show current status of bump/boop timers"""
    
    bump_info = "⏰ Ready to bump!"
    if bump_stats["last_time"]:
        time_since = datetime.now(UTC) - bump_stats["last_time"]
        time_until = timedelta(hours=2) - time_since
        if time_until.total_seconds() > 0:
            minutes = int(time_until.total_seconds() / 60)
            bump_info = f"⏳ Next bump in {minutes} minutes"
        last_user = f"<@{bump_stats['last_user']}>" if bump_stats["last_user"] else "Unknown"
        bump_info += f"\nLast bumped by: {last_user}"
    
    boop_info = "⏰ Ready to boop!"
    if boop_stats["last_time"]:
        time_since = datetime.now(UTC) - boop_stats["last_time"]
        time_until = timedelta(hours=2) - time_since
        if time_until.total_seconds() > 0:
            minutes = int(time_until.total_seconds() / 60)
            boop_info = f"⏳ Next boop in {minutes} minutes"
        last_user = f"<@{boop_stats['last_user']}>" if boop_stats["last_user"] else "Unknown"
        boop_info += f"\nLast booped by: {last_user}"
    
    embed = discord.Embed(
        title="📊 Bump/Boop Status",
        color=discord.Color.blue()
    )
    embed.add_field(name="Disboard Bump", value=bump_info, inline=False)
    embed.add_field(name="Unfocused Boop", value=boop_info, inline=False)
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

@tree.command(name="bump_stats", description="View bump and boop statistics")
async def bump_stats_command(interaction: discord.Interaction):
    """Show bump/boop statistics"""
    
    last_bumper = f"<@{bump_stats['last_user']}>" if bump_stats["last_user"] else "Nobody yet"
    last_booper = f"<@{boop_stats['last_user']}>" if boop_stats["last_user"] else "Nobody yet"
    
    embed = discord.Embed(
        title="📊 Bump/Boop Statistics",
        color=discord.Color.gold()
    )
    embed.add_field(
        name="📢 Disboard Bumps",
        value=f"**Total:** {bump_stats['count']}\n**Last Bumper:** {last_bumper}",
        inline=True
    )
    embed.add_field(
        name="📢 Unfocused Boops",
        value=f"**Total:** {boop_stats['count']}\n**Last Booper:** {last_booper}",
        inline=True
    )
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

@client.event
async def on_ready():
    await tree.sync()
    print(f'✅ Logged in as {client.user}')
    print(f'📝 Commands synced and ready!')
    print(f'⏰ Bump/Boop tracking active')
    if BUMP_CHANNEL_ID:
        print(f'📢 Posting reminders to channel ID: {BUMP_CHANNEL_ID}')
    else:
        print(f'⚠️  BUMP_CHANNEL_ID not set! Set it in Railway environment variables.')

# Run the bot
client.run(os.getenv('DISCORD_TOKEN'))
