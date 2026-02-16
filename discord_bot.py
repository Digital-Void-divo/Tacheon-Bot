import discord
from discord import app_commands
import random
import os
import asyncio
from datetime import datetime, timedelta, UTC
from PIL import Image, ImageDraw, ImageFont
import aiohttp
from io import BytesIO

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.members = True  # Needed for member autocomplete
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# Bump/Boop tracking
bump_timer = None
boop_timer = None
bump_stats = {"count": 0, "last_user": None, "last_time": None}
boop_stats = {"count": 0, "last_user": None, "last_time": None}

# Configuration
BUMP_CHANNEL_ID = int(os.getenv('BUMP_CHANNEL_ID', '0'))
BUMP_ROLE_ID = int(os.getenv('BUMP_ROLE_ID', '0'))
BUMP_REMINDER_IMAGE = os.getenv('BUMP_REMINDER_IMAGE', '')
BUMP_THANKYOU_IMAGE = os.getenv('BUMP_THANKYOU_IMAGE', '')
BOOP_REMINDER_IMAGE = os.getenv('BOOP_REMINDER_IMAGE', '')
BOOP_THANKYOU_IMAGE = os.getenv('BOOP_THANKYOU_IMAGE', '')
QUOTES_CHANNEL_ID = int(os.getenv('QUOTES_CHANNEL_ID', '0'))
SPEECH_BUBBLE_IMAGE = os.getenv('SPEECH_BUBBLE_IMAGE', '')

# Response lists
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

# Quote Modal
class QuoteModal(discord.ui.Modal, title="Submit a Quote"):
    quote_text = discord.ui.TextInput(
        label="What did they say?",
        style=discord.TextStyle.paragraph,
        placeholder="Enter the quote here...",
        required=True,
        max_length=500
    )
    
    def __init__(self, user: discord.Member):
        super().__init__()
        self.quoted_user = user
    
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        # Generate quote image
        try:
            image_bytes = await generate_quote_image(self.quoted_user, str(self.quote_text))
            
            # Post to quotes channel
            if QUOTES_CHANNEL_ID:
                channel = client.get_channel(QUOTES_CHANNEL_ID)
                if channel:
                    file = discord.File(fp=BytesIO(image_bytes), filename="quote.png")
                    await channel.send(
                        content=f"📜 Quote submitted by {interaction.user.mention}",
                        file=file
                    )
                    await interaction.followup.send("✅ Quote posted!", ephemeral=True)
                else:
                    await interaction.followup.send("❌ Quotes channel not found!", ephemeral=True)
            else:
                await interaction.followup.send("❌ QUOTES_CHANNEL_ID not configured!", ephemeral=True)
        except Exception as e:
            print(f"Error generating quote: {e}")
            await interaction.followup.send(f"❌ Error creating quote: {e}", ephemeral=True)

