# Discord Bot - Quick Setup 🤖

A simple Discord bot with slash commands for jokes, facts, and quotes!

## Commands
- `/joke` - Random programming joke
- `/fact` - Random fun fact  
- `/quote` - Random inspirational quote

## Setup

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Run the bot:**
   ```bash
   python discord_bot.py
   ```

3. **Invite to your server:**
   - Go to Discord Developer Portal → Your App → OAuth2 → URL Generator
   - Select `bot` and `applications.commands` scopes
   - Select `Send Messages` permission
   - Use the generated URL to invite the bot

## Customizing

Just edit the `JOKES`, `FACTS`, and `QUOTES` lists in `discord_bot.py` to add your own!

Enjoy! 🎉
