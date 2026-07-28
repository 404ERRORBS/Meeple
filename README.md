# Meeple Bot — Deployment Guide (v2.9)

A Discord bot that manages a fully configurable economy for your server: video sharing, reaction rewards, streaks, a shop, quests, achievements, daily quests, boost announcements, a daily shop post, and a daily revive-ping button. The currency name and emoji are customizable per server via `/config`.

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
| **🛍️ Daily Shop Post** | Channel where the daily shop overview is posted every day at 08:00 UTC |
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

### 7. Shop (`🛒 Shop`)

| Setting | Purpose |
|---|---|
| Add / Remove items | Manage the shop catalogue |
| Set image | Thumbnail shown in `/shop` and purchase tickets |
| **🤝 Set Provider** | Credit text shown on the item (e.g. `Sponsor Name`) — appears in `/shop`, in the purchase ticket, and in the daily shop post |

### 8. Boost Announce (`🚀 Boost Announce`)
Configure the channel and role mentioned when a member boosts the server.
- **Bug fix v2.9:** simultaneous boosts from multiple members are now all detected and rewarded correctly.
- **Bug fix v2.9:** channel and role configuration now saves reliably (interaction timeout fixed).

### 9. Revive Ping (`🔔 Revive Ping`)

| Setting | Purpose |
|---|---|
| Toggle Revive Ping | Enable / disable the daily button |
| 🔔 Set Ping Role | The role given when members click the button |
| ➕ Add Channel | Add a channel to the daily pool |
| ➖ Remove Channel | Remove a channel from the pool |

**How it works:**
- Once per day at a **random time between 12:00 and 20:00 UTC**, the bot posts a button in **one random channel** from your configured pool.
- The message does **not** ping the role — it only shows the opt-in button.
- Members click **🔔 Toggle Revive Ping role** to opt in or out (toggle behaviour).
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

### v2.9 — Bug fixes · New features · Daily shop post

**Bug Fixes**

1. **Boost announce channel/role config — "This interaction failed" fixed**
   - Button → modal → refresh pattern was calling `edit_original_response()` on a modal token. Now refreshes via direct message edit.

2. **Set Image URL — "This interaction failed" fixed**
   - Modal title could exceed Discord's 45-character limit. Item name is now capped so the title stays within the limit.

3. **Server tag gems not awarded**
   - `member_has_server_tag()` was checking a `guild_tag` attribute that no longer exists in discord.py 2.4+. Now uses `member.flags.guild_tag_and_badge`. Member is also mentioned in the public notification so they know they earned gems.

4. **Reaction ❌ cancel did nothing / ✅ could re-give after cancel**
   - Added `cancelled` column to `reaction_messages`. Cancel now marks the row instead of deleting it, so a second ✅ can never re-give. ❌ on a message that was never rewarded now pre-blocks it too.

5. **Revive ping posts at a random time, no role ping in message**
   - Post time is now randomised between 12:00 and 20:00 UTC each day instead of always at noon.
   - The message no longer pings the role — it only shows the opt-in button.

6. **YouTube detection — polling interval reduced**
   - RSS fallback polling reduced from 5 minutes to 1 minute for servers without `WEBHOOK_URL`.

**New Features**

7. **🤝 Shop "Provided by" credit**
   - New "🤝 Set Provider" button in `/config → Shop`.
   - Provider name is shown in `/shop` item embeds, in the purchase ticket, and in the daily shop post.

8. **🛍️ Daily shop post at 08:00 UTC**
   - Every day at 08:00 UTC the bot posts a compact shop overview (name, price, stock, thumbnail) in a configurable channel.
   - Set the channel in `/config → 💬 Channels → 🛍️ Daily Shop Post`.
   - Out-of-stock items show as **Sold out**. Message ends with a pointer to the `/shop` command.

### v2.8 — DM fix · Notification prompt · UI reorganisation
### v2.7 — Bug fixes: DMs · Boost Announce · Notification Prompt
### v2.6 — Bug fixes · Daily Quests · Boost Announce · /streak · /topstreak · Admin tools
### v2.5 — Customisable announce message · Info embed channels · DM fixes · Bulk DMs · Full logs
### v2.4 — Share channel lock + Notification "Later" button + Admin Commands Channel
### v2.3.1 — Bug fix: image attachment validation
### v2.3 — Channel routing per command + Nickname prefix feature
### v2.2 — Bug fix: `/xp` renamed to `/gems`
### v2.1 — Instant video notifications (WebSub)
