# Meeple Bot v3.0 — Deployment Guide

## What's new in v3.0

### Bug Fixes
- **All French strings replaced with English** — member join log, streak reset/modify log, share rejection, reaction removal, daily quest DM, daily shop post log, revive ping log
- **Quest logic fixed** — removed the nonsensical "check your quests with /quests" daily quest; position quests (be first / top 3 / top 5) are now mutually exclusive so only ONE is assigned per day; "ping him" instead of "ping them" for the Gems Bonus quest
- **Reaction reward** — no longer auto-deletes after 15 seconds; now mentions who gave the bonus (`@recipient received +X from @giver`)
- **Streak reminder DM spam fixed** — bot now tracks who was already reminded per video per member; won't DM the same person multiple times in the 5-minute window
- **Negative gem balances allowed** — balance no longer hard-clipped to 0, enabling debt/deduction mechanics
- **💬 Channels config crash fixed** — row 3 had 6 buttons (Discord max is 5); Info Channel moved to row 2
- **➕ Modify Streak crash fixed** — switched to two separate input fields (user ID + delta amount) to eliminate parsing errors; added error guard around modal open

### New Features

#### Shop: Approval System
- Items can now require **Gems Owner approval** before a purchase goes through
- When enabled: gems are NOT deducted until an owner clicks Approve in the admin channel
- Approve/Reject buttons appear in the admin channel with buyer info
- Buyer receives a DM on approval or rejection
- Configure via `/config → Shop → 🔒 Require Approval`

#### Shop: Per-Person Purchase Limit
- Set a maximum number of purchases per member for any item
- Limit counter can be shown or hidden in `/shop` (like the expiry visibility toggle)
- Configure via `/config → Shop → 🔢 Buy Limit` and `👁️ Hide Buy Limit`

#### Gift Gems (`/give`)
- Members can gift gems to each other with `/give @member amount`
- **Anti-alt protection**: sender must have ≥ 1,000 gems to give
- Configurable daily send cap (default: 100 gems/day)
- Configurable receive limit (default: 1 gift per day per person)
- Recipient gets a DM notification
- Enable/configure via `/config → DMs & Welcome → 🎁 Gift Gems`

---

## Deployment (Render)

### 1. Create a Render Web Service
1. Push the contents of this folder to a GitHub repo
2. On [render.com](https://render.com), create a **New Web Service** from that repo
3. Set manually:
   - **Build command:** `pip install -r requirements.txt`
   - **Start command:** `python main.py`

### 2. Set Environment Variables
In Render → Environment, add:

| Variable | Value |
|----------|-------|
| `TOKEN` | Your Discord bot token |
| `WEBHOOK_URL` | Your Render app URL (e.g. `https://meeple-bot.onrender.com`) |

### 3. Add a Persistent Disk
The bot stores its SQLite database (`bot_data.db`) on disk and backs it up to a Discord channel.
- Add a **Disk** in Render: mount path `/opt/render/project/src`, size 1 GB

### 4. Configure the Bot (Discord)
Use `/config` to set up channels, roles, and features for each server.

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `TOKEN` | ✅ | Discord bot token |
| `WEBHOOK_URL` | ✅ for YouTube push | Public URL for WebSub callbacks |
| `PORT` | ❌ | Web server port (Render sets this automatically) |

---

## Files

| File | Purpose |
|------|---------|
| `main.py` | Full bot source (single file) |
| `requirements.txt` | Python dependencies |
| `Procfile` | Process declaration for Render/Heroku |
| `.gitignore` | Excludes DB and secrets |
