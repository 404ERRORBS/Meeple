# Meeple Bot — Deployment Guide (v2.9)

A Discord bot that manages a fully configurable economy for your server: video sharing, reaction rewards, streaks, a shop, quests, achievements, daily quests, boost announcements, and a daily revive-ping button. The currency name and emoji are customizable per server via `/config`.

---

## Quick Start

### Requirements
- Python 3.10+
- A Discord bot token
- A Render (or similar) account for hosting

### Files in this folder
| File | Purpose |
|---|---|
| `main.py` | Full bot source (v2.9 — all fixes + new features) |
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

### 6. Daily Quests (`🗓️ Daily Quests`)

| Setting | Purpose |
|---|---|
| Toggle Daily Quests | Enable / disable the daily quest system |
| Quest Role | Restrict quests to members with a specific role |
| Toggle DMs | Send quest list via DM at UTC midnight |
| Reward XP | Currency awarded per completed quest |
| **💬 Chat Channel** | Channel counted for the "send N messages" quest — shows as a clickable #channel in the quest |
| **👑 Gems Bonus Owner** | The @member shown in the "get a gems bonus" quest — set to your own Discord user ID so members can ping you directly |

> **Gems Bonus Owner:** By default shows `404ERROR`. Set it to your Discord user ID so the quest shows your clickable @mention and the instructions say "ping them to ask!".

### 7. Boost Announce (`🚀 Boost Announce`)
Configure the channel and role mentioned when a member boosts the server.
- **Bug fix v2.9:** simultaneous boosts from multiple members are now all detected and rewarded correctly.
- **Bug fix v2.9:** channel configuration now saves reliably (interaction timeout fixed).

### 8. Revive Ping (`🔔 Revive Ping`) — New in v2.9

| Setting | Purpose |
|---|---|
| Toggle Revive Ping | Enable / disable the daily button |
| 🔔 Set Ping Role | The role given when members click the button |
| ➕ Add Channel | Add a channel to the daily pool |
| ➖ Remove Channel | Remove a channel from the pool |

**How it works:**
- Once per day at **12:00 UTC**, the bot posts a button in **one random channel** from your configured pool.
- Members click **🔔 Toggle Revive Ping role** to opt in or out.
- Clicking again removes the role (toggle behaviour).
- The goal is to maintain a pool of members to ping when the chat goes quiet.

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
| `/quests` | Monthly + daily quests |
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

### v2.9 — Daily quest improvements · Boost fix · Revive Ping

**New Features**

1. **Daily Quest: "send messages" now shows a clickable #channel**
   - Configure the target channel in `/config → 🗓️ Daily Quests → 💬 Chat Channel`.
   - The quest displays `<#channel>` as a clickable Discord link.

2. **Daily Quest: "gems bonus" shows a configurable owner @mention**
   - Renamed from "reaction bonus from Meeple Owner" → "gems bonus from @owner (ping them to ask!)".
   - Set your Discord user ID in `/config → 🗓️ Daily Quests → 👑 Gems Bonus Owner`.
   - The @mention is clickable. Default shows `404ERROR` when not configured.

3. **🔔 Revive Ping — new feature**
   - Once per day at 12:00 UTC, the bot posts a toggle button in a random channel from your pool.
   - Members click to opt in/out of the @revive-ping role.
   - Fully configurable: role, channels pool, and toggle in `/config → 🔔 Revive Ping`.

**Bug Fixes**

4. **Boost announce channel config — "interaction failed" fixed**
   - The `_refresh` method now falls back to direct message editing when the interaction token is a modal token, preventing the "This interaction failed" error.

5. **Boost detection — simultaneous boosters now all rewarded**
   - Changed internal tracking from a single member ID per guild to a list, so two members boosting at the same moment both receive their XP.

### v2.8 — DM fix · Notification prompt · UI reorganisation
### v2.7 — Bug fixes: DMs · Boost Announce · Notification Prompt
### v2.6 — Bug fixes · Daily Quests · Boost Announce · /streak · /topstreak · Admin tools
### v2.5 — Customisable announce message · Info embed channels · DM fixes · Bulk DMs · Full logs
### v2.4 — Share channel lock + Notification "Later" button + Admin Commands Channel
### v2.3.1 — Bug fix: image attachment validation
### v2.3 — Channel routing per command + Nickname prefix feature
### v2.2 — Bug fix: `/xp` renamed to `/gems`
### v2.1 — Instant video notifications (WebSub)
