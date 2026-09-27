# Meeple Bot — Deployment Guide

## What's new (Message Visibility update)

### New `/config → 👁️ Messages` panel
Configure how long each bot message stays visible in the channel — or keep it permanent.

| Setting | Default | Description |
|---------|---------|-------------|
| ✅ Share Reward | Permanent | Reply when a share is validated |
| ❌ Share Rejection | Permanent | Rejection notice when ❌ is clicked |
| 💎 Reaction Bonus | Permanent | Gems bonus notification |
| ⏱️ React Cooldown | Permanent | Cooldown warning (was hardcoded 10s) |
| 🚫 Block Message | Permanent | "Message blocked" notice |
| 💰 /gems | Permanent | Balance embed from `/gems` |
| 🛒 /shop | Permanent | Shop embed from `/shop` |
| 🏆 /leaderboard | Permanent | Leaderboard from `/leaderboard` |

Set **0** for permanent, or any positive number of seconds to auto-delete.

---

## Shop and daily quest updates

- **Guided shop item setup:** enter the name, base price, image, time listed, and
  post-purchase duration first. Optional settings let managers add required
  customer text, provider credit, reward codes, approval, and a per-member limit.
- **Separate expiration timers:** a listing can expire and disappear from the
  shop independently of how long a purchased item lasts. Expired listings are
  also rejected if a member has an old shop page open.
- **Purchase limits:** new items default to one purchase per member. The limit
  is hidden from members; managers can change it or set `0` for unlimited.
- **Shop discount:** configure a guild-wide discount from the Shop settings.
  The discounted price appears in the shop and is the amount charged, including
  approval-based purchases.
- **New-item DMs:** after an item has gone 20 minutes without edits, members
  with the configured Drops role receive one DM. Edits and added/changed reward
  codes restart the quiet period. Gems Owners are excluded, even if they also
  belong to the Drops role.
- **Meeple daily quest:** the ping quest now completes when a member mentions
  the bot in the configured daily-quest chat channel. Meeple replies with a
  varied response and grants the quest reward.

---

## Deployment (Render)

### 1. Push to GitHub
Push the contents of this `deploy/` folder to a new GitHub repository.

### 2. Create a Render Web Service
1. On [render.com](https://render.com), click **New → Web Service**
2. Connect your GitHub repository
3. Configure the service manually:
   - **Runtime:** Python
   - **Build command:** `pip install -r requirements.txt`
   - **Start command:** `python main.py`

### 3. Set Environment Variables
In Render → **Environment**, add:

| Variable | Value |
|----------|-------|
| `TOKEN` | Your Discord bot token |
| `WEBHOOK_URL` | Your Render app URL (e.g. `https://meeple-bot.onrender.com`) |

### 4. Database persistence and backups
The bot stores its SQLite database (`bot_data.db`) locally and also sends
compressed backups to the configured Discord backup channel.

Automatic backups are intentionally limited to one every 6 hours per server
and are skipped when the database has not changed. A manual backup remains
available from `/config`.

> Render Free Web Services have an ephemeral filesystem and do not support
> Persistent Disks. The Discord backup channel is therefore the recovery
> mechanism on the Free plan. A paid Render service can use a Persistent Disk
> if local database persistence is preferred.

### 5. Configure the Bot (Discord)
Use `/config` to set up channels, roles, and features for each server.

### Troubleshooting logs
The bot writes diagnostics to the platform console and to `bot.log` in its
working directory. The log file is excluded from Git by `.gitignore`.
For the `/config → DMs & Welcome` button, look for:

- `DMs & Welcome button clicked`
- `DMs & Welcome panel built`
- `DMs & Welcome panel sent successfully`
- or an error entry containing an `Error ID`

If the error message in Discord includes an `Error ID`, search for that exact
ID in the Render service logs or in `bot.log`.

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `TOKEN` | ✅ | Discord bot token |
| `WEBHOOK_URL` | ✅ (YouTube push) | Public URL for WebSub callbacks |
| `PORT` | ❌ | Web server port (Render sets this automatically) |

---

## Files

| File | Purpose |
|------|---------|
| `main.py` | Full bot source |
| `requirements.txt` | Python dependencies |
| `Procfile` | Process declaration for Render/Heroku |
| `.gitignore` | Excludes DB and secrets from Git |
| `README.md` | Deployment and feature notes |
