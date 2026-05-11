from __future__ import annotations

import asyncio
import contextlib
import datetime
import io
import logging
import math
import os
import random
import re
import string
import uuid
from typing import Optional
from zoneinfo import ZoneInfo

import asyncpg
import discord
from discord import app_commands
from discord.ext import commands, tasks

try:
    import chat_exporter
    HAS_CHAT_EXPORTER = True
except ImportError:
    HAS_CHAT_EXPORTER = False


# ══════════════════════════════════════════════════════════════════
# LOGGING
# ══════════════════════════════════════════════════════════════════
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler("combined_bot.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("CombinedBot")


# ══════════════════════════════════════════════════════════════════
# UTILITY — datetime
# ══════════════════════════════════════════════════════════════════
_UTC = ZoneInfo("UTC")


def utcnow() -> datetime.datetime:
    return datetime.datetime.now(_UTC)


def utcnow_naive() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


_TZ_OFFSET_RE = re.compile(r"[+-]\d{2}:?\d{2}$")


def parse_naive(value: str | datetime.datetime) -> datetime.datetime:
    if isinstance(value, datetime.datetime):
        return value.replace(tzinfo=None) if value.tzinfo is not None else value
    raw = value.strip().replace("T", " ")
    raw = raw.replace("Z", "").replace("+00:00", "").replace("+0000", "")
    raw = _TZ_OFFSET_RE.sub("", raw)
    dt = datetime.datetime.fromisoformat(raw)
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt


# ══════════════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════════════
class Config:

    TOKEN    = os.environ.get("BOT_TOKEN", "")
    GUILD_ID = int(os.environ.get("GUILD_ID", "0"))

    DATABASE_URL = os.environ.get("DATABASE_URL", "")

    LOG_CHANNEL_ID         = 1493559866713964706
    CATEGORY_GENERAL       = 1501154415367950366
    CATEGORY_MISSION_ID    = 1499276810159128627
    PARTNERSHIP_CHANNEL_ID = 1390021687495622686

    STAFF_TICKET_ROLE_ID      = 1499048776588071095
    STAFF_CASINO_ROLE_ID      = 1499051397591601163
    STAFF_GIVEAWAY_ROLE_ID    = 1499051397591601163
    STAFF_TEAM_ROLE_ID        = 1499050738007932999
    STAFF_MISSION_ROLE_ID     = 1499051397591601163
    STAFF_PARTNERSHIP_ROLE_ID = 1499050738007932999

    TEAM_ROLE_ID    = 1494779994944180224
    CASINO_ROLE_ID  = 1390082984215973918
    ROLE_PARTNER_ID = 1499840483852161144
    ROLE_ADMIN_ID   = 1499052316119273592
    ROLE_TRIAL_ID   = 1499048776588071095

    STARTING_BALANCE    = 250
    CASINO_COOLDOWN     = 3
    DAILY_BONUS_MIN     = 50
    DAILY_BONUS_MAX     = 200
    COINFLIP_WIN_CHANCE = 40

    MISSION_CHANNEL_ID          = 1503400533103476866 # ID del canale dove annunciare le missioni
    MISSION_MESSAGE_COUNT_TARGET = 50
    MISSION_MESSAGE_COUNT_REWARD = 100

    SHOP_MULTIPLIERS = [
        {"name": "x1.5 per 5 giocate", "multiplier": 1.5, "uses": 5, "cost": 500},
        {"name": "x2.0 per 3 giocate", "multiplier": 2.0, "uses": 3, "cost": 1000},
    ]
    SHOP_ROLES = [
        {"name": "Ruolo VIP Bronzo", "role_id": 1503399636713603244, "cost": 2000},
        {"name": "Ruolo VIP Argento", "role_id": 1503400072212385973, "cost": 5000},
    ]

    COLOR_WIN    = 0x2ECC71
    COLOR_LOSE   = 0xE74C3C
    COLOR_INFO   = 0x3498DB
    COLOR_GOLD   = 0xF1C40F
    COLOR_PURPLE = 0x9B59B6

    MAX_OPEN_TICKETS = 2
    COOLDOWN_SECONDS = 30
    AUTO_CLOSE_HOURS = 48
    CLOSE_DELAY      = 600

    CATEGORIE = [
        "Supporto Tecnico",
        "Pagamenti & Acquisti",
        "Report Utente",
        "Partnership",
        "Candidatura Staff",
        "Unisciti al Team",
        "Altro",
    ]
    PRIORITY_LEVELS = ["Bassa", "Media", "Alta", "Urgente"]
    PRIORITY_ICONS  = {"Bassa": "🟢", "Media": "🟡", "Alta": "🔴", "Urgente": "🚨"}
    PRIORITY_COLORS = {
        "Bassa":   0x2ECC71,
        "Media":   0xF39C12,
        "Alta":    0xE67E22,
        "Urgente": 0xE74C3C,
    }

    @classmethod
    def validate(cls) -> None:
        if not cls.TOKEN:
            raise SystemExit(
                "❌  TOKEN non configurato.\n"
                "    Imposta la variabile d'ambiente BOT_TOKEN."
            )
        if cls.GUILD_ID == 0:
            raise SystemExit(
                "❌  GUILD_ID non configurato.\n"
                "    Imposta la variabile d'ambiente GUILD_ID."
            )
        if not cls.DATABASE_URL:
            raise SystemExit(
                "❌  DATABASE_URL non configurato.\n"
                "    Su Railway: Variables → Add Reference → Postgres → DATABASE_URL."
            )
        optional_ids = [
            "LOG_CHANNEL_ID", "CATEGORY_GENERAL", "CATEGORY_MISSION_ID",
            "STAFF_TICKET_ROLE_ID", "STAFF_CASINO_ROLE_ID", "STAFF_GIVEAWAY_ROLE_ID",
            "STAFF_TEAM_ROLE_ID", "STAFF_MISSION_ROLE_ID", "TEAM_ROLE_ID",
            "CASINO_ROLE_ID", "ROLE_ADMIN_ID", "ROLE_TRIAL_ID",
            "STAFF_PARTNERSHIP_ROLE_ID", "ROLE_PARTNER_ID", "PARTNERSHIP_CHANNEL_ID",
            "MISSION_CHANNEL_ID",
        ]
        for attr in optional_ids:
            if getattr(cls, attr, 0) == 0:
                log.warning("⚠️  Config.%s = 0 — ricordati di impostarlo.", attr)

        for i, role_item in enumerate(cls.SHOP_ROLES):
            if role_item["role_id"] == 0:
                log.warning("⚠️  Config.SHOP_ROLES[%d][\"role_id\"] = 0 — ricordati di impostarlo.", i)

    @classmethod
    def guild_obj(cls) -> discord.Object:
        return discord.Object(id=cls.GUILD_ID)


# ══════════════════════════════════════════════════════════════════
# COSTANTI GLOBALI
# ══════════════════════════════════════════════════════════════════
_MC_NAME_RE = re.compile(r"^[A-Za-z0-9_]{3,16}$")
PAGE_SIZE   = 10

_giveaway_close_locks:   dict[str, asyncio.Lock] = {}
_giveaway_tasks_running: set[str]                = set()
_ticket_close_tasks:     dict[int, asyncio.Task] = {}
_afk_store:              dict[int, dict]         = {}

_db_pool: Optional[asyncpg.Pool] = None


def _get_giveaway_lock(g_id: str) -> asyncio.Lock:
    if g_id not in _giveaway_close_locks:
        _giveaway_close_locks[g_id] = asyncio.Lock()
    return _giveaway_close_locks[g_id]


def _cleanup_giveaway_lock(g_id: str) -> None:
    _giveaway_close_locks.pop(g_id, None)


# ══════════════════════════════════════════════════════════════════
# DATABASE — Pool asyncpg
# ══════════════════════════════════════════════════════════════════
async def create_pool() -> asyncpg.Pool:
    pool = await asyncpg.create_pool(
        Config.DATABASE_URL,
        ssl="require",
        min_size=2,
        max_size=10,
        command_timeout=30,
    )
    return pool


def get_pool() -> asyncpg.Pool:
    if _db_pool is None:
        raise RuntimeError("Pool del database non inizializzato.")
    return _db_pool


async def init_db() -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS members (
                discord_id BIGINT PRIMARY KEY,
                mc_name    TEXT   NOT NULL UNIQUE,
                added_by   BIGINT,
                added_at   TIMESTAMP DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS tickets (
                channel_id   BIGINT PRIMARY KEY,
                user_id      BIGINT NOT NULL,
                categoria    TEXT,
                priority     TEXT DEFAULT 'Bassa',
                status       TEXT DEFAULT 'open',
                opened_at    TIMESTAMP DEFAULT NOW(),
                last_message TIMESTAMP DEFAULT NOW(),
                claimed_by   BIGINT,
                closed_by    BIGINT,
                closed_at    TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS blacklist (
                user_id  BIGINT PRIMARY KEY,
                reason   TEXT,
                added_by BIGINT,
                added_at TIMESTAMP DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS ticket_stats (
                staff_id      BIGINT PRIMARY KEY,
                closed_count  INTEGER DEFAULT 0,
                claimed_count INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS cooldowns (
                user_id   BIGINT PRIMARY KEY,
                last_open TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS ratings (
                channel_id BIGINT PRIMARY KEY,
                user_id    BIGINT,
                score      INTEGER,
                rated_at   TIMESTAMP DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS luck (
                user_id BIGINT PRIMARY KEY,
                factor  INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS giveaways (
                id               TEXT  PRIMARY KEY,
                title            TEXT  NOT NULL,
                description      TEXT,
                channel_id       BIGINT NOT NULL,
                message_id       BIGINT,
                creator_id       BIGINT NOT NULL,
                prize            TEXT,
                winners          INTEGER NOT NULL DEFAULT 1,
                end_time         TIMESTAMP NOT NULL,
                active           BOOLEAN NOT NULL DEFAULT TRUE,
                required_role_id BIGINT DEFAULT NULL
            );

            CREATE TABLE IF NOT EXISTS entries (
                giveaway_id TEXT   NOT NULL REFERENCES giveaways(id) ON DELETE CASCADE,
                user_id     BIGINT NOT NULL,
                PRIMARY KEY (giveaway_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS casino_users (
                user_id     BIGINT PRIMARY KEY,
                balance     INTEGER  DEFAULT 250,
                bet         INTEGER  DEFAULT 10,
                last_daily  TIMESTAMP,
                last_play   TIMESTAMP,
                total_wins  INTEGER  DEFAULT 0,
                total_games INTEGER  DEFAULT 0,
                biggest_win INTEGER  DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS promo_codes (
                code       TEXT PRIMARY KEY,
                reward     INTEGER NOT NULL,
                max_uses   INTEGER NOT NULL DEFAULT 1,
                uses       INTEGER NOT NULL DEFAULT 0,
                expires_at TIMESTAMP,
                created_by BIGINT NOT NULL,
                active     BOOLEAN NOT NULL DEFAULT TRUE
            );

            CREATE TABLE IF NOT EXISTS promo_uses (
                code    TEXT   NOT NULL REFERENCES promo_codes(code) ON DELETE CASCADE,
                user_id BIGINT NOT NULL,
                used_at TIMESTAMP DEFAULT NOW(),
                PRIMARY KEY (code, user_id)
            );

            CREATE TABLE IF NOT EXISTS daily_missions (
                id          SERIAL PRIMARY KEY,
                type        TEXT    NOT NULL,
                target      INTEGER NOT NULL,
                reward      INTEGER NOT NULL,
                active_date DATE    UNIQUE NOT NULL
            );

            CREATE TABLE IF NOT EXISTS user_missions (
                user_id    BIGINT  NOT NULL,
                mission_id INTEGER NOT NULL REFERENCES daily_missions(id) ON DELETE CASCADE,
                progress   INTEGER DEFAULT 0,
                completed  BOOLEAN DEFAULT FALSE,
                PRIMARY KEY (user_id, mission_id)
            );

            CREATE TABLE IF NOT EXISTS shop_multipliers (
                id         SERIAL PRIMARY KEY,
                name       TEXT          NOT NULL UNIQUE,
                multiplier NUMERIC(3, 2) NOT NULL,
                uses       INTEGER       NOT NULL,
                cost       INTEGER       NOT NULL
            );

            CREATE TABLE IF NOT EXISTS user_multipliers (
                user_id        BIGINT  NOT NULL,
                multiplier_id  INTEGER NOT NULL REFERENCES shop_multipliers(id) ON DELETE CASCADE,
                remaining_uses INTEGER NOT NULL,
                PRIMARY KEY (user_id, multiplier_id)
            );

            CREATE TABLE IF NOT EXISTS deleted_messages (
                id BIGINT PRIMARY KEY,
                channel_id BIGINT NOT NULL,
                guild_id BIGINT NOT NULL,
                author_id BIGINT NOT NULL,
                content TEXT,
                deleted_at TIMESTAMP DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS edited_messages (
                id BIGINT PRIMARY KEY,
                channel_id BIGINT NOT NULL,
                guild_id BIGINT NOT NULL,
                author_id BIGINT NOT NULL,
                old_content TEXT,
                new_content TEXT,
                edited_at TIMESTAMP DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS polls (
                id         TEXT PRIMARY KEY,
                channel_id BIGINT NOT NULL,
                message_id BIGINT,
                question   TEXT NOT NULL,
                creator_id BIGINT NOT NULL,
                created_at TIMESTAMP DEFAULT NOW(),
                active     BOOLEAN NOT NULL DEFAULT TRUE
            );

            CREATE TABLE IF NOT EXISTS poll_options (
                id      SERIAL PRIMARY KEY,
                poll_id TEXT   NOT NULL REFERENCES polls(id) ON DELETE CASCADE,
                label   TEXT   NOT NULL,
                votes   INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS poll_votes (
                poll_id   TEXT   NOT NULL,
                option_id INTEGER NOT NULL,
                user_id   BIGINT NOT NULL,
                PRIMARY KEY (poll_id, user_id)
            );

            CREATE INDEX IF NOT EXISTS idx_tickets_status   ON tickets(status);
            CREATE INDEX IF NOT EXISTS idx_tickets_user     ON tickets(user_id);
            CREATE INDEX IF NOT EXISTS idx_entries_giveaway ON entries(giveaway_id);
            CREATE INDEX IF NOT EXISTS idx_giveaways_active ON giveaways(active, end_time);
        """)
    log.info("Database PostgreSQL inizializzato.")


# ══════════════════════════════════════════════════════════════════
# DB HELPERS — TEAM
# ══════════════════════════════════════════════════════════════════
async def db_upsert_member(discord_id: int, mc_name: str, added_by: int) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO members (discord_id, mc_name, added_by)
            VALUES ($1, $2, $3)
            ON CONFLICT(discord_id) DO UPDATE SET
                mc_name  = EXCLUDED.mc_name,
                added_by = EXCLUDED.added_by,
                added_at = NOW()
            """,
            discord_id, mc_name, added_by,
        )


async def db_delete_member(discord_id: int) -> bool:
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM members WHERE discord_id = $1", discord_id
        )
    return result.split()[-1] != "0"


async def db_get_all_members() -> list[tuple[int, str]]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT discord_id, mc_name FROM members ORDER BY mc_name"
        )
    return [(r["discord_id"], r["mc_name"]) for r in rows]


async def db_find_by_mc(mc_name: str) -> Optional[int]:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT discord_id FROM members WHERE LOWER(mc_name) = LOWER($1)", mc_name
        )
    return row["discord_id"] if row else None


# ══════════════════════════════════════════════════════════════════
# DB HELPERS — TICKET
# ══════════════════════════════════════════════════════════════════
async def is_blacklisted(user_id: int) -> bool:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT 1 FROM blacklist WHERE user_id = $1", user_id
        )
    return row is not None


async def count_open_tickets(user_id: int) -> int:
    pool = get_pool()
    async with pool.acquire() as conn:
        val = await conn.fetchval(
            "SELECT COUNT(*) FROM tickets WHERE user_id = $1 AND status = 'open'", user_id
        )
    return val or 0


async def check_cooldown(user_id: int) -> int:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT last_open FROM cooldowns WHERE user_id = $1", user_id
        )
    if not row:
        return 0
    try:
        elapsed = (utcnow_naive() - parse_naive(row["last_open"])).total_seconds()
        return max(0, int(Config.COOLDOWN_SECONDS - elapsed))
    except (ValueError, AttributeError):
        return 0


async def update_cooldown(user_id: int) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO cooldowns (user_id, last_open) VALUES ($1, NOW())
            ON CONFLICT(user_id) DO UPDATE SET last_open = NOW()
            """,
            user_id,
        )


async def get_ticket(channel_id: int) -> Optional[dict]:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM tickets WHERE channel_id = $1", channel_id
        )
    return dict(row) if row else None


async def try_update_last_message(channel_id: int) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE tickets SET last_message = NOW() WHERE channel_id = $1 AND status = 'open'",
            channel_id,
        )


# ══════════════════════════════════════════════════════════════════
# DB HELPERS — GIVEAWAY
# ══════════════════════════════════════════════════════════════════
async def db_get_luck(user_id: int) -> int:
    pool = get_pool()
    async with pool.acquire() as conn:
        val = await conn.fetchval(
            "SELECT factor FROM luck WHERE user_id = $1", user_id
        )
    return val if val is not None else 1


async def db_set_luck(user_id: int, factor: int) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO luck (user_id, factor) VALUES ($1, $2)
            ON CONFLICT(user_id) DO UPDATE SET factor = EXCLUDED.factor
            """,
            user_id, factor,
        )


async def db_get_entries_with_luck(g_id: str) -> list[tuple[int, int]]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT e.user_id, COALESCE(l.factor, 1) AS factor
            FROM entries e
            LEFT JOIN luck l ON l.user_id = e.user_id
            WHERE e.giveaway_id = $1
            ORDER BY factor DESC, e.user_id
            """,
            g_id,
        )
    return [(r["user_id"], r["factor"]) for r in rows]


async def db_create_giveaway(
    title: str,
    description: str,
    channel_id: int,
    creator_id: int,
    prize: str,
    winners: int,
    minutes: int,
    required_role_id: Optional[int] = None,
) -> tuple[str, datetime.datetime]:
    g_id   = str(uuid.uuid4())
    end_dt = utcnow_naive() + datetime.timedelta(minutes=minutes)
    pool   = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO giveaways
            (id, title, description, channel_id, creator_id, prize, winners, end_time, active, required_role_id)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, TRUE, $9)
            """,
            g_id, title, description, channel_id, creator_id,
            prize, winners, end_dt, required_role_id,
        )
    return g_id, end_dt


async def db_set_message_id(g_id: str, message_id: int) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE giveaways SET message_id = $1 WHERE id = $2", message_id, g_id
        )


async def db_get_giveaway(g_id: str) -> Optional[dict]:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM giveaways WHERE id = $1", g_id
        )
    return dict(row) if row else None


async def db_get_daily_mission(date: datetime.date) -> Optional[dict]:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM daily_missions WHERE active_date = $1", date)
    return dict(row) if row else None


async def db_create_daily_mission(type: str, target: int, reward: int, date: datetime.date) -> dict:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO daily_missions (type, target, reward, active_date) VALUES ($1, $2, $3, $4) RETURNING *",
            type, target, reward, date
        )
    return dict(row) if row else {}


async def db_get_user_mission_progress(user_id: int, mission_id: int) -> Optional[dict]:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM user_missions WHERE user_id = $1 AND mission_id = $2",
            user_id, mission_id
        )
    return dict(row) if row else None


async def db_upsert_user_mission_progress(user_id: int, mission_id: int, progress: int, completed: bool) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO user_missions (user_id, mission_id, progress, completed)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (user_id, mission_id) DO UPDATE
            SET progress = $3, completed = $4
            """,
            user_id, mission_id, progress, completed
        )


async def db_get_shop_multipliers() -> list[dict]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM shop_multipliers")
    return [dict(r) for r in rows]


async def db_get_user_multipliers(user_id: int) -> list[dict]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT sm.name, sm.multiplier, um.remaining_uses FROM user_multipliers um JOIN shop_multipliers sm ON um.multiplier_id = sm.id WHERE um.user_id = $1",
            user_id
        )
    return [dict(r) for r in rows]


async def db_add_user_multiplier(user_id: int, multiplier_id: int, uses: int) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO user_multipliers (user_id, multiplier_id, remaining_uses)
            VALUES ($1, $2, $3)
            ON CONFLICT (user_id, multiplier_id) DO UPDATE
            SET remaining_uses = user_multipliers.remaining_uses + $3
            """,
            user_id, multiplier_id, uses
        )

async def db_log_edited_message(message_id: int, channel_id: int, guild_id: int, author_id: int, old_content: str, new_content: str) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO edited_messages (id, channel_id, guild_id, author_id, old_content, new_content) VALUES ($1, $2, $3, $4, $5, $6)",
            message_id, channel_id, guild_id, author_id, old_content, new_content
        )



async def db_log_deleted_message(message_id: int, channel_id: int, guild_id: int, author_id: int, content: str) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO deleted_messages (id, channel_id, guild_id, author_id, content) VALUES ($1, $2, $3, $4, $5)",
            message_id, channel_id, guild_id, author_id, content
        )
async def db_decrement_user_multiplier(user_id: int, multiplier_id: int) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE user_multipliers SET remaining_uses = remaining_uses - 1 WHERE user_id = $1 AND multiplier_id = $2",
            user_id, multiplier_id
        )
        await conn.execute(
            "DELETE FROM user_multipliers WHERE user_id = $1 AND multiplier_id = $2 AND remaining_uses <= 0",
            user_id, multiplier_id
        )


async def db_get_expired_giveaways() -> list[dict]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM giveaways WHERE active = TRUE AND end_time <= NOW()"
        )
    return [dict(r) for r in rows]


async def db_close_giveaway(g_id: str) -> bool:
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE giveaways SET active = FALSE WHERE id = $1 AND active = TRUE", g_id
        )
    return result.split()[-1] != "0"


async def db_add_entry(g_id: str, user_id: int) -> bool:
    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO entries (giveaway_id, user_id) VALUES ($1, $2)", g_id, user_id
            )
        return True
    except asyncpg.UniqueViolationError:
        return False


async def db_remove_entry(g_id: str, user_id: int) -> bool:
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM entries WHERE giveaway_id = $1 AND user_id = $2", g_id, user_id
        )
    return result.split()[-1] != "0"


async def db_entry_count(g_id: str) -> int:
    pool = get_pool()
    async with pool.acquire() as conn:
        val = await conn.fetchval(
            "SELECT COUNT(*) FROM entries WHERE giveaway_id = $1", g_id
        )
    return val or 0


async def db_list_active_giveaways() -> list[dict]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, title, end_time, winners FROM giveaways WHERE active = TRUE ORDER BY end_time"
        )
    return [dict(r) for r in rows]


# ══════════════════════════════════════════════════════════════════
# DB HELPERS — CASINO
# ══════════════════════════════════════════════════════════════════
async def casino_get_user(user_id: int) -> dict:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO casino_users(user_id) VALUES($1) ON CONFLICT DO NOTHING", user_id
        )
        row = await conn.fetchrow(
            "SELECT * FROM casino_users WHERE user_id = $1", user_id
        )
    return dict(row)

async def casino_get_balance(user_id: int) -> int:
    data = await casino_get_user(user_id)
    return data["balance"]


async def casino_update_balance(user_id: int, amount: int) -> int:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO casino_users(user_id) VALUES($1) ON CONFLICT DO NOTHING", user_id
        )

        row = await conn.fetchrow(
            """
            UPDATE casino_users
            SET balance = GREATEST(0, balance + $1)
            WHERE user_id = $2
            RETURNING balance
            """,
            amount, user_id,
        )
        new_balance = row["balance"] if row else 0  # Handle case where row might be None

        # Update win statistics only if amount is positive (a win)
        if amount > 0:
            await conn.execute(
                """
                UPDATE casino_users
                SET total_wins  = total_wins + 1,
                    total_games = total_games + 1,
                    biggest_win = GREATEST(biggest_win, $1)
                WHERE user_id = $2
                """,
                amount, user_id,
            )
        return new_balance


