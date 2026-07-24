# Meeple Bot — Deployment Guide (v2.8)

A Discord bot that manages a fully configurable economy for your server: video sharing, reaction rewards, streaks, a shop, quests, achievements, daily quests, and boost announcements. The currency name and emoji are customizable per server via `/config`.

---

## Quick Start

### Requirements
- Python 3.10+
- A Discord bot token
- A Render (or similar) account for hosting

### Files in this folder
| File | Purpose |
|---|---|
| `main.py` | Full bot source (v2.8 — all fixes) |
| `requirements.txt` | Python dependencies |
| `Procfile` | Render web service definition |
| `.gitignore` | Ignores `bot_data.db` and `.env` |

---

## Deploy on Render

1. Push these files to a GitHub repository.
2. On [render.com](https://render.com), create a new **Web Service**.
3. Set the build command to `pip install -r requirements.txt`.
4. Set the start command to `python main.py` (or use the provided `Procfile`).
5. Add the following **Environment Variables** in the Render dashboard:

| Variable | Required | Description |
|---|---|---|
| `TOKEN` | ✅ | Your Discord bot token |
| `WEBHOOK_URL` | ✅ (for instant notifications) | Public URL of your Render service, e.g. `https://meeple-bot.onrender.com` |
| `PORT` | Optional | Port for the web server (Render sets this automatically) |

> **Getting `WEBHOOK_URL`:** After your first deploy, copy the URL shown at the top of your Render service dashboard and set it as `WEBHOOK_URL`. The bot appends `/youtube` automatically.

> The bot stores everything in a local SQLite file (`bot_data.db`). For persistence across deploys, mount a **Render Disk** at the same directory as `main.py`.

---

## Bot Setup (after deploy)

Once running, use **`/config`** to set everything up.

### 1. Channels (`💬 Channels`)
| Setting | Purpose |
|---|---|
| Share Channel | Where members post the video link + screenshot |
| Notifications | Where invite/quest/achievement announcements go |
| Commands Channel | Default channel for `/gems`, `/leaderboard`, etc. |
| Shop Channel | Restricts `/shop` and `/inventory` (falls back to Commands) |
| Quests Channel | Restricts `/quests` (falls back to Commands) |
| Admin Channel | Where admin alerts go |
| Log Channel | Where **all bot actions** are logged |
| Backup Channel | Where the DB backup file is sent every 15 min |
| Admin Commands Channel | Staff-only channel that bypasses all channel restrictions |
| Reaction Channel | Restrict Meeple Owner reactions to this channel |
| **📢 Announce Message** | Customise the new-video announcement message |

### 2. Economy (`💰 Economy`)
Configure share window, reaction emoji, rewards, cooldowns, and invite reward.

### 3. Currency (`💎 Currency`)
Change the name and emoji of your server's currency (default: **💎 Gems**).

### 4. Permissions (`👥 Permissions`)

#### Share Channel Lock
Set a **Share Lock Role** — the bot denies Send Messages for that role when no video window is active, and restores it automatically when a new video is announced.

#### Notification Prompt
After any bot command, members without the ping role see an ephemeral prompt with **🔔 Enable notifications** and **🔕 Later** buttons.
The snooze duration is configurable in **minutes, hours, or days** (e.g. `30m`, `2h`, `3d`). Set to `0` to always show the prompt. Default: `3d`.

### 5. DMs & Welcome (`📨 DMs & Welcome`)

| Setting | Behaviour |
|---|---|
| **Welcome DM (on join)** | DMs new members when they join |
| **DM on Role Assign** | DMs members when they receive a specific role |
| **Bulk DM Role** | Role used by the **📨 Send DMs** button |
| **Server Welcome Msg** | Posts a welcome message in a configured channel |
| **Streak Reminder** | DMs members with < 5 min left to share and keep their streak |
| **Purchase DM** | DMs a role when a member opens a purchase ticket |
| **📨 Send DMs** | Sends the welcome DM to all members with the Bulk DM Role |

#### Fixing DM Failures (HTTP 403 / code 20026 or 50007)
If the log channel shows DM failures, the member has **Allow direct messages from server members** disabled.

Ask the member to:
1. Right-click the server name in Discord
2. Go to **Privacy Settings**
3. Enable **Allow direct messages from server members**

> This is a **per-server** setting, not a global DM setting. The bot now correctly opens the DM channel before sending to avoid spurious 403 errors.

---

## Member Commands

| Command | Description |
|---|---|
| `/gems` | Check your balance and rank |
| `/leaderboard` | Server leaderboard |
| `/streak` | 🔥 View your current streak and personal best |
| `/topstreak` | ⭐ Top streak leaderboard |
| `/shop` | Browse and buy items |
| `/inventory` | View your purchased items |
| `/quests` | Monthly quests |
| `/achievements` | Your achievement progress |
| `/video` | See the current video to share |
| `/info` | How the rewards system works |

## Admin Commands

| Command | Description |
|---|---|
| `/config` | Full configuration panel |
| `/admin` | Admin panel — manage balances, trigger pings, backup |

---

## Intents Required

Enable these in the [Discord Developer Portal](https://discord.com/developers/applications):
- **Message Content Intent**
- **Server Members Intent**
- **Presence Intent** (optional)

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `TOKEN` | ✅ | Discord bot token |
| `WEBHOOK_URL` | Recommended | Public URL of your service (for YouTube push notifications) |
| `PORT` | Optional | Port for the web server — Render sets this automatically |

---

## Changelog

### v2.8 — DM fix · Notification prompt · UI reorganisation

**Bug Fixes**

1. **Welcome DM — all triggers (join, role, bulk)**
   - Now calls `create_dm()` explicitly before `send()`, which fixes persistent 403 failures even when DMs appear enabled.
   - Join-trigger delay increased to 3 s (was 0.5 s) so Discord fully registers new accounts before the DM is attempted.
   - Error message now distinguishes codes 50007 and 20026 with clearer fix instructions.

2. **Notification prompt — only showed once**
   - The prompt now sets a debounce snooze equal to the configured cooldown after being shown, so it does not flood users on every command.
   - Failed followup sends now correctly undo the debounce snooze so the next command can retry.
   - Error logging improved: failure code is printed to stdout.

3. **Notification prompt — cooldown `0` ("always show")**
   - A debounce of 1 minute is applied even when cooldown is set to `0` to prevent rapid re-sends.

**UI Reorganisation**

4. **`📨 Send DMs` moved from `/admin` → `/config → 📨 DMs & Welcome`**
   - Logically grouped with the other DM settings.

5. **`🛒 Manage Shop` removed from `/admin`**
   - Shop management already exists in `/config → 🛒 Shop`.

6. **`📊 Status` removed from `/config` main menu**
   - Redundant with the config overview embed that opens automatically.

7. **`📨 DMs & Welcome` moved to row 1 in `/config`** (was row 2) for better discoverability.

### v2.7 — Bug fixes: DMs · Boost Announce · Notification Prompt
### v2.6 — Bug fixes · Daily Quests · Boost Announce · /streak · /topstreak · Admin tools
### v2.5 — Customisable announce message · Info embed channels · DM fixes · Bulk DMs · Full logs
### v2.4 — Share channel lock + Notification "Later" button + Admin Commands Channel
### v2.3.1 — Bug fix: image attachment validation
### v2.3 — Channel routing per command + Nickname prefix feature
### v2.2 — Bug fix: `/xp` renamed to `/gems`
### v2.1 — Instant video notifications (WebSub)
