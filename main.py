"""
Discord Economy Bot v2 — Full rewrite
Multi-server, fully button-driven, zero-hardcoded IDs.

Features
--------
• Video share rewards — auto-validated (link + screenshot)
• Emoji reaction rewards — Meeple Owner bonus (default emoji: ✅)
• Invitation rewards — configurable, announced in notifications channel
• Video Streak — consecutive shares, nickname display (🔥N)
• Monthly Quests — 5 rarities (Stone → Diamond), random per user
• Repeatable Boost Quest — Nitro Boost = currency reward
• Achievements — Discord role rewards, fully configurable
• Events — Double rewards, Community Goals
• Shop — images, temporary items, text-input items
• 3 member channels: share / notifications / commands
• Admin channel — internal notifications (expired items, text orders)
• Full /config panel (buttons only)
"""

import discord
from discord.ext import commands, tasks
from discord import app_commands
import sqlite3
import asyncio
import aiohttp
import xml.etree.ElementTree as ET
import re
import os
import json
import shutil
import random
import traceback
from collections import Counter
from datetime import datetime, timedelta
from typing import Optional
from aiohttp import web as aiohttp_web
import hmac
import hashlib

# ══════════════════════════════════════════════════════════════
#  IMAGE-ATTACHMENT HELPER
# ══════════════════════════════════════════════════════════════

# Extensions treated as images when Discord omits content_type
# (common on mobile / HEIC / certain CDN responses).
_IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.gif', '.webp',
               '.bmp', '.tiff', '.tif', '.avif', '.heic', '.heif'}

def _is_image_attachment(att) -> bool:
    """Return True if the attachment is an image.

    Checks content_type first (fast path). Falls back to the file
    extension so that mobile uploads where Discord doesn't send a
    content_type are not mistakenly rejected.
    """
    if att.content_type and att.content_type.startswith("image/"):
        return True
    ext = os.path.splitext(att.filename.lower())[1]
    return ext in _IMAGE_EXTS

# ══════════════════════════════════════════════════════════════
#  CONSTANTS
# ══════════════════════════════════════════════════════════════

DB_PATH         = "bot_data.db"
BACKUP_REGISTRY = "backup_channels.json"
BOT_START_TIME  = datetime.utcnow()   # recorded the instant the process starts

C_MAIN    = 0x5865F2
C_SUCCESS = 0x57F287
C_ERROR   = 0xED4245
C_GOLD    = 0xFEE75C
C_INFO    = 0x1ABC9C
C_STREAK  = 0xFF6B35
C_QUEST   = 0x9B59B6
C_ACHIEVE = 0xF1C40F
C_EVENT   = 0xE74C3C

RARITIES = ["stone", "bronze", "silver", "gold", "diamond"]
RARITY_EMOJI = {"stone": "🪨", "bronze": "🥉", "silver": "🥈", "gold": "🥇", "diamond": "💎"}
RARITY_COLOR = {
    "stone": 0x95A5A6, "bronze": 0xCD7F32, "silver": 0xBDC3C7,
    "gold": 0xF1C40F,  "diamond": 0x1ABC9C
}

# Quest pool — add more dicts here to extend without code changes
QUEST_POOL = {
    "stone": [
        {"key": "share_5",   "name": "Share 5 videos",                     "type": "share_videos",  "target": 5},
        {"key": "invite_1",  "name": "Invite 1 member",                    "type": "invite_members","target": 1},
        {"key": "streak_5",  "name": "Reach a 5-video streak",             "type": "video_streak",  "target": 5},
        {"key": "first5_1",  "name": "Be among the first 5 supporters once","type": "first_5",      "target": 1},
    ],
    "bronze": [
        {"key": "share_10",  "name": "Share 10 videos",                    "type": "share_videos",  "target": 10},
        {"key": "invite_3",  "name": "Invite 3 members",                   "type": "invite_members","target": 3},
        {"key": "streak_10", "name": "Reach a 10-video streak",            "type": "video_streak",  "target": 10},
        {"key": "first5_3",  "name": "Be among the first 5 supporters 3 times","type": "first_5",  "target": 3},
    ],
    "silver": [
        {"key": "share_20",  "name": "Share 20 videos",                    "type": "share_videos",  "target": 20},
        {"key": "invite_5",  "name": "Invite 5 members",                   "type": "invite_members","target": 5},
        {"key": "streak_20", "name": "Reach a 20-video streak",            "type": "video_streak",  "target": 20},
        {"key": "first5_10", "name": "Be among the first 5 supporters 10 times","type": "first_5", "target": 10},
        {"key": "top1_1",    "name": "Be the #1 supporter once",           "type": "top_1",         "target": 1},
    ],
    "gold": [
        {"key": "share_35",  "name": "Share 35 videos",                    "type": "share_videos",  "target": 35},
        {"key": "invite_10", "name": "Invite 10 members",                  "type": "invite_members","target": 10},
        {"key": "streak_35", "name": "Reach a 35-video streak",            "type": "video_streak",  "target": 35},
        {"key": "top1_3",    "name": "Be the #1 supporter 3 times",        "type": "top_1",         "target": 3},
        {"key": "all_events","name": "Participate in every enabled event this month","type": "all_events","target": 1},
    ],
    "diamond": [
        {"key": "share_50",  "name": "Share 50 videos",                    "type": "share_videos",  "target": 50},
        {"key": "invite_15", "name": "Invite 15 members",                  "type": "invite_members","target": 15},
        {"key": "streak_50", "name": "Reach a 50-video streak",            "type": "video_streak",  "target": 50},
        {"key": "top1_10",   "name": "Be the #1 supporter 10 times",       "type": "top_1",         "target": 10},
        {"key": "all_quests","name": "Complete all 4 monthly quests",        "type": "all_quests",    "target": 4},
    ],
}

# ── Daily quest pool — simple tasks achievable in one day ─────
DAILY_QUEST_POOL = [
    # Share quests — grouped with position so only ONE share-type task is assigned per day.
    # A user can't have "Share today's video" AND "Be the first to share" simultaneously
    # since both complete from the exact same action.
    {"key": "dq_share_1",    "name": "Share today's video",                  "type": "dq_share",    "target": 1, "group": "position"},
    {"key": "dq_first5",     "name": "Be among the first 5 to share",        "type": "dq_first5",   "target": 1, "group": "position"},
    {"key": "dq_first3",     "name": "Be among the first 3 to share",        "type": "dq_first3",   "target": 1, "group": "position"},
    {"key": "dq_first1",     "name": "Be the very first to share",           "type": "dq_first1",   "target": 1, "group": "position"},
    {"key": "dq_invite",     "name": "Invite a new member",                  "type": "dq_invite",   "target": 1},
    {"key": "dq_check_gems", "name": "Check your balance with /gems",        "type": "dq_checkin",  "target": 1},
    {"key": "dq_share_top10","name": "Share and be in the top 10",           "type": "dq_top10",    "target": 1},
    # dq_get_react: name is resolved at assignment time (see db_assign_daily_quests)
    # ANY member with the Gems Owner role can trigger this — not only the designated owner.
    {"key": "dq_get_react",  "name": "Get a gems bonus from a Gems Owner",   "type": "dq_get_react", "target": 1},
    # dq_messages: target and channel are resolved at assignment time
    {"key": "dq_messages",   "name": "Send {n} messages in the chat",        "type": "dq_messages", "target": 20},
]

# Groups of quest keys that are mutually exclusive (only one from each group is assigned per day)
_DAILY_QUEST_GROUPS: dict[str, list] = {}
for _q in DAILY_QUEST_POOL:
    _g = _q.get("group")
    if _g:
        _DAILY_QUEST_GROUPS.setdefault(_g, []).append(_q["key"])

# Achievement definitions — add entries to extend
ACHIEVEMENT_DEFS = [
    {"key": "shares",  "name": "Video Supporter", "category": "total_shares",      "tiers": [10, 50, 100, 250, 500]},
    {"key": "invites", "name": "Recruiter",        "category": "total_invites",     "tiers": [1, 5, 10, 25, 50]},
    {"key": "streak",  "name": "On Fire",          "category": "max_streak_ever",   "tiers": [5, 15, 30, 60, 100]},
    {"key": "boosts",  "name": "Server Booster",   "category": "total_boosts",      "tiers": [1, 3, 6, 12, 24]},
    {"key": "quests",  "name": "Quest Master",     "category": "total_quests_done", "tiers": [1, 5, 10, 25, 50]},
]

# ══════════════════════════════════════════════════════════════
#  DATABASE
# ══════════════════════════════════════════════════════════════

def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute("""CREATE TABLE IF NOT EXISTS guild_config (
        guild_id                INTEGER PRIMARY KEY,
        youtube_channel_id      TEXT,
        share_channel_id        INTEGER,
        notification_channel_id INTEGER,
        commands_channel_id     INTEGER,
        admin_channel_id        INTEGER,
        log_channel_id          INTEGER,
        backup_channel_id       INTEGER,
        ticket_category_id      INTEGER,
        share_ping_role_id      INTEGER,
        manager_role_id         INTEGER,
        reaction_emoji          TEXT    DEFAULT '✅',
        reaction_xp             INTEGER DEFAULT 50,
        reaction_cooldown_h     INTEGER DEFAULT 1,
        invite_xp               INTEGER DEFAULT 25,
        share_window_min        INTEGER DEFAULT 20,
        streak_enabled          INTEGER DEFAULT 1,
        streak_xp_bonus         INTEGER DEFAULT 2,
        streak_xp_cap           INTEGER DEFAULT 30,
        streak_reset_on_miss    INTEGER DEFAULT 1,
        boost_quest_enabled     INTEGER DEFAULT 1,
        boost_quest_xp          INTEGER DEFAULT 100,
        currency_name           TEXT    DEFAULT 'Gems',
        currency_emoji          TEXT    DEFAULT '💎',
        quest_xp_stone          INTEGER DEFAULT 50,
        quest_xp_bronze         INTEGER DEFAULT 100,
        quest_xp_silver         INTEGER DEFAULT 200,
        quest_xp_gold           INTEGER DEFAULT 400,
        quest_xp_diamond        INTEGER DEFAULT 750,
        achievement_channel_id  INTEGER,
        event_double_xp_mult    REAL    DEFAULT 2.0,
        event_announce_channel_id INTEGER,
        cancel_emoji              TEXT    DEFAULT '❌',
        reaction_channel_id       INTEGER,
        share_xp                  INTEGER DEFAULT 100,
        shop_channel_id           INTEGER,
        quests_channel_id         INTEGER,
        prefix_role_id            INTEGER,
        nick_prefix               TEXT    DEFAULT '404 | '
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS xp_data (
        guild_id INTEGER, user_id INTEGER, xp INTEGER DEFAULT 0,
        PRIMARY KEY (guild_id, user_id)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS video_shares (
        guild_id  INTEGER, video_id TEXT, user_id INTEGER,
        shared_at TEXT,    position INTEGER DEFAULT 0,
        PRIMARY KEY (guild_id, video_id, user_id)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS current_video (
        guild_id          INTEGER PRIMARY KEY,
        video_id          TEXT,
        video_url         TEXT,
        video_title       TEXT,
        detected_at       TEXT,
        previous_video_id TEXT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS shop_items (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id      INTEGER,
        name          TEXT,
        price         INTEGER,
        image_url     TEXT,
        created_at    TEXT,
        new_item_dm_sent INTEGER DEFAULT 0,
        is_temporary  INTEGER DEFAULT 0,
        duration_days INTEGER,
        show_duration INTEGER DEFAULT 1,
        requires_text INTEGER DEFAULT 0,
        text_label    TEXT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS shop_item_rewards (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        shop_item_id INTEGER,
        guild_id     INTEGER,
        reward_text  TEXT,
        used         INTEGER DEFAULT 0,
        used_by      INTEGER,
        used_at      TEXT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS inventory (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id     INTEGER,
        user_id      INTEGER,
        item_name    TEXT,
        purchased_at TEXT,
        expires_at   TEXT,
        is_expired   INTEGER DEFAULT 0,
        item_text    TEXT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS reaction_cooldowns (
        guild_id INTEGER, user_id INTEGER, last_reaction TEXT,
        PRIMARY KEY (guild_id, user_id)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS reaction_messages (
        guild_id     INTEGER, message_id INTEGER, target_uid INTEGER,
        given_by_uid INTEGER, amount INTEGER, given_at TEXT,
        PRIMARY KEY (guild_id, message_id)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS streaks (
        guild_id       INTEGER,
        user_id        INTEGER,
        current_streak INTEGER DEFAULT 0,
        max_streak     INTEGER DEFAULT 0,
        last_video_id  TEXT,
        PRIMARY KEY (guild_id, user_id)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS monthly_quests (
        guild_id     INTEGER,
        user_id      INTEGER,
        month_key    TEXT,
        rarity       TEXT,
        quest_key    TEXT,
        quest_type   TEXT,
        quest_target INTEGER,
        quest_name   TEXT,
        progress     INTEGER DEFAULT 0,
        completed    INTEGER DEFAULT 0,
        xp_awarded   INTEGER DEFAULT 0,
        PRIMARY KEY (guild_id, user_id, month_key, rarity)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS quest_pool_config (
        guild_id  INTEGER, quest_key TEXT, enabled INTEGER DEFAULT 1,
        PRIMARY KEY (guild_id, quest_key)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS achievements (
        guild_id        INTEGER, user_id INTEGER,
        achievement_key TEXT,    tier INTEGER,
        unlocked_at     TEXT,
        PRIMARY KEY (guild_id, user_id, achievement_key, tier)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS achievement_config (
        guild_id        INTEGER, achievement_key TEXT,
        tier            INTEGER, threshold INTEGER,
        role_id         INTEGER, enabled INTEGER DEFAULT 1,
        PRIMARY KEY (guild_id, achievement_key, tier)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS events (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id    INTEGER,
        name        TEXT,
        description TEXT,
        event_type  TEXT,
        start_date  TEXT,
        end_date    TEXT,
        config_json TEXT DEFAULT '{}',
        enabled     INTEGER DEFAULT 1
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS community_goals (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id     INTEGER,
        event_id     INTEGER,
        name         TEXT,
        goal_type    TEXT,
        target       INTEGER,
        current      INTEGER DEFAULT 0,
        reward_xp    INTEGER DEFAULT 0,
        contributors TEXT    DEFAULT '[]',
        completed    INTEGER DEFAULT 0,
        enabled      INTEGER DEFAULT 1
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS invites_cache (
        guild_id    INTEGER, invite_code TEXT,
        inviter_id  INTEGER, uses INTEGER DEFAULT 0,
        PRIMARY KEY (guild_id, invite_code)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS invite_log (
        guild_id    INTEGER,
        member_id   INTEGER,
        inviter_id  INTEGER,
        xp_given    INTEGER DEFAULT 0,
        PRIMARY KEY (guild_id, member_id)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS user_stats (
        guild_id          INTEGER, user_id INTEGER,
        total_shares      INTEGER DEFAULT 0,
        total_invites     INTEGER DEFAULT 0,
        total_boosts      INTEGER DEFAULT 0,
        total_quests_done INTEGER DEFAULT 0,
        max_streak_ever   INTEGER DEFAULT 0,
        PRIMARY KEY (guild_id, user_id)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS notification_snooze (
        guild_id      INTEGER,
        user_id       INTEGER,
        snoozed_until TEXT NOT NULL,
        PRIMARY KEY (guild_id, user_id)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS daily_quests (
        guild_id    INTEGER,
        user_id     INTEGER,
        date_key    TEXT,
        quest_key   TEXT,
        quest_type  TEXT,
        quest_target INTEGER,
        quest_name  TEXT,
        progress    INTEGER DEFAULT 0,
        completed   INTEGER DEFAULT 0,
        xp_awarded  INTEGER DEFAULT 0,
        dm_sent     INTEGER DEFAULT 0,
        PRIMARY KEY (guild_id, user_id, date_key)
    )""")

    conn.commit()

    # Safe migrations for existing databases
    for migration in [
        "ALTER TABLE current_video ADD COLUMN previous_video_id TEXT",
        "ALTER TABLE current_video ADD COLUMN deadline_ts INTEGER",
        "ALTER TABLE shop_items ADD COLUMN image_url TEXT",
        "ALTER TABLE shop_items ADD COLUMN created_at TEXT",
        "ALTER TABLE shop_items ADD COLUMN new_item_dm_sent INTEGER DEFAULT 0",
        "ALTER TABLE shop_items ADD COLUMN is_temporary INTEGER DEFAULT 0",
        "ALTER TABLE shop_items ADD COLUMN duration_days INTEGER",
        "ALTER TABLE shop_items ADD COLUMN show_duration INTEGER DEFAULT 1",
        "ALTER TABLE shop_items ADD COLUMN requires_text INTEGER DEFAULT 0",
        "ALTER TABLE shop_items ADD COLUMN text_label TEXT",
        "ALTER TABLE shop_items ADD COLUMN notify_admin INTEGER DEFAULT 0",
        "ALTER TABLE shop_items ADD COLUMN stock INTEGER DEFAULT NULL",
        "ALTER TABLE shop_items ADD COLUMN sort_order INTEGER DEFAULT 0",
        "ALTER TABLE inventory ADD COLUMN purchased_at TEXT",
        "ALTER TABLE inventory ADD COLUMN expires_at TEXT",
        "ALTER TABLE inventory ADD COLUMN is_expired INTEGER DEFAULT 0",
        "ALTER TABLE inventory ADD COLUMN item_text TEXT",
        "ALTER TABLE video_shares ADD COLUMN position INTEGER DEFAULT 0",
        # DM & Welcome features
        "ALTER TABLE guild_config ADD COLUMN info_channel_id INTEGER",
        "ALTER TABLE guild_config ADD COLUMN info_message_id INTEGER",
        "ALTER TABLE guild_config ADD COLUMN welcome_dm_enabled INTEGER DEFAULT 0",
        "ALTER TABLE guild_config ADD COLUMN welcome_dm_role_id INTEGER",
        "ALTER TABLE guild_config ADD COLUMN welcome_dm_on_role_id INTEGER",
        "ALTER TABLE guild_config ADD COLUMN streak_reminder_enabled INTEGER DEFAULT 0",
        "ALTER TABLE guild_config ADD COLUMN server_welcome_enabled INTEGER DEFAULT 0",
        "ALTER TABLE guild_config ADD COLUMN server_welcome_channel_id INTEGER",
        "ALTER TABLE guild_config ADD COLUMN server_welcome_on_role_id INTEGER",
        "ALTER TABLE guild_config ADD COLUMN currency_name TEXT DEFAULT 'Gems'",
        "ALTER TABLE guild_config ADD COLUMN currency_emoji TEXT DEFAULT '💎'",
        "ALTER TABLE guild_config ADD COLUMN event_announce_channel_id INTEGER",
        "ALTER TABLE guild_config ADD COLUMN ticket_category_id INTEGER",
        # Purchase DM controls
        "ALTER TABLE guild_config ADD COLUMN purchase_dm_enabled INTEGER DEFAULT 1",
        "ALTER TABLE guild_config ADD COLUMN purchase_dm_role_id INTEGER",
        # Cancel emoji and reaction channel
        "ALTER TABLE guild_config ADD COLUMN cancel_emoji TEXT DEFAULT '❌'",
        "ALTER TABLE guild_config ADD COLUMN reaction_channel_id INTEGER",
        "ALTER TABLE guild_config ADD COLUMN share_xp INTEGER DEFAULT 100",
        # Channel routing per command category
        "ALTER TABLE guild_config ADD COLUMN shop_channel_id INTEGER",
        "ALTER TABLE guild_config ADD COLUMN quests_channel_id INTEGER",
        # Nickname prefix feature
        "ALTER TABLE guild_config ADD COLUMN prefix_role_id INTEGER",
        "ALTER TABLE guild_config ADD COLUMN nick_prefix TEXT DEFAULT '404 | '",
        # Admin commands channel — bypasses all member-facing channel restrictions
        "ALTER TABLE guild_config ADD COLUMN admin_commands_channel_id INTEGER",
        # Share channel lock — role to deny send_messages when no video is active
        "ALTER TABLE guild_config ADD COLUMN share_lock_role_id INTEGER",
        # Notification prompt snooze cooldown in days (legacy — kept for migration)
        "ALTER TABLE guild_config ADD COLUMN notify_prompt_cooldown_days INTEGER DEFAULT 3",
        # Customisable video announcement message (placeholders: {mention} {url} {deadline} {title})
        "ALTER TABLE guild_config ADD COLUMN video_announce_message TEXT",
        # Role used by the admin "Send DMs" bulk action (independent of join DM toggle)
        "ALTER TABLE guild_config ADD COLUMN bulk_dm_role_id INTEGER",
        # Notification prompt cooldown in minutes (0 = always show, replaces cooldown_days)
        "ALTER TABLE guild_config ADD COLUMN notify_prompt_cooldown_minutes INTEGER DEFAULT 4320",
        # Boost announce: role to mention + per-guild hourly rate-limit timestamp (unix)
        "ALTER TABLE guild_config ADD COLUMN boost_announce_role_id INTEGER",
        "ALTER TABLE guild_config ADD COLUMN boost_announce_cooldown_ts INTEGER DEFAULT 0",
        "ALTER TABLE guild_config ADD COLUMN boost_announce_channel_id INTEGER",
        "ALTER TABLE guild_config ADD COLUMN server_tag_enabled INTEGER DEFAULT 0",
        "ALTER TABLE guild_config ADD COLUMN server_tag_xp INTEGER DEFAULT 100",
        "ALTER TABLE guild_config ADD COLUMN daily_quest_messages_channel_id INTEGER",
        # Daily quests
        "ALTER TABLE guild_config ADD COLUMN daily_quest_enabled INTEGER DEFAULT 0",
        "ALTER TABLE guild_config ADD COLUMN daily_quest_role_id INTEGER",
        "ALTER TABLE guild_config ADD COLUMN daily_quest_dm_enabled INTEGER DEFAULT 1",
        "ALTER TABLE guild_config ADD COLUMN daily_quest_xp INTEGER DEFAULT 50",
        # New shop item DM notifications
        "ALTER TABLE guild_config ADD COLUMN new_item_dm_enabled INTEGER DEFAULT 1",
        "ALTER TABLE guild_config ADD COLUMN new_item_dm_delay_minutes INTEGER DEFAULT 5",
        # Gems bonus quest: configurable owner user ID
        "ALTER TABLE guild_config ADD COLUMN meeple_owner_user_id INTEGER",
        # Optional personal DM recipient for manual Gems balance changes
        "ALTER TABLE guild_config ADD COLUMN balance_change_dm_user_id INTEGER",
        # Revive ping: role to assign + list of channels (JSON array) + toggle
        "ALTER TABLE guild_config ADD COLUMN revive_ping_role_id INTEGER",
        "ALTER TABLE guild_config ADD COLUMN drops_ping_role_id INTEGER",
        "ALTER TABLE guild_config ADD COLUMN revive_ping_channels TEXT DEFAULT '[]'",
        "ALTER TABLE guild_config ADD COLUMN revive_ping_enabled INTEGER DEFAULT 0",
        # Daily shop post channel
        "ALTER TABLE guild_config ADD COLUMN daily_shop_channel_id INTEGER",
        # Provided-by tag on shop items
        "ALTER TABLE shop_items ADD COLUMN provided_by TEXT",
        # Reaction message cancellation flag
        "ALTER TABLE reaction_messages ADD COLUMN cancelled INTEGER DEFAULT 0",
        # Shop: per-item approval requirement and per-person purchase limit
        "ALTER TABLE shop_items ADD COLUMN requires_approval INTEGER DEFAULT 0",
        "ALTER TABLE shop_items ADD COLUMN purchase_limit INTEGER DEFAULT NULL",
        "ALTER TABLE shop_items ADD COLUMN show_purchase_limit INTEGER DEFAULT 1",
        # Gift gems: configurable daily send cap and receive cooldown (hours)
        "ALTER TABLE guild_config ADD COLUMN give_max_daily INTEGER DEFAULT 100",
        "ALTER TABLE guild_config ADD COLUMN give_receive_cooldown_h INTEGER DEFAULT 24",
        "ALTER TABLE guild_config ADD COLUMN give_enabled INTEGER DEFAULT 0",
        "ALTER TABLE guild_config ADD COLUMN give_min_balance INTEGER DEFAULT 1000",
        # Message visibility / auto-delete TTL (seconds). 0 = permanent, >0 = auto-delete after N seconds.
        "ALTER TABLE guild_config ADD COLUMN msg_ttl_share_reward    INTEGER DEFAULT 0",
        "ALTER TABLE guild_config ADD COLUMN msg_ttl_share_reject    INTEGER DEFAULT 0",
        "ALTER TABLE guild_config ADD COLUMN msg_ttl_reaction_bonus  INTEGER DEFAULT 0",
        "ALTER TABLE guild_config ADD COLUMN msg_ttl_reaction_cooldown INTEGER DEFAULT 0",
        "ALTER TABLE guild_config ADD COLUMN msg_ttl_block_msg       INTEGER DEFAULT 0",
        "ALTER TABLE guild_config ADD COLUMN msg_ttl_gems            INTEGER DEFAULT 0",
        "ALTER TABLE guild_config ADD COLUMN msg_ttl_shop            INTEGER DEFAULT 0",
        "ALTER TABLE guild_config ADD COLUMN msg_ttl_leaderboard     INTEGER DEFAULT 0",
        # Shop item expiry (listing expires — item removed from public shop after this date)
        "ALTER TABLE shop_items ADD COLUMN item_expires_at TEXT DEFAULT NULL",
        # Stock visibility in /shop (0 = hidden from members, 1 = shown)
        "ALTER TABLE shop_items ADD COLUMN show_stock INTEGER DEFAULT 0",
    ]:
        try:
            conn.execute(migration)
        except Exception:
            pass
    # Backfill NULL currency values — ALTER TABLE DEFAULT doesn't update existing rows
    conn.execute("UPDATE guild_config SET currency_emoji='💎' WHERE currency_emoji IS NULL")
    conn.execute("UPDATE guild_config SET currency_name='Gems' WHERE currency_name IS NULL")
    # Existing shop items predate delayed new-item notifications. Mark them as
    # already handled so enabling the feature never sends a surprise backlog
    # of DMs after an upgrade.
    conn.execute(
        "UPDATE shop_items SET created_at=datetime('now'), new_item_dm_sent=1 "
        "WHERE created_at IS NULL"
    )
    conn.commit()

    # Server tag rewards table — tracks who has already been rewarded for the server tag.
    conn.execute("""CREATE TABLE IF NOT EXISTS server_tag_rewards (
        guild_id INTEGER,
        user_id  INTEGER,
        rewarded_at TEXT DEFAULT (datetime('now')),
        PRIMARY KEY (guild_id, user_id)
    )""")

    # Tracks which channel received the revive-ping button today (one per guild per day)
    conn.execute("""CREATE TABLE IF NOT EXISTS revive_ping_sent (
        guild_id   INTEGER,
        date_key   TEXT,
        channel_id INTEGER,
        PRIMARY KEY (guild_id, date_key)
    )""")

    # share_log: tracks the XP and streak given for each validated share so ❌ can fully revert it
    conn.execute("""CREATE TABLE IF NOT EXISTS share_log (
        guild_id      INTEGER,
        message_id    INTEGER,
        user_id       INTEGER,
        video_id      TEXT,
        xp_given      INTEGER DEFAULT 0,
        streak_before INTEGER DEFAULT 0,
        new_streak    INTEGER DEFAULT 0,
        cancelled     INTEGER DEFAULT 0,
        PRIMARY KEY (guild_id, message_id)
    )""")

    # Fix daily_quests PRIMARY KEY — original schema only had (guild_id, user_id, date_key),
    # which silently drops all but the first quest per user per day.
    # Recreate with (guild_id, user_id, date_key, quest_key) to allow 3 quests per day.
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_quests_v2 (
                guild_id     INTEGER,
                user_id      INTEGER,
                date_key     TEXT,
                quest_key    TEXT,
                quest_type   TEXT,
                quest_target INTEGER,
                quest_name   TEXT,
                progress     INTEGER DEFAULT 0,
                completed    INTEGER DEFAULT 0,
                xp_awarded   INTEGER DEFAULT 0,
                dm_sent      INTEGER DEFAULT 0,
                PRIMARY KEY (guild_id, user_id, date_key, quest_key)
            )
        """)
        conn.execute("INSERT OR IGNORE INTO daily_quests_v2 SELECT * FROM daily_quests")
        conn.execute("DROP TABLE daily_quests")
        conn.execute("ALTER TABLE daily_quests_v2 RENAME TO daily_quests")
        conn.commit()
    except Exception:
        pass

    # Pending shop purchases — for items that require Gems Owner approval
    conn.execute("""CREATE TABLE IF NOT EXISTS shop_pending_purchases (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id     INTEGER,
        user_id      INTEGER,
        item_id      INTEGER,
        item_name    TEXT,
        item_price   INTEGER,
        item_text    TEXT,
        status       TEXT DEFAULT 'pending',
        created_at   TEXT DEFAULT (datetime('now')),
        resolved_at  TEXT,
        resolved_by  INTEGER
    )""")

    # Gems gift log — tracks daily give/receive for the /give command
    conn.execute("""CREATE TABLE IF NOT EXISTS gems_gifts (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id     INTEGER,
        sender_id    INTEGER,
        recipient_id INTEGER,
        amount       INTEGER,
        given_at     TEXT DEFAULT (datetime('now'))
    )""")

    conn.commit()
    conn.close()

# ── Config helpers ─────────────────────────────────────────────

def db_get_config(guild_id: int) -> dict:
    conn = get_db()
    row = conn.execute("SELECT * FROM guild_config WHERE guild_id=?", (guild_id,)).fetchone()
    conn.close()
    return dict(row) if row else {}

def db_ensure_config(guild_id: int):
    conn = get_db()
    conn.execute("INSERT OR IGNORE INTO guild_config (guild_id) VALUES (?)", (guild_id,))
    conn.commit()
    conn.close()

def db_set_config(guild_id: int, **kwargs):
    db_ensure_config(guild_id)
    conn = get_db()
    for key, val in kwargs.items():
        conn.execute(f"UPDATE guild_config SET {key}=? WHERE guild_id=?", (val, guild_id))
    conn.commit()
    conn.close()

# ── Currency helper ────────────────────────────────────────────

def _ttl(config: dict, key: str) -> Optional[float]:
    """Return delete_after seconds or None (permanent) based on config key.
    0 or unset → None (permanent).  Positive int → seconds before auto-delete.
    """
    v = config.get(key, 0)
    return float(v) if v and v > 0 else None

def cur(config: dict, amount: int = None) -> str:
    """Format the server currency for display.
    cur(config)       → '💎 Gems'
    cur(config, 500)  → '💎 500 Gems'
    """
    name  = config.get("currency_name") or "Gems"
    emoji = config.get("currency_emoji") or "💎"
    if amount is not None:
        return f"{emoji} {amount} {name}"
    return f"{emoji} {name}"

# ── XP helpers ─────────────────────────────────────────────────

def db_get_xp(guild_id: int, user_id: int) -> int:
    conn = get_db()
    row = conn.execute("SELECT xp FROM xp_data WHERE guild_id=? AND user_id=?", (guild_id, user_id)).fetchone()
    conn.close()
    return row["xp"] if row else 0

def db_add_xp(guild_id: int, user_id: int, amount: int) -> int:
    conn = get_db()
    conn.execute("""INSERT INTO xp_data (guild_id, user_id, xp) VALUES (?,?,?)
                    ON CONFLICT(guild_id, user_id) DO UPDATE SET xp = xp + ?""",
                 (guild_id, user_id, amount, amount))
    conn.commit()
    new_xp = conn.execute("SELECT xp FROM xp_data WHERE guild_id=? AND user_id=?",
                          (guild_id, user_id)).fetchone()["xp"]
    conn.close()
    return new_xp  # Negative balances are intentionally allowed

def db_set_xp(guild_id: int, user_id: int, amount: int):
    conn = get_db()
    conn.execute("""INSERT INTO xp_data (guild_id, user_id, xp) VALUES (?,?,?)
                    ON CONFLICT(guild_id, user_id) DO UPDATE SET xp=?""",
                 (guild_id, user_id, amount, amount))
    conn.commit()
    conn.close()

def db_top_xp(guild_id: int, limit: int = 10) -> list:
    conn = get_db()
    rows = conn.execute(
        "SELECT user_id, xp FROM xp_data WHERE guild_id=? ORDER BY xp DESC LIMIT ?",
        (guild_id, limit)
    ).fetchall()
    conn.close()
    return [(r["user_id"], r["xp"]) for r in rows]

# ── Video share helpers ────────────────────────────────────────

def db_log_share(guild_id: int, message_id: int, user_id: int, video_id: str,
                 xp_given: int, streak_before: int, new_streak: int):
    """Record the XP and streak awarded for a validated share (for ❌ cancel/revert)."""
    conn = get_db()
    conn.execute("""INSERT OR REPLACE INTO share_log
                    (guild_id, message_id, user_id, video_id, xp_given, streak_before, new_streak, cancelled)
                    VALUES (?,?,?,?,?,?,?,0)""",
                 (guild_id, message_id, user_id, video_id, xp_given, streak_before, new_streak))
    conn.commit()
    conn.close()

def db_get_share_log(guild_id: int, message_id: int) -> Optional[dict]:
    conn = get_db()
    row = conn.execute("SELECT * FROM share_log WHERE guild_id=? AND message_id=?",
                       (guild_id, message_id)).fetchone()
    conn.close()
    return dict(row) if row else None

def db_cancel_share_log(guild_id: int, message_id: int):
    conn = get_db()
    conn.execute("UPDATE share_log SET cancelled=1 WHERE guild_id=? AND message_id=?",
                 (guild_id, message_id))
    conn.commit()
    conn.close()

def db_remove_share(guild_id: int, video_id: str, user_id: int):
    """Remove a video_shares entry so the member can retry posting."""
    conn = get_db()
    conn.execute("DELETE FROM video_shares WHERE guild_id=? AND video_id=? AND user_id=?",
                 (guild_id, video_id, user_id))
    conn.commit()
    conn.close()

def db_has_shared(guild_id: int, video_id: str, user_id: int) -> bool:
    conn = get_db()
    row = conn.execute("SELECT 1 FROM video_shares WHERE guild_id=? AND video_id=? AND user_id=?",
                       (guild_id, video_id, user_id)).fetchone()
    conn.close()
    return row is not None

def db_add_share(guild_id: int, video_id: str, user_id: int) -> int:
    """Returns the position (1 = first, 2 = second, ...)"""
    conn = get_db()
    row = conn.execute(
        "SELECT COUNT(*)+1 AS pos FROM video_shares WHERE guild_id=? AND video_id=?",
        (guild_id, video_id)
    ).fetchone()
    pos = row["pos"] if row else 1
    conn.execute(
        "INSERT OR IGNORE INTO video_shares (guild_id, video_id, user_id, shared_at, position) VALUES (?,?,?,?,?)",
        (guild_id, video_id, user_id, datetime.now().isoformat(), pos)
    )
    conn.commit()
    conn.close()
    return pos

def db_get_current_video(guild_id: int) -> Optional[dict]:
    conn = get_db()
    row = conn.execute("SELECT * FROM current_video WHERE guild_id=?", (guild_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def db_set_current_video(guild_id: int, video_id: str, video_url: str, video_title: str):
    conn = get_db()
    now = datetime.utcnow().isoformat()  # Always UTC — consistent with window check
    old = conn.execute("SELECT video_id FROM current_video WHERE guild_id=?", (guild_id,)).fetchone()
    prev = old["video_id"] if old else None
    conn.execute("""INSERT INTO current_video (guild_id, video_id, video_url, video_title, detected_at, previous_video_id)
                    VALUES (?,?,?,?,?,?)
                    ON CONFLICT(guild_id) DO UPDATE SET
                    video_id=?, video_url=?, video_title=?, detected_at=?, previous_video_id=?""",
                 (guild_id, video_id, video_url, video_title, now, prev,
                  video_id, video_url, video_title, now, prev))
    conn.commit()
    conn.close()

# ── Shop / Inventory helpers ───────────────────────────────────

def db_get_shop_items(guild_id: int) -> list:
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM shop_items WHERE guild_id=? ORDER BY sort_order ASC, id ASC",
        (guild_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def db_add_shop_item(guild_id: int, name: str, price: int, image_url: str = None,
                     is_temporary: int = 0, duration_days: int = None,
                     show_duration: int = 1, requires_text: int = 0, text_label: str = None,
                     notify_admin: int = 0, stock: int = None) -> int:
    conn = get_db()
    created_at = datetime.utcnow().isoformat()
    c = conn.execute(
        """INSERT INTO shop_items
           (guild_id, name, price, image_url, created_at, new_item_dm_sent,
            is_temporary, duration_days, show_duration, requires_text, text_label,
            notify_admin, stock)
           VALUES (?,?,?,?,?,0,?,?,?,?,?,?,?)""",
        (guild_id, name, price, image_url, created_at, is_temporary, duration_days,
         show_duration, requires_text, text_label, notify_admin, stock)
    )
    item_id = c.lastrowid
    conn.commit()
    conn.close()
    return item_id


def db_decrement_stock(item_id: int, guild_id: int):
    """Decrement stock by 1 for a shop item (if stock is limited)."""
    conn = get_db()
    conn.execute(
        "UPDATE shop_items SET stock = MAX(0, stock - 1) WHERE id=? AND guild_id=? AND stock IS NOT NULL",
        (item_id, guild_id)
    )
    conn.commit()
    conn.close()


def db_set_shop_item_name(item_id: int, guild_id: int, new_name: str):
    """Rename a shop item."""
    conn = get_db()
    conn.execute("UPDATE shop_items SET name=? WHERE id=? AND guild_id=?",
                 (new_name, item_id, guild_id))
    conn.commit()
    conn.close()

def db_set_shop_item_price(item_id: int, guild_id: int, price: int):
    """Update a shop item's price."""
    conn = get_db()
    conn.execute("UPDATE shop_items SET price=? WHERE id=? AND guild_id=?",
                 (price, item_id, guild_id))
    conn.commit()
    conn.close()


def db_reorder_shop_items(guild_id: int, ordered_ids: list[int]):
    """Assign sort_order 1,2,3,... to the given item ids in order."""
    conn = get_db()
    for idx, item_id in enumerate(ordered_ids, 1):
        conn.execute("UPDATE shop_items SET sort_order=? WHERE id=? AND guild_id=?",
                     (idx, item_id, guild_id))
    conn.commit()
    conn.close()


def db_get_shop_item(item_id: int, guild_id: int) -> Optional[dict]:
    """Fetch a single shop item by id."""
    conn = get_db()
    row = conn.execute("SELECT * FROM shop_items WHERE id=? AND guild_id=?", (item_id, guild_id)).fetchone()
    conn.close()
    return dict(row) if row else None

def db_remove_shop_item(item_id: int, guild_id: int):
    conn = get_db()
    conn.execute("DELETE FROM shop_items WHERE id=? AND guild_id=?", (item_id, guild_id))
    conn.execute("DELETE FROM shop_item_rewards WHERE shop_item_id=? AND guild_id=?", (item_id, guild_id))
    conn.commit()
    conn.close()

def db_update_shop_image(item_id: int, guild_id: int, image_url: str | None):
    conn = get_db()
    conn.execute("UPDATE shop_items SET image_url=? WHERE id=? AND guild_id=?",
                 (image_url, item_id, guild_id))
    conn.commit()
    conn.close()

# ── Shop Rewards helpers ───────────────────────────────────────

def db_add_item_reward(shop_item_id: int, guild_id: int, reward_text: str):
    """Store a pre-loaded reward (link/code) for a shop item."""
    conn = get_db()
    conn.execute(
        "INSERT INTO shop_item_rewards (shop_item_id, guild_id, reward_text) VALUES (?,?,?)",
        (shop_item_id, guild_id, reward_text)
    )
    conn.commit()
    conn.close()

def db_get_item_rewards(shop_item_id: int, guild_id: int) -> list:
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM shop_item_rewards WHERE shop_item_id=? AND guild_id=? ORDER BY id",
        (shop_item_id, guild_id)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def db_count_available_rewards(shop_item_id: int, guild_id: int) -> int:
    conn = get_db()
    count = conn.execute(
        "SELECT COUNT(*) FROM shop_item_rewards WHERE shop_item_id=? AND guild_id=? AND used=0",
        (shop_item_id, guild_id)
    ).fetchone()[0]
    conn.close()
    return count

def db_claim_next_reward(shop_item_id: int, guild_id: int, user_id: int) -> Optional[str]:
    """Mark the next available reward as used and return its text. Returns None if none left."""
    conn = get_db()
    row = conn.execute(
        "SELECT id, reward_text FROM shop_item_rewards "
        "WHERE shop_item_id=? AND guild_id=? AND used=0 ORDER BY id LIMIT 1",
        (shop_item_id, guild_id)
    ).fetchone()
    if not row:
        conn.close()
        return None
    conn.execute(
        "UPDATE shop_item_rewards SET used=1, used_by=?, used_at=? WHERE id=?",
        (user_id, datetime.now().isoformat(), row["id"])
    )
    conn.commit()
    conn.close()
    return row["reward_text"]

def db_get_inventory(guild_id: int, user_id: int) -> list:
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM inventory WHERE guild_id=? AND user_id=? ORDER BY purchased_at DESC",
        (guild_id, user_id)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def db_add_inventory(guild_id: int, user_id: int, item_name: str,
                     expires_at: str = None, item_text: str = None):
    conn = get_db()
    conn.execute(
        "INSERT INTO inventory (guild_id, user_id, item_name, purchased_at, expires_at, item_text) VALUES (?,?,?,?,?,?)",
        (guild_id, user_id, item_name, datetime.now().isoformat(), expires_at, item_text)
    )
    conn.commit()
    conn.close()

def db_count_user_purchases(item_name: str, guild_id: int, user_id: int) -> int:
    """Return how many times a user has purchased an item (by name) in this guild."""
    conn = get_db()
    count = conn.execute(
        "SELECT COUNT(*) FROM inventory WHERE guild_id=? AND user_id=? AND item_name=?",
        (guild_id, user_id, item_name)
    ).fetchone()[0]
    conn.close()
    return count

def db_add_pending_purchase(guild_id: int, user_id: int, item_id: int,
                            item_name: str, item_price: int,
                            item_text: Optional[str]) -> int:
    """Insert a pending purchase and return its id."""
    conn = get_db()
    cur_row = conn.execute(
        "INSERT INTO shop_pending_purchases (guild_id, user_id, item_id, item_name, item_price, item_text) "
        "VALUES (?,?,?,?,?,?)",
        (guild_id, user_id, item_id, item_name, item_price, item_text)
    )
    purchase_id = cur_row.lastrowid
    conn.commit()
    conn.close()
    return purchase_id

def db_get_pending_purchase(purchase_id: int) -> Optional[dict]:
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM shop_pending_purchases WHERE id=?", (purchase_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None

def db_resolve_pending_purchase(purchase_id: int, status: str, resolved_by: int):
    conn = get_db()
    conn.execute(
        "UPDATE shop_pending_purchases SET status=?, resolved_at=?, resolved_by=? WHERE id=?",
        (status, datetime.utcnow().isoformat(), resolved_by, purchase_id)
    )
    conn.commit()
    conn.close()

# ── Gift gems helpers ──────────────────────────────────────────

def db_gifts_sent_today(guild_id: int, sender_id: int) -> int:
    """Total gems sent as gifts by this user today."""
    today = datetime.utcnow().strftime("%Y-%m-%d")
    conn = get_db()
    row = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM gems_gifts "
        "WHERE guild_id=? AND sender_id=? AND date(given_at)=?",
        (guild_id, sender_id, today)
    ).fetchone()
    conn.close()
    return row[0] if row else 0

def db_gifts_received_today(guild_id: int, recipient_id: int) -> int:
    """Number of gifts received by this user today (capped at 1 per day by default)."""
    today = datetime.utcnow().strftime("%Y-%m-%d")
    conn = get_db()
    row = conn.execute(
        "SELECT COUNT(*) FROM gems_gifts "
        "WHERE guild_id=? AND recipient_id=? AND date(given_at)=?",
        (guild_id, recipient_id, today)
    ).fetchone()
    conn.close()
    return row[0] if row else 0

def db_record_gift(guild_id: int, sender_id: int, recipient_id: int, amount: int):
    conn = get_db()
    conn.execute(
        "INSERT INTO gems_gifts (guild_id, sender_id, recipient_id, amount) VALUES (?,?,?,?)",
        (guild_id, sender_id, recipient_id, amount)
    )
    conn.commit()
    conn.close()

# ── Reaction helpers ───────────────────────────────────────────

def db_reaction_cooldown_ok(guild_id: int, user_id: int, cooldown_hours: int) -> tuple:
    conn = get_db()
    row = conn.execute("SELECT last_reaction FROM reaction_cooldowns WHERE guild_id=? AND user_id=?",
                       (guild_id, user_id)).fetchone()
    conn.close()
    if not row:
        return True, 0
    last = datetime.fromisoformat(row["last_reaction"])
    elapsed = datetime.now() - last
    if elapsed >= timedelta(hours=cooldown_hours):
        return True, 0
    remaining = timedelta(hours=cooldown_hours) - elapsed
    return False, int(remaining.total_seconds() // 60)

def db_set_reaction_cooldown(guild_id: int, user_id: int):
    conn = get_db()
    now = datetime.now().isoformat()
    conn.execute("""INSERT INTO reaction_cooldowns (guild_id, user_id, last_reaction) VALUES (?,?,?)
                    ON CONFLICT(guild_id, user_id) DO UPDATE SET last_reaction=?""",
                 (guild_id, user_id, now, now))
    conn.commit()
    conn.close()

def db_get_reaction_msg(guild_id: int, message_id: int) -> Optional[dict]:
    conn = get_db()
    row = conn.execute("SELECT * FROM reaction_messages WHERE guild_id=? AND message_id=?",
                       (guild_id, message_id)).fetchone()
    conn.close()
    return dict(row) if row else None

def db_add_reaction_msg(guild_id: int, message_id: int, target_uid: int, given_by: int, amount: int):
    conn = get_db()
    conn.execute("""INSERT OR IGNORE INTO reaction_messages
                    (guild_id, message_id, target_uid, given_by_uid, amount, given_at, cancelled)
                    VALUES (?,?,?,?,?,?,0)""",
                 (guild_id, message_id, target_uid, given_by, amount, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def db_cancel_reaction_msg(guild_id: int, message_id: int):
    """Mark a reaction_messages row as cancelled (keeps it so ✅ cannot re-give)."""
    conn = get_db()
    conn.execute("UPDATE reaction_messages SET cancelled=1 WHERE guild_id=? AND message_id=?",
                 (guild_id, message_id))
    conn.commit()
    conn.close()

def db_block_reaction_msg(guild_id: int, message_id: int):
    """Insert a pre-cancelled row so no ✅ award can happen on this message."""
    conn = get_db()
    conn.execute("""INSERT OR IGNORE INTO reaction_messages
                    (guild_id, message_id, target_uid, given_by_uid, amount, given_at, cancelled)
                    VALUES (?,?,0,0,0,?,1)""",
                 (guild_id, message_id, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def db_remove_reaction_msg(guild_id: int, message_id: int):
    conn = get_db()
    conn.execute("DELETE FROM reaction_messages WHERE guild_id=? AND message_id=?", (guild_id, message_id))
    conn.commit()
    conn.close()

# ── Streak helpers ─────────────────────────────────────────────

def db_get_streak(guild_id: int, user_id: int) -> dict:
    conn = get_db()
    row = conn.execute("SELECT * FROM streaks WHERE guild_id=? AND user_id=?", (guild_id, user_id)).fetchone()
    conn.close()
    return dict(row) if row else {"current_streak": 0, "max_streak": 0, "last_video_id": None}

def db_update_streak(guild_id: int, user_id: int, current_streak: int, last_video_id: str):
    conn = get_db()
    row = conn.execute("SELECT max_streak FROM streaks WHERE guild_id=? AND user_id=?",
                       (guild_id, user_id)).fetchone()
    max_streak = max(row["max_streak"] if row else 0, current_streak)
    conn.execute("""INSERT INTO streaks (guild_id, user_id, current_streak, max_streak, last_video_id)
                    VALUES (?,?,?,?,?)
                    ON CONFLICT(guild_id, user_id) DO UPDATE SET
                    current_streak=?, max_streak=?, last_video_id=?""",
                 (guild_id, user_id, current_streak, max_streak, last_video_id,
                  current_streak, max_streak, last_video_id))
    conn.commit()
    conn.close()
    return max_streak

# ── User stats helpers ─────────────────────────────────────────

def db_get_stats(guild_id: int, user_id: int) -> dict:
    conn = get_db()
    row = conn.execute("SELECT * FROM user_stats WHERE guild_id=? AND user_id=?", (guild_id, user_id)).fetchone()
    conn.close()
    return dict(row) if row else {
        "total_shares": 0, "total_invites": 0, "total_boosts": 0,
        "total_quests_done": 0, "max_streak_ever": 0
    }

def db_snooze_notification(guild_id: int, user_id: int, minutes: int) -> None:
    """Record that a user dismissed the notification prompt; suppress it for `minutes` minutes.
    Pass 0 to immediately expire (always show again on next command)."""
    if minutes <= 0:
        until = datetime.utcnow().isoformat()  # already expired
    else:
        until = (datetime.utcnow() + timedelta(minutes=minutes)).isoformat()
    conn = get_db()
    conn.execute(
        "INSERT INTO notification_snooze (guild_id, user_id, snoozed_until) VALUES (?,?,?) "
        "ON CONFLICT(guild_id, user_id) DO UPDATE SET snoozed_until=excluded.snoozed_until",
        (guild_id, user_id, until)
    )
    conn.commit()
    conn.close()

def db_is_notification_snoozed(guild_id: int, user_id: int) -> bool:
    """Return True if the user snoozed the notification prompt and the cooldown has not expired."""
    conn = get_db()
    row = conn.execute(
        "SELECT snoozed_until FROM notification_snooze WHERE guild_id=? AND user_id=?",
        (guild_id, user_id)
    ).fetchone()
    conn.close()
    if not row:
        return False
    try:
        return datetime.utcnow() < datetime.fromisoformat(row["snoozed_until"])
    except Exception:
        return False

def db_increment_stat(guild_id: int, user_id: int, column: str, amount: int = 1):
    conn = get_db()
    conn.execute("""INSERT INTO user_stats (guild_id, user_id) VALUES (?,?)
                    ON CONFLICT(guild_id, user_id) DO NOTHING""", (guild_id, user_id))
    conn.execute(f"UPDATE user_stats SET {column} = {column} + ? WHERE guild_id=? AND user_id=?",
                 (amount, guild_id, user_id))
    conn.commit()
    conn.close()

def db_update_max_streak_stat(guild_id: int, user_id: int, streak: int):
    conn = get_db()
    conn.execute("""INSERT INTO user_stats (guild_id, user_id, max_streak_ever) VALUES (?,?,?)
                    ON CONFLICT(guild_id, user_id) DO UPDATE SET max_streak_ever=MAX(max_streak_ever, ?)""",
                 (guild_id, user_id, streak, streak))
    conn.commit()
    conn.close()

# ── Daily quest DB helpers ─────────────────────────────────────

import random as _random

def db_get_daily_quests(guild_id: int, user_id: int, date_key: str) -> list:
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM daily_quests WHERE guild_id=? AND user_id=? AND date_key=?",
        (guild_id, user_id, date_key)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def db_assign_daily_quests(guild_id: int, user_id: int, date_key: str, count: int = 3) -> list:
    """Pick `count` random daily quests for this user if none exist yet.

    Rules:
    - Quests in the same exclusive group (e.g. position quests dq_first1/3/5)
      are mutually exclusive — only ONE from each group is ever assigned.
    - This prevents logically redundant combos such as "be first" + "be in top 5".
    Returns the assigned quest list.
    """
    existing = db_get_daily_quests(guild_id, user_id, date_key)
    if existing:
        # Normalize older assignments that used a specific member instead of the
        # Gems Owner role. This keeps already-created quests aligned with the
        # current workflow without changing their progress.
        old_bonus = [
            row for row in existing
            if row.get("quest_key") == "dq_get_react"
            and "Gems Owner role" not in (row.get("quest_name") or "")
        ]
        if old_bonus:
            legacy_cfg = db_get_config(guild_id)
            legacy_role_id = legacy_cfg.get("manager_role_id")
            legacy_role_text = (
                f"<@&{legacy_role_id}> (Gems Owner role)"
                if legacy_role_id else "the Gems Owner role"
            )
            conn_old = get_db()
            conn_old.execute(
                "UPDATE daily_quests SET quest_name=? "
                "WHERE guild_id=? AND user_id=? AND date_key=? AND quest_key=?",
                (f"Ping {legacy_role_text} for a Gems bonus",
                 guild_id, user_id, date_key, "dq_get_react"),
            )
            conn_old.commit()
            conn_old.close()
            existing = db_get_daily_quests(guild_id, user_id, date_key)
        return existing

    # Build a de-grouped pool: keep at most one representative per exclusive group
    pool = list(DAILY_QUEST_POOL)
    chosen: list = []
    used_groups: set = set()
    _random.shuffle(pool)
    for q in pool:
        if len(chosen) >= count:
            break
        grp = q.get("group")
        if grp and grp in used_groups:
            continue  # skip — another quest from this group is already chosen
        chosen.append(q)
        if grp:
            used_groups.add(grp)

    conn = get_db()
    for q in chosen:
        target = q["target"]
        name   = q["name"]
        # dq_messages: randomise target and embed the configured chat channel as a clickable mention
        if q["type"] == "dq_messages":
            target     = _random.randint(10, 50)
            dq_cfg     = db_get_config(guild_id)
            msgs_ch_id = dq_cfg.get("daily_quest_messages_channel_id")
            ch_str     = f"<#{msgs_ch_id}>" if msgs_ch_id else "the chat"
            name       = f"Send {target} messages in {ch_str}"
        elif q["type"] == "dq_get_react":
            dq_cfg = db_get_config(guild_id)
            owner_role_id = dq_cfg.get("manager_role_id")
            role_text = f"<@&{owner_role_id}> (Gems Owner role)" if owner_role_id else "the Gems Owner role"
            name = f"Ping {role_text} for a Gems bonus"
        conn.execute(
            "INSERT OR IGNORE INTO daily_quests "
            "(guild_id, user_id, date_key, quest_key, quest_type, quest_target, quest_name) "
            "VALUES (?,?,?,?,?,?,?)",
            (guild_id, user_id, date_key, q["key"], q["type"], target, name)
        )
    conn.commit()
    conn.close()
    return db_get_daily_quests(guild_id, user_id, date_key)

def db_mark_daily_quest_complete(guild_id: int, user_id: int, date_key: str,
                                  quest_key: str, xp: int) -> bool:
    """Mark a daily quest complete and award XP. Returns True if newly completed."""
    conn = get_db()
    row = conn.execute(
        "SELECT completed FROM daily_quests WHERE guild_id=? AND user_id=? AND date_key=? AND quest_key=?",
        (guild_id, user_id, date_key, quest_key)
    ).fetchone()
    if not row or row["completed"]:
        conn.close()
        return False
    conn.execute(
        "UPDATE daily_quests SET completed=1, xp_awarded=? WHERE guild_id=? AND user_id=? AND date_key=? AND quest_key=?",
        (xp, guild_id, user_id, date_key, quest_key)
    )
    conn.commit()
    conn.close()
    return True

def db_daily_quest_progress(guild_id: int, user_id: int, date_key: str,
                             quest_type: str, amount: int = 1):
    """Increment progress for all matching incomplete daily quests of this type."""
    conn = get_db()
    rows = conn.execute(
        "SELECT quest_key, quest_target, progress, completed FROM daily_quests "
        "WHERE guild_id=? AND user_id=? AND date_key=? AND quest_type=? AND completed=0",
        (guild_id, user_id, date_key, quest_type)
    ).fetchall()
    newly_done = []
    for row in rows:
        new_prog = row["progress"] + amount
        if new_prog >= row["quest_target"]:
            conn.execute(
                "UPDATE daily_quests SET progress=?, completed=1 WHERE guild_id=? AND user_id=? AND date_key=? AND quest_key=?",
                (new_prog, guild_id, user_id, date_key, row["quest_key"])
            )
            newly_done.append(row["quest_key"])
        else:
            conn.execute(
                "UPDATE daily_quests SET progress=? WHERE guild_id=? AND user_id=? AND date_key=? AND quest_key=?",
                (new_prog, guild_id, user_id, date_key, row["quest_key"])
            )
    conn.commit()
    conn.close()
    return newly_done

def db_today_key() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d")

# ── Monthly quest helpers ──────────────────────────────────────

def current_month_key() -> str:
    return datetime.now().strftime("%Y-%m")

def db_get_user_quests(guild_id: int, user_id: int, month_key: str) -> list:
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM monthly_quests WHERE guild_id=? AND user_id=? AND month_key=?",
        (guild_id, user_id, month_key)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def db_is_quest_key_enabled(guild_id: int, quest_key: str) -> bool:
    conn = get_db()
    row = conn.execute("SELECT enabled FROM quest_pool_config WHERE guild_id=? AND quest_key=?",
                       (guild_id, quest_key)).fetchone()
    conn.close()
    return (row["enabled"] != 0) if row else True  # default enabled

def db_assign_monthly_quests(guild_id: int, user_id: int, month_key: str):
    """Assign one quest per rarity for this user/month (skip if already assigned).
    Diamond is ALWAYS the "Complete all 4 monthly quests" quest when enabled —
    this guarantees the chain quest is always present.
    Other rarities get a random quest from their pool."""
    existing = db_get_user_quests(guild_id, user_id, month_key)
    existing_rarities = {q["rarity"] for q in existing}
    conn = get_db()
    for rarity in RARITIES:
        if rarity in existing_rarities:
            continue
        if rarity == "diamond":
            # Diamond is always the "all_quests" quest when enabled
            all_q = next((q for q in QUEST_POOL["diamond"] if q["key"] == "all_quests"), None)
            if all_q and db_is_quest_key_enabled(guild_id, "all_quests"):
                quest = all_q
            else:
                # Fallback: any other diamond quest
                pool = [q for q in QUEST_POOL["diamond"] if q["key"] != "all_quests"
                        and db_is_quest_key_enabled(guild_id, q["key"])]
                if not pool:
                    pool = [q for q in QUEST_POOL["diamond"] if q["key"] != "all_quests"]
                if not pool:
                    pool = QUEST_POOL["diamond"]
                quest = random.choice(pool)
        else:
            pool = [q for q in QUEST_POOL[rarity] if db_is_quest_key_enabled(guild_id, q["key"])]
            if not pool:
                pool = QUEST_POOL[rarity]  # fallback: use all if all disabled
            quest = random.choice(pool)
        conn.execute(
            """INSERT OR IGNORE INTO monthly_quests
               (guild_id, user_id, month_key, rarity, quest_key, quest_type, quest_target, quest_name)
               VALUES (?,?,?,?,?,?,?,?)""",
            (guild_id, user_id, month_key, rarity, quest["key"],
             quest["type"], quest["target"], quest["name"])
        )
    conn.commit()
    conn.close()

def db_update_quest_progress(guild_id: int, user_id: int, quest_type: str,
                              amount: int = 1, value: int = None) -> list:
    """
    Update quest progress for all active quests matching quest_type.
    value: for streak quests — set if current value > progress.
    Returns list of newly completed quest dicts.
    """
    month_key = current_month_key()
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM monthly_quests WHERE guild_id=? AND user_id=? AND month_key=? AND quest_type=? AND completed=0",
        (guild_id, user_id, month_key, quest_type)
    ).fetchall()
    newly_done = []
    for row in rows:
        quest = dict(row)
        if value is not None:
            new_prog = max(quest["progress"], value)
        else:
            new_prog = quest["progress"] + amount
        completed = 1 if new_prog >= quest["quest_target"] else 0
        conn.execute(
            "UPDATE monthly_quests SET progress=?, completed=? WHERE guild_id=? AND user_id=? AND month_key=? AND rarity=?",
            (new_prog, completed, guild_id, user_id, month_key, quest["rarity"])
        )
        if completed and not quest["completed"]:
            newly_done.append(quest)
    conn.commit()
    conn.close()
    return newly_done

def db_get_all_quests_completed(guild_id: int, user_id: int, month_key: str,
                                 exclude_rarity: str = "diamond") -> bool:
    conn = get_db()
    rows = conn.execute(
        "SELECT completed FROM monthly_quests WHERE guild_id=? AND user_id=? AND month_key=? AND rarity != ?",
        (guild_id, user_id, month_key, exclude_rarity)
    ).fetchall()
    conn.close()
    if not rows:
        return False
    return all(r["completed"] for r in rows)

# ── Achievement helpers ────────────────────────────────────────

def db_get_achievement_config(guild_id: int, achievement_key: str) -> list:
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM achievement_config WHERE guild_id=? AND achievement_key=? ORDER BY tier",
        (guild_id, achievement_key)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def db_has_achievement(guild_id: int, user_id: int, achievement_key: str, tier: int) -> bool:
    conn = get_db()
    row = conn.execute(
        "SELECT 1 FROM achievements WHERE guild_id=? AND user_id=? AND achievement_key=? AND tier=?",
        (guild_id, user_id, achievement_key, tier)
    ).fetchone()
    conn.close()
    return row is not None

def db_unlock_achievement(guild_id: int, user_id: int, achievement_key: str, tier: int):
    conn = get_db()
    conn.execute(
        "INSERT OR IGNORE INTO achievements (guild_id, user_id, achievement_key, tier, unlocked_at) VALUES (?,?,?,?,?)",
        (guild_id, user_id, achievement_key, tier, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()

def db_ensure_achievement_config(guild_id: int):
    """Insert default achievement config rows for this guild if missing."""
    conn = get_db()
    for ach in ACHIEVEMENT_DEFS:
        for i, threshold in enumerate(ach["tiers"]):
            conn.execute(
                "INSERT OR IGNORE INTO achievement_config (guild_id, achievement_key, tier, threshold) VALUES (?,?,?,?)",
                (guild_id, ach["key"], i, threshold)
            )
    conn.commit()
    conn.close()

# ── Event helpers ──────────────────────────────────────────────

def db_get_active_events(guild_id: int) -> list:
    now = datetime.now().isoformat()
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM events WHERE guild_id=? AND enabled=1 AND start_date<=? AND end_date>=?",
        (guild_id, now, now)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def db_get_all_events(guild_id: int) -> list:
    conn = get_db()
    rows = conn.execute("SELECT * FROM events WHERE guild_id=? ORDER BY start_date DESC", (guild_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def db_has_double_xp(guild_id: int) -> float:
    """Returns multiplier (1.0 = no event, 2.0 = double XP)."""
    active = db_get_active_events(guild_id)
    for ev in active:
        if ev["event_type"] == "double_xp":
            try:
                cfg = json.loads(ev["config_json"] or "{}")
                return float(cfg.get("multiplier", 2.0))
            except Exception:
                return 2.0
    return 1.0

def db_get_community_goals(guild_id: int, event_id: int = None) -> list:
    conn = get_db()
    if event_id:
        rows = conn.execute("SELECT * FROM community_goals WHERE guild_id=? AND event_id=? AND enabled=1",
                            (guild_id, event_id)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM community_goals WHERE guild_id=? AND enabled=1", (guild_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def db_add_goal_contribution(guild_id: int, goal_id: int, user_id: int, amount: int = 1) -> dict:
    """Add user contribution to a community goal. Returns updated goal."""
    conn = get_db()
    row = conn.execute("SELECT * FROM community_goals WHERE id=? AND guild_id=?", (goal_id, guild_id)).fetchone()
    if not row:
        conn.close()
        return {}
    goal = dict(row)
    contribs = json.loads(goal["contributors"] or "[]")
    if user_id not in contribs:
        contribs.append(user_id)
    new_current = goal["current"] + amount
    completed = 1 if new_current >= goal["target"] and not goal["completed"] else goal["completed"]
    conn.execute(
        "UPDATE community_goals SET current=?, contributors=?, completed=? WHERE id=?",
        (new_current, json.dumps(contribs), completed, goal_id)
    )
    conn.commit()
    goal["current"] = new_current
    goal["contributors"] = contribs
    goal["completed"] = completed
    conn.close()
    return goal

# ── Invite cache helpers ───────────────────────────────────────

def db_cache_invites(guild_id: int, invites: list):
    conn = get_db()
    for inv in invites:
        conn.execute(
            "INSERT INTO invites_cache (guild_id, invite_code, inviter_id, uses) VALUES (?,?,?,?) "
            "ON CONFLICT(guild_id, invite_code) DO UPDATE SET uses=?, inviter_id=?",
            (guild_id, inv.code, inv.inviter.id if inv.inviter else 0, inv.uses,
             inv.uses, inv.inviter.id if inv.inviter else 0)
        )
    conn.commit()
    conn.close()

def db_log_invite(guild_id: int, member_id: int, inviter_id: int, xp_given: int):
    """Record that member_id was invited by inviter_id (prevents double-counting)."""
    conn = get_db()
    conn.execute(
        "INSERT OR REPLACE INTO invite_log (guild_id, member_id, inviter_id, xp_given) VALUES (?,?,?,?)",
        (guild_id, member_id, inviter_id, xp_given)
    )
    conn.commit()
    conn.close()

def db_get_invite_log(guild_id: int, member_id: int) -> Optional[dict]:
    """Return the invite record for member_id in this guild, or None."""
    conn = get_db()
    row = conn.execute(
        "SELECT inviter_id, xp_given FROM invite_log WHERE guild_id=? AND member_id=?",
        (guild_id, member_id)
    ).fetchone()
    conn.close()
    return dict(row) if row else None

def db_remove_invite_log(guild_id: int, member_id: int):
    """Delete the invite record when the invited member leaves."""
    conn = get_db()
    conn.execute("DELETE FROM invite_log WHERE guild_id=? AND member_id=?", (guild_id, member_id))
    conn.commit()
    conn.close()

def db_find_used_invite(guild_id: int, current_invites: list) -> Optional[int]:
    """Compare current invite uses to cached to find which invite was used. Returns inviter_id."""
    conn = get_db()
    for inv in current_invites:
        row = conn.execute(
            "SELECT uses, inviter_id FROM invites_cache WHERE guild_id=? AND invite_code=?",
            (guild_id, inv.code)
        ).fetchone()
        if row and inv.uses > row["uses"]:
            inviter_id = row["inviter_id"]
            conn.close()
            return inviter_id if inviter_id else None
    conn.close()
    return None

# ── Backup / Restore ───────────────────────────────────────────

def _registry_update(guild_id: int, channel_id: int):
    try:
        data: dict = {}
        if os.path.exists(BACKUP_REGISTRY):
            with open(BACKUP_REGISTRY, "r") as f:
                data = json.load(f)
        data[str(guild_id)] = channel_id
        with open(BACKUP_REGISTRY, "w") as f:
            json.dump(data, f)
    except Exception as e:
        print(f"[Registry] Could not update: {e}")


def _rebuild_registry_from_db():
    """Reconstruct backup_channels.json from the restored DB.
    Called right after a successful restore so the next restart can find
    the backup channel without doing a full guild scan again."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT guild_id, backup_channel_id FROM guild_config "
            "WHERE backup_channel_id IS NOT NULL"
        ).fetchall()
        conn.close()
        data = {str(r["guild_id"]): r["backup_channel_id"] for r in rows}
        if data:
            with open(BACKUP_REGISTRY, "w") as f:
                json.dump(data, f)
            print(f"[Restore] Registry rebuilt with {len(data)} guild(s).")
    except Exception as e:
        print(f"[Restore] Could not rebuild registry: {e}")


async def restore_from_discord(bot: commands.Bot):
    """Restore the DB from the most recent Discord backup.

    Render (and similar platforms) wipe the filesystem on every deploy, so
    backup_channels.json is gone after each restart.  When the registry is
    missing we fall back to scanning every guild's text channels for a .db
    attachment sent by the bot — this is the self-healing path.  After a
    successful restore we immediately rebuild the registry from the restored
    DB so subsequent restarts skip the slow scan.
    """
    registry: dict = {}

    # ── Fast path: registry file still exists (in-session restart) ──
    if os.path.exists(BACKUP_REGISTRY):
        try:
            with open(BACKUP_REGISTRY, "r") as f:
                registry = json.load(f)
            print("[Restore] Registry loaded from file.")
        except Exception as e:
            print(f"[Restore] Could not read registry: {e}")

    # ── Slow path: registry lost (Render cold-start / redeploy) ─────
    if not registry:
        print("[Restore] Registry missing — scanning guilds for backup files (Render recovery)...")
        for guild in bot.guilds:
            found_ch = None
            for channel in guild.text_channels:
                if found_ch:
                    break
                try:
                    async for msg in channel.history(limit=20):
                        for att in msg.attachments:
                            if att.filename.endswith(".db"):
                                found_ch = channel.id
                                print(f"[Restore] Found backup in #{channel.name} ({guild.name})")
                                break
                        if found_ch:
                            break
                except Exception:
                    continue
            if found_ch:
                registry[str(guild.id)] = found_ch

    if not registry:
        print("[Restore] No .db backup found anywhere — starting fresh.")
        return

    # ── Find the most recent .db attachment across all backup channels ─
    best_message = None
    best_ts = None
    for guild_id_str, ch_id in registry.items():
        ch = bot.get_channel(int(ch_id))
        if not ch:
            continue
        try:
            async for msg in ch.history(limit=50):
                for att in msg.attachments:
                    if att.filename.endswith(".db"):
                        if best_ts is None or msg.created_at > best_ts:
                            best_message = msg
                            best_ts = msg.created_at
                        break
        except Exception as e:
            print(f"[Restore] Error reading channel {ch_id}: {e}")

    if not best_message:
        print("[Restore] No .db backup found — starting fresh.")
        return

    att = next(a for a in best_message.attachments if a.filename.endswith(".db"))
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(att.url) as resp:
                if resp.status != 200:
                    print(f"[Restore] Download failed — HTTP {resp.status}")
                    return
                data = await resp.read()
        with open("restore_tmp.db", "wb") as f:
            f.write(data)
        shutil.move("restore_tmp.db", DB_PATH)
        print(f"[Restore] ✅ Restored from {best_ts.strftime('%Y-%m-%d %H:%M:%S')} UTC")
        # Immediately rebuild the registry so the next restart is fast
        _rebuild_registry_from_db()
    except Exception as e:
        print(f"[Restore] Error downloading backup: {e}")

async def do_backup(bot: commands.Bot, guild_id: int):
    config = db_get_config(guild_id)
    ch_id = config.get("backup_channel_id")
    if not ch_id:
        return
    ch = bot.get_channel(ch_id)
    if not ch:
        return
    backup_path = f"backup_{guild_id}.db"
    shutil.copy2(DB_PATH, backup_path)
    try:
        await ch.send(
            f"💾 **Automatic backup** — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            file=discord.File(backup_path)
        )
        _registry_update(guild_id, ch_id)
    except Exception as e:
        print(f"[Backup] {e}")
    finally:
        try:
            os.remove(backup_path)
        except Exception:
            pass

# ══════════════════════════════════════════════════════════════
#  YOUTUBE
# ══════════════════════════════════════════════════════════════

YT_ID_RE = re.compile(
    r'(?:youtube\.com/(?:shorts/|watch\?(?:.*&)?v=)|youtu\.be/)([a-zA-Z0-9_-]{11})(?=[^a-zA-Z0-9_-]|$)'
)

def extract_video_id(text: str) -> Optional[str]:
    m = YT_ID_RE.search(text)
    return m.group(1) if m else None

def make_shorts_url(video_id: str) -> str:
    return f"https://youtube.com/shorts/{video_id}"

def make_watch_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"

async def resolve_youtube_channel_id(handle_or_id: str) -> Optional[str]:
    cleaned = handle_or_id.strip()
    if re.match(r'^UC[a-zA-Z0-9_-]{22}$', cleaned):
        return cleaned
    handle = cleaned.lstrip('@')
    url = f"https://www.youtube.com/@{handle}"
    try:
        async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    return None
                html = await resp.text()
                for pattern in [r'"channelId"\s*:\s*"(UC[a-zA-Z0-9_-]{22})"',
                                 r'"externalChannelId"\s*:\s*"(UC[a-zA-Z0-9_-]{22})"']:
                    m = re.search(pattern, html)
                    if m:
                        return m.group(1)
    except Exception as e:
        print(f"[YouTube] Resolve failed for {handle}: {e}")
    return None

async def fetch_latest_videos(channel_id: str) -> list:
    feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    try:
        # Cache-busting headers so we get the freshest RSS possible
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; MeepleBot/2.0)",
            "Cache-Control": "no-cache, no-store",
            "Pragma": "no-cache",
        }
        async with aiohttp.ClientSession() as s:
            async with s.get(feed_url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return []
                text = await resp.text()
        root = ET.fromstring(text)
        ns = {'atom': 'http://www.w3.org/2005/Atom', 'yt': 'http://www.youtube.com/xml/schemas/2015'}
        videos = []
        for entry in root.findall('atom:entry', ns):
            vid_el   = entry.find('yt:videoId', ns)
            title_el = entry.find('atom:title', ns)
            link_el  = entry.find('atom:link', ns)
            pub_el   = entry.find('atom:published', ns)
            if vid_el is None:
                continue
            vid     = vid_el.text
            pub_str = pub_el.text if pub_el is not None else ''
            videos.append({
                'video_id':  vid,
                'title':     title_el.text if title_el is not None else 'Video',
                'url':       link_el.get('href', make_watch_url(vid)) if link_el is not None else make_watch_url(vid),
                'published': pub_str,
            })
        # Sort newest-first by published date (defensive — RSS order is usually correct but not guaranteed)
        videos.sort(key=lambda v: v['published'], reverse=True)
        return videos
    except Exception as e:
        print(f"[YouTube] RSS fetch error for {channel_id}: {e}")
        return []

WEBSUB_HUB = "https://pubsubhubbub.appspot.com/subscribe"

async def websub_subscribe(channel_id: str, callback_url: str, mode: str = "subscribe") -> bool:
    """Subscribe / renew a YouTube PubSubHubbub subscription for one channel."""
    topic = f"https://www.youtube.com/xml/feeds/videos.xml?channel_id={channel_id}"
    data  = {
        "hub.callback":      callback_url,
        "hub.topic":         topic,
        "hub.verify":        "async",
        "hub.mode":          mode,
        "hub.lease_seconds": "864000",   # 10 days max
    }
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(WEBSUB_HUB, data=data, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status in (202, 204):
                    print(f"[WebSub] ✅ {mode} OK for channel {channel_id}")
                    return True
                body = await resp.text()
                print(f"[WebSub] ❌ {mode} failed ({resp.status}): {body}")
                return False
    except Exception as e:
        print(f"[WebSub] Error during {mode}: {e}")
        return False

async def handle_websub_notification(body: bytes, guild_id: int) -> None:
    """Parse a WebSub push body and announce the video if it is genuinely new."""
    try:
        root = ET.fromstring(body)
        ns = {
            'atom': 'http://www.w3.org/2005/Atom',
            'yt':   'http://www.youtube.com/xml/schemas/2015',
        }
        entry = root.find('atom:entry', ns)
        if entry is None:
            return  # deletion or empty notification
        vid_el   = entry.find('yt:videoId', ns)
        title_el = entry.find('atom:title', ns)
        link_el  = entry.find('atom:link', ns)
        if vid_el is None:
            return
        video_id = vid_el.text
        title    = title_el.text if title_el is not None else 'Video'
        url      = (link_el.get('href', make_watch_url(video_id))
                    if link_el is not None else make_watch_url(video_id))

        current = db_get_current_video(guild_id)
        if current and current["video_id"] == video_id:
            return  # already announced

        print(f"[WebSub] 🆕 Push for guild {guild_id}: {video_id} — {title}")
        db_set_current_video(guild_id, video_id, url, title)
        await announce_video(bot, guild_id, video_id, url, title)
    except Exception as e:
        print(f"[WebSub] Parse error: {e}")

def parse_rss_date(date_str: str) -> Optional[datetime]:
    """Parse an RSS/Atom published date string to a UTC-naive datetime.
    YouTube uses ISO 8601 with timezone offset, e.g. '2024-01-15T10:30:00+00:00'.
    """
    if not date_str:
        return None
    try:
        # Strip timezone suffix so we get a plain UTC-naive datetime
        clean = re.sub(r'[Zz]$', '', date_str.strip())
        clean = re.sub(r'[+-]\d{2}:\d{2}$', '', clean)
        return datetime.fromisoformat(clean)
    except Exception:
        return None

# ══════════════════════════════════════════════════════════════
#  PERMISSIONS
# ══════════════════════════════════════════════════════════════

def is_xp_manager(member: discord.Member, config: dict) -> bool:
    role_id = config.get("manager_role_id")
    if not role_id:
        return member.guild_permissions.administrator
    return any(r.id == role_id for r in member.roles)

def in_commands_channel(interaction: discord.Interaction, config: dict) -> bool:
    ch_id = config.get("commands_channel_id")
    if not ch_id:
        return True  # no restriction if not configured
    return interaction.channel_id == ch_id

# ══════════════════════════════════════════════════════════════
#  EMBED HELPERS
# ══════════════════════════════════════════════════════════════

def E(title: str = "", description: str = "", color: int = C_MAIN) -> discord.Embed:
    e = discord.Embed(title=title, description=description, color=color)
    e.timestamp = datetime.now()
    return e

def _ch(v) -> str:  return f"<#{v}>" if v else "`Not set`"
def _role(v) -> str: return f"<@&{v}>" if v else "`Not set`"
def _val(v, suffix: str = "") -> str: return f"**{v}{suffix}**" if v is not None else "`Not set`"
def _bool(v) -> str: return "✅ Enabled" if v else "❌ Disabled"

def _safe_int(value, default: int) -> int:
    """Convert a persisted config value without breaking a Discord interaction."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default

def parse_channel_id(value: str) -> Optional[int]:
    m = re.search(r'<#(\d+)>', value) or re.search(r'(\d+)', value)
    return int(m.group(1)) if m else None

def parse_user_id(value: str) -> Optional[int]:
    m = re.search(r'<@!?(\d+)>', value) or re.search(r'(\d{17,20})', value)
    return int(m.group(1)) if m else None

def parse_role_id(value: str) -> Optional[int]:
    m = re.search(r'<@&(\d+)>', value) or re.search(r'^(\d{17,20})$', value.strip())
    return int(m.group(1)) if m else None

async def send_log(bot: commands.Bot, guild_id: int, actor: discord.Member, action: str, details: str = ""):
    config = db_get_config(guild_id)
    ch_id = config.get("log_channel_id")
    if not ch_id:
        return
    ch = bot.get_channel(ch_id)
    if not ch:
        return
    e = E(color=C_MAIN)
    e.set_author(name=str(actor), icon_url=actor.display_avatar.url if actor.display_avatar else None)
    e.add_field(name="Action", value=action, inline=False)
    if details:
        e.add_field(name="Details", value=details, inline=False)
    e.set_footer(text=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"))
    try:
        await ch.send(embed=e)
    except Exception:
        pass


async def bot_log(bot: commands.Bot, guild_id: int, title: str, description: str, color: int = C_MAIN):
    """Log a bot-triggered action to the log channel (no human actor)."""
    config = db_get_config(guild_id)
    ch_id = config.get("log_channel_id")
    if not ch_id:
        return
    ch = bot.get_channel(ch_id)
    if not ch:
        return
    e = discord.Embed(title=title, description=description, color=color)
    e.set_footer(text=f"Bot • {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    try:
        await ch.send(embed=e)
    except Exception:
        pass

async def notify_admin(bot: commands.Bot, guild_id: int, content: str = "", embed: discord.Embed = None):
    config = db_get_config(guild_id)
    ch_id = config.get("admin_channel_id")
    if not ch_id:
        return
    ch = bot.get_channel(ch_id)
    if not ch:
        return
    try:
        await ch.send(content=content, embed=embed)
    except Exception:
        pass

async def notify_xp(bot: commands.Bot, guild_id: int, content: str = "", embed: discord.Embed = None):
    config = db_get_config(guild_id)
    ch_id = config.get("notification_channel_id")
    if not ch_id:
        return
    ch = bot.get_channel(ch_id)
    if not ch:
        return
    try:
        await ch.send(content=content, embed=embed)
    except Exception:
        pass

# ══════════════════════════════════════════════════════════════
#  STREAK NICKNAME
# ══════════════════════════════════════════════════════════════

async def update_streak_nickname(guild: discord.Guild, user_id: int, streak: int):
    """
    Update member nickname to show streak: "Username 🔥N"
    Preserves the configured nickname prefix if the member has the prefix role.
    Requires bot role above member + Manage Nicknames permission.
    Cannot change the server owner's nickname (Discord limitation).
    """
    member = guild.get_member(user_id)
    if not member:
        return
    # Discord never allows bots to change the server owner's nickname
    if member.id == guild.owner_id:
        return
    config = db_get_config(guild.id)
    nick_prefix    = config.get("nick_prefix") or ""
    prefix_role_id = config.get("prefix_role_id")
    has_prefix = bool(
        nick_prefix and prefix_role_id and
        any(r.id == prefix_role_id for r in member.roles)
    )
    base_name = member.display_name
    # Remove existing streak suffix
    base_name = re.sub(r'\s*🔥\d+$', '', base_name).strip()
    # Remove prefix if present so we work with the clean username
    if nick_prefix and base_name.startswith(nick_prefix):
        base_name = base_name[len(nick_prefix):]
    # Rebuild: prefix (if applicable) + base + streak suffix
    new_name = (nick_prefix + base_name) if has_prefix else base_name
    if streak > 0:
        new_name = f"{new_name} 🔥{streak}"
    if new_name[:32] == member.display_name[:32]:
        return
    try:
        await member.edit(nick=new_name[:32])
    except discord.Forbidden:
        print(f"[Streak] ⚠️  Cannot update nickname for {member} ({user_id}): "
              f"bot role must be ABOVE the member's highest role and have Manage Nicknames. "
              f"Check role hierarchy in Server Settings → Roles.")
    except discord.HTTPException as e:
        print(f"[Streak] Nick update error for {user_id}: {e}")

# ══════════════════════════════════════════════════════════════
#  NICKNAME PREFIX (role-based)
# ══════════════════════════════════════════════════════════════

async def apply_nick_prefix(guild: discord.Guild, member: discord.Member, add: bool):
    """
    Add or remove the configured nickname prefix for a member.
    Preserves the existing streak suffix (🔥N) so both features coexist cleanly.
    add=True  → <prefix><base> 🔥N
    add=False → <base> 🔥N  (prefix stripped)
    Silently skips the server owner (Discord limitation) and bots.
    """
    if member.id == guild.owner_id or member.bot:
        return
    config = db_get_config(guild.id)
    nick_prefix = config.get("nick_prefix") or "404 | "
    if not nick_prefix:
        return
    # Retrieve current streak so we can preserve it
    streak_data = db_get_streak(guild.id, member.id)
    streak = streak_data["current_streak"] if streak_data else 0
    # Strip both prefix and streak to get the raw username
    base_name = member.display_name
    base_name = re.sub(r'\s*🔥\d+$', '', base_name).strip()
    if base_name.startswith(nick_prefix):
        base_name = base_name[len(nick_prefix):]
    # Rebuild
    new_name = (nick_prefix + base_name) if add else base_name
    if streak > 0:
        new_name = f"{new_name} 🔥{streak}"
    if new_name[:32] == member.display_name[:32]:
        return
    try:
        await member.edit(nick=new_name[:32])
    except discord.Forbidden:
        pass  # Bot role not high enough — skip silently
    except discord.HTTPException as e:
        print(f"[NickPrefix] Error updating nickname for {member}: {e}")

# ══════════════════════════════════════════════════════════════
#  QUEST & ACHIEVEMENT PROCESSING
# ══════════════════════════════════════════════════════════════

async def process_quest_completions(bot: commands.Bot, guild_id: int, user_id: int,
                                    newly_done: list):
    """Award XP and announce newly completed quests."""
    if not newly_done:
        return
    config = db_get_config(guild_id)
    xp_map = {
        "stone": config.get("quest_xp_stone", 50),
        "bronze": config.get("quest_xp_bronze", 100),
        "silver": config.get("quest_xp_silver", 200),
        "gold": config.get("quest_xp_gold", 400),
        "diamond": config.get("quest_xp_diamond", 750),
    }
    guild = bot.get_guild(guild_id)
    member = guild.get_member(user_id) if guild else None
    for quest in newly_done:
        rarity = quest["rarity"]
        xp_reward = xp_map.get(rarity, 50)
        # Mark as awarded
        conn = get_db()
        conn.execute(
            "UPDATE monthly_quests SET xp_awarded=? WHERE guild_id=? AND user_id=? AND month_key=? AND rarity=?",
            (xp_reward, guild_id, user_id, quest["month_key"], rarity)
        )
        conn.commit()
        conn.close()
        db_add_xp(guild_id, user_id, xp_reward)
        db_increment_stat(guild_id, user_id, "total_quests_done")
        # Check all_quests (diamond dependency) — increment by 1 per completed non-diamond quest
        if quest["quest_type"] != "all_quests" and rarity != "diamond":
            diamond_done = db_update_quest_progress(guild_id, user_id, "all_quests", amount=1)
            if diamond_done:
                newly_done.extend(diamond_done)
        # Announce
        e = E(
            f"{RARITY_EMOJI[rarity]} Quest Completed!",
            f"**{quest['quest_name']}**\nReward: **+{cur(config, xp_reward)}**",
            RARITY_COLOR[rarity]
        )
        if member:
            e.set_author(name=str(member), icon_url=member.display_avatar.url if member.display_avatar else None)
        await notify_xp(bot, guild_id, embed=e)
        # Log quest completion
        await bot_log(bot, guild_id, f"{RARITY_EMOJI[rarity]} Quest Completed",
                      f"**Member:** {member.mention if member else f'<@{user_id}>'}\n"
                      f"**Quest:** {quest['quest_name']} ({rarity.capitalize()})\n"
                      f"**Reward:** +{cur(config, xp_reward)}", RARITY_COLOR[rarity])
        # Check achievements after quest completion
        await check_achievements(bot, guild_id, user_id)

async def process_daily_quest_completions(bot: commands.Bot, guild_id: int, user_id: int,
                                          newly_done_keys: list, date_key: str):
    """Award XP and announce newly completed daily quests in the quests (or notification) channel."""
    if not newly_done_keys:
        return
    config   = db_get_config(guild_id)
    quest_xp = config.get("daily_quest_xp", 50)
    guild    = bot.get_guild(guild_id)
    member   = guild.get_member(user_id) if guild else None

    ch_id = config.get("quests_channel_id") or config.get("notification_channel_id")
    ch    = bot.get_channel(ch_id) if ch_id else None

    for quest_key in newly_done_keys:
        # Use the name stored in the DB — it may be dynamic (e.g. dq_get_react has the real
        # owner mention, dq_messages has the real channel mention and randomised count).
        # Fall back to the static pool name, then to the raw key.
        _conn_n = get_db()
        _row_n  = _conn_n.execute(
            "SELECT quest_name FROM daily_quests "
            "WHERE guild_id=? AND user_id=? AND date_key=? AND quest_key=?",
            (guild_id, user_id, date_key, quest_key)
        ).fetchone()
        _conn_n.close()
        if _row_n and _row_n["quest_name"]:
            quest_name = _row_n["quest_name"]
        else:
            quest_def  = next((q for q in DAILY_QUEST_POOL if q["key"] == quest_key), None)
            quest_name = quest_def["name"] if quest_def else quest_key

        # Award XP (only if not already awarded for this quest)
        conn = get_db()
        row  = conn.execute(
            "SELECT xp_awarded FROM daily_quests WHERE guild_id=? AND user_id=? AND date_key=? AND quest_key=?",
            (guild_id, user_id, date_key, quest_key)
        ).fetchone()
        already = row and row["xp_awarded"]
        if not already:
            conn.execute(
                "UPDATE daily_quests SET xp_awarded=? WHERE guild_id=? AND user_id=? AND date_key=? AND quest_key=?",
                (quest_xp, guild_id, user_id, date_key, quest_key)
            )
            conn.commit()
            conn.close()
            db_add_xp(guild_id, user_id, quest_xp)
        else:
            conn.close()

        # Announce in quests / notification channel
        e = E("📋 Daily Quest Complete!",
              f"**{quest_name}**\nReward: **+{cur(config, quest_xp)}**",
              C_QUEST)
        if member:
            e.set_author(name=str(member),
                         icon_url=member.display_avatar.url if member.display_avatar else None)
        if ch:
            try:
                await ch.send(embed=e)
            except Exception:
                pass

        # Structured log
        await bot_log(bot, guild_id, "📋 Daily Quest Complete",
                      f"**Member:** {member.mention if member else f'<@{user_id}>'}\n"
                      f"**Quest:** {quest_name}\n"
                      f"**Reward:** +{cur(config, quest_xp)}", C_QUEST)


async def check_achievements(bot: commands.Bot, guild_id: int, user_id: int):
    """Check and unlock achievements based on current stats."""
    db_ensure_achievement_config(guild_id)
    stats = db_get_stats(guild_id, user_id)
    guild = bot.get_guild(guild_id)
    if not guild:
        return
    member = guild.get_member(user_id)
    config = db_get_config(guild_id)
    ach_ch_id = config.get("achievement_channel_id")

    for ach_def in ACHIEVEMENT_DEFS:
        key = ach_def["key"]
        stat_val = stats.get(ach_def["category"], 0)
        tiers = db_get_achievement_config(guild_id, key)
        if not tiers:
            # Use defaults
            for i, threshold in enumerate(ach_def["tiers"]):
                tiers.append({"tier": i, "threshold": threshold, "role_id": None, "enabled": 1})

        for tier_row in tiers:
            if not tier_row.get("enabled", 1):
                continue
            tier = tier_row["tier"]
            threshold = tier_row["threshold"]
            role_id = tier_row.get("role_id")
            if stat_val >= threshold and not db_has_achievement(guild_id, user_id, key, tier):
                db_unlock_achievement(guild_id, user_id, key, tier)
                tier_names = ["I", "II", "III", "IV", "V"]
                tier_label = tier_names[tier] if tier < len(tier_names) else str(tier)
                e = E(
                    f"🏆 Achievement Unlocked!",
                    f"**{ach_def['name']} {tier_label}**\n_{threshold}+ {ach_def['category'].replace('_',' ')}_",
                    C_ACHIEVE
                )
                if member:
                    e.set_author(name=str(member), icon_url=member.display_avatar.url if member.display_avatar else None)
                    if role_id:
                        role = guild.get_role(role_id)
                        if role:
                            try:
                                await member.add_roles(role, reason="Achievement unlocked")
                                e.add_field(name="Role awarded", value=f"<@&{role_id}>", inline=False)
                            except Exception:
                                pass
                # Announce in achievement channel
                if ach_ch_id:
                    ch = bot.get_channel(ach_ch_id)
                    if ch:
                        try:
                            await ch.send(
                                content=f"🏆 {member.mention if member else f'<@{user_id}>'}" ,
                                embed=e
                            )
                        except Exception:
                            pass
                # Log achievement unlock
                role_str = f" | Role: <@&{role_id}>" if role_id else ""
                await bot_log(bot, guild_id, "🏆 Achievement Unlocked",
                              f"**Member:** {member.mention if member else f'<@{user_id}>'}\n"
                              f"**Achievement:** {ach_def['name']} {tier_label}\n"
                              f"**Threshold:** {threshold}+ {ach_def['category'].replace('_',' ')}"
                              + role_str, C_ACHIEVE)

async def announce_video(bot: commands.Bot, guild_id: int, video_id: str, video_url: str, video_title: str):
    config = db_get_config(guild_id)
    share_id   = config.get("share_channel_id")
    ping_role  = config.get("share_ping_role_id")
    window_min = config.get("share_window_min") or 20
    if not share_id:
        return
    ch = bot.get_channel(share_id)
    if not ch:
        return
    deadline_ts = int((datetime.utcnow() + timedelta(minutes=window_min)).timestamp())
    # Store deadline so streak reminder can use it
    conn = get_db()
    conn.execute("UPDATE current_video SET deadline_ts=? WHERE guild_id=?", (deadline_ts, guild_id))
    conn.commit()
    conn.close()
    # Unlock the share channel so members can post
    await _set_share_channel_lock(bot, guild_id, locked=False)
    role_mention = f"<@&{ping_role}>" if ping_role else "@everyone"
    shorts_url = make_shorts_url(video_id)
    # Use custom message if configured; otherwise fall back to the default
    custom_msg = config.get("video_announce_message")
    if custom_msg:
        msg_text = (custom_msg
                    .replace("{mention}", role_mention)
                    .replace("{url}", shorts_url)
                    .replace("{deadline}", f"<t:{deadline_ts}:R>")
                    .replace("{title}", video_title or ""))
    else:
        msg_text = (
            f"{role_mention} 📲 Share the latest video + a screenshot of your comment!\n"
            f"🔗 {shorts_url}\n"
            f"Post your share before <t:{deadline_ts}:R> ⏰"
        )
    try:
        await ch.send(msg_text)
    except Exception as ex:
        print(f"[Announce] Error: {ex}")
    # Log to the log channel
    await bot_log(bot, guild_id, "📺 Video Announced",
                  f"**Title:** {video_title or '(unknown)'}\n**URL:** {shorts_url}\n"
                  f"**Window:** {window_min} min — closes <t:{deadline_ts}:R>", C_INFO)

# ══════════════════════════════════════════════════════════════
#  SHARE CHANNEL LOCK
# ══════════════════════════════════════════════════════════════

# In-memory cache so we don't spam set_permissions on every loop tick.
_SHARE_LOCK_STATE: dict[int, bool] = {}   # guild_id → True = locked

async def _set_share_channel_lock(bot: commands.Bot, guild_id: int, locked: bool) -> None:
    """Deny or restore send_messages for the configured share-lock role in the share channel.

    locked=True  → role cannot send messages (no active video)
    locked=False → permission override removed (video is live, window is open)
    """
    if _SHARE_LOCK_STATE.get(guild_id) == locked:
        return   # Already in the right state — nothing to do
    config       = db_get_config(guild_id)
    share_ch_id  = config.get("share_channel_id")
    lock_role_id = config.get("share_lock_role_id")
    if not share_ch_id or not lock_role_id:
        return
    guild = bot.get_guild(guild_id)
    if not guild:
        return
    ch   = guild.get_channel(share_ch_id)
    role = guild.get_role(lock_role_id)
    if not ch or not role:
        return
    try:
        if locked:
            await ch.set_permissions(role, send_messages=False,
                                     reason="No active share video — channel locked by Meeple Bot")
        else:
            await ch.set_permissions(role, overwrite=None,
                                     reason="Share video announced — channel unlocked by Meeple Bot")
        _SHARE_LOCK_STATE[guild_id] = locked
    except discord.Forbidden:
        print(f"[ShareLock] Missing Manage Channel permission in guild {guild_id}")
    except Exception as e:
        print(f"[ShareLock] Error for guild {guild_id}: {e}")

# ══════════════════════════════════════════════════════════════
#  MODALS
# ══════════════════════════════════════════════════════════════

class Modal1(discord.ui.Modal):
    def __init__(self, title: str, label: str, placeholder: str = "",
                 default: str = "", required: bool = True, max_length: int = 200,
                 paragraph: bool = False, callback=None):
        # Discord rejects modal titles longer than 45 characters. Item names
        # are user-provided, so always clamp dynamic titles before opening.
        super().__init__(title=str(title)[:45])
        self._cb = callback
        style = discord.TextStyle.paragraph if paragraph else discord.TextStyle.short
        self.field = discord.ui.TextInput(label=str(label)[:45], placeholder=str(placeholder)[:100],
                                          default=str(default)[:4000], required=required,
                                          max_length=max_length, style=style)
        self.add_item(self.field)

    async def on_submit(self, interaction: discord.Interaction):
        if self._cb:
            try:
                await self._cb(interaction, self.field.value)
            except Exception as e:
                print(f"[Modal1 error] {e}")
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "❌ An error occurred. Please try again.", ephemeral=True)
        else:
            await interaction.response.defer()

class Modal2(discord.ui.Modal):
    def __init__(self, title: str, label1: str, ph1: str, label2: str, ph2: str,
                 default1: str = "", default2: str = "", required1: bool = True, required2: bool = True,
                 max1: int = 200, max2: int = 200, callback=None):
        super().__init__(title=str(title)[:45])
        self._cb = callback
        self.f1 = discord.ui.TextInput(label=str(label1)[:45], placeholder=str(ph1)[:100], default=str(default1)[:4000], required=required1, max_length=max1)
        self.f2 = discord.ui.TextInput(label=str(label2)[:45], placeholder=str(ph2)[:100], default=str(default2)[:4000], required=required2, max_length=max2)
        self.add_item(self.f1)
        self.add_item(self.f2)

    async def on_submit(self, interaction: discord.Interaction):
        if self._cb:
            try:
                await self._cb(interaction, self.f1.value, self.f2.value)
            except Exception as e:
                print(f"[Modal2 error] {e}")
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "❌ An error occurred. Please try again.", ephemeral=True)
        else:
            await interaction.response.defer()

class Modal3(discord.ui.Modal):
    def __init__(self, title: str,
                 label1: str, ph1: str,
                 label2: str, ph2: str,
                 label3: str, ph3: str,
                 default1="", default2="", default3="",
                 required1=True, required2=True, required3=True,
                 callback=None):
        super().__init__(title=str(title)[:45])
        self._cb = callback
        self.f1 = discord.ui.TextInput(label=str(label1)[:45], placeholder=str(ph1)[:100], default=str(default1)[:4000], required=required1)
        self.f2 = discord.ui.TextInput(label=str(label2)[:45], placeholder=str(ph2)[:100], default=str(default2)[:4000], required=required2)
        self.f3 = discord.ui.TextInput(label=str(label3)[:45], placeholder=str(ph3)[:100], default=str(default3)[:4000], required=required3)
        self.add_item(self.f1); self.add_item(self.f2); self.add_item(self.f3)

    async def on_submit(self, interaction: discord.Interaction):
        if self._cb:
            try:
                await self._cb(interaction, self.f1.value, self.f2.value, self.f3.value)
            except Exception as e:
                print(f"[Modal3 error] {e}")
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "❌ An error occurred. Please try again.", ephemeral=True)
        else:
            await interaction.response.defer()

class Modal4Shop(discord.ui.Modal):
    """4-field modal for shop item creation (image is uploaded separately)."""
    def __init__(self, title: str, currency_label: str = "Gems", callback=None):
        super().__init__(title=str(title)[:45])
        self._cb = callback
        self.f_name  = discord.ui.TextInput(label="Item name (emoji welcome)", placeholder="🎮 Custom Role", max_length=80)
        self.f_price = discord.ui.TextInput(label=f"Price in {str(currency_label)[:30]}", placeholder="500")
        self.f_temp  = discord.ui.TextInput(label="Duration in days (0 = permanent)", placeholder="0 or 30")
        self.f_text  = discord.ui.TextInput(label="Text field label (empty = none)", placeholder="Your game username", required=False)
        for f in [self.f_name, self.f_price, self.f_temp, self.f_text]:
            self.add_item(f)

    async def on_submit(self, interaction: discord.Interaction):
        if self._cb:
            try:
                await self._cb(interaction, self.f_name.value, self.f_price.value,
                               self.f_temp.value, self.f_text.value)
            except Exception as e:
                print(f"[Modal4Shop error] {e}")
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "❌ An error occurred. Please try again.", ephemeral=True)
        else:
            await interaction.response.defer()


class Modal5(discord.ui.Modal):
    """5-field modal for shop item creation (name, price, stock, duration, text label).
    Image URL is set separately via the 'Set Image URL' button after creation.
    """
    def __init__(self, title: str, currency_label: str = "Gems", callback=None):
        super().__init__(title=str(title)[:45])
        self._cb = callback
        self.f_name  = discord.ui.TextInput(label="Item name (emoji welcome)", placeholder="🎮 Custom Role", max_length=80)
        self.f_price = discord.ui.TextInput(label=f"Price in {str(currency_label)[:30]}", placeholder="500")
        self.f_stock = discord.ui.TextInput(label="Stock quantity (0 = unlimited)", placeholder="0", required=False)
        self.f_temp  = discord.ui.TextInput(label="Duration in days (0 = permanent)", placeholder="0 or 30")
        self.f_text  = discord.ui.TextInput(label="Text field label (empty = none)", placeholder="Your game username", required=False)
        for f in [self.f_name, self.f_price, self.f_stock, self.f_temp, self.f_text]:
            self.add_item(f)

    async def on_submit(self, interaction: discord.Interaction):
        if self._cb:
            try:
                await self._cb(interaction, self.f_name.value, self.f_price.value,
                               self.f_stock.value, self.f_temp.value, self.f_text.value)
            except Exception as e:
                print(f"[Modal5 error] {e}")
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "❌ An error occurred. Please try again.", ephemeral=True)
        else:
            await interaction.response.defer()


async def _await_image_upload(bot: commands.Bot, interaction: discord.Interaction,
                               item_name: str) -> str | None:
    """
    Sends a prompt in the channel asking the user to upload an image file.
    Returns the Discord CDN URL of the attachment, or None if skipped/timed out.
    The user's message and the prompt are deleted afterward to keep the channel clean.
    """
    image_result: list[str | None] = [None]
    finished = asyncio.Event()

    class SkipView(discord.ui.View):
        @discord.ui.button(label="⏭️ Skip (no image)", style=discord.ButtonStyle.grey)
        async def skip(self, i: discord.Interaction, b: discord.ui.Button):
            finished.set()
            self.stop()
            await i.response.defer()

    view = SkipView(timeout=65)

    prompt = await interaction.channel.send(
        f"🖼️ **Image for « {item_name} »**\n"
        f"Upload an image from your device (jpg, png, gif…), "
        f"or click **Skip** to continue without one.\n"
        f"*You have 60 seconds. Only you can send.*",
        view=view,
    )

    def msg_check(m: discord.Message) -> bool:
        return (
            m.author.id == interaction.user.id
            and m.channel.id == interaction.channel.id
            and bool(m.attachments)
            and any(_is_image_attachment(a) for a in m.attachments)
        )

    async def listen():
        try:
            msg = await bot.wait_for("message", check=msg_check, timeout=60)
            img = next(
                (a for a in msg.attachments if _is_image_attachment(a)),
                None,
            )
            if img:
                image_result[0] = img.url
            finished.set()
            view.stop()
            try:
                await msg.delete()
            except Exception:
                pass
        except asyncio.TimeoutError:
            finished.set()
            view.stop()

    listener = asyncio.ensure_future(listen())
    await finished.wait()
    listener.cancel()

    try:
        await prompt.delete()
    except Exception:
        pass

    return image_result[0]

# ══════════════════════════════════════════════════════════════
#  CONFIRM VIEW
# ══════════════════════════════════════════════════════════════

class ConfirmView(discord.ui.View):
    def __init__(self, author_id: int, timeout: float = 30.0):
        super().__init__(timeout=timeout)
        self.value = None
        self.author_id = author_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ This isn't your button.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.green, emoji="✅")
    async def confirm(self, interaction: discord.Interaction, btn: discord.ui.Button):
        self.value = True; self.stop(); await interaction.response.defer()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red, emoji="❌")
    async def cancel(self, interaction: discord.Interaction, btn: discord.ui.Button):
        self.value = False; self.stop(); await interaction.response.defer()

# ══════════════════════════════════════════════════════════════
#  /config — MAIN MENU
# ══════════════════════════════════════════════════════════════

def config_overview_embed(guild: discord.Guild, config: dict) -> discord.Embed:
    """Lightweight overview shown when /config is first opened."""
    e = discord.Embed(title=f"⚙️ Config — {guild.name}", color=C_MAIN)
    issues = []
    if not config.get("youtube_channel_id"):      issues.append("YouTube channel")
    if not config.get("share_channel_id"):        issues.append("Share channel")
    if not config.get("notification_channel_id"): issues.append("Notification channel")
    if not config.get("commands_channel_id"):     issues.append("Commands channel")
    if not config.get("manager_role_id"):         issues.append("Meeple Owner role")
    if issues:
        e.add_field(name="⚠️ Incomplete setup", value="\n".join(f"• {i}" for i in issues), inline=False)
    else:
        e.add_field(name="✅ All essential settings configured", value="\u200b", inline=False)
    e.add_field(name="📹 Video / Reaction",     value=f"**{cur(config, config.get('reaction_xp', 50))}**", inline=True)
    e.add_field(name="📨 Invite",              value=f"**{cur(config, config.get('invite_xp', 25))}**",   inline=True)
    e.add_field(name="🔥 Streak",              value="Enabled" if config.get("streak_enabled", 1) else "Disabled", inline=True)
    e.set_footer(text="Select a category below to edit settings")
    return e

def config_status_embed(guild: discord.Guild, config: dict) -> discord.Embed:
    e = E(f"⚙️ Configuration — {guild.name}", color=C_MAIN)
    # ── Channels & roles ──────────────────────────────────────────
    e.add_field(name="📺 YouTube",            value=f"`{config.get('youtube_channel_id') or 'Not set'}`", inline=True)
    e.add_field(name="🔗 Share Channel",      value=_ch(config.get("share_channel_id")),              inline=True)
    e.add_field(name="🔔 Notifications",      value=_ch(config.get("notification_channel_id")),       inline=True)
    e.add_field(name="💬 Commands Channel",   value=_ch(config.get("commands_channel_id")),           inline=True)
    e.add_field(name="🛡️ Admin Channel",     value=_ch(config.get("admin_channel_id")),              inline=True)
    e.add_field(name="👥 Meeple Owner Role",    value=_role(config.get("manager_role_id")),             inline=True)
    # ── Features ─────────────────────────────────────────────────
    e.add_field(name="✅ Reaction Emoji",     value=config.get("reaction_emoji", "✅"),               inline=True)
    e.add_field(name="🔥 Streak",             value=_bool(config.get("streak_enabled", 1)),           inline=True)
    e.add_field(name="🎉 Boost Quest",        value=_bool(config.get("boost_quest_enabled", 1)),      inline=True)
    # ── DMs & Welcome ─────────────────────────────────────────────
    e.add_field(name="📩 Welcome DM",         value=_bool(config.get("welcome_dm_enabled", 0)),       inline=True)
    e.add_field(name="👋 Server Welcome",     value=_bool(config.get("server_welcome_enabled", 0)),   inline=True)
    e.add_field(name="⚡ Streak Reminder",    value=_bool(config.get("streak_reminder_enabled", 0)),  inline=True)
    dm_role   = _role(config.get("welcome_dm_role_id"))   or "`All members`"
    on_role   = _role(config.get("welcome_dm_on_role_id"))or "`Not set`"
    sw_ch     = _ch(config.get("server_welcome_channel_id")) or "`Not set`"
    info_ch   = _ch(config.get("info_channel_id"))        or "`Not set`"
    e.add_field(name="📌 DM Role Filter",     value=dm_role,  inline=True)
    e.add_field(name="🎭 DM on Role",         value=on_role,  inline=True)
    e.add_field(name="📢 Welcome Channel",    value=sw_ch,    inline=True)
    e.add_field(name="ℹ️ Info Channel",       value=info_ch,  inline=True)
    # ── Status ────────────────────────────────────────────────────
    issues = []
    if not config.get("youtube_channel_id"):      issues.append("YouTube channel")
    if not config.get("share_channel_id"):        issues.append("Share channel")
    if not config.get("notification_channel_id"): issues.append("Notification channel")
    if not config.get("commands_channel_id"):     issues.append("Commands channel")
    if not config.get("manager_role_id"):         issues.append("Meeple Owner role")
    if issues:
        e.add_field(name="⚠️ Not configured", value="\n".join(f"• {i}" for i in issues), inline=False)
    else:
        e.add_field(name="✅ Status", value="All essential settings configured.", inline=False)
    e.set_footer(text="Select a category below to edit settings")
    return e

def make_info_embed(guild: discord.Guild, config: dict) -> discord.Embed:
    """Dynamic info embed shown in the info channel — values reflect live config."""
    share_ch = config.get("share_channel_id")
    cmd_ch   = config.get("commands_channel_id")
    share_xp = config.get("share_xp", 100)
    react_xp = config.get("reaction_xp", 50)
    inv_xp   = config.get("invite_xp", 25)
    boost_xp = config.get("boost_quest_xp", 100)
    streak_on = config.get("streak_enabled", 1)
    streak_bonus = config.get("streak_xp_bonus", 2)
    streak_cap   = config.get("streak_xp_cap", 30)
    q_stone  = config.get("quest_xp_stone", 50)
    q_diamond= config.get("quest_xp_diamond", 750)

    shop_ch  = config.get("shop_channel_id")
    quest_ch = config.get("quests_channel_id")

    ch_share = f"<#{share_ch}>" if share_ch else "#share-channel"
    ch_cmd   = f"<#{cmd_ch}>"   if cmd_ch   else "#commands-channel"
    ch_shop  = f"<#{shop_ch}>"  if shop_ch  else ch_cmd
    ch_quest = f"<#{quest_ch}>" if quest_ch else ch_cmd

    config = db_get_config(guild.id)
    c_name  = config.get("currency_name")  or "Gems"
    c_emoji = config.get("currency_emoji") or "💎"
    e = E(f"⚡ How to Earn {c_emoji} {c_name}", color=C_GOLD)
    e.set_author(name=guild.name, icon_url=guild.icon.url if guild.icon else None)

    e.add_field(
        name="🎬 Share a Video",
        value=f"Post the link + a screenshot in {ch_share} within the time window.\n**+{cur(config, share_xp)}** per video"
              + (f" — consecutive shares build a 🔥 **Streak** (+{streak_bonus}/level, up to +{streak_cap})" if streak_on else ""),
        inline=False
    )
    e.add_field(
        name="✅ Reaction Bonus",
        value=f"A Meeple Owner reacts to your message → **+{cur(config, react_xp)}**",
        inline=True
    )
    e.add_field(
        name="📨 Invite a Friend",
        value=f"Someone joins through your link → **+{cur(config, inv_xp)}**",
        inline=True
    )
    e.add_field(
        name="🚀 Server Boost",
        value=f"Boost the server → **+{cur(config, boost_xp)}** (repeatable)",
        inline=True
    )
    e.add_field(
        name="📅 Monthly Quests",
        value=f"Complete quests each month to earn between **{cur(config, q_stone)}** (Stone) and **{cur(config, q_diamond)}** (Diamond).\nUse `/quests` in {ch_quest} to check your progress.",
        inline=False
    )
    if config.get("daily_quest_enabled"):
        daily_xp = config.get("daily_quest_xp", 50)
        e.add_field(
            name="🗓️ Daily Quests",
            value=f"3 new quests every day — complete them to earn **+{cur(config, daily_xp)}** each.\nUse `/quests` to see today's list.",
            inline=False
        )
    e.add_field(
        name=f"🛒 What can you do with {c_emoji} {c_name}?",
        value=f"Spend your {c_name} in `/shop` (use it in {ch_shop}) to unlock exclusive rewards — pins, skins, friend requests, and more.",
        inline=False
    )
    e.add_field(
        name=f"📊 Check your {c_name}",
        value=f"Use `/gems`, `/leaderboard`, `/inventory`, `/achievements` in {ch_cmd}.",
        inline=False
    )
    e.set_footer(text=f"Updated • {datetime.utcnow().strftime('%d %b %Y %H:%M')} UTC")
    return e


async def post_or_update_info_embed(bot: commands.Bot, guild: discord.Guild, config: dict):
    """Post the info embed in the info channel, or edit the existing one."""
    ch_id  = config.get("info_channel_id")
    msg_id = config.get("info_message_id")
    if not ch_id:
        return False, "No info channel configured."
    ch = bot.get_channel(ch_id)
    if not ch:
        return False, "Info channel not found — bot may lack access."
    embed = make_info_embed(guild, config)
    if msg_id:
        try:
            msg = await ch.fetch_message(msg_id)
            await msg.edit(embed=embed)
            return True, "Info message updated ✅"
        except discord.NotFound:
            pass  # Message deleted — post a new one
    try:
        msg = await ch.send(embed=embed)
        db_set_config(guild.id, info_message_id=msg.id)
        return True, "Info message posted ✅"
    except Exception as ex:
        return False, f"Error: {ex}"


def member_has_server_tag(member: discord.Member) -> bool:
    """Return True if the member has the server's clan/guild tag enabled (discord.py 2.4+).
    Checks both MemberFlags.guild_tag_and_badge (2.4+) and the legacy guild_tag attribute."""
    try:
        flags = getattr(member, "flags", None)
        if flags is not None and hasattr(flags, "guild_tag_and_badge"):
            return bool(flags.guild_tag_and_badge)
    except Exception:
        pass
    return getattr(member, "guild_tag", None) is not None


async def _reward_server_tag(guild: discord.Guild, member: discord.Member, config: dict):
    """Award gems when a member enables the server tag for the first time."""
    guild_id = guild.id
    conn = get_db()
    already = conn.execute(
        "SELECT 1 FROM server_tag_rewards WHERE guild_id=? AND user_id=?",
        (guild_id, member.id)
    ).fetchone()
    if already:
        conn.close()
        return
    conn.execute(
        "INSERT OR IGNORE INTO server_tag_rewards (guild_id, user_id) VALUES (?,?)",
        (guild_id, member.id)
    )
    conn.commit()
    conn.close()

    xp     = config.get("server_tag_xp", 100)
    new_xp = db_add_xp(guild_id, member.id, xp)
    e = E("🏷️ Server Tag!", color=C_GOLD)
    e.description = (
        f"**{member.display_name}** is now sporting the server tag!\n"
        f"Reward: **+{cur(config, xp)}**  |  Balance: **{cur(config, new_xp)}**"
    )
    e.set_thumbnail(url=member.display_avatar.url if member.display_avatar else None)
    # Notify in the notification channel so the member sees they earned gems
    await notify_xp(bot, guild_id,
                    content=f"🏷️ {member.mention} just enabled the server tag and earned **+{cur(config, xp)}**!",
                    embed=e)
    await bot_log(bot, guild_id, "🏷️ Server Tag Reward",
                  f"**Member:** {member.mention} ({member.display_name})\n"
                  f"**Reward:** +{cur(config, xp)}\n"
                  f"**Balance:** {cur(config, new_xp)}", C_GOLD)


async def send_welcome_dm(member: discord.Member, config: dict, trigger: str = "join") -> bool:
    """Send the welcome DM to a member.  Returns True if the DM was sent successfully.

    `trigger` is a short label used in the log ('join', 'role', 'bulk').
    """
    e = discord.Embed(
        title=f"👋 Welcome to **{member.guild.name}**!",
        color=C_MAIN
    )
    e.description = (
        f"Welcome, **{member.display_name}**! 🎉\n\n"
        "This server rewards members for supporting the community.\n"
        "Share the current video, complete quests, earn Gems, and spend them in `/shop`.\n\n"
        "📖 Start with `/tutorial` to learn how to earn and use Gems.\n"
        "If you need help, ping a member with the **Gems Owner** role.\n\n"
        "Have fun and good luck! 🚀"
    )
    e.set_footer(text=f"{member.guild.name} • Rewards System")
    dm_sent = False
    dm_error = ""
    try:
        # Small delay; join needs 3 s for Discord to fully register the new member.
        await asyncio.sleep(3 if trigger == "join" else 0.5)
        await member.send(embed=e)
        dm_sent = True
    except discord.Forbidden as ex:
        # HTTP 403 / code 50007 or 20026:
        #   The member has "Allow direct messages from server members" OFF in
        #   Server Settings → Privacy for THIS server (separate from global DM settings),
        #   OR they have the bot blocked.
        # Fix: right-click server → Privacy Settings → enable Allow direct messages.
        dm_error = (
            f"Forbidden (HTTP 403, code {ex.code}) — DMs are disabled.\n"
            f"Fix: member must right-click the server → Privacy Settings → "
            f"enable **Allow direct messages from server members**."
        )
    except discord.HTTPException as ex:
        dm_error = f"HTTPException (status {ex.status}, code {ex.code}): {ex.text}"
    except Exception as ex:
        dm_error = str(ex)
    # Log the DM attempt
    await bot_log(
        bot, member.guild.id,
        "📩 Welcome DM Sent" if dm_sent else "📩 Welcome DM Failed",
        f"**Member:** {member.mention} ({member.display_name})\n"
        f"**Trigger:** {trigger}\n"
        f"**DM sent:** {'✅ Yes' if dm_sent else f'❌ No — {dm_error}'}",
        C_INFO if dm_sent else C_ERROR
    )
    return dm_sent


async def notify_balance_change_dm(bot: commands.Bot, guild_id: int, actor,
                                   target_uid: int, before: int, after: int,
                                   action: str, amount: Optional[int] = None):
    """DM the configured audit recipient after a manual /admin balance change."""
    config = db_get_config(guild_id)
    recipient_id = config.get("balance_change_dm_user_id")
    if not recipient_id:
        return
    recipient = bot.get_user(int(recipient_id))
    if recipient is None:
        try:
            recipient = await bot.fetch_user(int(recipient_id))
        except Exception as ex:
            await bot_log(
                bot, guild_id, "⚠️ Balance Change DM Failed",
                f"Could not find configured recipient <@{recipient_id}>.\n**Error:** {ex}",
                C_ERROR,
            )
            return
    c_name = config.get("currency_name") or "Gems"
    change_line = f"**Change:** `{amount:+d}` {c_name}\n" if amount is not None else ""
    embed = discord.Embed(title="💰 Manual Balance Change", color=C_GOLD)
    embed.description = (
        f"**Server:** {bot.get_guild(guild_id).name if bot.get_guild(guild_id) else guild_id}\n"
        f"**Action:** {action}\n"
        f"**Changed by:** {getattr(actor, 'mention', str(actor))}\n"
        f"**Member:** <@{target_uid}>\n"
        f"{change_line}"
        f"**Balance:** {cur(config, before)} → **{cur(config, after)}**"
    )
    embed.set_footer(text="Sent because this recipient is configured in /config → DMs & Welcome")
    try:
        await recipient.send(embed=embed)
        await bot_log(
            bot, guild_id, "📩 Balance Change DM Sent",
            f"**Recipient:** <@{recipient_id}>\n"
            f"**Changed by:** {getattr(actor, 'mention', str(actor))}\n"
            f"**Member:** <@{target_uid}>\n"
            f"**Balance:** {before} → {after}",
            C_INFO,
        )
    except Exception as ex:
        await bot_log(
            bot, guild_id, "⚠️ Balance Change DM Failed",
            f"**Recipient:** <@{recipient_id}>\n**Error:** {ex}",
            C_ERROR,
        )


class PagedTutorialView(discord.ui.View):
    """Small, reusable step-by-step tutorial with safe, author-only controls."""

    def __init__(self, guild: discord.Guild, author_id: int, pages: list,
                 title: str, back_factory):
        super().__init__(timeout=600)
        self.guild = guild
        self.author_id = author_id
        self.pages = pages
        self.tutorial_title = title
        self.back_factory = back_factory
        self.page_index = 0
        self._sync_buttons()
        self.back_to_menu.disabled = back_factory is None

    def _sync_buttons(self):
        self.previous_page.disabled = self.page_index == 0
        self.next_page.disabled = self.page_index >= len(self.pages) - 1

    def build_embed(self) -> discord.Embed:
        page = self.pages[self.page_index]
        e = E(page["title"], color=page.get("color", C_INFO))
        e.description = page["description"]
        for field in page.get("fields", []):
            e.add_field(name=field[0], value=field[1], inline=field[2] if len(field) > 2 else False)
        e.set_footer(text=f"{self.tutorial_title} • Step {self.page_index + 1}/{len(self.pages)}")
        return e

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ This tutorial belongs to someone else.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="◀ Previous", style=discord.ButtonStyle.grey, row=0)
    async def previous_page(self, interaction: discord.Interaction, button):
        self.page_index = max(0, self.page_index - 1)
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.blurple, row=0)
    async def next_page(self, interaction: discord.Interaction, button):
        self.page_index = min(len(self.pages) - 1, self.page_index + 1)
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="↩ Back to menu", style=discord.ButtonStyle.green, row=1)
    async def back_to_menu(self, interaction: discord.Interaction, button):
        if self.back_factory is None:
            await interaction.response.edit_message(content="✅ Tutorial closed.", embed=None, view=None)
            return
        menu = self.back_factory(self.guild, self.author_id)
        if isinstance(menu, ConfigMainMenu):
            embed = config_status_embed(self.guild, db_get_config(self.guild.id))
        else:
            embed = admin_main_embed(self.guild)
        await interaction.response.edit_message(embed=embed, view=menu)

    @discord.ui.button(label="✖ Close", style=discord.ButtonStyle.red, row=1)
    async def close_tutorial(self, interaction: discord.Interaction, button):
        await interaction.response.edit_message(content="✅ Tutorial closed.", embed=None, view=None)


def member_tutorial_pages(guild: discord.Guild) -> list:
    """Simple member-facing tutorial shown by /tutorial."""
    config = db_get_config(guild.id)
    c_name = config.get("currency_name") or "Gems"
    c_emoji = config.get("currency_emoji") or "💎"
    share_ch = config.get("share_channel_id")
    shop_ch = config.get("shop_channel_id")
    quests_ch = config.get("quests_channel_id")
    commands_ch = config.get("commands_channel_id")
    share_text = f"<#{share_ch}>" if share_ch else "the share channel"
    shop_text = f"<#{shop_ch}>" if shop_ch else "the shop channel"
    quests_text = f"<#{quests_ch}>" if quests_ch else "the quests channel"
    commands_text = f"<#{commands_ch}>" if commands_ch else "the commands channel"
    return [
        {
            "title": "👋 Welcome to the rewards system",
            "description": (
                "This short guide explains how to earn and use your rewards. "
                "Press **Next ▶** to continue."
            ),
            "fields": [
                ("Your currency", f"Your server currency is **{c_emoji} {c_name}**.", False),
                ("Start here", "Use `/gems` to see your balance and rank. Use `/tutorial` any time to reopen this guide.", False),
            ],
        },
        {
            "title": "1️⃣ Earn rewards",
            "description": "There are several ways to earn Gems and support the community.",
            "fields": [
                ("🎬 Share the current video", f"Use `/video`, then share the video link and proof in {share_text}.", False),
                ("✅ Reaction bonus", "A Gems Owner may react to an eligible message to give you a Gems bonus.", False),
                ("📨 Invite members", "Invite someone to the server to earn the configured invite reward.", False),
                ("🚀 Boost the server", "Server boosts may grant a repeatable reward when this feature is enabled.", False),
            ],
        },
        {
            "title": "2️⃣ Share a video correctly",
            "description": "Sharing the current video is the main way to build your reward streak.",
            "fields": [
                ("Step 1", "Run `/video` to see which video is currently active.", False),
                ("Step 2", f"Post the video link and a screenshot of your comment in {share_text}.", False),
                ("Step 3", "Wait for validation. Do not repost the same video unless staff asks you to.", False),
                ("🔥 Streak", "Validated consecutive shares build your streak. A Gems reaction bonus never changes your streak.", False),
            ],
        },
        {
            "title": "3️⃣ Complete daily quests",
            "description": "Use daily quests for extra rewards and check your progress regularly.",
            "fields": [
                ("📅 Check progress", f"Use `/quests` in {quests_text} to see your active quests.", False),
                ("👑 Gems bonus quest", "When a quest asks for a Gems bonus, **ping the Gems Owner role** and ask for the bonus. You must ping the role.", False),
                ("Daily reset", "Daily quests refresh automatically. Complete them before the daily reset when possible.", False),
            ],
        },
        {
            "title": "4️⃣ Spend your Gems",
            "description": "The shop contains rewards configured by the server team.",
            "fields": [
                ("🛒 Browse", f"Use `/shop` in {shop_text} to see available items.", False),
                ("🛍️ Buy", "Select an item, confirm the purchase, and provide any requested information.", False),
                ("🎒 Check your items", "Use `/inventory` to see your active and previously purchased rewards.", False),
                ("🎁 Gift", "If enabled, use `/give` to send Gems to another member within the server limits.", False),
            ],
        },
        {
            "title": "5️⃣ Useful commands",
            "description": f"Most commands should be used in {commands_text}.",
            "fields": [
                ("`/gems`", f"View your {c_name} balance and rank.", True),
                ("`/leaderboard`", "See the server ranking.", True),
                ("`/video`", "See the current video to share.", True),
                ("`/quests`", "Track daily and monthly quests.", True),
                ("`/achievements`", "View your achievement progress.", True),
                ("`/shop` · `/inventory`", "Buy rewards and view your items.", True),
            ],
        },
        {
            "title": "✅ You are ready",
            "description": (
                "Start with `/gems`, check `/video`, and complete your first quest. "
                "Good luck and have fun!"
            ),
            "fields": [
                ("Need help?", "Ping a member with the **Gems Owner** role and clearly explain what you need.", False),
                ("Remember", "Be respectful, share valid proof, and never spam the share channel.", False),
                ("Open this guide again", "Use `/tutorial` whenever you need a refresher.", False),
            ],
        },
    ]


class MemberTutorialView(PagedTutorialView):
    def __init__(self, guild: discord.Guild, author_id: int):
        super().__init__(guild, author_id, member_tutorial_pages(guild), "Member Tutorial", None)


def config_tutorial_pages(guild: discord.Guild) -> list:
    config = db_get_config(guild.id)
    c_name = config.get("currency_name") or "Gems"
    c_emoji = config.get("currency_emoji") or "💎"
    return [
        {
            "title": "📖 Welcome — start here",
            "description": (
                "This guided setup takes you through the bot in the right order. "
                "Press **Next** after each step. You can come back to this tutorial any time."
            ),
            "fields": [
                ("Recommended order", "YouTube → Channels → Roles → Currency → DMs → Shop → Quests", False),
                ("Important", "Every setting is saved immediately. If a button asks for a mention or ID, paste the Discord mention when possible.", False),
            ],
        },
        {
            "title": "1️⃣ Connect YouTube",
            "description": (
                "Open **📺 YouTube** and use **Set YouTube Channel**. Paste the channel handle "
                "such as `@YourChannel`, or the channel ID. The bot will watch for new videos "
                "and create the share window automatically."
            ),
            "fields": [
                ("Check", "Use **Test Feed** if available and confirm that the channel is found.", False),
                ("Why first?", "The share channel and streak system need an active video.", False),
            ],
        },
        {
            "title": "2️⃣ Choose your channels",
            "description": "Open **💬 Channels** and route each feature to the channel where members should see it.",
            "fields": [
                ("Member channels", "Share Channel = video links and screenshots\nCommands Channel = `/gems`, `/shop`, `/quests`", False),
                ("Staff channels", "Notification/Admin Channel = rewards and staff notices\nLog Channel = audit history\nBackup Channel = database backups", False),
                ("Optional", "Set the ticket category and event channel if you use shop tickets or events.", False),
            ],
        },
        {
            "title": "3️⃣ Set the right roles",
            "description": "Open **👥 Roles** before giving the bot to your team.",
            "fields": [
                ("Meeple Owner role", "Controls `/admin`, `/config`, manual Gems awards, and purchase handling.", False),
                ("Share/Ping roles", "Configure the share ping role and the Gems Owner role used by the daily Gems bonus quest.", False),
                ("Safety", "Only trusted staff should receive the Meeple Owner role.", False),
            ],
        },
        {
            "title": f"4️⃣ Configure {c_emoji} {c_name}",
            "description": (
                f"Open **💎 Currency** to change the name and emoji. Current value: **{c_emoji} {c_name}**."
            ),
            "fields": [
                ("Rewards", "Set reaction, share, invite, streak, quest, and boost rewards in their matching menus.", False),
                ("Consistency", "The chosen currency name and emoji are used in balances, shop prices, DMs, and logs.", False),
            ],
        },
        {
            "title": "5️⃣ Configure DMs and welcome messages",
            "description": "Open **📨 DMs & Welcome** and decide which messages your members should receive.",
            "fields": [
                ("New members", "Enable Welcome DM for a short introduction. The DM points members to the info channel and tutorial.", False),
                ("Daily quests", "Toggle Daily Quest DM if you want members to receive their quests privately.", False),
                ("Shop items", "New Shop Item DM is delayed by 5 minutes by default so you can finish the image, keys, and options first.", False),
                ("Balance audit", "Use **Balance Change DM Recipient** to set the member who receives a DM whenever a Gems Owner changes a balance from `/admin`.", False),
            ],
        },
        {
            "title": "6️⃣ Build and test the shop",
            "description": "Open **🛒 Shop**. Add the item first, then configure its image, keys, price, stock, duration, and approval options.",
            "fields": [
                ("Before launch", "Use the preview/test controls. Main shop images use a full embed image so they are not cropped.", False),
                ("After launch", "Purchases create tickets and notify the configured purchase DM role.", False),
            ],
        },
        {
            "title": "7️⃣ Daily quests and community pings",
            "description": (
                "Use **📋 Daily Quests** to select the member role, reward, chat channel, and the **Gems Owner role**."
            ),
            "fields": [
                ("Gems bonus quest", "Members must **ping the Gems Owner role** and ask for their Gems bonus. Any member with that role can award it.", False),
                ("Revive and drops", "Use **🌐 Community** to set separate roles, then use the manual message buttons whenever you want to call them.", False),
            ],
        },
        {
            "title": "✅ Final checklist",
            "description": "Your setup is ready when these tests work:",
            "fields": [
                ("Test as a member", "Run `/gems`, `/quests`, `/shop`, and share one valid video link with its screenshot.", False),
                ("Test as staff", "Open `/admin`, make a small balance change, confirm the log and the configured personal DM.", False),
                ("Need help?", "Reopen `/config` and this tutorial. If a member cannot use a command, check their role and the command channel.", False),
            ],
        },
    ]


class ConfigTutorialView(PagedTutorialView):
    def __init__(self, guild: discord.Guild, author_id: int):
        super().__init__(guild, author_id, config_tutorial_pages(guild), "Config Tutorial", ConfigMainMenu)


def admin_tutorial_pages(guild: discord.Guild) -> list:
    config = db_get_config(guild.id)
    c_name = config.get("currency_name") or "Gems"
    return [
        {
            "title": "🛠️ Admin guide — welcome",
            "description": "This guide explains the safe day-to-day actions available in `/admin`. Press **Next** to continue.",
            "fields": [
                ("Rule 1", "Use the smallest action that solves the problem. Every manual balance action is logged.", False),
                ("Rule 2", "Never share the admin panel with untrusted members. Access is controlled by the Meeple Owner role or Discord Administrator permission.", False),
            ],
        },
        {
            "title": f"1️⃣ Manage {c_name}",
            "description": f"Open **👤 Manage Balance** when you need to correct or award a member's {c_name}.",
            "fields": [
                ("Add / Remove", "Enter a positive number to award, or a negative number to remove. The result shows the new total.", False),
                ("Set Exact", "Use this when you know the final balance that the member must have.", False),
                ("Reset", "Use only when necessary. It asks for confirmation before setting the balance to zero.", False),
            ],
        },
        {
            "title": "2️⃣ Balance audit and notifications",
            "description": "Each manual balance change creates a log entry with the actor, member, amount, and resulting balance.",
            "fields": [
                ("Personal DM", "If a Balance Change DM Recipient is configured in `/config` → DMs & Welcome, that member receives the same audit summary privately.", False),
                ("Recommended test", "Start with a small amount, verify the public log and DM, then make the real correction.", False),
            ],
        },
        {
            "title": "3️⃣ Streaks and quests",
            "description": "Use the streak and quest controls only for corrections or support cases.",
            "fields": [
                ("Streak", "Reset or modify a streak when a valid support decision requires it. A Gems reaction never changes a streak.", False),
                ("Quests", "Reroll a member's quests only when their assignment is broken or needs staff correction.", False),
            ],
        },
        {
            "title": "4️⃣ Pings, backups, and stats",
            "description": "The remaining admin buttons are operational tools.",
            "fields": [
                ("Trigger Ping", "Manually start a video share window with a valid YouTube URL.", False),
                ("Run Backup", "Send an immediate database backup to the configured backup channel.", False),
                ("Server Stats", "Review members, total rewards, shop items, shares, and completed quests.", False),
            ],
        },
        {
            "title": "5️⃣ Community workflow",
            "description": "Revive and drops pings are now manual and easy to control from `/config` → Community.",
            "fields": [
                ("Revive", "Set the Revive role, then press **Send Revive Message** whenever you want to call those members.", False),
                ("Drops", "Set the Drops role, then press **Send Drops Message** when you post skin/item links in general.", False),
                ("Buttons", "Members can opt in or out from the message buttons without changing their Gems or streak.", False),
            ],
        },
        {
            "title": "✅ Finish safely",
            "description": "When you are done, return to the main panel and leave the rest of the automation running.",
            "fields": [
                ("If something fails", "Check the configured channel, role, and bot permissions first. Then check the log channel for the exact action.", False),
                ("Good habit", "Use `/config` for setup and `/admin` for operations. Keep the two jobs separate.", False),
            ],
        },
    ]


class AdminTutorialView(PagedTutorialView):
    def __init__(self, guild: discord.Guild, author_id: int):
        super().__init__(guild, author_id, admin_tutorial_pages(guild), "Admin Guide", AdminMainMenu)


class ConfigMainMenu(discord.ui.View):
    def __init__(self, guild: discord.Guild, author_id: int):
        super().__init__(timeout=1800)
        self.guild = guild
        self.author_id = author_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ This panel belongs to someone else.", ephemeral=True)
            return False
        return True

    async def _go(self, interaction, embed, view):
        try:
            await interaction.response.edit_message(embed=embed, view=view)
        except Exception:
            traceback.print_exc()
            message = (
                "❌ This settings page could not be opened. "
                "The error was logged; please try again."
            )
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(message, ephemeral=True)
                else:
                    await interaction.followup.send(message, ephemeral=True)
            except Exception:
                pass

    async def on_error(self, interaction, error, item):
        traceback.print_exception(type(error), error, error.__traceback__)
        message = (
            "❌ This settings action failed before it could finish. "
            "Please try again; the error was logged."
        )
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(message, ephemeral=True)
            else:
                await interaction.followup.send(message, ephemeral=True)
        except Exception:
            pass

    # ── Row 0 · Setup ─────────────────────────────────────────
    @discord.ui.button(label="📺 YouTube",      style=discord.ButtonStyle.blurple, row=0)
    async def cat_yt(self, i, b):
        sub = ConfigYouTubeMenu(self.guild, self.author_id)
        await self._go(i, sub.build_embed(db_get_config(self.guild.id)), sub)

    @discord.ui.button(label="💬 Channels",     style=discord.ButtonStyle.blurple, row=0)
    async def cat_ch(self, i, b):
        sub = ConfigChannelsMenu(self.guild, self.author_id)
        await self._go(i, sub.build_embed(db_get_config(self.guild.id)), sub)

    @discord.ui.button(label="👥 Roles",        style=discord.ButtonStyle.blurple, row=0)
    async def cat_perms(self, i, b):
        sub = ConfigPermissionsMenu(self.guild, self.author_id)
        await self._go(i, sub.build_embed(db_get_config(self.guild.id)), sub)

    @discord.ui.button(label="💎 Currency",     style=discord.ButtonStyle.blurple, row=0)
    async def cat_currency(self, i, b):
        sub = ConfigCurrencyMenu(self.guild, self.author_id)
        await self._go(i, sub.build_embed(db_get_config(self.guild.id)), sub)

    @discord.ui.button(label="📖 Tutorial",     style=discord.ButtonStyle.grey,    row=0)
    async def cat_tutorial(self, i: discord.Interaction, b):
        view = ConfigTutorialView(self.guild, self.author_id)
        await i.response.edit_message(embed=view.build_embed(), view=view)

    # ── Row 1 · Rewards ───────────────────────────────────────
    @discord.ui.button(label="💰 Rewards",      style=discord.ButtonStyle.blurple, row=1)
    async def cat_xp(self, i, b):
        sub = ConfigXPMenu(self.guild, self.author_id)
        await self._go(i, sub.build_embed(db_get_config(self.guild.id)), sub)

    @discord.ui.button(label="🔥 Streak",       style=discord.ButtonStyle.blurple, row=1)
    async def cat_streak(self, i, b):
        sub = ConfigStreakMenu(self.guild, self.author_id)
        await self._go(i, sub.build_embed(db_get_config(self.guild.id)), sub)

    @discord.ui.button(label="🎁 Gift Gems",    style=discord.ButtonStyle.blurple, row=1)
    async def cat_gift(self, i, b):
        sub = ConfigGiftMenu(self.guild, self.author_id)
        await self._go(i, sub.build_embed(db_get_config(self.guild.id)), sub)

    @discord.ui.button(label="🛒 Shop",         style=discord.ButtonStyle.blurple, row=1)
    async def cat_shop(self, i, b):
        sub = ConfigShopMenu(self.guild, self.author_id)
        await self._go(i, sub.build_embed(db_get_config(self.guild.id)), sub)

    @discord.ui.button(label="👁️ Messages",     style=discord.ButtonStyle.blurple, row=1)
    async def cat_messages(self, i, b):
        sub = ConfigMessageVisibilityMenu(self.guild, self.author_id)
        await self._go(i, sub.build_embed(db_get_config(self.guild.id)), sub)

    # ── Row 2 · Community ─────────────────────────────────────
    @discord.ui.button(label="📅 Quests",       style=discord.ButtonStyle.blurple, row=2)
    async def cat_quests(self, i, b):
        sub = ConfigQuestsMenu(self.guild, self.author_id)
        await self._go(i, sub.build_embed(db_get_config(self.guild.id)), sub)

    @discord.ui.button(label="🏆 Achievements", style=discord.ButtonStyle.blurple, row=2)
    async def cat_ach(self, i, b):
        sub = ConfigAchievementsMenu(self.guild, self.author_id)
        await self._go(i, sub.build_embed(db_get_config(self.guild.id)), sub)

    @discord.ui.button(label="🎉 Events",       style=discord.ButtonStyle.blurple, row=2)
    async def cat_events(self, i, b):
        sub = ConfigEventsMenu(self.guild, self.author_id)
        await self._go(i, sub.build_embed(db_get_config(self.guild.id)), sub)

    @discord.ui.button(label="📨 DMs & Welcome",style=discord.ButtonStyle.blurple, row=2)
    async def cat_dms(self, i, b):
        # Send the complete submenu as the component response. Avoid a second
        # edit request on an ephemeral response: Discord clients and webhook
        # tokens can reject that follow-up edit even though the first response
        # succeeded.
        try:
            sub = ConfigDMsMenu(self.guild, self.author_id)
            embed = sub.build_embed(db_get_config(self.guild.id))
            await i.response.send_message(embed=embed, view=sub, ephemeral=True)
        except Exception as ex:
            traceback.print_exception(type(ex), ex, ex.__traceback__)
            try:
                if not i.response.is_done():
                    await i.response.send_message(
                        "❌ DMs & Welcome could not be opened. "
                        "The error was logged; please try again.",
                        ephemeral=True,
                    )
                else:
                    await i.followup.send(
                        "❌ DMs & Welcome could not be opened. Please try again.",
                        ephemeral=True,
                    )
            except Exception:
                pass

    @discord.ui.button(label="🔔 Community",    style=discord.ButtonStyle.blurple, row=2)
    async def cat_community(self, i, b):
        sub = ConfigCommunityMenu(self.guild, self.author_id)
        await self._go(i, sub.build_embed(db_get_config(self.guild.id)), sub)

# ══════════════════════════════════════════════════════════════
#  SUBMENU BASE
# ══════════════════════════════════════════════════════════════

class _SubMenu(discord.ui.View):
    def __init__(self, guild: discord.Guild, author_id: int):
        super().__init__(timeout=1800)
        self.guild = guild
        self.author_id = author_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ This panel belongs to someone else.", ephemeral=True)
            return False
        return True

    def build_embed(self, config: dict) -> discord.Embed:
        raise NotImplementedError

    async def _back(self, interaction: discord.Interaction):
        config = db_get_config(self.guild.id)
        main = ConfigMainMenu(self.guild, self.author_id)
        await interaction.response.edit_message(embed=config_status_embed(self.guild, config), view=main)

    async def _refresh(self, interaction: discord.Interaction):
        config = db_get_config(self.guild.id)
        embed  = self.build_embed(config)
        # Try editing via the interaction webhook first; fall back to direct
        # message edit (needed when the interaction responded with a modal,
        # where edit_original_response returns 404 on the modal token).
        try:
            await interaction.edit_original_response(embed=embed, view=self)
        except Exception:
            try:
                if getattr(interaction, "message", None):
                    await interaction.message.edit(embed=embed, view=self)
            except Exception:
                pass

    async def on_error(self, interaction, error, item):
        traceback.print_exception(type(error), error, error.__traceback__)
        message = (
            "❌ This settings action failed before it could finish. "
            "Please try again; the error was logged."
        )
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(message, ephemeral=True)
            else:
                await interaction.followup.send(message, ephemeral=True)
        except Exception:
            pass

    @discord.ui.button(label="← Back", style=discord.ButtonStyle.grey, row=4)
    async def btn_back(self, interaction: discord.Interaction, btn: discord.ui.Button):
        await self._back(interaction)

# ══════════════════════════════════════════════════════════════
#  MESSAGE VISIBILITY SUBMENU
# ══════════════════════════════════════════════════════════════

_MSG_TTL_LABELS = {
    "msg_ttl_share_reward":      ("✅ Share Reward",      "Message sent when a share is validated"),
    "msg_ttl_share_reject":      ("❌ Share Rejection",   "Message sent when a share is rejected"),
    "msg_ttl_reaction_bonus":    ("💎 Reaction Bonus",   "Message sent when a gems bonus is given"),
    "msg_ttl_reaction_cooldown": ("⏱️ React Cooldown",   "Cooldown warning when bonus is too soon"),
    "msg_ttl_block_msg":         ("🚫 Block Message",    "Message blocked notice (no reward)"),
    "msg_ttl_gems":              ("💰 /gems Response",   "Balance embed from /gems command"),
    "msg_ttl_shop":              ("🛒 /shop Response",   "Shop embed from /shop command"),
    "msg_ttl_leaderboard":       ("🏆 /leaderboard",     "Leaderboard from /leaderboard command"),
}

def _ttl_display(v) -> str:
    """Human-readable TTL value."""
    if not v or v == 0:
        return "Permanent"
    if v < 60:
        return f"{v}s"
    return f"{v // 60}min {v % 60}s" if v % 60 else f"{v // 60}min"

class _SetTTLModal(discord.ui.Modal):
    def __init__(self, guild, author_id, config_key: str, label: str):
        super().__init__(title=f"Set display time — {label}")
        self.guild      = guild
        self.author_id  = author_id
        self.config_key = config_key
        self.field = discord.ui.TextInput(
            label="Seconds (0 = permanent, e.g. 30, 60, 120)",
            placeholder="0",
            max_length=6,
        )
        self.add_item(self.field)

    async def on_submit(self, interaction: discord.Interaction):
        raw = self.field.value.strip()
        try:
            secs = max(0, int(raw))
        except ValueError:
            await interaction.response.send_message("❌ Enter a whole number of seconds (0 = permanent).", ephemeral=True)
            return
        db_set_config(self.guild.id, **{self.config_key: secs})
        config = db_get_config(self.guild.id)
        sub = ConfigMessageVisibilityMenu(self.guild, self.author_id)
        await interaction.response.edit_message(embed=sub.build_embed(config), view=sub)

class ConfigMessageVisibilityMenu(_SubMenu):
    def build_embed(self, config: dict) -> discord.Embed:
        e = E("👁️ Message Visibility", color=C_INFO)
        e.description = (
            "Control how long each bot message stays visible.\n"
            "**0 = permanent** — message stays forever.\n"
            "**N seconds** — message auto-deletes after N seconds.\n\u200b"
        )
        for key, (label, desc) in _MSG_TTL_LABELS.items():
            v = config.get(key, 0)
            e.add_field(name=label, value=f"{desc}\n**→ {_ttl_display(v)}**", inline=True)
        return e

    # ── Row 0 ──────────────────────────────────────────────────
    @discord.ui.button(label="✅ Share Reward",    style=discord.ButtonStyle.blurple, row=0)
    async def btn_share_reward(self, i, b):
        await i.response.send_modal(_SetTTLModal(self.guild, self.author_id, "msg_ttl_share_reward", "Share Reward"))

    @discord.ui.button(label="❌ Share Rejection", style=discord.ButtonStyle.blurple, row=0)
    async def btn_share_reject(self, i, b):
        await i.response.send_modal(_SetTTLModal(self.guild, self.author_id, "msg_ttl_share_reject", "Share Rejection"))

    @discord.ui.button(label="💎 Reaction Bonus",  style=discord.ButtonStyle.blurple, row=0)
    async def btn_reaction_bonus(self, i, b):
        await i.response.send_modal(_SetTTLModal(self.guild, self.author_id, "msg_ttl_reaction_bonus", "Reaction Bonus"))

    @discord.ui.button(label="⏱️ React Cooldown", style=discord.ButtonStyle.blurple, row=0)
    async def btn_react_cooldown(self, i, b):
        await i.response.send_modal(_SetTTLModal(self.guild, self.author_id, "msg_ttl_reaction_cooldown", "Reaction Cooldown"))

    @discord.ui.button(label="🚫 Block Message",   style=discord.ButtonStyle.blurple, row=0)
    async def btn_block_msg(self, i, b):
        await i.response.send_modal(_SetTTLModal(self.guild, self.author_id, "msg_ttl_block_msg", "Block Message"))

    # ── Row 1 ──────────────────────────────────────────────────
    @discord.ui.button(label="💰 /gems",           style=discord.ButtonStyle.green,  row=1)
    async def btn_gems(self, i, b):
        await i.response.send_modal(_SetTTLModal(self.guild, self.author_id, "msg_ttl_gems", "/gems"))

    @discord.ui.button(label="🛒 /shop",           style=discord.ButtonStyle.green,  row=1)
    async def btn_shop(self, i, b):
        await i.response.send_modal(_SetTTLModal(self.guild, self.author_id, "msg_ttl_shop", "/shop"))

    @discord.ui.button(label="🏆 /leaderboard",    style=discord.ButtonStyle.green,  row=1)
    async def btn_leaderboard(self, i, b):
        await i.response.send_modal(_SetTTLModal(self.guild, self.author_id, "msg_ttl_leaderboard", "/leaderboard"))

    # ── Reset all ──────────────────────────────────────────────
    @discord.ui.button(label="🔄 Reset All to Permanent", style=discord.ButtonStyle.red, row=2)
    async def btn_reset_all(self, i, b):
        db_set_config(self.guild.id,
            msg_ttl_share_reward=0, msg_ttl_share_reject=0, msg_ttl_reaction_bonus=0,
            msg_ttl_reaction_cooldown=0, msg_ttl_block_msg=0, msg_ttl_gems=0,
            msg_ttl_shop=0, msg_ttl_leaderboard=0)
        config = db_get_config(self.guild.id)
        await i.response.edit_message(embed=self.build_embed(config), view=self)

# ══════════════════════════════════════════════════════════════
#  SUBMENUS
# ══════════════════════════════════════════════════════════════

class ConfigYouTubeMenu(_SubMenu):
    def build_embed(self, config: dict) -> discord.Embed:
        e = E("📺 YouTube Settings", color=C_MAIN)
        e.add_field(name="YouTube Channel ID", value=f"`{config.get('youtube_channel_id') or 'Not set'}`", inline=True)
        e.set_footer(text="The bot checks for new videos every 60 seconds")
        return e

    @discord.ui.button(label="Set YouTube Channel", style=discord.ButtonStyle.blurple, row=0)
    async def btn_yt(self, interaction: discord.Interaction, btn: discord.ui.Button):
        config = db_get_config(self.guild.id)
        async def submit(inter, value):
            await inter.response.send_message("🔍 Resolving channel...", ephemeral=True)
            ch_id = await resolve_youtube_channel_id(value)
            if not ch_id:
                await inter.edit_original_response(content="❌ Could not find this channel. Check the handle or paste the ID directly.")
                return
            db_set_config(self.guild.id, youtube_channel_id=ch_id)
            await inter.edit_original_response(content=f"✅ YouTube channel set to `{ch_id}`")
            await self._refresh(interaction)
        await interaction.response.send_modal(Modal1(
            title="Set YouTube Channel", label="Channel handle or ID",
            placeholder="@YourChannel  or  UCxxxxxxxxxxxxxxxxxxxxxxxxx",
            default=config.get("youtube_channel_id") or "", callback=submit
        ))

    @discord.ui.button(label="Test YouTube Feed", style=discord.ButtonStyle.grey, row=0)
    async def btn_test(self, interaction: discord.Interaction, btn: discord.ui.Button):
        config = db_get_config(self.guild.id)
        ch_id = config.get("youtube_channel_id")
        if not ch_id:
            await interaction.response.send_message("❌ No YouTube channel configured.", ephemeral=True)
            return
        await interaction.response.send_message("🔍 Fetching feed...", ephemeral=True)
        videos = await fetch_latest_videos(ch_id)
        if not videos:
            await interaction.edit_original_response(content="❌ No videos found or invalid channel ID.")
            return
        latest = videos[0]
        await interaction.edit_original_response(
            content=f"✅ Feed working!\n**Latest:** {latest['title']}\n🔗 {latest['url']}"
        )

class ConfigChannelsMenu(_SubMenu):
    def build_embed(self, config: dict) -> discord.Embed:
        e = E("💬 Channel Settings", color=C_MAIN)
        e.add_field(name="🔗 Share Channel",      value=_ch(config.get("share_channel_id")),              inline=True)
        e.add_field(name="🔔 Notifications",      value=_ch(config.get("notification_channel_id")),       inline=True)
        e.add_field(name="💬 Commands",           value=_ch(config.get("commands_channel_id")),           inline=True)
        e.add_field(name="🛒 Shop Channel",       value=_ch(config.get("shop_channel_id")),               inline=True)
        e.add_field(name="📅 Quests Channel",     value=_ch(config.get("quests_channel_id")),             inline=True)
        e.add_field(name="🛡️ Admin",             value=_ch(config.get("admin_channel_id")),              inline=True)
        e.add_field(name="📋 Log",                value=_ch(config.get("log_channel_id")),                inline=True)
        e.add_field(name="💾 Backup",             value=_ch(config.get("backup_channel_id")),             inline=True)
        e.add_field(name="🔑 Admin Commands",     value=_ch(config.get("admin_commands_channel_id")),     inline=True)
        ping_r = _role(config.get("share_ping_role_id")) if config.get("share_ping_role_id") else "`@everyone`"
        e.add_field(name="🔔 Ping Role",          value=ping_r,                                           inline=True)
        e.add_field(name="📢 Event Announce",     value=_ch(config.get("event_announce_channel_id")),     inline=True)
        cat_id = config.get("ticket_category_id")
        e.add_field(name="🎫 Ticket Category",    value=f"`{cat_id}`" if cat_id else "`No category`",     inline=True)
        e.add_field(name="🎯 Reaction Channel",   value=_ch(config.get("reaction_channel_id")),           inline=True)
        e.add_field(name="🛍️ Daily Shop Post",   value=_ch(config.get("daily_shop_channel_id")),          inline=True)
        e.add_field(name="\u200b", value=(
            "**Share** — members post link + screenshot here\n"
            "**Notifications** — invites, quests, achievements\n"
            "**Commands** — /gems, /leaderboard, /video, /achievements, /tutorial\n"
            "**Shop** — /shop and /inventory only (falls back to Commands if not set)\n"
            "**Quests** — /quests only (falls back to Commands if not set)\n"
            "**Admin** — expired items, text orders\n"
            "**Log** — admin actions\n"
            "**Backup** — DB file every 15 min\n"
            "**Admin Commands** — staff-only channel where ALL bot commands work freely, bypassing every channel restriction\n"
            "**Event Announce** — event launch ping (pings Notification role)\n"
            "**Ticket Category** — category where purchase tickets are created\n"
            "**Reaction Channel** — restrict Meeple Owner gem reactions to this channel"
        ), inline=False)
        return e

    def _ch_btn(self, label: str, config_key: str, title: str):
        async def handler(interaction: discord.Interaction, btn):
            config = db_get_config(self.guild.id)
            async def submit(inter, value):
                if not value.strip():
                    db_set_config(self.guild.id, **{config_key: None})
                    await inter.response.send_message("✅ Channel removed.", ephemeral=True)
                else:
                    ch_id = parse_channel_id(value)
                    if not ch_id:
                        await inter.response.send_message("❌ Invalid channel.", ephemeral=True)
                        return
                    db_set_config(self.guild.id, **{config_key: ch_id})
                    await inter.response.send_message(f"✅ Set to <#{ch_id}>", ephemeral=True)
                # Refresh the panel via the original button's message (modal token
                # cannot edit_original_response on a message — only on the modal itself)
                try:
                    await interaction.message.edit(
                        embed=self.build_embed(db_get_config(self.guild.id)), view=self)
                except Exception:
                    pass
            await interaction.response.send_modal(Modal1(
                title=title, label="Channel mention or ID (empty = remove)",
                placeholder="#channel  or  1234567890",
                default=str(config.get(config_key) or ""),
                required=False, callback=submit
            ))
        return handler

    @discord.ui.button(label="Share Channel",        style=discord.ButtonStyle.blurple, row=0)
    async def btn_share(self, interaction, btn):
        await self._ch_btn("Share Channel", "share_channel_id", "Set Share Channel")(interaction, btn)

    @discord.ui.button(label="Notifications",        style=discord.ButtonStyle.blurple, row=0)
    async def btn_notif(self, interaction, btn):
        await self._ch_btn("Notifications", "notification_channel_id", "Set Notification Channel")(interaction, btn)

    @discord.ui.button(label="Commands Channel",     style=discord.ButtonStyle.blurple, row=0)
    async def btn_cmd(self, interaction, btn):
        await self._ch_btn("Commands Channel", "commands_channel_id", "Set Commands Channel")(interaction, btn)

    @discord.ui.button(label="Admin Channel",        style=discord.ButtonStyle.blurple, row=1)
    async def btn_admin(self, interaction, btn):
        await self._ch_btn("Admin Channel", "admin_channel_id", "Set Admin Channel")(interaction, btn)

    @discord.ui.button(label="Log Channel",          style=discord.ButtonStyle.blurple, row=1)
    async def btn_log(self, interaction, btn):
        await self._ch_btn("Log Channel", "log_channel_id", "Set Log Channel")(interaction, btn)

    @discord.ui.button(label="Backup Channel",       style=discord.ButtonStyle.blurple, row=1)
    async def btn_bak(self, interaction, btn):
        await self._ch_btn("Backup Channel", "backup_channel_id", "Set Backup Channel")(interaction, btn)

    @discord.ui.button(label="🔑 Admin Commands",   style=discord.ButtonStyle.green,   row=1)
    async def btn_admin_cmd(self, interaction, btn):
        await self._ch_btn("Admin Commands Channel", "admin_commands_channel_id",
                           "Set Admin Commands Channel")(interaction, btn)

    @discord.ui.button(label="Ping Role",            style=discord.ButtonStyle.grey, row=2)
    async def btn_ping(self, interaction: discord.Interaction, btn):
        config = db_get_config(self.guild.id)
        async def submit(inter, value):
            if not value.strip():
                db_set_config(self.guild.id, share_ping_role_id=None)
                await inter.response.send_message("✅ Ping role removed — bot will use @everyone.", ephemeral=True)
                await self._refresh(interaction)
                return
            raw = value.strip().lstrip("<@&").rstrip(">")
            if not raw.isdigit():
                await inter.response.send_message("❌ Mention the role or paste its ID.", ephemeral=True)
                return
            db_set_config(self.guild.id, share_ping_role_id=int(raw))
            await inter.response.send_message(f"✅ Ping role set to <@&{raw}>", ephemeral=True)
            await self._refresh(interaction)
        await interaction.response.send_modal(Modal1(
            title="Set Ping Role", label="Role mention or ID (empty = @everyone)",
            placeholder="@Subscribers  or  1234567890",
            default=str(config.get("share_ping_role_id") or ""),
            required=False, callback=submit
        ))

    @discord.ui.button(label="Event Announce",       style=discord.ButtonStyle.blurple, row=2)
    async def btn_event_announce(self, interaction, btn):
        await self._ch_btn("Event Announce Channel", "event_announce_channel_id",
                           "Set Event Announce Channel")(interaction, btn)

    @discord.ui.button(label="Reaction Channel",     style=discord.ButtonStyle.blurple, row=2)
    async def btn_reaction_ch(self, interaction, btn):
        await self._ch_btn("Reaction Channel", "reaction_channel_id",
                           "Set Reaction Channel")(interaction, btn)

    @discord.ui.button(label="Shop Channel",         style=discord.ButtonStyle.blurple, row=3)
    async def btn_shop_ch(self, interaction, btn):
        await self._ch_btn("Shop Channel", "shop_channel_id", "Set Shop Channel")(interaction, btn)

    @discord.ui.button(label="🛍️ Daily Shop Post",  style=discord.ButtonStyle.blurple, row=3)
    async def btn_daily_shop_ch(self, interaction, btn):
        await self._ch_btn("Daily Shop Post Channel", "daily_shop_channel_id",
                           "Daily Shop Post Channel")(interaction, btn)

    @discord.ui.button(label="Quests Channel",       style=discord.ButtonStyle.blurple, row=3)
    async def btn_quests_ch(self, interaction, btn):
        await self._ch_btn("Quests Channel", "quests_channel_id", "Set Quests Channel")(interaction, btn)

    @discord.ui.button(label="📢 Announce Message",  style=discord.ButtonStyle.grey,    row=3)
    async def btn_announce_msg(self, interaction: discord.Interaction, btn):
        """Set a custom video announcement message with placeholders."""
        config = db_get_config(self.guild.id)
        async def submit(inter, value):
            v = value.strip()
            if not v:
                db_set_config(self.guild.id, video_announce_message=None)
                await inter.response.send_message(
                    "✅ Announcement message reset to default.", ephemeral=True)
            else:
                db_set_config(self.guild.id, video_announce_message=v)
                await inter.response.send_message(
                    f"✅ Custom announcement message saved.\n"
                    f"Placeholders: `{{mention}}` `{{url}}` `{{deadline}}` `{{title}}`",
                    ephemeral=True)
            await self._refresh(interaction)
        current_msg = config.get("video_announce_message") or ""
        await interaction.response.send_modal(Modal1(
            title="Video Announcement Message",
            label="Message (empty = restore default)",
            placeholder="{mention} 📲 Share the video!\n🔗 {url}\nDeadline: {deadline}",
            default=current_msg,
            required=False,
            paragraph=True,
            max_length=1000,
            callback=submit
        ))

    @discord.ui.button(label="Ticket Category",      style=discord.ButtonStyle.grey, row=2)
    async def btn_ticket_cat(self, interaction: discord.Interaction, btn):
        config = db_get_config(self.guild.id)
        async def submit(inter, value):
            if not value.strip():
                db_set_config(self.guild.id, ticket_category_id=None)
                await inter.response.send_message("✅ Ticket category removed — tickets will be created without a category.", ephemeral=True)
                await self._refresh(interaction)
                return
            cat_id = parse_channel_id(value)
            if not cat_id:
                await inter.response.send_message("❌ Invalid category ID.", ephemeral=True)
                return
            db_set_config(self.guild.id, ticket_category_id=cat_id)
            await inter.response.send_message(f"✅ Ticket category set to `{cat_id}`", ephemeral=True)
            await self._refresh(interaction)
        await interaction.response.send_modal(Modal1(
            title="Set Ticket Category", label="Category ID (empty = no category)",
            placeholder="1234567890",
            default=str(config.get("ticket_category_id") or ""),
            required=False, callback=submit
        ))

    @discord.ui.button(label="Info Channel",         style=discord.ButtonStyle.blurple, row=2)
    async def btn_info_ch(self, interaction: discord.Interaction, btn):
        config = db_get_config(self.guild.id)
        async def submit(inter, value):
            if not value.strip():
                db_set_config(self.guild.id, info_channel_id=None, info_message_id=None)
                await inter.response.send_message("✅ Info channel removed.", ephemeral=True)
                await self._refresh(interaction)
                return
            ch_id = parse_channel_id(value)
            if not ch_id:
                await inter.response.send_message("❌ Invalid channel.", ephemeral=True)
                return
            db_set_config(self.guild.id, info_channel_id=ch_id, info_message_id=None)
            await inter.response.send_message(f"✅ Info channel set to <#{ch_id}>\nUse **Update Info Message** to post the embed.", ephemeral=True)
            await self._refresh(interaction)
        await interaction.response.send_modal(Modal1(
            title="Set Info Channel", label="Channel mention or ID (empty = remove)",
            placeholder="#xp-info  or  1234567890",
            default=str(config.get("info_channel_id") or ""),
            required=False, callback=submit
        ))

    @discord.ui.button(label="Update Info Message",  style=discord.ButtonStyle.green, row=3)
    async def btn_update_info(self, interaction: discord.Interaction, btn):
        await interaction.response.defer(ephemeral=True)
        config = db_get_config(self.guild.id)
        ok, msg = await post_or_update_info_embed(bot, self.guild, config)
        await interaction.followup.send(f"{'✅' if ok else '❌'} {msg}", ephemeral=True)

class ConfigDMsMenu(_SubMenu):
    def build_embed(self, config: dict) -> discord.Embed:
        e = E("📨 DMs & Welcome Settings", color=C_INFO)
        _on  = lambda v: "✅ Enabled" if v else "❌ Disabled"
        e.add_field(name="📩 Welcome DM (on join)",      value=_on(config.get("welcome_dm_enabled", 0)),       inline=True)
        e.add_field(name="🔖 DM Role Filter",            value=_role(config.get("welcome_dm_role_id")) or "`All new members`", inline=True)
        e.add_field(name="🎭 DM on Role Assign",         value=_role(config.get("welcome_dm_on_role_id")) or "`Not set`",      inline=True)
        e.add_field(name="👋 Server Welcome Msg",        value=_on(config.get("server_welcome_enabled", 0)),   inline=True)
        e.add_field(name="📢 Welcome Channel",           value=_ch(config.get("server_welcome_channel_id")),   inline=True)
        e.add_field(name="🎭 Welcome on Role Assign",    value=_role(config.get("server_welcome_on_role_id")) or "`Not set`",  inline=True)
        e.add_field(name="⚠️ Streak Reminder DM",       value=_on(config.get("streak_reminder_enabled", 0)),  inline=True)
        e.add_field(name="🗓️ Daily Quest DM",            value=_on(config.get("daily_quest_dm_enabled", 1)),   inline=True)
        e.add_field(name="🆕 New Shop Item DM",           value=_on(config.get("new_item_dm_enabled", 1)),      inline=True)
        new_item_delay = max(0, _safe_int(config.get("new_item_dm_delay_minutes"), 5))
        e.add_field(name="⏱️ New Item Delay",             value=f"**{new_item_delay} min**",                  inline=True)
        e.add_field(name="🎫 Purchase DM (to role)",     value=_on(config.get("purchase_dm_enabled", 1)),       inline=True)
        dm_role_val = _role(config.get("purchase_dm_role_id")) if config.get("purchase_dm_role_id") else "`Meeple Owner (default)`"
        e.add_field(name="📬 Purchase DM Role",          value=dm_role_val,                                     inline=True)
        balance_dm_uid = config.get("balance_change_dm_user_id")
        e.add_field(
            name="💰 Balance Change DM Recipient",
            value=f"<@{balance_dm_uid}>" if balance_dm_uid else "`Not set`",
            inline=True,
        )
        notif_mins_raw = config.get("notify_prompt_cooldown_minutes")
        if notif_mins_raw is None:
            _legacy_days = config.get("notify_prompt_cooldown_days")
            notif_mins_raw = (3 if _legacy_days is None else _legacy_days) * 1440
        notif_mins = _safe_int(notif_mins_raw, 4320)
        if notif_mins <= 0:
            notif_label = "Always show"
        elif notif_mins < 60:
            notif_label = f"{notif_mins} min"
        elif notif_mins < 1440:
            notif_label = f"{notif_mins // 60} h"
        else:
            notif_label = f"{notif_mins // 1440} day{'s' if notif_mins // 1440 != 1 else ''}"
        e.add_field(name="🔕 Notif Prompt Cooldown",    value=f"**{notif_label}**", inline=True)
        bulk_dm_role = config.get("bulk_dm_role_id")
        e.add_field(name="📨 Bulk DM Role",              value=_role(bulk_dm_role) if bulk_dm_role else "`Not set`", inline=True)
        e.add_field(name="\u200b", value=(
            "**Welcome DM** — bot DMs new members when they join\n"
            "**DM Role Filter** — (unused on join, only for reference)\n"
            "**DM on Role Assign** — DM when a member receives this specific role (independent of Welcome DM toggle)\n"
            "**Server Welcome Msg** — posts a welcome message in a channel\n"
            "**Welcome on Role Assign** — triggers welcome msg when member gets this role\n"
            "**Streak Reminder** — DMs members with <5 min left to share and keep their streak\n"
            "**Daily Quest DM** — enable or disable the daily quest DMs\n"
            "**New Shop Item DM** — notify the Meeple Owner role about newly created shop items\n"
            "**Balance Change DM Recipient** — personally DM this member after a manual balance change in /admin\n"
            "**New Item Delay** — wait before notifying, default **5 minutes** so images and rewards can be added\n"
            "**Purchase DM** — enable/disable DM notifications when a purchase ticket opens\n"
            "**Purchase DM Role** — role that receives purchase DMs (default: Meeple Owner)\n"
            "**Notif Prompt Cooldown** — days before the 🔔 notification prompt reappears after 'Later'\n"
            "**Bulk DM Role** — role whose members receive the welcome DM when you press **📨 Send DMs** below\n"
            "➡️ Gift Gems settings moved to **🎁 Gift Gems** in the main /config menu."
        ), inline=False)
        return e

    def _parse_role(self, value: str):
        raw = value.strip().lstrip("<@&").rstrip(">")
        return int(raw) if raw.isdigit() else None

    @discord.ui.button(label="Toggle Welcome DM",        style=discord.ButtonStyle.blurple, row=0)
    async def btn_toggle_dm(self, interaction: discord.Interaction, btn):
        config = db_get_config(self.guild.id)
        new_val = 0 if config.get("welcome_dm_enabled", 0) else 1
        db_set_config(self.guild.id, welcome_dm_enabled=new_val)
        await interaction.response.send_message(
            f"✅ Welcome DM {'**enabled**' if new_val else '**disabled**'}.", ephemeral=True)
        await self._refresh(interaction)

    @discord.ui.button(label="DM Role Filter",           style=discord.ButtonStyle.grey,    row=0)
    async def btn_dm_role(self, interaction: discord.Interaction, btn):
        config = db_get_config(self.guild.id)
        async def submit(inter, value):
            if not value.strip():
                db_set_config(self.guild.id, welcome_dm_role_id=None)
                await inter.response.send_message("✅ Role filter removed — all new members will be DM'd.", ephemeral=True)
            else:
                rid = self._parse_role(value)
                if not rid:
                    await inter.response.send_message("❌ Invalid role.", ephemeral=True); return
                db_set_config(self.guild.id, welcome_dm_role_id=rid)
                await inter.response.send_message(f"✅ Only members with <@&{rid}> will receive the DM.", ephemeral=True)
            await self._refresh(interaction)
        await interaction.response.send_modal(Modal1(
            title="DM Role Filter", label="Role mention or ID (empty = all members)",
            placeholder="@Member  or  1234567890",
            default=str(config.get("welcome_dm_role_id") or ""),
            required=False, callback=submit
        ))

    @discord.ui.button(label="DM on Role Assign",        style=discord.ButtonStyle.grey,    row=0)
    async def btn_dm_on_role(self, interaction: discord.Interaction, btn):
        config = db_get_config(self.guild.id)
        async def submit(inter, value):
            if not value.strip():
                db_set_config(self.guild.id, welcome_dm_on_role_id=None)
                await inter.response.send_message("✅ Role trigger removed.", ephemeral=True)
            else:
                rid = self._parse_role(value)
                if not rid:
                    await inter.response.send_message("❌ Invalid role.", ephemeral=True); return
                db_set_config(self.guild.id, welcome_dm_on_role_id=rid)
                await inter.response.send_message(f"✅ Bot will DM members when they receive <@&{rid}>.", ephemeral=True)
            await self._refresh(interaction)
        await interaction.response.send_modal(Modal1(
            title="DM on Role Assign", label="Role mention or ID (empty = disable)",
            placeholder="@Verified  or  1234567890",
            default=str(config.get("welcome_dm_on_role_id") or ""),
            required=False, callback=submit
        ))

    @discord.ui.button(label="Toggle Welcome Msg",       style=discord.ButtonStyle.blurple, row=1)
    async def btn_toggle_sw(self, interaction: discord.Interaction, btn):
        config = db_get_config(self.guild.id)
        new_val = 0 if config.get("server_welcome_enabled", 0) else 1
        db_set_config(self.guild.id, server_welcome_enabled=new_val)
        await interaction.response.send_message(
            f"✅ Server welcome message {'**enabled**' if new_val else '**disabled**'}.", ephemeral=True)
        await self._refresh(interaction)

    @discord.ui.button(label="Welcome Channel",          style=discord.ButtonStyle.grey,    row=1)
    async def btn_sw_channel(self, interaction: discord.Interaction, btn):
        config = db_get_config(self.guild.id)
        async def submit(inter, value):
            if not value.strip():
                db_set_config(self.guild.id, server_welcome_channel_id=None)
                await inter.response.send_message("✅ Welcome channel removed.", ephemeral=True)
            else:
                ch_id = parse_channel_id(value)
                if not ch_id:
                    await inter.response.send_message("❌ Invalid channel.", ephemeral=True); return
                db_set_config(self.guild.id, server_welcome_channel_id=ch_id)
                await inter.response.send_message(f"✅ Welcome messages will be posted in <#{ch_id}>.", ephemeral=True)
            await self._refresh(interaction)
        await interaction.response.send_modal(Modal1(
            title="Welcome Channel", label="Channel mention or ID (empty = remove)",
            placeholder="#welcome  or  1234567890",
            default=str(config.get("server_welcome_channel_id") or ""),
            required=False, callback=submit
        ))

    @discord.ui.button(label="Welcome on Role Assign",   style=discord.ButtonStyle.grey,    row=1)
    async def btn_sw_on_role(self, interaction: discord.Interaction, btn):
        config = db_get_config(self.guild.id)
        async def submit(inter, value):
            if not value.strip():
                db_set_config(self.guild.id, server_welcome_on_role_id=None)
                await inter.response.send_message("✅ Role trigger removed.", ephemeral=True)
            else:
                rid = self._parse_role(value)
                if not rid:
                    await inter.response.send_message("❌ Invalid role.", ephemeral=True); return
                db_set_config(self.guild.id, server_welcome_on_role_id=rid)
                await inter.response.send_message(
                    f"✅ Welcome message will post when a member receives <@&{rid}>.", ephemeral=True)
            await self._refresh(interaction)
        await interaction.response.send_modal(Modal1(
            title="Welcome on Role Assign", label="Role mention or ID (empty = disable)",
            placeholder="@Verified  or  1234567890",
            default=str(config.get("server_welcome_on_role_id") or ""),
            required=False, callback=submit
        ))

    @discord.ui.button(label="Notif Cooldown",            style=discord.ButtonStyle.grey,    row=2)
    async def btn_notif_cooldown(self, interaction: discord.Interaction, btn):
        config = db_get_config(self.guild.id)
        async def submit(inter, value):
            raw = value.strip().lower()
            if raw in ("0", "always"):
                minutes = 0
            else:
                # Accept: 30m / 2h / 3d — defaults to minutes if plain number
                import re as _re
                m = _re.fullmatch(r"(\d+)\s*(m(?:in(?:utes?)?)?|h(?:ours?)?|d(?:ays?)?)?", raw)
                if not m:
                    await inter.response.send_message(
                        "❌ Format: `30m`, `2h`, `3d`, or `0` for always show.", ephemeral=True)
                    return
                n, unit = int(m.group(1)), (m.group(2) or "m")[0]
                if n < 0:
                    await inter.response.send_message("❌ Value must be ≥ 0.", ephemeral=True)
                    return
                minutes = n * {"m": 1, "h": 60, "d": 1440}[unit]
            db_set_config(self.guild.id, notify_prompt_cooldown_minutes=minutes)
            label = "Always show" if minutes == 0 else (
                f"{minutes} min" if minutes < 60 else
                f"{minutes // 60} h" if minutes < 1440 else
                f"{minutes // 1440} day{'s' if minutes // 1440 != 1 else ''}")
            await inter.response.send_message(
                f"✅ Notification prompt cooldown set to **{label}**.", ephemeral=True)
            await self._refresh(interaction)
        cur_mins = config.get("notify_prompt_cooldown_minutes")
        if cur_mins is None:
            _leg = config.get("notify_prompt_cooldown_days")
            cur_mins = (3 if _leg is None else _leg) * 1440
        cur_mins = _safe_int(cur_mins, 4320)
        if cur_mins == 0:
            default_str = "0"
        elif cur_mins % 1440 == 0:
            default_str = f"{cur_mins // 1440}d"
        elif cur_mins % 60 == 0:
            default_str = f"{cur_mins // 60}h"
        else:
            default_str = f"{cur_mins}m"
        await interaction.response.send_modal(Modal1(
            title="Notification Prompt Cooldown",
            label="Time before prompt reappears (30m / 2h / 3d / 0)",
            placeholder="3d",
            default=default_str,
            callback=submit
        ))

    @discord.ui.button(label="Toggle Streak Reminder",   style=discord.ButtonStyle.blurple, row=2)
    async def btn_toggle_streak_reminder(self, interaction: discord.Interaction, btn):
        config = db_get_config(self.guild.id)
        new_val = 0 if config.get("streak_reminder_enabled", 0) else 1
        db_set_config(self.guild.id, streak_reminder_enabled=new_val)
        status_str = "**enabled**" if new_val else "**disabled**"
        detail_str = "Members with an active streak will be DMed when < 5 min remain to share." if new_val else ""
        await interaction.response.send_message(
            f"✅ Streak reminder DM {status_str}.\n{detail_str}",
            ephemeral=True)
        await self._refresh(interaction)

    @discord.ui.button(label="Toggle Daily Quest DM", style=discord.ButtonStyle.blurple, row=3)
    async def btn_toggle_daily_quest_dm(self, interaction: discord.Interaction, btn):
        config = db_get_config(self.guild.id)
        new_val = 0 if config.get("daily_quest_dm_enabled", 1) else 1
        db_set_config(self.guild.id, daily_quest_dm_enabled=new_val)
        await interaction.response.send_message(
            f"✅ Daily quest DM {'**enabled**' if new_val else '**disabled**'}.",
            ephemeral=True,
        )
        await self._refresh(interaction)

    @discord.ui.button(label="Toggle New Item DM", style=discord.ButtonStyle.blurple, row=4)
    async def btn_toggle_new_item_dm(self, interaction: discord.Interaction, btn):
        config = db_get_config(self.guild.id)
        new_val = 0 if config.get("new_item_dm_enabled", 1) else 1
        db_set_config(self.guild.id, new_item_dm_enabled=new_val)
        await interaction.response.send_message(
            f"✅ New shop item DM {'**enabled**' if new_val else '**disabled**'}.",
            ephemeral=True,
        )
        await self._refresh(interaction)

    @discord.ui.button(label="Balance DM Recipient", style=discord.ButtonStyle.grey, row=3)
    async def btn_balance_dm_recipient(self, interaction: discord.Interaction, btn):
        config = db_get_config(self.guild.id)

        async def submit(inter, value):
            value = value.strip()
            if not value:
                db_set_config(self.guild.id, balance_change_dm_user_id=None)
                await inter.response.send_message(
                    "✅ Balance change DMs disabled — no personal audit DM will be sent.",
                    ephemeral=True,
                )
            else:
                uid = parse_user_id(value)
                if not uid:
                    await inter.response.send_message(
                        "❌ Invalid member. Mention the member or paste their numeric ID.",
                        ephemeral=True,
                    )
                    return
                db_set_config(self.guild.id, balance_change_dm_user_id=uid)
                await inter.response.send_message(
                    f"✅ <@{uid}> will receive a personal DM after a Gems Owner changes a balance in `/admin`.",
                    ephemeral=True,
                )
            await self._refresh(interaction)

        await interaction.response.send_modal(Modal1(
            title="Balance DM Recipient",
            label="Member mention or ID (empty = disable)",
            placeholder="@username  or  1234567890",
            default=str(config.get("balance_change_dm_user_id") or ""),
            required=False,
            callback=submit,
        ))

    @discord.ui.button(label="New Item Delay", style=discord.ButtonStyle.grey, row=4)
    async def btn_new_item_delay(self, interaction: discord.Interaction, btn):
        config = db_get_config(self.guild.id)

        async def submit(inter, value):
            try:
                delay = int(value.strip())
                if delay < 0 or delay > 10080:
                    raise ValueError
            except ValueError:
                await inter.response.send_message(
                    "❌ Enter a whole number from 0 to 10080 minutes.",
                    ephemeral=True,
                )
                return
            db_set_config(self.guild.id, new_item_dm_delay_minutes=delay)
            await inter.response.send_message(
                f"✅ New shop item DM delay set to **{delay} minute(s)**.",
                ephemeral=True,
            )
            await self._refresh(interaction)

        await interaction.response.send_modal(Modal1(
            title="New Item DM Delay",
            label="Delay in minutes (0 = immediately)",
            placeholder="5",
            default=str(config.get("new_item_dm_delay_minutes") or 5),
            callback=submit,
        ))

    @discord.ui.button(label="Bulk DM Role",              style=discord.ButtonStyle.grey,    row=2)
    async def btn_bulk_dm_role(self, interaction: discord.Interaction, btn):
        """Set the role whose members will receive a welcome DM when admin presses Send DMs."""
        config = db_get_config(self.guild.id)
        async def submit(inter, value):
            if not value.strip():
                db_set_config(self.guild.id, bulk_dm_role_id=None)
                await inter.response.send_message("✅ Bulk DM role removed.", ephemeral=True)
            else:
                rid = self._parse_role(value)
                if not rid:
                    await inter.response.send_message("❌ Invalid role.", ephemeral=True); return
                db_set_config(self.guild.id, bulk_dm_role_id=rid)
                await inter.response.send_message(
                    f"✅ Bulk DM role set to <@&{rid}>.\n"
                    "Use **📨 Send DMs** below to send the welcome DM to all members with this role.",
                    ephemeral=True)
            await self._refresh(interaction)
        await interaction.response.send_modal(Modal1(
            title="Bulk DM Role",
            label="Role mention or ID (empty = remove)",
            placeholder="@Members  or  1234567890",
            default=str(config.get("bulk_dm_role_id") or ""),
            required=False, callback=submit
        ))

    @discord.ui.button(label="Toggle Purchase DM",       style=discord.ButtonStyle.blurple, row=2)
    async def btn_toggle_purchase_dm(self, interaction: discord.Interaction, btn):
        config = db_get_config(self.guild.id)
        new_val = 0 if config.get("purchase_dm_enabled", 1) else 1
        db_set_config(self.guild.id, purchase_dm_enabled=new_val)
        status_str = "**enabled**" if new_val else "**disabled**"
        await interaction.response.send_message(
            f"✅ Purchase ticket DM {status_str}.\n"
            + ("Role members will be DM'd when a member buys a shop item." if new_val else "No DM will be sent on purchase."),
            ephemeral=True)
        await self._refresh(interaction)

    @discord.ui.button(label="Purchase DM Role",         style=discord.ButtonStyle.grey,    row=2)
    async def btn_purchase_dm_role(self, interaction: discord.Interaction, btn):
        config = db_get_config(self.guild.id)
        async def submit(inter, value):
            if not value.strip():
                db_set_config(self.guild.id, purchase_dm_role_id=None)
                await inter.response.send_message(
                    "✅ Purchase DM role removed — Meeple Owner role will be used by default.", ephemeral=True)
            else:
                rid = self._parse_role(value)
                if not rid:
                    await inter.response.send_message("❌ Invalid role.", ephemeral=True); return
                db_set_config(self.guild.id, purchase_dm_role_id=rid)
                await inter.response.send_message(
                    f"✅ Purchase DMs will be sent to members with <@&{rid}>.", ephemeral=True)
            await self._refresh(interaction)
        await interaction.response.send_modal(Modal1(
            title="Purchase DM Role",
            label="Role mention or ID (empty = use Meeple Owner)",
            placeholder="@StoreManager  or  1234567890",
            default=str(config.get("purchase_dm_role_id") or ""),
            required=False, callback=submit
        ))

    @discord.ui.button(label="📨 Send DMs",              style=discord.ButtonStyle.green,   row=3)
    async def btn_send_dms(self, i: discord.Interaction, b):
        """Send the welcome DM to all members of the configured Bulk DM Role."""
        await i.response.defer(ephemeral=True)
        config = db_get_config(self.guild.id)
        bulk_role_id = config.get("bulk_dm_role_id")
        if not bulk_role_id:
            await i.followup.send(
                "❌ No Bulk DM Role configured.\n"
                "Use **Bulk DM Role** above to set the role first.",
                ephemeral=True)
            return
        role = self.guild.get_role(bulk_role_id)
        if not role:
            await i.followup.send("❌ Role not found — it may have been deleted.", ephemeral=True)
            return
        members_to_dm = [m for m in role.members if not m.bot]
        if not members_to_dm:
            await i.followup.send(f"❌ No members found with <@&{bulk_role_id}>.", ephemeral=True)
            return
        total = len(members_to_dm)
        # Rate-limit constants:
        #  • 2 s between each DM  → well within Discord's per-account anti-spam threshold
        #  • 45 s pause every 25  → avoids the medium-term heuristic that flagged the bot
        DM_DELAY_S      = 2.0   # seconds between every individual DM
        BATCH_SIZE      = 25    # DMs per batch before a longer pause
        BATCH_PAUSE_S   = 45    # seconds to wait between batches

        eta_min = round((total * DM_DELAY_S + (total // BATCH_SIZE) * BATCH_PAUSE_S) / 60, 1)
        await i.followup.send(
            f"📨 Sending welcome DM to **{total}** member(s) with <@&{bulk_role_id}>…\n"
            f"⏱️ Estimated time: **~{eta_min} min** (rate-limited to avoid spam flags).",
            ephemeral=True)
        sent = 0
        failed = 0
        for idx, member in enumerate(members_to_dm, start=1):
            success = await send_welcome_dm(member, config, trigger="bulk")
            if success:
                sent += 1
            else:
                failed += 1
            # Every BATCH_SIZE DMs, take a longer break to avoid Discord's anti-spam heuristic
            if idx % BATCH_SIZE == 0 and idx < total:
                try:
                    await i.followup.send(
                        f"📨 Progress: **{sent}** sent, **{failed}** failed out of {idx}/{total}. "
                        f"Pausing {BATCH_PAUSE_S}s to avoid rate-limit…",
                        ephemeral=True)
                except Exception:
                    pass
                await asyncio.sleep(BATCH_PAUSE_S)
            else:
                await asyncio.sleep(DM_DELAY_S)
        await i.followup.send(
            f"✅ Done — **{sent}** DM(s) sent, **{failed}** failed.\n"
            + (f"⚠️ {failed} member(s) may have DMs disabled — check the log channel for details." if failed else ""),
            ephemeral=True)
        await bot_log(i.client, self.guild.id, "📨 Bulk DM Sent",
                      f"**Triggered by:** {i.user.mention}\n"
                      f"**Role:** <@&{bulk_role_id}>\n"
                      f"**Sent:** {sent} | **Failed:** {failed}", C_INFO)


class ConfigGiftMenu(_SubMenu):
    """Configure the 🎁 /give (gift gems) feature."""

    def build_embed(self, config: dict) -> discord.Embed:
        _on    = lambda v: "✅ Enabled" if v else "❌ Disabled"
        c_name = config.get("currency_name") or "Gems"
        e = E("🎁 Gift Gems — /give Settings", color=C_GOLD)
        e.add_field(name="🎁 /give Enabled",        value=_on(config.get("give_enabled", 0)),           inline=True)
        e.add_field(name="📤 Max Given/Day",         value=f"**{config.get('give_max_daily', 100)} {c_name}**",     inline=True)
        e.add_field(name="📥 Recv Limit/Day",        value=f"**{config.get('give_receive_cooldown_h', 1)} gift(s)**", inline=True)
        e.add_field(name="🔒 Min Balance to Give",   value=f"**{config.get('give_min_balance', 1000)} {c_name}**",  inline=True)
        e.add_field(name="\u200b", value=(
            "**Toggle /give** — enable or disable the gift command server-wide\n"
            "**Max Given/Day** — max gems one member can send as gifts per day\n"
            "**Recv Limit/Day** — max gifts a member can receive per day (default: 1)\n"
            "**Min Balance** — sender must hold at least this many gems to use /give (anti-alt)"
        ), inline=False)
        return e

    @discord.ui.button(label="🎁 Toggle /give",       style=discord.ButtonStyle.blurple, row=0)
    async def btn_gift_toggle(self, interaction: discord.Interaction, btn):
        config  = db_get_config(self.guild.id)
        new_val = 0 if config.get("give_enabled", 0) else 1
        db_set_config(self.guild.id, give_enabled=new_val)
        await interaction.response.send_message(
            f"✅ Gift gems (/give) {'**enabled**' if new_val else '**disabled**'}.", ephemeral=True)
        await self._refresh(interaction)

    @discord.ui.button(label="📤 Max Given/Day",      style=discord.ButtonStyle.grey,    row=0)
    async def btn_gift_max(self, interaction: discord.Interaction, btn):
        config = db_get_config(self.guild.id)
        async def submit(inter, value):
            try:
                v = int(value.strip())
                if v <= 0: raise ValueError
            except ValueError:
                await inter.response.send_message("❌ Enter a positive number.", ephemeral=True); return
            db_set_config(self.guild.id, give_max_daily=v)
            await inter.response.send_message(
                f"✅ Max gift per day set to **{cur(db_get_config(self.guild.id), v)}**.", ephemeral=True)
            await self._refresh(interaction)
        await interaction.response.send_modal(Modal1(
            "Max Gift Per Day", "Max gems any member can give per day",
            placeholder="100", default=str(config.get("give_max_daily", 100)), callback=submit))

    @discord.ui.button(label="📥 Recv Limit/Day",     style=discord.ButtonStyle.grey,    row=0)
    async def btn_gift_recv(self, interaction: discord.Interaction, btn):
        config = db_get_config(self.guild.id)
        async def submit(inter, value):
            try:
                v = int(value.strip())
                if v < 1: raise ValueError
            except ValueError:
                await inter.response.send_message("❌ Enter a number ≥ 1.", ephemeral=True); return
            db_set_config(self.guild.id, give_receive_cooldown_h=v)
            await inter.response.send_message(
                f"✅ Members can receive at most **{v}** gift(s) per day.", ephemeral=True)
            await self._refresh(interaction)
        await interaction.response.send_modal(Modal1(
            "Gift Receive Limit", "Max gifts a member can receive per day",
            placeholder="1", default=str(config.get("give_receive_cooldown_h", 1)), callback=submit))

    @discord.ui.button(label="🔒 Min Balance to Give", style=discord.ButtonStyle.grey,   row=0)
    async def btn_gift_min_bal(self, interaction: discord.Interaction, btn):
        config = db_get_config(self.guild.id)
        async def submit(inter, value):
            try:
                v = int(value.strip())
                if v < 0: raise ValueError
            except ValueError:
                await inter.response.send_message("❌ Enter a non-negative number.", ephemeral=True); return
            db_set_config(self.guild.id, give_min_balance=v)
            await inter.response.send_message(
                f"✅ Minimum balance to use /give set to **{cur(db_get_config(self.guild.id), v)}**.", ephemeral=True)
            await self._refresh(interaction)
        await interaction.response.send_modal(Modal1(
            "Min Balance to Give", "Sender must hold at least this many gems",
            placeholder="1000", default=str(config.get("give_min_balance", 1000)), callback=submit))


class ConfigCurrencyMenu(_SubMenu):
    """Configure the server's currency: name and emoji."""

    def build_embed(self, config: dict) -> discord.Embed:
        name  = config.get("currency_name")  or "Gems"
        emoji = config.get("currency_emoji") or "💎"
        e = E("💎 Currency Settings", color=C_GOLD)
        e.description = (
            "Customise the currency used throughout the bot — in the shop, balances, "
            "leaderboard, quests, and every embed.\n\u200b"
        )
        e.add_field(name="Currency Name",  value=f"**{name}**",  inline=True)
        e.add_field(name="Currency Emoji", value=f"{emoji}", inline=True)
        e.add_field(name="Preview",        value=f"{emoji} **1 500 {name}**", inline=True)
        e.add_field(name="ℹ️ Emoji tip", value=(
            "You can use any Unicode emoji (💎 🪙 ⭐ 🔷…) "
            "**or** a custom server emoji — paste the full mention: `<:gemsbrawlstars:1234567890>`"
        ), inline=False)
        return e

    @discord.ui.button(label="Set Currency Name", style=discord.ButtonStyle.blurple, row=0)
    async def btn_name(self, interaction: discord.Interaction, btn):
        config = db_get_config(self.guild.id)
        async def submit(inter, value):
            v = value.strip()
            if not v:
                await inter.response.send_message("❌ Currency name cannot be empty.", ephemeral=True)
                return
            db_set_config(self.guild.id, currency_name=v)
            await inter.response.send_message(f"✅ Currency name set to **{v}**.", ephemeral=True)
            try:
                await self._refresh(interaction)
            except Exception:
                pass
        current_name = config.get("currency_name") or "Gems"
        await interaction.response.send_modal(Modal1(
            "Set Currency Name", "Name (e.g. Gems, Coins, Stars)",
            placeholder=current_name, default=current_name,
            callback=submit
        ))

    @discord.ui.button(label="Set Currency Emoji", style=discord.ButtonStyle.blurple, row=0)
    async def btn_emoji(self, interaction: discord.Interaction, btn):
        config = db_get_config(self.guild.id)
        async def submit(inter, value):
            v = value.strip()
            if not v:
                await inter.response.send_message("❌ Emoji cannot be empty.", ephemeral=True)
                return
            db_set_config(self.guild.id, currency_emoji=v)
            fresh_config = db_get_config(self.guild.id)
            await inter.response.send_message(
                f"✅ Currency emoji set to **{v}**.\n"
                f"Preview: {v} **500 {fresh_config.get('currency_name') or 'Gems'}**", ephemeral=True)
            try:
                await self._refresh(interaction)
            except Exception:
                pass
        await interaction.response.send_modal(Modal1(
            "Set Currency Emoji", "Unicode or custom server emoji",
            placeholder="💎  or  <:gemsbrawlstars:1234567890>",
            default=config.get("currency_emoji") or "💎",
            callback=submit
        ))

    @discord.ui.button(label="Reset to Default (💎 Gems)", style=discord.ButtonStyle.red, row=1)
    async def btn_reset(self, interaction: discord.Interaction, btn):
        db_set_config(self.guild.id, currency_name="Gems", currency_emoji="💎")
        await interaction.response.send_message("✅ Currency reset to **💎 Gems** (default).", ephemeral=True)
        await self._refresh(interaction)


class ConfigDailyQuestsMenu(_SubMenu):
    """Configure daily quests sent each day to members with a specific role."""

    def build_embed(self, config: dict) -> discord.Embed:
        _on   = lambda v: "✅ Enabled" if v else "❌ Disabled"
        _role = lambda rid: f"<@&{rid}>" if rid else "`Not set`"
        _ch   = lambda cid: f"<#{cid}>"  if cid else "`Not set`"
        e = E("🗓️ Daily Quests Settings", color=C_MAIN)
        e.add_field(name="Daily Quests",        value=_on(config.get("daily_quest_enabled", 0)),     inline=True)
        e.add_field(name="Quest Role",          value=_role(config.get("daily_quest_role_id")),       inline=True)
        e.add_field(name="DM Enabled",          value=_on(config.get("daily_quest_dm_enabled", 1)),  inline=True)
        xp = config.get("daily_quest_xp", 50)
        e.add_field(name="Reward per Quest",    value=f"**{xp}** {config.get('currency_emoji','💎')}", inline=True)
        e.add_field(name="💬 Chat Channel",     value=_ch(config.get("daily_quest_messages_channel_id")), inline=True)
        gems_owner_role = config.get("manager_role_id")
        e.add_field(
            name="👑 Gems Owner Role",
            value=f"<@&{gems_owner_role}>" if gems_owner_role else "`Not set`",
            inline=True,
        )
        e.add_field(name="\u200b", value=(
            "Members with the Quest Role receive 3 random daily quests each day.\n"
            "If DM Enabled, they receive a DM at UTC midnight with their quests.\n"
            "**Chat Channel** — channel counted for the 'send messages' quest (shown as clickable #channel).\n"
            "**Gems Owner Role** — members must ping this role when asking for a Gems bonus."
        ), inline=False)
        return e

    def _parse_role(self, value: str):
        raw = value.strip().lstrip("<@&").rstrip(">")
        return int(raw) if raw.isdigit() else None

    @discord.ui.button(label="Toggle Daily Quests", style=discord.ButtonStyle.blurple, row=0)
    async def btn_toggle(self, interaction: discord.Interaction, btn):
        config = db_get_config(self.guild.id)
        new_val = 0 if config.get("daily_quest_enabled", 0) else 1
        db_set_config(self.guild.id, daily_quest_enabled=new_val)
        await interaction.response.send_message(
            f"✅ Daily quests {'**enabled**' if new_val else '**disabled**'}.", ephemeral=True)
        await self._refresh(interaction)

    @discord.ui.button(label="Quest Role", style=discord.ButtonStyle.grey, row=0)
    async def btn_role(self, interaction: discord.Interaction, btn):
        config = db_get_config(self.guild.id)
        async def submit(inter, value):
            if not value.strip():
                db_set_config(self.guild.id, daily_quest_role_id=None)
                await inter.response.send_message("✅ Role removed — quests sent to all members.", ephemeral=True)
            else:
                rid = self._parse_role(value)
                if not rid:
                    await inter.response.send_message("❌ Invalid role.", ephemeral=True); return
                db_set_config(self.guild.id, daily_quest_role_id=rid)
                await inter.response.send_message(f"✅ Daily quests will target <@&{rid}>.", ephemeral=True)
            await self._refresh(interaction)
        await interaction.response.send_modal(Modal1(
            title="Daily Quest Role", label="Role mention or ID (empty = all members)",
            placeholder="@QuestMembers  or  1234567890",
            default=str(config.get("daily_quest_role_id") or ""),
            required=False, callback=submit))

    @discord.ui.button(label="Toggle DMs", style=discord.ButtonStyle.blurple, row=0)
    async def btn_dm_toggle(self, interaction: discord.Interaction, btn):
        config = db_get_config(self.guild.id)
        new_val = 0 if config.get("daily_quest_dm_enabled", 1) else 1
        db_set_config(self.guild.id, daily_quest_dm_enabled=new_val)
        await interaction.response.send_message(
            f"✅ Quest DMs {'**enabled**' if new_val else '**disabled**'}.", ephemeral=True)
        await self._refresh(interaction)

    @discord.ui.button(label="Reward XP", style=discord.ButtonStyle.grey, row=1)
    async def btn_xp(self, interaction: discord.Interaction, btn):
        config = db_get_config(self.guild.id)
        async def submit(inter, value):
            try:
                xp = int(value.strip())
                if xp < 0: raise ValueError
            except ValueError:
                await inter.response.send_message("❌ Must be a whole number ≥ 0.", ephemeral=True); return
            db_set_config(self.guild.id, daily_quest_xp=xp)
            await inter.response.send_message(
                f"✅ Daily quest reward set to **{xp} {config.get('currency_emoji','💎')}**.", ephemeral=True)
            await self._refresh(interaction)
        await interaction.response.send_modal(Modal1(
            title="Daily Quest Reward", label="Gems awarded per completed quest",
            placeholder="50",
            default=str(config.get("daily_quest_xp", 50)),
            callback=submit))

    @discord.ui.button(label="💬 Chat Channel", style=discord.ButtonStyle.blurple, row=2)
    async def btn_chat_ch(self, interaction: discord.Interaction, btn):
        """Set the channel that counts for the 'send messages' daily quest."""
        config = db_get_config(self.guild.id)
        async def submit(inter, value):
            if not value.strip():
                db_set_config(self.guild.id, daily_quest_messages_channel_id=None)
                await inter.response.send_message("✅ Chat channel removed.", ephemeral=True)
            else:
                ch_id = parse_channel_id(value)
                if not ch_id:
                    await inter.response.send_message("❌ Invalid channel.", ephemeral=True); return
                db_set_config(self.guild.id, daily_quest_messages_channel_id=ch_id)
                await inter.response.send_message(
                    f"✅ Chat channel set to <#{ch_id}>.\n"
                    "New 'send messages' quests will show this channel as a clickable link.",
                    ephemeral=True)
            await self._refresh(interaction)
        await interaction.response.send_modal(Modal1(
            title="Daily Quest Chat Channel",
            label="Channel mention or ID (empty = remove)",
            placeholder="#global  or  1234567890",
            default=str(config.get("daily_quest_messages_channel_id") or ""),
            required=False, callback=submit))

    @discord.ui.button(label="👑 Gems Owner Role", style=discord.ButtonStyle.blurple, row=2)
    async def btn_owner_uid(self, interaction: discord.Interaction, btn):
        """Set the role members must ping for the daily Gems bonus quest."""
        config = db_get_config(self.guild.id)
        async def submit(inter, value):
            if not value.strip():
                db_set_config(self.guild.id, manager_role_id=None)
                await inter.response.send_message(
                    "✅ Gems Owner role removed — the quest will show a generic role instruction.",
                    ephemeral=True)
            else:
                raw = value.strip().lstrip("<@&").rstrip(">")
                if not raw.isdigit():
                    await inter.response.send_message(
                        "❌ Mention the role or paste its ID.", ephemeral=True); return
                db_set_config(self.guild.id, manager_role_id=int(raw))
                await inter.response.send_message(
                    f"✅ Gems Owner role set to <@&{raw}>. Members must ping this role for their Gems bonus.",
                    ephemeral=True)
            await self._refresh(interaction)
        await interaction.response.send_modal(Modal1(
            title="Gems Owner Role",
            label="Role mention or ID (empty = remove)",
            placeholder="@Gems Owner  or  1234567890",
            default=str(config.get("manager_role_id") or ""),
            required=False, callback=submit))


class ConfigBoostAnnounceMenu(_SubMenu):
    """Configure boost announcements and server tag rewards."""

    def build_embed(self, config: dict) -> discord.Embed:
        _on   = lambda v: "✅ Enabled"   if v else "❌ Disabled"
        _role = lambda rid: f"<@&{rid}>" if rid else "`Not set`"
        _ch   = lambda cid: f"<#{cid}>"  if cid else "`Not set`"
        e = E("🚀 Boost Announce & 🏷️ Server Tag", color=C_ACHIEVE)
        boost_ch = config.get("boost_announce_channel_id") or config.get("notification_channel_id")
        e.add_field(name="📢 Announce Channel",
                    value=f"<#{boost_ch}>" if boost_ch else "`Notifications channel`", inline=True)
        e.add_field(name="📣 Mention Role",
                    value=_role(config.get("boost_announce_role_id")), inline=True)
        e.add_field(name="⏱️ Rate Limit", value="**1 per hour**", inline=True)
        e.add_field(name="🏷️ Server Tag Reward",
                    value=_on(config.get("server_tag_enabled", 0)), inline=True)
        e.add_field(name="🏷️ Tag Reward Amount",
                    value=f"**{cur(config, config.get('server_tag_xp', 100))}**", inline=True)
        e.add_field(name="\u200b", value=(
            "**Boost:** posts a thank-you when a member boosts. Rate-limited 1×/hour to avoid spam.\n"
            "**Server Tag:** awards gems when a member enables the server's clan tag.\n"
            "Members who already have the tag earn the reward when the bot restarts.\n"
            "Requires discord.py 2.4+."
        ), inline=False)
        return e

    def _parse_role(self, value: str):
        raw = value.strip().lstrip("<@&").rstrip(">")
        return int(raw) if raw.isdigit() else None

    def _parse_ch(self, value: str):
        raw = value.strip().lstrip("<#").rstrip(">")
        return int(raw) if raw.isdigit() else None

    @discord.ui.button(label="📢 Announce Channel", style=discord.ButtonStyle.blurple, row=0)
    async def btn_boost_channel(self, interaction: discord.Interaction, btn):
        config = db_get_config(self.guild.id)
        _view  = self
        async def submit(inter, value):
            if not value.strip():
                db_set_config(_view.guild.id, boost_announce_channel_id=None)
                await inter.response.send_message(
                    "✅ Boost announce channel cleared — will use Notifications channel.", ephemeral=True)
            else:
                cid = _view._parse_ch(value)
                if not cid:
                    await inter.response.send_message("❌ Invalid channel.", ephemeral=True); return
                db_set_config(_view.guild.id, boost_announce_channel_id=cid)
                await inter.response.send_message(
                    f"✅ Boost announcements will go to <#{cid}>.", ephemeral=True)
            # Refresh by directly editing the panel message
            try:
                cfg_new = db_get_config(_view.guild.id)
                if getattr(interaction, "message", None):
                    await interaction.message.edit(embed=_view.build_embed(cfg_new), view=_view)
            except Exception:
                pass
        try:
            await interaction.response.send_modal(Modal1(
                title="Boost Announce Channel",
                label="Channel mention or ID (empty = Notifications)",
                placeholder="#boosts  or  1234567890",
                default=str(config.get("boost_announce_channel_id") or ""),
                required=False, callback=submit))
        except Exception as e:
            print(f"[BoostChannel modal error] {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Could not open the modal. Please try again.", ephemeral=True)

    @discord.ui.button(label="📣 Boost Mention Role", style=discord.ButtonStyle.blurple, row=0)
    async def btn_boost_role(self, interaction: discord.Interaction, btn):
        config = db_get_config(self.guild.id)
        _view  = self
        async def submit(inter, value):
            if not value.strip():
                db_set_config(_view.guild.id, boost_announce_role_id=None)
                await inter.response.send_message(
                    "✅ Boost mention role removed — no role will be pinged.", ephemeral=True)
            else:
                rid = _view._parse_role(value)
                if not rid:
                    await inter.response.send_message("❌ Invalid role.", ephemeral=True); return
                db_set_config(_view.guild.id, boost_announce_role_id=rid)
                await inter.response.send_message(
                    f"✅ Boost announcements will mention <@&{rid}>.", ephemeral=True)
            # Refresh by directly editing the panel message
            try:
                cfg_new = db_get_config(_view.guild.id)
                if getattr(interaction, "message", None):
                    await interaction.message.edit(embed=_view.build_embed(cfg_new), view=_view)
            except Exception:
                pass
        try:
            await interaction.response.send_modal(Modal1(
                title="Boost Announce Role",
                label="Role mention or ID (empty = no ping)",
                placeholder="@Booster  or  1234567890",
                default=str(config.get("boost_announce_role_id") or ""),
                required=False, callback=submit))
        except Exception as e:
            print(f"[BoostRole modal error] {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Could not open the modal. Please try again.", ephemeral=True)

    @discord.ui.button(label="🏷️ Toggle Server Tag", style=discord.ButtonStyle.green, row=1)
    async def btn_tag_toggle(self, interaction: discord.Interaction, btn):
        config  = db_get_config(self.guild.id)
        new_val = 0 if config.get("server_tag_enabled", 0) else 1
        db_set_config(self.guild.id, server_tag_enabled=new_val)
        await interaction.response.defer()
        try:
            cfg_new = db_get_config(self.guild.id)
            if getattr(interaction, "message", None):
                await interaction.message.edit(embed=self.build_embed(cfg_new), view=self)
        except Exception:
            pass
        await interaction.followup.send(
            f"✅ Server tag reward {'enabled' if new_val else 'disabled'}.", ephemeral=True)

    @discord.ui.button(label="🏷️ Tag Reward Amount", style=discord.ButtonStyle.blurple, row=1)
    async def btn_tag_xp(self, interaction: discord.Interaction, btn):
        config = db_get_config(self.guild.id)
        _view  = self
        async def submit(inter, value):
            try:
                xp = int(value)
                if xp < 0: raise ValueError
            except ValueError:
                await inter.response.send_message("❌ Enter a non-negative number.", ephemeral=True); return
            db_set_config(_view.guild.id, server_tag_xp=xp)
            cfg2 = db_get_config(_view.guild.id)
            await inter.response.send_message(
                f"✅ Server tag reward set to **{cur(cfg2, xp)}**.", ephemeral=True)
            try:
                cfg_new = db_get_config(_view.guild.id)
                if getattr(interaction, "message", None):
                    await interaction.message.edit(embed=_view.build_embed(cfg_new), view=_view)
            except Exception:
                pass
        await interaction.response.send_modal(Modal1(
            "Server Tag Reward", "Gems awarded for enabling server tag",
            placeholder="100", default=str(config.get("server_tag_xp", 100)), callback=submit))

    # ← Back is inherited from _SubMenu — no duplicate needed


# ══════════════════════════════════════════════════════════════
#  REVIVE PING CONFIG SUBMENU
# ══════════════════════════════════════════════════════════════

class ConfigRevivePingMenu(_SubMenu):
    """Legacy revive configuration view kept for old Discord sessions."""

    def build_embed(self, config: dict) -> discord.Embed:
        _on   = lambda v: "✅ Enabled" if v else "❌ Disabled"
        _role = lambda rid: f"<@&{rid}>" if rid else "`Not set`"
        channels_raw = config.get("revive_ping_channels") or "[]"
        try:
            ch_ids = json.loads(channels_raw)
        except Exception:
            ch_ids = []
        ch_list = ", ".join(f"<#{c}>" for c in ch_ids) if ch_ids else "`None configured`"
        e = discord.Embed(title="🔔 Ping Roles Settings", color=0x3498DB)
        e.add_field(name="Daily Posting", value=_on(config.get("revive_ping_enabled", 0)), inline=True)
        e.add_field(name="Revive Role",   value=_role(config.get("revive_ping_role_id")),   inline=True)
        e.add_field(name="Drops Role",    value=_role(config.get("drops_ping_role_id")),    inline=True)
        e.add_field(name="Channels",      value=ch_list,                                    inline=False)
        e.add_field(name="\u200b", value=(
            "The bot can post a clean opt-in message in one of the configured channels.\n"
            "Members can independently get the **Revive** role or the **Drops** role.\n\n"
            "• **Revive Role** — pings members when the chat needs activity\n"
            "• **Drops Role** — pings members when skin or item links are posted\n"
            "• **Channels** — pool of channels from which one is picked each day\n"
            "• Add/remove channels one at a time with the buttons below."
        ), inline=False)
        return e

    def _parse_role(self, value: str):
        raw = value.strip().lstrip("<@&").rstrip(">")
        return int(raw) if raw.isdigit() else None

    def _get_channels(self, config: dict) -> list:
        try:
            return json.loads(config.get("revive_ping_channels") or "[]")
        except Exception:
            return []

    @discord.ui.button(label="Daily Posting", style=discord.ButtonStyle.blurple, row=0)
    async def btn_toggle(self, interaction: discord.Interaction, btn):
        config  = db_get_config(self.guild.id)
        new_val = 0 if config.get("revive_ping_enabled", 0) else 1
        db_set_config(self.guild.id, revive_ping_enabled=new_val)
        await interaction.response.send_message(
            f"✅ Revive ping {'**enabled**' if new_val else '**disabled**'}.", ephemeral=True)
        await self._refresh(interaction)

    @discord.ui.button(label="🔔 Revive Role", style=discord.ButtonStyle.blurple, row=0)
    async def btn_role(self, interaction: discord.Interaction, btn):
        config = db_get_config(self.guild.id)
        async def submit(inter, value):
            if not value.strip():
                db_set_config(self.guild.id, revive_ping_role_id=None)
                await inter.response.send_message("✅ Revive ping role removed.", ephemeral=True)
            else:
                rid = self._parse_role(value)
                if not rid:
                    await inter.response.send_message("❌ Invalid role.", ephemeral=True); return
                db_set_config(self.guild.id, revive_ping_role_id=rid)
                await inter.response.send_message(
                    f"✅ Revive ping role set to <@&{rid}>.\n"
                    "Members will receive/lose this role when clicking the daily button.",
                    ephemeral=True)
            await self._refresh(interaction)
        await interaction.response.send_modal(Modal1(
            title="Revive Role",
            label="Role mention or ID (empty = remove)",
            placeholder="@revive  or  1234567890",
            default=str(config.get("revive_ping_role_id") or ""),
            required=False, callback=submit))

    @discord.ui.button(label="🎁 Drops Role", style=discord.ButtonStyle.blurple, row=0)
    async def btn_drops_role(self, interaction: discord.Interaction, btn):
        config = db_get_config(self.guild.id)
        async def submit(inter, value):
            role_id = parse_role_id(value) if value.strip() else None
            if value.strip() and not role_id:
                await inter.response.send_message("❌ Invalid role.", ephemeral=True)
                return
            db_set_config(self.guild.id, drops_ping_role_id=role_id)
            await inter.response.send_message(
                f"✅ Drops role {'set to <@&' + str(role_id) + '>' if role_id else 'removed'}.",
                ephemeral=True)
            await self._refresh(interaction)
        await interaction.response.send_modal(Modal1(
            title="Drops Role",
            label="Role mention or ID (empty = remove)",
            placeholder="@drops  or  1234567890",
            default=str(config.get("drops_ping_role_id") or ""),
            required=False, callback=submit))

    @discord.ui.button(label="📣 Send Revive Message", style=discord.ButtonStyle.green, row=1)
    async def btn_send_revive(self, interaction: discord.Interaction, btn):
        await self._send_manual_ping(interaction, "revive")

    @discord.ui.button(label="🎁 Send Drops Message", style=discord.ButtonStyle.green, row=1)
    async def btn_send_drops(self, interaction: discord.Interaction, btn):
        await self._send_manual_ping(interaction, "drops")

    async def _send_manual_ping(self, interaction: discord.Interaction, kind: str):
        config = db_get_config(self.guild.id)
        role_key = "revive_ping_role_id" if kind == "revive" else "drops_ping_role_id"
        if not config.get(role_key):
            await interaction.response.send_message(
                f"❌ Configure the {'Revive' if kind == 'revive' else 'Drops'} role first.",
                ephemeral=True)
            return

        async def submit(inter, value):
            channel_id = parse_channel_id(value)
            channel = self.guild.get_channel(channel_id) if channel_id else None
            if not channel or not hasattr(channel, "send"):
                await inter.response.send_message("❌ Invalid text channel.", ephemeral=True)
                return
            sent = await send_ping_role_message(channel, kind, self.guild.id)
            if sent:
                await inter.response.send_message(
                    f"✅ {'Revive' if kind == 'revive' else 'Drops'} message sent in {channel.mention}.",
                    ephemeral=True)
            else:
                await inter.response.send_message(
                    "❌ The message could not be sent. Check the role and channel permissions.",
                    ephemeral=True)
            await self._refresh(interaction)

        await interaction.response.send_modal(Modal1(
            title=f"Send {'Revive' if kind == 'revive' else 'Drops'} Message",
            label="Channel mention or ID",
            placeholder="#general  or  1234567890",
            callback=submit))

    @discord.ui.button(label="➕ Add Channel", style=discord.ButtonStyle.green, row=1)
    async def btn_add_ch(self, interaction: discord.Interaction, btn):
        config = db_get_config(self.guild.id)
        async def submit(inter, value):
            ch_id = parse_channel_id(value)
            if not ch_id:
                await inter.response.send_message("❌ Invalid channel.", ephemeral=True); return
            ch_ids = self._get_channels(config)
            if ch_id in ch_ids:
                await inter.response.send_message("⚠️ That channel is already in the list.", ephemeral=True); return
            ch_ids.append(ch_id)
            db_set_config(self.guild.id, revive_ping_channels=json.dumps(ch_ids))
            await inter.response.send_message(f"✅ <#{ch_id}> added to revive ping channels.", ephemeral=True)
            await self._refresh(interaction)
        await interaction.response.send_modal(Modal1(
            title="Add Revive Ping Channel",
            label="Channel mention or ID",
            placeholder="#general  or  1234567890",
            callback=submit))

    @discord.ui.button(label="➖ Remove Channel", style=discord.ButtonStyle.red, row=1)
    async def btn_remove_ch(self, interaction: discord.Interaction, btn):
        config = db_get_config(self.guild.id)
        async def submit(inter, value):
            ch_id = parse_channel_id(value)
            if not ch_id:
                await inter.response.send_message("❌ Invalid channel.", ephemeral=True); return
            ch_ids = self._get_channels(config)
            if ch_id not in ch_ids:
                await inter.response.send_message("⚠️ That channel is not in the list.", ephemeral=True); return
            ch_ids.remove(ch_id)
            db_set_config(self.guild.id, revive_ping_channels=json.dumps(ch_ids))
            await inter.response.send_message(f"✅ <#{ch_id}> removed from revive ping channels.", ephemeral=True)
            await self._refresh(interaction)
        await interaction.response.send_modal(Modal1(
            title="Remove Revive Ping Channel",
            label="Channel mention or ID to remove",
            placeholder="#general  or  1234567890",
            callback=submit))

    # ← Back is inherited from _SubMenu


# ══════════════════════════════════════════════════════════════
#  REVIVE PING BUTTON VIEW (posted daily in channels)
# ══════════════════════════════════════════════════════════════

class RevivePingView(discord.ui.View):
    """Persistent role opt-in view used by both manual and daily messages."""

    def __init__(self, guild_id: int, role_id: int, mode: str = "both"):
        super().__init__(timeout=None)  # Persistent — survives bot restarts
        self.guild_id = guild_id
        self.role_id  = role_id
        self.mode = mode
        if mode in {"revive", "drops"}:
            disabled_id = "drops_ping_get" if mode == "revive" else "revive_ping_toggle"
            for child in self.children:
                if getattr(child, "custom_id", None) == disabled_id:
                    child.disabled = True

    @discord.ui.button(label="🔔 Get Revive Role", style=discord.ButtonStyle.green,
                       custom_id="revive_ping_toggle")
    async def btn_revive(self, interaction: discord.Interaction, btn):
        await self._toggle_role(interaction, "revive")

    @discord.ui.button(label="🎁 Get Drops Role", style=discord.ButtonStyle.blurple,
                       custom_id="drops_ping_get")
    async def btn_drops(self, interaction: discord.Interaction, btn):
        await self._toggle_role(interaction, "drops")

    async def _toggle_role(self, interaction: discord.Interaction, kind: str):
        if not interaction.guild:
            await interaction.response.send_message("❌ Server only.", ephemeral=True)
            return
        config = db_get_config(interaction.guild.id)
        role_key = "revive_ping_role_id" if kind == "revive" else "drops_ping_role_id"
        role_name = "Revive" if kind == "revive" else "Drops"
        role_id = config.get(role_key)
        if not role_id:
            await interaction.response.send_message(
                f"❌ The {role_name} role is not configured. Ask an admin to set it in `/config → 🔔 Community`.",
                ephemeral=True)
            return
        role = interaction.guild.get_role(role_id)
        if not role:
            await interaction.response.send_message(
                f"❌ The {role_name} role no longer exists. Ask an admin to reconfigure it.",
                ephemeral=True)
            return
        member = interaction.user
        if role in member.roles:
            try:
                await member.remove_roles(role, reason="Revive ping opt-out via button")
                await interaction.response.send_message(
                    f"🔕 You have been **removed** from {role.mention}.",
                    ephemeral=True)
            except discord.Forbidden:
                await interaction.response.send_message(
                    "❌ I don't have permission to remove that role. Ask an admin.", ephemeral=True)
        else:
            try:
                await member.add_roles(role, reason="Revive ping opt-in via button")
                await interaction.response.send_message(
                    f"✅ You have been **added** to {role.mention}.",
                    ephemeral=True)
            except discord.Forbidden:
                await interaction.response.send_message(
                    "❌ I don't have permission to assign that role. Ask an admin.", ephemeral=True)


class ConfigXPMenu(_SubMenu):
    def build_embed(self, config: dict) -> discord.Embed:
        e = E("💰 Rewards Settings", color=C_GOLD)
        e.add_field(name="⏰ Share Window",        value=f"**{config.get('share_window_min', 20)} min**",        inline=True)
        e.add_field(name="✅ Reaction Emoji",      value=config.get("reaction_emoji", "✅"),                      inline=True)
        e.add_field(name="❌ Cancel Emoji",        value=config.get("cancel_emoji", "❌"),                        inline=True)
        e.add_field(name="🎬 Share Reward",        value=f"**{cur(config, config.get('share_xp', 100))}**",      inline=True)
        e.add_field(name="✅ Reaction Bonus",      value=f"**{cur(config, config.get('reaction_xp', 50))}**",    inline=True)
        e.add_field(name="⏱️ Reaction Cooldown",  value=f"**{config.get('reaction_cooldown_h', 1)}h**",          inline=True)
        e.add_field(name="📨 Invite Reward",       value=f"**{cur(config, config.get('invite_xp', 25))}**",      inline=True)
        e.set_footer(text="🎬 Share Reward = gems per video share  ·  ✅ Reaction Bonus = gems awarded by managers reacting")
        return e

    @discord.ui.button(label="Share Window",     style=discord.ButtonStyle.blurple, row=0)
    async def btn_window(self, interaction, btn):
        config = db_get_config(self.guild.id)
        async def submit(inter, value):
            try:
                mins = int(value)
                if mins <= 0: raise ValueError
            except ValueError:
                await inter.response.send_message("❌ Enter a positive number of minutes.", ephemeral=True)
                return
            db_set_config(self.guild.id, share_window_min=mins)
            await inter.response.send_message(f"✅ Share window set to **{mins} min**", ephemeral=True)
            await self._refresh(interaction)
        await interaction.response.send_modal(Modal1("Share Window", "Minutes to share after video",
            placeholder="20", default=str(config.get("share_window_min", 20)), callback=submit))

    @discord.ui.button(label="Reaction Emoji",   style=discord.ButtonStyle.blurple, row=0)
    async def btn_emoji(self, interaction, btn):
        config = db_get_config(self.guild.id)
        async def submit(inter, value):
            db_set_config(self.guild.id, reaction_emoji=value.strip())
            await inter.response.send_message(f"✅ Reaction emoji set to **{value.strip()}**", ephemeral=True)
            await self._refresh(interaction)
        await interaction.response.send_modal(Modal1("Reaction Emoji", "Standard or custom emoji",
            placeholder="✅  or  <:custom:1234567890>",
            default=config.get("reaction_emoji", "✅"), callback=submit))

    @discord.ui.button(label="🎬 Share Reward",      style=discord.ButtonStyle.blurple, row=0)
    async def btn_share_xp(self, interaction, btn):
        config = db_get_config(self.guild.id)
        async def submit(inter, value):
            try:
                amt = int(value)
                if amt <= 0: raise ValueError
            except ValueError:
                await inter.response.send_message("❌ Enter a positive number.", ephemeral=True)
                return
            db_set_config(self.guild.id, share_xp=amt)
            cfg2 = db_get_config(self.guild.id)
            await inter.response.send_message(f"✅ Share reward set to **{cur(cfg2, amt)}** per video.", ephemeral=True)
            await self._refresh(interaction)
        c_name = config.get("currency_name") or "Gems"
        await interaction.response.send_modal(Modal1("Share Reward",
            f"{c_name} awarded per video share",
            placeholder="100", default=str(config.get("share_xp", 100)), callback=submit))

    @discord.ui.button(label="✅ Reaction Bonus",    style=discord.ButtonStyle.blurple, row=1)
    async def btn_react_xp(self, interaction, btn):
        config = db_get_config(self.guild.id)
        async def submit(inter, value):
            try:
                amt = int(value)
                if amt <= 0: raise ValueError
            except ValueError:
                await inter.response.send_message("❌ Enter a positive number.", ephemeral=True)
                return
            db_set_config(self.guild.id, reaction_xp=amt)
            cfg2 = db_get_config(self.guild.id)
            await inter.response.send_message(f"✅ Reaction bonus set to **{cur(cfg2, amt)}**.", ephemeral=True)
            await self._refresh(interaction)
        c_name = config.get("currency_name") or "Gems"
        await interaction.response.send_modal(Modal1("Reaction Bonus",
            f"{c_name} awarded when a manager reacts with the reaction emoji",
            placeholder="50", default=str(config.get("reaction_xp", 50)), callback=submit))

    @discord.ui.button(label="Reaction Cooldown", style=discord.ButtonStyle.grey, row=1)
    async def btn_cooldown(self, interaction, btn):
        config = db_get_config(self.guild.id)
        async def submit(inter, value):
            try:
                hours = int(value)
                if hours < 0: raise ValueError
            except ValueError:
                await inter.response.send_message("❌ Enter hours (0 = no cooldown).", ephemeral=True)
                return
            db_set_config(self.guild.id, reaction_cooldown_h=hours)
            await inter.response.send_message(f"✅ Cooldown set to **{hours}h**", ephemeral=True)
            await self._refresh(interaction)
        await interaction.response.send_modal(Modal1("Reaction Cooldown", "Hours between reaction rewards (0 = none)",
            placeholder="1", default=str(config.get("reaction_cooldown_h", 1)), callback=submit))

    @discord.ui.button(label="Invite Reward",    style=discord.ButtonStyle.grey, row=1)
    async def btn_invite_xp(self, interaction, btn):
        config = db_get_config(self.guild.id)
        async def submit(inter, value):
            try:
                amt = int(value)
                if amt < 0: raise ValueError
            except ValueError:
                await inter.response.send_message("❌ Enter a non-negative number.", ephemeral=True)
                return
            db_set_config(self.guild.id, invite_xp=amt)
            cfg2 = db_get_config(self.guild.id)
            await inter.response.send_message(f"✅ Invite reward set to **{cur(cfg2, amt)}**", ephemeral=True)
            await self._refresh(interaction)
        await interaction.response.send_modal(Modal1("Invite Reward", "Reward awarded per successful invite",
            placeholder="25", default=str(config.get("invite_xp", 25)), callback=submit))

    @discord.ui.button(label="Cancel Emoji",     style=discord.ButtonStyle.grey, row=1)
    async def btn_cancel_emoji(self, interaction, btn):
        config = db_get_config(self.guild.id)
        async def submit(inter, value):
            v = value.strip()
            if not v:
                await inter.response.send_message("❌ Cancel emoji cannot be empty.", ephemeral=True)
                return
            db_set_config(self.guild.id, cancel_emoji=v)
            await inter.response.send_message(
                f"✅ Cancel emoji set to **{v}**. React with this on a member's message to revoke their gem award.",
                ephemeral=True)
            await self._refresh(interaction)
        await interaction.response.send_modal(Modal1(
            "Set Cancel Emoji", "Emoji to revoke a gem award (default ❌)",
            placeholder="❌  or  <:reject:1234567890>",
            default=config.get("cancel_emoji") or "❌",
            callback=submit
        ))

class ConfigStreakMenu(_SubMenu):
    def build_embed(self, config: dict) -> discord.Embed:
        e = E("🔥 Streak Settings", color=C_STREAK)
        e.add_field(name="Enabled",           value=_bool(config.get("streak_enabled", 1)),         inline=True)
        e.add_field(name="Bonus per Level",   value=f"**+{cur(config, config.get('streak_xp_bonus', 2))}**",       inline=True)
        e.add_field(name="Bonus Cap",         value=f"**+{cur(config, config.get('streak_xp_cap', 30))} max**",    inline=True)
        e.add_field(name="Reset on Miss",     value=_bool(config.get("streak_reset_on_miss", 1)),    inline=True)
        e.add_field(name="\u200b", value=(
            "The streak increases by 1 for each consecutive video supported.\n"
            "**Streak Bonus** = min(streak × bonus, cap)  — added on top of the share reward.\n"
            "The streak is displayed in the member's nickname: **username 🔥N**\n"
            "⚠️ The bot needs **Manage Nicknames** and must be **above the member** in role hierarchy."
        ), inline=False)
        return e

    @discord.ui.button(label="Toggle Streak",   style=discord.ButtonStyle.blurple, row=0)
    async def btn_toggle(self, interaction, btn):
        config = db_get_config(self.guild.id)
        new_val = 0 if config.get("streak_enabled", 1) else 1
        db_set_config(self.guild.id, streak_enabled=new_val)
        await interaction.response.edit_message(embed=self.build_embed(db_get_config(self.guild.id)), view=self)

    @discord.ui.button(label="Bonus per Level",  style=discord.ButtonStyle.blurple, row=0)
    async def btn_bonus(self, interaction, btn):
        config = db_get_config(self.guild.id)
        async def submit(inter, value):
            try:
                amt = int(value)
                if amt < 0: raise ValueError
            except ValueError:
                await inter.response.send_message("❌ Enter a non-negative number.", ephemeral=True)
                return
            db_set_config(self.guild.id, streak_xp_bonus=amt)
            cfg2 = db_get_config(self.guild.id)
            await inter.response.send_message(f"✅ Streak bonus set to **+{cur(cfg2, amt)} per level**", ephemeral=True)
            await self._refresh(interaction)
        await interaction.response.send_modal(Modal1("Streak Bonus per Level", "Amount added per streak level",
            placeholder="2", default=str(config.get("streak_xp_bonus", 2)), callback=submit))

    @discord.ui.button(label="Bonus Cap",        style=discord.ButtonStyle.blurple, row=0)
    async def btn_cap(self, interaction, btn):
        config = db_get_config(self.guild.id)
        async def submit(inter, value):
            try:
                amt = int(value)
                if amt < 0: raise ValueError
            except ValueError:
                await inter.response.send_message("❌ Enter a non-negative number.", ephemeral=True)
                return
            db_set_config(self.guild.id, streak_xp_cap=amt)
            cfg2 = db_get_config(self.guild.id)
            await inter.response.send_message(f"✅ Streak bonus cap set to **+{cur(cfg2, amt)}**", ephemeral=True)
            await self._refresh(interaction)
        await interaction.response.send_modal(Modal1("Streak Bonus Cap", "Maximum streak bonus",
            placeholder="30", default=str(config.get("streak_xp_cap", 30)), callback=submit))

    @discord.ui.button(label="Toggle Reset on Miss", style=discord.ButtonStyle.grey, row=1)
    async def btn_reset(self, interaction, btn):
        config = db_get_config(self.guild.id)
        new_val = 0 if config.get("streak_reset_on_miss", 1) else 1
        db_set_config(self.guild.id, streak_reset_on_miss=new_val)
        await interaction.response.edit_message(embed=self.build_embed(db_get_config(self.guild.id)), view=self)

class LegacyConfigShopMenu(_SubMenu):
    def build_embed(self, config: dict) -> discord.Embed:
        items = db_get_shop_items(self.guild.id)
        c_name = config.get("currency_name") or "Gems"
        e = E("🛒 Shop Settings", color=C_GOLD)
        if not items:
            e.description = f"The shop is empty. Add items that members can buy with {c_name}."
        else:
            e.description = f"**{len(items)} item(s)** in the shop.\n\u200b"
            for item in items[:8]:
                tags = []
                if item.get("is_temporary"): tags.append(f"⏳{item['duration_days']}d")
                if item.get("requires_text"): tags.append("📝")
                if item.get("image_url"): tags.append("🖼️")
                tag_str = "  " + " ".join(tags) if tags else ""
                e.add_field(
                    name=f"{item['name']}{tag_str}",
                    value=f"**{cur(config, item['price'])}** — ID `{item['id']}`",
                    inline=True
                )
            if len(items) > 8:
                e.add_field(name="…", value=f"and {len(items)-8} more — use 📋 View All", inline=False)
        e.set_footer(text="🖼️ = has image  ⏳ = temporary  📝 = requires text input")
        return e

    @discord.ui.button(label="➕ Add Item", style=discord.ButtonStyle.green, row=0)
    async def btn_add(self, interaction: discord.Interaction, btn):
        guild_ref = self.guild
        config = db_get_config(guild_ref.id)
        c_name = config.get("currency_name") or "Gems"
        async def submit(inter, v_name, v_price, v_stock, v_temp, v_text):
            try:
                price = int(v_price)
                if price <= 0: raise ValueError
            except ValueError:
                await inter.response.send_message("❌ Price must be a positive number.", ephemeral=True)
                return
            try:
                days = int(v_temp)
                if days < 0: raise ValueError
            except ValueError:
                await inter.response.send_message("❌ Duration must be 0 (permanent) or a positive number of days.", ephemeral=True)
                return
            try:
                stock_val = int(v_stock.strip()) if v_stock.strip() else 0
                if stock_val < 0: raise ValueError
            except ValueError:
                await inter.response.send_message("❌ Stock must be 0 (unlimited) or a positive number.", ephemeral=True)
                return
            is_temp       = 1 if days > 0 else 0
            dur_days      = days if days > 0 else None
            requires_text = 1 if v_text.strip() else 0
            text_label    = v_text.strip() or None
            stock_db      = stock_val if stock_val > 0 else None  # None = unlimited
            item_id = db_add_shop_item(guild_ref.id, v_name.strip(), price, None,
                                       is_temp, dur_days, 1, requires_text, text_label,
                                       stock=stock_db)
            tags = []
            if is_temp:        tags.append(f"⏳ {days} days")
            if requires_text:  tags.append(f"📝 requires text")
            if stock_db:       tags.append(f"📦 {stock_val} in stock")
            await inter.response.send_message(
                f"✅ Added **{v_name.strip()}** — **{cur(config, price)}** (ID: `{item_id}`)\n"
                f"💡 Set an image via **🖼️ Set Image URL**."
                + ("\n" + "  ".join(tags) if tags else "\nPermanent · Unlimited stock"),
                ephemeral=True
            )
            await self._refresh(interaction)
        await interaction.response.send_modal(Modal5("Add Shop Item", currency_label=c_name, callback=submit))

    @discord.ui.button(label="🖼️ Set Image URL", style=discord.ButtonStyle.blurple, row=1)
    async def btn_set_image(self, interaction: discord.Interaction, btn):
        """Set or replace the image URL for an existing shop item."""
        items = db_get_shop_items(self.guild.id)
        if not items:
            await interaction.response.send_message("❌ Shop is empty.", ephemeral=True)
            return
        config_now = db_get_config(self.guild.id)
        options = [
            discord.SelectOption(
                label=f"{item['name'][:70]}  —  {cur(config_now, item['price'])}",
                description="🖼️ has image" if item.get("image_url") else "No image yet",
                value=str(item["id"])
            )
            for item in items[:25]
        ]
        sel       = discord.ui.Select(placeholder="Choose item to add/replace image URL", options=options)
        tmp_view  = discord.ui.View(timeout=120)
        guild_ref = self.guild
        panel_msg = interaction   # the button interaction (has .message = the panel)
        author_id = self.author_id
        view_ref  = self
        all_items = items
        async def on_select(inter2: discord.Interaction):
            if inter2.user.id != author_id:
                await inter2.response.send_message("❌ Not your panel.", ephemeral=True)
                return
            item_id   = int(sel.values[0])
            chosen    = next((i for i in all_items if i["id"] == item_id), None)
            item_name = (chosen["name"] if chosen else "item")
            # Title must be ≤ 45 chars; keep up to 28 chars of item name (12 prefix + 28 = 40)
            modal_title = f"Set Image — {item_name[:28]}"
            async def url_submit(inter3: discord.Interaction, value: str):
                v = value.strip()
                if not v:
                    conn = get_db()
                    conn.execute("UPDATE shop_items SET image_url=NULL WHERE id=? AND guild_id=?",
                                 (item_id, guild_ref.id))
                    conn.commit(); conn.close()
                    await inter3.response.send_message(f"✅ Image removed from **{item_name}**.", ephemeral=True)
                else:
                    db_update_shop_image(item_id, guild_ref.id, v)
                    await inter3.response.send_message(f"✅ Image set for **{item_name}**!", ephemeral=True)
                # Refresh the panel via the original button's message
                try:
                    cfg_new = db_get_config(guild_ref.id)
                    if getattr(panel_msg, "message", None):
                        await panel_msg.message.edit(embed=view_ref.build_embed(cfg_new), view=view_ref)
                except Exception:
                    pass
            try:
                await inter2.response.send_modal(Modal1(
                    modal_title,
                    "Image URL (empty = remove)",
                    placeholder="https://i.imgur.com/xxxx.png",
                    default=chosen.get("image_url") or "" if chosen else "",
                    required=False, callback=url_submit
                ))
            except Exception as e:
                print(f"[SetImage modal error] {e}")
                if not inter2.response.is_done():
                    await inter2.response.send_message("❌ Could not open modal. Please try again.", ephemeral=True)
        sel.callback = on_select
        tmp_view.add_item(sel)
        await interaction.response.send_message(
            "🖼️ Choose an item to set its image URL.\n"
            "💡 Tip: upload your image to [imgur.com](https://imgur.com) or any image host and paste the direct link.",
            view=tmp_view, ephemeral=True
        )

    @discord.ui.button(label="🤝 Set Provider", style=discord.ButtonStyle.grey, row=2)
    async def btn_set_provider(self, interaction: discord.Interaction, btn):
        """Set or clear the 'Provided by' credit shown on a shop item."""
        items = db_get_shop_items(self.guild.id)
        if not items:
            await interaction.response.send_message("❌ Shop is empty.", ephemeral=True)
            return
        config_now = db_get_config(self.guild.id)
        options = [
            discord.SelectOption(
                label=f"{item['name'][:70]}  —  {cur(config_now, item['price'])}",
                description=f"Provider: {item['provided_by']}" if item.get("provided_by") else "No provider set",
                value=str(item["id"])
            )
            for item in items[:25]
        ]
        sel       = discord.ui.Select(placeholder="Choose item to set provider", options=options)
        tmp_view  = discord.ui.View(timeout=120)
        guild_ref = self.guild
        panel_msg = interaction
        author_id = self.author_id
        view_ref  = self
        all_items = items
        async def on_select(inter2: discord.Interaction):
            if inter2.user.id != author_id:
                await inter2.response.send_message("❌ Not your panel.", ephemeral=True)
                return
            item_id   = int(sel.values[0])
            chosen    = next((i for i in all_items if i["id"] == item_id), None)
            item_name = chosen["name"] if chosen else "item"
            async def prov_submit(inter3: discord.Interaction, value: str):
                v = value.strip()
                conn = get_db()
                conn.execute("UPDATE shop_items SET provided_by=? WHERE id=? AND guild_id=?",
                             (v or None, item_id, guild_ref.id))
                conn.commit(); conn.close()
                if v:
                    await inter3.response.send_message(
                        f"✅ **{item_name}** will show \"Provided by {v}\".", ephemeral=True)
                else:
                    await inter3.response.send_message(
                        f"✅ Provider credit removed from **{item_name}**.", ephemeral=True)
                try:
                    cfg_new = db_get_config(guild_ref.id)
                    if getattr(panel_msg, "message", None):
                        await panel_msg.message.edit(embed=view_ref.build_embed(cfg_new), view=view_ref)
                except Exception:
                    pass
            await inter2.response.send_modal(Modal1(
                f"Set Provider — {item_name[:26]}",
                "Provided by (empty = remove)",
                placeholder="@username  or  Server Name",
                default=chosen.get("provided_by") or "" if chosen else "",
                required=False, callback=prov_submit
            ))
        sel.callback = on_select
        tmp_view.add_item(sel)
        await interaction.response.send_message(
            "🤝 Choose an item to set its **Provided by** credit.\n"
            "Enter a name or `@mention`. Leave blank to remove.",
            view=tmp_view, ephemeral=True
        )

    @discord.ui.button(label="✏️ Edit Expiry", style=discord.ButtonStyle.blurple, row=1)
    async def btn_edit_expiry(self, interaction: discord.Interaction, btn):
        """Change the duration (days) of a temporary shop item, or make it permanent."""
        all_items = db_get_shop_items(self.guild.id)
        if not all_items:
            await interaction.response.send_message("❌ Shop is empty.", ephemeral=True)
            return
        config = db_get_config(self.guild.id)
        options = [
            discord.SelectOption(
                label=f"{item['name'][:70]}  —  {cur(config, item['price'])}",
                description=f"⏳ {item['duration_days']}d" if item.get("is_temporary") else "Permanent",
                value=str(item["id"])
            )
            for item in all_items[:25]
        ]
        view = discord.ui.View(timeout=60)
        sel = discord.ui.Select(placeholder="Choose item to edit expiry", options=options)
        guild_ref = self.guild
        parent = interaction
        all_items_ref = all_items
        async def on_select(inter2):
            if inter2.user.id != self.author_id:
                await inter2.response.send_message("❌ Not your panel.", ephemeral=True)
                return
            item_id = int(sel.values[0])
            chosen = next((i for i in all_items_ref if i["id"] == item_id), None)
            item_name = chosen["name"] if chosen else "item"
            current_days = str(chosen.get("duration_days") or 0) if chosen else "0"
            async def expiry_submit(inter3, value):
                try:
                    days = int(value.strip())
                    if days < 0: raise ValueError
                except ValueError:
                    await inter3.response.send_message("❌ Enter 0 (permanent) or a positive number of days.", ephemeral=True)
                    return
                is_temp = 1 if days > 0 else 0
                dur = days if days > 0 else None
                conn = get_db()
                conn.execute(
                    "UPDATE shop_items SET is_temporary=?, duration_days=? WHERE id=? AND guild_id=?",
                    (is_temp, dur, item_id, guild_ref.id)
                )
                conn.commit()
                conn.close()
                if days == 0:
                    await inter3.response.send_message(f"✅ **{item_name}** is now **permanent**.", ephemeral=True)
                else:
                    await inter3.response.send_message(f"✅ **{item_name}** expiry set to **{days} days**.", ephemeral=True)
                await self._refresh(parent)
            await inter2.response.send_modal(Modal1(
                f"Edit Expiry — {item_name[:40]}",
                "Duration in days (0 = permanent)",
                placeholder="0 or 30",
                default=current_days,
                callback=expiry_submit
            ))
        sel.callback = on_select
        view.add_item(sel)
        await interaction.response.send_message(
            "✏️ Choose an item to edit its expiry duration:",
            view=view, ephemeral=True
        )

    @discord.ui.button(label="🔑 Add Rewards",  style=discord.ButtonStyle.green,  row=2)
    async def btn_add_rewards(self, interaction: discord.Interaction, btn):
        """Pre-load reward links/codes into a shop item for automatic distribution on purchase."""
        all_items = db_get_shop_items(self.guild.id)
        if not all_items:
            await interaction.response.send_message("❌ Shop is empty.", ephemeral=True)
            return
        config = db_get_config(self.guild.id)
        options = [
            discord.SelectOption(
                label=f"{item['name'][:70]}  —  {cur(config, item['price'])}",
                description=f"🔑 {db_count_available_rewards(item['id'], self.guild.id)} available",
                value=str(item["id"])
            )
            for item in all_items[:25]
        ]
        view = discord.ui.View(timeout=60)
        sel = discord.ui.Select(placeholder="Choose item to add rewards to", options=options)
        guild_ref = self.guild
        parent = interaction
        all_items_ref = all_items
        async def on_select(inter2):
            if inter2.user.id != self.author_id:
                await inter2.response.send_message("❌ Not your panel.", ephemeral=True)
                return
            item_id = int(sel.values[0])
            chosen = next((i for i in all_items_ref if i["id"] == item_id), None)
            item_name = chosen["name"] if chosen else "item"
            async def rewards_submit(inter3, value):
                # Support both newline-separated and space-separated entries
                # (Discord mobile can't always insert newlines in modals)
                raw = value.strip()
                if "\n" in raw:
                    entries = [l.strip() for l in raw.splitlines() if l.strip()]
                else:
                    entries = [l.strip() for l in raw.split() if l.strip()]
                if not entries:
                    await inter3.response.send_message("❌ No valid rewards entered.", ephemeral=True)
                    return
                for entry in entries:
                    db_add_item_reward(item_id, guild_ref.id, entry)
                total_avail = db_count_available_rewards(item_id, guild_ref.id)
                await inter3.response.send_message(
                    f"✅ Added **{len(entries)}** reward(s) to **{item_name}**.\n"
                    f"🔑 Total available: **{total_avail}**\n\n"
                    "When a member buys this item, one reward is sent automatically in the ticket.",
                    ephemeral=True
                )
                await self._refresh(parent)
            title_str = f"Add Rewards — {item_name}"
            await inter2.response.send_modal(Modal1(
                title_str[:45],
                "One reward per line (or space-sep.)",
                placeholder="https://link1.com\nhttps://link2.com\nCODE-ABC",
                required=True, max_length=4000, paragraph=True, callback=rewards_submit
            ))
        sel.callback = on_select
        view.add_item(sel)
        existing_counts = {i["id"]: db_count_available_rewards(i["id"], self.guild.id) for i in all_items}
        info = "\n".join(f"• **{i['name']}** — 🔑 {existing_counts[i['id']]} available" for i in all_items[:10])
        await interaction.response.send_message(
            f"🔑 **Pre-load rewards (links/codes) for instant distribution on purchase.**\n"
            f"Enter one reward per line — each purchase auto-claims one.\n\n"
            f"**Current stock:**\n{info}",
            view=view, ephemeral=True
        )

    @discord.ui.button(label="📊 Stock Overview", style=discord.ButtonStyle.grey, row=2)
    async def btn_stock(self, interaction: discord.Interaction, btn):
        """Show remaining reward stock for all items."""
        all_items = db_get_shop_items(self.guild.id)
        config = db_get_config(self.guild.id)
        if not all_items:
            await interaction.response.send_message("❌ Shop is empty.", ephemeral=True)
            return
        lines = []
        for item in all_items:
            avail = db_count_available_rewards(item["id"], self.guild.id)
            rewards = db_get_item_rewards(item["id"], self.guild.id)
            used_count = sum(1 for r in rewards if r["used"])
            if rewards:
                lines.append(f"**{item['name']}** — 🔑 {avail} available / {used_count} used")
            else:
                lines.append(f"**{item['name']}** — _(no pre-loaded rewards)_")
        e = E("📊 Reward Stock Overview", "\n".join(lines), C_GOLD)
        e.set_footer(text="Pre-load rewards with 🔑 Add Rewards. Each purchase auto-claims one.")
        await interaction.response.send_message(embed=e, ephemeral=True)

    @discord.ui.button(label="💰 Edit Price", style=discord.ButtonStyle.blurple, row=2)
    async def btn_edit_price(self, interaction: discord.Interaction, btn):
        """Change the price of an existing item from the /config shop panel."""
        items = db_get_shop_items(self.guild.id)
        if not items:
            await interaction.response.send_message("❌ Shop is empty.", ephemeral=True)
            return
        config = db_get_config(self.guild.id)
        options = [
            discord.SelectOption(
                label=f"{item['name'][:70]}  —  {cur(config, item['price'])}",
                description="Choose this item to update its price",
                value=str(item["id"]),
            )
            for item in items[:25]
        ]
        view = discord.ui.View(timeout=120)
        select = discord.ui.Select(
            placeholder="Choose an item to edit its price",
            options=options,
        )
        parent = interaction
        all_items = items
        guild_ref = self.guild

        async def on_select(inter2: discord.Interaction):
            if inter2.user.id != self.author_id:
                await inter2.response.send_message("❌ Not your panel.", ephemeral=True)
                return
            item_id = int(select.values[0])
            chosen = next((item for item in all_items if item["id"] == item_id), None)
            if not chosen:
                await inter2.response.send_message("❌ Item not found.", ephemeral=True)
                return

            async def price_submit(inter3: discord.Interaction, value: str):
                try:
                    new_price = int(value.strip())
                    if new_price <= 0:
                        raise ValueError
                except ValueError:
                    await inter3.response.send_message(
                        "❌ Price must be a positive whole number.",
                        ephemeral=True,
                    )
                    return
                db_set_shop_item_price(item_id, guild_ref.id, new_price)
                await inter3.response.send_message(
                    f"✅ **{chosen['name']}** price updated to **{cur(config, new_price)}**.",
                    ephemeral=True,
                )
                await self._refresh(parent)

            await inter2.response.send_modal(
                Modal1(
                    "Edit Item Price",
                    label=f"New price in {config.get('currency_name') or 'Gems'}",
                    placeholder="100",
                    default=str(chosen["price"]),
                    callback=price_submit,
                )
            )

        select.callback = on_select
        view.add_item(select)
        await interaction.response.send_message(
            "💰 Choose an item, then enter its new price.",
            view=view,
            ephemeral=True,
        )

    @discord.ui.button(label="⏳ Toggle Expiry Visibility", style=discord.ButtonStyle.grey, row=1)
    async def btn_toggle_expiry(self, interaction: discord.Interaction, btn):
        """Toggle whether the expiry duration is shown in /shop for temporary items."""
        all_items = db_get_shop_items(self.guild.id)
        items = [i for i in all_items if i.get("is_temporary")]
        if not items:
            await interaction.response.send_message("❌ No temporary items in the shop.", ephemeral=True)
            return
        config = db_get_config(self.guild.id)
        options = [
            discord.SelectOption(
                label=f"{item['name'][:70]}  —  {cur(config, item['price'])}",
                description="⏳ Expiry SHOWN" if item.get("show_duration", 1) else "🔇 Expiry HIDDEN",
                value=str(item["id"])
            )
            for item in items[:25]
        ]
        view = discord.ui.View(timeout=60)
        sel = discord.ui.Select(placeholder="Toggle expiry visibility", options=options)
        guild_ref = self.guild
        parent = interaction
        async def on_select(inter2):
            if inter2.user.id != self.author_id:
                await inter2.response.send_message("❌ Not your panel.", ephemeral=True)
                return
            item_id = int(sel.values[0])
            chosen = next((i for i in items if i["id"] == item_id), None)
            if not chosen:
                await inter2.response.send_message("❌ Item not found.", ephemeral=True)
                return
            new_show = 0 if chosen.get("show_duration", 1) else 1
            conn = get_db()
            conn.execute("UPDATE shop_items SET show_duration=? WHERE id=? AND guild_id=?",
                         (new_show, item_id, guild_ref.id))
            conn.commit()
            conn.close()
            label = "✅ Expiry now **shown** in /shop" if new_show else "🔇 Expiry now **hidden** in /shop"
            await inter2.response.send_message(f"{label} for **{chosen['name']}**", ephemeral=True)
            await self._refresh(parent)
        sel.callback = on_select
        view.add_item(sel)
        await interaction.response.send_message("⏳ Toggle expiry display for a temporary item:", view=view, ephemeral=True)

    @discord.ui.button(label="✏️ Edit Name", style=discord.ButtonStyle.blurple, row=1)
    async def btn_edit_name(self, interaction: discord.Interaction, btn):
        items = db_get_shop_items(self.guild.id)
        if not items:
            await interaction.response.send_message("❌ Shop is empty.", ephemeral=True)
            return
        config = db_get_config(self.guild.id)
        options = [
            discord.SelectOption(label=f"{item['name'][:80]}  —  {cur(config, item['price'])}", value=str(item["id"]))
            for item in items[:25]
        ]
        view = discord.ui.View(timeout=60)
        sel  = discord.ui.Select(placeholder="Choose item to rename", options=options)
        guild_ref = self.guild
        parent    = interaction
        all_items = items
        async def on_select(inter2):
            if inter2.user.id != self.author_id:
                await inter2.response.send_message("❌ Not your panel.", ephemeral=True)
                return
            item_id = int(sel.values[0])
            chosen  = next((i for i in all_items if i["id"] == item_id), None)
            current_name = chosen["name"] if chosen else ""
            async def name_submit(inter3, value):
                new_name = value.strip()
                if not new_name:
                    await inter3.response.send_message("❌ Name cannot be empty.", ephemeral=True)
                    return
                db_set_shop_item_name(item_id, guild_ref.id, new_name)
                await inter3.response.send_message(f"✅ Renamed to **{new_name}**.", ephemeral=True)
                await self._refresh(parent)
            await inter2.response.send_modal(Modal1(
                f"Rename — {current_name[:40]}",
                label="New item name",
                placeholder=current_name,
                default=current_name,
                max_length=80,
                callback=name_submit,
            ))
        sel.callback = on_select
        view.add_item(sel)
        await interaction.response.send_message("✏️ Choose an item to rename:", view=view, ephemeral=True)

    @discord.ui.button(label="↕️ Reorder Items", style=discord.ButtonStyle.blurple, row=1)
    async def btn_reorder(self, interaction: discord.Interaction, btn):
        items = db_get_shop_items(self.guild.id)
        if len(items) < 2:
            await interaction.response.send_message("❌ Need at least 2 items to reorder.", ephemeral=True)
            return
        config = db_get_config(self.guild.id)
        options = [
            discord.SelectOption(
                label=f"#{idx}  {item['name'][:60]}  —  {cur(config, item['price'])}",
                value=str(item["id"]),
            )
            for idx, item in enumerate(items[:25], 1)
        ]
        view1 = discord.ui.View(timeout=60)
        sel1  = discord.ui.Select(placeholder="Pick item to move…", options=options)
        guild_ref  = self.guild
        parent_int = interaction
        async def on_pick_item(inter2):
            if inter2.user.id != self.author_id:
                await inter2.response.send_message("❌ Not your panel.", ephemeral=True)
                return
            item_id = int(sel1.values[0])
            pos_opts = [
                discord.SelectOption(label=f"Position #{p}", value=str(p))
                for p in range(1, len(items) + 1)
            ]
            view2 = discord.ui.View(timeout=60)
            sel2  = discord.ui.Select(placeholder="Move to position…", options=pos_opts[:25])
            async def on_pick_pos(inter3):
                new_pos   = int(sel2.values[0])
                current   = db_get_shop_items(guild_ref.id)
                ordered   = [i for i in current if i["id"] != item_id]
                moved     = next((i for i in current if i["id"] == item_id), None)
                if moved:
                    ordered.insert(new_pos - 1, moved)
                db_reorder_shop_items(guild_ref.id, [i["id"] for i in ordered])
                await inter3.response.send_message(
                    f"✅ **{moved['name'] if moved else 'Item'}** moved to position **#{new_pos}**.",
                    ephemeral=True
                )
                await self._refresh(parent_int)
            sel2.callback = on_pick_pos
            view2.add_item(sel2)
            await inter2.response.send_message("📍 Move to which position?", view=view2, ephemeral=True)
        sel1.callback = on_pick_item
        view1.add_item(sel1)
        await interaction.response.send_message("↕️ Which item do you want to move?", view=view1, ephemeral=True)

    @discord.ui.button(label="🗑️ Remove Item", style=discord.ButtonStyle.red, row=0)
    async def btn_remove(self, interaction: discord.Interaction, btn):
        items = db_get_shop_items(self.guild.id)
        if not items:
            await interaction.response.send_message("❌ Shop is already empty.", ephemeral=True)
            return
        options = [
            discord.SelectOption(label=f"{item['name'][:80]}  —  {cur(db_get_config(self.guild.id), item['price'])}", value=str(item["id"]))
            for item in items[:25]
        ]
        view = discord.ui.View(timeout=60)
        sel = discord.ui.Select(placeholder="Choose an item to remove", options=options)
        async def on_select(inter2):
            if inter2.user.id != self.author_id:
                await inter2.response.send_message("❌ Not your panel.", ephemeral=True)
                return
            db_remove_shop_item(int(sel.values[0]), self.guild.id)
            await inter2.response.send_message("✅ Item removed.", ephemeral=True)
            await self._refresh(interaction)
        sel.callback = on_select
        view.add_item(sel)
        await interaction.response.send_message("🗑️ Which item would you like to remove?", view=view, ephemeral=True)

    @discord.ui.button(label="📋 View All", style=discord.ButtonStyle.grey, row=0)
    async def btn_view(self, interaction: discord.Interaction, btn):
        items = db_get_shop_items(self.guild.id)
        if not items:
            await interaction.response.send_message("The shop is empty.", ephemeral=True)
            return
        lines = []
        for i in items:
            tags = []
            if i.get("is_temporary"): tags.append(f"⏳{i['duration_days']}d")
            if i.get("requires_text"): tags.append(f"📝 {i['text_label']}")
            if i.get("image_url"): tags.append("🖼️")
            if i.get("requires_approval"): tags.append("🔒")
            if i.get("purchase_limit"): tags.append(f"🔢{i['purchase_limit']}")
            tag_str = "  " + "  ".join(tags) if tags else ""
            config = db_get_config(self.guild.id)
            lines.append(f"`{i['id']}` **{i['name']}** — {cur(config, i['price'])}{tag_str}")
        e = E("🛒 All Shop Items", "\n".join(lines), C_GOLD)
        e.set_footer(text="🖼️=image  ⏳=temp  📝=text  🔒=approval  🔢N=buy limit")
        await interaction.response.send_message(embed=e, ephemeral=True)

    @discord.ui.button(label="🔒 Require Approval", style=discord.ButtonStyle.grey, row=3)
    async def btn_toggle_approval(self, interaction: discord.Interaction, btn):
        """Toggle whether an item requires Gems Owner approval before purchase."""
        all_items = db_get_shop_items(self.guild.id)
        if not all_items:
            await interaction.response.send_message("❌ Shop is empty.", ephemeral=True)
            return
        config = db_get_config(self.guild.id)
        options = [
            discord.SelectOption(
                label=f"{item['name'][:70]}  —  {cur(config, item['price'])}",
                description="🔒 Approval REQUIRED" if item.get("requires_approval") else "🟢 Instant purchase",
                value=str(item["id"])
            )
            for item in all_items[:25]
        ]
        view = discord.ui.View(timeout=60)
        sel  = discord.ui.Select(placeholder="Toggle approval requirement", options=options)
        guild_ref = self.guild
        parent    = interaction
        async def on_select(inter2):
            if inter2.user.id != self.author_id:
                await inter2.response.send_message("❌ Not your panel.", ephemeral=True)
                return
            item_id = int(sel.values[0])
            chosen  = next((i for i in all_items if i["id"] == item_id), None)
            if not chosen:
                await inter2.response.send_message("❌ Item not found.", ephemeral=True)
                return
            new_val = 0 if chosen.get("requires_approval") else 1
            conn = get_db()
            conn.execute("UPDATE shop_items SET requires_approval=? WHERE id=? AND guild_id=?",
                         (new_val, item_id, guild_ref.id))
            conn.commit()
            conn.close()
            label = "🔒 Approval now **required**" if new_val else "🟢 Item is now **instant purchase**"
            await inter2.response.send_message(f"{label} for **{chosen['name']}**", ephemeral=True)
            await self._refresh(parent)
        sel.callback = on_select
        view.add_item(sel)
        await interaction.response.send_message(
            "🔒 **Require Gems Owner approval** before a purchase goes through.\n"
            "When enabled, gems are only deducted after an owner approves in the admin channel.",
            view=view, ephemeral=True
        )

    @discord.ui.button(label="🔢 Buy Limit", style=discord.ButtonStyle.grey, row=3)
    async def btn_buy_limit(self, interaction: discord.Interaction, btn):
        """Set or clear a per-person purchase limit for an item."""
        all_items = db_get_shop_items(self.guild.id)
        if not all_items:
            await interaction.response.send_message("❌ Shop is empty.", ephemeral=True)
            return
        config = db_get_config(self.guild.id)
        options = [
            discord.SelectOption(
                label=f"{item['name'][:70]}  —  {cur(config, item['price'])}",
                description=f"🔢 Limit: {item['purchase_limit']}/person" if item.get("purchase_limit") else "No limit",
                value=str(item["id"])
            )
            for item in all_items[:25]
        ]
        view = discord.ui.View(timeout=60)
        sel  = discord.ui.Select(placeholder="Set purchase limit for item", options=options)
        guild_ref = self.guild
        parent    = interaction
        async def on_select(inter2):
            if inter2.user.id != self.author_id:
                await inter2.response.send_message("❌ Not your panel.", ephemeral=True)
                return
            item_id = int(sel.values[0])
            chosen  = next((i for i in all_items if i["id"] == item_id), None)
            if not chosen:
                await inter2.response.send_message("❌ Item not found.", ephemeral=True)
                return
            async def limit_submit(inter3, value):
                v = value.strip()
                if not v or v == "0":
                    conn = get_db()
                    conn.execute("UPDATE shop_items SET purchase_limit=NULL WHERE id=? AND guild_id=?",
                                 (item_id, guild_ref.id))
                    conn.commit()
                    conn.close()
                    await inter3.response.send_message(
                        f"✅ Purchase limit **removed** from **{chosen['name']}** — unlimited purchases.", ephemeral=True)
                else:
                    try:
                        lim = int(v)
                        if lim < 1: raise ValueError
                    except ValueError:
                        await inter3.response.send_message("❌ Enter a positive number (or 0 to remove).", ephemeral=True)
                        return
                    conn = get_db()
                    conn.execute("UPDATE shop_items SET purchase_limit=? WHERE id=? AND guild_id=?",
                                 (lim, item_id, guild_ref.id))
                    conn.commit()
                    conn.close()
                    await inter3.response.send_message(
                        f"✅ **{chosen['name']}** limited to **{lim} purchase(s) per person**.", ephemeral=True)
                await self._refresh(parent)
            current_limit = str(chosen.get("purchase_limit") or "")
            await inter2.response.send_modal(Modal1(
                f"Buy Limit — {chosen['name'][:35]}",
                label="Max purchases per person (0 = unlimited)",
                placeholder="1  or  3  or  0",
                default=current_limit,
                required=False,
                callback=limit_submit
            ))
        sel.callback = on_select
        view.add_item(sel)
        await interaction.response.send_message(
            "🔢 **Set a per-person purchase limit.**\n"
            "Members who reach this limit will be blocked from buying again.\n"
            "Set to 0 to remove the limit.",
            view=view, ephemeral=True
        )

    @discord.ui.button(label="👁️ Hide Buy Limit", style=discord.ButtonStyle.grey, row=3)
    async def btn_hide_limit(self, interaction: discord.Interaction, btn):
        """Toggle whether the purchase limit counter is shown in /shop."""
        all_items = [i for i in db_get_shop_items(self.guild.id) if i.get("purchase_limit")]
        if not all_items:
            await interaction.response.send_message("❌ No items have a purchase limit set.", ephemeral=True)
            return
        config = db_get_config(self.guild.id)
        options = [
            discord.SelectOption(
                label=f"{item['name'][:70]}  —  {cur(config, item['price'])}",
                description="👁️ Limit SHOWN in /shop" if item.get("show_purchase_limit", 1) else "🔇 Limit HIDDEN",
                value=str(item["id"])
            )
            for item in all_items[:25]
        ]
        view = discord.ui.View(timeout=60)
        sel  = discord.ui.Select(placeholder="Toggle buy limit visibility", options=options)
        guild_ref = self.guild
        parent    = interaction
        async def on_select(inter2):
            if inter2.user.id != self.author_id:
                await inter2.response.send_message("❌ Not your panel.", ephemeral=True)
                return
            item_id = int(sel.values[0])
            chosen  = next((i for i in all_items if i["id"] == item_id), None)
            if not chosen:
                await inter2.response.send_message("❌ Item not found.", ephemeral=True)
                return
            new_show = 0 if chosen.get("show_purchase_limit", 1) else 1
            conn = get_db()
            conn.execute("UPDATE shop_items SET show_purchase_limit=? WHERE id=? AND guild_id=?",
                         (new_show, item_id, guild_ref.id))
            conn.commit()
            conn.close()
            label = "👁️ Buy limit now **shown** in /shop" if new_show else "🔇 Buy limit now **hidden** from /shop"
            await inter2.response.send_message(f"{label} for **{chosen['name']}**", ephemeral=True)
            await self._refresh(parent)
        sel.callback = on_select
        view.add_item(sel)
        await interaction.response.send_message("👁️ Toggle buy limit display:", view=view, ephemeral=True)

    @discord.ui.button(label="🔄 Post Shop Now", style=discord.ButtonStyle.green, row=3)
    async def btn_post_shop(self, interaction: discord.Interaction, btn):
        """Manually post the shop overview to the configured shop/daily-shop channel."""
        await interaction.response.defer(ephemeral=True)
        config  = db_get_config(self.guild.id)
        items   = db_get_shop_items(self.guild.id)
        if not items:
            await interaction.followup.send("❌ The shop is empty — add items first.", ephemeral=True)
            return
        # Prefer daily-shop channel, fall back to shop channel, then commands channel
        ch_id = (config.get("daily_shop_channel_id")
                 or config.get("shop_channel_id")
                 or config.get("commands_channel_id"))
        if not ch_id:
            await interaction.followup.send(
                "❌ No shop channel configured. Set one in `/config → 💬 Channels`.", ephemeral=True)
            return
        ch = interaction.client.get_channel(ch_id)
        if not ch:
            await interaction.followup.send(
                f"❌ Cannot find channel <#{ch_id}>. Check bot permissions.", ephemeral=True)
            return
        c_name  = config.get("currency_name")  or "Gems"
        c_emoji = config.get("currency_emoji") or "💎"
        shop_ch = config.get("shop_channel_id") or config.get("commands_channel_id")
        shop_ch_str = f"<#{shop_ch}>" if shop_ch else "the shop channel"
        embeds = []
        header = discord.Embed(
            title="🛍️ Shop Update",
            description=f"Here's what's available right now. Use `/shop` in {shop_ch_str} to buy!",
            color=C_GOLD
        )
        header.timestamp = datetime.utcnow()
        embeds.append(header)
        now_iso = datetime.utcnow().isoformat()
        live_count = 0
        for item in items:
            if item.get("item_expires_at") and item["item_expires_at"] < now_iso:
                continue
            line = f"{c_emoji} **{item['price']:,} {c_name}**"
            ie = discord.Embed(title=item["name"], description=line, color=C_GOLD)
            if item.get("image_url"):
                ie.set_image(url=item["image_url"])
            if item.get("stock") is not None:
                if item["stock"] == 0:
                    ie.set_footer(text="🚫 Sold out")
                else:
                    ie.set_footer(text=f"📦 {item['stock']} remaining")
            embeds.append(ie)
            live_count += 1
        try:
            for i in range(0, len(embeds), 10):
                await ch.send(embeds=embeds[i:i+10])
            await interaction.followup.send(
                f"✅ Shop posted to <#{ch_id}> — **{live_count}** item(s).", ephemeral=True)
            await bot_log(interaction.client, self.guild.id, "🔄 Shop Posted Manually",
                          f"**By:** {interaction.user.mention}\n**Channel:** <#{ch_id}>\n**Items:** {len(items)}")
        except discord.Forbidden:
            await interaction.followup.send(
                f"❌ Missing permission to post in <#{ch_id}>.", ephemeral=True)
        except Exception as ex:
            await interaction.followup.send(f"❌ Error: {ex}", ephemeral=True)


class ConfigQuestsMenu(_SubMenu):
    def build_embed(self, config: dict) -> discord.Embed:
        _on   = lambda v: "✅ Enabled" if v else "❌ Disabled"
        _role = lambda rid: f"<@&{rid}>" if rid else "`Not set`"
        _ch   = lambda cid: f"<#{cid}>" if cid else "`Not set`"
        e = E("📅 Quest Settings", color=C_QUEST)
        # ── Monthly quests ──────────────────────────────
        e.add_field(name="─── Monthly Quests ───", value="\u200b", inline=False)
        e.add_field(name="🪨 Stone",   value=f"**{cur(config, config.get('quest_xp_stone',50))}**",   inline=True)
        e.add_field(name="🥉 Bronze",  value=f"**{cur(config, config.get('quest_xp_bronze',100))}**", inline=True)
        e.add_field(name="🥈 Silver",  value=f"**{cur(config, config.get('quest_xp_silver',200))}**", inline=True)
        e.add_field(name="🥇 Gold",    value=f"**{cur(config, config.get('quest_xp_gold',400))}**",   inline=True)
        e.add_field(name="💎 Diamond", value=f"**{cur(config, config.get('quest_xp_diamond',750))}**",inline=True)
        e.add_field(name="🔄 Boost Quest",value=_bool(config.get("boost_quest_enabled", 1)) +
                    f" — **{cur(config, config.get('boost_quest_xp',100))}** per boost", inline=True)
        # ── Daily quests ─────────────────────────────────
        e.add_field(name="─── Daily Quests ───", value="\u200b", inline=False)
        e.add_field(name="Daily Quests",       value=_on(config.get("daily_quest_enabled", 0)),            inline=True)
        e.add_field(name="Quest Role",         value=_role(config.get("daily_quest_role_id")),              inline=True)
        e.add_field(name="DM Enabled",         value=_on(config.get("daily_quest_dm_enabled", 1)),         inline=True)
        daily_xp = config.get("daily_quest_xp", 50)
        e.add_field(name="Reward per Quest",   value=f"**{daily_xp}** {config.get('currency_emoji','💎')}", inline=True)
        e.add_field(name="💬 Chat Channel",    value=_ch(config.get("daily_quest_messages_channel_id")),   inline=True)
        gems_owner_role = config.get("manager_role_id")
        e.add_field(
            name="👑 Gems Owner Role",
            value=f"<@&{gems_owner_role}>" if gems_owner_role else "`Not set`",
            inline=True,
        )
        e.set_footer(text="Monthly: reset each month, 1 quest/rarity per user  ·  Daily: 3 random quests sent at midnight UTC")
        return e

    def _parse_role(self, value: str):
        raw = value.strip().lstrip("<@&").rstrip(">")
        return int(raw) if raw.isdigit() else None

    @discord.ui.button(label="Set Rarity Reward", style=discord.ButtonStyle.blurple, row=0)
    async def btn_rarity_xp(self, interaction: discord.Interaction, btn):
        config = db_get_config(self.guild.id)
        async def submit(inter, v_rarity, v_xp):
            rarity = v_rarity.strip().lower()
            if rarity not in RARITIES:
                await inter.response.send_message(f"❌ Valid rarities: {', '.join(RARITIES)}", ephemeral=True)
                return
            try:
                xp = int(v_xp)
                if xp < 0: raise ValueError
            except ValueError:
                await inter.response.send_message("❌ Enter a non-negative number.", ephemeral=True)
                return
            cfg2 = db_get_config(self.guild.id)
            db_set_config(self.guild.id, **{f"quest_xp_{rarity}": xp})
            await inter.response.send_message(f"✅ {rarity.capitalize()} quest reward set to **{cur(cfg2, xp)}**", ephemeral=True)
            await self._refresh(interaction)
        await interaction.response.send_modal(Modal2(
            "Set Quest Rarity Reward", "Rarity", "stone / bronze / silver / gold / diamond",
            "Reward amount", "200",
            callback=submit
        ))

    @discord.ui.button(label="Toggle Boost Quest", style=discord.ButtonStyle.blurple, row=0)
    async def btn_boost_toggle(self, interaction, btn):
        config = db_get_config(self.guild.id)
        new_val = 0 if config.get("boost_quest_enabled", 1) else 1
        db_set_config(self.guild.id, boost_quest_enabled=new_val)
        await interaction.response.edit_message(embed=self.build_embed(db_get_config(self.guild.id)), view=self)

    @discord.ui.button(label="Boost Quest Reward", style=discord.ButtonStyle.blurple, row=0)
    async def btn_boost_xp(self, interaction, btn):
        config = db_get_config(self.guild.id)
        async def submit(inter, value):
            try:
                xp = int(value)
                if xp < 0: raise ValueError
            except ValueError:
                await inter.response.send_message("❌ Enter a non-negative number.", ephemeral=True)
                return
            db_set_config(self.guild.id, boost_quest_xp=xp)
            cfg2 = db_get_config(self.guild.id)
            await inter.response.send_message(f"✅ Boost quest reward set to **{cur(cfg2, xp)}** per boost", ephemeral=True)
            await self._refresh(interaction)
        await interaction.response.send_modal(Modal1("Boost Quest Reward", "Reward per server boost",
            placeholder="100", default=str(config.get("boost_quest_xp", 100)), callback=submit))

    @discord.ui.button(label="Enable/Disable Quest",style=discord.ButtonStyle.grey, row=1)
    async def btn_toggle_quest(self, interaction: discord.Interaction, btn):
        # List all quest keys with enabled status
        conn = get_db()
        rows = conn.execute("SELECT quest_key, enabled FROM quest_pool_config WHERE guild_id=?",
                            (self.guild.id,)).fetchall()
        conn.close()
        status_map = {r["quest_key"]: r["enabled"] for r in rows}
        all_keys = [(r, q) for r, quests in QUEST_POOL.items() for q in quests]
        options = [
            discord.SelectOption(
                label=f"[{r.upper()}] {q['name'][:60]}",
                value=q["key"],
                description="✅ Enabled" if status_map.get(q["key"], 1) else "❌ Disabled"
            )
            for r, q in all_keys[:25]
        ]
        view = discord.ui.View(timeout=60)
        sel = discord.ui.Select(placeholder="Choose a quest to toggle", options=options)
        async def on_select(inter2):
            if inter2.user.id != self.author_id:
                await inter2.response.send_message("❌ Not your panel.", ephemeral=True)
                return
            key = sel.values[0]
            current = status_map.get(key, 1)
            new_enabled = 0 if current else 1
            conn2 = get_db()
            conn2.execute("INSERT INTO quest_pool_config (guild_id, quest_key, enabled) VALUES (?,?,?) "
                          "ON CONFLICT(guild_id, quest_key) DO UPDATE SET enabled=?",
                          (self.guild.id, key, new_enabled, new_enabled))
            conn2.commit()
            conn2.close()
            label = "✅ Enabled" if new_enabled else "❌ Disabled"
            await inter2.response.send_message(f"{label} quest: **{key}**", ephemeral=True)
        sel.callback = on_select
        view.add_item(sel)
        await interaction.response.send_message("Toggle a quest from the pool:", view=view, ephemeral=True)

    # ── Daily quest buttons ────────────────────────────────────
    @discord.ui.button(label="Toggle Daily Quests", style=discord.ButtonStyle.blurple, row=2)
    async def btn_daily_toggle(self, interaction: discord.Interaction, btn):
        config  = db_get_config(self.guild.id)
        new_val = 0 if config.get("daily_quest_enabled", 0) else 1
        db_set_config(self.guild.id, daily_quest_enabled=new_val)
        await interaction.response.send_message(
            f"✅ Daily quests {'**enabled**' if new_val else '**disabled**'}.", ephemeral=True)
        await self._refresh(interaction)

    @discord.ui.button(label="Daily Quest Role", style=discord.ButtonStyle.grey, row=2)
    async def btn_daily_role(self, interaction: discord.Interaction, btn):
        config = db_get_config(self.guild.id)
        async def submit(inter, value):
            if not value.strip():
                db_set_config(self.guild.id, daily_quest_role_id=None)
                await inter.response.send_message("✅ Role removed — quests sent to all members.", ephemeral=True)
            else:
                rid = self._parse_role(value)
                if not rid:
                    await inter.response.send_message("❌ Invalid role.", ephemeral=True); return
                db_set_config(self.guild.id, daily_quest_role_id=rid)
                await inter.response.send_message(f"✅ Daily quests will target <@&{rid}>.", ephemeral=True)
            await self._refresh(interaction)
        await interaction.response.send_modal(Modal1(
            title="Daily Quest Role", label="Role mention or ID (empty = all members)",
            placeholder="@QuestMembers  or  1234567890",
            default=str(config.get("daily_quest_role_id") or ""),
            required=False, callback=submit))

    @discord.ui.button(label="Toggle Quest DMs", style=discord.ButtonStyle.blurple, row=2)
    async def btn_daily_dm_toggle(self, interaction: discord.Interaction, btn):
        config  = db_get_config(self.guild.id)
        new_val = 0 if config.get("daily_quest_dm_enabled", 1) else 1
        db_set_config(self.guild.id, daily_quest_dm_enabled=new_val)
        await interaction.response.send_message(
            f"✅ Quest DMs {'**enabled**' if new_val else '**disabled**'}.", ephemeral=True)
        await self._refresh(interaction)

    @discord.ui.button(label="Daily Reward XP", style=discord.ButtonStyle.grey, row=3)
    async def btn_daily_xp(self, interaction: discord.Interaction, btn):
        config = db_get_config(self.guild.id)
        async def submit(inter, value):
            try:
                xp = int(value.strip())
                if xp < 0: raise ValueError
            except ValueError:
                await inter.response.send_message("❌ Must be a whole number ≥ 0.", ephemeral=True); return
            db_set_config(self.guild.id, daily_quest_xp=xp)
            await inter.response.send_message(
                f"✅ Daily quest reward set to **{xp} {config.get('currency_emoji','💎')}**.", ephemeral=True)
            await self._refresh(interaction)
        await interaction.response.send_modal(Modal1(
            title="Daily Quest Reward", label="Gems awarded per completed quest",
            placeholder="50", default=str(config.get("daily_quest_xp", 50)), callback=submit))

    @discord.ui.button(label="💬 Chat Channel", style=discord.ButtonStyle.blurple, row=3)
    async def btn_daily_chat_ch(self, interaction: discord.Interaction, btn):
        config = db_get_config(self.guild.id)
        async def submit(inter, value):
            if not value.strip():
                db_set_config(self.guild.id, daily_quest_messages_channel_id=None)
                await inter.response.send_message("✅ Chat channel removed.", ephemeral=True)
            else:
                ch_id = parse_channel_id(value)
                if not ch_id:
                    await inter.response.send_message("❌ Invalid channel.", ephemeral=True); return
                db_set_config(self.guild.id, daily_quest_messages_channel_id=ch_id)
                await inter.response.send_message(
                    f"✅ Daily quest chat channel set to <#{ch_id}>.", ephemeral=True)
            await self._refresh(interaction)
        await interaction.response.send_modal(Modal1(
            title="Daily Quest Chat Channel", label="Channel mention or ID (empty = remove)",
            placeholder="#global  or  1234567890",
            default=str(config.get("daily_quest_messages_channel_id") or ""),
            required=False, callback=submit))

    @discord.ui.button(label="👑 Gems Owner Role", style=discord.ButtonStyle.blurple, row=3)
    async def btn_daily_owner(self, interaction: discord.Interaction, btn):
        config = db_get_config(self.guild.id)
        async def submit(inter, value):
            if not value.strip():
                db_set_config(self.guild.id, manager_role_id=None)
                await inter.response.send_message(
                    "✅ Gems Owner role removed. The daily bonus quest will show a generic role instruction.",
                    ephemeral=True)
            else:
                raw = value.strip().lstrip("<@&").rstrip(">")
                if not raw.isdigit():
                    await inter.response.send_message(
                        "❌ Mention the role or paste its ID.", ephemeral=True); return
                db_set_config(self.guild.id, manager_role_id=int(raw))
                await inter.response.send_message(
                    f"✅ Gems Owner role set to <@&{raw}>. Members must ping this role for the daily Gems bonus quest.",
                    ephemeral=True)
            await self._refresh(interaction)
        await interaction.response.send_modal(Modal1(
            title="Gems Owner Role",
            label="Role mention or ID (empty = remove)",
            placeholder="@Gems Owner  or  1234567890",
            default=str(config.get("manager_role_id") or ""),
            required=False, callback=submit))

class ConfigAchievementsMenu(_SubMenu):
    def build_embed(self, config: dict) -> discord.Embed:
        db_ensure_achievement_config(self.guild.id)
        e = E("🏆 Achievement Settings", color=C_ACHIEVE)
        e.description = "Configure thresholds and Discord roles for each achievement tier."
        for ach_def in ACHIEVEMENT_DEFS:
            tiers = db_get_achievement_config(self.guild.id, ach_def["key"])
            tier_lines = []
            for t in tiers[:5]:
                role_str = f"<@&{t['role_id']}>" if t.get("role_id") else "`No role`"
                enabled_str = "" if t.get("enabled", 1) else " ❌"
                tier_lines.append(f"Tier {t['tier'] + 1}: **{t['threshold']}** → {role_str}{enabled_str}")
            e.add_field(
                name=f"{ach_def['name']} ({ach_def['category']})",
                value="\n".join(tier_lines) if tier_lines else "`Default thresholds, no roles set`",
                inline=False
            )
        e.add_field(name="📢 Announcement Channel", value=_ch(config.get("achievement_channel_id")), inline=False)
        return e

    @discord.ui.button(label="Set Tier Role",    style=discord.ButtonStyle.blurple, row=0)
    async def btn_role(self, interaction: discord.Interaction, btn):
        async def submit(inter, v_ach, v_tier, v_role):
            # Find achievement
            ach = next((a for a in ACHIEVEMENT_DEFS if a["key"].lower() == v_ach.strip().lower()), None)
            if not ach:
                keys = ", ".join(a["key"] for a in ACHIEVEMENT_DEFS)
                await inter.response.send_message(f"❌ Unknown achievement. Valid: {keys}", ephemeral=True)
                return
            try:
                tier_display = int(v_tier.strip())
                if tier_display < 1 or tier_display > 5: raise ValueError
            except ValueError:
                await inter.response.send_message("❌ Tier must be 1–5.", ephemeral=True)
                return
            tier = tier_display - 1  # convert to 0-indexed for storage
            role_id = parse_role_id(v_role.strip()) if v_role.strip() else None
            db_ensure_achievement_config(self.guild.id)
            conn = get_db()
            default_threshold = ach["tiers"][tier] if tier < len(ach["tiers"]) else 0
            conn.execute(
                "INSERT INTO achievement_config (guild_id, achievement_key, tier, threshold, role_id) VALUES (?,?,?,?,?) "
                "ON CONFLICT(guild_id, achievement_key, tier) DO UPDATE SET role_id=?",
                (self.guild.id, ach["key"], tier, default_threshold, role_id, role_id)
            )
            conn.commit()
            conn.close()
            role_str = f"<@&{role_id}>" if role_id else "removed"
            await inter.response.send_message(
                f"✅ **{ach['name']}** Tier {tier_display} role set to {role_str}", ephemeral=True)
            await self._refresh(interaction)
        await interaction.response.send_modal(Modal3(
            "Set Achievement Role",
            "Achievement key", "shares / invites / streak / boosts / quests",
            "Tier (1–5)", "1 = I,  2 = II,  3 = III,  4 = IV,  5 = V",
            "Role mention or ID (empty = remove)", "@RoleName  or  1234567890",
            callback=submit
        ))

    @discord.ui.button(label="Set Threshold",   style=discord.ButtonStyle.blurple, row=0)
    async def btn_threshold(self, interaction: discord.Interaction, btn):
        async def submit(inter, v_ach, v_tier, v_threshold):
            ach = next((a for a in ACHIEVEMENT_DEFS if a["key"].lower() == v_ach.strip().lower()), None)
            if not ach:
                await inter.response.send_message("❌ Unknown achievement key.", ephemeral=True)
                return
            try:
                tier_display = int(v_tier.strip())
                threshold = int(v_threshold.strip())
                if tier_display < 1 or tier_display > 5 or threshold < 1: raise ValueError
            except ValueError:
                await inter.response.send_message("❌ Invalid tier (1–5) or threshold.", ephemeral=True)
                return
            tier = tier_display - 1  # convert to 0-indexed for storage
            db_ensure_achievement_config(self.guild.id)
            conn = get_db()
            conn.execute(
                "INSERT INTO achievement_config (guild_id, achievement_key, tier, threshold) VALUES (?,?,?,?) "
                "ON CONFLICT(guild_id, achievement_key, tier) DO UPDATE SET threshold=?",
                (self.guild.id, ach["key"], tier, threshold, threshold)
            )
            conn.commit()
            conn.close()
            await inter.response.send_message(
                f"✅ **{ach['name']}** Tier {tier_display} threshold set to **{threshold}**", ephemeral=True)
            await self._refresh(interaction)
        await interaction.response.send_modal(Modal3(
            "Set Achievement Threshold",
            "Achievement key", "shares / invites / streak / boosts / quests",
            "Tier (1–5)", "1",
            "Required amount", "50",
            callback=submit
        ))

    @discord.ui.button(label="Achievement Channel", style=discord.ButtonStyle.grey, row=1)
    async def btn_ch(self, interaction: discord.Interaction, btn):
        config = db_get_config(self.guild.id)
        async def submit(inter, value):
            if not value.strip():
                db_set_config(self.guild.id, achievement_channel_id=None)
                await inter.response.send_message("✅ Achievement channel removed.", ephemeral=True)
                await self._refresh(interaction)
                return
            ch_id = parse_channel_id(value)
            if not ch_id:
                await inter.response.send_message("❌ Invalid channel.", ephemeral=True)
                return
            db_set_config(self.guild.id, achievement_channel_id=ch_id)
            await inter.response.send_message(f"✅ Achievement channel set to <#{ch_id}>", ephemeral=True)
            await self._refresh(interaction)
        await interaction.response.send_modal(Modal1("Achievement Channel", "Channel mention or ID (empty = disable)",
            placeholder="#achievements  or  1234567890",
            default=str(config.get("achievement_channel_id") or ""), required=False, callback=submit))

class ConfigEventsMenu(_SubMenu):
    def build_embed(self, config: dict) -> discord.Embed:
        events = db_get_all_events(self.guild.id)
        e = E("🎉 Events", color=C_EVENT)
        if not events:
            e.description = "No events created yet. Add a Double Bonus event or Community Goal."
        else:
            now = datetime.now().isoformat()
            for ev in events[:6]:
                status = "🟢 Active" if (ev["enabled"] and ev["start_date"] <= now <= ev["end_date"]) else \
                         "⏳ Upcoming" if (ev["enabled"] and now < ev["start_date"]) else \
                         "🔴 Ended/Disabled"
                e.add_field(
                    name=f"{status} — {ev['name']} [{ev['event_type']}]",
                    value=f"{ev['start_date'][:10]} → {ev['end_date'][:10]}  ID:`{ev['id']}`",
                    inline=False
                )
        return e

    @discord.ui.button(label="➕ Add Double Bonus Event", style=discord.ButtonStyle.green, row=0)
    async def btn_add_dxp(self, interaction: discord.Interaction, btn):
        async def submit(inter, v_name, v_start, v_end):
            try:
                start_dt = datetime.strptime(v_start.strip(), "%Y-%m-%d")
                end_dt   = datetime.strptime(v_end.strip(), "%Y-%m-%d")
                if end_dt < start_dt: raise ValueError
            except ValueError:
                await inter.response.send_message("❌ Use YYYY-MM-DD format. End must be after start.", ephemeral=True)
                return
            config = db_get_config(self.guild.id)
            mult = config.get("event_double_xp_mult", 2.0)
            conn = get_db()
            conn.execute(
                "INSERT INTO events (guild_id, name, description, event_type, start_date, end_date, config_json) VALUES (?,?,?,?,?,?,?)",
                (self.guild.id, v_name.strip(), f"Double Bonus event (×{mult})", "double_xp",
                 start_dt.isoformat(), end_dt.replace(hour=23, minute=59, second=59).isoformat(),
                 json.dumps({"multiplier": mult}))
            )
            conn.commit()
            conn.close()
            await inter.response.send_message(f"✅ Double Bonus event **{v_name.strip()}** created.", ephemeral=True)
            await self._refresh(interaction)
        await interaction.response.send_modal(Modal3(
            "Add Double Bonus Event",
            "Event name", "Double Bonus Weekend",
            "Start date", "YYYY-MM-DD",
            "End date", "YYYY-MM-DD",
            callback=submit
        ))

    @discord.ui.button(label="➕ Add Community Goal", style=discord.ButtonStyle.green, row=0)
    async def btn_add_goal(self, interaction: discord.Interaction, btn):
        async def submit(inter, v_name, v_target, v_xp):
            try:
                target = int(v_target.strip())
                xp = int(v_xp.strip())
                if target <= 0 or xp < 0: raise ValueError
            except ValueError:
                await inter.response.send_message("❌ Target must be positive, reward non-negative.", ephemeral=True)
                return
            conn = get_db()
            ev_row = conn.execute(
                "INSERT INTO events (guild_id, name, description, event_type, start_date, end_date, config_json) VALUES (?,?,?,?,?,?,?)",
                (self.guild.id, v_name.strip(), f"Community goal: {target} shares", "community_goal",
                 datetime.now().isoformat(),
                 (datetime.now() + timedelta(days=30)).isoformat(),
                 json.dumps({"goal_type": "share_videos", "target": target, "reward_xp": xp}))
            )
            ev_id = ev_row.lastrowid
            conn.execute(
                "INSERT INTO community_goals (guild_id, event_id, name, goal_type, target, reward_xp) VALUES (?,?,?,?,?,?)",
                (self.guild.id, ev_id, v_name.strip(), "share_videos", target, xp)
            )
            conn.commit()
            conn.close()
            cfg2 = db_get_config(self.guild.id)
            await inter.response.send_message(
                f"✅ Community goal **{v_name.strip()}** created.\nTarget: {target} shares → **{cur(cfg2, xp)}** per contributor.",
                ephemeral=True
            )
            await self._refresh(interaction)
        await interaction.response.send_modal(Modal3(
            "Add Community Goal",
            "Goal name", "100 Supporter Challenge",
            "Target (e.g. number of shares)", "100",
            "Reward per contributor", "150",
            callback=submit
        ))

    @discord.ui.button(label="Toggle Event",  style=discord.ButtonStyle.grey, row=1)
    async def btn_toggle(self, interaction: discord.Interaction, btn):
        events = db_get_all_events(self.guild.id)
        if not events:
            await interaction.response.send_message("❌ No events created.", ephemeral=True)
            return
        options = [
            discord.SelectOption(
                label=f"{ev['name'][:60]}  [{ev['event_type']}]",
                value=str(ev["id"]),
                description="✅ Enabled" if ev["enabled"] else "❌ Disabled"
            )
            for ev in events[:25]
        ]
        view = discord.ui.View(timeout=60)
        sel = discord.ui.Select(placeholder="Choose event to toggle", options=options)
        async def on_select(inter2):
            if inter2.user.id != self.author_id:
                await inter2.response.send_message("❌ Not your panel.", ephemeral=True)
                return
            ev_id = int(sel.values[0])
            conn = get_db()
            row = conn.execute("SELECT * FROM events WHERE id=?", (ev_id,)).fetchone()
            newly_enabled = False
            if row:
                new_state = 0 if row["enabled"] else 1
                conn.execute("UPDATE events SET enabled=? WHERE id=?", (new_state, ev_id))
                conn.commit()
                newly_enabled = bool(new_state)
            conn.close()
            await inter2.response.send_message("✅ Event toggled.", ephemeral=True)
            # Announce in event announce channel when event is turned ON
            if newly_enabled and row:
                config = db_get_config(self.guild.id)
                announce_ch_id = config.get("event_announce_channel_id")
                notif_role_id  = config.get("share_ping_role_id")
                if announce_ch_id:
                    ch = inter2.client.get_channel(announce_ch_id)
                    if ch:
                        role_mention = f"<@&{notif_role_id}>" if notif_role_id else "@everyone"
                        ev_type = row["event_type"]
                        if ev_type == "double_xp":
                            try:
                                cfg_json = json.loads(row["config_json"] or "{}")
                                mult = cfg_json.get("multiplier", config.get("event_double_xp_mult", 2.0))
                            except Exception:
                                mult = 2.0
                            desc = f"🎉 **{row['name']}** has started! All {cur(config)} gains are **×{mult}** for the duration!"
                        else:
                            desc = f"🏁 **{row['name']}** is now active! Work together to reach the community goal!"
                        try:
                            await ch.send(f"{role_mention}\n{desc}\n_{row['start_date'][:10]} → {row['end_date'][:10]}_")
                        except Exception as ex:
                            print(f"[EventAnnounce] {ex}")
            await self._refresh(interaction)
        sel.callback = on_select
        view.add_item(sel)
        await interaction.response.send_message("Toggle an event:", view=view, ephemeral=True)

    @discord.ui.button(label="Set Bonus Multiplier", style=discord.ButtonStyle.grey, row=1)
    async def btn_mult(self, interaction: discord.Interaction, btn):
        config = db_get_config(self.guild.id)
        async def submit(inter, value):
            try:
                mult = float(value.strip())
                if mult < 1: raise ValueError
            except ValueError:
                await inter.response.send_message("❌ Must be a number ≥ 1 (e.g. 2.0).", ephemeral=True)
                return
            db_set_config(self.guild.id, event_double_xp_mult=mult)
            await inter.response.send_message(f"✅ Default Double Bonus multiplier set to **×{mult}**", ephemeral=True)
            await self._refresh(interaction)
        await interaction.response.send_modal(Modal1("Double Bonus Multiplier",
            "Multiplier (e.g. 2 = double, 3 = triple)",
            placeholder="2.0", default=str(config.get("event_double_xp_mult", 2.0)), callback=submit))

class ConfigPermissionsMenu(_SubMenu):
    def build_embed(self, config: dict) -> discord.Embed:
        role_id        = config.get("manager_role_id")
        prefix_role_id = config.get("prefix_role_id")
        nick_prefix    = config.get("nick_prefix") or "404 | "
        lock_role_id   = config.get("share_lock_role_id")
        e = E("👥 Roles & Permissions", color=C_MAIN)
        c_name = config.get("currency_name") or "Gems"
        e.description = (
            "**Meeple Owner** is the single role controlling this bot.\n"
            f"Members with this role can award {c_name}, use `/admin`, and use `/config`.\n"
            "They also receive a DM whenever a member opens a purchase ticket.\n\u200b"
        )
        e.add_field(name="👥 Meeple Owner Role", value=_role(role_id), inline=False)
        if not role_id:
            e.add_field(name="⚠️ No role set",
                        value="Any Discord administrator can access the bot until a role is assigned.",
                        inline=False)
        e.add_field(name="\u200b", value="─────────────────────────", inline=False)
        e.add_field(name="🔒 Share Channel Lock Role",
                    value=_role(lock_role_id) if lock_role_id else "`Not set`",
                    inline=False)
        e.add_field(name="\u200b", value=(
            "When set, this role is **denied** `Send Messages` in the Share Channel "
            "whenever no video is active. As soon as a new video is announced the channel "
            "unlocks automatically. Leave empty to keep the channel always open.\n"
            "*(Requires the bot to have **Manage Channel** permission)*"
        ), inline=False)
        e.add_field(name="\u200b", value="─────────────────────────", inline=False)
        e.add_field(name="🏷️ Nickname Prefix",
                    value=f"`{nick_prefix}`",
                    inline=True)
        e.add_field(name="🎭 Prefix Role",
                    value=_role(prefix_role_id),
                    inline=True)
        e.add_field(name="\u200b", value=(
            "Members who receive the **Prefix Role** get `" + nick_prefix + "` prepended to their nickname.\n"
            "The prefix is added automatically when the role is assigned and removed when it is taken away.\n"
            "It coexists safely with the 🔥 streak suffix.\n"
            "Use **Apply Prefix Now** to update all current members who already have the role."
        ), inline=False)
        return e

    @discord.ui.button(label="Set Meeple Owner Role",  style=discord.ButtonStyle.blurple, row=0)
    async def btn_set(self, interaction: discord.Interaction, btn):
        config = db_get_config(self.guild.id)
        async def submit(inter, value):
            if not value.strip():
                db_set_config(self.guild.id, manager_role_id=None)
                await inter.response.send_message("✅ Meeple Owner role removed.", ephemeral=True)
                await self._refresh(interaction)
                return
            role_id = parse_role_id(value)
            if not role_id:
                await inter.response.send_message("❌ Invalid role. Mention it or paste its ID.", ephemeral=True)
                return
            db_set_config(self.guild.id, manager_role_id=role_id)
            await inter.response.send_message(f"✅ Meeple Owner role set to <@&{role_id}>", ephemeral=True)
            await self._refresh(interaction)
        await interaction.response.send_modal(Modal1("Set Meeple Owner Role",
            "Role mention or ID (empty = remove)",
            placeholder="@Meeple-Owner  or  1234567890",
            default=str(config.get("manager_role_id") or ""), required=False, callback=submit))

    @discord.ui.button(label="🔒 Share Lock Role",      style=discord.ButtonStyle.grey,    row=0)
    async def btn_share_lock_role(self, interaction: discord.Interaction, btn):
        config = db_get_config(self.guild.id)
        async def submit(inter, value):
            if not value.strip():
                db_set_config(self.guild.id, share_lock_role_id=None)
                await inter.response.send_message("✅ Share lock role removed — channel stays always open.", ephemeral=True)
                await self._refresh(interaction)
                return
            role_id = parse_role_id(value)
            if not role_id:
                await inter.response.send_message("❌ Invalid role. Mention it or paste its ID.", ephemeral=True)
                return
            db_set_config(self.guild.id, share_lock_role_id=role_id)
            await inter.response.send_message(
                f"✅ Share lock role set to <@&{role_id}>.\n"
                "The share channel will be locked for this role when no video is active.", ephemeral=True)
            await self._refresh(interaction)
        await interaction.response.send_modal(Modal1("Set Share Lock Role",
            "Role mention or ID (empty = disable)",
            placeholder="@Member  or  1234567890",
            default=str(config.get("share_lock_role_id") or ""), required=False, callback=submit))

    @discord.ui.button(label="Set Prefix Role",        style=discord.ButtonStyle.blurple, row=1)
    async def btn_prefix_role(self, interaction: discord.Interaction, btn):
        config = db_get_config(self.guild.id)
        async def submit(inter, value):
            if not value.strip():
                db_set_config(self.guild.id, prefix_role_id=None)
                await inter.response.send_message("✅ Prefix role removed.", ephemeral=True)
                await self._refresh(interaction)
                return
            role_id = parse_role_id(value)
            if not role_id:
                await inter.response.send_message("❌ Invalid role. Mention it or paste its ID.", ephemeral=True)
                return
            db_set_config(self.guild.id, prefix_role_id=role_id)
            await inter.response.send_message(f"✅ Prefix role set to <@&{role_id}>", ephemeral=True)
            await self._refresh(interaction)
        await interaction.response.send_modal(Modal1("Set Prefix Role",
            "Role mention or ID (empty = remove)",
            placeholder="@404-Member  or  1234567890",
            default=str(config.get("prefix_role_id") or ""), required=False, callback=submit))

    @discord.ui.button(label="Set Prefix Text",        style=discord.ButtonStyle.blurple, row=1)
    async def btn_prefix_text(self, interaction: discord.Interaction, btn):
        config = db_get_config(self.guild.id)
        async def submit(inter, value):
            prefix = value.strip() or "404 | "
            db_set_config(self.guild.id, nick_prefix=prefix)
            await inter.response.send_message(f"✅ Nickname prefix set to `{prefix}`", ephemeral=True)
            await self._refresh(interaction)
        await interaction.response.send_modal(Modal1("Set Nickname Prefix",
            "Prefix text (leave empty to reset to default)",
            placeholder="404 | ",
            default=config.get("nick_prefix") or "404 | ",
            required=False, callback=submit))

    @discord.ui.button(label="⚡ Apply Prefix Now",   style=discord.ButtonStyle.green, row=2)
    async def btn_apply_prefix(self, interaction: discord.Interaction, btn):
        """Batch-apply (or remove) the prefix to all current members based on role membership."""
        config = db_get_config(self.guild.id)
        prefix_role_id = config.get("prefix_role_id")
        nick_prefix    = config.get("nick_prefix") or "404 | "
        if not prefix_role_id:
            await interaction.response.send_message(
                "❌ No prefix role configured. Set one with **Set Prefix Role** first.", ephemeral=True)
            return
        role = self.guild.get_role(prefix_role_id)
        if not role:
            await interaction.response.send_message(
                "❌ Prefix role not found in this server.", ephemeral=True)
            return
        await interaction.response.send_message(
            f"⏳ Applying prefix `{nick_prefix}` to all members with **{role.name}** "
            f"and removing it from those without…", ephemeral=True)
        done = 0
        for member in self.guild.members:
            if member.bot or member.id == self.guild.owner_id:
                continue
            has_role = any(r.id == prefix_role_id for r in member.roles)
            await apply_nick_prefix(self.guild, member, add=has_role)
            done += 1
        await interaction.edit_original_response(
            content=f"✅ Done — processed **{done}** members.")

# ══════════════════════════════════════════════════════════════
#  /admin — PANEL
# ══════════════════════════════════════════════════════════════

# ── Clean /config → Shop menus ─────────────────────────────────
# The older shop view above is kept as a compatibility reference for
# existing sessions, but all new /config panels use the grouped views below.

def _shop_item_options(items: list, config: dict, description_fn=None) -> list:
    options = []
    for item in items[:25]:
        description = description_fn(item) if description_fn else "Choose this item"
        options.append(discord.SelectOption(
            label=f"{item['name'][:70]}  —  {cur(config, item['price'])}"[:100],
            description=str(description)[:100],
            value=str(item["id"]),
        ))
    return options


class ShopEditMenu(_SubMenu):
    def build_embed(self, config: dict) -> discord.Embed:
        items = db_get_shop_items(self.guild.id)
        e = E("🛒 Shop · Edit Items", color=C_GOLD)
        e.description = (
            f"**{len(items)} item(s)** configured.\n"
            "Choose an action below to update an existing item."
        )
        if items:
            e.add_field(
                name="Available actions",
                value=(
                    "✏️ Name and price\n"
                    "🖼️ Image and provider\n"
                    "⏳ Duration and listing expiry\n"
                    "↕️ Display order"
                ),
                inline=False,
            )
        else:
            e.description += "\nAdd an item first from the Shop menu."
        return e

    async def _pick_item(self, interaction, placeholder, description_fn, callback):
        items = db_get_shop_items(self.guild.id)
        if not items:
            await interaction.response.send_message("❌ Shop is empty.", ephemeral=True)
            return
        config = db_get_config(self.guild.id)
        select = discord.ui.Select(
            placeholder=placeholder,
            options=_shop_item_options(items, config, description_fn),
        )
        view = discord.ui.View(timeout=120)

        async def on_select(inter2):
            if inter2.user.id != self.author_id:
                await inter2.response.send_message("❌ Not your panel.", ephemeral=True)
                return
            try:
                item_id = int(select.values[0])
                chosen = next((item for item in items if item["id"] == item_id), None)
                if not chosen:
                    await inter2.response.send_message("❌ Item not found.", ephemeral=True)
                    return
                await callback(interaction, inter2, chosen)
            except Exception as exc:
                print(f"[Shop edit select error] {exc}")
                if not inter2.response.is_done():
                    await inter2.response.send_message(
                        "❌ Could not open the editor. Please try again.",
                        ephemeral=True,
                    )

        select.callback = on_select
        view.add_item(select)
        await interaction.response.send_message(
            f"🛒 {placeholder}.",
            view=view,
            ephemeral=True,
        )

    @discord.ui.button(label="✏️ Edit Name", style=discord.ButtonStyle.blurple, row=0)
    async def btn_name(self, interaction, btn):
        async def selected(parent, inter2, item):
            async def submit(inter3, value):
                new_name = value.strip()
                if not new_name:
                    await inter3.response.send_message("❌ Name cannot be empty.", ephemeral=True)
                    return
                db_set_shop_item_name(item["id"], self.guild.id, new_name)
                await inter3.response.send_message(
                    f"✅ Renamed to **{new_name}**.",
                    ephemeral=True,
                )
                await self._refresh(parent)
            await inter2.response.send_modal(Modal1(
                "Edit Item Name",
                "New item name",
                placeholder=item["name"][:100],
                default=item["name"],
                max_length=80,
                callback=submit,
            ))
        await self._pick_item(
            interaction,
            "Choose an item to rename",
            lambda item: "Edit the display name",
            selected,
        )

    @discord.ui.button(label="💰 Edit Price", style=discord.ButtonStyle.blurple, row=0)
    async def btn_price(self, interaction, btn):
        async def selected(parent, inter2, item):
            config = db_get_config(self.guild.id)
            async def submit(inter3, value):
                try:
                    price = int(value.strip())
                    if price <= 0:
                        raise ValueError
                except ValueError:
                    await inter3.response.send_message(
                        "❌ Price must be a positive whole number.",
                        ephemeral=True,
                    )
                    return
                db_set_shop_item_price(item["id"], self.guild.id, price)
                await inter3.response.send_message(
                    f"✅ **{item['name']}** price updated to **{cur(config, price)}**.",
                    ephemeral=True,
                )
                await self._refresh(parent)
            await inter2.response.send_modal(Modal1(
                "Edit Item Price",
                f"New price in {config.get('currency_name') or 'Gems'}",
                placeholder="100",
                default=str(item["price"]),
                callback=submit,
            ))
        await self._pick_item(
            interaction,
            "Choose an item to edit its price",
            lambda item: "Update the purchase price",
            selected,
        )

    @discord.ui.button(label="🖼️ Set Image", style=discord.ButtonStyle.blurple, row=0)
    async def btn_image(self, interaction, btn):
        async def selected(parent, inter2, item):
            async def submit(inter3, value):
                value = value.strip()
                db_update_shop_image(item["id"], self.guild.id, value or None)
                await inter3.response.send_message(
                    f"✅ Image {'updated' if value else 'removed'} for **{item['name']}**.",
                    ephemeral=True,
                )
                await self._refresh(parent)
            await inter2.response.send_modal(Modal1(
                "Edit Item Image",
                "Image URL (empty = remove)",
                placeholder="https://example.com/image.png",
                default=item.get("image_url") or "",
                required=False,
                callback=submit,
            ))
        await self._pick_item(
            interaction,
            "Choose an item to edit its image",
            lambda item: "Paste a direct image URL",
            selected,
        )

    @discord.ui.button(label="🤝 Set Provider", style=discord.ButtonStyle.grey, row=1)
    async def btn_provider(self, interaction, btn):
        async def selected(parent, inter2, item):
            async def submit(inter3, value):
                value = value.strip()
                conn = get_db()
                conn.execute(
                    "UPDATE shop_items SET provided_by=? WHERE id=? AND guild_id=?",
                    (value or None, item["id"], self.guild.id),
                )
                conn.commit()
                conn.close()
                await inter3.response.send_message(
                    f"✅ Provider {'updated' if value else 'removed'} for **{item['name']}**.",
                    ephemeral=True,
                )
                await self._refresh(parent)
            await inter2.response.send_modal(Modal1(
                "Edit Item Provider",
                "Provided by (empty = remove)",
                placeholder="Creator or server name",
                default=item.get("provided_by") or "",
                required=False,
                callback=submit,
            ))
        await self._pick_item(
            interaction,
            "Choose an item to edit its provider",
            lambda item: "Change the provider credit",
            selected,
        )

    @discord.ui.button(label="⏳ Edit Duration", style=discord.ButtonStyle.blurple, row=1)
    async def btn_duration(self, interaction, btn):
        async def selected(parent, inter2, item):
            async def submit(inter3, value):
                try:
                    days = int(value.strip())
                    if days < 0:
                        raise ValueError
                except ValueError:
                    await inter3.response.send_message(
                        "❌ Enter 0 (permanent) or a positive number of days.",
                        ephemeral=True,
                    )
                    return
                conn = get_db()
                conn.execute(
                    "UPDATE shop_items SET is_temporary=?, duration_days=? "
                    "WHERE id=? AND guild_id=?",
                    (1 if days else 0, days or None, item["id"], self.guild.id),
                )
                conn.commit()
                conn.close()
                status = "permanent" if not days else f"{days} days"
                await inter3.response.send_message(
                    f"✅ **{item['name']}** duration set to **{status}**.",
                    ephemeral=True,
                )
                await self._refresh(parent)
            await inter2.response.send_modal(Modal1(
                "Edit Item Duration",
                "Duration in days (0 = permanent)",
                placeholder="0 or 30",
                default=str(item.get("duration_days") or 0),
                callback=submit,
            ))
        await self._pick_item(
            interaction,
            "Choose an item to edit its duration",
            lambda item: f"Current: {item.get('duration_days') or 0} day(s)",
            selected,
        )

    @discord.ui.button(label="📅 Listing Expiry", style=discord.ButtonStyle.grey, row=1)
    async def btn_listing_expiry(self, interaction, btn):
        async def selected(parent, inter2, item):
            current = (item.get("item_expires_at") or "")[:10]
            async def submit(inter3, value):
                value = value.strip()
                conn = get_db()
                if not value:
                    conn.execute(
                        "UPDATE shop_items SET item_expires_at=NULL WHERE id=? AND guild_id=?",
                        (item["id"], self.guild.id),
                    )
                    message = f"✅ Listing expiry removed from **{item['name']}**."
                else:
                    try:
                        from datetime import date as _date
                        parsed = _date.fromisoformat(value)
                    except ValueError:
                        conn.close()
                        await inter3.response.send_message(
                            "❌ Use the date format **YYYY-MM-DD**.",
                            ephemeral=True,
                        )
                        return
                    conn.execute(
                        "UPDATE shop_items SET item_expires_at=? WHERE id=? AND guild_id=?",
                        (parsed.isoformat() + "T23:59:59", item["id"], self.guild.id),
                    )
                    message = f"✅ **{item['name']}** listing expires on **{parsed.isoformat()}**."
                conn.commit()
                conn.close()
                await inter3.response.send_message(message, ephemeral=True)
                await self._refresh(parent)
            await inter2.response.send_modal(Modal1(
                "Listing Expiry",
                "Date YYYY-MM-DD (empty = never)",
                placeholder="2026-12-31",
                default=current,
                required=False,
                callback=submit,
            ))
        await self._pick_item(
            interaction,
            "Choose an item to edit its listing expiry",
            lambda item: f"Current: {(item.get('item_expires_at') or 'never')[:10]}",
            selected,
        )

    @discord.ui.button(label="↕️ Reorder Items", style=discord.ButtonStyle.blurple, row=2)
    async def btn_reorder(self, interaction, btn):
        items = db_get_shop_items(self.guild.id)
        if len(items) < 2:
            await interaction.response.send_message(
                "❌ Need at least 2 items to reorder.",
                ephemeral=True,
            )
            return
        config = db_get_config(self.guild.id)
        select = discord.ui.Select(
            placeholder="Choose an item to move",
            options=[
                discord.SelectOption(
                    label=f"#{index}  {item['name'][:60]}  — {cur(config, item['price'])}",
                    value=str(item["id"]),
                )
                for index, item in enumerate(items[:25], 1)
            ],
        )
        view = discord.ui.View(timeout=120)
        parent = interaction

        async def on_select(inter2):
            if inter2.user.id != self.author_id:
                await inter2.response.send_message("❌ Not your panel.", ephemeral=True)
                return
            item_id = int(select.values[0])
            positions = discord.ui.Select(
                placeholder="Choose the new position",
                options=[
                    discord.SelectOption(label=f"Position #{pos}", value=str(pos))
                    for pos in range(1, min(len(items), 25) + 1)
                ],
            )
            position_view = discord.ui.View(timeout=120)

            async def on_position(inter3):
                current = db_get_shop_items(self.guild.id)
                moved = next((item for item in current if item["id"] == item_id), None)
                ordered = [item for item in current if item["id"] != item_id]
                new_position = int(positions.values[0])
                if moved:
                    ordered.insert(new_position - 1, moved)
                    db_reorder_shop_items(
                        self.guild.id,
                        [item["id"] for item in ordered],
                    )
                await inter3.response.send_message(
                    f"✅ **{moved['name'] if moved else 'Item'}** moved to position **#{new_position}**.",
                    ephemeral=True,
                )
                await self._refresh(parent)

            positions.callback = on_position
            position_view.add_item(positions)
            await inter2.response.send_message(
                "↕️ Choose the new position.",
                view=position_view,
                ephemeral=True,
            )

        select.callback = on_select
        view.add_item(select)
        await interaction.response.send_message(
            "↕️ Choose the item to move.",
            view=view,
            ephemeral=True,
        )

    @discord.ui.button(label="← Back to Shop", style=discord.ButtonStyle.grey, row=2)
    async def btn_shop(self, interaction, btn):
        shop = ConfigShopMenu(self.guild, self.author_id)
        await interaction.response.edit_message(
            embed=shop.build_embed(db_get_config(self.guild.id)),
            view=shop,
        )


class ShopOptionsMenu(_SubMenu):
    def build_embed(self, config: dict) -> discord.Embed:
        e = E("🛒 Shop · Item Options", color=C_GOLD)
        e.description = (
            "Control how items behave and what members can see in `/shop`.\n"
            "These settings apply to one selected item at a time."
        )
        e.add_field(
            name="Visibility",
            value="Expiry, stock count, and purchase-limit display",
            inline=False,
        )
        e.add_field(
            name="Purchase rules",
            value="Owner approval and per-member purchase limits",
            inline=False,
        )
        return e

    async def _toggle_item(self, interaction, placeholder, column, empty_message,
                           enabled_text, disabled_text, filter_fn=None):
        items = db_get_shop_items(self.guild.id)
        if filter_fn:
            items = [item for item in items if filter_fn(item)]
        if not items:
            await interaction.response.send_message(empty_message, ephemeral=True)
            return
        config = db_get_config(self.guild.id)
        select = discord.ui.Select(
            placeholder=placeholder,
            options=_shop_item_options(items, config),
        )
        view = discord.ui.View(timeout=120)
        parent = interaction

        async def on_select(inter2):
            if inter2.user.id != self.author_id:
                await inter2.response.send_message("❌ Not your panel.", ephemeral=True)
                return
            item_id = int(select.values[0])
            chosen = next((item for item in items if item["id"] == item_id), None)
            if not chosen:
                await inter2.response.send_message("❌ Item not found.", ephemeral=True)
                return
            new_value = 0 if chosen.get(column) else 1
            conn = get_db()
            conn.execute(
                f"UPDATE shop_items SET {column}=? WHERE id=? AND guild_id=?",
                (new_value, item_id, self.guild.id),
            )
            conn.commit()
            conn.close()
            message = enabled_text if new_value else disabled_text
            await inter2.response.send_message(
                f"{message} for **{chosen['name']}**.",
                ephemeral=True,
            )
            await self._refresh(parent)

        select.callback = on_select
        view.add_item(select)
        await interaction.response.send_message(
            f"🛒 {placeholder}.",
            view=view,
            ephemeral=True,
        )

    @discord.ui.button(label="⏳ Show/Hide Expiry", style=discord.ButtonStyle.grey, row=0)
    async def btn_expiry_visibility(self, interaction, btn):
        await self._toggle_item(
            interaction,
            "Choose a temporary item",
            "show_duration",
            "❌ No temporary items are configured.",
            "👁️ Expiry is now shown",
            "🔇 Expiry is now hidden",
            lambda item: bool(item.get("is_temporary")),
        )

    @discord.ui.button(label="📦 Show/Hide Stock", style=discord.ButtonStyle.grey, row=0)
    async def btn_stock_visibility(self, interaction, btn):
        await self._toggle_item(
            interaction,
            "Choose an item with limited stock",
            "show_stock",
            "❌ No items have limited stock configured.",
            "👁️ Stock count is now shown",
            "🔇 Stock count is now hidden",
            lambda item: item.get("stock") is not None,
        )

    @discord.ui.button(label="🔒 Require Approval", style=discord.ButtonStyle.grey, row=1)
    async def btn_approval(self, interaction, btn):
        await self._toggle_item(
            interaction,
            "Choose an item to toggle approval",
            "requires_approval",
            "❌ Shop is empty.",
            "🔒 Owner approval is now required",
            "🟢 Item is now instant purchase",
        )

    @discord.ui.button(label="🔢 Buy Limit", style=discord.ButtonStyle.grey, row=1)
    async def btn_buy_limit(self, interaction, btn):
        items = db_get_shop_items(self.guild.id)
        if not items:
            await interaction.response.send_message("❌ Shop is empty.", ephemeral=True)
            return
        config = db_get_config(self.guild.id)
        select = discord.ui.Select(
            placeholder="Choose an item to set a purchase limit",
            options=_shop_item_options(
                items,
                config,
                lambda item: f"Current: {item.get('purchase_limit') or 'unlimited'}",
            ),
        )
        view = discord.ui.View(timeout=120)
        parent = interaction

        async def on_select(inter2):
            if inter2.user.id != self.author_id:
                await inter2.response.send_message("❌ Not your panel.", ephemeral=True)
                return
            item_id = int(select.values[0])
            chosen = next((item for item in items if item["id"] == item_id), None)
            if not chosen:
                await inter2.response.send_message("❌ Item not found.", ephemeral=True)
                return
            async def submit(inter3, value):
                value = value.strip()
                if not value or value == "0":
                    limit = None
                else:
                    try:
                        limit = int(value)
                        if limit < 1:
                            raise ValueError
                    except ValueError:
                        await inter3.response.send_message(
                            "❌ Enter a positive number, or 0 for unlimited.",
                            ephemeral=True,
                        )
                        return
                conn = get_db()
                conn.execute(
                    "UPDATE shop_items SET purchase_limit=? WHERE id=? AND guild_id=?",
                    (limit, item_id, self.guild.id),
                )
                conn.commit()
                conn.close()
                result = "unlimited" if limit is None else str(limit)
                await inter3.response.send_message(
                    f"✅ **{chosen['name']}** purchase limit set to **{result}** per member.",
                    ephemeral=True,
                )
                await self._refresh(parent)
            await inter2.response.send_modal(Modal1(
                "Purchase Limit",
                "Max purchases per member (0 = unlimited)",
                placeholder="1, 3, or 0",
                default=str(chosen.get("purchase_limit") or ""),
                required=False,
                callback=submit,
            ))

        select.callback = on_select
        view.add_item(select)
        await interaction.response.send_message(
            "🔢 Choose an item and set its purchase limit.",
            view=view,
            ephemeral=True,
        )

    @discord.ui.button(label="← Back to Shop", style=discord.ButtonStyle.grey, row=2)
    async def btn_shop(self, interaction, btn):
        shop = ConfigShopMenu(self.guild, self.author_id)
        await interaction.response.edit_message(
            embed=shop.build_embed(db_get_config(self.guild.id)),
            view=shop,
        )


class ShopRewardsMenu(_SubMenu):
    def build_embed(self, config: dict) -> discord.Embed:
        items = db_get_shop_items(self.guild.id)
        e = E("🛒 Shop · Rewards & Stock", color=C_GOLD)
        e.description = (
            "Pre-load links or codes so purchases can receive a reward automatically."
        )
        if items:
            e.add_field(
                name="Current reward stock",
                value="\n".join(
                    f"**{item['name']}** — 🔑 {db_count_available_rewards(item['id'], self.guild.id)} available"
                    for item in items[:10]
                )[:1024],
                inline=False,
            )
        else:
            e.description += "\nAdd an item first from the Shop menu."
        return e

    @discord.ui.button(label="🔑 Add Rewards", style=discord.ButtonStyle.green, row=0)
    async def btn_add_rewards(self, interaction, btn):
        items = db_get_shop_items(self.guild.id)
        if not items:
            await interaction.response.send_message("❌ Shop is empty.", ephemeral=True)
            return
        config = db_get_config(self.guild.id)
        select = discord.ui.Select(
            placeholder="Choose an item to add rewards",
            options=_shop_item_options(
                items,
                config,
                lambda item: f"{db_count_available_rewards(item['id'], self.guild.id)} available",
            ),
        )
        view = discord.ui.View(timeout=120)
        parent = interaction

        async def on_select(inter2):
            if inter2.user.id != self.author_id:
                await inter2.response.send_message("❌ Not your panel.", ephemeral=True)
                return
            item_id = int(select.values[0])
            chosen = next((item for item in items if item["id"] == item_id), None)
            if not chosen:
                await inter2.response.send_message("❌ Item not found.", ephemeral=True)
                return
            async def submit(inter3, value):
                entries = [line.strip() for line in value.splitlines() if line.strip()]
                if not entries:
                    entries = [entry.strip() for entry in value.split() if entry.strip()]
                if not entries:
                    await inter3.response.send_message("❌ No valid rewards entered.", ephemeral=True)
                    return
                for entry in entries:
                    db_add_item_reward(item_id, self.guild.id, entry)
                await inter3.response.send_message(
                    f"✅ Added **{len(entries)}** reward(s) to **{chosen['name']}**.",
                    ephemeral=True,
                )
                await self._refresh(parent)
            await inter2.response.send_modal(Modal1(
                "Add Item Rewards",
                "One reward per line",
                placeholder="CODE-ABC or https://example.com/reward",
                max_length=4000,
                paragraph=True,
                callback=submit,
            ))

        select.callback = on_select
        view.add_item(select)
        await interaction.response.send_message(
            "🔑 Choose an item, then enter one reward per line.",
            view=view,
            ephemeral=True,
        )

    @discord.ui.button(label="📊 Stock Overview", style=discord.ButtonStyle.grey, row=0)
    async def btn_stock(self, interaction, btn):
        items = db_get_shop_items(self.guild.id)
        if not items:
            await interaction.response.send_message("❌ Shop is empty.", ephemeral=True)
            return
        lines = []
        for item in items:
            rewards = db_get_item_rewards(item["id"], self.guild.id)
            available = db_count_available_rewards(item["id"], self.guild.id)
            used = sum(1 for reward in rewards if reward["used"])
            lines.append(
                f"**{item['name']}** — {available} available / {used} used"
                if rewards else f"**{item['name']}** — no pre-loaded rewards"
            )
        await interaction.response.send_message(
            embed=E("📊 Reward Stock Overview", "\n".join(lines)[:4000], C_GOLD),
            ephemeral=True,
        )

    @discord.ui.button(label="← Back to Shop", style=discord.ButtonStyle.grey, row=1)
    async def btn_shop(self, interaction, btn):
        shop = ConfigShopMenu(self.guild, self.author_id)
        await interaction.response.edit_message(
            embed=shop.build_embed(db_get_config(self.guild.id)),
            view=shop,
        )


class ConfigShopMenu(_SubMenu):
    def build_embed(self, config: dict) -> discord.Embed:
        items = db_get_shop_items(self.guild.id)
        c_name = config.get("currency_name") or "Gems"
        e = E("🛒 Shop Settings", color=C_GOLD)
        e.description = (
            f"Manage the member shop in one place.\n"
            f"**{len(items)} item(s)** configured using {c_name}."
        )
        if items:
            for item in items[:8]:
                tags = []
                if item.get("is_temporary"):
                    tags.append(f"⏳ {item.get('duration_days')}d")
                if item.get("image_url"):
                    tags.append("🖼️")
                if item.get("requires_text"):
                    tags.append("📝")
                e.add_field(
                    name=item["name"],
                    value=f"**{cur(config, item['price'])}**"
                    + (f" · {' '.join(tags)}" if tags else ""),
                    inline=True,
                )
            if len(items) > 8:
                e.add_field(
                    name="More items",
                    value=f"{len(items) - 8} more — use **View All**.",
                    inline=False,
                )
        else:
            e.add_field(
                name="Getting started",
                value="Use **Add Item** to create the first shop item.",
                inline=False,
            )
        e.set_footer(text="Use the grouped menus below to keep shop management simple.")
        return e

    async def _open(self, interaction, view):
        await interaction.response.edit_message(
            embed=view.build_embed(db_get_config(self.guild.id)),
            view=view,
        )

    @discord.ui.button(label="➕ Add Item", style=discord.ButtonStyle.green, row=0)
    async def btn_add(self, interaction, btn):
        config = db_get_config(self.guild.id)
        async def submit(inter, name, price, stock, duration, text_label):
            try:
                parsed_price = int(price)
                parsed_duration = int(duration)
                parsed_stock = int(stock.strip()) if stock.strip() else 0
                if parsed_price <= 0 or parsed_duration < 0 or parsed_stock < 0:
                    raise ValueError
            except ValueError:
                await inter.response.send_message(
                    "❌ Price must be positive; duration and stock must be 0 or greater.",
                    ephemeral=True,
                )
                return
            item_id = db_add_shop_item(
                self.guild.id,
                name.strip(),
                parsed_price,
                None,
                1 if parsed_duration else 0,
                parsed_duration or None,
                1,
                1 if text_label.strip() else 0,
                text_label.strip() or None,
                stock=parsed_stock or None,
            )
            await inter.response.send_message(
                f"✅ Added **{name.strip()}** for **{cur(config, parsed_price)}** "
                f"(ID: `{item_id}`).\n"
                "Use **Edit Items → Set Image** if you want to add an image.",
                ephemeral=True,
            )
            await self._refresh(interaction)
        await interaction.response.send_modal(Modal5(
            "Add Shop Item",
            currency_label=config.get("currency_name") or "Gems",
            callback=submit,
        ))

    @discord.ui.button(label="🗑️ Remove Item", style=discord.ButtonStyle.red, row=0)
    async def btn_remove(self, interaction, btn):
        items = db_get_shop_items(self.guild.id)
        if not items:
            await interaction.response.send_message("❌ Shop is already empty.", ephemeral=True)
            return
        config = db_get_config(self.guild.id)
        select = discord.ui.Select(
            placeholder="Choose an item to remove",
            options=_shop_item_options(items, config, lambda item: "Permanently delete this item"),
        )
        view = discord.ui.View(timeout=120)

        async def on_select(inter2):
            if inter2.user.id != self.author_id:
                await inter2.response.send_message("❌ Not your panel.", ephemeral=True)
                return
            item = db_get_shop_item(int(select.values[0]), self.guild.id)
            if not item:
                await inter2.response.send_message("❌ Item not found.", ephemeral=True)
                return
            confirm = ConfirmView(self.author_id)
            await inter2.response.send_message(
                f"⚠️ Remove **{item['name']}** permanently?",
                view=confirm,
                ephemeral=True,
            )
            await confirm.wait()
            if confirm.value:
                db_remove_shop_item(item["id"], self.guild.id)
                await inter2.followup.send("✅ Item removed.", ephemeral=True)
                await self._refresh(interaction)
            else:
                await inter2.followup.send("Cancelled.", ephemeral=True)

        select.callback = on_select
        view.add_item(select)
        await interaction.response.send_message(
            "🗑️ Choose the item to remove.",
            view=view,
            ephemeral=True,
        )

    @discord.ui.button(label="📋 View All", style=discord.ButtonStyle.grey, row=0)
    async def btn_view(self, interaction, btn):
        items = db_get_shop_items(self.guild.id)
        if not items:
            await interaction.response.send_message("The shop is empty.", ephemeral=True)
            return
        config = db_get_config(self.guild.id)
        lines = []
        for item in items:
            tags = []
            if item.get("is_temporary"):
                tags.append(f"⏳{item.get('duration_days')}d")
            if item.get("requires_text"):
                tags.append("📝")
            if item.get("image_url"):
                tags.append("🖼️")
            if item.get("requires_approval"):
                tags.append("🔒")
            if item.get("purchase_limit"):
                tags.append(f"🔢{item['purchase_limit']}")
            lines.append(
                f"`{item['id']}` **{item['name']}** — {cur(config, item['price'])}"
                + (f"  {' '.join(tags)}" if tags else "")
            )
        await interaction.response.send_message(
            embed=E("🛒 All Shop Items", "\n".join(lines)[:4000], C_GOLD),
            ephemeral=True,
        )

    @discord.ui.button(label="✏️ Edit Items", style=discord.ButtonStyle.blurple, row=1)
    async def btn_edit(self, interaction, btn):
        await self._open(interaction, ShopEditMenu(self.guild, self.author_id))

    @discord.ui.button(label="⚙️ Item Options", style=discord.ButtonStyle.blurple, row=1)
    async def btn_options(self, interaction, btn):
        await self._open(interaction, ShopOptionsMenu(self.guild, self.author_id))

    @discord.ui.button(label="🔑 Rewards & Stock", style=discord.ButtonStyle.green, row=1)
    async def btn_rewards(self, interaction, btn):
        await self._open(interaction, ShopRewardsMenu(self.guild, self.author_id))

    @discord.ui.button(label="🔄 Post Shop Now", style=discord.ButtonStyle.green, row=2)
    async def btn_post(self, interaction, btn):
        # Reuse the existing posting implementation through the same
        # configured channels, without exposing shop management in /admin.
        await interaction.response.defer(ephemeral=True)
        config = db_get_config(self.guild.id)
        items = db_get_shop_items(self.guild.id)
        if not items:
            await interaction.followup.send("❌ The shop is empty — add items first.", ephemeral=True)
            return
        channel_id = (
            config.get("daily_shop_channel_id")
            or config.get("shop_channel_id")
            or config.get("commands_channel_id")
        )
        channel = interaction.client.get_channel(channel_id) if channel_id else None
        if not channel:
            await interaction.followup.send(
                "❌ No shop channel configured. Set one in `/config → 💬 Channels`.",
                ephemeral=True,
            )
            return
        currency_name = config.get("currency_name") or "Gems"
        currency_emoji = config.get("currency_emoji") or "💎"
        shop_channel = config.get("shop_channel_id") or config.get("commands_channel_id")
        embeds = [discord.Embed(
            title="🛍️ Shop Update",
            description=f"Use `/shop` in <#{shop_channel}> to buy!",
            color=C_GOLD,
        )]
        now_iso = datetime.utcnow().isoformat()
        for item in items:
            if item.get("item_expires_at") and item["item_expires_at"] < now_iso:
                continue
            embed = discord.Embed(
                title=item["name"],
                description=f"{currency_emoji} **{item['price']:,} {currency_name}**",
                color=C_GOLD,
            )
            if item.get("image_url"):
                embed.set_image(url=item["image_url"])
            embeds.append(embed)
        try:
            for start in range(0, len(embeds), 10):
                await channel.send(embeds=embeds[start:start + 10])
            await interaction.followup.send(
                f"✅ Shop posted to <#{channel.id}>.",
                ephemeral=True,
            )
        except discord.Forbidden:
            await interaction.followup.send(
                f"❌ Missing permission to post in <#{channel.id}>.",
                ephemeral=True,
            )

# ══════════════════════════════════════════════════════════════
#  COMMUNITY CONFIG SUBMENU (Boost Announce + Revive Ping)
# ══════════════════════════════════════════════════════════════

async def send_ping_role_message(channel, kind: str, guild_id: int) -> bool:
    """Publish the reusable Revive/Drops role opt-in message."""
    config = db_get_config(guild_id)
    revive_role = config.get("revive_ping_role_id")
    drops_role = config.get("drops_ping_role_id")
    if kind == "revive":
        roles = [("🔔 Revive notifications", revive_role,
                  "Get pinged when the chat needs a boost.")]
        title = "🔔 Revive Notifications"
        description = "Get a ping when the chat needs a boost."
    elif kind == "drops":
        roles = [("🎁 Drops notifications", drops_role,
                  "Get pinged when new skin or item links are posted.")]
        title = "🎁 Drops Notifications"
        description = "Get a ping when new skin or item links are posted."
    else:
        roles = [
            ("🔔 Revive notifications", revive_role,
             "Get pinged when the chat needs a boost."),
            ("🎁 Drops notifications", drops_role,
             "Get pinged when new skin or item links are posted."),
        ]
        title = "📣 Community Notifications"
        description = "Choose the notifications you want to receive."
    if not any(role_id for _, role_id, _ in roles):
        return False

    embed = E(title, description, C_INFO)
    for field_name, role_id, field_description in roles:
        if role_id:
            embed.add_field(
                name=field_name,
                value=f"<@&{role_id}>\n{field_description}",
                inline=False,
            )
    embed.set_footer(text="Click a button below to get or remove a role.")
    try:
        await channel.send(
            embed=embed,
            view=RevivePingView(
                guild_id,
                revive_role or drops_role or 0,
                mode=kind,
            ),
            allowed_mentions=discord.AllowedMentions(roles=False),
        )
        return True
    except Exception as ex:
        print(f"[PingRoles] Failed to post in {getattr(channel, 'id', '?')}: {ex}")
        return False

class ConfigCommunityMenu(_SubMenu):
    """Combined menu for boosts, server tags, and notification-role tools."""

    def build_embed(self, config: dict) -> discord.Embed:
        _on   = lambda v: "✅ Enabled" if v else "❌ Disabled"
        _role = lambda rid: f"<@&{rid}>" if rid else "`Not set`"
        _ch   = lambda cid: f"<#{cid}>" if cid else "`Not set`"
        channels_raw = config.get("revive_ping_channels") or "[]"
        try:
            ch_ids = json.loads(channels_raw)
        except Exception:
            ch_ids = []
        ch_list = ", ".join(f"<#{c}>" for c in ch_ids) if ch_ids else "`None configured`"
        boost_ch = config.get("boost_announce_channel_id") or config.get("notification_channel_id")
        e = E("🔔 Community Settings", color=C_ACHIEVE)
        # ── Boost Announce ─────────────────────────────
        e.add_field(name="─── 🚀 Boost Announce ───", value="\u200b", inline=False)
        e.add_field(name="📢 Announce Channel",
                    value=f"<#{boost_ch}>" if boost_ch else "`Notifications channel`", inline=True)
        e.add_field(name="📣 Mention Role",
                    value=_role(config.get("boost_announce_role_id")), inline=True)
        e.add_field(name="⏱️ Rate Limit", value="**1 per hour**", inline=True)
        # ── Server Tag ─────────────────────────────────
        e.add_field(name="─── 🏷️ Server Tag Reward ───", value="\u200b", inline=False)
        e.add_field(name="Server Tag Reward",
                    value=_on(config.get("server_tag_enabled", 0)), inline=True)
        e.add_field(name="Tag Reward Amount",
                    value=f"**{cur(config, config.get('server_tag_xp', 100))}**", inline=True)
        e.add_field(name="\u200b", value="\u200b", inline=True)
        # ── Revive Ping ────────────────────────────────
        e.add_field(name="─── 📣 Community Notifications ───", value="\u200b", inline=False)
        e.add_field(name="Daily Posting", value=_on(config.get("revive_ping_enabled", 0)), inline=True)
        e.add_field(name="Revive Role", value=_role(config.get("revive_ping_role_id")), inline=True)
        e.add_field(name="Drops Role", value=_role(config.get("drops_ping_role_id")), inline=True)
        e.add_field(name="Channels", value=ch_list, inline=False)
        e.set_footer(text=(
            "Boost: posts a thank-you when a member boosts (rate-limited 1×/hour)  ·  "
            "Server Tag: awards gems for enabling the server's clan tag  ·  "
            "Community Notifications: members can independently opt into Revive and Drops"
        ))
        return e

    def _parse_role(self, value: str):
        raw = value.strip().lstrip("<@&").rstrip(">")
        return int(raw) if raw.isdigit() else None

    def _parse_ch(self, value: str):
        raw = value.strip().lstrip("<#").rstrip(">")
        return int(raw) if raw.isdigit() else None

    def _get_revive_channels(self, config: dict) -> list:
        try:
            return json.loads(config.get("revive_ping_channels") or "[]")
        except Exception:
            return []

    # ── Row 0 · Boost Announce ────────────────────────────────
    @discord.ui.button(label="📢 Announce Channel", style=discord.ButtonStyle.blurple, row=0)
    async def btn_boost_channel(self, interaction: discord.Interaction, btn):
        config = db_get_config(self.guild.id)
        async def submit(inter, value):
            if not value.strip():
                db_set_config(self.guild.id, boost_announce_channel_id=None)
                await inter.response.send_message(
                    "✅ Boost announce channel cleared — will use Notifications channel.", ephemeral=True)
            else:
                cid = self._parse_ch(value)
                if not cid:
                    await inter.response.send_message("❌ Invalid channel.", ephemeral=True); return
                db_set_config(self.guild.id, boost_announce_channel_id=cid)
                await inter.response.send_message(
                    f"✅ Boost announcements will go to <#{cid}>.", ephemeral=True)
            await self._refresh(interaction)
        await interaction.response.send_modal(Modal1(
            title="Boost Announce Channel",
            label="Channel mention or ID (empty = Notifications)",
            placeholder="#boosts  or  1234567890",
            default=str(config.get("boost_announce_channel_id") or ""),
            required=False, callback=submit))

    @discord.ui.button(label="📣 Boost Mention Role", style=discord.ButtonStyle.blurple, row=0)
    async def btn_boost_role(self, interaction: discord.Interaction, btn):
        config = db_get_config(self.guild.id)
        async def submit(inter, value):
            if not value.strip():
                db_set_config(self.guild.id, boost_announce_role_id=None)
                await inter.response.send_message(
                    "✅ Boost mention role removed — no role will be pinged.", ephemeral=True)
            else:
                rid = self._parse_role(value)
                if not rid:
                    await inter.response.send_message("❌ Invalid role.", ephemeral=True); return
                db_set_config(self.guild.id, boost_announce_role_id=rid)
                await inter.response.send_message(
                    f"✅ Boost announcements will mention <@&{rid}>.", ephemeral=True)
            await self._refresh(interaction)
        await interaction.response.send_modal(Modal1(
            title="Boost Announce Role",
            label="Role mention or ID (empty = no ping)",
            placeholder="@Booster  or  1234567890",
            default=str(config.get("boost_announce_role_id") or ""),
            required=False, callback=submit))

    @discord.ui.button(label="🏷️ Toggle Server Tag", style=discord.ButtonStyle.green, row=0)
    async def btn_tag_toggle(self, interaction: discord.Interaction, btn):
        config  = db_get_config(self.guild.id)
        new_val = 0 if config.get("server_tag_enabled", 0) else 1
        db_set_config(self.guild.id, server_tag_enabled=new_val)
        await interaction.response.send_message(
            f"✅ Server tag reward {'**enabled**' if new_val else '**disabled**'}.", ephemeral=True)
        await self._refresh(interaction)

    @discord.ui.button(label="🏷️ Tag Reward Amount", style=discord.ButtonStyle.blurple, row=0)
    async def btn_tag_xp(self, interaction: discord.Interaction, btn):
        config = db_get_config(self.guild.id)
        async def submit(inter, value):
            try:
                xp = int(value)
                if xp < 0: raise ValueError
            except ValueError:
                await inter.response.send_message("❌ Enter a non-negative number.", ephemeral=True); return
            db_set_config(self.guild.id, server_tag_xp=xp)
            cfg2 = db_get_config(self.guild.id)
            await inter.response.send_message(
                f"✅ Server tag reward set to **{cur(cfg2, xp)}**.", ephemeral=True)
            await self._refresh(interaction)
        await interaction.response.send_modal(Modal1(
            "Server Tag Reward", "Gems awarded for enabling server tag",
            placeholder="100", default=str(config.get("server_tag_xp", 100)), callback=submit))

    # ── Row 1 · Revive Ping ───────────────────────────────────
    @discord.ui.button(label="Daily Posting", style=discord.ButtonStyle.blurple, row=1)
    async def btn_revive_toggle(self, interaction: discord.Interaction, btn):
        config  = db_get_config(self.guild.id)
        new_val = 0 if config.get("revive_ping_enabled", 0) else 1
        db_set_config(self.guild.id, revive_ping_enabled=new_val)
        await interaction.response.send_message(
            f"✅ Revive ping {'**enabled**' if new_val else '**disabled**'}.", ephemeral=True)
        await self._refresh(interaction)

    @discord.ui.button(label="🔔 Revive Role", style=discord.ButtonStyle.blurple, row=1)
    async def btn_revive_role(self, interaction: discord.Interaction, btn):
        config = db_get_config(self.guild.id)
        async def submit(inter, value):
            if not value.strip():
                db_set_config(self.guild.id, revive_ping_role_id=None)
                await inter.response.send_message("✅ Revive ping role removed.", ephemeral=True)
            else:
                rid = self._parse_role(value)
                if not rid:
                    await inter.response.send_message("❌ Invalid role.", ephemeral=True); return
                db_set_config(self.guild.id, revive_ping_role_id=rid)
                await inter.response.send_message(
                    f"✅ Revive ping role set to <@&{rid}>.", ephemeral=True)
            await self._refresh(interaction)
        await interaction.response.send_modal(Modal1(
            title="Revive Role",
            label="Role mention or ID (empty = remove)",
            placeholder="@revive  or  1234567890",
            default=str(config.get("revive_ping_role_id") or ""),
            required=False, callback=submit))

    @discord.ui.button(label="🎁 Drops Role", style=discord.ButtonStyle.blurple, row=1)
    async def btn_drops_role(self, interaction: discord.Interaction, btn):
        config = db_get_config(self.guild.id)
        async def submit(inter, value):
            role_id = parse_role_id(value) if value.strip() else None
            if value.strip() and not role_id:
                await inter.response.send_message("❌ Invalid role.", ephemeral=True)
                return
            db_set_config(self.guild.id, drops_ping_role_id=role_id)
            await inter.response.send_message(
                f"✅ Drops role {'set to <@&' + str(role_id) + '>' if role_id else 'removed'}.",
                ephemeral=True)
            await self._refresh(interaction)
        await interaction.response.send_modal(Modal1(
            title="Drops Role",
            label="Role mention or ID (empty = remove)",
            placeholder="@drops  or  1234567890",
            default=str(config.get("drops_ping_role_id") or ""),
            required=False, callback=submit))

    async def _send_manual_ping(self, interaction: discord.Interaction, kind: str):
        config = db_get_config(self.guild.id)
        role_key = "revive_ping_role_id" if kind == "revive" else "drops_ping_role_id"
        role_name = "Revive" if kind == "revive" else "Drops"
        if not config.get(role_key):
            await interaction.response.send_message(
                f"❌ Configure the {role_name} role first.", ephemeral=True)
            return

        async def submit(inter, value):
            channel_id = parse_channel_id(value)
            channel = self.guild.get_channel(channel_id) if channel_id else None
            if not channel or not hasattr(channel, "send"):
                await inter.response.send_message("❌ Invalid text channel.", ephemeral=True)
                return
            if await send_ping_role_message(channel, kind, self.guild.id):
                await inter.response.send_message(
                    f"✅ Community notification message sent in {channel.mention}.",
                    ephemeral=True)
            else:
                await inter.response.send_message(
                    "❌ The message could not be sent. Check channel permissions.",
                    ephemeral=True)
            await self._refresh(interaction)

        await interaction.response.send_modal(Modal1(
            title=f"Send {role_name} Message",
            label="Channel mention or ID",
            placeholder="#general  or  1234567890",
            callback=submit))

    @discord.ui.button(label="📣 Send Revive Message", style=discord.ButtonStyle.green, row=2)
    async def btn_send_revive(self, interaction: discord.Interaction, btn):
        await self._send_manual_ping(interaction, "revive")

    @discord.ui.button(label="🎁 Send Drops Message", style=discord.ButtonStyle.green, row=2)
    async def btn_send_drops(self, interaction: discord.Interaction, btn):
        await self._send_manual_ping(interaction, "drops")

    @discord.ui.button(label="➕ Add Revive Channel", style=discord.ButtonStyle.green, row=2)
    async def btn_revive_add_ch(self, interaction: discord.Interaction, btn):
        config = db_get_config(self.guild.id)
        async def submit(inter, value):
            ch_id = parse_channel_id(value)
            if not ch_id:
                await inter.response.send_message("❌ Invalid channel.", ephemeral=True); return
            ch_ids = self._get_revive_channels(config)
            if ch_id in ch_ids:
                await inter.response.send_message("⚠️ That channel is already in the list.", ephemeral=True); return
            ch_ids.append(ch_id)
            db_set_config(self.guild.id, revive_ping_channels=json.dumps(ch_ids))
            await inter.response.send_message(f"✅ <#{ch_id}> added to revive ping channels.", ephemeral=True)
            await self._refresh(interaction)
        await interaction.response.send_modal(Modal1(
            title="Add Revive Ping Channel", label="Channel mention or ID",
            placeholder="#general  or  1234567890", callback=submit))

    @discord.ui.button(label="➖ Remove Revive Channel", style=discord.ButtonStyle.red, row=2)
    async def btn_revive_remove_ch(self, interaction: discord.Interaction, btn):
        config = db_get_config(self.guild.id)
        async def submit(inter, value):
            ch_id = parse_channel_id(value)
            if not ch_id:
                await inter.response.send_message("❌ Invalid channel.", ephemeral=True); return
            ch_ids = self._get_revive_channels(config)
            if ch_id not in ch_ids:
                await inter.response.send_message("⚠️ That channel is not in the list.", ephemeral=True); return
            ch_ids.remove(ch_id)
            db_set_config(self.guild.id, revive_ping_channels=json.dumps(ch_ids))
            await inter.response.send_message(f"✅ <#{ch_id}> removed from revive ping channels.", ephemeral=True)
            await self._refresh(interaction)
        await interaction.response.send_modal(Modal1(
            title="Remove Revive Ping Channel", label="Channel mention or ID to remove",
            placeholder="#general  or  1234567890", callback=submit))

    # ← Back is inherited from _SubMenu


# ══════════════════════════════════════════════════════════════
#  /admin — PANEL
# ══════════════════════════════════════════════════════════════

def admin_main_embed(guild: discord.Guild) -> discord.Embed:
    e = E(f"🛠️ Admin Panel — {guild.name}", color=C_INFO)
    e.description = "Manage balances, announcements, backups, and community goals."
    return e

class AdminMainMenu(discord.ui.View):
    def __init__(self, guild: discord.Guild, author_id: int):
        super().__init__(timeout=300)
        self.guild = guild
        self.author_id = author_id

    async def interaction_check(self, i): 
        if i.user.id != self.author_id:
            await i.response.send_message("❌ Not your panel.", ephemeral=True)
            return False
        return True

    async def _go(self, i, embed, view):
        await i.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="👤 Manage Balance",    style=discord.ButtonStyle.blurple, row=0)
    async def cat_xp(self, i, b):
        sub = AdminXPMenu(self.guild, self.author_id)
        await self._go(i, sub.build_embed(), sub)

    @discord.ui.button(label="📢 Trigger Ping",     style=discord.ButtonStyle.blurple, row=0)
    async def cat_announce(self, i: discord.Interaction, b):
        config = db_get_config(self.guild.id)
        if not config.get("share_channel_id"):
            await i.response.send_message("❌ No share channel configured.", ephemeral=True)
            return
        async def submit(inter, value):
            vid_id = extract_video_id(value)
            if not vid_id:
                await inter.response.send_message("❌ Invalid YouTube URL — paste the full YouTube link.", ephemeral=True)
                return
            # Guard: warn if this video is already the active one (prevent duplicate pings)
            current = db_get_current_video(self.guild.id)
            if current and current["video_id"] == vid_id:
                await inter.response.send_message(
                    f"⚠️ This video (`{vid_id}`) is already the active share window.\n"
                    "The ping was **not** sent again to avoid spamming the channel.\n"
                    "If you really need to re-send it, change the current video first.",
                    ephemeral=True
                )
                return
            # Store with watch URL so it matches RSS and the /video command
            watch_url = make_watch_url(vid_id)
            db_set_current_video(self.guild.id, vid_id, watch_url, "Manually triggered")
            await inter.response.send_message("📢 Sending ping…", ephemeral=True)
            await announce_video(inter.client, self.guild.id, vid_id, watch_url, "Manually triggered")
            await inter.edit_original_response(content="✅ Ping sent to share channel!")
        await i.response.send_modal(Modal1("Trigger Share Ping", "YouTube video URL",
            placeholder="https://www.youtube.com/watch?v=xxxx  or  shorts/xxxx", callback=submit))

    @discord.ui.button(label="💾 Run Backup",       style=discord.ButtonStyle.grey, row=1)
    async def cat_backup(self, i: discord.Interaction, b):
        config = db_get_config(self.guild.id)
        if not config.get("backup_channel_id"):
            await i.response.send_message("❌ No backup channel configured.", ephemeral=True)
            return
        await i.response.send_message("💾 Running backup...", ephemeral=True)
        await do_backup(i.client, self.guild.id)
        await i.followup.send("✅ Backup sent!", ephemeral=True)

    @discord.ui.button(label="📊 Server Stats",     style=discord.ButtonStyle.grey, row=1)
    async def cat_stats(self, i: discord.Interaction, b):
        conn = get_db()
        member_count = conn.execute("SELECT COUNT(*) FROM xp_data WHERE guild_id=?", (self.guild.id,)).fetchone()[0]
        total_xp     = conn.execute("SELECT COALESCE(SUM(xp),0) FROM xp_data WHERE guild_id=?", (self.guild.id,)).fetchone()[0]
        shop_count   = conn.execute("SELECT COUNT(*) FROM shop_items WHERE guild_id=?", (self.guild.id,)).fetchone()[0]
        share_count  = conn.execute("SELECT COUNT(*) FROM video_shares WHERE guild_id=?", (self.guild.id,)).fetchone()[0]
        quest_done   = conn.execute("SELECT COUNT(*) FROM monthly_quests WHERE guild_id=? AND completed=1", (self.guild.id,)).fetchone()[0]
        conn.close()
        current = db_get_current_video(self.guild.id)
        e = E(f"📊 Stats — {self.guild.name}", color=C_INFO)
        config = db_get_config(self.guild.id)
        c_name = config.get("currency_name") or "Gems"
        e.add_field(name="👥 Members with balance", value=f"**{member_count}**",         inline=True)
        e.add_field(name=f"💰 Total {c_name} given", value=f"**{cur(config, total_xp)}**", inline=True)
        e.add_field(name="🛒 Shop items",            value=f"**{shop_count}**",           inline=True)
        e.add_field(name="🔗 Total shares",          value=f"**{share_count}**",          inline=True)
        e.add_field(name="📅 Quests completed",      value=f"**{quest_done}**",           inline=True)
        if current:
            e.add_field(name="🎬 Current video",
                        value=f"[{current['video_title']}]({make_shorts_url(current['video_id'])})", inline=False)
        await i.response.send_message(embed=e, ephemeral=True)

    @discord.ui.button(label="🏁 Community Goals", style=discord.ButtonStyle.grey,   row=1)
    async def cat_goals(self, i: discord.Interaction, b):
        goals = db_get_community_goals(self.guild.id)
        config = db_get_config(self.guild.id)
        if not goals:
            await i.response.send_message("❌ No community goals active.", ephemeral=True)
            return
        e = E("🏁 Community Goals", color=C_EVENT)
        for g in goals[:10]:
            pct = g["current"] / g["target"] if g["target"] else 1
            bar = "█" * int(min(pct, 1.0) * 10) + "░" * (10 - int(min(pct, 1.0) * 10))
            e.add_field(
                name=f"{'✅ ' if g['completed'] else ''}{g['name']}",
                value=f"`{bar}` {g['current']}/{g['target']}\n{len(json.loads(g['contributors']))} contributors → {cur(config, g['reward_xp'])} each",
                inline=False
            )
        await i.response.send_message(embed=e, ephemeral=True)

    @discord.ui.button(label="📖 Setup Guide",      style=discord.ButtonStyle.green,  row=2)
    async def cat_tutorial(self, i: discord.Interaction, b):
        view = AdminTutorialView(self.guild, self.author_id)
        await i.response.edit_message(embed=view.build_embed(), view=view)

class AdminXPMenu(discord.ui.View):
    def __init__(self, guild, author_id):
        super().__init__(timeout=300)
        self.guild = guild
        self.author_id = author_id

    async def interaction_check(self, i):
        if i.user.id != self.author_id:
            await i.response.send_message("❌ Not your panel.", ephemeral=True)
            return False
        return True

    def build_embed(self) -> discord.Embed:
        config = db_get_config(self.guild.id)
        c_name = config.get("currency_name") or "Gems"
        e = E(f"👤 Manage {c_name}", color=C_INFO)
        e.description = f"Add, remove, set, or reset a member's {c_name} balance."
        return e

    async def _back(self, i):
        main = AdminMainMenu(self.guild, self.author_id)
        await i.response.edit_message(embed=admin_main_embed(self.guild), view=main)

    @discord.ui.button(label="← Back",           style=discord.ButtonStyle.grey,   row=4)
    async def btn_back(self, i, b): await self._back(i)

    @discord.ui.button(label="➕ Add / Remove",   style=discord.ButtonStyle.green,  row=0)
    async def btn_add(self, interaction: discord.Interaction, btn):
        config = db_get_config(self.guild.id)
        async def submit(inter, v_member, v_amount):
            uid = parse_user_id(v_member)
            if not uid:
                await inter.response.send_message("❌ Invalid member.", ephemeral=True)
                return
            try:
                amount = int(v_amount)
            except ValueError:
                await inter.response.send_message("❌ Invalid amount.", ephemeral=True)
                return
            before = db_get_xp(self.guild.id, uid)
            new_xp = db_add_xp(self.guild.id, uid, amount)
            verb = "received" if amount >= 0 else "lost"
            await inter.response.send_message(
                f"✅ <@{uid}> {verb} **{cur(config, abs(amount))}** — balance: **{cur(config, new_xp)}**",
                ephemeral=True)
            await send_log(inter.client, self.guild.id, inter.user, "Balance Modified",
                           f"Member: <@{uid}> | Change: {amount:+d} | Balance: {new_xp}")
            await notify_balance_change_dm(
                inter.client, self.guild.id, inter.user, uid, before, new_xp,
                "Add / Remove", amount,
            )
        await interaction.response.send_modal(Modal2("Add / Remove Balance",
            "Member mention or ID", "@username  or  1234567890",
            "Amount (negative = remove)", "100  or  -50", callback=submit))

    @discord.ui.button(label="📊 Set Exact",      style=discord.ButtonStyle.blurple, row=0)
    async def btn_set(self, interaction: discord.Interaction, btn):
        config = db_get_config(self.guild.id)
        async def submit(inter, v_member, v_amount):
            uid = parse_user_id(v_member)
            if not uid:
                await inter.response.send_message("❌ Invalid member.", ephemeral=True)
                return
            try:
                amount = int(v_amount)
                if amount < 0: raise ValueError
            except ValueError:
                await inter.response.send_message("❌ Amount must be non-negative.", ephemeral=True)
                return
            before = db_get_xp(self.guild.id, uid)
            db_set_xp(self.guild.id, uid, amount)
            await inter.response.send_message(
                f"✅ Set <@{uid}>'s balance to **{cur(config, amount)}**", ephemeral=True)
            await send_log(inter.client, self.guild.id, inter.user, "Balance Set",
                           f"Member: <@{uid}> | Balance: {amount}")
            await notify_balance_change_dm(
                inter.client, self.guild.id, inter.user, uid, before, amount,
                "Set Exact", amount - before,
            )
        await interaction.response.send_modal(Modal2("Set Exact Balance",
            "Member mention or ID", "@username  or  1234567890",
            "New balance", "500", callback=submit))

    @discord.ui.button(label="🔄 Reset Balance",  style=discord.ButtonStyle.red,    row=0)
    async def btn_reset(self, interaction: discord.Interaction, btn):
        config = db_get_config(self.guild.id)
        async def submit(inter, value):
            uid = parse_user_id(value)
            if not uid:
                await inter.response.send_message("❌ Invalid member.", ephemeral=True)
                return
            old = db_get_xp(self.guild.id, uid)
            view = ConfirmView(inter.user.id)
            await inter.response.send_message(
                f"⚠️ Reset <@{uid}>'s balance to 0? (was **{cur(config, old)}**)",
                view=view, ephemeral=True)
            await view.wait()
            if view.value:
                db_set_xp(self.guild.id, uid, 0)
                await inter.followup.send(f"✅ <@{uid}>'s balance reset to 0.", ephemeral=True)
                await send_log(inter.client, self.guild.id, inter.user, "Balance Reset",
                               f"Member: <@{uid}> | Previous: {old}")
                await notify_balance_change_dm(
                    inter.client, self.guild.id, inter.user, uid, old, 0,
                    "Reset", -old,
                )
            else:
                await inter.followup.send("Cancelled.", ephemeral=True)
        await interaction.response.send_modal(Modal1("Reset Member Balance", "Member mention or ID",
            placeholder="@username  or  1234567890", callback=submit))

    @discord.ui.button(label="🔄 Reset Streak",   style=discord.ButtonStyle.red,    row=1)
    async def btn_reset_streak(self, interaction: discord.Interaction, btn):
        async def submit(inter, value):
            uid = parse_user_id(value)
            if not uid:
                await inter.response.send_message("❌ Invalid member.", ephemeral=True)
                return
            db_update_streak(self.guild.id, uid, 0, "")
            guild = inter.client.get_guild(self.guild.id)
            if guild:
                await update_streak_nickname(guild, uid, 0)
            await inter.response.send_message(f"✅ <@{uid}>'s streak reset to 0.", ephemeral=True)
            await send_log(inter.client, self.guild.id, inter.user, "Streak Reset",
                           f"<@{uid}> → 🔥0")
        await interaction.response.send_modal(Modal1("Reset Member Streak", "Member mention or ID",
            placeholder="@username  or  1234567890", callback=submit))

    @discord.ui.button(label="➕ Modify Streak",  style=discord.ButtonStyle.grey,   row=2)
    async def btn_modify_streak(self, interaction: discord.Interaction, btn):
        """Add or remove streak days for a member (e.g. +3 or -2)."""
        async def submit(inter, user_val, delta_val):
            uid = parse_user_id(user_val.strip())
            if not uid:
                await inter.response.send_message("❌ Invalid member — enter a mention or numeric ID.", ephemeral=True)
                return
            try:
                delta = int(delta_val.strip())
            except ValueError:
                await inter.response.send_message("❌ Invalid number — use e.g. `+3` or `-2`.", ephemeral=True)
                return
            streak = db_get_streak(self.guild.id, uid)
            new_streak = max(0, streak["current_streak"] + delta)
            db_update_streak(self.guild.id, uid, new_streak, streak.get("last_video_id", ""))
            guild = inter.client.get_guild(self.guild.id)
            if guild:
                await update_streak_nickname(guild, uid, new_streak)
            sign = "+" if delta >= 0 else ""
            await inter.response.send_message(
                f"✅ <@{uid}>'s streak {sign}{delta} → **🔥{new_streak}**.", ephemeral=True)
            await send_log(inter.client, self.guild.id, inter.user, "Streak Modified",
                           f"<@{uid}> : {sign}{delta} → 🔥{new_streak}")
        try:
            await interaction.response.send_modal(Modal2(
                "Modify Member Streak",
                "Member mention or ID", "e.g. @username  or  1234567890123456789",
                "Streak change", "e.g. +3  or  -2",
                callback=submit))
        except Exception as e:
            print(f"[btn_modify_streak] {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Could not open the form. Please try again.", ephemeral=True)

    @discord.ui.button(label="🎲 Reroll Quests",  style=discord.ButtonStyle.grey,   row=2)
    async def btn_reroll_quests(self, interaction: discord.Interaction, btn):
        """Clear and re-assign a member's current monthly quests."""
        async def submit(inter, value):
            uid = parse_user_id(value)
            if not uid:
                await inter.response.send_message("❌ Invalid member.", ephemeral=True)
                return
            month_key = current_month_key()
            conn = get_db()
            conn.execute(
                "DELETE FROM monthly_quests WHERE guild_id=? AND user_id=? AND month_key=?",
                (self.guild.id, uid, month_key)
            )
            conn.commit()
            conn.close()
            db_assign_monthly_quests(self.guild.id, uid, month_key)
            await inter.response.send_message(
                f"✅ <@{uid}>'s monthly quests for **{month_key}** have been rerolled.", ephemeral=True)
        await interaction.response.send_modal(Modal1("Reroll Member Quests", "Member mention or ID",
            placeholder="@username  or  1234567890", callback=submit))

    @discord.ui.button(label="🔍 Check Balance",  style=discord.ButtonStyle.grey,   row=1)
    async def btn_check(self, interaction: discord.Interaction, btn):
        config = db_get_config(self.guild.id)
        async def submit(inter, value):
            uid = parse_user_id(value)
            if not uid:
                await inter.response.send_message("❌ Invalid member.", ephemeral=True)
                return
            xp = db_get_xp(self.guild.id, uid)
            top = db_top_xp(self.guild.id, limit=1000)
            rank = next((i+1 for i, (u, _) in enumerate(top) if u == uid), None)
            streak = db_get_streak(self.guild.id, uid)
            await inter.response.send_message(
                f"<@{uid}> — **{cur(config, xp)}**" +
                (f"  |  Rank **#{rank}**" if rank else "") +
                f"  |  Streak **🔥{streak['current_streak']}**",
                ephemeral=True
            )
        await interaction.response.send_modal(Modal1("Check Member Balance", "Member mention or ID",
            placeholder="@username  or  1234567890", callback=submit))

class LegacyAdminShopMenu(discord.ui.View):
    def __init__(self, guild, author_id):
        super().__init__(timeout=300)
        self.guild = guild
        self.author_id = author_id

    async def interaction_check(self, i):
        if i.user.id != self.author_id:
            await i.response.send_message("❌ Not your panel.", ephemeral=True)
            return False
        return True

    def build_embed(self) -> discord.Embed:
        items  = db_get_shop_items(self.guild.id)
        config = db_get_config(self.guild.id)
        now_iso = datetime.utcnow().isoformat()
        e = E("🛒 Manage Shop", color=C_GOLD)
        if not items:
            e.description = "Shop is empty."
        else:
            for item in items[:15]:
                tags = []
                if item.get("is_temporary"):   tags.append(f"⏳{item['duration_days']}d")
                if item.get("requires_text"):  tags.append("📝")
                if item.get("image_url"):      tags.append("🖼️")
                if item.get("show_stock"):     tags.append("📦vis")
                exp = item.get("item_expires_at")
                if exp:
                    expired = exp < now_iso
                    exp_short = exp[:10]
                    tags.append(f"🗓️{exp_short}{'❌' if expired else ''}")
                e.add_field(
                    name=item['name'],
                    value=f"**{cur(config, item['price'])}** · ID:`{item['id']}`"
                          + (f"\n{'  '.join(tags)}" if tags else ""),
                    inline=True
                )
        e.set_footer(text="⏳=temp  📝=text req  🖼️=image  📦vis=stock visible  🗓️=listing expiry (❌=expired)")
        return e

    async def _back(self, i):
        main = AdminMainMenu(self.guild, self.author_id)
        await i.response.edit_message(embed=admin_main_embed(self.guild), view=main)

    async def _refresh(self, interaction):
        await interaction.edit_original_response(embed=self.build_embed(), view=self)

    @discord.ui.button(label="← Back",       style=discord.ButtonStyle.grey,  row=4)
    async def btn_back(self, i, b): await self._back(i)

    @discord.ui.button(label="➕ Add Item",   style=discord.ButtonStyle.green, row=0)
    async def btn_add(self, interaction: discord.Interaction, btn):
        cfg_add = db_get_config(self.guild.id)
        async def submit(inter, v_name, v_price, v_stock, v_temp, v_text):
            try:
                price = int(v_price); days = int(v_temp)
                if price <= 0 or days < 0: raise ValueError
            except ValueError:
                await inter.response.send_message("❌ Invalid price or duration.", ephemeral=True)
                return
            try:
                stock_val = int(v_stock.strip()) if v_stock.strip() else 0
                if stock_val < 0: raise ValueError
            except ValueError:
                await inter.response.send_message("❌ Stock must be 0 (unlimited) or a positive number.", ephemeral=True)
                return
            stock_db = stock_val if stock_val > 0 else None
            item_id = db_add_shop_item(
                self.guild.id, v_name.strip(), price, None,
                1 if days > 0 else 0, days if days > 0 else None, 1,
                1 if v_text.strip() else 0, v_text.strip() or None,
                stock=stock_db
            )
            stock_info = f" · 📦 {stock_val} in stock" if stock_db else " · unlimited stock"
            await inter.response.send_message(
                f"✅ Added **{v_name.strip()}** (ID: `{item_id}`){stock_info}\n"
                f"💡 Set an image via **🖼️ Set Image URL**.", ephemeral=True)
            await self._refresh(interaction)
        await interaction.response.send_modal(Modal5("Add Shop Item", currency_label=cfg_add.get("currency_name") or "Gems", callback=submit))

    @discord.ui.button(label="🗑️ Remove",      style=discord.ButtonStyle.red,    row=0)
    async def btn_remove(self, interaction: discord.Interaction, btn):
        items = db_get_shop_items(self.guild.id)
        if not items:
            await interaction.response.send_message("❌ Shop is empty.", ephemeral=True)
            return
        cfg = db_get_config(self.guild.id)
        options = [discord.SelectOption(label=f"{i['name'][:80]} — {cur(cfg, i['price'])}", value=str(i["id"])) for i in items[:25]]
        view = discord.ui.View(timeout=60)
        sel = discord.ui.Select(placeholder="Choose item to remove", options=options)
        async def on_select(inter2):
            db_remove_shop_item(int(sel.values[0]), self.guild.id)
            await inter2.response.send_message("✅ Removed.", ephemeral=True)
            await self._refresh(interaction)
        sel.callback = on_select
        view.add_item(sel)
        await interaction.response.send_message("Select item to remove:", view=view, ephemeral=True)

    @discord.ui.button(label="✏️ Edit Name",   style=discord.ButtonStyle.blurple, row=1)
    async def btn_edit_name(self, interaction: discord.Interaction, btn):
        items = db_get_shop_items(self.guild.id)
        if not items:
            await interaction.response.send_message("❌ Shop is empty.", ephemeral=True)
            return
        cfg = db_get_config(self.guild.id)
        options = [discord.SelectOption(label=f"{i['name'][:80]} — {cur(cfg, i['price'])}", value=str(i["id"])) for i in items[:25]]
        view      = discord.ui.View(timeout=60)
        sel       = discord.ui.Select(placeholder="Choose item to rename", options=options)
        guild_ref = self.guild
        parent    = interaction
        all_items = items
        async def on_select(inter2):
            item_id  = int(sel.values[0])
            chosen   = next((i for i in all_items if i["id"] == item_id), None)
            cur_name = chosen["name"] if chosen else ""
            async def name_submit(inter3, value):
                new_name = value.strip()
                if not new_name:
                    await inter3.response.send_message("❌ Name cannot be empty.", ephemeral=True)
                    return
                db_set_shop_item_name(item_id, guild_ref.id, new_name)
                await inter3.response.send_message(f"✅ Renamed to **{new_name}**.", ephemeral=True)
                await self._refresh(parent)
            await inter2.response.send_modal(Modal1(
                f"Rename — {cur_name[:40]}", label="New item name",
                placeholder=cur_name, default=cur_name, max_length=80,
                callback=name_submit,
            ))
        sel.callback = on_select
        view.add_item(sel)
        await interaction.response.send_message("✏️ Choose an item to rename:", view=view, ephemeral=True)

    @discord.ui.button(label="↕️ Reorder",     style=discord.ButtonStyle.blurple, row=1)
    async def btn_reorder(self, interaction: discord.Interaction, btn):
        items = db_get_shop_items(self.guild.id)
        if len(items) < 2:
            await interaction.response.send_message("❌ Need at least 2 items to reorder.", ephemeral=True)
            return
        cfg = db_get_config(self.guild.id)
        options = [
            discord.SelectOption(
                label=f"#{idx}  {i['name'][:60]} — {cur(cfg, i['price'])}",
                value=str(i["id"])
            )
            for idx, i in enumerate(items[:25], 1)
        ]
        view1     = discord.ui.View(timeout=60)
        sel1      = discord.ui.Select(placeholder="Pick item to move…", options=options)
        guild_ref = self.guild
        parent    = interaction
        async def on_pick_item(inter2):
            item_id  = int(sel1.values[0])
            pos_opts = [discord.SelectOption(label=f"Position #{p}", value=str(p)) for p in range(1, len(items) + 1)]
            view2 = discord.ui.View(timeout=60)
            sel2  = discord.ui.Select(placeholder="Move to position…", options=pos_opts[:25])
            async def on_pick_pos(inter3):
                new_pos = int(sel2.values[0])
                current = db_get_shop_items(guild_ref.id)
                moved   = next((i for i in current if i["id"] == item_id), None)
                ordered = [i for i in current if i["id"] != item_id]
                if moved:
                    ordered.insert(new_pos - 1, moved)
                db_reorder_shop_items(guild_ref.id, [i["id"] for i in ordered])
                await inter3.response.send_message(
                    f"✅ **{moved['name'] if moved else 'Item'}** moved to position **#{new_pos}**.",
                    ephemeral=True)
                await self._refresh(parent)
            sel2.callback = on_pick_pos
            view2.add_item(sel2)
            await inter2.response.send_message("📍 Move to which position?", view=view2, ephemeral=True)
        sel1.callback = on_pick_item
        view1.add_item(sel1)
        await interaction.response.send_message("↕️ Which item do you want to move?", view=view1, ephemeral=True)

    @discord.ui.button(label="💰 Edit Price",   style=discord.ButtonStyle.blurple, row=1)
    async def btn_edit_price(self, interaction: discord.Interaction, btn):
        items = db_get_shop_items(self.guild.id)
        if not items:
            await interaction.response.send_message("❌ Shop is empty.", ephemeral=True)
            return
        cfg = db_get_config(self.guild.id)
        options = [
            discord.SelectOption(
                label=f"{i['name'][:80]} — {cur(cfg, i['price'])}",
                value=str(i["id"])
            ) for i in items[:25]
        ]
        view      = discord.ui.View(timeout=60)
        sel       = discord.ui.Select(placeholder="Choose item to reprice", options=options)
        guild_ref = self.guild
        parent    = interaction
        all_items = items
        async def on_select(inter2):
            item_id = int(sel.values[0])
            chosen  = next((i for i in all_items if i["id"] == item_id), None)
            cur_price = str(chosen["price"]) if chosen else ""
            c_name  = cfg.get("currency_name") or "Gems"
            async def price_submit(inter3, value):
                try:
                    new_price = int(value.strip())
                    if new_price <= 0: raise ValueError
                except ValueError:
                    await inter3.response.send_message("❌ Enter a positive number.", ephemeral=True)
                    return
                conn = get_db()
                conn.execute("UPDATE shop_items SET price=? WHERE id=? AND guild_id=?",
                             (new_price, item_id, guild_ref.id))
                conn.commit()
                conn.close()
                await inter3.response.send_message(
                    f"✅ **{chosen['name']}** repriced to **{cur(cfg, new_price)}**.", ephemeral=True)
                await self._refresh(parent)
            await inter2.response.send_modal(Modal1(
                f"Edit Price — {chosen['name'][:40] if chosen else '?'}",
                label=f"New price in {c_name}",
                placeholder="100",
                default=cur_price,
                callback=price_submit,
            ))
        sel.callback = on_select
        view.add_item(sel)
        await interaction.response.send_message("💰 Choose an item to reprice:", view=view, ephemeral=True)

    @discord.ui.button(label="📅 Set Expiry",   style=discord.ButtonStyle.grey,    row=2)
    async def btn_set_expiry(self, interaction: discord.Interaction, btn):
        """Set or clear the listing expiry date for a shop item (YYYY-MM-DD)."""
        items = db_get_shop_items(self.guild.id)
        if not items:
            await interaction.response.send_message("❌ Shop is empty.", ephemeral=True)
            return
        cfg = db_get_config(self.guild.id)
        options = [
            discord.SelectOption(
                label=f"{i['name'][:60]} — {cur(cfg, i['price'])}",
                value=str(i["id"]),
                description=f"Expires {i['item_expires_at'][:10]}" if i.get("item_expires_at") else "No expiry",
            ) for i in items[:25]
        ]
        view      = discord.ui.View(timeout=60)
        sel       = discord.ui.Select(placeholder="Choose item to set expiry", options=options)
        guild_ref = self.guild
        parent    = interaction
        all_items = items
        async def on_select(inter2):
            item_id = int(sel.values[0])
            chosen  = next((i for i in all_items if i["id"] == item_id), None)
            cur_exp = (chosen.get("item_expires_at") or "")[:10] if chosen else ""
            async def expiry_submit(inter3, value):
                v = value.strip()
                if not v:
                    # Clear expiry
                    conn = get_db()
                    conn.execute("UPDATE shop_items SET item_expires_at=NULL WHERE id=? AND guild_id=?",
                                 (item_id, guild_ref.id))
                    conn.commit(); conn.close()
                    await inter3.response.send_message(
                        f"✅ Expiry removed from **{chosen['name']}** — listing never expires.", ephemeral=True)
                else:
                    # Parse and validate date
                    try:
                        from datetime import date as _date
                        parsed = _date.fromisoformat(v)
                        iso_str = parsed.isoformat() + "T23:59:59"
                    except ValueError:
                        await inter3.response.send_message(
                            "❌ Invalid date. Use **YYYY-MM-DD** format (e.g. `2026-12-31`).", ephemeral=True)
                        return
                    conn = get_db()
                    conn.execute("UPDATE shop_items SET item_expires_at=? WHERE id=? AND guild_id=?",
                                 (iso_str, item_id, guild_ref.id))
                    conn.commit(); conn.close()
                    await inter3.response.send_message(
                        f"✅ **{chosen['name']}** will expire on **{parsed.isoformat()}** "
                        f"and be hidden from the shop after that date.", ephemeral=True)
                await self._refresh(parent)
            await inter2.response.send_modal(Modal1(
                f"Set Expiry — {chosen['name'][:40] if chosen else '?'}",
                label="Expiry date (YYYY-MM-DD) — empty to remove",
                placeholder="2026-12-31",
                default=cur_exp,
                required=False,
                callback=expiry_submit,
            ))
        sel.callback = on_select
        view.add_item(sel)
        await interaction.response.send_message("📅 Choose an item to set a listing expiry:", view=view, ephemeral=True)

    @discord.ui.button(label="👁️ Stock Visible", style=discord.ButtonStyle.grey,    row=2)
    async def btn_toggle_stock_vis(self, interaction: discord.Interaction, btn):
        """Toggle whether remaining stock count is shown to members in /shop."""
        items = db_get_shop_items(self.guild.id)
        stock_items = [i for i in items if i.get("stock") is not None]
        if not stock_items:
            await interaction.response.send_message(
                "❌ No items have a stock limit set. Add stock when creating an item.", ephemeral=True)
            return
        cfg = db_get_config(self.guild.id)
        options = [
            discord.SelectOption(
                label=f"{i['name'][:60]} — {cur(cfg, i['price'])}",
                value=str(i["id"]),
                description="👁️ Stock SHOWN in /shop" if i.get("show_stock", 0) else "🔇 Stock HIDDEN from /shop",
            ) for i in stock_items[:25]
        ]
        view      = discord.ui.View(timeout=60)
        sel       = discord.ui.Select(placeholder="Choose item to toggle stock visibility", options=options)
        guild_ref = self.guild
        parent    = interaction
        all_items = stock_items
        async def on_select(inter2):
            item_id  = int(sel.values[0])
            chosen   = next((i for i in all_items if i["id"] == item_id), None)
            new_show = 0 if chosen and chosen.get("show_stock", 0) else 1
            conn = get_db()
            conn.execute("UPDATE shop_items SET show_stock=? WHERE id=? AND guild_id=?",
                         (new_show, item_id, guild_ref.id))
            conn.commit(); conn.close()
            label = "👁️ Stock now **shown** in /shop" if new_show else "🔇 Stock now **hidden** from /shop"
            await inter2.response.send_message(
                f"{label} for **{chosen['name'] if chosen else '?'}**.", ephemeral=True)
            await self._refresh(parent)
        sel.callback = on_select
        view.add_item(sel)
        await interaction.response.send_message(
            "👁️ Choose an item to toggle its stock visibility in **/shop**:", view=view, ephemeral=True)

# ══════════════════════════════════════════════════════════════
#  /shop — MEMBER SHOP VIEW
# ══════════════════════════════════════════════════════════════

async def _create_purchase_ticket(bot_instance, guild: discord.Guild, buyer: discord.Member,
                                   shop_item: dict, item_text: Optional[str]) -> Optional[discord.TextChannel]:
    """Create a ticket channel for a purchase and notify all Meeple Owners via DM."""
    config = db_get_config(guild.id)
    manager_role_id    = config.get("manager_role_id")
    ticket_category_id = config.get("ticket_category_id")

    # Build a Discord-safe channel name
    item_slug   = re.sub(r'[^a-z0-9]+', '-', shop_item['name'].lower())[:25].strip('-')
    buyer_slug  = re.sub(r'[^a-z0-9]+', '-', buyer.name.lower())[:15].strip('-')
    channel_name = f"ticket-{buyer_slug}-{item_slug}"[:100]

    # Permission overwrites
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        buyer:              discord.PermissionOverwrite(view_channel=True, send_messages=True,
                                                        read_message_history=True),
        guild.me:           discord.PermissionOverwrite(view_channel=True, send_messages=True,
                                                        manage_channels=True),
    }
    manager_role = guild.get_role(manager_role_id) if manager_role_id else None
    if manager_role:
        overwrites[manager_role] = discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True
        )

    category = None
    if ticket_category_id:
        category = guild.get_channel(ticket_category_id)

    try:
        ticket_ch = await guild.create_text_channel(
            channel_name,
            category=category,
            overwrites=overwrites,
            reason=f"Purchase ticket — {shop_item['name']}"
        )
    except Exception as ex:
        print(f"[Ticket] Could not create channel: {ex}")
        return None

    # ── Post in the ticket channel ──────────────────────────────
    role_ping = f"<@&{manager_role_id}>" if manager_role_id else ""
    ticket_embed = E(
        "🎫 New Purchase Ticket",
        f"**Buyer:** {buyer.mention}\n"
        f"**Item:** {shop_item['name']}\n"
        f"**Price:** {cur(config, shop_item['price'])}"
        + (f"\n**Info provided:** {item_text}" if item_text else ""),
        C_GOLD
    )
    if shop_item.get("image_url"):
        ticket_embed.set_image(url=shop_item["image_url"])
    if shop_item.get("provided_by"):
        ticket_embed.add_field(name="🤝 Provided by", value=shop_item["provided_by"], inline=True)
    ticket_embed.set_footer(text="Review the request and close this channel when done.")

    try:
        await ticket_ch.send(content=role_ping, embed=ticket_embed)
    except Exception as ex:
        print(f"[Ticket] Could not send ticket message: {ex}")

    # ── Auto-distribute pre-loaded reward if available ──────────
    reward_text = None
    item_id = shop_item.get("id")
    if item_id:
        available = db_count_available_rewards(item_id, guild.id)
        if available > 0:
            reward_text = db_claim_next_reward(item_id, guild.id, buyer.id)
            if reward_text:
                remaining = db_count_available_rewards(item_id, guild.id)
                try:
                    reward_embed = E(
                        "🔑 Your Reward",
                        f"**Item:** {shop_item['name']}\n"
                        f"**Buyer:** {buyer.mention}\n\n"
                        f"```\n{reward_text}\n```\n"
                        f"_({remaining} reward(s) remaining in stock)_",
                        C_SUCCESS
                    )
                    await ticket_ch.send(embed=reward_embed)
                except Exception as ex:
                    print(f"[Ticket] Could not send reward: {ex}")

    # Log the purchase
    await bot_log(bot, guild.id, "🛒 Shop Purchase",
                  f"**Buyer:** {buyer.mention} ({buyer.display_name})\n"
                  f"**Item:** {shop_item['name']}\n"
                  f"**Price:** {cur(config, shop_item['price'])}\n"
                  f"**Ticket:** {ticket_ch.mention}"
                  + (f"\n**Info:** {item_text}" if item_text else "")
                  + (f"\n**Auto-reward sent:** `{reward_text}`" if reward_text else ""),
                  C_GOLD)

    # ── DM role members (if purchase DMs are enabled) ────────────
    purchase_dm_enabled = config.get("purchase_dm_enabled", 1)
    if purchase_dm_enabled:
        # Use dedicated purchase DM role if set, otherwise fall back to Meeple Owner
        dm_role_id = config.get("purchase_dm_role_id") or manager_role_id
        dm_role = guild.get_role(dm_role_id) if dm_role_id else None
        if dm_role:
            dm_embed = E(
                "🎫 New Purchase Ticket Opened!",
                f"**Server:** {guild.name}\n"
                f"**Item:** {shop_item['name']}\n"
                f"**Buyer:** {buyer.mention} ({buyer.display_name})\n"
                f"**Price:** {cur(config, shop_item['price'])}"
                + (f"\n**Info:** {item_text}" if item_text else "")
                + (f"\n**Reward sent:** `{reward_text}`" if reward_text else "")
                + f"\n\n**Ticket channel:** {ticket_ch.mention}",
                C_GOLD
            )
            dm_sent_count = 0
            for m in dm_role.members:
                if m.bot:
                    continue
                try:
                    await m.send(embed=dm_embed)
                    dm_sent_count += 1
                except discord.Forbidden:
                    pass
                except Exception as ex:
                    print(f"[Ticket] DM failed for {m}: {ex}")
            if dm_sent_count:
                await bot_log(bot, guild.id, "📬 Purchase DM Sent",
                              f"**Item:** {shop_item['name']}\n"
                              f"**Buyer:** {buyer.mention}\n"
                              f"**DMs sent to:** {dm_sent_count} member(s) with <@&{dm_role_id}>",
                              C_INFO)

    return ticket_ch


class PendingPurchaseView(discord.ui.View):
    """Approve or reject a pending shop purchase requiring Gems Owner sign-off.

    Sent to the admin channel when a member tries to buy an item with
    requires_approval=1.  Gems are NOT deducted until a Gems Owner approves.
    """

    def __init__(self, purchase_id: int, guild: discord.Guild,
                 buyer: discord.Member, shop_item: dict,
                 item_text: Optional[str], bot_ref):
        super().__init__(timeout=None)   # stays active until clicked
        self.purchase_id = purchase_id
        self.guild       = guild
        self.buyer       = buyer
        self.shop_item   = shop_item
        self.item_text   = item_text
        self.bot_ref     = bot_ref
        self._resolved   = False

    async def _resolve(self, interaction: discord.Interaction, approved: bool):
        if self._resolved:
            await interaction.response.send_message("⚠️ Already resolved.", ephemeral=True)
            return
        config   = db_get_config(self.guild.id)
        purchase = db_get_pending_purchase(self.purchase_id)
        if not purchase or purchase["status"] != "pending":
            await interaction.response.send_message("⚠️ Purchase already resolved.", ephemeral=True)
            return
        self._resolved = True
        resolver = interaction.user

        if approved:
            # Deduct gems and add to inventory
            buyer_bal = db_get_xp(self.guild.id, self.buyer.id)
            if buyer_bal < self.shop_item["price"]:
                await interaction.response.send_message(
                    f"❌ Cannot approve — {self.buyer.mention} no longer has enough "
                    f"{cur(config)} (has **{buyer_bal}**, needs **{self.shop_item['price']}**).",
                    ephemeral=True
                )
                self._resolved = False
                return
            new_bal = db_add_xp(self.guild.id, self.buyer.id, -self.shop_item["price"])
            db_decrement_stock(self.shop_item["id"], self.guild.id)
            expires_at = None
            if self.shop_item.get("is_temporary") and self.shop_item.get("duration_days"):
                expires_at = (datetime.now() + timedelta(days=self.shop_item["duration_days"])).isoformat()
            db_add_inventory(self.guild.id, self.buyer.id, self.shop_item["name"], expires_at, self.item_text)
            db_resolve_pending_purchase(self.purchase_id, "approved", resolver.id)

            # Create ticket
            ticket_ch = await _create_purchase_ticket(
                self.bot_ref, self.guild, self.buyer, self.shop_item, self.item_text
            )
            # DM buyer
            try:
                dm_msg = (
                    f"✅ Your purchase of **{self.shop_item['name']}** in **{self.guild.name}** "
                    f"has been **approved** by {resolver.mention}!\n"
                    f"Remaining balance: **{cur(config, new_bal)}**"
                )
                if ticket_ch:
                    dm_msg += f"\n🎫 Ticket opened: {ticket_ch.mention}"
                await self.buyer.send(dm_msg)
            except Exception:
                pass
            await interaction.response.send_message(
                f"✅ Purchase approved for {self.buyer.mention}. "
                f"Ticket: {ticket_ch.mention if ticket_ch else '(could not create)'}",
                ephemeral=True
            )
            await bot_log(self.bot_ref, self.guild.id, "✅ Purchase Approved",
                          f"**Item:** {self.shop_item['name']}\n"
                          f"**Buyer:** {self.buyer.mention}\n"
                          f"**Approved by:** {resolver.mention}", C_SUCCESS)
        else:
            db_resolve_pending_purchase(self.purchase_id, "rejected", resolver.id)
            # DM buyer
            try:
                await self.buyer.send(
                    f"❌ Your purchase request for **{self.shop_item['name']}** in "
                    f"**{self.guild.name}** was **rejected** by a Gems Owner.\n"
                    f"Your gems were not deducted. Contact them if you have questions."
                )
            except Exception:
                pass
            await interaction.response.send_message(
                f"❌ Purchase rejected for {self.buyer.mention}. No gems were deducted.",
                ephemeral=True
            )
            await bot_log(self.bot_ref, self.guild.id, "❌ Purchase Rejected",
                          f"**Item:** {self.shop_item['name']}\n"
                          f"**Buyer:** {self.buyer.mention}\n"
                          f"**Rejected by:** {resolver.mention}", C_ERROR)

        # Disable buttons
        for child in self.children:
            child.disabled = True
        try:
            await interaction.message.edit(view=self)
        except Exception:
            pass
        self.stop()

    @discord.ui.button(label="✅ Approve", style=discord.ButtonStyle.green)
    async def approve(self, interaction: discord.Interaction, btn: discord.ui.Button):
        config = db_get_config(self.guild.id)
        if not is_xp_manager(interaction.user, config):
            await interaction.response.send_message("❌ Only Gems Owners can approve purchases.", ephemeral=True)
            return
        await self._resolve(interaction, approved=True)

    @discord.ui.button(label="❌ Reject", style=discord.ButtonStyle.red)
    async def reject(self, interaction: discord.Interaction, btn: discord.ui.Button):
        config = db_get_config(self.guild.id)
        if not is_xp_manager(interaction.user, config):
            await interaction.response.send_message("❌ Only Gems Owners can reject purchases.", ephemeral=True)
            return
        await self._resolve(interaction, approved=False)


class ShopView(discord.ui.View):
    """Member-facing paginated shop — one item per page.

    Each page shows a single item embed with its dedicated Buy button,
    so the button is always visually tied to the item above it.
    Navigation (◀ Prev / Next ▶) sits on row 4.
    """

    PER_PAGE = 1

    def __init__(self, guild: discord.Guild, user: discord.Member, page: int = 0):
        super().__init__(timeout=120)
        self.guild = guild
        self.user  = user
        self.page  = page
        # Filter out items whose listing has expired
        now_iso = datetime.utcnow().isoformat()
        self.items = [
            i for i in db_get_shop_items(guild.id)
            if not (i.get("item_expires_at") and i["item_expires_at"] < now_iso)
        ]
        self._msg: Optional[discord.Message] = None  # set by /shop after sending
        self._build()

    async def on_timeout(self):
        """Disable all buttons when the shop times out so the message goes dark."""
        for child in self.children:
            child.disabled = True
        if self._msg:
            try:
                await self._msg.edit(view=self)
            except Exception:
                pass

    # ── internal ──────────────────────────────────────────────

    def _build(self):
        self.clear_items()
        config  = db_get_config(self.guild.id)
        c_emoji = config.get("currency_emoji") or "💎"
        c_name  = config.get("currency_name")  or "Gems"
        start      = self.page * self.PER_PAGE
        page_items = self.items[start:start + self.PER_PAGE]

        for idx, item in enumerate(page_items):
            # Determine if item is sold out (limited stock that hit 0)
            sold_out = item.get("stock") is not None and item["stock"] == 0

            # Custom Discord emojis (e.g. <:gems:123>) cannot be rendered inside
            # a button label — Discord shows them as raw text.  They must be
            # passed via the emoji= parameter instead.
            if c_emoji.startswith("<") and c_emoji.endswith(">"):
                parts = c_emoji.strip("<>").split(":")
                try:
                    animated  = parts[0] == "a"
                    btn_emoji = discord.PartialEmoji(
                        animated=animated, name=parts[1], id=int(parts[2])
                    )
                except (ValueError, IndexError):
                    btn_emoji = None
                if sold_out:
                    btn_label = "🚫 Sold Out"
                    btn_emoji = None
                else:
                    btn_label = f"✅ Buy — {item['price']:,} {c_name}"
            else:
                btn_emoji = None
                if sold_out:
                    btn_label = "🚫 Sold Out"
                else:
                    btn_label = f"✅ Buy — {c_emoji} {item['price']:,} {c_name}"

            btn = discord.ui.Button(
                label=btn_label,
                emoji=btn_emoji,
                style=discord.ButtonStyle.grey if sold_out else discord.ButtonStyle.blurple,
                disabled=sold_out,
                row=idx,
            )
            if not sold_out:
                btn.callback = self._buy_cb(item)
            self.add_item(btn)

        total = max(1, -(-len(self.items) // self.PER_PAGE))
        if self.page > 0:
            prev = discord.ui.Button(label="◀ Prev", style=discord.ButtonStyle.grey, row=4)
            prev.callback = self._prev
            self.add_item(prev)
        if self.page < total - 1:
            nxt = discord.ui.Button(label="Next ▶", style=discord.ButtonStyle.grey, row=4)
            nxt.callback = self._next
            self.add_item(nxt)

    def embeds(self) -> list[discord.Embed]:
        """One header embed + one embed per item on the current page."""
        user_bal   = db_get_xp(self.guild.id, self.user.id)
        config     = db_get_config(self.guild.id)
        c_name     = config.get("currency_name")  or "Gems"
        c_emoji    = config.get("currency_emoji") or "💎"
        start      = self.page * self.PER_PAGE
        page_items = self.items[start:start + self.PER_PAGE]
        total      = max(1, -(-len(self.items) // self.PER_PAGE))

        # ── header ──
        header = discord.Embed(title=f"🛒 Shop — {self.guild.name}", color=C_GOLD)
        header.set_footer(text=f"Page {self.page + 1}/{total}")

        if not self.items:
            header.description = (
                f"Your balance: **{c_emoji} {user_bal:,} {c_name}**\n\n"
                "⚠️ The shop is empty. Ask a manager to add items via `/config → 🛒 Shop`."
            )
            return [header]

        can_afford = user_bal >= min(i["price"] for i in page_items) if page_items else True
        header.description = (
            f"Your balance: **{c_emoji} {user_bal:,} {c_name}**\n"
            f"Use the **✅ Buy** button below the item to purchase it."
            + ("" if can_afford else f"\n\n⚠️ You don't have enough {c_name} for this item.")
        )

        # ── item embeds ──
        out = [header]
        for item in page_items:
            ie = discord.Embed(title=item["name"], color=C_GOLD)

            # price + tags
            price_str = f"{c_emoji} **{item['price']:,} {c_name}**"
            extras = []
            if item.get("is_temporary") and item.get("show_duration"):
                extras.append(f"⏳ {item['duration_days']} days")
            if item.get("requires_text"):
                extras.append(f"📝 {item.get('text_label') or 'Info required'}")
            ie.description = price_str + ("  •  " + "  •  ".join(extras) if extras else "")

            # image — only works when a persistent URL (imgur, etc.) is stored
            if item.get("image_url"):
                ie.set_image(url=item["image_url"])

            # Provided-by credit
            if item.get("provided_by"):
                ie.add_field(name="🤝 Provided by", value=item["provided_by"], inline=True)

            # Show stock info only if admin enabled visibility
            item_id = item.get("id")
            if item_id:
                avail_rewards = db_count_available_rewards(item_id, self.guild.id)
                if avail_rewards > 0:
                    ie.add_field(name="🔑 Rewards in stock", value=f"**{avail_rewards}** — delivered instantly", inline=True)
                elif item.get("stock") is not None and item.get("show_stock", 0):
                    stock_left = item["stock"]
                    if stock_left == 0:
                        ie.add_field(name="📦 Stock", value="**Sold out**", inline=True)
                    else:
                        ie.add_field(name="📦 Stock", value=f"**{stock_left}** remaining", inline=True)

            # Per-person purchase limit display
            pur_limit = item.get("purchase_limit")
            if pur_limit and item.get("show_purchase_limit", 1):
                already = db_count_user_purchases(item["name"], self.guild.id, self.user.id)
                remaining_purchases = max(0, pur_limit - already)
                ie.add_field(
                    name="🔢 Purchase Limit",
                    value=f"**{remaining_purchases}/{pur_limit}** remaining for you",
                    inline=True
                )

            # Approval badge
            if item.get("requires_approval"):
                ie.add_field(name="🔒 Approval Required", value="A Gems Owner must approve this purchase", inline=True)

            out.append(ie)
        return out

    def _buy_cb(self, item):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.user.id:
                await interaction.response.send_message("❌ This isn't your shop!", ephemeral=True)
                return
            config = db_get_config(self.guild.id)
            user_bal = db_get_xp(self.guild.id, self.user.id)
            if user_bal < item["price"]:
                await interaction.response.send_message(
                    f"❌ Not enough {cur(config)}. Need **{item['price']}**, you have **{user_bal}**.",
                    ephemeral=True)
                return
            # ── Per-person purchase limit check ──────────────────
            purchase_limit = item.get("purchase_limit")
            if purchase_limit:
                already_bought = db_count_user_purchases(item["name"], self.guild.id, self.user.id)
                if already_bought >= purchase_limit:
                    await interaction.response.send_message(
                        f"❌ You've reached the purchase limit for **{item['name']}** "
                        f"(**{purchase_limit}** max per person).",
                        ephemeral=True)
                    return
            # If item requires text, ask for it first
            if item.get("requires_text"):
                async def text_submit(inter, value):
                    await _complete_purchase(inter, item, value.strip())
                await interaction.response.send_modal(Modal1(
                    f"Complete Purchase — {item['name'][:40]}",
                    label=item.get("text_label") or "Required information",
                    placeholder="Enter the required information",
                    callback=text_submit
                ))
            else:
                view = ConfirmView(interaction.user.id)
                await interaction.response.send_message(
                    f"🛒 Buy **{item['name']}** for **{cur(config, item['price'])}**?\n"
                    f"Remaining: **{cur(config, user_bal - item['price'])}**",
                    view=view, ephemeral=True
                )
                await view.wait()
                if view.value:
                    await _complete_purchase(interaction, item, None)
                else:
                    await interaction.followup.send("Purchase cancelled.", ephemeral=True)

        async def _complete_purchase(inter: discord.Interaction, shop_item, item_text: Optional[str]):
            config = db_get_config(self.guild.id)
            check_bal = db_get_xp(self.guild.id, self.user.id)
            if check_bal < shop_item["price"]:
                msg = f"❌ Insufficient {cur(config)}."
                if inter.response.is_done():
                    await inter.followup.send(msg, ephemeral=True)
                else:
                    await inter.response.send_message(msg, ephemeral=True)
                return
            # Re-check stock right before purchase to prevent race conditions
            fresh_item = db_get_shop_item(shop_item["id"], self.guild.id)
            if fresh_item and fresh_item.get("stock") is not None and fresh_item["stock"] == 0:
                msg = "❌ This item is sold out."
                if inter.response.is_done():
                    await inter.followup.send(msg, ephemeral=True)
                else:
                    await inter.response.send_message(msg, ephemeral=True)
                return

            # ── Approval flow ─────────────────────────────────────
            if fresh_item and fresh_item.get("requires_approval"):
                # Don't deduct gems yet — create a pending record and wait for owner approval
                purchase_id = db_add_pending_purchase(
                    self.guild.id, self.user.id,
                    shop_item["id"], shop_item["name"],
                    shop_item["price"], item_text
                )
                # Notify admin channel
                pending_embed = E(
                    "🔔 Purchase Awaiting Approval",
                    f"**Item:** {shop_item['name']}\n"
                    f"**Buyer:** {self.user.mention} ({self.user.display_name})\n"
                    f"**Price:** {cur(config, shop_item['price'])}"
                    + (f"\n**Info provided:** {item_text}" if item_text else ""),
                    C_GOLD
                )
                if shop_item.get("image_url"):
                    pending_embed.set_image(url=shop_item["image_url"])
                pending_embed.set_footer(text=f"Purchase ID: #{purchase_id} — use the buttons to approve or reject")
                pv = PendingPurchaseView(
                    purchase_id=purchase_id,
                    guild=self.guild,
                    buyer=self.user,
                    shop_item=fresh_item,
                    item_text=item_text,
                    bot_ref=inter.client
                )
                manager_role_id = config.get("manager_role_id")
                role_ping = f"<@&{manager_role_id}>" if manager_role_id else ""
                await notify_admin(inter.client, self.guild.id,
                                   content=role_ping,
                                   embed=pending_embed)
                # Also post view to admin channel so buttons appear there
                admin_ch_id = config.get("admin_channel_id")
                admin_ch = inter.client.get_channel(admin_ch_id) if admin_ch_id else None
                if admin_ch:
                    try:
                        await admin_ch.send(view=pv)
                    except Exception:
                        pass
                pending_msg = (
                    f"⏳ Your purchase request for **{shop_item['name']}** has been submitted!\n"
                    f"A Gems Owner will review it shortly. You'll receive a DM when it's approved or rejected.\n"
                    f"*(Your gems will only be deducted if approved.)*"
                )
                if inter.response.is_done():
                    await inter.followup.send(pending_msg, ephemeral=True)
                else:
                    await inter.response.send_message(pending_msg, ephemeral=True)
                # Refresh shop
                self.items = db_get_shop_items(self.guild.id)
                self._build()
                try:
                    if inter.response.is_done():
                        await inter.edit_original_response(embeds=self.embeds(), view=self)
                except Exception:
                    pass
                return

            new_bal = db_add_xp(self.guild.id, self.user.id, -shop_item["price"])
            # Decrement limited stock
            db_decrement_stock(shop_item["id"], self.guild.id)
            expires_at = None
            if shop_item.get("is_temporary") and shop_item.get("duration_days"):
                expires_at = (datetime.now() + timedelta(days=shop_item["duration_days"])).isoformat()
            db_add_inventory(self.guild.id, self.user.id, shop_item["name"], expires_at, item_text)

            # ── Create purchase ticket ──────────────────────────
            ticket_ch = await _create_purchase_ticket(
                inter.client, self.guild, self.user, shop_item, item_text
            )

            success_msg = (
                f"✅ **{shop_item['name']}** added to your inventory!\n"
                f"Remaining balance: **{cur(config, new_bal)}**"
            )
            if shop_item.get("is_temporary") and shop_item.get("show_duration"):
                success_msg += f"\n⏳ Expires in **{shop_item['duration_days']} days**"
            if ticket_ch:
                success_msg += f"\n🎫 A ticket has been opened: {ticket_ch.mention}"
            if inter.response.is_done():
                await inter.followup.send(success_msg, ephemeral=True)
            else:
                await inter.response.send_message(success_msg, ephemeral=True)
            # Notify admin if text was submitted (legacy admin channel notif kept as backup)
            if item_text:
                e = E("📝 Shop Order — Text Required",
                      f"**Item:** {shop_item['name']}\n**Buyer:** <@{self.user.id}>\n**Info:** {item_text}",
                      C_INFO)
                await notify_admin(inter.client, self.guild.id, embed=e)
            # Refresh shop
            self.items = db_get_shop_items(self.guild.id)
            self._build()
            try:
                if inter.response.is_done():
                    await inter.edit_original_response(embeds=self.embeds(), view=self)
            except Exception:
                pass

        return callback

    async def _prev(self, interaction: discord.Interaction):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("❌ Not your shop!", ephemeral=True)
            return
        self.page -= 1; self._build()
        await interaction.response.edit_message(embeds=self.embeds(), view=self)

    async def _next(self, interaction: discord.Interaction):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("❌ Not your shop!", ephemeral=True)
            return
        self.page += 1; self._build()
        await interaction.response.edit_message(embeds=self.embeds(), view=self)

# ══════════════════════════════════════════════════════════════
#  BOT SETUP
# ══════════════════════════════════════════════════════════════

intents = discord.Intents.default()
intents.message_content = True
intents.members          = True
intents.reactions        = True
intents.guilds           = True

# Tracks members who fire on_member_update with premium_since already set,
# so on_guild_update can attribute a 2nd+ server boost to the right member.
_pending_reboost:    dict[int, list]  = {}  # guild_id -> [member_id, ...]  (list supports simultaneous boosters)
_boost_announce_ts:  dict[int, float] = {}  # guild_id -> last announce unix timestamp

bot = commands.Bot(command_prefix="!", intents=intents)

# ══════════════════════════════════════════════════════════════
#  BACKGROUND TASKS
# ══════════════════════════════════════════════════════════════

@tasks.loop(minutes=1)
async def check_youtube():
    await bot.wait_until_ready()
    conn = get_db()
    guilds = conn.execute(
        "SELECT guild_id, youtube_channel_id FROM guild_config WHERE youtube_channel_id IS NOT NULL"
    ).fetchall()
    conn.close()
    for row in guilds:
        guild_id = row["guild_id"]
        yt_id    = row["youtube_channel_id"]
        videos   = await fetch_latest_videos(yt_id)
        if not videos:
            continue
        latest  = videos[0]
        current = db_get_current_video(guild_id)

        # Already tracking this video — nothing to do
        if current and current["video_id"] == latest["video_id"]:
            continue

        # ── Anti-regression guard ─────────────────────────────────────
        # Prevent the RSS feed from overriding a newer manual trigger with
        # an older cached entry.  This is the root cause of the repeat-ping
        # bug: after a manual /admin ping the RSS still shows the previous
        # video for up to 30 min, causing the bot to re-announce it every
        # poll cycle.
        #
        # Rule: if the RSS video was published MORE than 45 minutes before
        # the current video was detected/set, treat it as stale and skip.
        # 45 min is generous enough to cover normal RSS lag (~15-30 min)
        # while still blocking old entries from overriding manual triggers.
        if current:
            rss_pub = parse_rss_date(latest.get("published", ""))
            try:
                current_det = datetime.fromisoformat(current["detected_at"])
            except Exception:
                current_det = None
            if rss_pub and current_det and rss_pub < current_det - timedelta(minutes=45):
                print(f"[YouTube] ⏭️  Skipping stale RSS entry {latest['video_id']} "
                      f"(published {rss_pub} vs current detected {current_det})")
                continue

        print(f"[YouTube] 🆕 New video for guild {guild_id}: {latest['video_id']} — {latest.get('title', '')}")
        db_set_current_video(guild_id, latest["video_id"], latest["url"], latest["title"])
        await announce_video(bot, guild_id, latest["video_id"], latest["url"], latest["title"])

@tasks.loop(hours=216)   # 9 days — YouTube leases last 10, renew before expiry
async def renew_websub_subscriptions():
    """Re-subscribe to YouTube WebSub for every configured channel."""
    await bot.wait_until_ready()
    callback_url = os.environ.get("WEBHOOK_URL", "").rstrip('/')
    if not callback_url:
        return
    callback_url += "/youtube"
    conn = get_db()
    rows = conn.execute(
        "SELECT DISTINCT youtube_channel_id FROM guild_config WHERE youtube_channel_id IS NOT NULL"
    ).fetchall()
    conn.close()
    seen: set = set()
    for row in rows:
        cid = row["youtube_channel_id"]
        if cid in seen:
            continue
        seen.add(cid)
        await websub_subscribe(cid, callback_url)
        await asyncio.sleep(1)

@tasks.loop(minutes=15)
async def auto_backup():
    await bot.wait_until_ready()
    conn = get_db()
    guilds = conn.execute("SELECT guild_id FROM guild_config WHERE backup_channel_id IS NOT NULL").fetchall()
    conn.close()
    for row in guilds:
        await do_backup(bot, row["guild_id"])

@tasks.loop(hours=1)
async def check_expired_items():
    """Mark expired inventory items and notify admin channel."""
    await bot.wait_until_ready()
    now = datetime.now().isoformat()
    conn = get_db()
    expired = conn.execute(
        "SELECT * FROM inventory WHERE is_expired=0 AND expires_at IS NOT NULL AND expires_at <= ?",
        (now,)
    ).fetchall()
    for row in expired:
        conn.execute("UPDATE inventory SET is_expired=1 WHERE id=?", (row["id"],))
        conn.commit()
        guild_id = row["guild_id"]
        user_id  = row["user_id"]
        e = E("⏳ Item Expired",
              f"**Item:** {row['item_name']}\n**Member:** <@{user_id}>",
              C_ERROR)
        await notify_admin(bot, guild_id, embed=e)
    conn.close()

@tasks.loop(hours=24)
async def check_community_goals():
    """Check if any community goals completed and distribute rewards."""
    await bot.wait_until_ready()
    conn = get_db()
    goals = conn.execute(
        "SELECT * FROM community_goals WHERE completed=1 AND enabled=1"
    ).fetchall()
    # Mark as distributed (disable)
    for g in goals:
        contribs = json.loads(g["contributors"] or "[]")
        for uid in contribs:
            db_add_xp(g["guild_id"], uid, g["reward_xp"])
        if contribs:
            cfg = db_get_config(g["guild_id"])
            e = E("🏁 Community Goal Completed!",
                  f"**{g['name']}**\n{len(contribs)} contributors each earned **+{cur(cfg, g['reward_xp'])}**!",
                  C_EVENT)
            await notify_xp(bot, g["guild_id"], embed=e)
        conn.execute("UPDATE community_goals SET enabled=0 WHERE id=?", (g["id"],))
        conn.commit()
    conn.close()

@tasks.loop(minutes=1)
async def check_share_channel_lock():
    """Lock or unlock the share channel based on whether the share window is currently open."""
    await bot.wait_until_ready()
    now_ts = int(datetime.utcnow().timestamp())
    conn   = get_db()
    guilds = conn.execute(
        "SELECT gc.guild_id, cv.deadline_ts "
        "FROM guild_config gc "
        "LEFT JOIN current_video cv ON cv.guild_id = gc.guild_id "
        "WHERE gc.share_lock_role_id IS NOT NULL AND gc.share_channel_id IS NOT NULL"
    ).fetchall()
    conn.close()
    for row in guilds:
        guild_id   = row["guild_id"]
        deadline   = row["deadline_ts"]
        # Window open  → deadline exists and is in the future → unlock
        # Window closed → no deadline, or deadline has passed  → lock
        window_open = bool(deadline and deadline > now_ts)
        await _set_share_channel_lock(bot, guild_id, locked=not window_open)

# In-memory set tracking (guild_id, video_id, user_id) streak reminder DMs already sent this window.
# Prevents the 1-minute loop from DMing the same member multiple times.
_streak_reminder_sent: set = set()

@tasks.loop(minutes=1)
async def check_streak_reminders():
    """DM members with an active streak who haven't shared the current video and have < 5 min left."""
    await bot.wait_until_ready()
    now_ts = int(datetime.utcnow().timestamp())
    conn = get_db()
    videos = conn.execute(
        "SELECT cv.guild_id, cv.video_id, cv.deadline_ts "
        "FROM current_video cv "
        "JOIN guild_config gc ON gc.guild_id = cv.guild_id "
        "WHERE cv.deadline_ts IS NOT NULL "
        "AND cv.deadline_ts > ? "
        "AND cv.deadline_ts - ? <= 300 "  # 5 minutes = 300 seconds
        "AND gc.streak_reminder_enabled = 1",
        (now_ts, now_ts)
    ).fetchall()
    for row in videos:
        guild_id  = row["guild_id"]
        video_id  = row["video_id"]
        deadline  = row["deadline_ts"]
        guild = bot.get_guild(guild_id)
        if not guild:
            continue
        # Find members with a streak who haven't shared this video
        streaks = conn.execute(
            "SELECT user_id, current_streak FROM streaks WHERE guild_id=? AND current_streak > 0",
            (guild_id,)
        ).fetchall()
        for s in streaks:
            uid = s["user_id"]
            if db_has_shared(guild_id, video_id, uid):
                continue
            # Avoid DM spam: only send once per video per member across loop ticks
            reminder_key = (guild_id, video_id, uid)
            if reminder_key in _streak_reminder_sent:
                continue
            member = guild.get_member(uid)
            if not member or member.bot:
                continue
            try:
                await member.send(
                    f"⚠️ **Streak Alert!** Your 🔥 **{s['current_streak']}-video streak** is at risk!\n"
                    f"You have less than 5 minutes to share the video — <t:{deadline}:R>\n"
                    f"Go share it now to keep your streak alive!"
                )
                _streak_reminder_sent.add(reminder_key)
            except discord.Forbidden:
                pass
    conn.close()


@tasks.loop(hours=24)
async def check_daily_quests():
    """Send daily quest DMs to members with the configured role at UTC midnight."""
    await bot.wait_until_ready()
    date_key = db_today_key()
    conn = get_db()
    guilds = conn.execute(
        "SELECT guild_id, daily_quest_role_id, daily_quest_dm_enabled, daily_quest_xp "
        "FROM guild_config WHERE daily_quest_enabled=1"
    ).fetchall()
    conn.close()
    for row in guilds:
        guild_id   = row["guild_id"]
        role_id    = row["daily_quest_role_id"]
        dm_enabled = row["daily_quest_dm_enabled"]
        quest_xp   = row["daily_quest_xp"] or 50
        guild = bot.get_guild(guild_id)
        if not guild:
            continue
        if role_id:
            role = guild.get_role(role_id)
            if not role:
                continue
            members = [m for m in role.members if not m.bot]
        else:
            members = [m for m in guild.members if not m.bot]
        for member in members:
            quests = db_assign_daily_quests(guild_id, member.id, date_key, count=3)
            if not dm_enabled:
                continue
            # Check if we already sent a DM today
            conn2 = get_db()
            already_sent = conn2.execute(
                "SELECT COUNT(*) FROM daily_quests WHERE guild_id=? AND user_id=? AND date_key=? AND dm_sent=1",
                (guild_id, member.id, date_key)
            ).fetchone()[0]
            conn2.close()
            if already_sent:
                continue
            cfg_q  = db_get_config(guild_id)
            c_emoji = cfg_q.get("currency_emoji", "💎")
            lines = []
            for q in quests:
                lines.append(f"• {q['quest_name']} — {quest_xp} {c_emoji}")
            try:
                await member.send(
                    f"🗓️ Daily Quests — {guild.name} ({date_key})\n\n"
                    + "\n".join(lines)
                    + f"\n\nComplete them today to earn your rewards!\n"
                    f"Use /quests to track your progress. For the Gems bonus quest, ping the Gems Owner role and ask them to award your bonus. Good luck 🍀"
                )
                conn3 = get_db()
                conn3.execute(
                    "UPDATE daily_quests SET dm_sent=1 WHERE guild_id=? AND user_id=? AND date_key=?",
                    (guild_id, member.id, date_key)
                )
                conn3.commit()
                conn3.close()
            except (discord.Forbidden, discord.HTTPException):
                pass
            await asyncio.sleep(0.5)

@check_daily_quests.before_loop
async def before_daily_quests():
    """Wait until UTC midnight to start the daily quest loop."""
    await bot.wait_until_ready()
    now = datetime.utcnow()
    next_midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    await asyncio.sleep((next_midnight - now).total_seconds())


@tasks.loop(minutes=1)
async def check_new_shop_item_dms():
    """DM shop managers once for each new item after the configured delay."""
    await bot.wait_until_ready()
    conn = get_db()
    items = conn.execute(
        """
        SELECT si.*, gc.new_item_dm_enabled, gc.new_item_dm_delay_minutes,
               gc.manager_role_id, gc.purchase_dm_role_id
        FROM shop_items si
        JOIN guild_config gc ON gc.guild_id = si.guild_id
        WHERE COALESCE(si.new_item_dm_sent, 0)=0
          AND si.created_at IS NOT NULL
          AND COALESCE(gc.new_item_dm_enabled, 1)=1
        """
    ).fetchall()
    conn.close()

    now = datetime.utcnow()
    for row in items:
        item = dict(row)
        try:
            created_at = datetime.fromisoformat(item["created_at"])
        except (TypeError, ValueError):
            # A malformed timestamp must not break notifications for other
            # guilds; mark this item handled rather than retrying forever.
            conn_bad = get_db()
            conn_bad.execute(
                "UPDATE shop_items SET new_item_dm_sent=1 WHERE id=? AND guild_id=?",
                (item["id"], item["guild_id"]),
            )
            conn_bad.commit()
            conn_bad.close()
            continue

        delay_minutes = max(0, int(item.get("new_item_dm_delay_minutes") or 5))
        if now < created_at + timedelta(minutes=delay_minutes):
            continue

        guild = bot.get_guild(item["guild_id"])
        if not guild:
            continue

        role_id = item.get("purchase_dm_role_id") or item.get("manager_role_id")
        role = guild.get_role(role_id) if role_id else None
        if not role:
            # Leave it pending so a manager role configured later can receive
            # the notification.
            continue

        config = db_get_config(guild.id)
        image_url = item.get("image_url")
        embed = E(
            "🆕 New Shop Item Ready",
            f"**Item:** {item['name']}\n"
            f"**Price:** {cur(config, item['price'])}\n"
            f"**Created:** <t:{int(created_at.timestamp())}:R>\n\n"
            "Please finish the image, reward keys, stock, and options before "
            "publishing the shop.",
            C_GOLD,
        )
        if image_url:
            embed.set_image(url=image_url)
        embed.set_footer(text=f"Shop item ID: {item['id']}")

        sent_count = 0
        for member in role.members:
            if member.bot:
                continue
            try:
                await member.send(embed=embed)
                sent_count += 1
            except discord.Forbidden:
                continue
            except discord.HTTPException:
                continue
            except Exception as ex:
                print(f"[NewItemDM] Failed for {member}: {ex}")

        if sent_count:
            conn_sent = get_db()
            conn_sent.execute(
                "UPDATE shop_items SET new_item_dm_sent=1 WHERE id=? AND guild_id=?",
                (item["id"], item["guild_id"]),
            )
            conn_sent.commit()
            conn_sent.close()
            await bot_log(
                bot,
                guild.id,
                "🆕 New Shop Item DM Sent",
                f"**Item:** {item['name']}\n"
                f"**Recipients:** {sent_count} member(s) with <@&{role.id}>\n"
                f"**Delay:** {delay_minutes} minute(s)",
                C_INFO,
            )


@check_new_shop_item_dms.before_loop
async def before_new_shop_item_dms():
    await bot.wait_until_ready()


@tasks.loop(hours=24)
async def send_daily_shop():
    """Every day at 08:00 UTC, post a compact shop overview in the configured channel."""
    await bot.wait_until_ready()
    conn = get_db()
    guilds = conn.execute(
        "SELECT guild_id FROM guild_config WHERE daily_shop_channel_id IS NOT NULL"
    ).fetchall()
    conn.close()
    for row in guilds:
        guild_id = row["guild_id"]
        config   = db_get_config(guild_id)
        ch_id    = config.get("daily_shop_channel_id")
        if not ch_id:
            continue
        ch = bot.get_channel(ch_id)
        if not ch:
            continue
        items = db_get_shop_items(guild_id)
        if not items:
            continue
        c_name  = config.get("currency_name")  or "Gems"
        c_emoji = config.get("currency_emoji") or "💎"
        shop_ch = config.get("shop_channel_id") or config.get("commands_channel_id")
        shop_ch_str = f"<#{shop_ch}>" if shop_ch else "the shop channel"
        # Build a compact embed per item using the full image so artwork is
        # never cropped into Discord's thumbnail box.
        embeds = []
        header = discord.Embed(
            title="🛍️ Today's Shop",
            description=f"Here's what's available right now. Use `/shop` in {shop_ch_str} to buy!",
            color=C_GOLD
        )
        header.timestamp = datetime.utcnow()
        embeds.append(header)
        now_iso = datetime.utcnow().isoformat()
        for item in items:
            # Skip items whose listing has expired
            if item.get("item_expires_at") and item["item_expires_at"] < now_iso:
                continue
            line = f"{c_emoji} **{item['price']:,} {c_name}**"
            ie = discord.Embed(title=item["name"], description=line, color=C_GOLD)
            if item.get("image_url"):
                ie.set_image(url=item["image_url"])
            # Footer: remaining stock (replaces "Provided by")
            if item.get("stock") is not None:
                if item["stock"] == 0:
                    ie.set_footer(text="🚫 Sold out")
                else:
                    ie.set_footer(text=f"📦 {item['stock']} remaining")
            embeds.append(ie)
        if len(embeds) == 1:   # only the header, no live items
            continue
        # Discord allows up to 10 embeds per message
        posted = False
        for i in range(0, len(embeds), 10):
            try:
                await ch.send(embeds=embeds[i:i+10])
                posted = True
            except Exception as ex:
                print(f"[DailyShop] Error posting for guild {guild_id}: {ex}")
        if posted:
            await bot_log(bot, guild_id, "🛍️ Daily Shop Posted",
                          f"**Channel:** <#{ch_id}>\n**Items:** {len(items)}")

@send_daily_shop.before_loop
async def before_daily_shop():
    """Wait until 08:00 UTC to start the daily shop post loop."""
    await bot.wait_until_ready()
    now    = datetime.utcnow()
    target = now.replace(hour=8, minute=0, second=0, microsecond=0)
    if now >= target:
        target += timedelta(days=1)
    await asyncio.sleep((target - now).total_seconds())


@tasks.loop(hours=24)
async def send_revive_ping_button():
    """Once per day, post a revive-ping opt-in button in ONE random configured channel per guild."""
    await bot.wait_until_ready()
    date_key = db_today_key()
    conn = get_db()
    guilds = conn.execute(
        "SELECT guild_id, revive_ping_role_id, revive_ping_channels "
        "FROM guild_config WHERE revive_ping_enabled=1 AND revive_ping_role_id IS NOT NULL"
    ).fetchall()
    conn.close()

    for row in guilds:
        guild_id  = row["guild_id"]
        role_id   = row["revive_ping_role_id"]
        try:
            ch_ids = json.loads(row["revive_ping_channels"] or "[]")
        except Exception:
            ch_ids = []
        if not ch_ids:
            continue

        # Skip if already sent today
        conn2 = get_db()
        already = conn2.execute(
            "SELECT 1 FROM revive_ping_sent WHERE guild_id=? AND date_key=?",
            (guild_id, date_key)
        ).fetchone()
        conn2.close()
        if already:
            continue

        # Pick a random channel from the configured pool
        _random.shuffle(ch_ids)
        sent = False
        for ch_id in ch_ids:
            ch = bot.get_channel(ch_id)
            if not ch:
                continue
            try:
                if not await send_ping_role_message(ch, "both", guild_id):
                    continue
                conn3 = get_db()
                conn3.execute(
                    "INSERT OR REPLACE INTO revive_ping_sent (guild_id, date_key, channel_id) VALUES (?,?,?)",
                    (guild_id, date_key, ch_id)
                )
                conn3.commit()
                conn3.close()
                await bot_log(bot, guild_id, "🔔 Revive Ping Sent",
                              f"**Channel:** <#{ch_id}>\n**Date:** {date_key}")
                sent = True
                break
            except Exception:
                continue

@send_revive_ping_button.before_loop
async def before_revive_ping():
    """Wait until a random time between 12:00 and 20:00 UTC to post the revive ping button."""
    await bot.wait_until_ready()
    now  = datetime.utcnow()
    hour = _random.randint(12, 19)          # 12:xx – 19:xx UTC
    mins = _random.randint(0, 59)
    target = now.replace(hour=hour, minute=mins, second=0, microsecond=0)
    if now >= target:
        target += timedelta(days=1)
        # Re-randomise for the next day
        hour = _random.randint(12, 19)
        mins = _random.randint(0, 59)
        target = target.replace(hour=hour, minute=mins)
    await asyncio.sleep((target - now).total_seconds())


# ══════════════════════════════════════════════════════════════
#  EVENTS
# ══════════════════════════════════════════════════════════════

@bot.event
async def on_ready():
    now        = datetime.utcnow()
    boot_delta = now - BOT_START_TIME
    boot_secs  = int(boot_delta.total_seconds())
    if boot_secs < 60:
        boot_str = f"{boot_secs}s"
    elif boot_secs < 3600:
        boot_str = f"{boot_secs // 60}min {boot_secs % 60}s"
    else:
        h = boot_secs // 3600
        m = (boot_secs % 3600) // 60
        boot_str = f"{h}h {m}min"
    print("=" * 60)
    print(f"🔄 BOT RESTARTED — {now.strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"   Process boot time : {boot_str}")
    print(f"   Logged in as      : {bot.user} ({bot.user.id})")
    print(f"   Guilds            : {len(bot.guilds)}")
    print("=" * 60)
    await restore_from_discord(bot)
    init_db()
    # Re-register the persistent role buttons so messages posted before a
    # restart continue to accept both Revive and Drops opt-ins.
    bot.add_view(RevivePingView(0, 0))
    # Cache invites for all guilds
    for guild in bot.guilds:
        db_ensure_config(guild.id)
        db_ensure_achievement_config(guild.id)
        try:
            invites = await guild.invites()
            db_cache_invites(guild.id, invites)
        except Exception:
            pass
        await bot_log(
            bot,
            guild.id,
            "🔄 Bot Online",
            f"**Logged in as:** {bot.user} (`{bot.user.id}`)\n"
            f"**Started:** {now.strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
            f"**Process boot time:** {boot_str}\n"
            f"**Guilds connected:** {len(bot.guilds)}\n"
            "The bot is awake and background tasks have been checked.",
            C_SUCCESS,
        )
    for loop in [check_youtube, auto_backup, check_expired_items, check_community_goals,
                 check_streak_reminders, check_share_channel_lock, renew_websub_subscriptions,
                 check_daily_quests, check_new_shop_item_dms,
                 send_revive_ping_button, send_daily_shop]:
        if not loop.is_running():
            loop.start()
    # Initial WebSub subscription for all configured channels
    callback_url = os.environ.get("WEBHOOK_URL", "").rstrip('/')
    if callback_url:
        callback_url += "/youtube"
        conn = get_db()
        rows = conn.execute(
            "SELECT DISTINCT youtube_channel_id FROM guild_config WHERE youtube_channel_id IS NOT NULL"
        ).fetchall()
        conn.close()
        seen: set = set()
        for row in rows:
            cid = row["youtube_channel_id"]
            if cid in seen:
                continue
            seen.add(cid)
            await websub_subscribe(cid, callback_url)
            await asyncio.sleep(0.5)
    else:
        print("[WebSub] ⚠️  WEBHOOK_URL not set — push disabled, RSS fallback (5 min) active")
    # Reward existing server tag holders on startup
    for guild in bot.guilds:
        cfg = db_get_config(guild.id)
        if not cfg.get("server_tag_enabled", 0):
            continue
        try:
            for member in guild.members:
                if member.bot:
                    continue
                if member_has_server_tag(member):
                    await _reward_server_tag(guild, member, cfg)
                    await asyncio.sleep(0.1)
        except Exception as _e:
            print(f"[ServerTag] startup scan error for {guild.name}: {_e}")

    try:
        synced = await bot.tree.sync()
        print(f"✅ Synced {len(synced)} slash command(s)")
    except Exception as e:
        print(f"❌ Slash sync error: {e}")

@bot.event
async def on_guild_join(guild: discord.Guild):
    db_ensure_config(guild.id)
    db_ensure_achievement_config(guild.id)
    try:
        invites = await guild.invites()
        db_cache_invites(guild.id, invites)
    except Exception:
        pass
    print(f"[+] Joined: {guild.name} ({guild.id})")

@bot.event
async def on_invite_create(invite: discord.Invite):
    if invite.guild:
        try:
            invites = await invite.guild.invites()
            db_cache_invites(invite.guild.id, invites)
        except Exception:
            pass

@bot.event
async def on_member_join(member: discord.Member):
    guild_id = member.guild.id
    config = db_get_config(guild_id)
    invite_xp_amt = config.get("invite_xp", 25)
    try:
        # Guard: if this member was already counted before (re-join), skip reward
        if db_get_invite_log(guild_id, member.id):
            pass  # already recorded — update cache but give no XP
        else:
            current_invites = await member.guild.invites()
            inviter_id = db_find_used_invite(guild_id, current_invites)
            db_cache_invites(guild_id, current_invites)
            if inviter_id and invite_xp_amt > 0:
                # Apply double XP multiplier if active
                mult = db_has_double_xp(guild_id)
                xp_to_give = int(invite_xp_amt * mult)
                new_xp = db_add_xp(guild_id, inviter_id, xp_to_give)
                db_increment_stat(guild_id, inviter_id, "total_invites")
                # Record invite so re-joins don't re-award
                db_log_invite(guild_id, member.id, inviter_id, xp_to_give)
                # Assign monthly quests if needed
                month_key = current_month_key()
                db_assign_monthly_quests(guild_id, inviter_id, month_key)
                # Update quest progress
                newly_done = db_update_quest_progress(guild_id, inviter_id, "invite_members")
                await process_quest_completions(bot, guild_id, inviter_id, newly_done)
                # Daily quest progress for inviter
                if db_get_config(guild_id).get("daily_quest_enabled", 0):
                    dq_date = db_today_key()
                    dq_done = db_daily_quest_progress(guild_id, inviter_id, dq_date, "dq_invite")
                    await process_daily_quest_completions(bot, guild_id, inviter_id, dq_done, dq_date)
                # Check achievements
                await check_achievements(bot, guild_id, inviter_id)
                # Notify XP channel
                inviter = member.guild.get_member(inviter_id)
                mult_str = f" (×{mult} Double!)" if mult > 1 else ""
                e = E("📨 New Invite!", color=C_INFO)
                e.description = (
                    f"**{member.display_name}** joined!\n"
                    f"Invited by: <@{inviter_id}>\n"
                    f"Reward: **+{cur(config, xp_to_give)}**{mult_str}  |  Balance: **{cur(config, new_xp)}**"
                )
                await notify_xp(bot, guild_id, embed=e)
                await bot_log(bot, guild_id, "📨 Invite Reward",
                              f"**New member:** {member.mention}\n"
                              f"**Invited by:** <@{inviter_id}>\n"
                              f"**Reward:** +{cur(config, xp_to_give)}{mult_str}\n"
                              f"**Balance:** {cur(config, new_xp)}", C_INFO)
            else:
                # No inviter found — still refresh cache
                current_invites = await member.guild.invites()
                db_cache_invites(guild_id, current_invites)
    except Exception as e:
        print(f"[Invite] Error on member join: {e}")

    # ── Log member join ─────────────────────────────────────────
    await bot_log(bot, guild_id, "👋 Member Joined",
                  f"**Member:** {member.mention} ({member.display_name})\n"
                  f"**Account created:** <t:{int(member.created_at.timestamp())}:R>")

    # ── Welcome DM (on join) ────────────────────────────────────
    config = db_get_config(guild_id)
    if config.get("welcome_dm_enabled", 0):
        # Wait for Discord to fully register the member before sending a DM.
        # Without this delay, DMs to brand-new accounts often fail with 403.
        await asyncio.sleep(2)
        await send_welcome_dm(member, config, trigger="join")

    # ── Server welcome message (on join) ────────────────────────
    if config.get("server_welcome_enabled", 0):
        sw_ch_id = config.get("server_welcome_channel_id")
        if sw_ch_id:
            sw_ch = bot.get_channel(sw_ch_id)
            if sw_ch:
                try:
                    await sw_ch.send(
                        f"👋 Welcome to **{member.guild.name}**, {member.mention}! "
                        "Use `/tutorial` to learn how to earn rewards and unlock perks. 🎉"
                    )
                except Exception:
                    pass


@bot.event
async def on_member_remove(member: discord.Member):
    """When a member leaves, remove their invite credit so the inviter's count stays clean."""
    guild_id = member.guild.id
    try:
        record = db_get_invite_log(guild_id, member.id)
        if not record:
            return
        inviter_id = record["inviter_id"]
        xp_given   = record.get("xp_given", 0)
        # Remove the XP that was awarded for this invite
        if xp_given > 0:
            conn = get_db()
            conn.execute(
                "UPDATE xp_data SET xp = MAX(0, xp - ?) WHERE guild_id=? AND user_id=?",
                (xp_given, guild_id, inviter_id)
            )
            conn.commit()
            conn.close()
        # Decrement total_invites stat (floor at 0)
        conn = get_db()
        conn.execute(
            "UPDATE user_stats SET total_invites = MAX(0, total_invites - 1) "
            "WHERE guild_id=? AND user_id=?",
            (guild_id, inviter_id)
        )
        conn.commit()
        conn.close()
        # NOTE: invite_log entry is intentionally kept so re-joins never re-award gems
        # Notify gems channel
        config  = db_get_config(guild_id)
        inviter = member.guild.get_member(inviter_id)
        e = E("📨 Invite Lost", color=discord.Color.orange())
        e.description = (
            f"**{member.display_name}** left the server.\n"
            f"Invite by <@{inviter_id}> removed."
            + (f"\n**−{cur(config, xp_given)}** deducted." if xp_given > 0 else "")
        )
        await notify_xp(bot, guild_id, embed=e)
    except Exception as ex:
        print(f"[Invite] Error on member remove: {ex}")


@bot.event
async def on_guild_update(before: discord.Guild, after: discord.Guild):
    """Award boost XP for ALL new boost slots (first or re-boost) based on the delta."""
    prev = before.premium_subscription_count or 0
    new  = after.premium_subscription_count or 0
    if new <= prev:
        return
    delta        = new - prev          # Number of new boost slots applied at once
    guild_id     = after.id
    members_list = _pending_reboost.pop(guild_id, [])
    if not members_list:
        return
    config = db_get_config(guild_id)
    if not config.get("boost_quest_enabled", 1):
        return
    boost_xp = config.get("boost_quest_xp", 100)
    # Award each queued booster for one slot (covers simultaneous boosts correctly)
    for member_id in members_list:
        new_xp = db_add_xp(guild_id, member_id, boost_xp)
        db_increment_stat(guild_id, member_id, "total_boosts")
        member  = after.get_member(member_id)
        display = member.display_name if member else f"<@{member_id}>"
        e = E("🚀 Server Boost!", color=C_ACHIEVE)
        e.description = (
            f"**{display}** boosted the server!\n"
            f"Reward: **+{cur(config, boost_xp)}**  |  Balance: **{cur(config, new_xp)}**"
        )
        await notify_xp(bot, guild_id, embed=e)
        month_key = current_month_key()
        db_assign_monthly_quests(guild_id, member_id, month_key)
        await check_achievements(bot, guild_id, member_id)

@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    """Track server boosts, server tag rewards, and role-based welcome DM."""
    guild_id = after.guild.id
    config = db_get_config(guild_id)

    # ── Detect boost (first or re-boost) ───────────────────────
    # Always store the member in _pending_reboost so on_guild_update can
    # award XP for the exact number of boost slots applied (delta).
    if not before.premium_since and after.premium_since:
        # First boost → queue for on_guild_update
        # Use a list so multiple simultaneous boosters are all tracked
        if guild_id not in _pending_reboost:
            _pending_reboost[guild_id] = []
        if after.id not in _pending_reboost[guild_id]:
            _pending_reboost[guild_id].append(after.id)
        # Boost announcement (rate-limited to once/hour per guild)
        announce_role_id = config.get("boost_announce_role_id")
        announce_ch_id   = config.get("boost_announce_channel_id") or config.get("notification_channel_id")
        import time as _time
        now_ts  = _time.time()
        last_ts = _boost_announce_ts.get(guild_id, 0.0)
        if announce_ch_id and (now_ts - last_ts) >= 3600:
            ch = bot.get_channel(announce_ch_id)
            if ch:
                role_ping = f"<@&{announce_role_id}> — " if announce_role_id else ""
                try:
                    await ch.send(
                        f"🚀 **{after.mention}** just boosted the server — thank you so much! 💜\n"
                        f"{role_ping}you can boost too to earn exclusive rewards!"
                    )
                    _boost_announce_ts[guild_id] = now_ts
                except Exception:
                    pass
    elif before.premium_since and after.premium_since:
        # Re-boost (adding another slot) → queue for on_guild_update
        if guild_id not in _pending_reboost:
            _pending_reboost[guild_id] = []
        if after.id not in _pending_reboost[guild_id]:
            _pending_reboost[guild_id].append(after.id)

    # ── Server tag reward ───────────────────────────────────────
    if config.get("server_tag_enabled", 0):
        before_tag = getattr(before, "guild_tag", None)
        after_tag  = getattr(after,  "guild_tag", None)
        if after_tag and not before_tag:
            await _reward_server_tag(after.guild, after, config)

    # ── Role-based welcome DM ───────────────────────────────────
    # Fires whenever welcome_dm_on_role_id is configured — independent of welcome_dm_enabled.
    on_role_id = config.get("welcome_dm_on_role_id")
    if on_role_id:
        before_role_ids = {r.id for r in before.roles}
        after_role_ids  = {r.id for r in after.roles}
        if on_role_id in after_role_ids and on_role_id not in before_role_ids:
            await send_welcome_dm(after, config, trigger="role")

    # ── Role-based server welcome message ──────────────────────
    sw_on_role_id = config.get("server_welcome_on_role_id")
    if sw_on_role_id and config.get("server_welcome_enabled", 0):
        before_role_ids = {r.id for r in before.roles}
        after_role_ids  = {r.id for r in after.roles}
        if sw_on_role_id in after_role_ids and sw_on_role_id not in before_role_ids:
            sw_ch_id = config.get("server_welcome_channel_id")
            if sw_ch_id:
                sw_ch = bot.get_channel(sw_ch_id)
                if sw_ch:
                    try:
                        await sw_ch.send(
                            f"👋 Welcome, {after.mention}! "
                            "Use `/tutorial` to learn how to earn rewards and unlock perks. 🎉"
                        )
                    except Exception:
                        pass

    # ── Nickname prefix based on role ──────────────────────────
    prefix_role_id = config.get("prefix_role_id")
    if prefix_role_id and config.get("nick_prefix"):
        _before_roles = {r.id for r in before.roles}
        _after_roles  = {r.id for r in after.roles}
        if prefix_role_id in _after_roles and prefix_role_id not in _before_roles:
            # Role just added → apply prefix
            await apply_nick_prefix(after.guild, after, add=True)
        elif prefix_role_id not in _after_roles and prefix_role_id in _before_roles:
            # Role just removed → strip prefix
            await apply_nick_prefix(after.guild, after, add=False)

@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if not payload.guild_id:
        return
    guild = bot.get_guild(payload.guild_id)
    if not guild:
        return
    actor = guild.get_member(payload.user_id)
    if not actor or actor.bot:
        return
    config = db_get_config(payload.guild_id)
    if not config:
        return

    emoji_str = (f"<:{payload.emoji.name}:{payload.emoji.id}>"
                 if payload.emoji.is_custom_emoji() else str(payload.emoji))

    # ── Cancel emoji: revoke a previously awarded gem bonus on this message ──
    cancel_emoji = config.get("cancel_emoji", "❌")
    # Normalise variation selectors so ❌️ == ❌
    def _norm_emoji(s: str) -> str:
        return s.replace("\ufe0f", "").replace("\ufe0e", "")
    if _norm_emoji(emoji_str) == _norm_emoji(cancel_emoji) and is_xp_manager(actor, config):
        existing   = db_get_reaction_msg(payload.guild_id, payload.message_id)
        share_rec  = db_get_share_log(payload.guild_id, payload.message_id)
        config_r   = db_get_config(payload.guild_id)
        channel    = bot.get_channel(payload.channel_id)

        # Fetch the message to find the author (needed for DM + streak revert)
        target_member = None
        if channel:
            try:
                fetched_msg = await channel.fetch_message(payload.message_id)
                if fetched_msg and not fetched_msg.author.bot:
                    target_member = guild.get_member(fetched_msg.author.id) or fetched_msg.author
            except Exception:
                pass

        react_amount = 0
        share_amount = 0
        streak_before_rev = 0

        # ── 1. Cancel the ✅ reaction bonus if it was already given ──
        if existing and not existing.get("cancelled"):
            t_id = existing["target_uid"]
            react_amount = existing.get("amount", 0)
            if react_amount > 0:
                db_add_xp(payload.guild_id, t_id, -react_amount)
            db_cancel_reaction_msg(payload.guild_id, payload.message_id)
            if not target_member:
                target_member = guild.get_member(t_id)
        elif not existing:
            # Pre-block so ✅ cannot give a bonus later
            db_block_reaction_msg(payload.guild_id, payload.message_id)

        # ── 2. Revert the share XP + streak if the share was validated ──
        if share_rec and not share_rec.get("cancelled"):
            t_id_s         = share_rec["user_id"]
            share_amount   = share_rec.get("xp_given", 0)
            streak_before_rev = share_rec.get("streak_before", 0)
            if not target_member:
                target_member = guild.get_member(t_id_s)
            if share_amount > 0:
                db_add_xp(payload.guild_id, t_id_s, -share_amount)
            # Restore streak to its value before the share
            db_update_streak(payload.guild_id, t_id_s, streak_before_rev,
                             share_rec.get("video_id") or "")
            await update_streak_nickname(guild, t_id_s, streak_before_rev)
            # Remove the video_shares entry so the member can post again
            db_remove_share(payload.guild_id, share_rec["video_id"], t_id_s)
            db_cancel_share_log(payload.guild_id, payload.message_id)

        total_removed  = react_amount + share_amount
        streak_reverted = share_rec and not share_rec.get("cancelled")

        # ── 3. Channel notification ──
        if channel:
            mention = target_member.mention if target_member else "(unknown)"
            if total_removed > 0 or share_rec:
                notif = f"❌ Share rejected for {mention}"
                if total_removed > 0:
                    notif += f" — **{cur(config_r, total_removed)}** removed"
                if streak_reverted:
                    notif += f" — streak reset to 🔥{streak_before_rev}"
                notif += " — can retry with a new post."
                try:
                    await channel.send(notif, delete_after=_ttl(config_r, "msg_ttl_share_reject"))
                except Exception:
                    pass
            else:
                try:
                    await channel.send(
                        f"🚫 Message blocked for {mention} — no reward can be assigned.",
                        delete_after=_ttl(config_r, "msg_ttl_block_msg"))
                except Exception:
                    pass

        # ── 4. DM to the member ──
        if target_member:
            dm_lines = [f"❌ Your share was rejected in **{guild.name}**."]
            if share_amount > 0:
                dm_lines.append(f"**{cur(config_r, share_amount)}** were removed from your balance.")
            if streak_reverted:
                dm_lines.append(f"Your streak was reset to 🔥{streak_before_rev}.")
            dm_lines.append(
                "Make sure your screenshot clearly shows your comment on the video, "
                "then repost and get it validated! 💪"
            )
            try:
                await target_member.send("\n".join(dm_lines))
            except Exception:
                pass

        # ── 5. Log ──
        await bot_log(bot, payload.guild_id, "❌ Share Rejected",
                      f"**Rejected by:** {actor.mention} ({actor.display_name})\n"
                      f"**Member:** {target_member.mention if target_member else '(unknown)'}\n"
                      + (f"**Removed:** {cur(config_r, total_removed)}\n" if total_removed else "")
                      + (f"**Streak reset to:** 🔥{streak_before_rev}\n" if streak_reverted else "")
                      + "**Retry:** allowed",
                      C_ERROR)
        return

    # ── Reaction emoji: award gems to the message author ──
    configured = config.get("reaction_emoji", "✅")
    if emoji_str != configured:
        return
    if not is_xp_manager(actor, config):
        return

    # Restrict to the configured reaction channel (if set)
    reaction_ch_id = config.get("reaction_channel_id")
    if reaction_ch_id and payload.channel_id != reaction_ch_id:
        return

    channel = bot.get_channel(payload.channel_id)
    if not channel:
        return
    try:
        message = await channel.fetch_message(payload.message_id)
    except Exception:
        return
    target = message.author
    if target.bot or target.id == actor.id:
        return
    existing_rm = db_get_reaction_msg(payload.guild_id, payload.message_id)
    if existing_rm:
        return  # already rewarded, or blocked/cancelled — no re-give
    react_xp   = config.get("reaction_xp", 50)
    cooldown_h = config.get("reaction_cooldown_h", 1)
    can_give, mins_left = db_reaction_cooldown_ok(payload.guild_id, target.id, cooldown_h)
    if not can_give:
        try:
            await channel.send(
                f"⏱️ {target.mention} must wait **{mins_left} min** before receiving a reaction bonus again.",
                delete_after=_ttl(config, "msg_ttl_reaction_cooldown"))
        except Exception:
            pass
        return
    # Apply double XP multiplier
    mult = db_has_double_xp(payload.guild_id)
    xp_to_give = int(react_xp * mult)
    new_xp = db_add_xp(payload.guild_id, target.id, xp_to_give)
    db_set_reaction_cooldown(payload.guild_id, target.id)
    db_add_reaction_msg(payload.guild_id, payload.message_id, target.id, actor.id, xp_to_give)

    mult_str = f" (×{mult})" if mult > 1 else ""
    config_r  = db_get_config(payload.guild_id)
    # A reaction bonus is a Gems reward only. It must never create or change
    # a video streak: streaks are updated exclusively when a share is
    # validated in _handle_share().
    # Re-read the balance after the write so the displayed total cannot be
    # stale if another reward was recorded just before this callback.
    displayed_balance = db_get_xp(payload.guild_id, target.id)
    msg = (f"{config_r.get('currency_emoji', '💎')} {target.mention} received "
           f"**+{cur(config_r, xp_to_give)}**{mult_str} from {actor.mention}! "
           f"Total: **{cur(config_r, displayed_balance)}**")
    try:
        await channel.send(msg, delete_after=_ttl(config_r, "msg_ttl_reaction_bonus"))
    except Exception:
        pass
    await check_achievements(bot, payload.guild_id, target.id)
    await bot_log(bot, payload.guild_id, "✅ Reaction Reward",
                  f"**Recipient:** {target.mention} ({target.display_name})\n"
                  f"**Awarded by:** {actor.mention} ({actor.display_name})\n"
                  f"**Amount:** +{cur(config_r, xp_to_give)}{mult_str}\n"
                  f"**Balance:** {cur(config_r, displayed_balance)}", C_SUCCESS)
    # Daily quest: the RECIPIENT gets credit for "Get a reaction bonus from a Meeple Owner"
    if config_r.get("daily_quest_enabled", 0):
        dq_date = db_today_key()
        dq_done = db_daily_quest_progress(payload.guild_id, target.id, dq_date, "dq_get_react")
        await process_daily_quest_completions(bot, payload.guild_id, target.id, dq_done, dq_date)

@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    if not payload.guild_id:
        return
    guild = bot.get_guild(payload.guild_id)
    if not guild:
        return
    actor = guild.get_member(payload.user_id)
    if not actor or actor.bot:
        return
    config = db_get_config(payload.guild_id)
    if not config:
        return
    configured = config.get("reaction_emoji", "✅")
    emoji_str = (f"<:{payload.emoji.name}:{payload.emoji.id}>"
                 if payload.emoji.is_custom_emoji() else str(payload.emoji))
    if emoji_str != configured or not is_xp_manager(actor, config):
        return
    existing = db_get_reaction_msg(payload.guild_id, payload.message_id)
    # Only revoke if it was actually awarded (not a pre-block / cancelled row)
    if not existing or existing.get("cancelled") or existing.get("amount", 0) == 0:
        return
    target_id = existing["target_uid"]
    amount    = existing["amount"]
    new_xp    = db_add_xp(payload.guild_id, target_id, -amount)
    # Mark cancelled instead of deleting — prevents re-give with ✅
    db_cancel_reaction_msg(payload.guild_id, payload.message_id)
    config_r2 = db_get_config(payload.guild_id)
    target_member = guild.get_member(target_id)
    if target_member:
        try:
            await target_member.send(
                f"❌ Your reaction reward was removed in **{guild.name}**.\n"
                f"Lost: **{cur(config_r2, amount)}** — make sure your share clearly shows "
                f"your comment and the video link. Good luck on the next one! 💪"
            )
        except Exception:
            pass
    await bot_log(bot, payload.guild_id, "↩️ Reaction Removed",
                  f"**Member:** <@{target_id}>\n"
                  f"**Removed by:** {actor.mention}\n"
                  f"**Amount:** -{cur(config_r2, amount)}\n"
                  f"**Balance:** {cur(config_r2, new_xp)}", C_ERROR)

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        await bot.process_commands(message)
        return
    config = db_get_config(message.guild.id)
    share_ch_id = config.get("share_channel_id")
    if share_ch_id and message.channel.id == share_ch_id:
        await _handle_share(message, config)
    # Daily quest: count messages in the configured chat channel
    dq_msgs_ch = config.get("daily_quest_messages_channel_id")
    if dq_msgs_ch and message.channel.id == dq_msgs_ch and config.get("daily_quest_enabled", 0):
        dq_date = db_today_key()
        dq_done = db_daily_quest_progress(message.guild.id, message.author.id, dq_date, "dq_messages")
        if dq_done:
            await process_daily_quest_completions(bot, message.guild.id, message.author.id, dq_done, dq_date)
    await bot.process_commands(message)

async def _handle_share(message: discord.Message, config: dict):
    """Validate a share-channel post.  Only valid link + screenshot posts survive;
    everything else is silently deleted and the member gets a private DM explaining what to do.
    """
    guild_id   = message.guild.id
    window_min = config.get("share_window_min") or 20
    c_name     = config.get("currency_name") or "Gems"

    # Meeple Owners can post freely — never delete or DM them.
    is_manager = isinstance(message.author, discord.Member) and is_xp_manager(message.author, config)

    async def _reject(dm_text: str):
        """DM the author and delete the message — skip silently for Meeple Owners."""
        if is_manager:
            return
        try:
            await message.author.send(dm_text)
        except Exception:
            pass  # DMs disabled — nothing we can do
        try:
            await message.delete()
        except Exception:
            pass

    video_id = extract_video_id(message.content)

    # Require at least one image attachment (screenshot)
    has_image = any(_is_image_attachment(att) for att in message.attachments)

    # ── Basic format checks ───────────────────────────────────────
    if not video_id and not has_image:
        await _reject(
            f"👋 Hey! Your message in **{message.guild.name}** was removed.\n\n"
            f"This channel is reserved for video shares. Please post:\n"
            f"• The **YouTube link** of the video\n"
            f"• A **screenshot** of your comment on that video\n\n"
            f"Both are required to earn {c_name}. Try again! 🎬"
        )
        return

    if not video_id:
        await _reject(
            f"👋 Hey! Your message in **{message.guild.name}** was removed.\n\n"
            f"You attached a screenshot but forgot to include the **YouTube link**.\n"
            f"Please post the link **and** the screenshot together to earn {c_name}. 🔗"
        )
        return

    if not has_image:
        await _reject(
            f"👋 Hey! Your message in **{message.guild.name}** was removed.\n\n"
            f"You shared the YouTube link but forgot to attach a **screenshot of your comment**.\n"
            f"Please post the link **and** the screenshot together to earn {c_name}. 📸"
        )
        return

    # ── Video / window checks (DM + delete on failure) ───────────
    current = db_get_current_video(guild_id)
    if not current:
        await _reject(
            f"👋 Hey! Your message in **{message.guild.name}** was removed.\n\n"
            f"There's no active video to share right now. Wait for the next announcement! ⏳"
        )
        return

    # Check share window
    try:
        detected_at = datetime.fromisoformat(current["detected_at"])
        deadline    = detected_at + timedelta(minutes=window_min)
        if datetime.utcnow() > deadline:
            deadline_ts = int(deadline.timestamp())
            await _reject(
                f"👋 Hey! Your message in **{message.guild.name}** was removed.\n\n"
                f"The share window closed <t:{deadline_ts}:R>. "
                f"You were too late this time — hang on for the next video! ⏰"
            )
            return
    except Exception:
        pass

    # Check video match
    if video_id != current["video_id"]:
        await _reject(
            f"👋 Hey! Your message in **{message.guild.name}** was removed.\n\n"
            f"The link you posted doesn't match the current video.\n"
            f"Use `/video` in the server to get the correct link. 🎯"
        )
        return

    # Already shared?
    if db_has_shared(guild_id, video_id, message.author.id):
        await _reject(
            f"👋 Hey! Your message in **{message.guild.name}** was removed.\n\n"
            f"You already shared this video and received your {c_name}. "
            f"Wait for the next one! ✅"
        )
        return

    # ── All checks passed — award automatically ──
    position = db_add_share(guild_id, video_id, message.author.id)
    db_increment_stat(guild_id, message.author.id, "total_shares")

    # Apply Double multiplier
    mult = db_has_double_xp(guild_id)

    # Streak bonus
    streak_info = db_get_streak(guild_id, message.author.id)
    prev_video_id = current.get("previous_video_id")
    if config.get("streak_enabled", 1):
        if prev_video_id and streak_info["last_video_id"] == prev_video_id:
            new_streak = streak_info["current_streak"] + 1
        else:
            new_streak = 1
    else:
        new_streak = 0

    streak_bonus = 0
    if config.get("streak_enabled", 1) and new_streak > 0:
        bonus_per = config.get("streak_xp_bonus", 2)
        cap       = config.get("streak_xp_cap", 30)
        streak_bonus = min(new_streak * bonus_per, cap)

    share_xp_base = config.get("share_xp", 100)

    total_xp = int((share_xp_base + streak_bonus) * mult)
    streak_before_val = streak_info["current_streak"]   # captured before update, for ❌ revert
    new_xp = db_add_xp(guild_id, message.author.id, total_xp)

    # Update streak
    if config.get("streak_enabled", 1):
        max_streak = db_update_streak(guild_id, message.author.id, new_streak, video_id)
        db_update_max_streak_stat(guild_id, message.author.id, new_streak)
        await update_streak_nickname(message.guild, message.author.id, new_streak)

    # Log the share reward so ❌ can fully revert it (XP + streak)
    db_log_share(guild_id, message.id, message.author.id, video_id,
                 total_xp, streak_before_val, new_streak)

    # Confirm to member
    parts = [f"✅ {message.author.mention} — **+{cur(config, total_xp)}**! Balance: **{cur(config, new_xp)}**"]
    if config.get("streak_enabled", 1) and new_streak > 0:
        parts.append(f"🔥 Streak: **{new_streak}**" + (f" (+{cur(config, streak_bonus)} bonus)" if streak_bonus else ""))
    if mult > 1:
        parts.append(f"⚡ Double {config.get('currency_name','Gems')} active! (×{mult})")
    if position <= 5:
        parts.append(f"🥇 You're #{position} to share this video!")
    try:
        await message.reply("\n".join(parts), delete_after=_ttl(config, "msg_ttl_share_reward"))
    except Exception:
        pass
    # Log the validated share
    current_v = db_get_current_video(guild_id)
    await bot_log(bot, guild_id, "🎬 Share Validated",
                  f"**Member:** {message.author.mention} ({message.author.display_name})\n"
                  f"**Video:** {current_v['video_title'] if current_v else '(unknown)'}\n"
                  f"**Position:** #{position}\n"
                  f"**Reward:** +{cur(config, total_xp)}"
                  + (f" (🔥 streak {new_streak})" if config.get("streak_enabled",1) and new_streak else "")
                  + (f" (×{mult} double)" if mult > 1 else "")
                  + f"\n**Balance:** {cur(config, new_xp)}", C_SUCCESS)
    # React to the validated share with the server's currency emoji
    try:
        react_emoji_str = config.get("currency_emoji") or "💎"
        if react_emoji_str.startswith("<") and react_emoji_str.endswith(">"):
            e_parts = react_emoji_str.strip("<>").split(":")
            animated   = e_parts[0] == "a"
            emoji_obj  = discord.PartialEmoji(animated=animated, name=e_parts[1], id=int(e_parts[2]))
        else:
            emoji_obj = react_emoji_str
        await message.add_reaction(emoji_obj)
    except Exception:
        pass

    # Update quests
    month_key = current_month_key()
    db_assign_monthly_quests(guild_id, message.author.id, month_key)
    newly_done = db_update_quest_progress(guild_id, message.author.id, "share_videos")
    # Streak quest
    if config.get("streak_enabled", 1):
        newly_done += db_update_quest_progress(guild_id, message.author.id, "video_streak",
                                               value=new_streak)
    # First 5 quest
    if position <= 5:
        newly_done += db_update_quest_progress(guild_id, message.author.id, "first_5")
    # #1 quest
    if position == 1:
        newly_done += db_update_quest_progress(guild_id, message.author.id, "top_1")
    await process_quest_completions(bot, guild_id, message.author.id, newly_done)
    # Daily quest progress
    if config.get("daily_quest_enabled", 0):
        date_key = db_today_key()
        dq_done: list = []
        dq_done += db_daily_quest_progress(guild_id, message.author.id, date_key, "dq_share")
        if position <= 10:
            dq_done += db_daily_quest_progress(guild_id, message.author.id, date_key, "dq_top10")
        if position <= 5:
            dq_done += db_daily_quest_progress(guild_id, message.author.id, date_key, "dq_first5")
        if position <= 3:
            dq_done += db_daily_quest_progress(guild_id, message.author.id, date_key, "dq_first3")
        if position == 1:
            dq_done += db_daily_quest_progress(guild_id, message.author.id, date_key, "dq_first1")
        await process_daily_quest_completions(bot, guild_id, message.author.id, dq_done, date_key)
    # Community goal contributions
    active_goals = db_get_community_goals(guild_id)
    for goal in active_goals:
        if goal["goal_type"] == "share_videos" and not goal["completed"]:
            updated = db_add_goal_contribution(guild_id, goal["id"], message.author.id)
            if updated.get("completed") and not goal["completed"]:
                # Already handled by check_community_goals background task
                pass
    # Achievements
    await check_achievements(bot, guild_id, message.author.id)

# ══════════════════════════════════════════════════════════════
#  SLASH COMMANDS
# ══════════════════════════════════════════════════════════════

async def _check_commands_channel(interaction: discord.Interaction) -> bool:
    """Returns True if the interaction is in the configured commands channel (or not configured).
    Always returns True when used from the admin commands channel."""
    config = db_get_config(interaction.guild_id)
    if interaction.channel_id == config.get("admin_commands_channel_id"):
        return True
    ch_id = config.get("commands_channel_id")
    if not ch_id:
        return True
    if interaction.channel_id != ch_id:
        await interaction.response.send_message(
            f"❌ Please use <#{ch_id}> for bot commands.", ephemeral=True)
        return False
    return True

async def _check_shop_channel(interaction: discord.Interaction) -> bool:
    """Returns True if the interaction is in the shop channel (falls back to commands channel).
    Always returns True when used from the admin commands channel."""
    config = db_get_config(interaction.guild_id)
    if interaction.channel_id == config.get("admin_commands_channel_id"):
        return True
    ch_id = config.get("shop_channel_id") or config.get("commands_channel_id")
    if not ch_id:
        return True
    if interaction.channel_id != ch_id:
        await interaction.response.send_message(
            f"❌ Please use <#{ch_id}> for shop commands.", ephemeral=True)
        return False
    return True

async def _check_quests_channel(interaction: discord.Interaction) -> bool:
    """Returns True if the interaction is in the quests channel (falls back to commands channel).
    Always returns True when used from the admin commands channel."""
    config = db_get_config(interaction.guild_id)
    if interaction.channel_id == config.get("admin_commands_channel_id"):
        return True
    ch_id = config.get("quests_channel_id") or config.get("commands_channel_id")
    if not ch_id:
        return True
    if interaction.channel_id != ch_id:
        await interaction.response.send_message(
            f"❌ Please use <#{ch_id}> for quest commands.", ephemeral=True)
        return False
    return True

# ══════════════════════════════════════════════════════════════
#  PING ROLE OPT-IN
# ══════════════════════════════════════════════════════════════

class PingRoleOptInView(discord.ui.View):
    """Ephemeral prompt that lets a user self-assign the notification ping role."""
    def __init__(self, role: discord.Role, guild_id: int, cooldown_minutes: int):
        super().__init__(timeout=60)
        self.role             = role
        self.guild_id         = guild_id
        self.cooldown_minutes = cooldown_minutes

    @discord.ui.button(label="🔔 Enable notifications", style=discord.ButtonStyle.primary)
    async def enable_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member):
            return
        try:
            await interaction.user.add_roles(self.role, reason="Opted in via bot prompt")
            for child in self.children:
                child.disabled = True
            await interaction.response.edit_message(
                content=f"✅ You now have the **{self.role.name}** role — you'll be pinged for every new video!",
                view=self,
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ I don't have permission to assign that role.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Error: {e}", ephemeral=True)

    @discord.ui.button(label="🔕 Later", style=discord.ButtonStyle.grey)
    async def later_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member):
            return
        db_snooze_notification(self.guild_id, interaction.user.id, self.cooldown_minutes)
        for child in self.children:
            child.disabled = True
        mins = self.cooldown_minutes
        if mins <= 0:
            label = "right away next time"
        elif mins < 60:
            label = f"{mins} minute{'s' if mins != 1 else ''}"
        elif mins < 1440:
            h = mins // 60
            label = f"{h} hour{'s' if h != 1 else ''}"
        else:
            d = mins // 1440
            label = f"{d} day{'s' if d != 1 else ''}"
        await interaction.response.edit_message(
            content=f"👍 Got it — I won't ask again for **{label}**.",
            view=self,
        )

    async def on_timeout(self):
        pass

async def _prompt_ping_role(interaction: discord.Interaction) -> None:
    """After any user command, nudge members who don't have the ping role yet.
    Skipped if the user snoozed the prompt or if it was already shown recently."""
    if not isinstance(interaction.user, discord.Member) or not interaction.guild:
        return
    config  = db_get_config(interaction.guild_id)
    role_id = config.get("share_ping_role_id")
    if not role_id:
        return
    role = interaction.guild.get_role(role_id)
    if not role or role in interaction.user.roles:
        return
    if db_is_notification_snoozed(interaction.guild_id, interaction.user.id):
        return
    # Resolve the configured cooldown (minutes). 0 = always show (minimum 1-minute debounce).
    cooldown_minutes = config.get("notify_prompt_cooldown_minutes")
    if cooldown_minutes is None:
        legacy_days = config.get("notify_prompt_cooldown_days")
        cooldown_minutes = (3 if legacy_days is None else legacy_days) * 24 * 60
    cooldown_minutes = int(cooldown_minutes)

    # Set a short debounce snooze so the prompt doesn't re-appear on every consecutive
    # command within the same session. "Later" click extends to the full configured cooldown.
    # Use 1 minute for cooldown=0 ("always show"), otherwise use the configured value.
    debounce = max(1, cooldown_minutes)
    db_snooze_notification(interaction.guild_id, interaction.user.id, debounce)

    try:
        await interaction.followup.send(
            f"🔔 **Want to be notified when a new video drops?**\n"
            f"Get the **{role.name}** role to receive pings and maximize your rewards!",
            view=PingRoleOptInView(role, interaction.guild_id, cooldown_minutes),
            ephemeral=True,
        )
    except discord.NotFound:
        # Interaction token expired — undo the snooze so it can try again next command.
        db_snooze_notification(interaction.guild_id, interaction.user.id, 0)
    except discord.HTTPException as _e:
        print(f"[NotifyPrompt] followup.send failed (code {_e.code}): {_e}")
        # Undo debounce so the next command can retry.
        db_snooze_notification(interaction.guild_id, interaction.user.id, 0)

# ── /config ───────────────────────────────────────────────────

@bot.tree.command(name="config", description="⚙️ Open the bot configuration panel")
async def cmd_config(interaction: discord.Interaction):
    if not interaction.guild:
        await interaction.response.send_message("❌ Server only.", ephemeral=True)
        return
    if not isinstance(interaction.user, discord.Member):
        return
    db_ensure_config(interaction.guild_id)
    config = db_get_config(interaction.guild_id)
    if not is_xp_manager(interaction.user, config):
        await interaction.response.send_message("❌ You need the **Meeple Owner** role.", ephemeral=True)
        return
    view  = ConfigMainMenu(interaction.guild, interaction.user.id)
    embed = config_overview_embed(interaction.guild, config)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

# ── /admin ────────────────────────────────────────────────────

@bot.tree.command(name="admin", description="🛠️ Open the admin panel")
async def cmd_admin(interaction: discord.Interaction):
    if not interaction.guild:
        await interaction.response.send_message("❌ Server only.", ephemeral=True)
        return
    if not isinstance(interaction.user, discord.Member):
        return
    config = db_get_config(interaction.guild_id)
    if not is_xp_manager(interaction.user, config):
        await interaction.response.send_message("❌ You need the **Meeple Owner** role.", ephemeral=True)
        return
    view = AdminMainMenu(interaction.guild, interaction.user.id)
    await interaction.response.send_message(embed=admin_main_embed(interaction.guild), view=view, ephemeral=True)

# ── /gems ─────────────────────────────────────────────────────

@bot.tree.command(name="gems", description="💰 Check your balance and rank")
@app_commands.describe(member="Check another member's balance (Meeple Owners only)")
async def cmd_gems(interaction: discord.Interaction, member: Optional[discord.Member] = None):
    if not interaction.guild:
        await interaction.response.send_message("❌ Server only.", ephemeral=True)
        return
    if not await _check_commands_channel(interaction):
        return
    config = db_get_config(interaction.guild_id)
    if member and member.id != interaction.user.id:
        if not isinstance(interaction.user, discord.Member) or not is_xp_manager(interaction.user, config):
            await interaction.response.send_message("❌ Only Meeple Owners can view others' balance.", ephemeral=True)
            return
        target = member
    else:
        target = interaction.user

    xp   = db_get_xp(interaction.guild_id, target.id)
    top  = db_top_xp(interaction.guild_id, limit=1000)
    rank = next((i+1 for i, (uid, _) in enumerate(top) if uid == target.id), None)
    streak = db_get_streak(interaction.guild_id, target.id)
    c_name = config.get("currency_name") or "Gems"

    e = E(color=C_GOLD)
    e.set_author(name=str(target), icon_url=target.display_avatar.url if target.display_avatar else None)
    e.add_field(name=f"{config.get('currency_emoji') or '💎'} {c_name}", value=f"**{cur(config, xp)}**", inline=True)
    if rank:
        e.add_field(name="🏆 Rank", value=f"**#{rank}**",                             inline=True)
    if config.get("streak_enabled", 1):
        e.add_field(name="🔥 Streak",value=f"**{streak['current_streak']}**"
                    + (f" (max: {streak['max_streak']})" if streak["max_streak"] else ""), inline=True)
    await interaction.response.send_message(embed=e, delete_after=_ttl(config, "msg_ttl_gems"))
    # Daily quest: "Check your balance with /gems" (only for own balance check)
    if target.id == interaction.user.id:
        config2 = db_get_config(interaction.guild_id)
        if config2.get("daily_quest_enabled", 0):
            dq_date = db_today_key()
            dq_done = db_daily_quest_progress(interaction.guild_id, interaction.user.id, dq_date, "dq_checkin")
            await process_daily_quest_completions(bot, interaction.guild_id, interaction.user.id, dq_done, dq_date)
    await _prompt_ping_role(interaction)

# ── /leaderboard ─────────────────────────────────────────────

@bot.tree.command(name="leaderboard", description="🏆 Server leaderboard")
@app_commands.describe(limit="How many members to show (max 25, default 10)")
async def cmd_leaderboard(interaction: discord.Interaction, limit: int = 10):
    if not interaction.guild:
        await interaction.response.send_message("❌ Server only.", ephemeral=True)
        return
    if not await _check_commands_channel(interaction):
        return
    limit = max(1, min(25, limit))
    await interaction.response.defer()
    top = db_top_xp(interaction.guild_id, limit=limit)
    if not top:
        await interaction.followup.send("❌ Nobody has earned any rewards yet!")
        return
    config = db_get_config(interaction.guild_id)
    medals = ["🥇", "🥈", "🥉"]
    lines  = []
    for i, (uid, xp) in enumerate(top):
        prefix = medals[i] if i < 3 else f"`{i+1}.`"
        try:
            user = await bot.fetch_user(uid)
            name = user.display_name
        except Exception:
            name = f"Unknown ({uid})"
        streak = db_get_streak(interaction.guild_id, uid)
        streak_str = f" 🔥{streak['current_streak']}" if streak["current_streak"] > 0 else ""
        lines.append(f"{prefix} **{name}**{streak_str} — {cur(config, xp)}")
    e = E(f"🏆 Leaderboard — Top {limit}", "\n".join(lines), C_GOLD)
    await interaction.followup.send(embed=e, delete_after=_ttl(config, "msg_ttl_leaderboard"))
    await _prompt_ping_role(interaction)

# ── /streak ───────────────────────────────────────────────────

@bot.tree.command(name="streak", description="🔥 View your current streak and personal best")
async def cmd_streak(interaction: discord.Interaction):
    if not interaction.guild:
        await interaction.response.send_message("❌ Server only.", ephemeral=True)
        return
    if not await _check_commands_channel(interaction):
        return
    await interaction.response.defer(ephemeral=True)
    config  = db_get_config(interaction.guild_id)
    streak  = db_get_streak(interaction.guild_id, interaction.user.id)
    stats   = db_get_stats(interaction.guild_id, interaction.user.id)
    cur_s   = streak["current_streak"]
    max_s   = max(streak.get("max_streak", 0), stats.get("max_streak_ever", 0))
    e = E("🔥 Your Streak", color=C_ACHIEVE)
    e.add_field(name="Current Streak", value=f"🔥 **{cur_s}**", inline=True)
    e.add_field(name="Personal Best",  value=f"⭐ **{max_s}**", inline=True)
    if cur_s > 0 and streak.get("last_video_id"):
        e.set_footer(text="Keep sharing every video to grow your streak!")
    elif cur_s == 0:
        e.set_footer(text="Share the next video to start your streak!")
    await interaction.followup.send(embed=e, ephemeral=True)

# ── /topstreak ────────────────────────────────────────────────

@bot.tree.command(name="topstreak", description="⭐ Top streak leaderboard")
@app_commands.describe(limit="How many members to show (max 25, default 10)")
async def cmd_topstreak(interaction: discord.Interaction, limit: int = 10):
    if not interaction.guild:
        await interaction.response.send_message("❌ Server only.", ephemeral=True)
        return
    if not await _check_commands_channel(interaction):
        return
    limit = max(1, min(25, limit))
    await interaction.response.defer()
    conn = get_db()
    rows = conn.execute(
        "SELECT user_id, current_streak, max_streak FROM streaks "
        "WHERE guild_id=? AND max_streak > 0 "
        "ORDER BY max_streak DESC, current_streak DESC LIMIT ?",
        (interaction.guild_id, limit)
    ).fetchall()
    conn.close()
    if not rows:
        await interaction.followup.send("❌ No streak records yet — share a video to start!")
        return
    medals = ["🥇", "🥈", "🥉"]
    lines  = []
    for i, row in enumerate(rows):
        prefix = medals[i] if i < 3 else f"`{i+1}.`"
        try:
            user = await bot.fetch_user(row["user_id"])
            name = user.display_name
        except Exception:
            name = f"Unknown ({row['user_id']})"
        cur_s = row["current_streak"]
        max_s = row["max_streak"]
        live = f" *(🔥 {cur_s} now)*" if cur_s > 0 else ""
        lines.append(f"{prefix} **{name}** — ⭐ best **{max_s}**{live}")
    e = E(f"⭐ Top Streak — Best of All Time", "\n".join(lines), C_GOLD)
    await interaction.followup.send(embed=e)
    await _prompt_ping_role(interaction)

# ── /shop ─────────────────────────────────────────────────────

@bot.tree.command(name="shop", description="🛒 Browse and buy items in the shop")
async def cmd_shop(interaction: discord.Interaction):
    if not interaction.guild:
        await interaction.response.send_message("❌ Server only.", ephemeral=True)
        return
    if not await _check_shop_channel(interaction):
        return
    if not isinstance(interaction.user, discord.Member):
        return
    config = db_get_config(interaction.guild_id)
    view = ShopView(interaction.guild, interaction.user)
    await interaction.response.send_message(embeds=view.embeds(), view=view,
                                            delete_after=_ttl(config, "msg_ttl_shop"))
    # Store message ref so on_timeout can disable the buttons
    try:
        view._msg = await interaction.original_response()
    except Exception:
        pass
    await _prompt_ping_role(interaction)

# ── /inventory ────────────────────────────────────────────────

@bot.tree.command(name="inventory", description="🎒 View your purchased items")
@app_commands.describe(member="View another member's inventory (Meeple Owners only)")
async def cmd_inventory(interaction: discord.Interaction, member: Optional[discord.Member] = None):
    if not interaction.guild:
        await interaction.response.send_message("❌ Server only.", ephemeral=True)
        return
    if not await _check_shop_channel(interaction):
        return
    config = db_get_config(interaction.guild_id)
    if member and member.id != interaction.user.id:
        if not isinstance(interaction.user, discord.Member) or not is_xp_manager(interaction.user, config):
            await interaction.response.send_message("❌ Only Meeple Owners can view others' inventories.", ephemeral=True)
            return
        target = member
    else:
        target = interaction.user

    items = db_get_inventory(interaction.guild_id, target.id)
    e = E(f"🎒 Inventory — {target.display_name}", color=C_INFO)
    if not items:
        e.description = "Your inventory is empty. Buy items from `/shop`!"
    else:
        for item in items:
            if item["is_expired"]:
                name = f"~~{item['item_name']}~~ *(expired)*"
            elif item.get("expires_at"):
                try:
                    exp = datetime.fromisoformat(item["expires_at"])
                    delta = exp - datetime.now()
                    total_seconds = int(delta.total_seconds())
                    if total_seconds <= 0:
                        name = f"~~{item['item_name']}~~ *(expired)*"
                    elif total_seconds < 3600:
                        mins_left = max(1, total_seconds // 60)
                        name = f"{item['item_name']} *(⚠️ {mins_left}min remaining!)*"
                    elif total_seconds < 86400:
                        hours_left = total_seconds // 3600
                        name = f"{item['item_name']} *(⏳ {hours_left}h remaining)*"
                    else:
                        days_left = delta.days
                        name = f"{item['item_name']} *(⏳ {days_left} day{'s' if days_left != 1 else ''} remaining)*"
                except Exception:
                    name = item["item_name"]
            else:
                name = item["item_name"]
            val = f"Purchased: {item.get('purchased_at', '?')[:10]}"
            if item.get("item_text"):
                val += f"\nInfo: {item['item_text'][:80]}"
            e.add_field(name=name, value=val, inline=True)
    await interaction.response.send_message(embed=e)
    await _prompt_ping_role(interaction)

# ── /video ────────────────────────────────────────────────────

@bot.tree.command(name="video", description="🎬 See the current video to share for rewards")
async def cmd_video(interaction: discord.Interaction):
    if not interaction.guild:
        await interaction.response.send_message("❌ Server only.", ephemeral=True)
        return
    if not await _check_commands_channel(interaction):
        return
    current = db_get_current_video(interaction.guild_id)
    if not current:
        await interaction.response.send_message("⚠️ No active video right now.", ephemeral=True)
        return
    config = db_get_config(interaction.guild_id)
    already_shared = db_has_shared(interaction.guild_id, current["video_id"], interaction.user.id)
    e = E(
        "🎬 Current Video",
        f"**{current['video_title']}**\n\n"
        f"📲 [Short]({make_shorts_url(current['video_id'])})  •  🖥️ [Watch]({make_watch_url(current['video_id'])})",
        color=C_GOLD
    )
    if already_shared:
        e.add_field(name="✅ Already shared", value="You shared this one — wait for the next!", inline=False)
    else:
        share_ch = config.get("share_channel_id")
        e.add_field(
            name=f"🎁 How to earn {cur(config)}",
            value=f"Share the link + screenshot in <#{share_ch}>" if share_ch else "Set a share channel with `/config`",
            inline=False
        )
    if config.get("streak_enabled", 1):
        streak = db_get_streak(interaction.guild_id, interaction.user.id)
        e.add_field(name="🔥 Your streak", value=f"**{streak['current_streak']}**", inline=True)
    await interaction.response.send_message(embed=e)
    await _prompt_ping_role(interaction)

# ── /quests ───────────────────────────────────────────────────

@bot.tree.command(name="quests", description="📅 View your monthly quests")
async def cmd_quests(interaction: discord.Interaction):
    if not interaction.guild:
        await interaction.response.send_message("❌ Server only.", ephemeral=True)
        return
    if not await _check_quests_channel(interaction):
        return
    guild_id  = interaction.guild_id
    user_id   = interaction.user.id
    month_key = current_month_key()
    db_assign_monthly_quests(guild_id, user_id, month_key)
    quests = db_get_user_quests(guild_id, user_id, month_key)
    config = db_get_config(guild_id)
    xp_map = {
        "stone": config.get("quest_xp_stone", 50),
        "bronze": config.get("quest_xp_bronze", 100),
        "silver": config.get("quest_xp_silver", 200),
        "gold": config.get("quest_xp_gold", 400),
        "diamond": config.get("quest_xp_diamond", 750),
    }
    e = E(f"📅 Monthly Quests — {month_key}", color=C_QUEST)
    e.set_author(name=str(interaction.user),
                 icon_url=interaction.user.display_avatar.url if interaction.user.display_avatar else None)
    for rarity in RARITIES:
        quest = next((q for q in quests if q["rarity"] == rarity), None)
        if not quest:
            e.add_field(name=f"{RARITY_EMOJI[rarity]} {rarity.capitalize()}", value="`Not assigned yet`", inline=False)
            continue
        progress_pct = min(quest["progress"] / quest["quest_target"], 1.0) if quest["quest_target"] else 1.0
        bar_filled = int(progress_pct * 10)
        bar = "█" * bar_filled + "░" * (10 - bar_filled)
        status = "✅ **COMPLETE**" if quest["completed"] else f"`{bar}` {quest['progress']}/{quest['quest_target']}"
        reward_str = f"**{cur(config, xp_map.get(rarity, 50))}**" + (" *(claimed)*" if quest.get("xp_awarded") else "")
        e.add_field(
            name=f"{RARITY_EMOJI[rarity]} {rarity.capitalize()} — {quest['quest_name']}",
            value=f"{status}\nReward: {reward_str}",
            inline=False
        )
    # Boost quest
    if config.get("boost_quest_enabled", 1):
        e.add_field(
            name="🚀 Boost Quest (Repeatable)",
            value=f"Boost the server → **+{cur(config, config.get('boost_quest_xp', 100))}** per boost\n♾️ Unlimited completions",
            inline=False
        )
    # ── Daily quests section ──────────────────────────────────────
    if config.get("daily_quest_enabled", 0):
        date_key  = db_today_key()
        dq_xp     = config.get("daily_quest_xp", 50)
        daily_qs  = db_assign_daily_quests(guild_id, user_id, date_key, count=3)
        e.add_field(name="─" * 32, value="", inline=False)
        e.add_field(
            name=f"📋 Daily Quests — {date_key}",
            value=f"Complete these today to earn **{cur(config, dq_xp)}** each.",
            inline=False
        )
        for dq in daily_qs:
            tgt = dq["quest_target"] or 1
            prog_pct  = min(dq["progress"] / tgt, 1.0)
            bar_filled = int(prog_pct * 10)
            bar = "█" * bar_filled + "░" * (10 - bar_filled)
            status    = "✅ **COMPLETE**" if dq["completed"] else f"`{bar}` {dq['progress']}/{tgt}"
            reward_str = f"**{cur(config, dq_xp)}**" + (" *(claimed)*" if dq.get("xp_awarded") else "")
            e.add_field(
                name=f"• {dq['quest_name']}",
                value=f"{status}\nReward: {reward_str}",
                inline=False
            )
        # Send the embed first so the user sees it before any follow-up completion announce
        await interaction.response.send_message(embed=e)
    else:
        await interaction.response.send_message(embed=e)
    await _prompt_ping_role(interaction)

# ── /achievements ─────────────────────────────────────────────

@bot.tree.command(name="achievements", description="🏆 View your achievements")
@app_commands.describe(member="View another member's achievements")
async def cmd_achievements(interaction: discord.Interaction, member: Optional[discord.Member] = None):
    if not interaction.guild:
        await interaction.response.send_message("❌ Server only.", ephemeral=True)
        return
    if not await _check_commands_channel(interaction):
        return
    guild_id = interaction.guild_id
    target = member or interaction.user
    db_ensure_achievement_config(guild_id)
    stats = db_get_stats(guild_id, target.id)
    conn = get_db()
    unlocked_rows = conn.execute(
        "SELECT achievement_key, tier FROM achievements WHERE guild_id=? AND user_id=?",
        (guild_id, target.id)
    ).fetchall()
    conn.close()
    unlocked = {(r["achievement_key"], r["tier"]) for r in unlocked_rows}
    e = E(f"🏆 Achievements — {target.display_name}", color=C_ACHIEVE)
    e.set_author(name=str(target), icon_url=target.display_avatar.url if target.display_avatar else None)
    tier_names = ["I", "II", "III", "IV", "V"]
    for ach_def in ACHIEVEMENT_DEFS:
        tiers = db_get_achievement_config(guild_id, ach_def["key"])
        if not tiers:
            tiers = [{"tier": i, "threshold": t, "role_id": None, "enabled": 1}
                     for i, t in enumerate(ach_def["tiers"])]
        stat_val = stats.get(ach_def["category"], 0)
        tier_strs = []
        for t in tiers:
            if not t.get("enabled", 1):
                continue
            tier_idx = t["tier"]
            tier_label = tier_names[tier_idx] if tier_idx < len(tier_names) else str(tier_idx)
            unlocked_icon = "✅" if (ach_def["key"], tier_idx) in unlocked else "🔒"
            tier_strs.append(f"{unlocked_icon} {tier_label}: {t['threshold']}")
        e.add_field(
            name=f"{ach_def['name']}  (current: {stat_val})",
            value="  ".join(tier_strs) if tier_strs else "`No tiers configured`",
            inline=False
        )
    await interaction.response.send_message(embed=e)
    await _prompt_ping_role(interaction)

# ── /tutorial ─────────────────────────────────────────────────

@bot.tree.command(name="tutorial", description="📖 Learn how to earn and use rewards")
async def cmd_tutorial(interaction: discord.Interaction):
    if not interaction.guild:
        await interaction.response.send_message("❌ Server only.", ephemeral=True)
        return
    if not await _check_commands_channel(interaction):
        return
    view = MemberTutorialView(interaction.guild, interaction.user.id)
    await interaction.response.send_message(embed=view.build_embed(), view=view)

async def _give_amount_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[int]]:
    """Show balance, daily limit, min balance, and already-sent amount while typing /give amount."""
    if not interaction.guild_id:
        return []
    try:
        config       = db_get_config(interaction.guild_id)
        give_max     = config.get("give_max_daily", 100)
        min_bal      = config.get("give_min_balance", 1000)
        already_sent = db_gifts_sent_today(interaction.guild_id, interaction.user.id)
        remaining    = max(0, give_max - already_sent)
        bal          = db_get_xp(interaction.guild_id, interaction.user.id)
        c_name       = config.get("currency_name") or "Gems"

        choices = []
        if bal < min_bal:
            choices.append(app_commands.Choice(
                name=f"❌ Need {min_bal} {c_name} min to give (you have {bal})",
                value=1))
            return choices
        if remaining == 0:
            choices.append(app_commands.Choice(
                name=f"Daily limit reached — already sent {already_sent}/{give_max} {c_name} today",
                value=1))
        else:
            choices.append(app_commands.Choice(
                name=f"Max today: {remaining} {c_name}  |  balance: {bal}  |  sent: {already_sent}/{give_max}",
                value=remaining))
            for preset in [10, 25, 50, 100]:
                if preset < remaining:
                    choices.append(app_commands.Choice(
                        name=f"{preset} {c_name}", value=preset))
        return choices[:5]
    except Exception:
        return []

@bot.tree.command(name="give", description="🎁 Gift gems to another member")
@app_commands.describe(
    member="The member to gift gems to",
    amount="How many gems to give — type to see your balance, daily limit, and how much you've already sent"
)
@app_commands.autocomplete(amount=_give_amount_autocomplete)
async def cmd_give(interaction: discord.Interaction, member: discord.Member, amount: int):
    if not interaction.guild:
        await interaction.response.send_message("❌ Server only.", ephemeral=True)
        return
    config = db_get_config(interaction.guild_id)
    if not config.get("give_enabled", 0):
        await interaction.response.send_message(
            "❌ The gift gems feature is not enabled on this server.", ephemeral=True)
        return
    if not await _check_commands_channel(interaction):
        return
    sender = interaction.user
    if sender.id == member.id:
        await interaction.response.send_message("❌ You can't gift gems to yourself.", ephemeral=True)
        return
    if member.bot:
        await interaction.response.send_message("❌ Bots can't receive gems.", ephemeral=True)
        return
    if amount <= 0:
        await interaction.response.send_message("❌ Amount must be positive.", ephemeral=True)
        return

    give_max    = config.get("give_max_daily", 100)
    recv_limit  = config.get("give_receive_cooldown_h", 1)  # stored as "max per day"
    min_balance = config.get("give_min_balance", 1000)      # configurable via /config → 🎁 Gift Gems

    sender_bal = db_get_xp(interaction.guild_id, sender.id)
    if sender_bal < min_balance:
        await interaction.response.send_message(
            f"❌ You need at least **{cur(config, min_balance)}** to give gems "
            f"(anti-alt protection). You have **{cur(config, sender_bal)}**.",
            ephemeral=True
        )
        return

    already_sent = db_gifts_sent_today(interaction.guild_id, sender.id)
    if already_sent + amount > give_max:
        remaining_today = max(0, give_max - already_sent)
        await interaction.response.send_message(
            f"❌ Daily gift limit: **{cur(config, give_max)}**.\n"
            f"You've already sent **{cur(config, already_sent)}** today — "
            f"you can still give **{cur(config, remaining_today)}** more.",
            ephemeral=True
        )
        return

    recv_today = db_gifts_received_today(interaction.guild_id, member.id)
    if recv_today >= recv_limit:
        await interaction.response.send_message(
            f"❌ **{member.display_name}** has already received their maximum of "
            f"**{recv_limit}** gift(s) today. Try again tomorrow!",
            ephemeral=True
        )
        return

    if sender_bal < amount:
        await interaction.response.send_message(
            f"❌ Not enough {cur(config)}. You have **{cur(config, sender_bal)}** "
            f"but want to give **{cur(config, amount)}**.",
            ephemeral=True
        )
        return

    # Confirm
    view = ConfirmView(sender.id)
    await interaction.response.send_message(
        f"🎁 Gift **{cur(config, amount)}** to {member.mention}?\n"
        f"Your balance after: **{cur(config, sender_bal - amount)}**",
        view=view, ephemeral=True
    )
    await view.wait()
    if not view.value:
        await interaction.followup.send("❌ Gift cancelled.", ephemeral=True)
        return

    # Execute
    db_add_xp(interaction.guild_id, sender.id, -amount)
    new_recv_bal = db_add_xp(interaction.guild_id, member.id, amount)
    db_record_gift(interaction.guild_id, sender.id, member.id, amount)

    await interaction.followup.send(
        f"✅ You gifted **{cur(config, amount)}** to {member.mention}!", ephemeral=True
    )

    # DM recipient
    try:
        await member.send(
            f"🎁 **{sender.display_name}** gifted you **{cur(config, amount)}** in **{interaction.guild.name}**!\n"
            f"Your new balance: **{cur(config, new_recv_bal)}**"
        )
    except Exception:
        pass

    await bot_log(bot, interaction.guild_id, "🎁 Gems Gift",
                  f"**From:** {sender.mention} ({sender.display_name})\n"
                  f"**To:** {member.mention} ({member.display_name})\n"
                  f"**Amount:** {cur(config, amount)}\n"
                  f"**Recipient balance:** {cur(config, new_recv_bal)}", C_SUCCESS)


# ── Error handler ─────────────────────────────────────────────

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    print(f"[Slash error] {error}")
    msg = "❌ Something went wrong. Please try again."
    try:
        if not interaction.response.is_done():
            await interaction.response.send_message(msg, ephemeral=True)
        else:
            await interaction.followup.send(msg, ephemeral=True)
    except Exception:
        pass

# ══════════════════════════════════════════════════════════════
#  AIOHTTP WEB SERVER — WebSub callback + health check
#  Runs in the same event loop as the bot — no threads needed.
# ══════════════════════════════════════════════════════════════

async def _web_home(request: aiohttp_web.Request) -> aiohttp_web.Response:
    return aiohttp_web.Response(text="Bot is alive!")

async def _web_health(request: aiohttp_web.Request) -> aiohttp_web.Response:
    return aiohttp_web.json_response({
        "status": "ok",
        "bot": str(bot.user) if bot.user else "Not connected",
    })

async def _web_youtube_get(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """YouTube PubSubHubbub subscription verification (hub.challenge echo)."""
    challenge = request.rel_url.query.get("hub.challenge", "")
    if not challenge:
        return aiohttp_web.Response(status=400, text="Missing hub.challenge")
    mode    = request.rel_url.query.get("hub.mode", "")
    topic   = request.rel_url.query.get("hub.topic", "")
    print(f"[WebSub] ✅ Verified — mode={mode} topic={topic}")
    return aiohttp_web.Response(text=challenge, content_type="text/plain")

async def _web_youtube_post(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """YouTube PubSubHubbub push notification — fan out to matching guilds."""
    body = await request.read()
    try:
        root = ET.fromstring(body)
        ns   = {
            'atom': 'http://www.w3.org/2005/Atom',
            'yt':   'http://www.youtube.com/xml/schemas/2015',
        }
        # Channel ID may appear at feed level or inside the entry
        ch_el = root.find('yt:channelId', ns)
        if ch_el is None:
            entry = root.find('atom:entry', ns)
            if entry is not None:
                ch_el = entry.find('yt:channelId', ns)
        if ch_el is None:
            return aiohttp_web.Response(status=200, text="ok")

        notif_channel_id = ch_el.text
        conn  = get_db()
        guilds = conn.execute(
            "SELECT guild_id FROM guild_config WHERE youtube_channel_id = ?",
            (notif_channel_id,)
        ).fetchall()
        conn.close()
        for row in guilds:
            asyncio.create_task(handle_websub_notification(body, row["guild_id"]))
    except Exception as e:
        print(f"[WebSub] POST error: {e}")
    return aiohttp_web.Response(status=200, text="ok")

async def start_web_server() -> None:
    """Start the aiohttp server inside the running event loop."""
    app = aiohttp_web.Application()
    app.router.add_get('/',        _web_home)
    app.router.add_get('/health',  _web_health)
    app.router.add_get('/youtube', _web_youtube_get)
    app.router.add_post('/youtube', _web_youtube_post)
    runner = aiohttp_web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 5000))
    site = aiohttp_web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"[WebServer] ✅ Listening on port {port}")

# ══════════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════════

async def _main():
    """Async entry point: web server + bot share the same event loop."""
    init_db()
    await start_web_server()
    token = os.environ.get("TOKEN")
    if not token:
        print("❌ Missing TOKEN environment variable!")
        raise SystemExit(1)
    async with bot:
        await bot.start(token)

if __name__ == "__main__":
    asyncio.run(_main())