async def casino_set_bet(user_id: int, bet: int) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE casino_users SET bet = $1 WHERE user_id = $2", bet, user_id
        )



async def casino_record_game(user_id: int, won: bool, prize: int) -> None:
    # This function is used to track games if needed, for now it just logs
    log.info(f"Casino game: user {user_id}, won: {won}, prize: {prize}")
# ══════════════════════════════════════════════════════════════════
# DB HELPERS — PROMO CODES
# ══════════════════════════════════════════════════════════════════
async def db_create_promo(
    code: str, reward: int, max_uses: int,
    expires_at: Optional[datetime.datetime], created_by: int,
) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO promo_codes (code, reward, max_uses, expires_at, created_by)
            VALUES ($1, $2, $3, $4, $5)
            """,
            code.upper(), reward, max_uses, expires_at, created_by,
        )


async def db_redeem_promo(code: str, user_id: int) -> tuple[bool, str, int]:
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT * FROM promo_codes WHERE code = $1 AND active = TRUE",
                code.upper(),
            )

            if not row:
                return False, "❌ Codice non valido o scaduto.", 0

            if row["expires_at"] and utcnow_naive() > parse_naive(row["expires_at"]):
                return False, "❌ Codice scaduto.", 0

            if row["uses"] >= row["max_uses"]:
                return False, "❌ Codice esaurito.", 0

            already = await conn.fetchrow(
                "SELECT 1 FROM promo_uses WHERE code = $1 AND user_id = $2",
                code.upper(), user_id,
            )
            if already:
                return False, "❌ Hai già riscattato questo codice.", 0

            await conn.execute(
                "INSERT INTO promo_uses (code, user_id) VALUES ($1, $2)",
                code.upper(), user_id,
            )
            new_uses = row["uses"] + 1
            await conn.execute(
                "UPDATE promo_codes SET uses = $1 WHERE code = $2", new_uses, code.upper()
            )
            if new_uses >= row["max_uses"]:
                await conn.execute(
                    "UPDATE promo_codes SET active = FALSE WHERE code = $1", code.upper()
                )

    return True, "✅ Codice riscattato!", row["reward"]


# ══════════════════════════════════════════════════════════════════
# DB HELPERS — PROMO CODES (ELIMINA)  ← MODIFICA
# ══════════════════════════════════════════════════════════════════
async def db_delete_promo(code: str) -> bool:
    """Elimina fisicamente un codice promo e i relativi usi (CASCADE)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM promo_codes WHERE code = $1", code.upper()
        )
    return result.split()[-1] != "0"


# ══════════════════════════════════════════════════════════════════
# DB HELPERS — POLLS
# ══════════════════════════════════════════════════════════════════
async def db_create_poll(
    question: str, options: list[str], channel_id: int, creator_id: int
) -> str:
    p_id = str(uuid.uuid4())
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "INSERT INTO polls (id, channel_id, question, creator_id) VALUES ($1, $2, $3, $4)",
                p_id, channel_id, question, creator_id,
            )
            for opt in options:
                await conn.execute(
                    "INSERT INTO poll_options (poll_id, label) VALUES ($1, $2)", p_id, opt
                )
    return p_id


async def db_get_poll(p_id: str) -> Optional[dict]:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM polls WHERE id = $1", p_id)
    return dict(row) if row else None


async def db_get_poll_options(p_id: str) -> list[dict]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM poll_options WHERE poll_id = $1 ORDER BY id", p_id
        )
    return [dict(r) for r in rows]


async def db_vote_poll(p_id: str, option_id: int, user_id: int) -> tuple[bool, str]:
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            existing = await conn.fetchrow(
                "SELECT option_id FROM poll_votes WHERE poll_id = $1 AND user_id = $2",
                p_id, user_id,
            )

            if existing:
                if existing["option_id"] == option_id:
                    return False, "Hai già votato questa opzione."
                await conn.execute(
                    "UPDATE poll_options SET votes = votes - 1 WHERE id = $1",
                    existing["option_id"],
                )
                await conn.execute(
                    "UPDATE poll_votes SET option_id = $1 WHERE poll_id = $2 AND user_id = $3",
                    option_id, p_id, user_id,
                )
            else:
                await conn.execute(
                    "INSERT INTO poll_votes (poll_id, option_id, user_id) VALUES ($1, $2, $3)",
                    p_id, option_id, user_id,
                )

            await conn.execute(
                "UPDATE poll_options SET votes = votes + 1 WHERE id = $1", option_id
            )
    return True, "Voto registrato."


async def db_close_poll(p_id: str) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE polls SET active = FALSE WHERE id = $1", p_id)


async def db_set_poll_message(p_id: str, message_id: int) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE polls SET message_id = $1 WHERE id = $2", message_id, p_id
        )


# ══════════════════════════════════════════════════════════════════
# GIOCHI — SLOT MACHINE
# ══════════════════════════════════════════════════════════════════
SYMBOLS: dict[str, dict] = {
    "🍒": {"weight": 55, "name": "Ciliegia",  "multiplier": 2},
    "🍋": {"weight": 40, "name": "Limone",    "multiplier": 3},
    "🔔": {"weight": 20, "name": "Campana",   "multiplier": 5},
    "⭐": {"weight": 12, "name": "Stella",    "multiplier": 8},
    "💎": {"weight":  5, "name": "Diamante",  "multiplier": 15},
}
_POOL: list[str] = [
    sym for sym, data in SYMBOLS.items() for _ in range(data["weight"])
]


def spin_reels() -> list[str]:
    return [random.choice(_POOL) for _ in range(3)]


def evaluate_spin(result: list[str], bet: int) -> tuple[int, str]:
    counts = {s: result.count(s) for s in set(result)}
    best   = max(counts, key=lambda s: (counts[s], SYMBOLS[s]["multiplier"]))
    if counts[best] == 3:
        mult  = SYMBOLS[best]["multiplier"]
        return bet * mult, f"**JACKPOT** {SYMBOLS[best]['name']}! ×{mult}"
    if counts[best] == 2:
        return int(bet * 1.5), f"Coppia di {SYMBOLS[best]['name']} ×1.5"
    return 0, "Nessuna combinazione"


# ══════════════════════════════════════════════════════════════════
# GIOCHI — ROULETTE
# ══════════════════════════════════════════════════════════════════
ROULETTE_RED   = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}
ROULETTE_BLACK = {2,4,6,8,10,11,13,15,17,20,22,24,26,28,29,31,33,35}


def roulette_spin() -> int:
    return random.randint(0, 36)


def roulette_color(n: int) -> str:
    if n == 0:
        return "🟢"
    return "🔴" if n in ROULETTE_RED else "⚫"


def roulette_evaluate(
    bet_type: str, bet_value: str, result: int, bet_amount: int
) -> tuple[int, str]:
    color = roulette_color(result)
    desc  = f"Risultato: **{result}** {color}"

    if bet_type == "numero":
        try:
            chosen = int(bet_value)
        except ValueError:
            return 0, desc + "\n❌ Numero non valido."
        if chosen == result:
            return bet_amount * 35, desc + "\n🎯 Numero esatto! ×35"
        return 0, desc

    if bet_type == "colore":
        v = bet_value.lower()
        if result == 0:
            return 0, desc + "\n🟢 Zero! Banco vince."
        if (v in ("rosso", "red") and result in ROULETTE_RED) or \
           (v in ("nero", "black") and result in ROULETTE_BLACK):
            return bet_amount * 2, desc + "\n✅ Colore corretto! ×2"
        return 0, desc

    if bet_type == "parita":
        if result == 0:
            return 0, desc + "\n🟢 Zero! Banco vince."
        v = bet_value.lower()
        if (v == "pari" and result % 2 == 0) or (v == "dispari" and result % 2 != 0):
            return bet_amount * 2, desc + "\n✅ Parità corretta! ×2"
        return 0, desc

    if bet_type == "metà":
        if result == 0:
            return 0, desc + "\n🟢 Zero! Banco vince."
        v = bet_value.lower()
        if (v in ("bassa", "low") and 1 <= result <= 18) or \
           (v in ("alta", "high") and 19 <= result <= 36):
            return bet_amount * 2, desc + "\n✅ Metà corretta! ×2"
        return 0, desc

    if bet_type == "dozzina":
        if result == 0:
            return 0, desc + "\n🟢 Zero! Banco vince."
        try:
            d = int(bet_value)
        except ValueError:
            return 0, desc
        ranges = {1: range(1, 13), 2: range(13, 25), 3: range(25, 37)}
        names  = {1: "Prima", 2: "Seconda", 3: "Terza"}
        if d in ranges and result in ranges[d]:
            return bet_amount * 3, desc + f"\n✅ {names[d]} dozzina! ×3"
        return 0, desc

    return 0, desc + "\n❌ Tipo di scommessa non riconosciuto."


# ══════════════════════════════════════════════════════════════════
# UTILS — CONTROLLI ACCESSO
# ══════════════════════════════════════════════════════════════════
def _has_role_or_admin(member: discord.Member, role_id: int) -> bool:
    if member.guild_permissions.administrator:
        return True
    return bool(role_id) and member.get_role(role_id) is not None


def is_ticket_staff(m: discord.Member)      -> bool: return _has_role_or_admin(m, Config.STAFF_TICKET_ROLE_ID)
def is_casino_staff(m: discord.Member)      -> bool: return _has_role_or_admin(m, Config.STAFF_CASINO_ROLE_ID)
def is_giveaway_staff(m: discord.Member)    -> bool: return _has_role_or_admin(m, Config.STAFF_GIVEAWAY_ROLE_ID)
def is_team_staff(m: discord.Member)        -> bool: return _has_role_or_admin(m, Config.STAFF_TEAM_ROLE_ID)
def is_mission_staff(m: discord.Member)     -> bool: return _has_role_or_admin(m, Config.STAFF_MISSION_ROLE_ID)
def is_partnership_staff(m: discord.Member) -> bool: return _has_role_or_admin(m, Config.STAFF_PARTNERSHIP_ROLE_ID)
def has_casino_access(m: discord.Member)    -> bool: return _has_role_or_admin(m, Config.CASINO_ROLE_ID)
def is_high_mod(m: discord.Member)          -> bool: return _has_role_or_admin(m, Config.ROLE_ADMIN_ID)


def is_any_staff(m: discord.Member) -> bool:
    return any([
        is_ticket_staff(m), is_casino_staff(m), is_giveaway_staff(m),
        is_team_staff(m), is_mission_staff(m), is_partnership_staff(m), is_high_mod(m),
    ])


def _make_staff_check(check_fn, role_id_attr: str):
    async def predicate(interaction: discord.Interaction) -> bool:
        if check_fn(interaction.user):
            return True
        raise app_commands.MissingRole(getattr(Config, role_id_attr, 0))
    return app_commands.check(predicate)


def ticket_staff_check():      return _make_staff_check(is_ticket_staff,      "STAFF_TICKET_ROLE_ID")
def casino_staff_check():      return _make_staff_check(is_casino_staff,      "STAFF_CASINO_ROLE_ID")
def giveaway_staff_check():    return _make_staff_check(is_giveaway_staff,    "STAFF_GIVEAWAY_ROLE_ID")
def team_staff_check():        return _make_staff_check(is_team_staff,        "STAFF_TEAM_ROLE_ID")
def mission_staff_check():     return _make_staff_check(is_mission_staff,     "STAFF_MISSION_ROLE_ID")
def partnership_staff_check(): return _make_staff_check(is_partnership_staff, "STAFF_PARTNERSHIP_ROLE_ID")


def casino_access_check():
    async def predicate(interaction: discord.Interaction) -> bool:
        if has_casino_access(interaction.user):
            return True
        embed = discord.Embed(
            title="🚫 Accesso negato",
            description=(
                f"Per usare il casino hai bisogno del ruolo <@&{Config.CASINO_ROLE_ID}>.\n"
                "Contatta lo staff per ottenerlo."
            ),
            color=Config.COLOR_LOSE,
        )
        if not interaction.response.is_done():
            await interaction.response.send_message(embed=embed, ephemeral=True)
        raise app_commands.CheckFailure("Casino role required")
    return app_commands.check(predicate)


# ══════════════════════════════════════════════════════════════════
# UTILS — HELPER GENERICI
# ══════════════════════════════════════════════════════════════════
def base_embed(title: str, color: int, user: discord.User | discord.Member) -> discord.Embed:
    embed = discord.Embed(title=title, color=color, timestamp=utcnow())
    embed.set_footer(
        text=f"{user.display_name}  •  Combined Bot",
        icon_url=user.display_avatar.url,
    )
    return embed


def coin(n: int) -> str:
    return f"**{n:,}** 🪙"


async def get_team_role(guild: discord.Guild) -> Optional[discord.Role]:
    return guild.get_role(Config.TEAM_ROLE_ID)


async def safe_add_role(member: discord.Member, role: discord.Role) -> tuple[bool, str]:
    try:
        await member.add_roles(role, reason="Aggiunto via bot")
        return True, ""
    except discord.Forbidden:
        return False, "Permessi insufficienti."
    except discord.HTTPException as exc:
        return False, f"Errore HTTP: {exc.status}"


async def safe_remove_role(member: discord.Member, role: discord.Role) -> tuple[bool, str]:
    try:
        await member.remove_roles(role, reason="Rimosso via bot")
        return True, ""
    except discord.Forbidden:
        return False, "Permessi insufficienti."
    except discord.HTTPException as exc:
        return False, f"Errore HTTP: {exc.status}"


async def build_transcript(channel: discord.TextChannel) -> Optional[discord.File]:
    if HAS_CHAT_EXPORTER:
        try:
            html = await chat_exporter.export(channel)
            if html:
                return discord.File(
                    io.BytesIO(html.encode()),
                    filename=f"transcript-{channel.id}.html",
                )
        except Exception as e:
            log.warning("chat_exporter fallito per #%s: %s", channel.name, e)

    try:
        lines = [
            f"[{m.created_at:%Y-%m-%d %H:%M}] {m.author.display_name}: {m.content}"
            async for m in channel.history(limit=1000, oldest_first=True)
            if m.content
        ]
        return discord.File(
            io.BytesIO("\n".join(lines).encode()),
            filename=f"transcript-{channel.id}.txt",
        )
    except Exception as e:
        log.error("Fallback transcript fallito per #%s: %s", channel.name, e)
        return None


