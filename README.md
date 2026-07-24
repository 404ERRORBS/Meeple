# Meeple Bot — Deployment Guide (v2.7)

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
| `main.py` | Full bot source (v2.7 — all fixes) |
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

#### Custom Video Announcement Message
Set via `/config → 💬 Channels → 📢 Announce Message`.
Supports these placeholders:
| Placeholder | Replaced with |
|---|---|
| `{mention}` | The configured ping role (or @everyone) |
| `{url}` | The video Shorts URL |
| `{deadline}` | Discord timestamp showing time remaining |
| `{title}` | The video title |

Example: `{mention} 🎬 New video is out! {url} — share before {deadline} ⏰`

Leave empty to restore the default message.

### 2. Economy (`💰 Economy`)
Configure share window, reaction emoji, rewards, cooldowns, and invite reward.

### 3. Currency (`💎 Currency`)
Change the name and emoji of your server's currency (default: **💎 Gems**).

### 4. Permissions (`👥 Permissions`)

#### Share Channel Lock
Set a **Share Lock Role** — the bot denies Send Messages for that role when no video window is active, and restores it automatically when a new video is announced.

#### Notification Prompt
After any bot command, members without the ping role see an ephemeral prompt with **🔔 Enable notifications** and **🔕 Later** buttons.
The snooze duration is configurable in **minutes, hours, or days** (e.g. `30m`, `2h`, `3d`). Set to `0` to always show the prompt. Default: `3d` (4320 minutes).

### 5. DMs & Welcome (`📨 DMs & Welcome`)

| Setting | Behaviour |
|---|---|
| **Welcome DM (on join)** | DMs new members when they join |
| **DM on Role Assign** | DMs members when they receive a specific role — works independently of the join DM toggle |
| **Bulk DM Role** | Role used by the **Send DMs** admin button |
| **Server Welcome Msg** | Posts a welcome message in a configured channel |
| **Streak Reminder** | DMs members with < 5 min left to share and keep their streak |
| **Purchase DM** | DMs a role when a member opens a purchase ticket |

#### Fixing DM Failures
If the log channel shows DM failures (HTTP 403, code 50007), the member has **Allow direct messages from server members** disabled.

**This is a per-server setting, not a global DM setting.**

Ask the member to:
1. Right-click the server name in Discord
2. Go to **Privacy Settings**
3. Enable **Allow direct messages from server members**

This is different from their global Discord privacy settings.

#### "Send DMs" Admin Button (`/admin → 📨 Send DMs`)
Sends the welcome DM to **all members** of the configured Bulk DM Role in one click.
The result now correctly reports how many DMs were sent vs failed.

### 6. Daily Quests (`🗓️ Daily Quests`)
Send members 3 random daily quests every day at UTC midnight.

| Setting | Description |
|---|---|
| **Daily Quests** | Enable/disable the feature |
| **Quest Role** | Only members with this role receive quests (empty = all members) |
| **DM Enabled** | Whether the bot DMs members their quests at midnight |
| **Reward XP** | Gems awarded per completed quest |

12 quest types available (share videos, invite members, react, check balance, etc.).

### 7. Boost Announce (`🚀 Boost Announce`)
When a member boosts the server, the bot posts a thank-you message in the notifications channel and optionally mentions a configurable role to recruit more boosters.

| Setting | Description |
|---|---|
| **Boost Mention Role** | Role mentioned in the boost announcement (empty = no mention) |
| **Rate Limit** | Maximum one announcement per hour per guild (prevents spam from multi-boosts) |

Uses the **Notifications** channel configured in 💬 Channels.

### 8. Logs Channel
Set via `/config → 💬 Channels → Log Channel`.
Every bot action is logged there, including:
- 📺 Video announced
- 🎬 Share validated (member, position, reward, streak)
- ✅ Reaction reward given (who gave it, who received it, amount)
- 📨 Invite reward (new member, inviter, reward)
- 📩 Welcome DM sent / failed (trigger: join / role / bulk, **exact error code + fix instructions on failure**)
- 📬 Purchase DM sent (item, buyer, how many staff DM'd)
- 🛒 Shop purchase (buyer, item, price, ticket channel)
- 📅 Quest completed (member, quest name, rarity, reward)
- 🏆 Achievement unlocked (member, achievement, tier, role awarded)
- 👤 Balance modified / set / reset (admin actions)

---

## Member Commands

| Command | Description |
|---|---|
| `/gems` | Check your balance and rank |
| `/leaderboard` | Server leaderboard |
| `/streak` | 🔥 View your current streak and personal best |
| `/topstreak` | ⭐ Top streak leaderboard — who has the longest all-time streak |
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
| `/admin` | Admin panel — manage balances, send DMs, trigger pings, backup |

### Admin Panel Buttons
In `/admin → 👤 Manage Gems`:

| Button | Description |
|---|---|
| **➕ Modify Streak** | Add or remove streak days from a member (format: `@user +3` or `@user -2`) |
| **🎲 Reroll Quests** | Clear and re-assign a member's current monthly quests |

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

### v2.7 — Bug fixes: DMs · Boost Announce · Notification Prompt

**Bug Fixes**

1. **Welcome DM — all triggers (join, role, bulk)**
   - `send_welcome_dm` now returns `bool` so callers know if the DM succeeded.
   - The join-trigger now waits **2 seconds** before sending so Discord fully registers the new member — this fixes 403 failures for brand-new accounts.
   - Error messages in the log now include step-by-step instructions for the exact server-level DM privacy setting to enable (not the global DM setting).

2. **Bulk DM (`/admin → 📨 Send DMs`) — failure counter fixed**
   - Previously always showed 0 failures even when all DMs failed (the counter relied on exceptions that were swallowed inside `send_welcome_dm`).
   - Now correctly counts sent vs failed DMs by using the return value.

3. **Boost Announce — wrong config key**
   - The announce function was reading `notify_channel_id` (non-existent) instead of `notification_channel_id`, so boost messages were never sent regardless of configuration.
   - Fixed in both the event handler and the config menu display.

4. **Notification prompt — `0` cooldown bug**
   - Setting the cooldown to `0` (always show) was being replaced with 3 days by the `or 3` fallback.
   - Fixed in all three places where this fallback was used.
   - Now correctly shows `0` = always show on every command.

5. **Notification prompt — silent errors**
   - `_prompt_ping_role` was swallowing ALL exceptions with `except Exception: pass`.
   - Now distinguishes between `discord.NotFound` (interaction expired — silent) and other HTTP errors (logged to stdout for debugging).

### v2.6 — Bug fixes · Daily Quests · Boost Announce · /streak · /topstreak · Admin tools

**Bug Fixes**

1. **Welcome DM failures — better error reporting**
2. **Admin "Send DMs" failure count fixed**
3. **Notification prompt cooldown — `or 3` bug fixed**

**New Features**

4. **🚀 Boost announcement**
5. **🗓️ Daily Quests**
6. **`/streak`** and **`/topstreak`**
7. **Admin panel — Modify Streak**
8. **Admin panel — Reroll Quests**

### v2.5 — Customisable announce message · Info embed channels · DM fixes · Bulk DMs · Full logs

### v2.4 — Share channel lock + Notification "Later" button + Admin Commands Channel

### v2.3.1 — Bug fix: image attachment validation

### v2.3 — Channel routing per command + Nickname prefix feature

### v2.2 — Bug fix: `/xp` renamed to `/gems`

### v2.1 — Instant video notifications (WebSub)
