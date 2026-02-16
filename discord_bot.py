import discord
from discord import app_commands
import random
import os
from PIL import Image, ImageDraw, ImageFont
import aiohttp
from io import BytesIO

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.members = True  # Needed for member autocomplete
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# Configuration
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
            async with session.get(str(user.display_avatar.url)) as resp:
                avatar_bytes = await resp.read()
            async with session.get(SPEECH_BUBBLE_IMAGE) as resp:
                if resp.status != 200:
                    raise Exception(f"Failed to download bubble: HTTP {resp.status}")
                bubble_bytes = await resp.read()
        
        avatar = Image.open(BytesIO(avatar_bytes)).convert("RGBA")
        bubble_orig = Image.open(BytesIO(bubble_bytes)).convert("RGBA")
        
        # --- Avatar: 120x120 circular ---
        avatar_size = 120
        avatar = avatar.resize((avatar_size, avatar_size), Image.Resampling.LANCZOS)
        mask = Image.new('L', (avatar_size, avatar_size), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, avatar_size, avatar_size), fill=255)
        avatar.putalpha(mask)
        
        # --- Fonts ---
        font = ImageFont.load_default(size=24)
        username_font = ImageFont.load_default(size=18)
        
        # --- Truncate text to prevent overflow ---
        max_chars = 200
        if len(quote_text) > max_chars:
            quote_text = quote_text[:max_chars - 3] + "..."
        
        # --- Text wrapping ---
        # The bubble interior padding (percentage of bubble size)
        # Adjust these based on your specific bubble image's border thickness
        h_padding_pct = 0.15  # 15% padding on each side
        v_padding_pct = 0.20  # 20% padding top/bottom
        
        # We'll target a bubble width and calculate text area from it
        target_bubble_width = 450
        text_area_width = int(target_bubble_width * (1 - 2 * h_padding_pct))
        
        draw_temp = ImageDraw.Draw(Image.new('RGBA', (1, 1)))
        lines = []
        words = quote_text.split()
        current_line = ""
        
        for word in words:
            test_line = current_line + word + " "
            bbox = draw_temp.textbbox((0, 0), test_line, font=font)
            if bbox[2] - bbox[0] <= text_area_width:
                current_line = test_line
            else:
                if current_line:
                    lines.append(current_line.strip())
                current_line = word + " "
        if current_line:
            lines.append(current_line.strip())
        
        # --- Scale bubble to fit text ---
        line_height = 32
        text_block_height = len(lines) * line_height
        
        # Required interior height for text + vertical padding
        required_interior_h = text_block_height
        target_bubble_height = int(required_interior_h / (1 - 2 * v_padding_pct))
        target_bubble_height = max(target_bubble_height, 150)  # minimum size
        
        # Scale bubble image to target size
        scale_x = target_bubble_width / bubble_orig.width
        scale_y = target_bubble_height / bubble_orig.height
        bubble = bubble_orig.resize(
            (target_bubble_width, target_bubble_height),
            Image.Resampling.LANCZOS
        )
        
        # --- Layout positions ---
        # Bubble tail points bottom-left, so avatar goes below-left of bubble
        padding = 20
        bubble_x = avatar_size + padding  # bubble starts to the right of avatar area
        bubble_y = padding
        
        # Avatar positioned at bottom-left, aligned with the tail
        # Adjust avatar_y so it sits near the bottom of the bubble where the tail is
        avatar_x = padding
        avatar_y = bubble_y + target_bubble_height - avatar_size + 10  # slight overlap with tail
        
        # --- Canvas ---
        canvas_width = bubble_x + target_bubble_width + padding
        canvas_height = max(avatar_y + avatar_size + 40, bubble_y + target_bubble_height + padding)
        canvas = Image.new('RGBA', (canvas_width, canvas_height), (0, 0, 0, 0))
        
        # Paste bubble and avatar
        canvas.paste(bubble, (bubble_x, bubble_y), bubble)
        canvas.paste(avatar, (avatar_x, avatar_y), avatar)
        
        # --- Draw quote text centered inside bubble ---
        draw = ImageDraw.Draw(canvas)
        
        text_area_x_start = bubble_x + int(target_bubble_width * h_padding_pct)
        text_area_y_start = bubble_y + int(target_bubble_height * v_padding_pct)
        # Center text block vertically in the text area
        text_area_inner_h = target_bubble_height - 2 * int(target_bubble_height * v_padding_pct)
        text_offset_y = text_area_y_start + (text_area_inner_h - text_block_height) // 2
        
        for i, line in enumerate(lines):
            bbox = draw.textbbox((0, 0), line, font=font)
            lw = bbox[2] - bbox[0]
            # Center each line horizontally in the text area
            text_x = text_area_x_start + (text_area_width - lw) // 2
            text_y = text_offset_y + i * line_height
            draw.text((text_x, text_y), line, font=font, fill=(255, 255, 255, 255))
        
        # --- Username below avatar ---
        name_text = user.display_name
        name_bbox = draw.textbbox((0, 0), name_text, font=username_font)
        name_w = name_bbox[2] - name_bbox[0]
        name_x = avatar_x + (avatar_size - name_w) // 2
        name_y = avatar_y + avatar_size + 5
        draw.text((name_x, name_y), name_text, font=username_font, fill=(255, 255, 255, 255))
        
        # Save
        output = BytesIO()
        canvas.save(output, format='PNG')
        output.seek(0)
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

@client.event
async def on_ready():
    await tree.sync()
    print(f'✅ Logged in as {client.user}')
    print(f'📝 Commands synced and ready!')
    if QUOTES_CHANNEL_ID:
        print(f'📜 Posting quotes to channel ID: {QUOTES_CHANNEL_ID}')
    else:
        print(f'⚠️  QUOTES_CHANNEL_ID not set!')

client.run(os.getenv('DISCORD_TOKEN'))