# ══════════════════════════════════════════════════════════════════
# TICKET — CHIUSURA con countdown e riapri
# ══════════════════════════════════════════════════════════════════
async def _do_archive_ticket(
    channel: discord.TextChannel,
    closer: discord.Member,
    guild: discord.Guild,
    force: bool = False,
    reason: str = "",
) -> None:
    ticket = await get_ticket(channel.id)
    if not ticket:
        return

    transcript_file = await build_transcript(channel)

    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO ticket_stats (staff_id, closed_count) VALUES ($1, 1)
            ON CONFLICT(staff_id) DO UPDATE SET closed_count = ticket_stats.closed_count + 1
            """,
            closer.id,
        )
        await conn.execute(
            "UPDATE tickets SET status='closed', closed_by=$1, closed_at=NOW() WHERE channel_id=$2",
            closer.id, channel.id,
        )

    owner = guild.get_member(ticket["user_id"])
    if owner:
        icon  = Config.PRIORITY_ICONS.get(ticket.get("priority", ""), "")
        embed = discord.Embed(
            title="Il tuo ticket è stato chiuso",
            description=(
                f"**Server:** {guild.name}\n"
                f"**Canale:** `{channel.name}`\n"
                f"**Chiuso da:** {closer.display_name}\n"
                f"**Priorità:** {icon} {ticket.get('priority', 'N/A')}\n"
                + (f"**Motivo:** {reason}" if reason else "")
            ),
            color=0xE74C3C,
            timestamp=utcnow(),
        )
        with contextlib.suppress(discord.Forbidden, discord.HTTPException):
            await owner.send(embed=embed, view=RatingView(channel.id, owner.id))

    log_ch = guild.get_channel(Config.LOG_CHANNEL_ID)
    if log_ch:
        label   = "forzata" if force else "chiusa"
        r_text  = f"\n**Motivo:** {reason}" if reason else ""
        content = (
            f"Ticket `{channel.name}` {label} da {closer.mention}{r_text}\n"
            f"**Categoria:** {ticket.get('categoria', 'N/A')} | "
            f"**Priorità:** {ticket.get('priority', 'N/A')}"
        )
        with contextlib.suppress(discord.HTTPException):
            if transcript_file:
                await log_ch.send(content, file=transcript_file)
            else:
                await log_ch.send(content + "\n*(transcript non disponibile)*")

    await asyncio.sleep(3)
    with contextlib.suppress(discord.HTTPException, discord.NotFound):
        await channel.delete(
            reason=f"Ticket chiuso da {closer} — {reason or 'nessun motivo'}"
        )


async def _countdown_and_archive(
    channel: discord.TextChannel,
    closer: discord.Member,
    guild: discord.Guild,
    force: bool = False,
    reason: str = "",
) -> None:
    try:
        await asyncio.sleep(Config.CLOSE_DELAY)
        ticket = await get_ticket(channel.id)
        if ticket and ticket["status"] == "open":
            return
        await _do_archive_ticket(channel, closer, guild, force=force, reason=reason)
    except asyncio.CancelledError:
        log.info("Countdown chiusura annullato per #%s (riaperto)", channel.name)
    finally:
        _ticket_close_tasks.pop(channel.id, None)


async def close_ticket(
    channel: discord.TextChannel,
    closer: discord.Member,
    guild: discord.Guild,
    force: bool = False,
    reason: str = "",
) -> None:
    ticket = await get_ticket(channel.id)
    if not ticket or ticket["status"] != "open":
        return

    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE tickets SET status='closing' WHERE channel_id=$1", channel.id
        )

    delay_min = Config.CLOSE_DELAY // 60
    embed = discord.Embed(
        title="🔒 Ticket in fase di archiviazione",
        description=(
            f"Il canale verrà eliminato tra **{delay_min} minuti**.\n"
            f"**Chiuso da:** {closer.mention}\n"
            + (f"**Motivo:** {reason}" if reason else "")
        ),
        color=0xE74C3C,
        timestamp=utcnow(),
    )
    embed.set_footer(text="Clicca 'Riapri Ticket' per annullare la chiusura.")

    reopen_view = ReopenView(channel.id, ticket["user_id"])
    close_msg   = await channel.send(embed=embed, view=reopen_view)
    reopen_view._close_message = close_msg

    old_task = _ticket_close_tasks.pop(channel.id, None)
    if old_task and not old_task.done():
        old_task.cancel()

    task = asyncio.create_task(
        _countdown_and_archive(channel, closer, guild, force=force, reason=reason)
    )
    _ticket_close_tasks[channel.id] = task


class ReopenView(discord.ui.View):
    def __init__(self, channel_id: int, owner_id: int):
        super().__init__(timeout=Config.CLOSE_DELAY + 60)
        self.channel_id    = channel_id
        self.owner_id      = owner_id
        self._close_message: Optional[discord.Message] = None

    @discord.ui.button(
        label="🔓 Riapri Ticket",
        style=discord.ButtonStyle.success,
        custom_id="reopen_ticket_v17",
    )
    async def reopen_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.owner_id and not is_ticket_staff(interaction.user):
            return await interaction.response.send_message(
                "❌ Solo l'utente che ha aperto il ticket o lo staff possono riaprirlo.",
                ephemeral=True,
            )

        task = _ticket_close_tasks.pop(self.channel_id, None)
        if task and not task.done():
            task.cancel()

        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE tickets SET status='open' WHERE channel_id=$1", self.channel_id
            )

        button.disabled = True
        button.label    = "✅ Riaperto"
        button.style    = discord.ButtonStyle.secondary
        with contextlib.suppress(discord.HTTPException):
            await interaction.response.edit_message(
                embed=discord.Embed(
                    title="✅ Ticket Riaperto",
                    description=f"Riaperto da {interaction.user.mention}.",
                    color=0x2ECC71,
                    timestamp=utcnow(),
                ),
                view=self,
            )

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True  # type: ignore[attr-defined]
        if self._close_message:
            with contextlib.suppress(discord.HTTPException):
                await self._close_message.edit(view=self)


# ══════════════════════════════════════════════════════════════════
# GIVEAWAY — embed builder
# ══════════════════════════════════════════════════════════════════
def _parse_end_time(raw: str | datetime.datetime) -> datetime.datetime:
    if isinstance(raw, str):
        return datetime.datetime.fromisoformat(raw)
    return raw


def build_giveaway_embed(
    title: str,
    description: str,
    prize: str,
    end_time: datetime.datetime,
    winners: int,
    entry_count: int,
    active: bool = True,
    winner_mentions: list[str] | None = None,
    required_role_id: Optional[int] = None,
) -> discord.Embed:
    colour = discord.Colour.gold() if active else discord.Colour.greyple()
    embed  = discord.Embed(
        title=f"🎉 {title}",
        description=description or "",
        colour=colour,
        timestamp=end_time,
    )
    embed.add_field(name="🏆 Premio",       value=prize or "Sorpresa!", inline=True)
    embed.add_field(name="🎖️ Vincitori",   value=str(winners),         inline=True)
    embed.add_field(name="👥 Partecipanti", value=str(entry_count),     inline=True)
    if required_role_id:
        embed.add_field(name="🔒 Ruolo richiesto", value=f"<@&{required_role_id}>", inline=True)
    if active:
        embed.set_footer(text="Scade il")
    elif winner_mentions:
        embed.add_field(name="🥳 Vincitori", value="\n".join(winner_mentions), inline=False)
        embed.set_footer(text="Giveaway terminato il")
    else:
        embed.add_field(name="Risultato", value="Nessun partecipante 😔", inline=False)
        embed.set_footer(text="Giveaway terminato il")
    return embed


async def refresh_giveaway_embed(client: discord.Client, g_id: str, count: int) -> None:
    g = await db_get_giveaway(g_id)
    if not g or not g["message_id"]:
        return
    channel = client.get_channel(g["channel_id"])
    if not channel:
        return
    end_time = _parse_end_time(g["end_time"])
    embed = build_giveaway_embed(
        title=g["title"],
        description=g["description"] or "",
        prize=g["prize"] or "",
        end_time=end_time,
        winners=g["winners"],
        entry_count=count,
        required_role_id=g.get("required_role_id"),
    )
    with contextlib.suppress(discord.HTTPException, discord.NotFound):
        msg = await channel.fetch_message(g["message_id"])
        await msg.edit(embed=embed)


# ══════════════════════════════════════════════════════════════════
# MISSIONI
# ══════════════════════════════════════════════════════════════════
def _make_mission_channel_name(username: str) -> str:
    clean = re.sub(r"[^a-z0-9-]", "-", username.lower())
    clean = re.sub(r"-{2,}", "-", clean).strip("-")
    return f"missione-{clean}"


class MissionControl(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Concludi ✅",
        style=discord.ButtonStyle.success,
        custom_id="mission_control_complete",
    )
    async def complete(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_mission_staff(interaction.user):
            return await interaction.response.send_message(
                "Solo lo Staff Missioni può confermare!", ephemeral=True
            )
        await interaction.response.send_message("✨ **Missione Completata!** Premiazione in corso...")
        await asyncio.sleep(7)
        with contextlib.suppress(discord.HTTPException, discord.NotFound):
            await interaction.channel.delete()

    @discord.ui.button(
        label="Annulla ❌",
        style=discord.ButtonStyle.danger,
        custom_id="mission_control_cancel",
    )
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_mission_staff(interaction.user):
            return await interaction.response.send_message(
                "Solo lo Staff Missioni può annullare!", ephemeral=True
            )
        await interaction.response.send_message(
            "⚠️ **Missione Fallita/Annullata.** Chiusura canale..."
        )
        await asyncio.sleep(5)
        with contextlib.suppress(discord.HTTPException, discord.NotFound):
            await interaction.channel.delete()


class MissionView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Accetta Missione ⚔️",
        style=discord.ButtonStyle.green,
        custom_id="mission_board_accept",
    )
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)

        embed       = interaction.message.embeds[0]
        footer_text = embed.footer.text or ""
        matches     = re.findall(r"\d+", footer_text)

        if len(matches) < 2:
            return await interaction.followup.send(
                "❌ Impossibile leggere i posti dalla bacheca. Contatta uno staff.",
                ephemeral=True,
            )

        current = int(matches[0])
        total   = int(matches[1])

        if current >= total:
            button.disabled = True
            button.label    = "Missione Piena"
            with contextlib.suppress(discord.HTTPException):
                await interaction.message.edit(view=self)
            return await interaction.followup.send(
                "❌ Tutti i posti per questa missione sono già occupati!", ephemeral=True
            )

        channel_name = _make_mission_channel_name(interaction.user.name)
        existing     = discord.utils.get(interaction.guild.channels, name=channel_name)
        if existing:
            return await interaction.followup.send(
                f"⚠️ Hai già una missione attiva: {existing.mention}", ephemeral=True
            )

        current += 1
        embed.set_footer(text=f"Posti occupati: {current}/{total}")
        if current >= total:
            button.label    = "Missione Piena"
            button.style    = discord.ButtonStyle.secondary
            button.disabled = True

        with contextlib.suppress(discord.HTTPException):
            await interaction.message.edit(embed=embed, view=self)

        staff_role = interaction.guild.get_role(Config.STAFF_MISSION_ROLE_ID)
        category   = interaction.guild.get_channel(Config.CATEGORY_MISSION_ID)

        overwrites: dict = {
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, attach_files=True
            ),
        }
        if staff_role:
            overwrites[staff_role] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True
            )

        try:
            channel = await interaction.guild.create_text_channel(
                name=channel_name,
                category=category,
                overwrites=overwrites,
                topic=f"Missione privata di {interaction.user} | Staff: {staff_role}",
            )
        except discord.HTTPException as e:
            log.error("Impossibile creare canale missione per %s: %s", interaction.user, e)
            current -= 1
            embed.set_footer(text=f"Posti occupati: {current}/{total}")
            button.disabled = False
            button.label    = "Accetta Missione ⚔️"
            button.style    = discord.ButtonStyle.green
            with contextlib.suppress(discord.HTTPException):
                await interaction.message.edit(embed=embed, view=self)
            return await interaction.followup.send(
                "❌ Impossibile creare il canale missione. Contatta uno staff.", ephemeral=True
            )

        obiettivo = embed.fields[0].value if embed.fields else "N/D"
        premio    = embed.fields[1].value if len(embed.fields) > 1 else "N/D"

        priv_embed = discord.Embed(
            title="⚔️ DETTAGLI MISSIONE",
            color=discord.Color.blue(),
            timestamp=utcnow(),
        )
        priv_embed.add_field(name="🎯 Obiettivo", value=obiettivo, inline=False)
        priv_embed.add_field(name="💰 Premio",    value=premio,    inline=True)
        priv_embed.set_footer(text=f"Accettata da {interaction.user}")

        content_parts = [interaction.user.mention]
        if staff_role:
            content_parts.append(staff_role.mention)

        await channel.send(
            content=" | ".join(content_parts),
            embed=priv_embed,
            view=MissionControl(),
        )
        await interaction.followup.send(
            f"✅ Missione accettata! Il tuo canale privato: {channel.mention}", ephemeral=True
        )


# ══════════════════════════════════════════════════════════════════
# PAGINAZIONE GENERICA
# ══════════════════════════════════════════════════════════════════
class GiveawayParticipantsView(discord.ui.View):
    def __init__(
        self,
        rows: list[tuple[int, int]],
        giveaway_title: str,
        guild: discord.Guild,
        invoker: discord.Member,
        show_luck: bool = True,
    ):
        super().__init__(timeout=180)
        self.rows           = rows
        self.giveaway_title = giveaway_title
        self.guild          = guild
        self.invoker        = invoker
        self.show_luck      = show_luck
        self.page           = 0
        self.max_page       = max(0, math.ceil(len(rows) / PAGE_SIZE) - 1)
        self._message: Optional[discord.Message] = None
        self._update_buttons()

    def _update_buttons(self) -> None:
        self.prev_btn.disabled = self.page == 0
        self.next_btn.disabled = self.page == self.max_page

    def _build_embed(self) -> discord.Embed:
        start      = self.page * PAGE_SIZE
        chunk      = self.rows[start: start + PAGE_SIZE]
        total_luck = sum(r[1] for r in self.rows)
        title      = (
            f"🍀 Partecipanti & Fortuna — {self.giveaway_title[:45]}"
            if self.show_luck else f"👥 Partecipanti — {self.giveaway_title[:50]}"
        )
        embed = discord.Embed(
            title=title,
            description=(
                f"**Totale partecipanti:** {len(self.rows)}\n"
                + (f"**Luck totale pool:** {total_luck}\n" if self.show_luck else "")
            ),
            color=discord.Colour.green() if self.show_luck else discord.Colour.blurple(),
            timestamp=utcnow(),
        )
        for pos, (user_id, luck) in enumerate(chunk, start=start + 1):
            member  = self.guild.get_member(user_id)
            display = member.mention if member else f"*(ID: {user_id})*"
            name    = member.display_name if member else str(user_id)
            if self.show_luck:
                pct = (luck / total_luck * 100) if total_luck > 0 else 0
                embed.add_field(
                    name=f"{pos}. {name}",
                    value=f"{display}\n🍀 Fortuna: **{luck}x** | 📊 Prob. ~{pct:.1f}%",
                    inline=False,
                )
            else:
                embed.add_field(name=f"{pos}.", value=display, inline=True)
        embed.set_footer(text=f"Pagina {self.page + 1}/{self.max_page + 1}")
        return embed

    async def _check_invoker(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.invoker.id:
            await interaction.response.send_message(
                "❌ Solo chi ha usato il comando può navigare questa lista.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="◀ Precedente", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_invoker(interaction):
            return
        self.page -= 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    @discord.ui.button(label="Successivo ▶", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_invoker(interaction):
            return
        self.page += 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True  # type: ignore[attr-defined]
        if self._message:
            with contextlib.suppress(discord.HTTPException):
                await self._message.edit(view=self)


class MemberListView(discord.ui.View):
    def __init__(
        self,
        rows: list[tuple[int, str]],
        guild: discord.Guild,
        invoker: discord.User | discord.Member,
    ):
        super().__init__(timeout=120)
        self.rows     = rows
        self.guild    = guild
        self.invoker  = invoker
        self.page     = 0
        self.max_page = max(0, (len(rows) - 1) // PAGE_SIZE)
        self._message: Optional[discord.Message] = None
        self._update_buttons()

    def _update_buttons(self) -> None:
        self.prev_btn.disabled = self.page == 0
        self.next_btn.disabled = self.page == self.max_page

    def _build_embed(self) -> discord.Embed:
        start = self.page * PAGE_SIZE
        chunk = self.rows[start: start + PAGE_SIZE]
        embed = discord.Embed(
            title="🏆 Membri del Team",
            description=f"**{len(self.rows)}** membri registrati",
            color=discord.Color.blue(),
        )
        for discord_id, mc_name in chunk:
            member  = self.guild.get_member(discord_id)
            display = member.mention if member else f"*(non nel server — ID: {discord_id})*"
            embed.add_field(name=f"🎮 {mc_name}", value=display, inline=False)
        embed.set_footer(text=f"Pagina {self.page + 1}/{self.max_page + 1}")
        return embed

    async def _check_invoker(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.invoker.id:
            await interaction.response.send_message(
                "❌ Solo chi ha usato il comando può navigare la lista.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="◀ Precedente", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_invoker(interaction):
            return
        self.page -= 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    @discord.ui.button(label="Successivo ▶", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_invoker(interaction):
            return
        self.page += 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True  # type: ignore[attr-defined]
        if self._message:
            with contextlib.suppress(discord.HTTPException):
                await self._message.edit(view=self)


# ══════════════════════════════════════════════════════════════════
# TEAM — MODAL
# ══════════════════════════════════════════════════════════════════
class AddMemberModal(discord.ui.Modal, title="Aggiungi Membro al Team"):
    discord_id_field = discord.ui.TextInput(
        label="ID Discord (solo numeri)",
        placeholder="Es. 123456789012345678",
        min_length=17, max_length=20,
    )
    mc_name_field = discord.ui.TextInput(
        label="Nickname Minecraft (3–16 caratteri)",
        placeholder="Es. Steve_123",
        min_length=3, max_length=16,
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        raw_id = self.discord_id_field.value.strip()
        if not raw_id.isdigit():
            return await interaction.response.send_message(
                "❌ L'ID Discord deve contenere solo numeri.", ephemeral=True
            )
        user_id = int(raw_id)
        member  = interaction.guild.get_member(user_id)
        if not member:
            return await interaction.response.send_message(
                f"❌ Nessun membro trovato con ID `{user_id}`.", ephemeral=True
            )
        mc = self.mc_name_field.value.strip()()
        if not _MC_NAME_RE.match(mc):
            return await interaction.response.send_message(
                "❌ Nickname Minecraft non valido (lettere, cifre, _, 3–16 caratteri).",
                ephemeral=True,
            )
        await db_upsert_member(user_id, mc, interaction.user.id)
        role = await get_team_role(interaction.guild)
        if not role:
            return await interaction.response.send_message(
                f"⚠️ Membro salvato, ma il ruolo ID `{Config.TEAM_ROLE_ID}` non esiste.",
                ephemeral=True,
            )
        role_ok, role_err = await safe_add_role(member, role)
        embed = discord.Embed(
            title="✅ Membro Aggiunto",
            description=(
                f"**Discord:** {member.mention}\n"
                f"**Minecraft:** `{mc}`\n"
                f"**Ruolo:** {role.mention if role_ok else f'⚠️ {role_err}'}"
            ),
            color=discord.Color.green() if role_ok else discord.Color.orange(),
        )
        embed.set_footer(text=f"Aggiunto da {interaction.user}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        log.exception("Errore in AddMemberModal: %s", error)
        msg = "❌ Errore imprevisto."
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)


# ══════════════════════════════════════════════════════════════════
# CANDIDATURA STAFF — MODAL & REVIEW
# ══════════════════════════════════════════════════════════════════
class StaffApplicationModal(discord.ui.Modal, title="📋 Candidatura Staff"):
    eta = discord.ui.TextInput(
        label="Età",
        placeholder="Inserisci la tua età (numero)",
        min_length=1, max_length=3,
    )
    motivazione = discord.ui.TextInput(
        label="Perché vuoi entrare nello staff?",
        style=discord.TextStyle.paragraph,
        placeholder="Descrivi la tua motivazione...",
        min_length=20, max_length=1000,
    )
    esperienze = discord.ui.TextInput(
        label="Esperienze pregresse (Opzionale)",
        style=discord.TextStyle.paragraph,
        placeholder="Hai già fatto lo staff altrove?",
        required=False, max_length=500,
    )

    def __init__(self, channel: discord.TextChannel, applicant: discord.Member):
        super().__init__()
        self.channel   = channel
        self.applicant = applicant

    async def on_submit(self, interaction: discord.Interaction) -> None:
        eta_str = self.eta.value.strip()
        if not eta_str.isdigit() or not (10 <= int(eta_str) <= 99):
            return await interaction.response.send_message(
                "❌ Inserisci un'età valida.", ephemeral=True
            )
        eta_val = int(eta_str)
        await interaction.response.defer(ephemeral=True)

        embed = discord.Embed(
            title="📋 Candidatura Ricevuta",
            color=discord.Color.blurple(),
            timestamp=utcnow(),
        )
        embed.set_author(
            name=f"Candidatura di {self.applicant.display_name}",
            icon_url=self.applicant.display_avatar.url,
        )
        embed.add_field(name="👤 Candidato",  value=self.applicant.mention, inline=True)
        embed.add_field(name="🎂 Età",         value=str(eta_val),           inline=True)
        embed.add_field(name="\u200b",          value="\u200b",               inline=True)
        embed.add_field(name="💬 Motivazione", value=self.motivazione.value, inline=False)
        embed.add_field(
            name="🏅 Esperienze",
            value=self.esperienze.value or "*(non specificate)*",
            inline=False,
        )
        embed.set_footer(text="Solo High Mod può accettare o rifiutare.")

        admin_role = self.channel.guild.get_role(Config.ROLE_ADMIN_ID)
        mention    = admin_role.mention if admin_role else "**@High Mod**"

        await self.channel.send(
            content=f"{mention} — nuova candidatura da esaminare!",
            embed=embed,
            view=StaffApplicationReviewView(applicant=self.applicant, channel=self.channel),
            allowed_mentions=discord.AllowedMentions(roles=True),
        )
        await interaction.followup.send(
            "✅ La tua candidatura è stata inviata! Lo staff la esaminerà a breve.",
            ephemeral=True,
        )

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        log.exception("Errore in StaffApplicationModal: %s", error)
        msg = "❌ Errore imprevisto."
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)


class StaffApplicationReviewView(discord.ui.View):
    def __init__(self, applicant: discord.Member, channel: discord.TextChannel):
        super().__init__(timeout=None)
        self.applicant = applicant
        self.channel   = channel
        self._decided  = False

    async def _check_perm(self, interaction: discord.Interaction) -> bool:
        if is_high_mod(interaction.user):
            return True
        await interaction.response.send_message(
            "❌ Solo i **High Mod** possono gestire le candidature.", ephemeral=True
        )
        return False

    @discord.ui.button(label="✅ ACCETTA", style=discord.ButtonStyle.success, custom_id="staff_app_accept_v17")
    async def accept_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_perm(interaction) or self._decided:
            if self._decided:
                await interaction.response.send_message("⚠️ Già gestita.", ephemeral=True)
            return
        self._decided = True

        trial_role = interaction.guild.get_role(Config.ROLE_TRIAL_ID)
        role_msg   = ""
        if trial_role:
            ok, err  = await safe_add_role(self.applicant, trial_role)
            role_msg = f"✅ Ruolo {trial_role.mention} assegnato." if ok else f"⚠️ {err}"
        else:
            role_msg = f"⚠️ Ruolo Trial (ID `{Config.ROLE_TRIAL_ID}`) non trovato."

        for item in self.children:
            item.disabled = True  # type: ignore[attr-defined]
        await interaction.response.edit_message(view=self)

        await self.channel.send(
            embed=discord.Embed(
                title="🎉 Candidatura Accettata!",
                description=(
                    f"Congratulazioni {self.applicant.mention}! 🥳\n"
                    f"Accettata da {interaction.user.mention}.\n\n{role_msg}"
                ),
                color=0x2ECC71, timestamp=utcnow(),
            ).set_footer(text=f"Gestita da {interaction.user}")
        )
        with contextlib.suppress(discord.Forbidden, discord.HTTPException):
            await self.applicant.send(
                embed=discord.Embed(
                    title="🎉 Candidatura Accettata!",
                    description=f"La tua candidatura su **{interaction.guild.name}** è stata accettata!\n\n{role_msg}",
                    color=0x2ECC71, timestamp=utcnow(),
                )
            )
        await asyncio.sleep(5)
        ticket = await get_ticket(self.channel.id)
        if ticket and ticket["status"] == "open":
            await close_ticket(self.channel, interaction.user, interaction.guild, reason="Candidatura accettata")

    @discord.ui.button(label="❌ RIFIUTA", style=discord.ButtonStyle.danger, custom_id="staff_app_reject_v17")
    async def reject_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_perm(interaction) or self._decided:
            if self._decided:
                await interaction.response.send_message("⚠️ Già gestita.", ephemeral=True)
            return
        self._decided = True

        for item in self.children:
            item.disabled = True  # type: ignore[attr-defined]
        await interaction.response.edit_message(view=self)

        await self.channel.send(
            embed=discord.Embed(
                title="❌ Candidatura Rifiutata",
                description=(
                    f"Ci dispiace {self.applicant.mention}, candidatura rifiutata da {interaction.user.mention}.\n"
                    "Non scoraggiarti! Puoi riprovare in futuro."
                ),
                color=0xE74C3C, timestamp=utcnow(),
            ).set_footer(text=f"Gestita da {interaction.user}")
        )
        with contextlib.suppress(discord.Forbidden, discord.HTTPException):
            await self.applicant.send(
                embed=discord.Embed(
                    title="❌ Candidatura Rifiutata",
                    description=f"La tua candidatura su **{interaction.guild.name}** è stata rifiutata. Riprova in futuro!",
                    color=0xE74C3C, timestamp=utcnow(),
                )
            )
        await asyncio.sleep(3)
        ticket = await get_ticket(self.channel.id)
        if ticket and ticket["status"] == "open":
            await close_ticket(self.channel, interaction.user, interaction.guild, reason="Candidatura rifiutata")


# ══════════════════════════════════════════════════════════════════
# PARTNERSHIP — MODAL & REVIEW
# ══════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════
# UNISCITI AL TEAM — MODAL & REVIEW
# ══════════════════════════════════════════════════════════════════
class JoinTeamModal(discord.ui.Modal, title="🎮 Unisciti al Team"):
    eta = discord.ui.TextInput(
        label="Età",
        placeholder="Inserisci la tua età",
        min_length=1, max_length=3,
    )
    motivazione = discord.ui.TextInput(
        label="Perché vuoi entrare nel team?",
        style=discord.TextStyle.paragraph,
        placeholder="Descrivi la tua motivazione...",
        min_length=20, max_length=1000,
    )
    vip_metamc = discord.ui.TextInput(
        label="Che VIP possiedi sulla survival di MetaMC?",
        placeholder="Es: VIP, VIP+, MVP, Nessuno...",
        max_length=100,
    )

    def __init__(self, channel: discord.TextChannel, applicant: discord.Member):
        super().__init__()
        self.channel   = channel
        self.applicant = applicant

    async def on_submit(self, interaction: discord.Interaction) -> None:
        eta_str = self.eta.value.strip()
        if not eta_str.isdigit() or not (10 <= int(eta_str) <= 99):
            return await interaction.response.send_message(
                "❌ Inserisci un'età valida.", ephemeral=True
            )
        eta_val = int(eta_str)
        await interaction.response.defer(ephemeral=True)

        embed = discord.Embed(
            title="🎮 Candidatura Team Ricevuta",
            color=discord.Color.green(),
            timestamp=utcnow(),
        )
        embed.set_author(
            name=f"Candidatura di {self.applicant.display_name}",
            icon_url=self.applicant.display_avatar.url,
        )
        embed.add_field(name="👤 Candidato",  value=self.applicant.mention, inline=True)
        embed.add_field(name="🎂 Età",         value=str(eta_val),           inline=True)
        embed.add_field(name="💎 VIP MetaMC",  value=self.vip_metamc.value,  inline=True)
        embed.add_field(name="💬 Motivazione", value=self.motivazione.value, inline=False)
        embed.set_footer(text="Lo staff del team può accettare o rifiutare.")

        team_role = self.channel.guild.get_role(Config.STAFF_TEAM_ROLE_ID)
        mention   = team_role.mention if team_role else "**@Staff Team**"

        await self.channel.send(
            content=f"{mention} — nuova candidatura per il Team!",
            embed=embed,
            view=JoinTeamReviewView(applicant=self.applicant, channel=self.channel),
            allowed_mentions=discord.AllowedMentions(roles=True),
        )
        await interaction.followup.send(
            "✅ La tua candidatura per il Team è stata inviata!",
            ephemeral=True,
        )

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        log.exception("Errore in JoinTeamModal: %s", error)
        msg = "❌ Errore imprevisto."
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)


class JoinTeamReviewView(discord.ui.View):
    def __init__(self, applicant: discord.Member, channel: discord.TextChannel):
        super().__init__(timeout=None)
        self.applicant = applicant
        self.channel   = channel
        self._decided  = False

    async def _check_perm(self, interaction: discord.Interaction) -> bool:
        if is_team_staff(interaction.user):
            return True
        await interaction.response.send_message(
            "❌ Solo lo **Staff Team** può gestire queste candidature.", ephemeral=True
        )
        return False

    @discord.ui.button(label="✅ ACCETTA", style=discord.ButtonStyle.success, custom_id="join_team_accept_v17")
    async def accept_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_perm(interaction) or self._decided:
            if self._decided:
                await interaction.response.send_message("⚠️ Già gestita.", ephemeral=True)
            return
        self._decided = True

        team_role = interaction.guild.get_role(Config.TEAM_ROLE_ID)
        role_msg  = ""
        if team_role:
            ok, err  = await safe_add_role(self.applicant, team_role)
            role_msg = f"✅ Ruolo {team_role.mention} assegnato." if ok else f"⚠️ {err}"
        else:
            role_msg = f"⚠️ Ruolo Team (ID `{Config.TEAM_ROLE_ID}`) non trovato."

        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)

        await self.channel.send(
            embed=discord.Embed(
                title="🎉 Benvenuto nel Team!",
                description=(
                    f"Congratulazioni {self.applicant.mention}! 🥳\n"
                    f"Accettata da {interaction.user.mention}.\n\n{role_msg}"
                ),
                color=0x2ECC71, timestamp=utcnow(),
            ).set_footer(text=f"Gestita da {interaction.user}")
        )
        with contextlib.suppress(discord.Forbidden, discord.HTTPException):
            await self.applicant.send(
                embed=discord.Embed(
                    title="🎉 Benvenuto nel Team!",
                    description=f"La tua candidatura per il Team su **{interaction.guild.name}** è stata accettata!\n\n{role_msg}",
                    color=0x2ECC71, timestamp=utcnow(),
                )
            )

    @discord.ui.button(label="❌ RIFIUTA", style=discord.ButtonStyle.danger, custom_id="join_team_reject_v17")
    async def reject_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_perm(interaction) or self._decided:
            if self._decided:
                await interaction.response.send_message("⚠️ Già gestita.", ephemeral=True)
            return
        self._decided = True

        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)

        await self.channel.send(
            embed=discord.Embed(
                title="❌ Candidatura Rifiutata",
                description=(
                    f"Ci dispiace {self.applicant.mention}, la tua candidatura per il team è stata rifiutata da {interaction.user.mention}."
                ),
                color=0xE74C3C, timestamp=utcnow(),
            ).set_footer(text=f"Gestita da {interaction.user}")
        )
        with contextlib.suppress(discord.Forbidden, discord.HTTPException):
            await self.applicant.send(
                embed=discord.Embed(
                    title="❌ Candidatura Team Rifiutata",
                    description=f"La tua candidatura per il team su **{interaction.guild.name}** è stata rifiutata.",
                    color=0xE74C3C, timestamp=utcnow(),
                )
            )
        await asyncio.sleep(3)
        ticket = await get_ticket(self.channel.id)
        if ticket and ticket["status"] == "open":
            await close_ticket(self.channel, interaction.user, interaction.guild, reason="Candidatura team rifiutata")


class JoinTeamStartView(discord.ui.View):
    def __init__(self, applicant: discord.Member | discord.User, channel: discord.TextChannel):
        super().__init__(timeout=3600)
        self.applicant = applicant
        self.channel   = channel
        self._used     = False

    @discord.ui.button(
        label="🎮 Compila Candidatura Team",
        style=discord.ButtonStyle.green,
        custom_id="join_team_start_v17",
    )
    async def start_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.applicant.id:
            return await interaction.response.send_message(
                "❌ Solo il candidato può compilare questo form.", ephemeral=True
            )
        if self._used:
            return await interaction.response.send_message("⚠️ Hai già compilato la candidatura.", ephemeral=True)
        self._used      = True
        button.disabled = True
        button.label    = "✅ Candidatura Inviata"
        with contextlib.suppress(discord.HTTPException):
            await interaction.message.edit(view=self)
        member = interaction.guild.get_member(self.applicant.id)
        if not member:
            return await interaction.response.send_message("❌ Impossibile identificarti.", ephemeral=True)
        await interaction.response.send_modal(JoinTeamModal(channel=self.channel, applicant=member))

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True


class PartnershipModal(discord.ui.Modal, title="🤝 Richiesta di Partnership"):
    server_name  = discord.ui.TextInput(label="Nome Server/Progetto",                           min_length=3,  max_length=100)
    invite_link  = discord.ui.TextInput(label="Link Invito / Sito Web",                         min_length=10, max_length=200)
    member_count = discord.ui.TextInput(label="N° approssimativo di membri/utenti",                            max_length=50)
    descrizione  = discord.ui.TextInput(label="Cosa offre il tuo server/progetto?",
                                        style=discord.TextStyle.paragraph, min_length=30, max_length=800)

    def __init__(self, channel: discord.TextChannel, applicant: discord.Member):
        super().__init__()
        self.channel   = channel
        self.applicant = applicant

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        embed = discord.Embed(
            title="🤝 Richiesta Partnership Ricevuta",
            color=discord.Color.teal(),
            timestamp=utcnow(),
        )
        embed.set_author(
            name=f"Richiesta da {self.applicant.display_name}",
            icon_url=self.applicant.display_avatar.url,
        )
        embed.add_field(name="👤 Richiedente", value=self.applicant.mention,  inline=True)
        embed.add_field(name="🏷️ Progetto",   value=self.server_name.value,  inline=True)
        embed.add_field(name="👥 Utenza",      value=self.member_count.value, inline=True)
        embed.add_field(name="🔗 Link",        value=self.invite_link.value,  inline=False)
        embed.add_field(name="📝 Descrizione", value=self.descrizione.value,  inline=False)
        embed.set_footer(text="Solo il Partner Manager può accettare o rifiutare.")

        partner_role = self.channel.guild.get_role(Config.STAFF_PARTNERSHIP_ROLE_ID)
        mention      = partner_role.mention if partner_role else "**@Partner Manager**"

        await self.channel.send(
            content=f"{mention} — nuova richiesta di partnership!",
            embed=embed,
            view=PartnershipReviewView(
                applicant=self.applicant,
                channel=self.channel,
                server_name=self.server_name.value,
                invite_link=self.invite_link.value,
                member_count=self.member_count.value,
                descrizione=self.descrizione.value,
            ),
            allowed_mentions=discord.AllowedMentions(roles=True),
        )
        await interaction.followup.send(
            "✅ Richiesta inviata! Lo staff la esaminerà a breve.", ephemeral=True
        )

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        log.exception("Errore in PartnershipModal: %s", error)
        msg = "❌ Errore imprevisto."
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)


class PartnershipReviewView(discord.ui.View):
    def __init__(
        self,
        applicant: discord.Member,
        channel: discord.TextChannel,
        server_name: str,
        invite_link: str,
        member_count: str,
        descrizione: str,
    ):
        super().__init__(timeout=None)
        self.applicant    = applicant
        self.channel      = channel
        self.server_name  = server_name
        self.invite_link  = invite_link
        self.member_count = member_count
        self.descrizione  = descrizione
        self._decided     = False

    async def _check_perm(self, interaction: discord.Interaction) -> bool:
        if is_partnership_staff(interaction.user):
            return True
        await interaction.response.send_message(
            "❌ Solo il **Partner Manager** può gestire le richieste.", ephemeral=True
        )
        return False

    @discord.ui.button(label="✅ ACCETTA", style=discord.ButtonStyle.success, custom_id="partnership_accept_v17")
    async def accept_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_perm(interaction) or self._decided:
            if self._decided:
                await interaction.response.send_message("⚠️ Già gestita.", ephemeral=True)
            return
        self._decided = True

        partner_role = interaction.guild.get_role(Config.ROLE_PARTNER_ID)
        role_msg     = ""
        if partner_role:
            ok, err  = await safe_add_role(self.applicant, partner_role)
            role_msg = f"✅ Ruolo {partner_role.mention} assegnato." if ok else f"⚠️ {err}"
        else:
            role_msg = f"⚠️ Ruolo Partner (ID `{Config.ROLE_PARTNER_ID}`) non configurato."

        for item in self.children:
            item.disabled = True  # type: ignore[attr-defined]
        await interaction.response.edit_message(view=self)

        await self.channel.send(
            embed=discord.Embed(
                title="🎉 Partnership Accettata!",
                description=(
                    f"Congratulazioni {self.applicant.mention}! 🥳\n"
                    f"Accettata da {interaction.user.mention}.\n\n{role_msg}\n\n"
                    "Benvenuto tra i nostri partner! 🤝"
                ),
                color=0x2ECC71, timestamp=utcnow(),
            ).set_footer(text=f"Gestita da {interaction.user}")
        )

        pub_channel = interaction.guild.get_channel(Config.PARTNERSHIP_CHANNEL_ID)
        if pub_channel:
            pub_embed = discord.Embed(
                title=f"🤝 Nuova Collaborazione: {self.server_name}",
                color=discord.Color.teal(),
                timestamp=utcnow(),
            )
            pub_embed.add_field(name="👤 Partner",     value=self.applicant.mention, inline=True)
            pub_embed.add_field(name="👥 Community",   value=self.member_count,      inline=True)
            pub_embed.add_field(name="🔗 Link",        value=self.invite_link,       inline=False)
            pub_embed.add_field(name="📝 Descrizione", value=self.descrizione,       inline=False)
            pub_embed.set_footer(
                text=f"Approvata da {interaction.user.display_name}",
                icon_url=interaction.user.display_avatar.url,
            )
            with contextlib.suppress(discord.HTTPException, discord.Forbidden):
                await pub_channel.send(
                    content=f"📢 **Nuova Partnership!** Benvenuto {self.applicant.mention}!",
                    embed=pub_embed,
                )

        with contextlib.suppress(discord.Forbidden, discord.HTTPException):
            await self.applicant.send(
                embed=discord.Embed(
                    title="🎉 Partnership Accettata!",
                    description=(
                        f"La tua richiesta per **{self.server_name}** su **{interaction.guild.name}** è stata accettata!\n\n{role_msg}"
                    ),
                    color=0x2ECC71, timestamp=utcnow(),
                )
            )
        await asyncio.sleep(5)
        ticket = await get_ticket(self.channel.id)
        if ticket and ticket["status"] == "open":
            await close_ticket(self.channel, interaction.user, interaction.guild, reason="Partnership accettata")

    @discord.ui.button(label="❌ RIFIUTA", style=discord.ButtonStyle.danger, custom_id="partnership_reject_v17")
    async def reject_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_perm(interaction) or self._decided:
            if self._decided:
                await interaction.response.send_message("⚠️ Già gestita.", ephemeral=True)
            return
        self._decided = True

        for item in self.children:
            item.disabled = True  # type: ignore[attr-defined]
        await interaction.response.edit_message(view=self)

        await self.channel.send(
            embed=discord.Embed(
                title="❌ Partnership Rifiutata",
                description=(
                    f"Ci dispiace {self.applicant.mention}, la richiesta per **{self.server_name}** "
                    "non soddisfa i nostri requisiti. Puoi riprovare in futuro."
                ),
                color=0xE74C3C, timestamp=utcnow(),
            ).set_footer(text=f"Gestita da {interaction.user}")
        )
        with contextlib.suppress(discord.Forbidden, discord.HTTPException):
            await self.applicant.send(
                embed=discord.Embed(
                    title="❌ Partnership Rifiutata",
                    description=f"La tua richiesta per **{self.server_name}** su **{interaction.guild.name}** è stata rifiutata.",
                    color=0xE74C3C, timestamp=utcnow(),
                )
            )
        await asyncio.sleep(3)
        ticket = await get_ticket(self.channel.id)
        if ticket and ticket["status"] == "open":
            await close_ticket(self.channel, interaction.user, interaction.guild, reason="Partnership rifiutata")


class PartnershipStartView(discord.ui.View):
    def __init__(self, applicant: discord.Member | discord.User, channel: discord.TextChannel):
        super().__init__(timeout=3600)
        self.applicant = applicant
        self.channel   = channel
        self._used     = False

    @discord.ui.button(
        label="🤝 Compila Richiesta Partnership",
        style=discord.ButtonStyle.blurple,
        custom_id="partnership_start_v17",
    )
    async def start_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.applicant.id:
            return await interaction.response.send_message(
                "❌ Solo il richiedente può compilare questo form.", ephemeral=True
            )
        if self._used:
            return await interaction.response.send_message("⚠️ Hai già inviato la richiesta.", ephemeral=True)
        self._used      = True
        button.disabled = True
        button.label    = "✅ Richiesta Inviata"
        with contextlib.suppress(discord.HTTPException):
            await interaction.message.edit(view=self)
        member = interaction.guild.get_member(self.applicant.id)
        if not member:
            return await interaction.response.send_message("❌ Impossibile identificarti.", ephemeral=True)
        await interaction.response.send_modal(PartnershipModal(channel=self.channel, applicant=member))

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True  # type: ignore[attr-defined]


# ══════════════════════════════════════════════════════════════════
# TICKET — VIEWS & MODALS
# ══════════════════════════════════════════════════════════════════
class RatingView(discord.ui.View):
    def __init__(self, channel_id: int, user_id: int):
        super().__init__(timeout=86400)
        self.channel_id = channel_id
        self.user_id    = user_id
        ts = int(utcnow_naive().timestamp())
        for i in range(1, 6):
            btn          = discord.ui.Button(
                label="⭐" * i,
                style=discord.ButtonStyle.secondary,
                custom_id=f"rate_{channel_id}_{i}_{ts}",
            )
            btn.callback = self._make_cb(i)
            self.add_item(btn)

    def _make_cb(self, score: int):
        async def cb(interaction: discord.Interaction):
            pool = get_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO ratings (channel_id, user_id, score)
                    VALUES ($1, $2, $3)
                    ON CONFLICT(channel_id) DO UPDATE SET score = EXCLUDED.score, rated_at = NOW()
                    """,
                    self.channel_id, self.user_id, score,
                )
            for item in self.children:
                item.disabled = True
            await interaction.response.edit_message(
                content=f"Grazie per la valutazione: {'⭐' * score}", view=self
            )
        return cb


class CategorySelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="1. Scegli la categoria...",
            options=[discord.SelectOption(label=c, value=c) for c in Config.CATEGORIE],
            custom_id="cat_select_v17",
        )

    async def callback(self, interaction: discord.Interaction):
        self.view.categoria = self.values[0]
        self.disabled       = True
        self.placeholder    = self.values[0]
        for item in self.view.children:
            if isinstance(item, PrioritySelect):
                item.disabled = False
        await interaction.response.edit_message(view=self.view)


class PrioritySelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="2. Scegli la priorità...",
            options=[
                discord.SelectOption(label=f"{Config.PRIORITY_ICONS[p]} {p}", value=p)
                for p in Config.PRIORITY_LEVELS
            ],
            custom_id="prio_select_v17",
            disabled=True,
        )

    async def callback(self, interaction: discord.Interaction):
        self.view.priority = self.values[0]
        self.disabled      = True
        self.placeholder   = self.values[0]
        for item in self.view.children:
            if isinstance(item, ConfirmButton):
                item.disabled = False
        await interaction.response.edit_message(view=self.view)


class ConfirmButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="Apri Ticket",
            style=discord.ButtonStyle.green,
            emoji="🎫",
            custom_id="confirm_open_v17",
            disabled=True,
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(
            TicketModal(self.view.categoria, self.view.priority)
        )


class TicketOpenView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        self.categoria: Optional[str] = None
        self.priority:  Optional[str] = None
        self.add_item(CategorySelect())
        self.add_item(PrioritySelect())
        self.add_item(ConfirmButton())


class TicketModal(discord.ui.Modal):
    mc_name = discord.ui.TextInput(
        label="Nickname Minecraft",
        placeholder="Es. Steve_123  (3–16 caratteri)",
        min_length=3, max_length=16,
    )
    oggetto = discord.ui.TextInput(
        label="Oggetto",
        placeholder="Riassumi il problema...",
        min_length=5, max_length=60,
    )
    descrizione = discord.ui.TextInput(
        label="Descrizione dettagliata",
        style=discord.TextStyle.long,
        placeholder="Più dettagli fornisci, prima risolviamo.",
        min_length=20, max_length=1000,
    )

    def __init__(self, categoria: str, priority: str):
        super().__init__(title=f"Ticket — {categoria[:35]}")
        self.categoria = categoria
        self.priority  = priority

    async def on_submit(self, interaction: discord.Interaction):
        user = interaction.user
        mc   = self.mc_name.value.strip()
        if not _MC_NAME_RE.match(mc):
            return await interaction.response.send_message(
                "❌ Nickname Minecraft non valido.", ephemeral=True
            )
        if await is_blacklisted(user.id):
            return await interaction.response.send_message("Sei nella blacklist.", ephemeral=True)
        remaining = await check_cooldown(user.id)
        if remaining > 0:
            return await interaction.response.send_message(
                f"Attendi ancora **{remaining}s**.", ephemeral=True
            )
        open_count = await count_open_tickets(user.id)
        if open_count >= Config.MAX_OPEN_TICKETS:
            return await interaction.response.send_message(
                f"Hai già **{open_count}** ticket aperti (max {Config.MAX_OPEN_TICKETS}).",
                ephemeral=True,
            )
        await interaction.response.defer(ephemeral=True)

        guild      = interaction.guild
        category   = guild.get_channel(Config.CATEGORY_GENERAL)
        staff_role = guild.get_role(Config.STAFF_TICKET_ROLE_ID)
        icon       = Config.PRIORITY_ICONS.get(self.priority, "")

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            user: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True),
        }
        if staff_role:
            overwrites[staff_role] = discord.PermissionOverwrite(
                read_messages=True, send_messages=True, manage_messages=True, attach_files=True,
            )

        if self.categoria == "Candidatura Staff":
            admin_role = guild.get_role(Config.ROLE_ADMIN_ID)
            if admin_role and admin_role not in overwrites:
                overwrites[admin_role] = discord.PermissionOverwrite(
                    read_messages=True, send_messages=True, manage_messages=True, attach_files=True,
                )
        if self.categoria == "Unisciti al Team":
            team_role_staff = guild.get_role(Config.STAFF_TEAM_ROLE_ID)
            if team_role_staff and team_role_staff not in overwrites:
                overwrites[team_role_staff] = discord.PermissionOverwrite(
                    read_messages=True, send_messages=True, manage_messages=True, attach_files=True,
                )
        if self.categoria == "Partnership":

            partner_mgr = guild.get_role(Config.STAFF_PARTNERSHIP_ROLE_ID)
            if partner_mgr and partner_mgr not in overwrites:
                overwrites[partner_mgr] = discord.PermissionOverwrite(
                    read_messages=True, send_messages=True, manage_messages=True, attach_files=True,
                )

        try:
            channel = await guild.create_text_channel(
                name=f"{icon}ticket-{user.name[:18]}",
                category=category,
                topic=f"Ticket di {user} | {self.categoria} | Priorità: {self.priority}",
                overwrites=overwrites,
            )
        except discord.HTTPException as e:
            log.error("Errore creazione canale ticket: %s", e)
            return await interaction.followup.send(
                "Impossibile creare il canale. Riprova o contatta un admin.", ephemeral=True
            )

        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO tickets (channel_id, user_id, categoria, priority) VALUES ($1, $2, $3, $4)",
                channel.id, user.id, self.categoria, self.priority,
            )

        await update_cooldown(user.id)

        color = Config.PRIORITY_COLORS.get(self.priority, 0x3498DB)
        embed = discord.Embed(title=f"Ticket: {self.categoria}", color=color, timestamp=utcnow())
        embed.set_author(name=str(user), icon_url=user.display_avatar.url)
        embed.add_field(name="Utente",         value=user.mention,              inline=True)
        embed.add_field(name="Categoria",      value=self.categoria,            inline=True)
        embed.add_field(name="Priorità",       value=f"{icon} {self.priority}", inline=True)
        embed.add_field(name="🎮 Nickname MC", value=f"`{mc}`",                 inline=True)
        embed.add_field(name="Oggetto",        value=self.oggetto.value,        inline=False)
        embed.add_field(name="Descrizione",    value=self.descrizione.value,    inline=False)
        embed.set_footer(text=f"User ID: {user.id}")

        ping_parts = [user.mention]
        if staff_role:
            ping_parts.append(staff_role.mention)

        await channel.send(
            content=" | ".join(ping_parts),
            embed=embed,
            view=TicketControlView(),
            allowed_mentions=discord.AllowedMentions(users=True, roles=True),
        )

        if self.priority == "Urgente" and staff_role:
            await channel.send(
                f"🚨 {staff_role.mention} — ticket **URGENTE** da gestire immediatamente!",
                allowed_mentions=discord.AllowedMentions(roles=True),
            )


        if self.categoria == "Candidatura Staff":
            await channel.send(
                embed=discord.Embed(
                    title="📋 Compila la candidatura",
                    description=f"{user.mention}, clicca il pulsante per compilare il modulo.",
                    color=discord.Color.blurple(), timestamp=utcnow(),
                ),
                view=StaffApplicationStartView(applicant=user, channel=channel),
            )
        elif self.categoria == "Unisciti al Team":
            await channel.send(
                embed=discord.Embed(
                    title="🎮 Compila la candidatura per il Team",
                    description=f"{user.mention}, clicca il pulsante per inserire età, motivazione e VIP su MetaMC.",
                    color=discord.Color.green(), timestamp=utcnow(),
                ),
                view=JoinTeamStartView(applicant=user, channel=channel),
            )
        elif self.categoria == "Partnership":

            await channel.send(
                embed=discord.Embed(
                    title="🤝 Compila la richiesta di Partnership",
                    description=f"{user.mention}, clicca il pulsante per compilare il modulo.",
                    color=discord.Color.teal(), timestamp=utcnow(),
                ),
                view=PartnershipStartView(applicant=user, channel=channel),
            )

        await interaction.followup.send(f"Ticket aperto in {channel.mention}", ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        log.error("Errore modal ticket: %s", error, exc_info=True)
        msg = "Errore imprevisto. Riprova o contatta un amministratore."
        if not interaction.response.is_done():
            await interaction.response.send_message(msg, ephemeral=True)
        else:
            await interaction.followup.send(msg, ephemeral=True)


class StaffApplicationStartView(discord.ui.View):
    def __init__(self, applicant: discord.Member | discord.User, channel: discord.TextChannel):
        super().__init__(timeout=3600)
        self.applicant = applicant
        self.channel   = channel
        self._used     = False

    @discord.ui.button(
        label="📋 Compila Candidatura",
        style=discord.ButtonStyle.blurple,
        custom_id="staff_app_start_v17",
    )
    async def start_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.applicant.id:
            return await interaction.response.send_message(
                "❌ Solo il candidato può compilare questo form.", ephemeral=True
            )
        if self._used:
            return await interaction.response.send_message("⚠️ Hai già compilato la candidatura.", ephemeral=True)
        self._used      = True
        button.disabled = True
        button.label    = "✅ Candidatura Inviata"
        with contextlib.suppress(discord.HTTPException):
            await interaction.message.edit(view=self)
        member = interaction.guild.get_member(self.applicant.id)
        if not member:
            return await interaction.response.send_message("❌ Impossibile identificarti.", ephemeral=True)
        await interaction.response.send_modal(StaffApplicationModal(channel=self.channel, applicant=member))

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True  # type: ignore[attr-defined]


class TicketAssignModal(discord.ui.Modal, title="📋 Assegna Ticket"):
    nota_interna = discord.ui.TextInput(
        label="Nota interna per lo staff",
        style=discord.TextStyle.paragraph,
        placeholder="Contesto o istruzioni riservate...",
        min_length=5, max_length=500,
    )
    commento_canale = discord.ui.TextInput(
        label="Commento pubblico nel canale (opzionale)",
        style=discord.TextStyle.paragraph,
        placeholder="Lascia vuoto per non postare nulla.",
        max_length=400, required=False,
    )

    def __init__(self, staff_member: discord.Member, ticket: dict, previous_claimer_id: Optional[int]):
        super().__init__()
        self.staff_member        = staff_member
        self.ticket              = ticket
        self.previous_claimer_id = previous_claimer_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        commento = self.commento_canale.value.strip() if self.commento_canale.value else ""

        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE tickets SET claimed_by = $1 WHERE channel_id = $2",
                self.staff_member.id, interaction.channel.id,
            )
            await conn.execute(
                """
                INSERT INTO ticket_stats (staff_id, claimed_count) VALUES ($1, 1)
                ON CONFLICT(staff_id) DO UPDATE SET claimed_count = ticket_stats.claimed_count + 1
                """,
                self.staff_member.id,
            )

        with contextlib.suppress(discord.HTTPException):
            await interaction.channel.set_permissions(
                self.staff_member,
                read_messages=True, send_messages=True,
                manage_messages=True, attach_files=True,
            )

        prev_text = f"<@{self.previous_claimer_id}>" if self.previous_claimer_id else "*(nessuno)*"
        embed = discord.Embed(title="🔄 Ticket Riassegnato", color=0x5865F2, timestamp=utcnow())
        embed.add_field(name="Assegnato da", value=interaction.user.mention,  inline=True)
        embed.add_field(name="Assegnato a",  value=self.staff_member.mention, inline=True)
        embed.add_field(name="Precedente",   value=prev_text,                 inline=True)
        if commento:
            embed.add_field(name="💬 Commento", value=commento, inline=False)

        await interaction.response.send_message(
            content=f"{self.staff_member.mention} sei stato assegnato a questo ticket.",
            embed=embed,
        )

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        log.exception("Errore in TicketAssignModal: %s", error)
        msg = "❌ Errore imprevisto durante l'assegnazione."
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)


class TicketControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Prendi in carico", style=discord.ButtonStyle.blurple, emoji="🙋", custom_id="claim_v17")
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_ticket_staff(interaction.user):
            return await interaction.response.send_message("Solo lo staff ticket.", ephemeral=True)
        ticket = await get_ticket(interaction.channel.id)
        if ticket and ticket.get("claimed_by"):
            return await interaction.response.send_message(
                f"Ticket già in carico a <@{ticket['claimed_by']}>.", ephemeral=True
            )
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE tickets SET claimed_by=$1 WHERE channel_id=$2",
                interaction.user.id, interaction.channel.id,
            )
            await conn.execute(
                """
                INSERT INTO ticket_stats (staff_id, claimed_count) VALUES ($1, 1)
                ON CONFLICT(staff_id) DO UPDATE SET claimed_count = ticket_stats.claimed_count + 1
                """,
                interaction.user.id,
            )
        button.disabled = True
        button.label    = f"In gestione da {interaction.user.display_name}"
        button.emoji    = None
        await interaction.response.edit_message(view=self)
        await interaction.channel.send(
            embed=discord.Embed(
                description=f"🙋 {interaction.user.mention} ha preso in carico questo ticket.",
                color=0x3498DB,
            )
        )

    @discord.ui.button(label="Chiudi Ticket", style=discord.ButtonStyle.danger, emoji="🔒", custom_id="close_v17")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_ticket_staff(interaction.user):
            return await interaction.response.send_message("Solo lo staff ticket.", ephemeral=True)
        await interaction.response.send_modal(CloseReasonModal())

    @discord.ui.button(label="Aggiungi Utente", style=discord.ButtonStyle.secondary, emoji="➕", custom_id="adduser_v17")
    async def add_user(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_ticket_staff(interaction.user):
            return await interaction.response.send_message("Solo lo staff ticket.", ephemeral=True)
        await interaction.response.send_modal(AddUserModal())

    @discord.ui.button(label="Cambia Priorità", style=discord.ButtonStyle.secondary, emoji="🚦", custom_id="chprio_v17")
    async def change_priority(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_ticket_staff(interaction.user):
            return await interaction.response.send_message("Solo lo staff ticket.", ephemeral=True)
        await interaction.response.send_message(
            "Seleziona la nuova priorità:",
            view=ChangePriorityView(interaction.channel.id),
            ephemeral=True,
        )


class CloseReasonModal(discord.ui.Modal, title="Chiudi Ticket"):
    motivo = discord.ui.TextInput(
        label="Motivo di chiusura",
        placeholder="Es: Problema risolto, nessuna risposta...",
        max_length=200, required=False,
    )

    async def on_submit(self, interaction: discord.Interaction):
        ticket = await get_ticket(interaction.channel.id)
        if not ticket or ticket["status"] not in ("open",):
            return await interaction.response.send_message(
                "❌ Ticket già in chiusura o già chiuso.", ephemeral=True
            )
        await interaction.response.defer()
        await close_ticket(
            interaction.channel, interaction.user, interaction.guild,
            reason=self.motivo.value or "Nessun motivo specificato",
        )


class AddUserModal(discord.ui.Modal, title="Aggiungi Utente al Ticket"):
    user_id_input = discord.ui.TextInput(
        label="User ID",
        placeholder="Es: 123456789012345678",
        max_length=20,
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            uid    = int(self.user_id_input.value.strip())
            member = interaction.guild.get_member(uid) or await interaction.guild.fetch_member(uid)
        except (ValueError, discord.NotFound):
            return await interaction.response.send_message("Utente non trovato.", ephemeral=True)
        await interaction.channel.set_permissions(
            member, read_messages=True, send_messages=True, attach_files=True
        )
        await interaction.response.send_message(f"{member.mention} aggiunto al ticket.")


class ChangePriorityView(discord.ui.View):
    def __init__(self, channel_id: int):
        super().__init__(timeout=60)
        self.channel_id = channel_id
        sel             = discord.ui.Select(
            placeholder="Nuova priorità...",
            options=[
                discord.SelectOption(label=f"{Config.PRIORITY_ICONS[p]} {p}", value=p)
                for p in Config.PRIORITY_LEVELS
            ],
        )
        sel.callback = self._cb
        self.add_item(sel)

    async def _cb(self, interaction: discord.Interaction):
        ticket = await get_ticket(self.channel_id)
        if not ticket or ticket["status"] not in ("open", "closing"):
            return await interaction.response.edit_message(
                content="❌ Ticket già chiuso.", view=None
            )
        new_prio = interaction.data["values"][0]
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE tickets SET priority=$1 WHERE channel_id=$2", new_prio, self.channel_id
            )
        icon = Config.PRIORITY_ICONS.get(new_prio, "")
        await interaction.response.edit_message(
            content=f"Priorità aggiornata a **{icon} {new_prio}**", view=None
        )
        await interaction.channel.send(
            embed=discord.Embed(
                description=f"🚦 Priorità cambiata a **{icon} {new_prio}** da {interaction.user.mention}",
                color=Config.PRIORITY_COLORS.get(new_prio, 0xF39C12),
            )
        )


class MainPersistentView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Apri un Ticket",
        style=discord.ButtonStyle.green,
        custom_id="main_open_v17",
        emoji="🎫",
    )
    async def open_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await is_blacklisted(interaction.user.id):
            return await interaction.response.send_message("Sei nella blacklist.", ephemeral=True)
        remaining = await check_cooldown(interaction.user.id)
        if remaining > 0:
            return await interaction.response.send_message(
                f"Attendi ancora **{remaining}s**.", ephemeral=True
            )
        open_count = await count_open_tickets(interaction.user.id)
        if open_count >= Config.MAX_OPEN_TICKETS:
            return await interaction.response.send_message(
                f"Hai già **{open_count}** ticket aperti (max {Config.MAX_OPEN_TICKETS}).",
                ephemeral=True,
            )
        await interaction.response.send_message(
            "**Apri un nuovo ticket**\nSeleziona categoria e priorità:",
            view=TicketOpenView(),
            ephemeral=True,
        )


# ══════════════════════════════════════════════════════════════════
# ANNUNCIO — MODAL
# ══════════════════════════════════════════════════════════════════
class AnnuncioModal(discord.ui.Modal, title="📢 Crea Annuncio"):
    titolo         = discord.ui.TextInput(label="Titolo",                                            min_length=3,  max_length=100)
    messaggio      = discord.ui.TextInput(label="Messaggio", style=discord.TextStyle.long,           min_length=5,  max_length=2000)
    menzione_extra = discord.ui.TextInput(label="Menzione iniziale (opzionale)",
                                          placeholder="Es: @everyone  oppure  @here",
                                          required=False, max_length=50)

    def __init__(self, canale: discord.TextChannel, colore: int):
        super().__init__()
        self.canale = canale
        self.colore = colore

    async def on_submit(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title=self.titolo.value,
            description=self.messaggio.value,
            color=self.colore,
            timestamp=utcnow(),
        )
        embed.set_author(
            name=f"Annuncio da {interaction.user.display_name}",
            icon_url=interaction.user.display_avatar.url,
        )
        embed.set_footer(
            text=interaction.guild.name,
            icon_url=interaction.guild.icon.url if interaction.guild.icon else None,
        )
        menzione = self.menzione_extra.value.strip() if self.menzione_extra.value else ""
        try:
            await self.canale.send(
                content=menzione or None,
                embed=embed,
                allowed_mentions=discord.AllowedMentions(everyone=True, roles=True, users=True),
            )
        except discord.Forbidden:
            return await interaction.response.send_message(
                f"❌ Non ho i permessi per scrivere in {self.canale.mention}.", ephemeral=True
            )
        await interaction.response.send_message(
            f"✅ Annuncio inviato in {self.canale.mention}!", ephemeral=True
        )

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        log.exception("Errore in AnnuncioModal: %s", error)
        msg = "❌ Errore imprevisto."
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)


# ══════════════════════════════════════════════════════════════════
# SONDAGGI — VIEW & EMBED
# ══════════════════════════════════════════════════════════════════
def _build_poll_embed(poll: dict, options: list[dict], closed: bool = False) -> discord.Embed:
    total_votes = sum(o["votes"] for o in options)
    embed       = discord.Embed(
        title=f"{'🔒' if closed else '📊'} {poll['question']}",
        color=discord.Color.greyple() if closed else discord.Color.blurple(),
        timestamp=utcnow(),
    )
    bar_len = 12
    lines   = []
    for o in options:
        pct    = (o["votes"] / total_votes * 100) if total_votes > 0 else 0
        filled = int(pct / 100 * bar_len)
        bar    = "█" * filled + "░" * (bar_len - filled)
        lines.append(f"**{o['label']}**\n`{bar}` {pct:.1f}% ({o['votes']} voti)")
    embed.description = "\n\n".join(lines) if lines else "*Nessuna opzione.*"
    embed.set_footer(text=f"{'Sondaggio chiuso' if closed else 'Vota!'} • Totale: {total_votes}")
    return embed


class PollView(discord.ui.View):
    def __init__(self, poll_id: str, options: list[dict]):
        super().__init__(timeout=None)
        self.poll_id = poll_id
        EMOJIS       = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
        for i, opt in enumerate(options):
            btn = discord.ui.Button(
                label=opt["label"][:40],
                emoji=EMOJIS[i] if i < len(EMOJIS) else "▶",
                style=discord.ButtonStyle.secondary,
                custom_id=f"poll_vote_{poll_id[:8]}_{opt['id']}",
            )
            btn.callback = self._make_vote_cb(opt["id"])
            self.add_item(btn)

    def _make_vote_cb(self, option_id: int):
        async def cb(interaction: discord.Interaction):
            poll = await db_get_poll(self.poll_id)
            if not poll or not poll["active"]:
                return await interaction.response.send_message(
                    "❌ Questo sondaggio è già chiuso.", ephemeral=True
                )
            ok, msg = await db_vote_poll(self.poll_id, option_id, interaction.user.id)
            options = await db_get_poll_options(self.poll_id)
            embed   = _build_poll_embed(poll, options)
            with contextlib.suppress(discord.HTTPException):
                await interaction.message.edit(embed=embed)
            await interaction.response.send_message(
                f"✅ {msg}" if ok else f"ℹ️ {msg}", ephemeral=True
            )
        return cb


# ══════════════════════════════════════════════════════════════════
# GIVEAWAY — VIEWS & MODALS
# ══════════════════════════════════════════════════════════════════
class GiveawayModal(discord.ui.Modal, title="Crea un Giveaway"):
    g_title       = discord.ui.TextInput(label="Titolo",          max_length=100)
    g_description = discord.ui.TextInput(label="Descrizione",     style=discord.TextStyle.paragraph, required=False, max_length=500)
    g_prize       = discord.ui.TextInput(label="Premio",          max_length=200)
    g_winners     = discord.ui.TextInput(label="N° vincitori",    default="1", max_length=2)
    g_minutes     = discord.ui.TextInput(label="Durata (minuti)", max_length=5)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            winners = int(self.g_winners.value)
            minutes = int(self.g_minutes.value)
        except ValueError:
            return await interaction.response.send_message("❌ Inserisci numeri validi.", ephemeral=True)
        if not (1 <= winners <= 50):
            return await interaction.response.send_message("❌ Vincitori: tra 1 e 50.", ephemeral=True)
        if not (1 <= minutes <= 525_600):
            return await interaction.response.send_message("❌ Durata: tra 1 e 525600 minuti.", ephemeral=True)

        g_id, end_time = await db_create_giveaway(
            title=self.g_title.value,
            description=self.g_description.value or "",
            channel_id=interaction.channel_id,
            creator_id=interaction.user.id,
            prize=self.g_prize.value,
            winners=winners,
            minutes=minutes,
        )
        embed = build_giveaway_embed(
            title=self.g_title.value,
            description=self.g_description.value or "",
            prize=self.g_prize.value,
            end_time=end_time,
            winners=winners,
            entry_count=0,
        )
        view = GiveawayView(g_id)
        await interaction.response.send_message(embed=embed, view=view)
        msg = await interaction.original_response()
        await db_set_message_id(g_id, msg.id)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        log.exception("Errore in GiveawayModal: %s", error)
        msg = "❌ Errore imprevisto."
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)


class GiveawayView(discord.ui.View):
    def __init__(self, giveaway_id: Optional[str]):
        super().__init__(timeout=None)
        self.giveaway_id = giveaway_id

    async def _resolve_giveaway_id(self, interaction: discord.Interaction) -> Optional[str]:
        if self.giveaway_id:
            g = await db_get_giveaway(self.giveaway_id)
            if g:
                return self.giveaway_id

        if interaction.message:
            pool = get_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT id FROM giveaways WHERE message_id = $1", interaction.message.id
                )
            if row:
                self.giveaway_id = row["id"]
                return self.giveaway_id

        if not interaction.response.is_done():
            await interaction.response.send_message(
                "❌ Impossibile identificare il giveaway.", ephemeral=True
            )
        return None

    @discord.ui.button(label="🎟️ Partecipa", style=discord.ButtonStyle.success, custom_id="giveaway:join")
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        g_id = await self._resolve_giveaway_id(interaction)
        if g_id is None:
            return
        g = await db_get_giveaway(g_id)
        if not g or not g["active"]:
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Giveaway non più attivo.", ephemeral=True)
            return

        req_role_id = g.get("required_role_id")
        if req_role_id:
            member = interaction.guild.get_member(interaction.user.id)
            if member and not member.get_role(req_role_id):
                return await interaction.response.send_message(
                    f"❌ Devi avere il ruolo <@&{req_role_id}> per partecipare.", ephemeral=True
                )

        added = await db_add_entry(g_id, interaction.user.id)
        count = await db_entry_count(g_id)
        if added:
            await interaction.response.send_message(
                f"✅ Sei iscritto! Partecipanti: **{count}**", ephemeral=True
            )
            await refresh_giveaway_embed(interaction.client, g_id, count)
        else:
            leave_view = LeaveView(g_id)
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "ℹ️ Sei già iscritto. Vuoi rimuovere la tua partecipazione?",
                    view=leave_view, ephemeral=True,
                )
                leave_view._message = await interaction.original_response()

    @discord.ui.button(label="👥 Partecipanti", style=discord.ButtonStyle.secondary, custom_id="giveaway:count")
    async def show_count(self, interaction: discord.Interaction, button: discord.ui.Button):
        g_id = await self._resolve_giveaway_id(interaction)
        if g_id is None:
            return
        count = await db_entry_count(g_id)
        if not interaction.response.is_done():
            await interaction.response.send_message(
                f"👥 Ci sono **{count}** partecipanti.", ephemeral=True
            )


class LeaveView(discord.ui.View):
    def __init__(self, giveaway_id: str):
        super().__init__(timeout=120)
        self.giveaway_id = giveaway_id
        self._message: Optional[discord.Message] = None

    @discord.ui.button(label="Rimuovi iscrizione", style=discord.ButtonStyle.danger)
    async def leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        g = await db_get_giveaway(self.giveaway_id)
        if not g or not g["active"]:
            return await interaction.response.edit_message(content="❌ Giveaway già terminato.", view=None)
        removed = await db_remove_entry(self.giveaway_id, interaction.user.id)
        count   = await db_entry_count(self.giveaway_id)
        await interaction.response.edit_message(
            content="✅ Iscrizione rimossa." if removed else "❌ Non eri iscritto.", view=None,
        )
        if removed:
            await refresh_giveaway_embed(interaction.client, self.giveaway_id, count)

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True  # type: ignore[attr-defined]
        if self._message:
            with contextlib.suppress(discord.HTTPException):
                await self._message.edit(view=self)


