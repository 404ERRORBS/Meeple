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

### 4. Add a Persistent Disk
The bot stores its SQLite database (`bot_data.db`) on disk.
- In Render → **Disks**, add a disk:
  - **Mount path:** `/opt/render/project/src`
  - **Size:** 1 GB

> **Note:** Because this deployment uses only the five files listed below, add the persistent disk manually in Render.

### 5. Configure the Bot (Discord)
Use `/config` to set up channels, roles, and features for each server.

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
