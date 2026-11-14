import sqlite3
import time
import re
import logging
from typing import Optional, Dict, List, Any

from config import DB_PATH

logger = logging.getLogger(__name__)

# ============================================================
# اتصال امن
# ============================================================

def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA busy_timeout=30000;")
    conn.execute("PRAGMA secure_delete=ON;")
    return conn

# ============================================================
# اعتبارسنجی و Sanitize
# ============================================================

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

def sanitize_text(value, max_len: int = 500) -> Optional[str]:
    if value is None:
        return None
    text = _CONTROL_CHARS.sub("", str(value)).strip()
    if len(text) > max_len:
        text = text[:max_len]
    return text or None

def validate_telegram_id(tid) -> int:
    try:
        tid = int(tid)
    except (ValueError, TypeError):
        raise ValueError("Invalid telegram_id")
    if tid <= 0 or tid > 10_000_000_000_000:
        raise ValueError("telegram_id out of range")
    return tid

def validate_amount(amount, max_val: int = 500_000_000) -> int:
    try:
        amount = int(amount)
    except (ValueError, TypeError):
        raise ValueError("Invalid amount")
    if amount <= 0 or amount > max_val:
        raise ValueError("Amount out of range")
    return amount

def now_ts() -> int:
    return int(time.time())

# ============================================================
# ساخت جداول
# ============================================================

