import discord
from discord import app_commands
import random
import os
import json
from PIL import Image, ImageDraw, ImageFont
import aiohttp
from io import BytesIO

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# Configuration
QUOTES_CHANNEL_ID = int(os.getenv('QUOTES_CHANNEL_ID', '0'))
SPEECH_BUBBLE_IMAGE = os.getenv('SPEECH_BUBBLE_IMAGE', '')
FEEDBACK_CHANNEL_ID = int(os.getenv('FEEDBACK_CHANNEL_ID', '0'))

# --- Welcome DM Storage ---
# welcome_dm.json stores:
#   "message": "the welcome text"
#   "enabled": true/false
WELCOME_DM_FILE = "welcome_dm.json"

def load_welcome_dm() -> dict:
    if os.path.exists(WELCOME_DM_FILE):
        with open(WELCOME_DM_FILE, "r") as f:
            return json.load(f)
    return {"message": None, "enabled": False}

def save_welcome_dm(data: dict):
    with open(WELCOME_DM_FILE, "w") as f:
        json.dump(data, f, indent=2)

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

# ---------------------------------------------------------------------------
# Quote Modal
# ---------------------------------------------------------------------------
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
        try:
            image_bytes = await generate_quote_image(self.quoted_user, str(self.quote_text))
            if QUOTES_CHANNEL_ID:
                channel = client.get_channel(QUOTES_CHANNEL_ID)
                if channel:
                    file = discord.File(fp=BytesIO(image_bytes), filename="quote.png")
                    await channel.send(
                        content=f"📜 {self.quoted_user.mention}'s quote submitted by {interaction.user.mention}",
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

# ---------------------------------------------------------------------------
# Feedback Modal
# ---------------------------------------------------------------------------
class FeedbackModal(discord.ui.Modal, title="Anonymous Feedback"):
    feedback_text = discord.ui.TextInput(
        label="Your feedback",
        style=discord.TextStyle.paragraph,
        placeholder="Share your thoughts — this is completely anonymous...",
        required=True,
        max_length=1000
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if FEEDBACK_CHANNEL_ID:
            channel = client.get_channel(FEEDBACK_CHANNEL_ID)
            if channel:
                embed = discord.Embed(
                    title="📬 Anonymous Feedback",
                    description=str(self.feedback_text),
                    color=discord.Color.blurple()
                )
                await channel.send(embed=embed)
                await interaction.followup.send(
                    "✅ Your feedback was sent anonymously. Thanks!", ephemeral=True
                )
            else:
                await interaction.followup.send("❌ Feedback channel not found!", ephemeral=True)
        else:
            await interaction.followup.send("❌ FEEDBACK_CHANNEL_ID not configured!", ephemeral=True)

# ---------------------------------------------------------------------------
# Welcome DM Modal
# ---------------------------------------------------------------------------
class WelcomeDMModal(discord.ui.Modal, title="Set Welcome DM Message"):
    message = discord.ui.TextInput(
        label="Welcome message",
        style=discord.TextStyle.paragraph,
        placeholder="Write what new members will receive when they join...",
        required=True,
        max_length=2000
    )

    async def on_submit(self, interaction: discord.Interaction):
        data = load_welcome_dm()
        data["message"] = str(self.message)
        data["enabled"] = True
        save_welcome_dm(data)
        await interaction.response.send_message(
            "✅ Welcome DM set and enabled. New members will receive this message when they join.",
            ephemeral=True
        )

# ---------------------------------------------------------------------------
# Image generation
# ---------------------------------------------------------------------------
async def generate_quote_image(user: discord.Member, quote_text: str) -> bytes:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(str(user.display_avatar.url)) as resp:
                avatar_bytes = await resp.read()
            async with session.get(SPEECH_BUBBLE_IMAGE) as resp:
                if resp.status != 200:
                    raise Exception(f"Failed to download bubble: HTTP {resp.status}")
                bubble_bytes = await resp.read()

        avatar = Image.open(BytesIO(avatar_bytes)).convert("RGBA")
        bubble_orig = Image.open(BytesIO(bubble_bytes)).convert("RGBA")

        avatar_size = 120
        avatar = avatar.resize((avatar_size, avatar_size), Image.Resampling.LANCZOS)
        mask = Image.new('L', (avatar_size, avatar_size), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, avatar_size, avatar_size), fill=255)
        avatar.putalpha(mask)

        font = ImageFont.load_default(size=24)
        username_font = ImageFont.load_default(size=18)

        max_chars = 200
        if len(quote_text) > max_chars:
            quote_text = quote_text[:max_chars - 3] + "..."

        line_height = 28
        h_pad_left = 0.15
        h_pad_right = 0.075
        v_pad_px = 100

        draw_temp = ImageDraw.Draw(Image.new('RGBA', (1, 1)))

        def wrap_text(text, max_width):
            lines = []
            words = text.split()
            current_line = ""
            for word in words:
                test_line = current_line + word + " "
                bbox = draw_temp.textbbox((0, 0), test_line, font=font)
                if bbox[2] - bbox[0] <= max_width:
                    current_line = test_line
                else:
                    if current_line:
                        lines.append(current_line.strip())
                    current_line = word + " "
            if current_line:
                lines.append(current_line.strip())
            return lines

        best_width = 450
        best_ratio_diff = float('inf')

        for test_width in range(350, 750, 10):
            text_area_w = int(test_width * (1 - h_pad_left - h_pad_right))
            test_lines = wrap_text(quote_text, text_area_w)
            text_block_h = len(test_lines) * line_height
            test_height = max(text_block_h + v_pad_px, 150)
            ratio = test_width / test_height
            diff = abs(ratio - 3.0)
            if diff < best_ratio_diff:
                best_ratio_diff = diff
                best_width = test_width

        target_bubble_width = max(best_width, 300)
        text_area_width = int(target_bubble_width * (1 - h_pad_left - h_pad_right))
        lines = wrap_text(quote_text, text_area_width)
        text_block_height = len(lines) * line_height
        target_bubble_height = max(text_block_height + v_pad_px, 120)

        bubble = bubble_orig.resize(
            (target_bubble_width, target_bubble_height),
            Image.Resampling.LANCZOS
        )

        padding = 20
        bubble_x = avatar_size + padding
        bubble_y = padding
        avatar_x = padding
        avatar_y = bubble_y + target_bubble_height - avatar_size + 10

        canvas_width = bubble_x + target_bubble_width + padding
        canvas_height = max(avatar_y + avatar_size + 40, bubble_y + target_bubble_height + padding)
        canvas = Image.new('RGBA', (canvas_width, canvas_height), (0, 0, 0, 0))

        canvas.paste(bubble, (bubble_x, bubble_y), bubble)
        canvas.paste(avatar, (avatar_x, avatar_y), avatar)

        draw = ImageDraw.Draw(canvas)
        text_area_x_start = bubble_x + int(target_bubble_width * h_pad_left)
        text_offset_y = bubble_y + (target_bubble_height - text_block_height) // 3

        for i, line in enumerate(lines):
            bbox = draw.textbbox((0, 0), line, font=font)
            lw = bbox[2] - bbox[0]
            text_x = text_area_x_start + (text_area_width - lw) // 2
            text_y = text_offset_y + i * line_height
            draw.text((text_x, text_y), line, font=font, fill=(255, 255, 255, 255))

        name_text = user.display_name
        name_bbox = draw.textbbox((0, 0), name_text, font=username_font)
        name_w = name_bbox[2] - name_bbox[0]
        name_x = avatar_x + (avatar_size - name_w) // 2
        name_y = avatar_y + avatar_size + 5
        draw.text((name_x, name_y), name_text, font=username_font, fill=(255, 255, 255, 255))

        output = BytesIO()
        canvas.save(output, format='PNG')
        output.seek(0)
        return output.getvalue()

    except Exception as e:
        print(f"Error in generate_quote_image: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        raise

# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------
@client.event
async def on_ready():
    await tree.sync()
    print(f'✅ Logged in as {client.user}')
    print(f'📝 Commands synced and ready!')
    if QUOTES_CHANNEL_ID:
        print(f'📜 Posting quotes to channel ID: {QUOTES_CHANNEL_ID}')
    else:
        print(f'⚠️  QUOTES_CHANNEL_ID not set!')
    if FEEDBACK_CHANNEL_ID:
        print(f'📬 Posting feedback to channel ID: {FEEDBACK_CHANNEL_ID}')
    else:
        print(f'⚠️  FEEDBACK_CHANNEL_ID not set!')
    welcome_data = load_welcome_dm()
    if welcome_data["enabled"] and welcome_data["message"]:
        print(f'👋 Welcome DM is enabled.')
    else:
        print(f'⚠️  Welcome DM is not configured or disabled.')


@client.event
async def on_member_join(member: discord.Member):
    """Send a welcome DM to every new member if configured."""
    if member.bot:
        return

    data = load_welcome_dm()
    if not data.get("enabled") or not data.get("message"):
        return

    embed = discord.Embed(
        title=f"👋 Welcome to {member.guild.name}!",
        description=data["message"],
        color=discord.Color.teal()
    )
    embed.set_thumbnail(url=member.guild.icon.url if member.guild.icon else None)
    embed.set_footer(text=f"Sent by {member.guild.name} staff")

    try:
        await member.send(embed=embed)
    except discord.Forbidden:
        # Member has DMs closed — nothing we can do
        print(f"⚠️  Could not DM {member} (DMs likely closed).")

# ---------------------------------------------------------------------------
# Slash commands
# ---------------------------------------------------------------------------
@tree.command(name="joke", description="Get a random programming joke")
async def joke(interaction: discord.Interaction):
    embed = discord.Embed(description=random.choice(JOKES), color=discord.Color.blue())
    await interaction.response.send_message(embed=embed)


@tree.command(name="fact", description="Get a random fun fact")
async def fact(interaction: discord.Interaction):
    embed = discord.Embed(description=random.choice(FACTS), color=discord.Color.green())
    await interaction.response.send_message(embed=embed)


@tree.command(name="quote", description="Quote a server member")
async def quote(interaction: discord.Interaction, user: discord.Member):
    modal = QuoteModal(user)
    await interaction.response.send_modal(modal)


@tree.command(name="feedback", description="Send anonymous feedback to the mods")
async def feedback(interaction: discord.Interaction):
    modal = FeedbackModal()
    await interaction.response.send_modal(modal)


@tree.command(name="set-welcome-dm", description="Set the DM new members receive when joining (admin only)")
@app_commands.checks.has_permissions(manage_guild=True)
async def set_welcome_dm(interaction: discord.Interaction):
    modal = WelcomeDMModal()
    await interaction.response.send_modal(modal)


@tree.command(name="preview-welcome-dm", description="Preview the current welcome DM (admin only)")
@app_commands.checks.has_permissions(manage_guild=True)
async def preview_welcome_dm(interaction: discord.Interaction):
    data = load_welcome_dm()
    if not data.get("message"):
        await interaction.response.send_message("ℹ️ No welcome DM is configured yet.", ephemeral=True)
        return

    embed = discord.Embed(
        title=f"👋 Welcome to {interaction.guild.name}!",
        description=data["message"],
        color=discord.Color.teal()
    )
    embed.set_thumbnail(url=interaction.guild.icon.url if interaction.guild.icon else None)
    embed.set_footer(text=f"Sent by {interaction.guild.name} staff")
    status = "✅ Enabled" if data.get("enabled") else "⏸️ Disabled"
    await interaction.response.send_message(
        content=f"**Welcome DM Preview** — Status: {status}",
        embed=embed,
        ephemeral=True
    )


@tree.command(name="toggle-welcome-dm", description="Enable or disable the welcome DM without deleting it (admin only)")
@app_commands.checks.has_permissions(manage_guild=True)
async def toggle_welcome_dm(interaction: discord.Interaction):
    data = load_welcome_dm()
    if not data.get("message"):
        await interaction.response.send_message(
            "ℹ️ No welcome DM is configured yet. Use `/set-welcome-dm` first.", ephemeral=True
        )
        return
    data["enabled"] = not data.get("enabled", False)
    save_welcome_dm(data)
    state = "✅ enabled" if data["enabled"] else "⏸️ disabled"
    await interaction.response.send_message(f"Welcome DM is now {state}.", ephemeral=True)


@set_welcome_dm.error
@preview_welcome_dm.error
@toggle_welcome_dm.error
async def admin_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message(
            "❌ You need the **Manage Server** permission to use this command.", ephemeral=True
        )


client.run(os.getenv('DISCORD_TOKEN'))