# ══════════════════════════════════════════════════════════════════
# COG — TEAM
# ══════════════════════════════════════════════════════════════════
class TeamCog(commands.Cog):
    def __init__(self, bot: "CombinedBot"):
        self.bot = bot

    @app_commands.command(name="add_member", description="[Staff Team] Aggiunge un membro al team")
    @team_staff_check()
    @app_commands.guild_only()
    async def add_member(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(AddMemberModal())

    @app_commands.command(name="remove_member", description="[Staff Team] Rimuove un membro dal team")
    @team_staff_check()
    @app_commands.describe(member="Il membro Discord da rimuovere")
    @app_commands.guild_only()
    async def remove_member(self, interaction: discord.Interaction, member: discord.Member) -> None:
        if not await db_delete_member(member.id):
            return await interaction.response.send_message(
                f"⚠️ {member.mention} non è nel database del team.", ephemeral=True
            )
        role = await get_team_role(interaction.guild)
        role_removed, role_err = False, "Ruolo non configurato."
        if role and role in member.roles:
            role_removed, role_err = await safe_remove_role(member, role)
        embed = discord.Embed(
            title="🗑️ Membro Rimosso",
            description=(
                f"**Discord:** {member.mention}\n"
                f"**Ruolo rimosso:** {'✅' if role_removed else f'⚠️ {role_err}'}"
            ),
            color=discord.Color.red() if role_removed else discord.Color.orange(),
        )
        embed.set_footer(text=f"Rimosso da {interaction.user}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="list_members", description="Mostra la lista dei membri del team")
    @app_commands.guild_only()
    async def list_members(self, interaction: discord.Interaction) -> None:
        rows = await db_get_all_members()
        if not rows:
            return await interaction.response.send_message("📭 Il team è vuoto.", ephemeral=True)
        view = MemberListView(rows, interaction.guild, interaction.user)
        await interaction.response.send_message(embed=view._build_embed(), view=view, ephemeral=True)
        view._message = await interaction.original_response()

    @app_commands.command(name="mc_lookup", description="[Staff Team] Cerca membro Discord dal nickname MC")
    @team_staff_check()
    @app_commands.describe(mc_name="Nickname Minecraft da cercare")
    @app_commands.guild_only()
    async def mc_lookup(self, interaction: discord.Interaction, mc_name: str) -> None:
        discord_id = await db_find_by_mc(mc_name.strip())
        if discord_id is None:
            return await interaction.response.send_message(
                f"🔍 Nessun membro con nickname `{mc_name}`.", ephemeral=True
            )
        member  = interaction.guild.get_member(discord_id)
        display = member.mention if member else f"*(non nel server — ID: {discord_id})*"
        embed   = discord.Embed(
            title="🔍 Risultato Ricerca",
            description=f"**Minecraft:** `{mc_name}`\n**Discord:** {display}",
            color=discord.Color.blurple(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


# ══════════════════════════════════════════════════════════════════
# COG — TICKET
# ══════════════════════════════════════════════════════════════════
class TicketCog(commands.Cog):
    def __init__(self, bot: "CombinedBot"):
        self.bot = bot
        self.auto_close_task.start()

    def cog_unload(self):
        self.auto_close_task.cancel()

    @app_commands.command(name="ticket_setup", description="[Admin] Invia l'embed per aprire i ticket")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    async def ticket_setup(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="Centro Supporto",
            description=(
                "Hai bisogno di assistenza? Clicca il pulsante qui sotto.\n\n"
                "**Come funziona:**\n"
                "1️⃣ Scegli la categoria del problema\n"
                "2️⃣ Seleziona la priorità\n"
                "3️⃣ Inserisci i dettagli\n\n"
                "📋 **Candidatura Staff?** Seleziona la categoria apposita!\n"
                "🤝 **Partnership?** Seleziona la categoria Partnership!"
            ),
            color=discord.Color.blue(),
            timestamp=utcnow(),
        )
        embed.set_footer(text="Sistema Ticket Automatizzato")
        await interaction.channel.send(embed=embed, view=MainPersistentView())
        await interaction.response.send_message("Embed inviato!", ephemeral=True)

    @app_commands.command(name="ticket_ban", description="[Staff Ticket] Aggiunge un utente alla blacklist")
    @app_commands.guild_only()
    @ticket_staff_check()
    @app_commands.describe(utente="L'utente da bannare", motivo="Motivo")
    async def ticket_ban(self, interaction: discord.Interaction, utente: discord.Member, motivo: Optional[str] = "Nessun motivo specificato"):
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO blacklist (user_id, reason, added_by) VALUES ($1, $2, $3)
                ON CONFLICT(user_id) DO UPDATE SET reason = EXCLUDED.reason, added_by = EXCLUDED.added_by
                """,
                utente.id, motivo, interaction.user.id,
            )
        embed = discord.Embed(title="🚫 Aggiunto alla blacklist", color=0xE74C3C, timestamp=utcnow())
        embed.add_field(name="Utente",     value=utente.mention,          inline=True)
        embed.add_field(name="Aggiunto da", value=interaction.user.mention, inline=True)
        embed.add_field(name="Motivo",     value=motivo,                  inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="ticket_unban", description="[Staff Ticket] Rimuove un utente dalla blacklist")
    @app_commands.guild_only()
    @ticket_staff_check()
    @app_commands.describe(utente="L'utente da sbannare")
    async def ticket_unban(self, interaction: discord.Interaction, utente: discord.Member):
        pool = get_pool()
        async with pool.acquire() as conn:
            result = await conn.execute("DELETE FROM blacklist WHERE user_id = $1", utente.id)
        removed = result.split()[-1] != "0"
        if removed:
            await interaction.response.send_message(f"✅ {utente.mention} rimosso dalla blacklist.")
        else:
            await interaction.response.send_message(f"ℹ️ {utente.mention} non era in blacklist.", ephemeral=True)

    @app_commands.command(name="ticket_list", description="[Staff Ticket] Mostra tutti i ticket aperti")
    @app_commands.guild_only()
    @ticket_staff_check()
    @app_commands.describe(categoria="Filtra per categoria", priorita="Filtra per priorità")
    async def ticket_list(self, interaction: discord.Interaction, categoria: Optional[str] = None, priorita: Optional[str] = None):
        conditions = ["status IN ('open', 'closing')"]
        params: list = []
        idx = 1
        if categoria:
            conditions.append(f"categoria = ${idx}")
            params.append(categoria)
            idx += 1
        if priorita:
            conditions.append(f"priority = ${idx}")
            params.append(priorita)
            idx += 1
        query = (
            "SELECT channel_id, user_id, categoria, priority, opened_at, claimed_by "
            "FROM tickets WHERE " + " AND ".join(conditions) + " ORDER BY opened_at"
        )

        pool = get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(query, *params)

        if not rows:
            return await interaction.response.send_message("Nessun ticket aperto.", ephemeral=True)
        embed = discord.Embed(title=f"Ticket aperti — {len(rows)} totali", color=0x3498DB, timestamp=utcnow())
        for row in rows[:20]:
            icon      = Config.PRIORITY_ICONS.get(row["priority"], "")
            claim_txt = f"In carico a <@{row['claimed_by']}>" if row["claimed_by"] else "Non assegnato"
            opened_str = row["opened_at"].strftime("%Y-%m-%d %H:%M") if row["opened_at"] else "N/D"
            embed.add_field(
                name=f"{icon} {row['priority']} | <#{row['channel_id']}>",
                value=f"<@{row['user_id']}> • {row['categoria']}\n{opened_str} • {claim_txt}",
                inline=False,
            )
        if len(rows) > 20:
            embed.set_footer(text=f"Mostrando 20 di {len(rows)} ticket")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ticket_list.autocomplete("categoria")
    async def ac_categoria(self, interaction: discord.Interaction, current: str):
        return [app_commands.Choice(name=c, value=c) for c in Config.CATEGORIE if current.lower() in c.lower()]

    @ticket_list.autocomplete("priorita")
    async def ac_priorita(self, interaction: discord.Interaction, current: str):
        return [app_commands.Choice(name=p, value=p) for p in Config.PRIORITY_LEVELS if current.lower() in p.lower()]

    @app_commands.command(name="ticket_stats", description="[Staff Ticket] Statistiche del sistema ticket")
    @app_commands.guild_only()
    @ticket_staff_check()
    async def ticket_stats(self, interaction: discord.Interaction):
        pool = get_pool()
        async with pool.acquire() as conn:
            staff_rows  = await conn.fetch(
                "SELECT staff_id, closed_count, claimed_count FROM ticket_stats ORDER BY closed_count DESC LIMIT 10"
            )
            rating_row  = await conn.fetchrow("SELECT AVG(score), COUNT(*) FROM ratings")
            open_count  = await conn.fetchval(
                "SELECT COUNT(*) FROM tickets WHERE status IN ('open', 'closing')"
            )
            closed_total = await conn.fetchval(
                "SELECT COUNT(*) FROM tickets WHERE status = 'closed'"
            )

        avg_rating    = round(float(rating_row[0] or 0), 1)
        total_ratings = rating_row[1]
        embed = discord.Embed(title="📊 Statistiche Ticket", color=0xF39C12, timestamp=utcnow())
        embed.add_field(name="Ticket aperti",     value=str(open_count),   inline=True)
        embed.add_field(name="Ticket chiusi",     value=str(closed_total), inline=True)
        embed.add_field(
            name="Valutazione media",
            value=f"{'★' * round(avg_rating)}{'☆' * (5 - round(avg_rating))} {avg_rating}/5 ({total_ratings} voti)",
            inline=True,
        )
        if staff_rows:
            lines = [
                f"`{i+1}.` <@{r['staff_id']}> — chiusi: **{r['closed_count']}** | presi: **{r['claimed_count']}**"
                for i, r in enumerate(staff_rows)
            ]
            embed.add_field(name="Top Staff", value="\n".join(lines), inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="ticket_close", description="[Staff Ticket] Chiude il ticket corrente")
    @app_commands.guild_only()
    @ticket_staff_check()
    @app_commands.describe(motivo="Motivo della chiusura")
    async def ticket_close(self, interaction: discord.Interaction, motivo: Optional[str] = "Nessun motivo specificato"):
        ticket = await get_ticket(interaction.channel.id)
        if not ticket or ticket["status"] not in ("open",):
            return await interaction.response.send_message(
                "Questo canale non è un ticket aperto.", ephemeral=True
            )
        await interaction.response.send_message(
            f"⏳ Avvio chiusura... Motivo: *{motivo}*", ephemeral=True
        )
        await close_ticket(interaction.channel, interaction.user, interaction.guild, reason=motivo)

    @app_commands.command(name="ticket_forceclose", description="[Admin] Forza la chiusura immediata del ticket")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(motivo="Motivo della chiusura forzata")
    async def ticket_forceclose(self, interaction: discord.Interaction, motivo: Optional[str] = "Chiusura forzata"):
        ticket = await get_ticket(interaction.channel.id)
        if not ticket:
            return await interaction.response.send_message("Questo canale non è un ticket.", ephemeral=True)
        task = _ticket_close_tasks.pop(interaction.channel.id, None)
        if task and not task.done():
            task.cancel()
        await interaction.response.send_message("⚡ Chiusura forzata in corso...")
        await _do_archive_ticket(interaction.channel, interaction.user, interaction.guild, force=True, reason=motivo)

    @app_commands.command(name="ticket_claim", description="[Staff Ticket] Prendi in carico il ticket")
    @app_commands.guild_only()
    @ticket_staff_check()
    async def ticket_claim(self, interaction: discord.Interaction):
        ticket = await get_ticket(interaction.channel.id)
        if not ticket:
            return await interaction.response.send_message("Questo canale non è un ticket.", ephemeral=True)
        if ticket.get("claimed_by"):
            return await interaction.response.send_message(
                f"Ticket già in carico a <@{ticket['claimed_by']}>.", ephemeral=True
            )
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE tickets SET claimed_by=$1 WHERE channel_id=$2",
                interaction.user.id, interaction.channel.id,
            )
            await conn.execute(
                """
                INSERT INTO ticket_stats (staff_id, claimed_count) VALUES ($1, 1)
                ON CONFLICT(staff_id) DO UPDATE SET claimed_count = ticket_stats.claimed_count + 1
                """,
                interaction.user.id,
            )
        await interaction.response.send_message(
            embed=discord.Embed(
                description=f"🙋 {interaction.user.mention} ha preso in carico questo ticket.",
                color=0x3498DB,
            )
        )

    @app_commands.command(name="ticket_assign", description="[Staff Ticket] Assegna il ticket a uno staff")
    @app_commands.guild_only()
    @ticket_staff_check()
    @app_commands.describe(staff_member="Il membro dello staff a cui assegnare il ticket")
    async def ticket_assign(self, interaction: discord.Interaction, staff_member: discord.Member) -> None:
        ticket = await get_ticket(interaction.channel.id)
        if not ticket:
            return await interaction.response.send_message("❌ Questo canale non è un ticket.", ephemeral=True)
        if not is_ticket_staff(staff_member):
            return await interaction.response.send_message(
                f"❌ {staff_member.mention} non è staff ticket.", ephemeral=True
            )
        if staff_member.id == interaction.user.id:
            return await interaction.response.send_message(
                "⚠️ Non puoi assegnare a te stesso. Usa /ticket_claim.", ephemeral=True
            )
        await interaction.response.send_modal(
            TicketAssignModal(
                staff_member=staff_member,
                ticket=ticket,
                previous_claimer_id=ticket.get("claimed_by"),
            )
        )

    @app_commands.command(name="ticket_add", description="[Staff Ticket] Aggiunge un utente al ticket")
    @app_commands.guild_only()
    @ticket_staff_check()
    @app_commands.describe(utente="Utente da aggiungere")
    async def ticket_add(self, interaction: discord.Interaction, utente: discord.Member):
        if not await get_ticket(interaction.channel.id):
            return await interaction.response.send_message("Questo canale non è un ticket.", ephemeral=True)
        await interaction.channel.set_permissions(utente, read_messages=True, send_messages=True, attach_files=True)
        await interaction.response.send_message(f"✅ {utente.mention} aggiunto al ticket.")

    @app_commands.command(name="ticket_remove", description="[Staff Ticket] Rimuove un utente dal ticket")
    @app_commands.guild_only()
    @ticket_staff_check()
    @app_commands.describe(utente="Utente da rimuovere")
    async def ticket_remove(self, interaction: discord.Interaction, utente: discord.Member):
        if not await get_ticket(interaction.channel.id):
            return await interaction.response.send_message("Questo canale non è un ticket.", ephemeral=True)
        await interaction.channel.set_permissions(utente, overwrite=None)
        await interaction.response.send_message(f"✅ {utente.mention} rimosso dal ticket.")

    @app_commands.command(name="ticket_info", description="Mostra le info del ticket corrente")
    @app_commands.guild_only()
    async def ticket_info(self, interaction: discord.Interaction):
        ticket = await get_ticket(interaction.channel.id)
        if not ticket:
            return await interaction.response.send_message("Questo canale non è un ticket.", ephemeral=True)
        icon  = Config.PRIORITY_ICONS.get(ticket["priority"], "")
        color = Config.PRIORITY_COLORS.get(ticket["priority"], 0x3498DB)
        embed = discord.Embed(title="📋 Info Ticket", color=color, timestamp=utcnow())
        opened_str = ticket["opened_at"].strftime("%Y-%m-%d %H:%M") if ticket["opened_at"] else "N/D"
        embed.add_field(name="Utente",      value=f"<@{ticket['user_id']}>",                                              inline=True)
        embed.add_field(name="Categoria",   value=ticket["categoria"],                                                    inline=True)
        embed.add_field(name="Priorità",    value=f"{icon} {ticket['priority']}",                                         inline=True)
        embed.add_field(name="Stato",       value=ticket["status"].capitalize(),                                          inline=True)
        embed.add_field(name="Aperto il",   value=opened_str,                                                             inline=True)
        embed.add_field(name="In carico a", value=f"<@{ticket['claimed_by']}>" if ticket["claimed_by"] else "Non assegnato", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="ticket_transcript", description="[Staff Ticket] Genera il transcript del ticket")
    @app_commands.guild_only()
    @ticket_staff_check()
    async def ticket_transcript(self, interaction: discord.Interaction):
        if not await get_ticket(interaction.channel.id):
            return await interaction.response.send_message("Questo canale non è un ticket.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        f = await build_transcript(interaction.channel)
        if f:
            await interaction.followup.send("Transcript generato:", file=f, ephemeral=True)
        else:
            await interaction.followup.send("Impossibile generare il transcript.", ephemeral=True)

    @app_commands.command(name="ticket_priority", description="[Staff Ticket] Cambia la priorità del ticket")
    @app_commands.guild_only()
    @ticket_staff_check()
    @app_commands.describe(priorita="Nuova priorità")
    async def ticket_priority(self, interaction: discord.Interaction, priorita: str):
        if priorita not in Config.PRIORITY_LEVELS:
            return await interaction.response.send_message(
                f"Priorità non valida. Scegli tra: {', '.join(Config.PRIORITY_LEVELS)}", ephemeral=True
            )
        if not await get_ticket(interaction.channel.id):
            return await interaction.response.send_message("Questo canale non è un ticket.", ephemeral=True)
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE tickets SET priority=$1 WHERE channel_id=$2", priorita, interaction.channel.id
            )
        icon  = Config.PRIORITY_ICONS.get(priorita, "")
        color = Config.PRIORITY_COLORS.get(priorita, 0xF39C12)
        await interaction.response.send_message(
            embed=discord.Embed(
                description=f"🚦 Priorità aggiornata a **{icon} {priorita}** da {interaction.user.mention}",
                color=color,
            )
        )

    @ticket_priority.autocomplete("priorita")
    async def ac_prio_cmd(self, interaction: discord.Interaction, current: str):
        return [app_commands.Choice(name=p, value=p) for p in Config.PRIORITY_LEVELS if current.lower() in p.lower()]

    @app_commands.command(name="annuncio", description="[Staff] Invia un annuncio formattato")
    @app_commands.guild_only()
    @ticket_staff_check()
    @app_commands.describe(canale="Canale destinazione", colore="Colore hex (es: ff0000)")
    async def cmd_annuncio(self, interaction: discord.Interaction, canale: Optional[discord.TextChannel] = None, colore: Optional[str] = None):
        target = canale or interaction.channel
        parsed_color = 0x3498DB
        if colore:
            try:
                parsed_color = int(colore.lstrip("#"), 16)
            except ValueError:
                return await interaction.response.send_message("❌ Colore non valido.", ephemeral=True)
        await interaction.response.send_modal(AnnuncioModal(canale=target, colore=parsed_color))

    @tasks.loop(hours=1)
    async def auto_close_task(self):
        if Config.AUTO_CLOSE_HOURS <= 0:
            return
        pool = get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT channel_id FROM tickets WHERE status='open' AND last_message < NOW() - INTERVAL '{Config.AUTO_CLOSE_HOURS} hours'"
            )
        for row in rows:
            channel_id = row["channel_id"]
            channel    = self.bot.get_channel(channel_id)
            if channel is None:
                async with pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE tickets SET status='closed', closed_at=NOW() WHERE channel_id=$1",
                        channel_id,
                    )
                continue
            try:
                await channel.send(
                    f"⏰ Ticket chiuso automaticamente per inattività superiore a {Config.AUTO_CLOSE_HOURS}h."
                )
                await close_ticket(
                    channel, channel.guild.me, channel.guild,
                    reason=f"Auto-chiusura dopo {Config.AUTO_CLOSE_HOURS}h di inattività",
                )
            except Exception as e:
                log.error("Auto-close fallito per channel_id=%d: %s", channel_id, e)

    @auto_close_task.before_loop
    async def before_auto_close(self):
        await self.bot.wait_until_ready()


# ══════════════════════════════════════════════════════════════════
# COG — MISSIONI
# ══════════════════════════════════════════════════════════════════
class MissionCog(commands.Cog):
    def __init__(self, bot: "CombinedBot"):
        self.bot = bot

    @app_commands.command(
        name="missione-crea",
        description="[Staff Missioni] Pubblica una nuova missione sulla bacheca",
    )
    @app_commands.describe(
        titolo="Cosa fare?",
        premio="Cosa si vince?",
        posti="Quanti player possono accettare? (1–50)",
    )
    @app_commands.guild_only()
    @mission_staff_check()
    async def missione_crea(
        self,
        interaction: discord.Interaction,
        titolo: str,
        premio: str,
        posti: app_commands.Range[int, 1, 50],
    ):
        embed = discord.Embed(
            title="📜 NUOVO INCARICO",
            color=discord.Color.gold(),
            timestamp=utcnow(),
        )
        embed.add_field(name="🎯 Obiettivo", value=titolo,           inline=False)
        embed.add_field(name="💰 Premio",    value=premio,           inline=True)
        embed.add_field(name="👥 Limite",    value=f"{posti} Player", inline=True)
        embed.set_footer(text=f"Posti occupati: 0/{posti}")
        embed.set_author(
            name=f"Pubblicata da {interaction.user.display_name}",
            icon_url=interaction.user.display_avatar.url,
        )
        await interaction.channel.send(embed=embed, view=MissionView())
        await interaction.response.send_message("✅ Missione pubblicata!", ephemeral=True)


# ══════════════════════════════════════════════════════════════════
# COG — GIVEAWAY
# ══════════════════════════════════════════════════════════════════
class GiveawayCog(commands.Cog):
    def __init__(self, bot: "CombinedBot"):
        self.bot = bot
        self.check_giveaways.start()

    def cog_unload(self):
        self.check_giveaways.cancel()

    @tasks.loop(minutes=1)
    async def check_giveaways(self):
        for g in await db_get_expired_giveaways():
            g_id = g["id"]
            if g_id not in _giveaway_tasks_running:
                _giveaway_tasks_running.add(g_id)
                asyncio.create_task(self._conclude_giveaway(g))

    @check_giveaways.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

    async def _conclude_giveaway(self, g: dict) -> None:
        g_id             = g["id"]
        winner_mentions: list[str] = []
        total_entries    = 0
        fresh: Optional[dict] = None

        try:
            async with _get_giveaway_lock(g_id):
                fresh = await db_get_giveaway(g_id)
                if not fresh or not fresh["active"]:
                    return
                if not await db_close_giveaway(g_id):
                    return

                entries_with_luck = await db_get_entries_with_luck(g_id)
                if entries_with_luck:
                    unique_users      = [r[0] for r in entries_with_luck]
                    luck_weights      = [r[1] for r in entries_with_luck]
                    total_entries     = len(unique_users)
                    num_winners       = min(fresh["winners"], total_entries)
                    chosen: list[int] = []
                    remaining_pool    = list(range(total_entries))
                    remaining_weights = list(luck_weights)

                    for _ in range(num_winners):
                        if not remaining_pool:
                            break
                        [idx] = random.choices(remaining_pool, weights=remaining_weights, k=1)
                        chosen.append(unique_users[idx])
                        pos = remaining_pool.index(idx)
                        remaining_pool.pop(pos)
                        remaining_weights.pop(pos)

                    winner_mentions = [f"<@{uid}>" for uid in chosen]

            if fresh is None:
                return

            channel = self.bot.get_channel(fresh["channel_id"])
            if channel and fresh["message_id"]:
                end_time = _parse_end_time(fresh["end_time"])
                embed    = build_giveaway_embed(
                    title=fresh["title"],
                    description=fresh["description"] or "",
                    prize=fresh["prize"] or "",
                    end_time=end_time,
                    winners=fresh["winners"],
                    entry_count=total_entries,
                    active=False,
                    winner_mentions=winner_mentions,
                    required_role_id=fresh.get("required_role_id"),
                )
                with contextlib.suppress(discord.HTTPException, discord.NotFound):
                    msg = await channel.fetch_message(fresh["message_id"])
                    await msg.edit(embed=embed, view=None)

                if winner_mentions:
                    await channel.send(
                        f"🎊 Il giveaway **{fresh['title']}** è terminato!\n"
                        f"Congratulazioni a {' '.join(winner_mentions)} per aver vinto **{fresh['prize']}**!"
                    )
                else:
                    await channel.send(
                        f"😔 Il giveaway **{fresh['title']}** è terminato, ma nessuno ha partecipato."
                    )
        except Exception as e:
            log.exception("Errore concludendo giveaway %s: %s", g_id, e)
        finally:
            _giveaway_tasks_running.discard(g_id)
            _cleanup_giveaway_lock(g_id)

    async def _resolve_partial_id(self, partial_id: str) -> Optional[dict]:
        g = await db_get_giveaway(partial_id)
        if g:
            return g
        pool = get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM giveaways WHERE id LIKE $1 LIMIT 2", f"{partial_id}%"
            )
        return dict(rows[0]) if len(rows) == 1 else None

    @app_commands.command(name="giveaway_crea", description="[Staff Giveaway] Crea un nuovo giveaway")
    @app_commands.guild_only()
    @giveaway_staff_check()
    async def cmd_create_giveaway(self, interaction: discord.Interaction):
        await interaction.response.send_modal(GiveawayModal())

    @app_commands.command(name="giveaway_requisiti", description="[Staff Giveaway] Imposta un ruolo richiesto")
    @app_commands.guild_only()
    @giveaway_staff_check()
    @app_commands.describe(giveaway_id="ID del giveaway", ruolo="Ruolo richiesto (vuoto = rimuovi)")
    async def cmd_giveaway_requisiti(self, interaction: discord.Interaction, giveaway_id: str, ruolo: Optional[discord.Role] = None):
        g = await self._resolve_partial_id(giveaway_id)
        if not g:
            return await interaction.response.send_message("❌ Giveaway non trovato.", ephemeral=True)
        if not g["active"]:
            return await interaction.response.send_message("❌ Giveaway già terminato.", ephemeral=True)
        role_id = ruolo.id if ruolo else None
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE giveaways SET required_role_id = $1 WHERE id = $2", role_id, g["id"]
            )
        count = await db_entry_count(g["id"])
        await refresh_giveaway_embed(interaction.client, g["id"], count)
        msg = f"✅ Ruolo richiesto: {ruolo.mention}" if ruolo else "✅ Requisito rimosso."
        await interaction.response.send_message(msg, ephemeral=True)

    @app_commands.command(name="giveaway_termina", description="[Staff Giveaway] Termina anticipatamente un giveaway")
    @app_commands.guild_only()
    @giveaway_staff_check()
    @app_commands.describe(giveaway_id="ID del giveaway da terminare")
    async def cmd_end_giveaway(self, interaction: discord.Interaction, giveaway_id: str):
        g = await self._resolve_partial_id(giveaway_id)
        if not g:
            return await interaction.response.send_message("❌ Giveaway non trovato.", ephemeral=True)
        if not g["active"]:
            return await interaction.response.send_message("ℹ️ Già terminato.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        await self._conclude_giveaway(g)
        await interaction.followup.send(f"✅ Giveaway `{g['id'][:8]}…` terminato manualmente.")

    @app_commands.command(name="giveaway_reroll", description="[Staff Giveaway] Estrae un nuovo vincitore")
    @app_commands.guild_only()
    @giveaway_staff_check()
    @app_commands.describe(giveaway_id="ID del giveaway concluso")
    async def cmd_giveaway_reroll(self, interaction: discord.Interaction, giveaway_id: str):
        g = await self._resolve_partial_id(giveaway_id)
        if not g:
            return await interaction.response.send_message("❌ Giveaway non trovato.", ephemeral=True)
        if g["active"]:
            return await interaction.response.send_message("❌ Giveaway ancora attivo.", ephemeral=True)
        entries = await db_get_entries_with_luck(g["id"])
        if not entries:
            return await interaction.response.send_message("❌ Nessun partecipante.", ephemeral=True)
        [winner_id] = random.choices([r[0] for r in entries], weights=[r[1] for r in entries], k=1)
        await interaction.response.send_message(
            f"🎲 Nuovo vincitore per **{g['title']}**: <@{winner_id}>!"
        )

    @app_commands.command(name="giveaway_partecipanti", description="[Staff Giveaway] Elenca i partecipanti con fortuna")
    @app_commands.guild_only()
    @giveaway_staff_check()
    @app_commands.describe(giveaway_id="ID del giveaway")
    async def cmd_giveaway_participants(self, interaction: discord.Interaction, giveaway_id: str):
        g = await self._resolve_partial_id(giveaway_id)
        if not g:
            return await interaction.response.send_message("❌ Giveaway non trovato.", ephemeral=True)
        rows = await db_get_entries_with_luck(g["id"])
        if not rows:
            return await interaction.response.send_message(
                f"📭 Nessun partecipante per **{g['title']}**.", ephemeral=True
            )
        view = GiveawayParticipantsView(
            rows=rows,
            giveaway_title=g["title"],
            guild=interaction.guild,
            invoker=interaction.user,
            show_luck=True,
        )
        await interaction.response.send_message(embed=view._build_embed(), view=view, ephemeral=True)
        view._message = await interaction.original_response()

    @app_commands.command(name="set_luck", description="[Staff Giveaway] Imposta il moltiplicatore fortuna")
    @app_commands.guild_only()
    @giveaway_staff_check()
    @app_commands.describe(user="Utente target", factor="Moltiplicatore (1–20)")
    async def cmd_set_luck(self, interaction: discord.Interaction, user: discord.User, factor: app_commands.Range[int, 1, 20]):
        await db_set_luck(user.id, factor)
        await interaction.response.send_message(
            f"✅ Fortuna di {user.mention} impostata a **{factor}x**.", ephemeral=True
        )

    @app_commands.command(name="my_luck", description="Scopri il tuo moltiplicatore fortuna")
    @app_commands.guild_only()
    async def cmd_my_luck(self, interaction: discord.Interaction):
        factor = await db_get_luck(interaction.user.id)
        await interaction.response.send_message(
            f"🍀 Il tuo moltiplicatore fortuna è **{factor}x**!", ephemeral=True
        )

    @app_commands.command(name="giveaways_attivi", description="Mostra i giveaway attivi")
    @app_commands.guild_only()
    async def cmd_list_giveaways(self, interaction: discord.Interaction):
        rows = await db_list_active_giveaways()
        if not rows:
            return await interaction.response.send_message("📭 Nessun giveaway attivo.", ephemeral=True)
        embed = discord.Embed(title="🎉 Giveaway Attivi", colour=discord.Colour.gold())
        for row in rows:
            end_time = _parse_end_time(row["end_time"])
            ts       = int(end_time.timestamp())
            embed.add_field(
                name=row["title"],
                value=f"ID: `{row['id'][:8]}…`\nScade: <t:{ts}:R>\nVincitori: {row['winners']}",
                inline=True,
            )
        embed.set_footer(text="Usa /giveaway_partecipanti <id> per i dettagli")
        await interaction.response.send_message(embed=embed, ephemeral=True)


# ══════════════════════════════════════════════════════════════════
# COG — CASINO
# ══════════════════════════════════════════════════════════════════
class ShopCog(commands.Cog):
    def __init__(self, bot: "CombinedBot"):
        self.bot = bot

    @app_commands.command(name="shop", description="🛍️ Acquista moltiplicatori o ruoli con le tue monete")
    @app_commands.guild_only()
    @casino_access_check()
    async def shop_cmd(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🛍️ Negozio di MetaMC",
            description="Scegli cosa vuoi acquistare con le tue monete del casinò.",
            color=Config.COLOR_PURPLE,
            timestamp=utcnow(),
        )
        embed.set_footer(text=f"Il tuo saldo: {coin(await casino_get_balance(interaction.user.id))}")
        await interaction.response.send_message(embed=embed, view=ShopView(self.bot), ephemeral=True)


class ShopView(discord.ui.View):
    def __init__(self, bot: "CombinedBot"):
        super().__init__(timeout=180)
        self.bot = bot
        self.add_item(ShopSelect(bot))


class ShopSelect(discord.ui.Select):
    def __init__(self, bot: "CombinedBot"):
        self.bot = bot
        options = []

        # Add multipliers to options
        for i, item in enumerate(Config.SHOP_MULTIPLIERS):
            options.append(discord.SelectOption(
                label=f"{item['name']} ({coin(item['cost'])})",
                value=f"multiplier_{i}",
                description=f"Moltiplicatore x{item['multiplier']} per {item['uses']} giocate."
            ))

        # Add roles to options
        for i, item in enumerate(Config.SHOP_ROLES):
            role = bot.get_guild(Config.GUILD_ID).get_role(item['role_id'])
            if role:
                options.append(discord.SelectOption(
                    label=f"{item['name']} ({coin(item['cost'])})",
                    value=f"role_{i}",
                    description=f"Assegna il ruolo {role.name}."
                ))

        super().__init__(
            placeholder="Scegli un articolo...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="shop_select_menu"
        )

    async def callback(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        balance = await casino_get_balance(user_id)
        selected_value = self.values[0]

        if selected_value.startswith("multiplier_"):
            index = int(selected_value.split("_")[1])
            item = Config.SHOP_MULTIPLIERS[index]
            item_cost = item['cost']

            if balance < item_cost:
                return await interaction.response.send_message(
                    f"❌ Non hai abbastanza monete per acquistare {item['name']}. Saldo: {coin(balance)}",
                    ephemeral=True
                )

            await casino_update_balance(user_id, -item_cost)
            # Assuming multiplier_id is the index for now, will update if actual IDs are used
            await db_add_user_multiplier(user_id, index, item['uses'])

            await interaction.response.send_message(
                f"✅ Hai acquistato **{item['name']}** per {coin(item_cost)}! Il tuo nuovo saldo è {coin(await casino_get_balance(user_id))}.",
                ephemeral=True
            )

        elif selected_value.startswith("role_"):
            index = int(selected_value.split("_")[1])
            item = Config.SHOP_ROLES[index]
            item_cost = item['cost']
            role_id = item['role_id']

            if balance < item_cost:
                return await interaction.response.send_message(
                    f"❌ Non hai abbastanza monete per acquistare {item['name']}. Saldo: {coin(balance)}",
                    ephemeral=True
                )

            guild = interaction.guild
            role = guild.get_role(role_id)
            if not role:
                return await interaction.response.send_message("❌ Ruolo non trovato. Contatta un amministratore.", ephemeral=True)

            if role in interaction.user.roles:
                return await interaction.response.send_message(f"ℹ️ Hai già il ruolo {role.mention}.", ephemeral=True)

            await casino_update_balance(user_id, -item_cost)
            ok, err = await safe_add_role(interaction.user, role)

            if ok:
                await interaction.response.send_message(
                    f"✅ Hai acquistato il ruolo {role.mention} per {coin(item_cost)}! Il tuo nuovo saldo è {coin(await casino_get_balance(user_id))}.",
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    f"❌ Errore nell'assegnazione del ruolo: {err}. Contatta un amministratore.",
                    ephemeral=True
                )


class CasinoCog(commands.Cog):
    def __init__(self, bot: "CombinedBot"):
        self.bot = bot

    @app_commands.command(name="slot", description="🎰 Gira le slot machine")
    @app_commands.describe(puntata="Importo della puntata (lascia vuoto per quella salvata)")
    @app_commands.guild_only()
    @casino_access_check()
    async def slot_cmd(self, interaction: discord.Interaction, puntata: Optional[int] = None):
        uid  = interaction.user.id
        data = await casino_get_user(uid)
        bet  = puntata if puntata is not None else data["bet"]

        if bet <= 0:
            return await interaction.response.send_message("❌ La puntata deve essere positiva.", ephemeral=True)
        if bet > data["balance"]:
            embed = base_embed("💸 Fondi insufficienti", Config.COLOR_LOSE, interaction.user)
            embed.description = f"Saldo: {coin(data['balance'])}\nPuntata: {coin(bet)}"
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        if data["last_play"]:
            try:
                elapsed = (utcnow_naive() - parse_naive(data["last_play"])).total_seconds()
                if elapsed < Config.CASINO_COOLDOWN:
                    remaining = Config.CASINO_COOLDOWN - elapsed
                    return await interaction.response.send_message(
                        f"⏳ Attendi ancora **{remaining:.1f}s**.", ephemeral=True
                    )
            except (ValueError, TypeError):
                pass

        balance_after = await casino_update_balance(uid, -bet)
        loading = base_embed("🎰 Girando...", Config.COLOR_INFO, interaction.user)
        loading.description = "❔ | ❔ | ❔"
        await interaction.response.send_message(embed=loading)
        msg = await interaction.original_response()

        for frame in [["🍒", "❔", "❔"], ["🍒", "🍋", "❔"]]:
            loading.description = " | ".join(frame)
            with contextlib.suppress(discord.HTTPException):
                await msg.edit(embed=loading)
            await asyncio.sleep(0.6)

        result       = spin_reels()
        prize, label = evaluate_spin(result, bet)
        won          = prize > 0

        # Apply multipliers
        user_multipliers = await db_get_user_multipliers(uid)
        active_multiplier = 1.0
        multiplier_id = None
        for i, m in enumerate(Config.SHOP_MULTIPLIERS):
            for user_m in user_multipliers:
                if user_m["name"] == m["name"] and user_m["remaining_uses"] > 0:
                    active_multiplier = m["multiplier"]
                    multiplier_id = i # Assuming index as ID for now
                    break
            if multiplier_id is not None: break

        if active_multiplier > 1.0 and prize > 0:
            prize = int(prize * active_multiplier)
            label += f" (x{active_multiplier} Moltiplicatore!)"
            if multiplier_id is not None:
                await db_decrement_user_multiplier(uid, multiplier_id)



        if won:
            new_bal = await casino_update_balance(uid, prize)
            embed   = base_embed("🎰 Slot Machine", Config.COLOR_WIN, interaction.user)
            embed.description = (
                f"## {' ｜ '.join(result)}\n\n"
                f"✨ {label}\n\n"
                f"**Vinto:** {coin(prize)}  (+{coin(prize - bet)} netto)\n"
                f"**Saldo:** {coin(new_bal)}"
            )
        else:
            embed = base_embed("🎰 Slot Machine", Config.COLOR_LOSE, interaction.user)
            embed.description = (
                f"## {' ｜ '.join(result)}\n\n"
                f"💨 {label}\n\n"
                f"**Perso:** {coin(bet)}\n"
                f"**Saldo:** {coin(balance_after)}"
            )

        await casino_record_game(uid, won, prize)
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE casino_users SET last_play = NOW(), bet = $1 WHERE user_id = $2",
                bet, uid,
            )

        with contextlib.suppress(discord.HTTPException):
            await msg.edit(embed=embed)

    @app_commands.command(name="coinflip", description="🪙 Lancia una moneta: testa o croce")
    @app_commands.describe(scelta="Testa o Croce", puntata="Importo della puntata")
    @app_commands.choices(scelta=[
        app_commands.Choice(name="Testa", value="testa"),
        app_commands.Choice(name="Croce", value="croce"),
    ])
    @app_commands.guild_only()
    @casino_access_check()
    async def coinflip_cmd(self, interaction: discord.Interaction, scelta: str, puntata: int):
        uid  = interaction.user.id
        data = await casino_get_user(uid)
        if puntata <= 0:
            return await interaction.response.send_message("❌ Puntata non valida.", ephemeral=True)
        if puntata > data["balance"]:
            return await interaction.response.send_message("❌ Saldo insufficiente.", ephemeral=True)

        await casino_update_balance(uid, -puntata)
        won     = random.random() < Config.COINFLIP_WIN_CHANCE / 100
        outcome = scelta if won else ("testa" if scelta == "croce" else "croce")
        icon    = "🦅" if outcome == "testa" else "🏛️"

        # Apply multipliers
        user_multipliers = await db_get_user_multipliers(uid)
        active_multiplier = 1.0
        multiplier_id = None
        for i, m in enumerate(Config.SHOP_MULTIPLIERS):
            for user_m in user_multipliers:
                if user_m["name"] == m["name"] and user_m["remaining_uses"] > 0:
                    active_multiplier = m["multiplier"]
                    multiplier_id = i # Assuming index as ID for now
                    break
            if multiplier_id is not None: break

        if active_multiplier > 1.0 and won:
            puntata = int(puntata * active_multiplier)
            if multiplier_id is not None:
                await db_decrement_user_multiplier(uid, multiplier_id)


        if won:
            new_bal = await casino_update_balance(uid, puntata * 2)
            # Multiplier applied to puntata, so prize is puntata * 2
            prize = puntata * 2
            embed   = base_embed(f"{icon} Hai vinto!", Config.COLOR_WIN, interaction.user)
            embed.description = f"La moneta mostra: **{outcome.capitalize()}**\n\nVinto: {coin(puntata)}\nSaldo: {coin(new_bal)}"
        else:
            new_bal = data["balance"] - puntata
            embed   = base_embed(f"{icon} Hai perso!", Config.COLOR_LOSE, interaction.user)
            embed.description = f"La moneta mostra: **{outcome.capitalize()}**\n\nPerso: {coin(puntata)}\nSaldo: {coin(new_bal)}"

        await casino_record_game(uid, won, prize if won else 0)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="roulette", description="🎡 Punta sulla roulette")
    @app_commands.describe(
        tipo="Tipo: numero / colore / parita / metà / dozzina",
        valore="Valore: 0-36 / rosso|nero / pari|dispari / bassa|alta / 1|2|3",
        puntata="Importo da puntare",
    )
    @app_commands.guild_only()
    @casino_access_check()
    async def roulette_cmd(self, interaction: discord.Interaction, tipo: str, valore: str, puntata: int):
        uid  = interaction.user.id
        data = await casino_get_user(uid)
        tipo = tipo.lower().strip()
        if tipo == "meta":
            tipo = "metà"
        VALID_TYPES = {"numero", "colore", "parita", "metà", "dozzina"}
        if tipo not in VALID_TYPES:
            return await interaction.response.send_message(
                "❌ Tipo non valido. Usa: `numero`, `colore`, `parita`, `metà`, `dozzina`",
                ephemeral=True,
            )
        if puntata <= 0:
            return await interaction.response.send_message("❌ Puntata non valida.", ephemeral=True)
        if puntata > data["balance"]:
            return await interaction.response.send_message(
                f"❌ Saldo insufficiente. Hai {coin(data['balance'])}.", ephemeral=True
            )

        await casino_update_balance(uid, -puntata)
        result        = roulette_spin()
        prize, detail = roulette_evaluate(tipo, valore, result, puntata)
        won           = prize > 0

        # Apply multipliers
        user_multipliers = await db_get_user_multipliers(uid)
        active_multiplier = 1.0
        multiplier_id = None
        for i, m in enumerate(Config.SHOP_MULTIPLIERS):
            for user_m in user_multipliers:
                if user_m["name"] == m["name"] and user_m["remaining_uses"] > 0:
                    active_multiplier = m["multiplier"]
                    multiplier_id = i # Assuming index as ID for now
                    break
            if multiplier_id is not None: break

        if active_multiplier > 1.0 and won:
            prize = int(prize * active_multiplier)
            detail += f" (x{active_multiplier} Moltiplicatore!)"
            if multiplier_id is not None:
                await db_decrement_user_multiplier(uid, multiplier_id)


        if won:
            new_bal = await casino_update_balance(uid, prize)
            embed   = base_embed("🎡 Roulette — Vittoria!", Config.COLOR_WIN, interaction.user)
            embed.description = f"{detail}\n\n**Vinto:** {coin(prize)} (+{coin(prize - puntata)} netto)\n**Saldo:** {coin(new_bal)}"
        else:
            new_bal = data["balance"] - puntata
            embed   = base_embed("🎡 Roulette — Sconfitta", Config.COLOR_LOSE, interaction.user)
            embed.description = f"{detail}\n\n**Perso:** {coin(puntata)}\n**Saldo:** {coin(new_bal)}"

        embed.add_field(name="Puntata su", value=f"`{tipo}` → `{valore}`", inline=True)
        await casino_record_game(uid, won, prize)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="casino_balance", description="💰 Mostra il tuo saldo del casino")
    @app_commands.describe(utente="Utente di cui vedere il saldo")
    @app_commands.guild_only()
    @casino_access_check()
    async def balance_cmd(self, interaction: discord.Interaction, utente: Optional[discord.Member] = None):
        target  = utente or interaction.user
        data    = await casino_get_user(target.id)
        winrate = f"{data['total_wins'] / data['total_games'] * 100:.1f}%" if data["total_games"] > 0 else "N/D"
        embed   = base_embed(f"💰 Portafoglio di {target.display_name}", Config.COLOR_GOLD, interaction.user)
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="Saldo",           value=coin(data["balance"]),     inline=True)
        embed.add_field(name="Puntata salvata", value=coin(data["bet"]),          inline=True)
        embed.add_field(name="Partite (V/T)",   value=f"{data['total_wins']} / {data['total_games']}", inline=True)
        embed.add_field(name="Win Rate",        value=winrate,                   inline=True)
        embed.add_field(name="Record vincita",  value=coin(data["biggest_win"]), inline=True)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="bet", description="🎯 Imposta la puntata predefinita")
    @app_commands.describe(importo="Nuova puntata predefinita")
    @app_commands.guild_only()
    @casino_access_check()
    async def bet_cmd(self, interaction: discord.Interaction, importo: int):
        if importo <= 0:
            return await interaction.response.send_message("❌ La puntata deve essere > 0.", ephemeral=True)
        data = await casino_get_user(interaction.user.id)
        if importo > data["balance"]:
            return await interaction.response.send_message(
                f"❌ Non puoi impostare una puntata superiore al saldo ({coin(data['balance'])}).", ephemeral=True
            )
        await casino_set_bet(interaction.user.id, importo)
        embed = base_embed("🎯 Puntata aggiornata", Config.COLOR_INFO, interaction.user)
        embed.description = f"Nuova puntata predefinita: {coin(importo)}"
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="daily", description="🎁 Riscatta il bonus giornaliero")
    @app_commands.guild_only()
    @casino_access_check()
    async def daily_cmd(self, interaction: discord.Interaction):
        uid  = interaction.user.id
        data = await casino_get_user(uid)

        if data["last_daily"]:
            try:
                diff = utcnow_naive() - parse_naive(data["last_daily"])
                if diff < datetime.timedelta(hours=24):
                    remaining = datetime.timedelta(hours=24) - diff
                    h, rem    = divmod(int(remaining.total_seconds()), 3600)
                    m         = rem // 60
                    embed     = base_embed("⏳ Daily non disponibile", Config.COLOR_INFO, interaction.user)
                    embed.description = f"Torna tra **{h}h {m}m**."
                    return await interaction.response.send_message(embed=embed, ephemeral=True)
            except (ValueError, TypeError):
                pass

        reward  = random.randint(Config.DAILY_BONUS_MIN, Config.DAILY_BONUS_MAX)
        new_bal = await casino_update_balance(uid, reward)
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE casino_users SET last_daily = NOW() WHERE user_id = $1", uid
            )

        embed = base_embed("🎁 Bonus Giornaliero", Config.COLOR_GOLD, interaction.user)
        embed.description = (
            f"Hai ricevuto {coin(reward)}!\n\n"
            f"**Saldo aggiornato:** {coin(new_bal)}\n\n"
            "*Torna domani per un altro bonus.*"
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="casino_give", description="🎁 Trasferisci monete a un altro utente")
    @app_commands.describe(destinatario="A chi inviare le monete", importo="Quante monete")
    @app_commands.guild_only()
    @casino_access_check()
    async def give_cmd(self, interaction: discord.Interaction, destinatario: discord.Member, importo: app_commands.Range[int, 1, 100_000]):
        if destinatario.id == interaction.user.id:
            return await interaction.response.send_message("❌ Non puoi trasferire a te stesso.", ephemeral=True)
        if destinatario.bot:
            return await interaction.response.send_message("❌ Non puoi trasferire a un bot.", ephemeral=True)
        sender = await casino_get_user(interaction.user.id)
        if sender["balance"] < importo:
            return await interaction.response.send_message(
                f"❌ Saldo insufficiente. Hai {coin(sender['balance'])}.", ephemeral=True
            )
        await casino_update_balance(interaction.user.id, -importo)
        new_bal = await casino_update_balance(destinatario.id, importo)
        embed   = base_embed("💸 Trasferimento effettuato", Config.COLOR_INFO, interaction.user)
        embed.description = f"Inviato {coin(importo)} a {destinatario.mention}.\nIl loro saldo: {coin(new_bal)}."
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="casino_leaderboard", description="🏆 Classifica del casino")
    @app_commands.guild_only()
    @casino_access_check()
    async def leaderboard_cmd(self, interaction: discord.Interaction):
        await interaction.response.defer()
        pool = get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT user_id, balance, total_wins, total_games FROM casino_users ORDER BY balance DESC LIMIT 10"
            )

        async def _fetch_name(user_id: int) -> str:
            try:
                user = await self.bot.fetch_user(user_id)
                return user.display_name
            except Exception:
                return f"Utente#{user_id}"

        names  = await asyncio.gather(*[_fetch_name(r["user_id"]) for r in rows])
        MEDALS = ["🥇", "🥈", "🥉"]
        embed  = base_embed("🏆 Classifica Casino", Config.COLOR_GOLD, interaction.user)
        lines: list[str] = []
        for i, (row, name) in enumerate(zip(rows, names)):
            medal = MEDALS[i] if i < 3 else f"`{i+1}.`"
            wr    = f"{row['total_wins'] / row['total_games'] * 100:.0f}%" if row["total_games"] else "–"
            lines.append(f"{medal} **{name}** — {coin(row['balance'])}  *(WR {wr})*")
        embed.description = "\n".join(lines) or "Nessun dato disponibile."
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="casino_stats", description="📊 Le tue statistiche di gioco")
    @app_commands.guild_only()
    @casino_access_check()
    async def stats_cmd(self, interaction: discord.Interaction):
        data   = await casino_get_user(interaction.user.id)
        games  = data["total_games"]
        wins   = data["total_wins"]
        wr     = f"{wins / games * 100:.1f}%" if games else "N/D"
        embed  = base_embed("📊 Le tue statistiche", Config.COLOR_PURPLE, interaction.user)
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.add_field(name="Partite totali", value=str(games),                 inline=True)
        embed.add_field(name="Vittorie",       value=str(wins),                  inline=True)
        embed.add_field(name="Sconfitte",      value=str(games - wins),          inline=True)
        embed.add_field(name="Win Rate",       value=wr,                         inline=True)
        embed.add_field(name="Record vincita", value=coin(data["biggest_win"]),  inline=True)
        embed.add_field(name="Saldo",          value=coin(data["balance"]),      inline=True)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="casino_bonus_codice", description="🎟️ Riscatta un codice promozionale")
    @app_commands.describe(codice="Il codice promozionale")
    @app_commands.guild_only()
    @casino_access_check()
    async def redeem_promo_cmd(self, interaction: discord.Interaction, codice: str):
        uid             = interaction.user.id
        ok, msg, reward = await db_redeem_promo(codice.strip(), uid)
        if ok:
            new_bal = await casino_update_balance(uid, reward)
            embed   = base_embed("🎟️ Codice Riscattato!", Config.COLOR_WIN, interaction.user)
            embed.description = f"{msg}\n\nHai ricevuto {coin(reward)}!\n**Saldo:** {coin(new_bal)}"
        else:
            embed = base_embed("❌ Codice non valido", Config.COLOR_LOSE, interaction.user)
            embed.description = msg
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="casino_bonus_crea", description="[Staff Casino] Crea un codice promozionale")
    @app_commands.describe(
        monete="Monete da assegnare",
        codice="Codice (lascia vuoto per generazione automatica)",
        usi="Numero massimo di utilizzi (0 = illimitato)",
        scadenza="Scadenza in ore (0 = nessuna)",
    )
    @app_commands.guild_only()
    @casino_staff_check()
    async def create_promo_cmd(
        self, interaction: discord.Interaction,
        monete: int,
        codice: Optional[str] = None,
        usi: int = 1,
        scadenza: int = 0,
    ):
        if monete <= 0:
            return await interaction.response.send_message("❌ Le monete devono essere > 0.", ephemeral=True)
        if usi < 0:
            return await interaction.response.send_message("❌ Gli usi devono essere ≥ 0.", ephemeral=True)

        final_code = codice.strip().upper() if codice else "".join(
            random.choices(string.ascii_uppercase + string.digits, k=8)
        )
        max_uses   = usi if usi > 0 else 999_999_999
        expires_dt: Optional[datetime.datetime] = None
        if scadenza > 0:
            expires_dt = utcnow_naive() + datetime.timedelta(hours=scadenza)

        try:
            await db_create_promo(final_code, monete, max_uses, expires_dt, interaction.user.id)
        except asyncpg.UniqueViolationError:
            return await interaction.response.send_message(
                f"❌ Il codice `{final_code}` esiste già.", ephemeral=True
            )

        embed = base_embed("✅ Codice Promozionale Creato", Config.COLOR_WIN, interaction.user)
        embed.add_field(name="Codice",   value=f"`{final_code}`",                              inline=True)
        embed.add_field(name="Monete",  value=coin(monete),                                   inline=True)
        embed.add_field(name="Usi max", value=str(usi) if usi > 0 else "Illimitato",          inline=True)
        embed.add_field(name="Scade",   value=f"Tra {scadenza}h" if scadenza > 0 else "Mai", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── NUOVO COMANDO: rimuovi codice promo ── MODIFICA ──────────
    @app_commands.command(
        name="casino_rimuovi_codice",
        description="[Staff Casino] Elimina un codice promozionale dal database",
    )
    @app_commands.describe(codice="Il codice da eliminare (es: ESTATE24)")
    @app_commands.guild_only()
    @casino_staff_check()
    async def rimuovi_codice_cmd(
        self, interaction: discord.Interaction, codice: str
    ) -> None:
        code_upper = codice.strip().upper()
        deleted = await db_delete_promo(code_upper)
        if deleted:
            embed = base_embed("🗑️ Codice Eliminato", Config.COLOR_INFO, interaction.user)
            embed.description = (
                f"Il codice `{code_upper}` è stato **eliminato** dal database.\n"
                "Tutti gli utilizzi precedenti vengono rimossi automaticamente."
            )
        else:
            embed = base_embed("❌ Codice Non Trovato", Config.COLOR_LOSE, interaction.user)
            embed.description = f"Nessun codice `{code_upper}` trovato nel database."
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="casino_lista_codici", description="[Staff Casino] Visualizza tutti i codici promozionali")
    @app_commands.guild_only()
    @casino_staff_check()
    async def lista_codici_cmd(self, interaction: discord.Interaction):
        pool = get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT code, reward, uses, max_uses, expires_at, created_by, active
                FROM promo_codes
                ORDER BY active DESC, code
                LIMIT 50
                """
            )

        if not rows:
            return await interaction.response.send_message(
                "📭 Nessun codice promozionale nel database.", ephemeral=True
            )

        PAGE = 10
        pages: list[discord.Embed] = []
        chunks = [rows[i:i+PAGE] for i in range(0, len(rows), PAGE)]
        now = utcnow_naive()

        for idx, chunk in enumerate(chunks):
            embed = discord.Embed(
                title="🎟️ Codici Promozionali",
                color=Config.COLOR_GOLD,
                timestamp=utcnow(),
            )
            embed.set_footer(text=f"Pagina {idx+1}/{len(chunks)} • Totale: {len(rows)} codici")

            for row in chunk:
                stato = "✅ Attivo" if row["active"] else "❌ Esaurito/Disattivato"
                if row["expires_at"]:
                    exp_naive = parse_naive(row["expires_at"])
                    if now > exp_naive:
                        scad_text = "⏰ Scaduto"
                    else:
                        delta = exp_naive - now
                        h, rem = divmod(int(delta.total_seconds()), 3600)
                        scad_text = f"Scade tra {h}h {rem//60}m"
                else:
                    scad_text = "Nessuna scadenza"

                max_u = row["max_uses"]
                remaining_uses = (
                    "Illimitato" if max_u >= 999_999_999
                    else f"{row['uses']}/{max_u} usati"
                )

                embed.add_field(
                    name=f"`{row['code']}` — {coin(row['reward'])}",
                    value=(
                        f"**Stato:** {stato}\n"
                        f"**Usi:** {remaining_uses}\n"
                        f"**Scadenza:** {scad_text}\n"
                        f"**Creato da:** <@{row['created_by']}>"
                    ),
                    inline=True,
                )
            pages.append(embed)

        if len(pages) == 1:
            return await interaction.response.send_message(embed=pages[0], ephemeral=True)

        view = PromoCodesPageView(pages, interaction.user)
        await interaction.response.send_message(embed=pages[0], view=view, ephemeral=True)
        view._message = await interaction.original_response()

    @app_commands.command(name="casino_addcoins", description="[Staff Casino] Aggiungi monete a un utente")
    @app_commands.describe(utente="Utente target", importo="Quantità")
    @app_commands.guild_only()
    @casino_staff_check()
    async def addcoins_cmd(self, interaction: discord.Interaction, utente: discord.User, importo: int):
        if importo <= 0:
            return await interaction.response.send_message("❌ Importo non valido.", ephemeral=True)
        new_bal = await casino_update_balance(utente.id, importo)
        embed   = base_embed("✅ Monete aggiunte", Config.COLOR_WIN, interaction.user)
        embed.description = f"{utente.mention} ha ricevuto {coin(importo)}.\nNuovo saldo: {coin(new_bal)}"
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="casino_removecoins", description="[Staff Casino] Rimuovi monete a un utente")
    @app_commands.describe(utente="Utente target", importo="Quantità")
    @app_commands.guild_only()
    @casino_staff_check()
    async def removecoins_cmd(self, interaction: discord.Interaction, utente: discord.User, importo: int):
        if importo <= 0:
            return await interaction.response.send_message("❌ Importo non valido.", ephemeral=True)
        new_bal = await casino_update_balance(utente.id, -importo)
        embed   = base_embed("✅ Monete rimosse", Config.COLOR_LOSE, interaction.user)
        embed.description = f"Rimosso {coin(importo)} da {utente.mention}.\nNuovo saldo: {coin(new_bal)}"
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="casino_reset", description="[Staff Casino] Resetta l'account casino di un utente")
    @app_commands.describe(utente="Utente da resettare")
    @app_commands.guild_only()
    @casino_staff_check()
    async def resetuser_cmd(self, interaction: discord.Interaction, utente: discord.User):
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE casino_users
                SET balance=$1, bet=10, last_daily=NULL, last_play=NULL,
                    total_wins=0, total_games=0, biggest_win=0
                WHERE user_id=$2
                """,
                Config.STARTING_BALANCE, utente.id,
            )
        embed = base_embed("🔄 Account Resettato", Config.COLOR_INFO, interaction.user)
        embed.description = f"Account di {utente.mention} resettato a {coin(Config.STARTING_BALANCE)}."
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="casino_grant_role", description="[Staff Casino] Assegna il ruolo casino")
    @app_commands.describe(utente="Utente a cui assegnare il ruolo casino")
    @app_commands.guild_only()
    @casino_staff_check()
    async def grant_casino_role(self, interaction: discord.Interaction, utente: discord.Member):
        role = interaction.guild.get_role(Config.CASINO_ROLE_ID)
        if not role:
            return await interaction.response.send_message(
                f"❌ Ruolo casino (ID `{Config.CASINO_ROLE_ID}`) non trovato.", ephemeral=True
            )
        if role in utente.roles:
            return await interaction.response.send_message(
                f"ℹ️ {utente.mention} ha già il ruolo {role.mention}.", ephemeral=True
            )
        ok, err = await safe_add_role(utente, role)
        if ok:
            embed = base_embed("🎰 Accesso Casino Concesso", Config.COLOR_WIN, interaction.user)
            embed.description = f"{utente.mention} può ora usare il casino ({role.mention})."
            await interaction.response.send_message(embed=embed)
        else:
            await interaction.response.send_message(f"❌ Errore: {err}", ephemeral=True)

    @app_commands.command(name="casino_revoke_role", description="[Staff Casino] Rimuovi il ruolo casino")
    @app_commands.describe(utente="Utente a cui rimuovere il ruolo casino")
    @app_commands.guild_only()
    @casino_staff_check()
    async def revoke_casino_role(self, interaction: discord.Interaction, utente: discord.Member):
        role = interaction.guild.get_role(Config.CASINO_ROLE_ID)
        if not role:
            return await interaction.response.send_message(
                f"❌ Ruolo casino (ID `{Config.CASINO_ROLE_ID}`) non trovato.", ephemeral=True
            )
        if role not in utente.roles:
            return await interaction.response.send_message(
                f"ℹ️ {utente.mention} non ha il ruolo {role.mention}.", ephemeral=True
            )
        ok, err = await safe_remove_role(utente, role)
        if ok:
            embed = base_embed("🎰 Accesso Casino Revocato", Config.COLOR_LOSE, interaction.user)
            embed.description = f"Ruolo casino rimosso da {utente.mention}."
            await interaction.response.send_message(embed=embed)
        else:
            await interaction.response.send_message(f"❌ Errore: {err}", ephemeral=True)


# ══════════════════════════════════════════════════════════════════
# View paginazione per lista codici promo
# ══════════════════════════════════════════════════════════════════
class PromoCodesPageView(discord.ui.View):
    def __init__(self, pages: list[discord.Embed], invoker: discord.User | discord.Member):
        super().__init__(timeout=120)
        self.pages   = pages
        self.invoker = invoker
        self.page    = 0
        self._message: Optional[discord.Message] = None
        self._update_buttons()

    def _update_buttons(self) -> None:
        self.prev_btn.disabled = self.page == 0
        self.next_btn.disabled = self.page >= len(self.pages) - 1

    async def _check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.invoker.id:
            await interaction.response.send_message("❌ Non puoi navigare questa lista.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="◀ Precedente", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check(interaction):
            return
        self.page -= 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.pages[self.page], view=self)

    @discord.ui.button(label="Successivo ▶", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check(interaction):
            return
        self.page += 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.pages[self.page], view=self)

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True  # type: ignore[attr-defined]
        if self._message:
            with contextlib.suppress(discord.HTTPException):
                await self._message.edit(view=self)


# ══════════════════════════════════════════════════════════════════
# COG — SONDAGGI
# ══════════════════════════════════════════════════════════════════
class PollCog(commands.Cog):
    def __init__(self, bot: "CombinedBot"):
        self.bot = bot

    @app_commands.command(name="sondaggio", description="📊 Crea un sondaggio con pulsanti di voto")
    @app_commands.describe(
        domanda="La domanda del sondaggio",
        opzioni="Opzioni separate da | (max 10). Es: Sì|No|Forse",
    )
    @app_commands.guild_only()
    @ticket_staff_check()
    async def sondaggio_cmd(self, interaction: discord.Interaction, domanda: str, opzioni: str):
        opts = [o.strip() for o in opzioni.split("|") if o.strip()]
        if len(opts) < 2:
            return await interaction.response.send_message(
                "❌ Inserisci almeno 2 opzioni separate da `|`.", ephemeral=True
            )
        if len(opts) > 10:
            return await interaction.response.send_message("❌ Massimo 10 opzioni.", ephemeral=True)

        p_id    = await db_create_poll(domanda, opts, interaction.channel_id, interaction.user.id)
        options = await db_get_poll_options(p_id)
        poll    = await db_get_poll(p_id)
        embed   = _build_poll_embed(poll, options)
        embed.set_author(
            name=f"Sondaggio di {interaction.user.display_name}",
            icon_url=interaction.user.display_avatar.url,
        )
        view = PollView(p_id, options)

        await interaction.response.send_message(embed=embed, view=view)
        msg = await interaction.original_response()
        await db_set_poll_message(p_id, msg.id)

    @app_commands.command(name="sondaggio_chiudi", description="[Staff] Chiude un sondaggio attivo")
    @app_commands.describe(poll_id="ID del sondaggio (prime 8 cifre)")
    @app_commands.guild_only()
    @ticket_staff_check()
    async def chiudi_sondaggio_cmd(self, interaction: discord.Interaction, poll_id: str):
        pool = get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM polls WHERE id LIKE $1 AND active = TRUE LIMIT 2", f"{poll_id}%"
            )

        if not rows:
            return await interaction.response.send_message(
                "❌ Sondaggio non trovato o già chiuso.", ephemeral=True
            )
        if len(rows) > 1:
            return await interaction.response.send_message(
                "❌ ID ambiguo, fornisci più caratteri.", ephemeral=True
            )

        p = dict(rows[0])
        await db_close_poll(p["id"])
        options = await db_get_poll_options(p["id"])
        embed   = _build_poll_embed(p, options, closed=True)

        channel = interaction.guild.get_channel(p["channel_id"])
        if channel and p["message_id"]:
            with contextlib.suppress(discord.HTTPException, discord.NotFound):
                msg         = await channel.fetch_message(p["message_id"])
                closed_view = discord.ui.View()
                for btn in PollView(p["id"], options).children:
                    btn.disabled = True  # type: ignore[attr-defined]
                    closed_view.add_item(btn)
                await msg.edit(embed=embed, view=closed_view)

        await interaction.response.send_message("✅ Sondaggio chiuso.", ephemeral=True)


# ══════════════════════════════════════════════════════════════════
# COG — AFK
# ══════════════════════════════════════════════════════════════════
class AfkCog(commands.Cog):
    def __init__(self, bot: "CombinedBot"):
        self.bot = bot

    @app_commands.command(name="afk", description="[Staff] Imposta il tuo stato AFK")
    @app_commands.describe(motivo="Motivo dell'assenza")
    @app_commands.guild_only()
    async def afk_cmd(self, interaction: discord.Interaction, motivo: str = "Assente"):
        if not is_any_staff(interaction.user):
            return await interaction.response.send_message(
                "❌ Questo comando è riservato allo staff.", ephemeral=True
            )
        _afk_store[interaction.user.id] = {"reason": motivo, "since": utcnow()}
        embed = discord.Embed(
            title="💤 Stato AFK Attivato",
            description=f"Sei ora in modalità AFK.\n**Motivo:** {motivo}\n\nUsa `/unafk` per tornare disponibile.",
            color=discord.Color.orange(),
            timestamp=utcnow(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="unafk", description="[Staff] Rimuovi il tuo stato AFK")
    @app_commands.guild_only()
    async def unafk_cmd(self, interaction: discord.Interaction):
        if not is_any_staff(interaction.user):
            return await interaction.response.send_message(
                "❌ Questo comando è riservato allo staff.", ephemeral=True
            )
        if interaction.user.id not in _afk_store:
            return await interaction.response.send_message("ℹ️ Non sei in modalità AFK.", ephemeral=True)

        afk_data = _afk_store.pop(interaction.user.id)
        duration = utcnow() - afk_data["since"]
        h, rem   = divmod(int(duration.total_seconds()), 3600)
        m        = rem // 60
        embed = discord.Embed(
            title="✅ Benvenuto di ritorno!",
            description=f"Hai rimosso lo stato AFK.\n**Durata assenza:** {h}h {m}m",
            color=discord.Color.green(),
            timestamp=utcnow(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        for user in message.mentions:
            if user.id in _afk_store and user.id != message.author.id:
                afk_data = _afk_store[user.id]
                duration = utcnow() - afk_data["since"]
                h, rem   = divmod(int(duration.total_seconds()), 3600)
                m        = rem // 60
                with contextlib.suppress(discord.HTTPException):
                    await message.channel.send(
                        embed=discord.Embed(
                            description=(
                                f"💤 **{user.display_name}** è attualmente AFK.\n"
                                f"**Motivo:** {afk_data['reason']}\n"
                                f"**Assente da:** {h}h {m}m"
                            ),
                            color=discord.Color.orange(),
                        ),
                        delete_after=15,
                    )


# ══════════════════════════════════════════════════════════════════
# COG — COMUNICAZIONI  ← MODIFICA: usa send() del bot, no webhook
# ══════════════════════════════════════════════════════════════════
class ComunicazioniCog(commands.Cog):
    """
    Invia il messaggio nel canale con il profilo del BOT.
    Nessun webhook, nessun nome utente sovrapposto:
    il messaggio appare esattamente come se il bot stesso avesse scritto.
    """

    def __init__(self, bot: "CombinedBot"):
        self.bot = bot

    @app_commands.command(
        name="comunicazioni",
        description="[Staff] Scrivi nel canale con il profilo del bot",
    )
    @app_commands.describe(
        messaggio="Il testo da inviare",
        canale="Canale destinazione (lascia vuoto = canale corrente)",
    )
    @app_commands.guild_only()
    @ticket_staff_check()
    async def comunicazioni_cmd(
        self,
        interaction: discord.Interaction,
        messaggio: str,
        canale: Optional[discord.TextChannel] = None,
    ) -> None:
        target = canale or interaction.channel

        perms = target.permissions_for(interaction.guild.me)
        if not perms.send_messages:
            return await interaction.response.send_message(
                f"❌ Non ho il permesso **Invia Messaggi** in {target.mention}.",
                ephemeral=True,
            )

        await interaction.response.defer(ephemeral=True)

        try:
            await target.send(
                content=messaggio,
                allowed_mentions=discord.AllowedMentions(
                    everyone=False, roles=False, users=True
                ),
            )
        except discord.Forbidden:
            return await interaction.followup.send(
                "❌ Impossibile inviare il messaggio. Controlla i permessi del bot.",
                ephemeral=True,
            )
        except discord.HTTPException as e:
            return await interaction.followup.send(
                f"❌ Errore nell'invio: {e}", ephemeral=True
            )

        await interaction.followup.send(
            f"✅ Messaggio inviato in {target.mention}.",
            ephemeral=True,
        )


# ══════════════════════════════════════════════════════════════════
# COG — HELP
# ══════════════════════════════════════════════════════════════════
class HelpCog(commands.Cog):
    def __init__(self, bot: "CombinedBot"):
        self.bot = bot

    @app_commands.command(name="help", description="📖 Lista di tutti i comandi divisa per categoria")
    @app_commands.guild_only()
    async def help_cmd(self, interaction: discord.Interaction):
        HELP_SECTIONS = [
            {
                "title": "🎫 Ticket",
                "color": 0x3498DB,
                "commands": [
                    ("/ticket_setup",      "Admin",        "Invia l'embed per aprire ticket"),
                    ("/ticket_ban",        "Staff Ticket", "Aggiunge utente alla blacklist"),
                    ("/ticket_unban",      "Staff Ticket", "Rimuove utente dalla blacklist"),
                    ("/ticket_list",       "Staff Ticket", "Mostra tutti i ticket aperti"),
                    ("/ticket_stats",      "Staff Ticket", "Statistiche del sistema ticket"),
                    ("/ticket_close",      "Staff Ticket", "Chiude il ticket (countdown 10min)"),
                    ("/ticket_forceclose", "Admin",        "Chiude immediatamente il ticket"),
                    ("/ticket_claim",      "Staff Ticket", "Prendi in carico il ticket"),
                    ("/ticket_assign",     "Staff Ticket", "Assegna ticket ad altro staff"),
                    ("/ticket_add",        "Staff Ticket", "Aggiungi utente al ticket"),
                    ("/ticket_remove",     "Staff Ticket", "Rimuovi utente dal ticket"),
                    ("/ticket_info",       "Tutti",        "Info sul ticket corrente"),
                    ("/ticket_transcript", "Staff Ticket", "Genera il transcript del ticket"),
                    ("/ticket_priority",   "Staff Ticket", "Cambia la priorità del ticket"),
                    ("/annuncio",          "Staff",        "Invia un annuncio formattato"),
                    ("/comunicazioni",     "Staff",        "Scrivi nel canale con il profilo del bot"),
                ],
            },
            {
                "title": "🤝 Partnership",
                "color": 0x1ABC9C,
                "commands": [
                    ("Ticket categoria Partnership", "Tutti",           "Apri un ticket di partnership"),
                    ("Pulsante ACCETTA/RIFIUTA",     "Partner Manager", "Accetta/rifiuta la richiesta"),
                ],
            },
            {
                "title": "🎰 Casino",
                "color": 0xF1C40F,
                "commands": [
                    ("/slot",                   "Ruolo Casino",  "Gira le slot machine"),
                    ("/coinflip",               "Ruolo Casino",  "Lancia una moneta"),
                    ("/roulette",               "Ruolo Casino",  "Punta sulla roulette"),
                    ("/casino_balance",         "Ruolo Casino",  "Vedi il tuo saldo"),
                    ("/bet",                    "Ruolo Casino",  "Imposta puntata predefinita"),
                    ("/daily",                  "Ruolo Casino",  "Riscatta bonus giornaliero"),
                    ("/casino_give",            "Ruolo Casino",  "Trasferisci monete a un altro"),
                    ("/casino_leaderboard",     "Ruolo Casino",  "Classifica casino"),
                    ("/casino_stats",           "Ruolo Casino",  "Le tue statistiche"),
                    ("/casino_bonus_codice",    "Ruolo Casino",  "Riscatta un codice promozionale"),
                    ("/casino_lista_codici",    "Staff Casino",  "Vedi tutti i codici promo"),
                    ("/casino_bonus_crea",      "Staff Casino",  "Crea un codice promozionale"),
                    ("/casino_rimuovi_codice",  "Staff Casino",  "Elimina un codice promozionale"),
                    ("/casino_addcoins",        "Staff Casino",  "Aggiungi monete a un utente"),
                    ("/casino_removecoins",     "Staff Casino",  "Rimuovi monete a un utente"),
                    ("/casino_reset",           "Staff Casino",  "Resetta account casino"),
                    ("/casino_grant_role",      "Staff Casino",  "Assegna ruolo casino"),
                    ("/casino_revoke_role",     "Staff Casino",  "Rimuovi ruolo casino"),
                ],
            },
            {
                "title": "🎉 Giveaway",
                "color": 0xFFD700,
                "commands": [
                    ("/giveaway_crea",        "Staff Giveaway", "Crea un giveaway"),
                    ("/giveaway_termina",      "Staff Giveaway", "Termina anticipatamente"),
                    ("/giveaway_reroll",       "Staff Giveaway", "Estrae nuovo vincitore"),
                    ("/giveaway_partecipanti", "Staff Giveaway", "Lista partecipanti con fortuna"),
                    ("/giveaway_requisiti",    "Staff Giveaway", "Imposta ruolo richiesto"),
                    ("/set_luck",             "Staff Giveaway", "Imposta moltiplicatore fortuna"),
                    ("/my_luck",              "Tutti",          "Mostra il tuo moltiplicatore"),
                    ("/giveaways_attivi",      "Tutti",          "Mostra giveaway attivi"),
                ],
            },
            {
                "title": "⚔️ Missioni",
                "color": 0x8B0000,
                "commands": [
                    ("/missione-crea", "Staff Missioni", "Pubblica una missione sulla bacheca"),
                    ("/missioni_attive", "Tutti", "Mostra la missione giornaliera attiva"),
                    ("/missioni_progresso", "Tutti", "Mostra il tuo progresso nella missione"),
                ],
            },
            {
                "title": "🛍️ Shop",
                "color": Config.COLOR_PURPLE,
                "commands": [
                    ("/shop", "Ruolo Casino", "Acquista moltiplicatori o ruoli"),
                ],
            },
            {
                "title": "🏆 Team",
                "color": 0x27AE60,
                "commands": [
                    ("/add_member",    "Staff Team", "Aggiunge membro al team"),
                    ("/remove_member", "Staff Team", "Rimuove membro dal team"),
                    ("/list_members",  "Tutti",      "Lista membri del team"),
                    ("/mc_lookup",     "Staff Team", "Cerca Discord da nickname MC"),
                ],
            },
            {
                "title": "📊 Sondaggi",
                "color": 0x9B59B6,
                "commands": [
                    ("/sondaggio",        "Staff", "Crea un sondaggio con pulsanti"),
                    ("/sondaggio_chiudi", "Staff", "Chiude un sondaggio attivo"),
                ],
            },
            {
                "title": "💤 AFK",
                "color": 0xE67E22,
                "commands": [
                    ("/afk",   "Staff", "Imposta stato AFK (avvisa chi ti tagga)"),
                    ("/unafk", "Staff", "Rimuovi stato AFK"),
                ],
            },
        ]

        def make_section_embed(section: dict) -> discord.Embed:
            embed = discord.Embed(
                title=section["title"],
                color=section["color"],
                timestamp=utcnow(),
            )
            lines = [f"`{cmd}` — **[{role}]** {desc}" for cmd, role, desc in section["commands"]]
            embed.description = "\n".join(lines)
            embed.set_footer(text="Combined Bot v17 • Usa il menu a tendina per navigare")
            return embed

        select = discord.ui.Select(
            placeholder="📂 Scegli una categoria...",
            options=[
                discord.SelectOption(
                    label=s["title"],
                    value=str(i),
                    emoji=s["title"].split()[0],
                )
                for i, s in enumerate(HELP_SECTIONS)
            ],
        )
        help_view = discord.ui.View(timeout=120)

        async def select_callback(inter: discord.Interaction):
            idx = int(inter.data["values"][0])
            await inter.response.edit_message(embed=make_section_embed(HELP_SECTIONS[idx]), view=help_view)

        select.callback = select_callback
        help_view.add_item(select)

        overview = discord.Embed(
            title="📖 Guida ai Comandi — Combined Bot v17",
            description=(
                "Usa il menu a tendina per esplorare i comandi per categoria.\n\n"
                "**Moduli disponibili:**\n"
                "🎫 Ticket & Candidature\n"
                "🤝 Partnership\n"
                "🎰 Casino (Slot, Coinflip, Roulette, Codici Promo)\n"
                "🎉 Giveaway (con sistema Fortuna e Requisiti)\n"
                "⚔️ Missioni\n"
                "🛍️ Shop\n"
                "🏆 Team Manager\n"
                "📊 Sondaggi\n"
                "💤 Sistema AFK\n"
                "📣 Comunicazioni (scrivi con il profilo del bot)\n"
            ),
            color=0x5865F2,
            timestamp=utcnow(),
        )
        overview.set_footer(
            text=f"Richiesto da {interaction.user.display_name}",
            icon_url=interaction.user.display_avatar.url,
        )
        await interaction.response.send_message(embed=overview, view=help_view, ephemeral=True)


# ══════════════════════════════════════════════════════════════════
# BOT PRINCIPALE
# ══════════════════════════════════════════════════════════════════
class CombinedBot(commands.Bot):
    def __init__(self) -> None:
        intents                 = discord.Intents.default()
        intents.message_content = True
        intents.members         = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self) -> None:
        global _db_pool
        Config.validate()

        _db_pool = await create_pool()
        log.info("Pool PostgreSQL creato.")
        await init_db()

        self.add_view(TicketControlView())
        self.add_view(MainPersistentView())
        self.add_view(GiveawayView(None))
        self.add_view(MissionView())
        self.add_view(MissionControl())

        await self.add_cog(TeamCog(self))
        await self.add_cog(TicketCog(self))
        await self.add_cog(GiveawayCog(self))
        await self.add_cog(CasinoCog(self))
        await self.add_cog(ShopCog(self))
        await self.add_cog(MissionCog(self))
        await self.add_cog(PollCog(self))
        await self.add_cog(AfkCog(self))
        await self.add_cog(ComunicazioniCog(self))
        await self.add_cog(HelpCog(self))

        guild  = Config.guild_obj()
        self.tree.copy_global_to(guild=guild)
        synced = await self.tree.sync(guild=guild)
        log.info("Slash commands sincronizzati: %d sul server %d", len(synced), Config.GUILD_ID)

    async def on_ready(self) -> None:
        log.info("Bot online: %s (ID: %d)", self.user, self.user.id)
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="⚔️ missioni · 🎰 casino · 🎫 ticket · 🎉 giveaway · 🤝 partnership",
            )
        )
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute("UPDATE tickets SET status='open' WHERE status='closing'")
        log.info("Ticket 'closing' ripristinati a 'open' dopo il restart.")
        self.daily_mission_task.start()

    @tasks.loop(hours=24)
    async def daily_mission_task(self) -> None:
        await self.wait_until_ready()
        today = utcnow().date()
        mission = await db_get_daily_mission(today)

        if not mission:
            # Create a new mission for today
            mission_type = "message_count"
            target = Config.MISSION_MESSAGE_COUNT_TARGET
            reward = Config.MISSION_MESSAGE_COUNT_REWARD
            mission = await db_create_daily_mission(mission_type, target, reward, today)

            # Announce the new mission
            mission_channel = self.get_channel(Config.MISSION_CHANNEL_ID)
            if mission_channel and isinstance(mission_channel, discord.TextChannel):
                embed = discord.Embed(
                    title="✨ Nuova Missione Giornaliera! ✨",
                    description=f"Scrivi **{target} messaggi** oggi per guadagnare **{reward} monete** del casinò!",
                    color=Config.COLOR_GOLD,
                    timestamp=utcnow(),
                )
                await mission_channel.send(content="@everyone", embed=embed, allowed_mentions=discord.AllowedMentions(everyone=True))

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        if message.guild is not None:
            await try_update_last_message(message.channel.id)

            # Daily Mission: Message Count
            today = utcnow().date()
            mission = await db_get_daily_mission(today)
            if mission and mission["type"] == "message_count":
                user_mission = await db_get_user_mission_progress(message.author.id, mission["id"])
                current_progress = user_mission["progress"] if user_mission else 0
                completed = user_mission["completed"] if user_mission else False

                if not completed:
                    new_progress = current_progress + 1
                    await db_upsert_user_mission_progress(message.author.id, mission["id"], new_progress, False)

                    if new_progress >= mission["target"]:
                        await db_upsert_user_mission_progress(message.author.id, mission["id"], new_progress, True)
                        await casino_update_balance(message.author.id, mission["reward"])
                        await message.channel.send(
                            f"🎉 {message.author.mention}, hai completato la missione giornaliera e guadagnato **{mission['reward']} monete**!"
                        )

        await self.process_commands(message)

    async def on_message_delete(self, message: discord.Message) -> None:
        if message.author.bot or not message.guild:
            return
        if message.content:
            await db_log_deleted_message(message.id, message.channel.id, message.guild.id, message.author.id, message.content)
            log.info(f"Messaggio eliminato da {message.author} in #{message.channel.name}: {message.content[:50]}...")

    async def on_message_edit(self, before: discord.Message, after: discord.Message) -> None:
        if before.author.bot or not before.guild or before.content == after.content:
            return
        if before.content and after.content:
            await db_log_edited_message(before.id, before.channel.id, before.guild.id, before.author.id, before.content, after.content)
            log.info(f"Messaggio modificato da {before.author} in #{before.channel.name}: da '{before.content[:50]}...' a '{after.content[:50]}...'")

    async def on_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        if isinstance(error, (app_commands.MissingPermissions, app_commands.MissingRole)):
            msg = "🚫 Non hai i permessi necessari per usare questo comando."
        elif isinstance(error, app_commands.BotMissingPermissions):
            msg = "🚫 Il bot non ha i permessi necessari."
        elif isinstance(error, app_commands.CommandOnCooldown):
            msg = f"⏳ Riprova tra {error.retry_after:.1f} secondi."
        elif isinstance(error, app_commands.NoPrivateMessage):
            msg = "❌ Questo comando non funziona nei messaggi privati."
        elif isinstance(error, app_commands.CheckFailure):
            return
        else:
            log.exception(
                "Errore non gestito nel comando '%s': %s",
                getattr(interaction.command, "name", "?"), error,
            )
            msg = "❌ Si è verificato un errore imprevisto."

        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)

    async def close(self) -> None:
        log.info("Shutdown in corso…")
        for task in list(_ticket_close_tasks.values()):
            if not task.done():
                task.cancel()
        if _db_pool:
            await _db_pool.close()
            log.info("Pool PostgreSQL chiuso.")
        await super().close()


# ══════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    Config.validate()
    bot = CombinedBot()
    bot.run(Config.TOKEN, log_handler=None)