def init_database() -> None:
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                balance INTEGER NOT NULL DEFAULT 0,
                total_purchases INTEGER NOT NULL DEFAULT 0,
                trial_used INTEGER NOT NULL DEFAULT 0,
                is_banned INTEGER NOT NULL DEFAULT 0,
                ban_until INTEGER,
                joined_at INTEGER NOT NULL,
                last_seen_at INTEGER,
                CHECK (balance >= 0),
                CHECK (total_purchases >= 0)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS username_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL,
                username TEXT NOT NULL,
                changed_at INTEGER NOT NULL,
                FOREIGN KEY (telegram_id) REFERENCES users(telegram_id) ON DELETE CASCADE
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL,
                config_number INTEGER NOT NULL,
                config_name TEXT NOT NULL UNIQUE,
                paxiva_client_id INTEGER,
                kind TEXT NOT NULL DEFAULT 'vol' CHECK (kind IN ('vol', 'unl')),
                volume_gb REAL NOT NULL DEFAULT 0,
                days INTEGER NOT NULL DEFAULT 30,
                devices INTEGER NOT NULL DEFAULT 2,
                price_toman INTEGER NOT NULL DEFAULT 0,
                price_stars INTEGER NOT NULL DEFAULT 0,
                is_trial INTEGER NOT NULL DEFAULT 0,
                auto_renew INTEGER NOT NULL DEFAULT 0,
                state TEXT NOT NULL DEFAULT 'active',
                expires_at INTEGER,
                used_bytes INTEGER NOT NULL DEFAULT 0,
                link TEXT,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                deleted_from_list_at INTEGER,
                deleted_from_db_at INTEGER,
                FOREIGN KEY (telegram_id) REFERENCES users(telegram_id) ON DELETE CASCADE
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS wallet_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL,
                amount INTEGER NOT NULL,
                balance_before INTEGER NOT NULL,
                balance_after INTEGER NOT NULL,
                type TEXT NOT NULL,
                description TEXT,
                reference_id TEXT,
                created_at INTEGER NOT NULL,
                FOREIGN KEY (telegram_id) REFERENCES users(telegram_id) ON DELETE CASCADE
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS payment_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL,
                amount INTEGER NOT NULL,
                photo_file_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
                reviewed_by INTEGER,
                reviewed_at INTEGER,
                created_at INTEGER NOT NULL,
                FOREIGN KEY (telegram_id) REFERENCES users(telegram_id) ON DELETE CASCADE
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS stars_invoices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                payload TEXT NOT NULL UNIQUE,
                telegram_id INTEGER NOT NULL,
                volume_gb REAL NOT NULL,
                days INTEGER NOT NULL,
                devices INTEGER NOT NULL,
                amount_stars INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'paid', 'delivered', 'refunded')),
                created_at INTEGER NOT NULL,
                FOREIGN KEY (telegram_id) REFERENCES users(telegram_id) ON DELETE CASCADE
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS stars_charges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                charge_id TEXT NOT NULL UNIQUE,
                telegram_id INTEGER NOT NULL,
                payload TEXT NOT NULL,
                amount_stars INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'charged' CHECK (status IN ('charged', 'delivered', 'refunded')),
                created_at INTEGER NOT NULL,
                FOREIGN KEY (telegram_id) REFERENCES users(telegram_id) ON DELETE CASCADE
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id INTEGER NOT NULL,
                referred_id INTEGER NOT NULL UNIQUE,
                created_at INTEGER NOT NULL,
                FOREIGN KEY (referrer_id) REFERENCES users(telegram_id) ON DELETE CASCADE,
                FOREIGN KEY (referred_id) REFERENCES users(telegram_id) ON DELETE CASCADE,
                CHECK (referrer_id != referred_id)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS referral_earnings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id INTEGER NOT NULL,
                referred_id INTEGER NOT NULL,
                amount INTEGER NOT NULL,
                source TEXT,
                subscription_id INTEGER,
                created_at INTEGER NOT NULL,
                FOREIGN KEY (referrer_id) REFERENCES users(telegram_id) ON DELETE CASCADE,
                FOREIGN KEY (referred_id) REFERENCES users(telegram_id) ON DELETE CASCADE
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS discount_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL UNIQUE,
                percent INTEGER NOT NULL CHECK (percent > 0 AND percent <= 100),
                max_uses INTEGER NOT NULL,
                used_count INTEGER NOT NULL DEFAULT 0,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at INTEGER NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS discount_uses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code_id INTEGER NOT NULL,
                telegram_id INTEGER NOT NULL,
                used_at INTEGER NOT NULL,
                UNIQUE (code_id, telegram_id),
                FOREIGN KEY (code_id) REFERENCES discount_codes(id) ON DELETE CASCADE,
                FOREIGN KEY (telegram_id) REFERENCES users(telegram_id) ON DELETE CASCADE
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at INTEGER
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                level TEXT NOT NULL,
                event_type TEXT NOT NULL,
                user_id INTEGER,
                detail TEXT,
                created_at INTEGER NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS bans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL,
                banned_by INTEGER NOT NULL,
                reason TEXT,
                until INTEGER,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at INTEGER NOT NULL,
                FOREIGN KEY (telegram_id) REFERENCES users(telegram_id) ON DELETE CASCADE
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL DEFAULT 'vol' CHECK (kind IN ('vol', 'unl')),
                volume_gb REAL NOT NULL DEFAULT 0,
                days INTEGER NOT NULL DEFAULT 30,
                price_toman INTEGER NOT NULL,
                price_stars INTEGER NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at INTEGER NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_date TEXT NOT NULL UNIQUE,
                configs_sold INTEGER NOT NULL DEFAULT 0,
                revenue_toman INTEGER NOT NULL DEFAULT 0,
                active_users INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_activity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL,
                activity_date TEXT NOT NULL,
                UNIQUE (telegram_id, activity_date),
                FOREIGN KEY (telegram_id) REFERENCES users(telegram_id) ON DELETE CASCADE
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS lucky_wheel_spins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL,
                prize TEXT NOT NULL,
                prize_type TEXT NOT NULL DEFAULT 'nothing',
                config_name TEXT,
                created_at INTEGER NOT NULL,
                FOREIGN KEY (telegram_id) REFERENCES users(telegram_id) ON DELETE CASCADE
            )
        """)

        conn.execute("CREATE INDEX IF NOT EXISTS idx_subs_user ON subscriptions(telegram_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_subs_state ON subscriptions(state);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_subs_expires ON subscriptions(expires_at);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_subs_config_name ON subscriptions(config_name COLLATE NOCASE);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_wallet_user ON wallet_transactions(telegram_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pay_status ON payment_requests(status);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pay_user ON payment_requests(telegram_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_logs_created ON logs(created_at);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_logs_level ON logs(level);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_refs_referrer ON referrals(referrer_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_refs_referred ON referrals(referred_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ref_earn_referrer ON referral_earnings(referrer_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_disc_code ON discount_codes(code);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_bans_user ON bans(telegram_id, is_active);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_stars_inv_payload ON stars_invoices(payload);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_stars_chg_charge ON stars_charges(charge_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_activity_date ON user_activity(activity_date);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_wheel_telegram ON lucky_wheel_spins(telegram_id);")

# ============================================================
# تنظیمات
# ============================================================

def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    with get_connection() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

def set_setting(key: str, value: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (key, str(value), now_ts())
        )

# ============================================================
# لاگ
# ============================================================

def log_event(level: str, event_type: str, user_id: Optional[int] = None, detail: Optional[str] = None) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO logs (level, event_type, user_id, detail, created_at) VALUES (?, ?, ?, ?, ?)",
            (level, event_type, user_id, sanitize_text(detail, 1000), now_ts())
        )

# ============================================================
# کاربران
# ============================================================

def create_or_update_user(telegram_id: int, username: Optional[str] = None, first_name: Optional[str] = None) -> bool:
    telegram_id = validate_telegram_id(telegram_id)
    username = sanitize_text(username, 64)
    first_name = sanitize_text(first_name, 128)
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            existing = conn.execute("SELECT username FROM users WHERE telegram_id = ?", (telegram_id,)).fetchone()
            if existing:
                if existing["username"] != username and username:
                    conn.execute(
                        "INSERT INTO username_history (telegram_id, username, changed_at) VALUES (?, ?, ?)",
                        (telegram_id, username, now_ts())
                    )
                conn.execute(
                    "UPDATE users SET username = ?, first_name = ?, last_seen_at = ? WHERE telegram_id = ?",
                    (username, first_name, now_ts(), telegram_id)
                )
                conn.commit()
                return False
            conn.execute(
                "INSERT INTO users (telegram_id, username, first_name, joined_at, last_seen_at) VALUES (?, ?, ?, ?, ?)",
                (telegram_id, username, first_name, now_ts(), now_ts())
            )
            conn.commit()
            return True
        except Exception:
            conn.rollback()
            raise

def get_user(telegram_id: int) -> Optional[Dict[str, Any]]:
    telegram_id = validate_telegram_id(telegram_id)
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)).fetchone()
        return dict(row) if row else None

def get_user_by_username(username: str) -> Optional[Dict[str, Any]]:
    username = sanitize_text(username, 64)
    if not username:
        return None
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ? COLLATE NOCASE",
            (username.lstrip("@"),)
        ).fetchone()
        return dict(row) if row else None

def get_user_by_identifier(query: str) -> Optional[Dict[str, Any]]:
    query = sanitize_text(query, 100)
    if not query:
        return None
    raw = query.strip().lstrip("@")
    if re.fullmatch(r"[0-9]{1,15}", raw):
        try:
            return get_user(int(raw))
        except ValueError:
            return None
    return get_user_by_username(raw)

def get_user_registration_date(telegram_id: int) -> str:
    telegram_id = validate_telegram_id(telegram_id)
    with get_connection() as conn:
        row = conn.execute("SELECT joined_at FROM users WHERE telegram_id = ?", (telegram_id,)).fetchone()
        if row and row["joined_at"]:
            import datetime
            return datetime.datetime.fromtimestamp(row["joined_at"]).strftime("%Y-%m-%d")
        return "نامشخص"

def increment_total_purchases(telegram_id: int) -> None:
    telegram_id = validate_telegram_id(telegram_id)
    with get_connection() as conn:
        conn.execute("UPDATE users SET total_purchases = total_purchases + 1 WHERE telegram_id = ?", (telegram_id,))

def mark_trial_used(telegram_id: int) -> None:
    telegram_id = validate_telegram_id(telegram_id)
    with get_connection() as conn:
        conn.execute("UPDATE users SET trial_used = 1 WHERE telegram_id = ?", (telegram_id,))

def get_user_level(total_purchases: int):
    from config import LEVEL_NAMES
    if total_purchases <= 1:
        return "new", LEVEL_NAMES.get("new", "تازه‌وارد")
    elif total_purchases <= 5:
        return "prime", LEVEL_NAMES.get("prime", "پرایم")
    elif total_purchases <= 10:
        return "royal", LEVEL_NAMES.get("royal", "رویال")
    elif total_purchases <= 20:
        return "diamond", LEVEL_NAMES.get("diamond", "دایموند")
    else:
        return "legendary", LEVEL_NAMES.get("legendary", "لجندری")

# ============================================================
# شمارنده کانفیگ
# ============================================================

def reserve_config_number(is_test: bool = False) -> int:
    key = "test_counter" if is_test else "config_counter"
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
            counter = int(row["value"]) if row else 0
            if is_test:
                max_row = conn.execute("SELECT COALESCE(MAX(config_number), 0) AS mx FROM subscriptions WHERE is_trial = 1").fetchone()
            else:
                max_row = conn.execute("SELECT COALESCE(MAX(config_number), 0) AS mx FROM subscriptions WHERE is_trial = 0").fetchone()
            next_num = max(counter, int(max_row["mx"])) + 1
            conn.execute(
                "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                (key, str(next_num), now_ts())
            )
            conn.commit()
            return next_num
        except Exception:
            conn.rollback()
            raise

def release_config_number(number: int, is_test: bool = False) -> bool:
    key = "test_counter" if is_test else "config_counter"
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
            counter = int(row["value"]) if row else 0
            used = conn.execute("SELECT 1 FROM subscriptions WHERE config_number = ? AND is_trial = ?", (number, 1 if is_test else 0)).fetchone()
            if counter == number and not used:
                conn.execute("UPDATE settings SET value = ?, updated_at = ? WHERE key = ?", (str(number - 1), now_ts(), key))
                conn.commit()
                return True
            conn.rollback()
            return False
        except Exception:
            conn.rollback()
            return False

# ============================================================
# کیف پول
# ============================================================

def get_balance(telegram_id: int) -> int:
    telegram_id = validate_telegram_id(telegram_id)
    with get_connection() as conn:
        row = conn.execute("SELECT balance FROM users WHERE telegram_id = ?", (telegram_id,)).fetchone()
        return int(row["balance"]) if row else 0

def change_balance(telegram_id: int, delta: int, tx_type: str, description: str = "", reference_id: Optional[str] = None) -> bool:
    telegram_id = validate_telegram_id(telegram_id)
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute("SELECT balance FROM users WHERE telegram_id = ?", (telegram_id,)).fetchone()
            if not row:
                conn.rollback()
                return False
            before = int(row["balance"])
            after = before + delta
            if after < 0:
                conn.rollback()
                return False
            conn.execute("UPDATE users SET balance = ? WHERE telegram_id = ?", (after, telegram_id))
            conn.execute(
                "INSERT INTO wallet_transactions (telegram_id, amount, balance_before, balance_after, type, description, reference_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (telegram_id, delta, before, after, tx_type, sanitize_text(description, 500), reference_id, now_ts())
            )
            conn.commit()
            return True
        except Exception:
            conn.rollback()
            raise

def add_balance(telegram_id: int, amount: int, tx_type: str, description: str = "", reference_id: Optional[str] = None) -> bool:
    return change_balance(telegram_id, validate_amount(amount), tx_type, description, reference_id)

def deduct_balance(telegram_id: int, amount: int, tx_type: str, description: str = "", reference_id: Optional[str] = None) -> bool:
    return change_balance(telegram_id, -validate_amount(amount), tx_type, description, reference_id)

def get_wallet_transactions(telegram_id: int, limit: int = 10) -> List[Dict[str, Any]]:
    """دریافت تاریخچه تراکنش‌های کیف پول کاربر."""
    telegram_id = validate_telegram_id(telegram_id)
    try:
        limit = max(1, min(int(limit), 100))
    except (ValueError, TypeError):
        limit = 10
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM wallet_transactions WHERE telegram_id = ? ORDER BY id DESC LIMIT ?",
            (telegram_id, limit)
        ).fetchall()
        return [dict(r) for r in rows]

# ============================================================
# درخواست‌های پرداخت
# ============================================================

def create_payment_request(telegram_id: int, amount: int, photo_file_id: str) -> Optional[int]:
    telegram_id = validate_telegram_id(telegram_id)
    amount = validate_amount(amount)
    photo_file_id = sanitize_text(photo_file_id, 200)
    if not photo_file_id:
        return None
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            pending = conn.execute(
                "SELECT id FROM payment_requests WHERE telegram_id = ? AND status = 'pending'",
                (telegram_id,)
            ).fetchone()
            if pending:
                conn.rollback()
                return None
            cursor = conn.execute(
                "INSERT INTO payment_requests (telegram_id, amount, photo_file_id, status, created_at) VALUES (?, ?, ?, 'pending', ?)",
                (telegram_id, amount, photo_file_id, now_ts())
            )
            conn.commit()
            return cursor.lastrowid
        except Exception:
            conn.rollback()
            raise

def get_payment_request(payment_id: int) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM payment_requests WHERE id = ?", (payment_id,)).fetchone()
        return dict(row) if row else None

def approve_payment(payment_id: int, admin_id: int) -> bool:
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            req = conn.execute("SELECT * FROM payment_requests WHERE id = ? AND status = 'pending'", (payment_id,)).fetchone()
            if not req:
                conn.rollback()
                return False
            user = conn.execute("SELECT balance FROM users WHERE telegram_id = ?", (req["telegram_id"],)).fetchone()
            if not user:
                conn.rollback()
                return False
            before = int(user["balance"])
            after = before + int(req["amount"])
            conn.execute("UPDATE users SET balance = ? WHERE telegram_id = ?", (after, req["telegram_id"]))
            conn.execute(
                "INSERT INTO wallet_transactions (telegram_id, amount, balance_before, balance_after, type, description, created_at) "
                "VALUES (?, ?, ?, ?, 'card_payment', ?, ?)",
                (req["telegram_id"], req["amount"], before, after, f"Payment #{payment_id}", now_ts())
            )
            conn.execute(
                "UPDATE payment_requests SET status = 'approved', reviewed_by = ?, reviewed_at = ? WHERE id = ?",
                (admin_id, now_ts(), payment_id)
            )
            conn.commit()
            return True
        except Exception:
            conn.rollback()
            raise

def reject_payment(payment_id: int, admin_id: int) -> bool:
    with get_connection() as conn:
        cursor = conn.execute(
            "UPDATE payment_requests SET status = 'rejected', reviewed_by = ?, reviewed_at = ? WHERE id = ? AND status = 'pending'",
            (admin_id, now_ts(), payment_id)
        )
        return cursor.rowcount > 0

# ============================================================
# Stars
# ============================================================

def create_stars_invoice(payload: str, telegram_id: int, volume_gb: float, days: int, devices: int, amount_stars: int) -> Optional[int]:
    telegram_id = validate_telegram_id(telegram_id)
    payload = sanitize_text(payload, 100)
    if not payload or amount_stars <= 0:
        return None
    with get_connection() as conn:
        try:
            cursor = conn.execute(
                "INSERT INTO stars_invoices (payload, telegram_id, volume_gb, days, devices, amount_stars, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)",
                (payload, telegram_id, volume_gb, days, devices, amount_stars, now_ts())
            )
            conn.commit()
            return cursor.lastrowid
        except sqlite3.IntegrityError:
            conn.rollback()
            return None

def get_stars_invoice(payload: str) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM stars_invoices WHERE payload = ?", (payload,)).fetchone()
        return dict(row) if row else None

def update_stars_invoice_status(payload: str, status: str) -> bool:
    with get_connection() as conn:
        cursor = conn.execute("UPDATE stars_invoices SET status = ? WHERE payload = ?", (status, payload))
        return cursor.rowcount > 0

def register_stars_charge(charge_id: str, telegram_id: int, payload: str, amount_stars: int) -> bool:
    telegram_id = validate_telegram_id(telegram_id)
    charge_id = sanitize_text(charge_id, 200)
    if not charge_id:
        return False
    with get_connection() as conn:
        try:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO stars_charges (charge_id, telegram_id, payload, amount_stars, status, created_at) "
                "VALUES (?, ?, ?, ?, 'charged', ?)",
                (charge_id, telegram_id, payload, amount_stars, now_ts())
            )
            conn.commit()
            return cursor.rowcount > 0
        except Exception:
            conn.rollback()
            raise

def update_stars_charge_status(charge_id: str, status: str) -> bool:
    with get_connection() as conn:
        cursor = conn.execute("UPDATE stars_charges SET status = ? WHERE charge_id = ?", (status, charge_id))
        return cursor.rowcount > 0

# ============================================================
# سرویس‌ها
# ============================================================

def create_subscription(
    telegram_id: int, config_number: int, config_name: str, kind: str,
    volume_gb: float, days: int, devices: int,
    price_toman: int, price_stars: int,
    is_trial: int = 0, paxiva_client_id: Optional[int] = None, link: Optional[str] = None
) -> Optional[int]:
    telegram_id = validate_telegram_id(telegram_id)
    with get_connection() as conn:
        try:
            cursor = conn.execute(
                """INSERT INTO subscriptions 
                (telegram_id, config_number, config_name, kind, volume_gb, days, devices,
                 price_toman, price_stars, is_trial, paxiva_client_id, link, state, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)""",
                (telegram_id, config_number, config_name, kind, volume_gb, days, devices,
                 price_toman, price_stars, is_trial, paxiva_client_id, link, now_ts(), now_ts())
            )
            conn.commit()
            return cursor.lastrowid
        except Exception:
            conn.rollback()
            raise

def get_user_subscriptions(telegram_id: int, only_visible: bool = True) -> List[Dict[str, Any]]:
    telegram_id = validate_telegram_id(telegram_id)
    with get_connection() as conn:
        query = "SELECT * FROM subscriptions WHERE telegram_id = ?"
        if only_visible:
            query += " AND deleted_from_list_at IS NULL"
        query += " ORDER BY id DESC"
        rows = conn.execute(query, (telegram_id,)).fetchall()
        return [dict(r) for r in rows]

def get_subscription(subscription_id: int) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM subscriptions WHERE id = ?", (subscription_id,)).fetchone()
        return dict(row) if row else None

def update_subscription_state(subscription_id: int, state: str, expires_at: Optional[int] = None, used_bytes: Optional[int] = None) -> bool:
    with get_connection() as conn:
        cursor = conn.execute(
            "UPDATE subscriptions SET state = ?, expires_at = COALESCE(?, expires_at), used_bytes = COALESCE(?, used_bytes), updated_at = ? WHERE id = ?",
            (state, expires_at, used_bytes, now_ts(), subscription_id)
        )
        return cursor.rowcount > 0

def update_subscription_volume(subscription_id: int, new_volume: float) -> bool:
    with get_connection() as conn:
        cursor = conn.execute(
            "UPDATE subscriptions SET volume_gb = ?, updated_at = ? WHERE id = ?",
            (new_volume, now_ts(), subscription_id)
        )
        return cursor.rowcount > 0

def toggle_auto_renew(subscription_id: int, enabled: bool) -> bool:
    with get_connection() as conn:
        cursor = conn.execute(
            "UPDATE subscriptions SET auto_renew = ?, updated_at = ? WHERE id = ?",
            (1 if enabled else 0, now_ts(), subscription_id)
        )
        return cursor.rowcount > 0

def delete_subscription_from_list(subscription_id: int) -> bool:
    with get_connection() as conn:
        cursor = conn.execute(
            "UPDATE subscriptions SET deleted_from_list_at = ? WHERE id = ?",
            (now_ts(), subscription_id)
        )
        return cursor.rowcount > 0

def hard_delete_subscription(subscription_id: int) -> bool:
    with get_connection() as conn:
        cursor = conn.execute("DELETE FROM subscriptions WHERE id = ?", (subscription_id,))
        return cursor.rowcount > 0

# ============================================================
# رفرال و پورسانت
# ============================================================

def set_referral(referrer_id: int, referred_id: int) -> bool:
    referrer_id = validate_telegram_id(referrer_id)
    referred_id = validate_telegram_id(referred_id)
    if referrer_id == referred_id:
        return False
    with get_connection() as conn:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO referrals (referrer_id, referred_id, created_at) VALUES (?, ?, ?)",
            (referrer_id, referred_id, now_ts())
        )
        return cursor.rowcount > 0

def get_referrer(referred_id: int) -> Optional[int]:
    referred_id = validate_telegram_id(referred_id)
    with get_connection() as conn:
        row = conn.execute("SELECT referrer_id FROM referrals WHERE referred_id = ?", (referred_id,)).fetchone()
        return int(row["referrer_id"]) if row else None

def add_referral_commission(referred_id: int, purchase_amount: int, subscription_id: int, source: str = "purchase") -> bool:
    referrer_id = get_referrer(referred_id)
    if not referrer_id:
        return False
    commission = int(purchase_amount * 0.05)
    if commission <= 0:
        return False
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(
                "INSERT INTO referral_earnings (referrer_id, referred_id, amount, source, subscription_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (referrer_id, referred_id, commission, source, subscription_id, now_ts())
            )
            row = conn.execute("SELECT balance FROM users WHERE telegram_id = ?", (referrer_id,)).fetchone()
            if row:
                before = int(row["balance"])
                after = before + commission
                conn.execute("UPDATE users SET balance = ? WHERE telegram_id = ?", (after, referrer_id))
                conn.execute(
                    "INSERT INTO wallet_transactions (telegram_id, amount, balance_before, balance_after, type, description, reference_id, created_at) "
                    "VALUES (?, ?, ?, ?, 'referral_commission', ?, ?, ?)",
                    (referrer_id, commission, before, after, f"پورسانت ۵٪ از خرید {referred_id}", str(subscription_id), now_ts())
                )
            conn.commit()
            return True
        except Exception:
            conn.rollback()
            raise

def get_referral_stats(telegram_id: int) -> Dict[str, Any]:
    telegram_id = validate_telegram_id(telegram_id)
    with get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) AS c FROM referrals WHERE referrer_id = ?", (telegram_id,)).fetchone()["c"]
        total = conn.execute("SELECT COALESCE(SUM(amount), 0) AS s FROM referral_earnings WHERE referrer_id = ?", (telegram_id,)).fetchone()["s"]
        return {"count": int(count), "total_earnings": int(total)}

def get_user_referrals(referrer_id: int) -> List[Dict[str, Any]]:
    referrer_id = validate_telegram_id(referrer_id)
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM referrals WHERE referrer_id = ? ORDER BY id DESC", (referrer_id,)).fetchall()
        return [dict(r) for r in rows]

def get_referral_details(referrer_id: int, limit: int = 100) -> List[Dict[str, Any]]:
    referrer_id = validate_telegram_id(referrer_id)
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM referral_earnings WHERE referrer_id = ? ORDER BY id DESC LIMIT ?", (referrer_id, limit)).fetchall()
        return [dict(r) for r in rows]

# ============================================================
# کد تخفیف
# ============================================================

def create_discount_code(code: str, percent: int, max_uses: int) -> Optional[int]:
    code = sanitize_text(code, 50)
    if not code or not (1 <= percent <= 100) or max_uses <= 0:
        return None
    with get_connection() as conn:
        try:
            cursor = conn.execute(
                "INSERT INTO discount_codes (code, percent, max_uses, used_count, is_active, created_at) VALUES (?, ?, ?, 0, 1, ?)",
                (code, percent, max_uses, now_ts())
            )
            conn.commit()
            return cursor.lastrowid
        except sqlite3.IntegrityError:
            conn.rollback()
            return None

def get_discount_code(code: str) -> Optional[Dict[str, Any]]:
    code = sanitize_text(code, 50)
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM discount_codes WHERE code = ? COLLATE NOCASE", (code,)).fetchone()
        return dict(row) if row else None

def consume_discount_code(code_id: int, telegram_id: int) -> bool:
    telegram_id = validate_telegram_id(telegram_id)
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            code = conn.execute("SELECT * FROM discount_codes WHERE id = ? AND is_active = 1", (code_id,)).fetchone()
            if not code or code["used_count"] >= code["max_uses"]:
                conn.rollback()
                return False
            used = conn.execute("SELECT 1 FROM discount_uses WHERE code_id = ? AND telegram_id = ?", (code_id, telegram_id)).fetchone()
            if used:
                conn.rollback()
                return False
            conn.execute("INSERT INTO discount_uses (code_id, telegram_id, used_at) VALUES (?, ?, ?)", (code_id, telegram_id, now_ts()))
            new_count = code["used_count"] + 1
            active = 0 if new_count >= code["max_uses"] else 1
            conn.execute("UPDATE discount_codes SET used_count = ?, is_active = ? WHERE id = ?", (new_count, active, code_id))
            conn.commit()
            return True
        except Exception:
            conn.rollback()
            raise

# ============================================================
# بن
# ============================================================

def ban_user(telegram_id: int, admin_id: int, reason: str = "", until: Optional[int] = None) -> bool:
    telegram_id = validate_telegram_id(telegram_id)
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute("UPDATE bans SET is_active = 0 WHERE telegram_id = ?", (telegram_id,))
            conn.execute(
                "INSERT INTO bans (telegram_id, banned_by, reason, until, is_active, created_at) VALUES (?, ?, ?, ?, 1, ?)",
                (telegram_id, admin_id, sanitize_text(reason, 500), until, now_ts())
            )
            conn.execute("UPDATE users SET is_banned = 1, ban_until = ? WHERE telegram_id = ?", (until, telegram_id))
            conn.commit()
            return True
        except Exception:
            conn.rollback()
            raise

def unban_user(telegram_id: int) -> bool:
    telegram_id = validate_telegram_id(telegram_id)
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute("UPDATE bans SET is_active = 0 WHERE telegram_id = ? AND is_active = 1", (telegram_id,))
            conn.execute("UPDATE users SET is_banned = 0, ban_until = NULL WHERE telegram_id = ?", (telegram_id,))
            conn.commit()
            return True
        except Exception:
            conn.rollback()
            raise

def is_banned(telegram_id: int) -> bool:
    telegram_id = validate_telegram_id(telegram_id)
    with get_connection() as conn:
        row = conn.execute("SELECT ban_until FROM users WHERE telegram_id = ?", (telegram_id,)).fetchone()
        if not row:
            return False
        if not row["ban_until"]:
            return False
        if row["ban_until"] < now_ts():
            unban_user(telegram_id)
            return False
        return True

# ============================================================
# محصولات
# ============================================================

def create_product(kind: str, volume_gb: float, days: int, price_toman: int, price_stars: int) -> Optional[int]:
    with get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO products (kind, volume_gb, days, price_toman, price_stars, is_active, created_at) VALUES (?, ?, ?, ?, ?, 1, ?)",
            (kind, volume_gb, days, price_toman, price_stars, now_ts())
        )
        return cursor.lastrowid

def list_products(active_only: bool = True) -> List[Dict[str, Any]]:
    with get_connection() as conn:
        query = "SELECT * FROM products"
        if active_only:
            query += " WHERE is_active = 1"
        query += " ORDER BY id DESC"
        rows = conn.execute(query).fetchall()
        return [dict(r) for r in rows]

# ============================================================
# گزارش و DAU
# ============================================================

def record_user_activity(telegram_id: int) -> None:
    telegram_id = validate_telegram_id(telegram_id)
    today = time.strftime("%Y-%m-%d")
    with get_connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO user_activity (telegram_id, activity_date) VALUES (?, ?)",
            (telegram_id, today)
        )

def save_daily_report(report_date: str, configs_sold: int, revenue_toman: int) -> None:
    with get_connection() as conn:
        active = conn.execute("SELECT COUNT(DISTINCT telegram_id) AS c FROM user_activity WHERE activity_date = ?", (report_date,)).fetchone()["c"]
        conn.execute(
            "INSERT OR REPLACE INTO daily_reports (report_date, configs_sold, revenue_toman, active_users, created_at) VALUES (?, ?, ?, ?, ?)",
            (report_date, configs_sold, revenue_toman, active, now_ts())
        )

# ============================================================
# آمار
# ============================================================

def get_admin_stats() -> Dict[str, Any]:
    with get_connection() as conn:
        total_users = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
        banned = conn.execute("SELECT COUNT(*) AS c FROM users WHERE is_banned = 1").fetchone()["c"]
        total_purchases = conn.execute("SELECT COALESCE(SUM(total_purchases), 0) AS s FROM users").fetchone()["s"]
        total_balance = conn.execute("SELECT COALESCE(SUM(balance), 0) AS s FROM users").fetchone()["s"]
        total_revenue = conn.execute("SELECT COALESCE(SUM(price_toman), 0) AS s FROM subscriptions").fetchone()["s"]
        total_stars = conn.execute("SELECT COALESCE(SUM(amount_stars), 0) AS s FROM stars_charges WHERE status != 'refunded'").fetchone()["s"]
        return {
            "total_users": int(total_users),
            "banned_users": int(banned),
            "total_purchases": int(total_purchases),
            "total_balance": int(total_balance),
            "total_revenue_toman": int(total_revenue),
            "total_stars": int(total_stars),
        }

# ============================================================
# گردونه شانس
# ============================================================

def get_last_wheel_spin(telegram_id: int) -> Optional[Dict[str, Any]]:
    telegram_id = validate_telegram_id(telegram_id)
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM lucky_wheel_spins WHERE telegram_id = ? ORDER BY id DESC LIMIT 1", (telegram_id,)).fetchone()
        return dict(row) if row else None

def can_spin_wheel(telegram_id: int, cooldown_hours: int = 24) -> bool:
    last = get_last_wheel_spin(telegram_id)
    if not last:
        return True
    import datetime
    try:
        created = datetime.datetime.fromtimestamp(last["created_at"])
        elapsed = (datetime.datetime.now() - created).total_seconds()
        return elapsed >= cooldown_hours * 3600
    except Exception:
        return True

def record_wheel_spin(telegram_id: int, prize: str, prize_type: str, config_name: Optional[str] = None) -> Optional[int]:
    telegram_id = validate_telegram_id(telegram_id)
    prize = sanitize_text(prize, 100) or "?"
    prize_type = sanitize_text(prize_type, 20) or "nothing"
    config_name = sanitize_text(config_name, 100)
    with get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO lucky_wheel_spins (telegram_id, prize, prize_type, config_name, created_at) VALUES (?, ?, ?, ?, ?)",
            (telegram_id, prize, prize_type, config_name, now_ts())
        )
        return cursor.lastrowid