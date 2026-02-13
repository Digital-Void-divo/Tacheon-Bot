import discord
from discord import app_commands
import random
import os

# Bot setup
intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

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

@client.event
async def on_ready():
    await tree.sync()
    print(f'✅ Logged in as {client.user}')
    print(f'📝 Commands synced and ready!')

# Run the bot
client.run(os.getenv('DISCORD_TOKEN'))