async def generate_quote_image(user: discord.Member, quote_text: str) -> bytes:
    """Generate a quote image with user avatar and speech bubble"""
    
    try:
        # Download user avatar
        async with aiohttp.ClientSession() as session:
            print(f"Downloading avatar from: {user.display_avatar.url}")
            async with session.get(str(user.display_avatar.url)) as resp:
                print(f"Avatar download status: {resp.status}")
                avatar_bytes = await resp.read()
            
            # Download speech bubble
            print(f"Downloading bubble from: {SPEECH_BUBBLE_IMAGE}")
            async with session.get(SPEECH_BUBBLE_IMAGE) as resp:
                print(f"Bubble download status: {resp.status}")
                if resp.status != 200:
                    raise Exception(f"Failed to download bubble: HTTP {resp.status}")
                bubble_bytes = await resp.read()
        
        print("Opening images with PIL...")
        # Open images
        avatar = Image.open(BytesIO(avatar_bytes)).convert("RGBA")
        bubble = Image.open(BytesIO(bubble_bytes)).convert("RGBA")
        
        print("Resizing avatar...")
        # Resize avatar to 300x300
        avatar = avatar.resize((300, 300), Image.Resampling.LANCZOS)
        
        # Create circular mask for avatar
        mask = Image.new('L', (300, 300), 0)
        draw_mask = ImageDraw.Draw(mask)
        draw_mask.ellipse((0, 0, 300, 300), fill=255)
        avatar.putalpha(mask)
        
        # Use even larger font sizes
        font = ImageFont.load_default(size=60)  # Increased from 40
        username_font = ImageFont.load_default(size=40)  # Increased from 32
        
        # Calculate text dimensions and wrap text
        bubble_width = bubble.width
        max_text_width = bubble_width - 200  # More padding for centering
        
        # Wrap text
        lines = []
        words = quote_text.split()
        current_line = ""
        
        draw_temp = ImageDraw.Draw(Image.new('RGBA', (1, 1)))
        for word in words:
            test_line = current_line + word + " "
            bbox = draw_temp.textbbox((0, 0), test_line, font=font)
            if bbox[2] - bbox[0] <= max_text_width:
                current_line = test_line
            else:
                if current_line:
                    lines.append(current_line.strip())
                current_line = word + " "
        if current_line:
            lines.append(current_line.strip())
        
        # Calculate required bubble height (less tall)
        line_height = 70  # Increased from 50
        text_height = len(lines) * line_height
        min_bubble_height = text_height + 200  # Padding
        
        # Scale bubble to better proportions (less tall)
        target_bubble_height = min(min_bubble_height, bubble.height * 0.7)  # Cap at 70% of original height
        if target_bubble_height < min_bubble_height:
            target_bubble_height = min_bubble_height
        
        scale_factor = target_bubble_height / bubble.height
        new_height = int(bubble.height * scale_factor)
        bubble = bubble.resize((int(bubble_width * scale_factor), new_height), Image.Resampling.LANCZOS)
        
        # Update bubble_width after resize
        bubble_width = bubble.width
        
        # Create final canvas - avatar bottom aligned with bubble
        canvas_width = 350 + bubble_width
        canvas_height = max(400, new_height + 100)  # Extra space for username
        canvas = Image.new('RGBA', (canvas_width, canvas_height), (0, 0, 0, 0))
        
        # Position bubble first (centered vertically)
        bubble_y = 50
        canvas.paste(bubble, (325, bubble_y), bubble)
        
        # Position avatar lower - aligned with bottom of bubble
        avatar_y = bubble_y + new_height - 200  # Avatar bottom aligns near bubble bottom
        canvas.paste(avatar, (25, avatar_y), avatar)
        
        # Draw text centered in bubble
        draw = ImageDraw.Draw(canvas)
        text_start_y = bubble_y + (new_height - text_height) // 2
        
        for i, line in enumerate(lines):
            bbox = draw.textbbox((0, 0), line, font=font)
            text_width = bbox[2] - bbox[0]
            text_x = 325 + (bubble_width - text_width) // 2
            text_y = text_start_y + (i * line_height)
            
            # Draw text with white color
            draw.text((text_x, text_y), line, font=font, fill=(255, 255, 255, 255))
        
        # Draw username below avatar
        name_bbox = draw.textbbox((0, 0), user.display_name, font=username_font)
        name_width = name_bbox[2] - name_bbox[0]
        name_x = 175 - (name_width // 2)
        name_y = avatar_y + 320
        draw.text((name_x, name_y), user.display_name, font=username_font, fill=(255, 255, 255, 255))
        
        # Save to bytes
        print("Saving to PNG...")
        output = BytesIO()
        canvas.save(output, format='PNG')
        output.seek(0)
        print("Quote image generated successfully!")
        return output.getvalue()
        
    except Exception as e:
        print(f"Error in generate_quote_image: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        raise

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

@tree.command(name="quote", description="Quote a server member")
async def quote(interaction: discord.Interaction, user: discord.Member):
    """Create a quote for a server member"""
    modal = QuoteModal(user)
    await interaction.response.send_modal(modal)

# Bump/Boop Timer Functions
async def start_bump_timer():
    """Start 2-hour timer for bump reminder"""
    global bump_timer
    if bump_timer:
        bump_timer.cancel()
    
    await asyncio.sleep(2 * 60 * 60)
    
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
    
    await asyncio.sleep(2 * 60 * 60)
    
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
    
    if message.author == client.user:
        return
    
    # Detect Disboard bump success
    if message.author.id == 302050872383242240:
        print(f"Detected Disboard message")
        if message.embeds and len(message.embeds) > 0:
            embed = message.embeds[0]
            print(f"Embed description: {embed.description}")
            
            if embed.description and "bump done" in embed.description.lower():
                print(f"Bump success detected!")
                user = message.interaction_metadata.user if message.interaction_metadata else None
                print(f"User: {user}")
                
                if user:
                    bump_stats["count"] += 1
                    bump_stats["last_user"] = user.id
                    bump_stats["last_time"] = datetime.now(UTC)
                    
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
                    
                    if bump_timer:
                        bump_timer.cancel()
                    bump_timer = asyncio.create_task(start_bump_timer())
    
    # Detect Unfocused boop success
    elif message.author.id == 835255643157168168:
        print(f"Detected Unfocused message")
        if message.embeds and len(message.embeds) > 0:
            embed = message.embeds[0]
            print(f"Embed title: {embed.title}")
            print(f"Embed description: {embed.description}")
            
            if embed.title and "boop success" in embed.title.lower():
                print(f"Boop success detected!")
                user = message.interaction_metadata.user if message.interaction_metadata else None
                print(f"User: {user}")
                
                if user:
                    boop_stats["count"] += 1
                    boop_stats["last_user"] = user.id
                    boop_stats["last_time"] = datetime.now(UTC)
                    
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
        print(f'⚠️  BUMP_CHANNEL_ID not set!')
    if QUOTES_CHANNEL_ID:
        print(f'📜 Posting quotes to channel ID: {QUOTES_CHANNEL_ID}')
    else:
        print(f'⚠️  QUOTES_CHANNEL_ID not set!')

client.run(os.getenv('DISCORD_TOKEN'))
