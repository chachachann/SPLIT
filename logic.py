import os
import re
import sqlite3
import hashlib
import secrets
from datetime import datetime, timedelta
from html import escape

DB_PATH = r"C:\SPLIT\db\database.db"
NEWS_IMAGE_DIR = os.path.join(os.path.dirname(__file__), "static", "uploads", "news")
NEWS_IMAGE_WEB_PATH = "uploads/news"
CHAT_ATTACHMENT_DIR = os.path.join(os.path.dirname(__file__), "static", "uploads", "chat")
CHAT_ATTACHMENT_WEB_PATH = "uploads/chat"
ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
ALLOWED_CHAT_ATTACHMENT_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".heic",
    ".heif",
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".txt",
    ".csv",
    ".zip",
    ".rar",
}
REMEMBER_ME_DAYS = 7
CHAT_PRESENCE_WINDOW_SECONDS = 150
CHAT_CHANNEL_COUNT = 10
DEFAULT_ROLES = (
    ("SuperAdmin", 1),
    ("Admin", 0),
    ("Staff", 0),
    ("Developer", 0),
)
DEFAULT_MARQUEE_STYLE = "broadcast"
MARQUEE_STYLE_CHOICES = (
    ("broadcast", "Broadcast"),
    ("signal", "Signal"),
    ("bulletin", "Bulletin"),
)


def timestamp_now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def parse_timestamp(value):
    try:
        return datetime.strptime(value or "", "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return None


def normalize_role_names(role_names):
    seen = set()
    normalized = []

    for role_name in role_names or []:
        clean_name = " ".join((role_name or "").split())
        if not clean_name:
            continue

        role_key = clean_name.casefold()
        if role_key in seen:
            continue

        seen.add(role_key)
        normalized.append(clean_name)

    return normalized


def ensure_db_folder():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)


def ensure_news_image_folder():
    os.makedirs(NEWS_IMAGE_DIR, exist_ok=True)


def ensure_chat_attachment_folder():
    os.makedirs(CHAT_ATTACHMENT_DIR, exist_ok=True)


def connect_db():
    ensure_db_folder()
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def fetch_role_by_name(connection, role_name):
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT id, name, is_locked, created_at
        FROM roles
        WHERE lower(name) = lower(?)
        """,
        (role_name,),
    )
    return cursor.fetchone()


def ensure_role(connection, role_name, is_locked=0):
    existing_role = fetch_role_by_name(connection, role_name)
    if existing_role:
        if is_locked and not existing_role["is_locked"]:
            connection.execute(
                """
                UPDATE roles
                SET is_locked = 1
                WHERE id = ?
                """,
                (existing_role["id"],),
            )
        return existing_role["id"], existing_role["name"]

    cursor = connection.cursor()
    cursor.execute(
        """
        INSERT INTO roles (name, is_locked, created_at)
        VALUES (?, ?, ?)
        """,
        (role_name, 1 if is_locked else 0, timestamp_now()),
    )
    return cursor.lastrowid, role_name


def seed_default_roles(connection):
    for role_name, is_locked in DEFAULT_ROLES:
        ensure_role(connection, role_name, is_locked=is_locked)


def migrate_legacy_user_roles(connection):
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT id, userlevel
        FROM users
        """
    )

    for row in cursor.fetchall():
        legacy_roles = normalize_role_names((row["userlevel"] or "").replace(";", ",").split(","))
        for legacy_role in legacy_roles:
            role_id, _ = ensure_role(connection, legacy_role, is_locked=1 if legacy_role.casefold() == "superadmin" else 0)
            cursor.execute(
                """
                INSERT OR IGNORE INTO user_roles (user_id, role_id)
                VALUES (?, ?)
                """,
                (row["id"], role_id),
            )


def init_db():
    connection = connect_db()
    cursor = connection.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password TEXT,
            designation TEXT,
            userlevel TEXT,
            fullname TEXT,
            date_created TEXT
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS buttons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            route TEXT,
            required_role TEXT
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS roles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            is_locked INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS user_roles (
            user_id INTEGER NOT NULL,
            role_id INTEGER NOT NULL,
            PRIMARY KEY (user_id, role_id)
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS account_modifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            target_username TEXT NOT NULL,
            target_fullname TEXT NOT NULL,
            actor_username TEXT NOT NULL,
            action TEXT NOT NULL,
            details TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS news_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            slug TEXT NOT NULL UNIQUE,
            summary TEXT,
            content TEXT NOT NULL,
            author_username TEXT NOT NULL,
            author_fullname TEXT,
            updated_by_fullname TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS remember_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            selector TEXT NOT NULL UNIQUE,
            token_hash TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS marquee_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            style_key TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS marquee_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message TEXT NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            target_role TEXT NOT NULL,
            style_key TEXT NOT NULL DEFAULT 'info',
            link_url TEXT,
            created_by_username TEXT,
            created_by_fullname TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS notification_user_states (
            username TEXT NOT NULL,
            notification_key TEXT NOT NULL,
            is_read INTEGER NOT NULL DEFAULT 0,
            is_hidden INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (username, notification_key)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_threads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room_key TEXT NOT NULL UNIQUE,
            thread_type TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            role_name TEXT,
            is_enabled INTEGER NOT NULL DEFAULT 1,
            created_by_username TEXT,
            updated_by_username TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_thread_members (
            thread_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            joined_at TEXT NOT NULL,
            last_read_at TEXT,
            PRIMARY KEY (thread_id, username)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            thread_id INTEGER NOT NULL,
            sender_username TEXT NOT NULL,
            sender_fullname TEXT,
            body TEXT,
            attachment_path TEXT,
            attachment_name TEXT,
            attachment_kind TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS user_presence (
            username TEXT PRIMARY KEY,
            last_seen_at TEXT NOT NULL,
            last_login_at TEXT,
            heartbeat_source TEXT
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_chat_threads_type ON chat_threads(thread_type)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_chat_messages_thread_created ON chat_messages(thread_id, created_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_chat_members_username ON chat_thread_members(username)")
    connection.commit()

    cursor.execute("PRAGMA table_info(users)")
    user_columns = {row["name"] for row in cursor.fetchall()}
    if "last_login_at" not in user_columns:
        cursor.execute("ALTER TABLE users ADD COLUMN last_login_at TEXT")

    cursor.execute("PRAGMA table_info(news_posts)")
    news_post_columns = {row["name"] for row in cursor.fetchall()}
    if "author_fullname" not in news_post_columns:
        cursor.execute("ALTER TABLE news_posts ADD COLUMN author_fullname TEXT")
    if "updated_by_fullname" not in news_post_columns:
        cursor.execute("ALTER TABLE news_posts ADD COLUMN updated_by_fullname TEXT")
    if "is_archived" not in news_post_columns:
        cursor.execute("ALTER TABLE news_posts ADD COLUMN is_archived INTEGER NOT NULL DEFAULT 0")
    if "archived_at" not in news_post_columns:
        cursor.execute("ALTER TABLE news_posts ADD COLUMN archived_at TEXT")

    cursor.execute("PRAGMA table_info(marquee_items)")
    marquee_columns = {row["name"] for row in cursor.fetchall()}
    if "is_archived" not in marquee_columns:
        cursor.execute("ALTER TABLE marquee_items ADD COLUMN is_archived INTEGER NOT NULL DEFAULT 0")
    if "archived_at" not in marquee_columns:
        cursor.execute("ALTER TABLE marquee_items ADD COLUMN archived_at TEXT")

    cursor.execute("PRAGMA table_info(notifications)")
    notification_columns = {row["name"] for row in cursor.fetchall()}
    if "link_url" not in notification_columns:
        cursor.execute("ALTER TABLE notifications ADD COLUMN link_url TEXT")
    if "created_by_username" not in notification_columns:
        cursor.execute("ALTER TABLE notifications ADD COLUMN created_by_username TEXT")
    if "created_by_fullname" not in notification_columns:
        cursor.execute("ALTER TABLE notifications ADD COLUMN created_by_fullname TEXT")
    if "is_archived" not in notification_columns:
        cursor.execute("ALTER TABLE notifications ADD COLUMN is_archived INTEGER NOT NULL DEFAULT 0")
    if "archived_at" not in notification_columns:
        cursor.execute("ALTER TABLE notifications ADD COLUMN archived_at TEXT")

    cursor.execute("PRAGMA table_info(chat_threads)")
    chat_thread_columns = {row["name"] for row in cursor.fetchall()}
    if "role_name" not in chat_thread_columns:
        cursor.execute("ALTER TABLE chat_threads ADD COLUMN role_name TEXT")
    if "is_enabled" not in chat_thread_columns:
        cursor.execute("ALTER TABLE chat_threads ADD COLUMN is_enabled INTEGER NOT NULL DEFAULT 1")
    if "created_by_username" not in chat_thread_columns:
        cursor.execute("ALTER TABLE chat_threads ADD COLUMN created_by_username TEXT")
    if "updated_by_username" not in chat_thread_columns:
        cursor.execute("ALTER TABLE chat_threads ADD COLUMN updated_by_username TEXT")

    cursor.execute("SELECT id FROM users WHERE username = ?", ("RO_Admin",))
    if not cursor.fetchone():
        cursor.execute(
            """
            INSERT INTO users (username, password, designation, userlevel, fullname, date_created)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("RO_Admin", "1234", "admin", "SuperAdmin", "Regional Admin", timestamp_now()),
        )
        connection.commit()

    seed_default_roles(connection)
    migrate_legacy_user_roles(connection)
    ensure_chat_defaults(connection)

    default_buttons = [
        ("Account Manager", "/account-manager", "SuperAdmin"),
        ("Config", "/settings", "SuperAdmin"),
        ("Reports", "/reports", "Admin"),
        ("Users", "/users", "Admin"),
        ("Logs", "/logs", "SuperAdmin"),
    ]

    for button_name, route, required_role in default_buttons:
        cursor.execute("SELECT id FROM buttons WHERE name = ?", (button_name,))
        if not cursor.fetchone():
            cursor.execute(
                """
                INSERT INTO buttons (name, route, required_role)
                VALUES (?, ?, ?)
                """,
                (button_name, route, required_role),
            )

    cursor.execute("SELECT id FROM marquee_settings WHERE id = 1")
    if not cursor.fetchone():
        cursor.execute(
            """
            INSERT INTO marquee_settings (id, style_key, updated_at)
            VALUES (1, ?, ?)
            """,
            (DEFAULT_MARQUEE_STYLE, timestamp_now()),
        )

    cursor.execute("SELECT COUNT(*) AS total FROM marquee_items")
    if cursor.fetchone()["total"] == 0:
        default_marquee_items = [
            ("Dedicated website of DAR-NIR for Project SPLIT automation.", 1),
            ("Use your assigned credentials to access the system.", 2),
            ("Contact the administrator if you need account assistance.", 3),
        ]
        cursor.executemany(
            """
            INSERT INTO marquee_items (message, sort_order, created_at)
            VALUES (?, ?, ?)
            """,
            [(message, sort_order, timestamp_now()) for message, sort_order in default_marquee_items],
        )

    cursor.execute(
        """
        UPDATE news_posts
        SET author_fullname = COALESCE(
                NULLIF(author_fullname, ''),
                (SELECT fullname FROM users WHERE users.username = news_posts.author_username),
                author_username
            ),
            updated_by_fullname = COALESCE(
                NULLIF(updated_by_fullname, ''),
                NULLIF(author_fullname, ''),
                (SELECT fullname FROM users WHERE users.username = news_posts.author_username),
                author_username
            )
        """
    )

    connection.commit()
    connection.close()


def ensure_chat_defaults(connection):
    ensure_chat_attachment_folder()
    cursor = connection.cursor()
    now = timestamp_now()

    for channel_number in range(1, CHAT_CHANNEL_COUNT + 1):
        room_key = f"channel:{channel_number}"
        cursor.execute("SELECT id FROM chat_threads WHERE room_key = ?", (room_key,))
        if cursor.fetchone():
            continue

        cursor.execute(
            """
            INSERT INTO chat_threads (
                room_key,
                thread_type,
                title,
                description,
                role_name,
                is_enabled,
                created_by_username,
                updated_by_username,
                created_at,
                updated_at
            )
            VALUES (?, 'channel', ?, ?, NULL, 1, 'System', 'System', ?, ?)
            """,
            (room_key, f"Channel {channel_number}", f"Public room {channel_number}", now, now),
        )

    cursor.execute("SELECT name FROM roles ORDER BY name COLLATE NOCASE")
    for row in cursor.fetchall():
        role_name = row["name"]
        room_key = f"role:{role_name.casefold()}"
        cursor.execute("SELECT id FROM chat_threads WHERE room_key = ?", (room_key,))
        existing = cursor.fetchone()
        if existing:
            cursor.execute(
                """
                UPDATE chat_threads
                SET role_name = COALESCE(NULLIF(role_name, ''), ?)
                WHERE id = ?
                """,
                (role_name, existing["id"]),
            )
            continue

        cursor.execute(
            """
            INSERT INTO chat_threads (
                room_key,
                thread_type,
                title,
                description,
                role_name,
                is_enabled,
                created_by_username,
                updated_by_username,
                created_at,
                updated_at
            )
            VALUES (?, 'role', ?, ?, ?, 1, 'System', 'System', ?, ?)
            """,
            (room_key, f"{role_name} Group", f"Role room for {role_name}", role_name, now, now),
        )


def build_direct_room_key(username_a, username_b):
    participants = sorted(
        [(username_a or "").strip().casefold(), (username_b or "").strip().casefold()]
    )
    return f"dm:{participants[0]}|{participants[1]}"


def build_presence_state(last_seen_at, last_login_at):
    now = datetime.now()
    last_seen_dt = parse_timestamp(last_seen_at)
    last_login_dt = parse_timestamp(last_login_at)
    is_online = bool(
        last_seen_dt and (now - last_seen_dt).total_seconds() <= CHAT_PRESENCE_WINDOW_SECONDS
    )
    return {
        "status": "online" if is_online else "offline",
        "is_online": is_online,
        "last_seen_at": last_seen_at or "",
        "last_login_at": last_login_at or "",
        "last_activity_at": last_seen_at or last_login_at or "",
        "status_label": "Online" if is_online else "Offline",
        "last_seen_label": last_seen_at or (last_login_at or "No login recorded"),
        "last_login_label": last_login_at or "No login recorded",
    }


def record_user_login(username):
    clean_username = (username or "").strip()
    if not clean_username:
        return

    now = timestamp_now()
    connection = connect_db()
    connection.execute(
        """
        UPDATE users
        SET last_login_at = ?
        WHERE lower(username) = lower(?)
        """,
        (now, clean_username),
    )
    connection.execute(
        """
        INSERT INTO user_presence (username, last_seen_at, last_login_at, heartbeat_source)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(username) DO UPDATE SET
            last_seen_at = excluded.last_seen_at,
            last_login_at = excluded.last_login_at,
            heartbeat_source = excluded.heartbeat_source
        """,
        (clean_username, now, now, "login"),
    )
    connection.commit()
    connection.close()


def mark_user_presence(username, source="poll"):
    clean_username = (username or "").strip()
    if not clean_username:
        return

    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT last_login_at
        FROM users
        WHERE lower(username) = lower(?)
        """,
        (clean_username,),
    )
    user_row = cursor.fetchone()
    if not user_row:
        connection.close()
        return

    now = timestamp_now()
    connection.execute(
        """
        INSERT INTO user_presence (username, last_seen_at, last_login_at, heartbeat_source)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(username) DO UPDATE SET
            last_seen_at = excluded.last_seen_at,
            last_login_at = COALESCE(user_presence.last_login_at, excluded.last_login_at),
            heartbeat_source = excluded.heartbeat_source
        """,
        (clean_username, now, user_row["last_login_at"], source),
    )
    connection.commit()
    connection.close()


def get_presence_snapshot_map(connection):
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT
            u.username,
            u.last_login_at,
            p.last_seen_at,
            p.last_login_at AS presence_last_login_at
        FROM users u
        LEFT JOIN user_presence p ON lower(p.username) = lower(u.username)
        """
    )
    snapshot = {}
    for row in cursor.fetchall():
        state = build_presence_state(row["last_seen_at"], row["last_login_at"] or row["presence_last_login_at"])
        snapshot[row["username"].casefold()] = state
    return snapshot


def ensure_thread_memberships_for_user(connection, username, role_names):
    clean_username = (username or "").strip()
    if not clean_username:
        return

    normalized_roles = {role.casefold() for role in (role_names or [])}
    is_superadmin_role = "superadmin" in normalized_roles
    cursor = connection.cursor()
    ensure_chat_defaults(connection)

    if is_superadmin_role:
        cursor.execute(
            """
            SELECT id
            FROM chat_threads
            WHERE (thread_type = 'channel' OR thread_type = 'role') AND is_enabled = 1
            """
        )
    else:
        accessible_roles = [role for role in normalized_roles]
        role_clause = ""
        params = []
        if accessible_roles:
            placeholders = ", ".join("?" for _ in accessible_roles)
            role_clause = f" OR (thread_type = 'role' AND is_enabled = 1 AND lower(role_name) IN ({placeholders}))"
            params.extend(accessible_roles)
        cursor.execute(
            f"""
            SELECT id
            FROM chat_threads
            WHERE (thread_type = 'channel' AND is_enabled = 1){role_clause}
            """,
            tuple(params),
        )

    thread_ids = [row["id"] for row in cursor.fetchall()]
    if not thread_ids:
        return

    now = timestamp_now()
    cursor.executemany(
        """
        INSERT OR IGNORE INTO chat_thread_members (thread_id, username, joined_at, last_read_at)
        VALUES (?, ?, ?, ?)
        """,
        [(thread_id, clean_username, now, now) for thread_id in thread_ids],
    )


def ensure_direct_thread(connection, username, other_username):
    clean_username = (username or "").strip()
    clean_other_username = (other_username or "").strip()
    if not clean_username or not clean_other_username:
        return None, None, "Direct message target is required."
    if clean_username.casefold() == clean_other_username.casefold():
        return None, None, "You cannot open a direct chat with yourself."

    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT username, fullname, designation, last_login_at
        FROM users
        WHERE lower(username) IN (lower(?), lower(?))
        """,
        (clean_username, clean_other_username),
    )
    users = {row["username"].casefold(): dict(row) for row in cursor.fetchall()}
    current_user = users.get(clean_username.casefold())
    other_user = users.get(clean_other_username.casefold())
    if not current_user or not other_user:
        return None, None, "User not found."

    room_key = build_direct_room_key(current_user["username"], other_user["username"])
    cursor.execute(
        """
        SELECT *
        FROM chat_threads
        WHERE room_key = ?
        """,
        (room_key,),
    )
    thread = cursor.fetchone()
    now = timestamp_now()
    if not thread:
        cursor.execute(
            """
            INSERT INTO chat_threads (
                room_key,
                thread_type,
                title,
                description,
                role_name,
                is_enabled,
                created_by_username,
                updated_by_username,
                created_at,
                updated_at
            )
            VALUES (?, 'direct', ?, ?, NULL, 1, ?, ?, ?, ?)
            """,
            (room_key, "Direct Message", "", current_user["username"], current_user["username"], now, now),
        )
        thread_id = cursor.lastrowid
        cursor.executemany(
            """
            INSERT OR IGNORE INTO chat_thread_members (thread_id, username, joined_at, last_read_at)
            VALUES (?, ?, ?, ?)
            """,
            [
                (thread_id, current_user["username"], now, now),
                (thread_id, other_user["username"], now, None),
            ],
        )
        cursor.execute("SELECT * FROM chat_threads WHERE id = ?", (thread_id,))
        thread = cursor.fetchone()
    else:
        thread_id = thread["id"]
        cursor.executemany(
            """
            INSERT OR IGNORE INTO chat_thread_members (thread_id, username, joined_at, last_read_at)
            VALUES (?, ?, ?, ?)
            """,
            [
                (thread_id, current_user["username"], now, now),
                (thread_id, other_user["username"], now, None),
            ],
        )

    return dict(thread), other_user, ""


def resolve_chat_thread(connection, username, role_names, thread_type, target):
    clean_username = (username or "").strip()
    normalized_roles = {role.casefold() for role in (role_names or [])}
    ensure_chat_defaults(connection)
    cursor = connection.cursor()

    if thread_type == "direct":
        return ensure_direct_thread(connection, clean_username, target)

    if thread_type == "channel":
        if (target or "").startswith("channel:"):
            room_key = target
        else:
            try:
                room_key = f"channel:{int(target)}"
            except (TypeError, ValueError):
                return None, None, "Channel not found."
        cursor.execute(
            """
            SELECT *
            FROM chat_threads
            WHERE room_key = ? AND thread_type = 'channel'
            """,
            (room_key,),
        )
        thread = cursor.fetchone()
        if not thread:
            return None, None, "Channel not found."
        if not thread["is_enabled"]:
            return None, None, "This channel is currently disabled."
        return dict(thread), None, ""

    if thread_type == "role":
        room_key = target if (target or "").startswith("role:") else f"role:{(target or '').strip().casefold()}"
        cursor.execute(
            """
            SELECT *
            FROM chat_threads
            WHERE room_key = ? AND thread_type = 'role'
            """,
            (room_key,),
        )
        thread = cursor.fetchone()
        if not thread:
            return None, None, "Role group not found."
        if not thread["is_enabled"]:
            return None, None, "This role group is currently disabled."
        if "superadmin" not in normalized_roles and (thread["role_name"] or "").casefold() not in normalized_roles:
            return None, None, "You do not have access to this role group."
        return dict(thread), None, ""

    return None, None, "Unsupported chat type."


def ensure_member_record(connection, thread_id, username, *, initial_read_at=None):
    clean_username = (username or "").strip()
    if not clean_username:
        return
    now = timestamp_now()
    connection.execute(
        """
        INSERT OR IGNORE INTO chat_thread_members (thread_id, username, joined_at, last_read_at)
        VALUES (?, ?, ?, ?)
        """,
        (thread_id, clean_username, now, initial_read_at),
    )


def mark_chat_thread_read(connection, thread_id, username):
    clean_username = (username or "").strip()
    if not clean_username:
        return
    ensure_member_record(connection, thread_id, clean_username, initial_read_at=timestamp_now())
    connection.execute(
        """
        UPDATE chat_thread_members
        SET last_read_at = ?
        WHERE thread_id = ? AND lower(username) = lower(?)
        """,
        (timestamp_now(), thread_id, clean_username),
    )


def build_chat_message_preview(body, attachment_name=None, limit=72):
    text = " ".join((body or "").split())
    if text:
        if len(text) > limit:
            text = text[: limit - 3].rstrip() + "..."
        return text
    if attachment_name:
        return attachment_name
    return "No messages yet"


def get_chat_overview(username, role_names):
    clean_username = (username or "").strip()
    if not clean_username:
        return {
            "channels": [],
            "role_groups": [],
            "direct_threads": [],
            "users": [],
            "unread_total": 0,
        }

    connection = connect_db()
    ensure_chat_defaults(connection)
    ensure_thread_memberships_for_user(connection, clean_username, role_names)
    cursor = connection.cursor()
    normalized_roles = {role.casefold() for role in (role_names or [])}
    is_superadmin_role = "superadmin" in normalized_roles

    cursor.execute(
        """
        SELECT t.*, m.last_read_at
        FROM chat_threads t
        LEFT JOIN chat_thread_members m
            ON m.thread_id = t.id AND lower(m.username) = lower(?)
        WHERE t.thread_type = 'channel' AND t.is_enabled = 1
        ORDER BY CAST(substr(t.room_key, 9) AS INTEGER), t.id
        """,
        (clean_username,),
    )
    channel_rows = [dict(row) for row in cursor.fetchall()]

    if is_superadmin_role:
        cursor.execute(
            """
            SELECT t.*, m.last_read_at
            FROM chat_threads t
            LEFT JOIN chat_thread_members m
                ON m.thread_id = t.id AND lower(m.username) = lower(?)
            WHERE t.thread_type = 'role' AND t.is_enabled = 1
            ORDER BY t.title COLLATE NOCASE, t.id
            """,
            (clean_username,),
        )
    else:
        accessible_roles = [role for role in normalized_roles]
        if accessible_roles:
            placeholders = ", ".join("?" for _ in accessible_roles)
            cursor.execute(
                f"""
                SELECT t.*, m.last_read_at
                FROM chat_threads t
                LEFT JOIN chat_thread_members m
                    ON m.thread_id = t.id AND lower(m.username) = lower(?)
                WHERE t.thread_type = 'role'
                  AND t.is_enabled = 1
                  AND lower(t.role_name) IN ({placeholders})
                ORDER BY t.title COLLATE NOCASE, t.id
                """,
                (clean_username, *accessible_roles),
            )
        else:
            cursor.execute(
                """
                SELECT t.*, m.last_read_at
                FROM chat_threads t
                LEFT JOIN chat_thread_members m
                    ON m.thread_id = t.id AND lower(m.username) = lower(?)
                WHERE 1 = 0
                """,
                (clean_username,),
            )
    role_rows = [dict(row) for row in cursor.fetchall()]

    cursor.execute(
        """
        SELECT t.*, m.last_read_at
        FROM chat_threads t
        INNER JOIN chat_thread_members m
            ON m.thread_id = t.id AND lower(m.username) = lower(?)
        WHERE t.thread_type = 'direct'
        ORDER BY datetime(t.updated_at) DESC, t.id DESC
        """,
        (clean_username,),
    )
    direct_rows = [dict(row) for row in cursor.fetchall()]

    all_thread_rows = channel_rows + role_rows + direct_rows
    thread_ids = [row["id"] for row in all_thread_rows]
    unread_map = {}
    last_message_map = {}
    direct_partner_map = {}

    if thread_ids:
        placeholders = ", ".join("?" for _ in thread_ids)
        cursor.execute(
            f"""
            SELECT m.thread_id, COUNT(*) AS unread_count
            FROM chat_messages m
            LEFT JOIN chat_thread_members tm
                ON tm.thread_id = m.thread_id AND lower(tm.username) = lower(?)
            WHERE m.thread_id IN ({placeholders})
              AND lower(m.sender_username) <> lower(?)
              AND (tm.last_read_at IS NULL OR datetime(m.created_at) > datetime(tm.last_read_at))
            GROUP BY m.thread_id
            """,
            (clean_username, *thread_ids, clean_username),
        )
        unread_map = {row["thread_id"]: row["unread_count"] for row in cursor.fetchall()}

        cursor.execute(
            f"""
            SELECT cm.*
            FROM chat_messages cm
            INNER JOIN (
                SELECT thread_id, MAX(id) AS max_id
                FROM chat_messages
                WHERE thread_id IN ({placeholders})
                GROUP BY thread_id
            ) latest ON latest.max_id = cm.id
            """,
            tuple(thread_ids),
        )
        last_message_map = {row["thread_id"]: dict(row) for row in cursor.fetchall()}

        direct_thread_ids = [row["id"] for row in direct_rows]
        if direct_thread_ids:
            direct_placeholders = ", ".join("?" for _ in direct_thread_ids)
            cursor.execute(
                f"""
                SELECT tm.thread_id, u.username, u.fullname, u.designation, u.last_login_at
                FROM chat_thread_members tm
                INNER JOIN users u ON lower(u.username) = lower(tm.username)
                WHERE tm.thread_id IN ({direct_placeholders})
                  AND lower(tm.username) <> lower(?)
                """,
                (*direct_thread_ids, clean_username),
            )
            direct_partner_map = {row["thread_id"]: dict(row) for row in cursor.fetchall()}

    presence_map = get_presence_snapshot_map(connection)

    def enrich_thread(row, *, direct_partner=None):
        last_message = last_message_map.get(row["id"])
        item = {
            "room_key": row["room_key"],
            "thread_type": row["thread_type"],
            "title": row["title"],
            "description": row["description"] or "",
            "unread_count": int(unread_map.get(row["id"], 0) or 0),
            "last_message_preview": build_chat_message_preview(
                last_message.get("body") if last_message else "",
                last_message.get("attachment_name") if last_message else "",
            ),
            "last_message_at": last_message.get("created_at") if last_message else row["updated_at"],
            "editable": row["thread_type"] == "channel",
        }
        if row["thread_type"] == "role":
            item["role_name"] = row["role_name"]
        if direct_partner:
            partner_state = presence_map.get(direct_partner["username"].casefold(), build_presence_state("", direct_partner.get("last_login_at")))
            item.update(
                {
                    "target_username": direct_partner["username"],
                    "title": (direct_partner.get("fullname") or "").strip() or direct_partner["username"],
                    "description": direct_partner.get("designation") or "",
                    "presence": partner_state["status"],
                    "presence_label": partner_state["status_label"],
                    "last_seen_at": partner_state["last_seen_at"],
                    "last_login_at": partner_state["last_login_at"],
                }
            )
        return item

    channels = [enrich_thread(row) for row in channel_rows]
    role_groups = [enrich_thread(row) for row in role_rows]
    direct_threads = [enrich_thread(row, direct_partner=direct_partner_map.get(row["id"])) for row in direct_rows]

    cursor.execute(
        """
        SELECT u.username, u.fullname, u.designation, u.last_login_at
        FROM users u
        WHERE lower(u.username) <> lower(?)
        ORDER BY u.fullname COLLATE NOCASE, u.username COLLATE NOCASE
        """,
        (clean_username,),
    )
    users = []
    for row in cursor.fetchall():
        state = presence_map.get(row["username"].casefold(), build_presence_state("", row["last_login_at"]))
        users.append(
            {
                "username": row["username"],
                "fullname": (row["fullname"] or "").strip() or row["username"],
                "designation": row["designation"] or "",
                "room_key": build_direct_room_key(clean_username, row["username"]),
                "presence": state["status"],
                "presence_label": state["status_label"],
                "last_seen_at": state["last_seen_at"],
                "last_login_at": state["last_login_at"],
                "last_seen_label": state["last_seen_label"],
            }
        )

    users.sort(key=lambda item: (0 if item["presence"] == "online" else 1, item["fullname"].casefold(), item["username"].casefold()))
    connection.commit()
    connection.close()
    return {
        "channels": channels,
        "role_groups": role_groups,
        "direct_threads": direct_threads,
        "users": users,
        "unread_total": sum(item["unread_count"] for item in channels + role_groups + direct_threads),
    }


def build_chat_attachment_payload(attachment_path, attachment_name, attachment_kind):
    if not attachment_path:
        return None
    return {
        "url": f"/static/{attachment_path}",
        "name": attachment_name or os.path.basename(attachment_path),
        "kind": attachment_kind or "file",
    }


def build_chat_message_payload(row, username):
    clean_username = (username or "").strip()
    attachment = build_chat_attachment_payload(row.get("attachment_path"), row.get("attachment_name"), row.get("attachment_kind"))
    return {
        "id": row["id"],
        "sender_username": row["sender_username"],
        "sender_fullname": (row.get("sender_fullname") or "").strip() or row["sender_username"],
        "created_at": row["created_at"],
        "is_self": row["sender_username"].casefold() == clean_username.casefold(),
        "body": row.get("body") or "",
        "body_html": render_chat_message_markup(row.get("body")),
        "attachment": attachment,
    }


def get_chat_thread_messages(username, fullname, role_names, thread_type, target, limit=80, before_id=None, after_id=None):
    clean_username = (username or "").strip()
    if not clean_username:
        return False, "Authentication required.", None

    connection = connect_db()
    ensure_chat_defaults(connection)
    if thread_type in {"channel", "role"}:
        ensure_thread_memberships_for_user(connection, clean_username, role_names)

    thread, direct_partner, error_message = resolve_chat_thread(connection, clean_username, role_names, thread_type, target)
    if not thread:
        connection.close()
        return False, error_message, None

    ensure_member_record(connection, thread["id"], clean_username, initial_read_at=timestamp_now())
    cursor = connection.cursor()
    page_size = max(1, min(int(limit or 80), 200))

    if after_id is not None:
        cursor.execute(
            """
            SELECT id, sender_username, sender_fullname, body, attachment_path, attachment_name, attachment_kind, created_at
            FROM chat_messages
            WHERE thread_id = ? AND id > ?
            ORDER BY id ASC
            LIMIT ?
            """,
            (thread["id"], int(after_id), page_size),
        )
        rows = [dict(row) for row in cursor.fetchall()]
    elif before_id is not None:
        cursor.execute(
            """
            SELECT id, sender_username, sender_fullname, body, attachment_path, attachment_name, attachment_kind, created_at
            FROM chat_messages
            WHERE thread_id = ? AND id < ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (thread["id"], int(before_id), page_size),
        )
        rows = list(reversed([dict(row) for row in cursor.fetchall()]))
    else:
        cursor.execute(
            """
            SELECT id, sender_username, sender_fullname, body, attachment_path, attachment_name, attachment_kind, created_at
            FROM chat_messages
            WHERE thread_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (thread["id"], page_size),
        )
        rows = list(reversed([dict(row) for row in cursor.fetchall()]))

    cursor.execute(
        """
        SELECT COUNT(*) AS total_count, MIN(id) AS oldest_id, MAX(id) AS newest_id
        FROM chat_messages
        WHERE thread_id = ?
        """,
        (thread["id"],),
    )
    thread_stats = dict(cursor.fetchone() or {})
    messages = [build_chat_message_payload(row, clean_username) for row in rows]
    window_oldest_id = messages[0]["id"] if messages else None
    window_newest_id = messages[-1]["id"] if messages else None
    thread_oldest_id = thread_stats.get("oldest_id")
    thread_newest_id = thread_stats.get("newest_id")

    mark_chat_thread_read(connection, thread["id"], clean_username)
    connection.commit()

    thread_payload = {
        "room_key": thread["room_key"],
        "thread_type": thread["thread_type"],
        "title": thread["title"],
        "description": thread["description"] or "",
        "editable": thread["thread_type"] == "channel",
    }
    if thread["thread_type"] == "direct" and direct_partner:
        presence_map = get_presence_snapshot_map(connection)
        thread_payload["title"] = (direct_partner.get("fullname") or "").strip() or direct_partner["username"]
        thread_payload["description"] = direct_partner.get("designation") or ""
        thread_payload["target_username"] = direct_partner["username"]
        thread_payload["presence"] = presence_map.get(
            direct_partner["username"].casefold(),
            build_presence_state("", direct_partner.get("last_login_at")),
        )

    connection.close()
    return True, "Thread loaded.", {
        "thread": thread_payload,
        "messages": messages,
        "message_meta": {
            "total_count": int(thread_stats.get("total_count") or 0),
            "thread_oldest_id": thread_oldest_id,
            "thread_newest_id": thread_newest_id,
            "window_oldest_id": window_oldest_id,
            "window_newest_id": window_newest_id,
            "returned_count": len(messages),
            "has_more_before": bool(messages and thread_oldest_id is not None and window_oldest_id and window_oldest_id > thread_oldest_id),
            "has_more_after": bool(messages and thread_newest_id is not None and window_newest_id and window_newest_id < thread_newest_id),
        },
    }


def create_chat_message(username, fullname, role_names, thread_type, target, body, attachment_meta=None):
    clean_username = (username or "").strip()
    clean_body = (body or "").strip()
    if not clean_username:
        return False, "Authentication required."
    if not clean_body and not attachment_meta:
        return False, "Enter a message or attach a file."

    connection = connect_db()
    ensure_chat_defaults(connection)
    if thread_type in {"channel", "role"}:
        ensure_thread_memberships_for_user(connection, clean_username, role_names)

    thread, direct_partner, error_message = resolve_chat_thread(connection, clean_username, role_names, thread_type, target)
    if not thread:
        connection.close()
        return False, error_message

    now = timestamp_now()
    ensure_member_record(connection, thread["id"], clean_username, initial_read_at=now)
    connection.execute(
        """
        INSERT INTO chat_messages (
            thread_id,
            sender_username,
            sender_fullname,
            body,
            attachment_path,
            attachment_name,
            attachment_kind,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            thread["id"],
            clean_username,
            (fullname or "").strip() or clean_username,
            clean_body or None,
            attachment_meta.get("path") if attachment_meta else None,
            attachment_meta.get("name") if attachment_meta else None,
            attachment_meta.get("kind") if attachment_meta else None,
            now,
        ),
    )
    connection.execute(
        """
        UPDATE chat_threads
        SET updated_at = ?, updated_by_username = ?
        WHERE id = ?
        """,
        (now, clean_username, thread["id"]),
    )
    mark_chat_thread_read(connection, thread["id"], clean_username)
    if thread["thread_type"] == "direct" and direct_partner:
        ensure_member_record(connection, thread["id"], direct_partner["username"], initial_read_at=None)
    connection.commit()
    connection.close()
    return True, "Message sent."


def update_chat_channel(room_key, title, description, actor_username):
    clean_title = " ".join((title or "").split())
    clean_description = (description or "").strip()
    if not clean_title:
        return False, "Channel title is required."

    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute(
        """
        UPDATE chat_threads
        SET title = ?, description = ?, updated_by_username = ?, updated_at = ?
        WHERE room_key = ? AND thread_type = 'channel'
        """,
        (clean_title, clean_description, (actor_username or "").strip() or "System", timestamp_now(), room_key),
    )
    if cursor.rowcount == 0:
        connection.close()
        return False, "Channel not found."
    connection.commit()
    connection.close()
    return True, "Channel updated."


def get_role_group_settings():
    connection = connect_db()
    ensure_chat_defaults(connection)
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT room_key, title, description, role_name, is_enabled, updated_at
        FROM chat_threads
        WHERE thread_type = 'role'
        ORDER BY title COLLATE NOCASE, id
        """
    )
    items = [dict(row) for row in cursor.fetchall()]
    connection.commit()
    connection.close()
    return items


def update_role_group(room_key, title, description, is_enabled, actor_username):
    clean_title = " ".join((title or "").split())
    clean_description = (description or "").strip()
    enabled_value = 1 if is_enabled else 0
    if not clean_title:
        return False, "Role group title is required."

    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute(
        """
        UPDATE chat_threads
        SET title = ?, description = ?, is_enabled = ?, updated_by_username = ?, updated_at = ?
        WHERE room_key = ? AND thread_type = 'role'
        """,
        (
            clean_title,
            clean_description,
            enabled_value,
            (actor_username or "").strip() or "System",
            timestamp_now(),
            room_key,
        ),
    )
    if cursor.rowcount == 0:
        connection.close()
        return False, "Role group not found."
    connection.commit()
    connection.close()
    return True, "Role group updated."

def get_marquee_styles():
    return [{"key": key, "label": label} for key, label in MARQUEE_STYLE_CHOICES]


def get_marquee_settings():
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute("SELECT style_key FROM marquee_settings WHERE id = 1")
    settings_row = cursor.fetchone()
    cursor.execute(
        """
        SELECT id, message, sort_order, created_at, is_archived, archived_at
        FROM marquee_items
        WHERE is_archived = 0
        ORDER BY sort_order ASC, id ASC
        """
    )
    items = [dict(row) for row in cursor.fetchall()]
    cursor.execute(
        """
        SELECT id, message, sort_order, created_at, is_archived, archived_at
        FROM marquee_items
        WHERE is_archived = 1
        ORDER BY datetime(archived_at) DESC, id DESC
        """
    )
    archived_items = [dict(row) for row in cursor.fetchall()]
    connection.close()
    return {
        "style_key": settings_row["style_key"] if settings_row else DEFAULT_MARQUEE_STYLE,
        "items": items,
        "archived_items": archived_items,
    }


def update_marquee_style(style_key):
    valid_keys = {key for key, _ in MARQUEE_STYLE_CHOICES}
    if style_key not in valid_keys:
        return False, "Unsupported marquee style."

    connection = connect_db()
    connection.execute(
        """
        UPDATE marquee_settings
        SET style_key = ?, updated_at = ?
        WHERE id = 1
        """,
        (style_key, timestamp_now()),
    )
    connection.commit()
    connection.close()
    return True, "Marquee style updated."


def create_marquee_item(message):
    message = " ".join((message or "").split())
    if not message:
        return False, "Marquee message is required."

    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute("SELECT COALESCE(MAX(sort_order), 0) + 1 AS next_order FROM marquee_items")
    next_order = cursor.fetchone()["next_order"]
    cursor.execute(
        """
        INSERT INTO marquee_items (message, sort_order, created_at)
        VALUES (?, ?, ?)
        """,
        (message, next_order, timestamp_now()),
    )
    connection.commit()
    connection.close()
    return True, "Marquee item added."


def update_marquee_item(item_id, message):
    message = " ".join((message or "").split())
    if not message:
        return False, "Marquee message is required."

    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute(
        """
        UPDATE marquee_items
        SET message = ?
        WHERE id = ?
        """,
        (message, item_id),
    )
    if cursor.rowcount == 0:
        connection.close()
        return False, "Marquee item not found."
    connection.commit()
    connection.close()
    return True, "Marquee item updated."


def delete_marquee_item(item_id):
    return archive_marquee_item(item_id)


def archive_marquee_item(item_id):
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute(
        """
        UPDATE marquee_items
        SET is_archived = 1, archived_at = ?
        WHERE id = ?
        """,
        (timestamp_now(), item_id),
    )
    if cursor.rowcount == 0:
        connection.close()
        return False, "Marquee item not found."
    connection.commit()
    connection.close()
    return True, "Marquee item archived."


def restore_marquee_item(item_id):
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute("SELECT COALESCE(MAX(sort_order), 0) + 1 AS next_order FROM marquee_items WHERE is_archived = 0")
    next_order = cursor.fetchone()["next_order"]
    cursor.execute(
        """
        UPDATE marquee_items
        SET is_archived = 0, archived_at = NULL, sort_order = ?
        WHERE id = ?
        """,
        (next_order, item_id),
    )
    if cursor.rowcount == 0:
        connection.close()
        return False, "Marquee item not found."
    connection.commit()
    connection.close()
    return True, "Marquee item restored."


def permanently_delete_marquee_item(item_id):
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute("DELETE FROM marquee_items WHERE id = ? AND is_archived = 1", (item_id,))
    if cursor.rowcount == 0:
        connection.close()
        return False, "Archived marquee item not found."
    connection.commit()
    connection.close()
    return True, "Archived marquee item deleted."


def move_marquee_item(item_id, direction):
    if direction not in {"up", "down"}:
        return False, "Unsupported move direction."

    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT id, sort_order
        FROM marquee_items
        WHERE id = ?
        """,
        (item_id,),
    )
    current_item = cursor.fetchone()
    if not current_item:
        connection.close()
        return False, "Marquee item not found."

    comparison = "<" if direction == "up" else ">"
    ordering = "DESC" if direction == "up" else "ASC"
    cursor.execute(
        f"""
        SELECT id, sort_order
        FROM marquee_items
        WHERE sort_order {comparison} ?
        ORDER BY sort_order {ordering}, id {ordering}
        LIMIT 1
        """,
        (current_item["sort_order"],),
    )
    swap_item = cursor.fetchone()
    if not swap_item:
        connection.close()
        return False, "Item is already at the edge of the list."

    cursor.execute("UPDATE marquee_items SET sort_order = ? WHERE id = ?", (swap_item["sort_order"], current_item["id"]))
    cursor.execute("UPDATE marquee_items SET sort_order = ? WHERE id = ?", (current_item["sort_order"], swap_item["id"]))
    connection.commit()
    connection.close()
    return True, "Marquee order updated."


def get_notifications_for_user(username, role_names, fullname):
    normalized_roles = {role.casefold() for role in (role_names or [])}
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT id, title, message, target_role, style_key, link_url, created_at, created_by_username, created_by_fullname
        FROM notifications
        WHERE is_archived = 0
        ORDER BY datetime(created_at) DESC, id DESC
        """
    )
    notifications = []
    for row in cursor.fetchall():
        item = dict(row)
        target_roles = normalize_role_names((item["target_role"] or "").replace(";", ",").split(","))
        target_role_keys = {role.casefold() for role in target_roles}
        if "all" not in target_role_keys and not (target_role_keys & normalized_roles):
            continue
        item["notification_key"] = f"db:{item['id']}"
        item["sender_name"] = (
            (item.get("created_by_fullname") or "").strip()
            or (item.get("created_by_username") or "").strip()
            or "System"
        )
        item["target_role_display"] = ", ".join(target_roles) if target_roles else "All"
        item["message_preview"] = build_notification_preview(item.get("message"))
        item["message_html"] = render_notification_markup(item.get("message"))
        notifications.append(item)

    welcome_name = (fullname or "").strip() or "User"
    notifications.insert(
        0,
        {
            "id": "welcome",
            "notification_key": "entry:welcome",
            "title": f"Hello, {welcome_name}",
            "message": "Welcome back. Review current notices and updates before proceeding with your work.",
            "message_preview": "Welcome back. Review current notices and updates before proceeding with your work.",
            "message_html": "<p>Welcome back. Review current notices and updates before proceeding with your work.</p>",
            "target_role": "all",
            "style_key": "success",
            "created_at": timestamp_now(),
            "sender_name": "System",
        },
    )

    if not username:
        connection.close()
        for item in notifications:
            item["is_read"] = False
            item["is_hidden"] = False
        return notifications

    notification_keys = [item["notification_key"] for item in notifications]
    placeholders = ", ".join("?" for _ in notification_keys)
    cursor.execute(
        f"""
        SELECT notification_key, is_read, is_hidden
        FROM notification_user_states
        WHERE username = ? AND notification_key IN ({placeholders})
        """,
        (username, *notification_keys),
    )
    state_map = {row["notification_key"]: dict(row) for row in cursor.fetchall()}
    connection.close()

    visible_notifications = []
    for item in notifications:
        state = state_map.get(item["notification_key"], {})
        item["is_read"] = bool(state.get("is_read"))
        item["is_hidden"] = bool(state.get("is_hidden"))
        if item["is_hidden"]:
            continue
        visible_notifications.append(item)
    return visible_notifications


def set_notification_state(username, notification_key, *, is_read=None, is_hidden=None):
    username = (username or "").strip()
    notification_key = (notification_key or "").strip()
    if not username or not notification_key:
        return False

    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT is_read, is_hidden
        FROM notification_user_states
        WHERE username = ? AND notification_key = ?
        """,
        (username, notification_key),
    )
    existing = cursor.fetchone()
    current_read = int(existing["is_read"]) if existing else 0
    current_hidden = int(existing["is_hidden"]) if existing else 0
    next_read = current_read if is_read is None else (1 if is_read else 0)
    next_hidden = current_hidden if is_hidden is None else (1 if is_hidden else 0)

    cursor.execute(
        """
        INSERT INTO notification_user_states (username, notification_key, is_read, is_hidden, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(username, notification_key) DO UPDATE SET
            is_read = excluded.is_read,
            is_hidden = excluded.is_hidden,
            updated_at = excluded.updated_at
        """,
        (username, notification_key, next_read, next_hidden, timestamp_now()),
    )
    connection.commit()
    connection.close()
    return True


def get_all_notifications(include_archived=False):
    connection = connect_db()
    cursor = connection.cursor()
    where_clause = "" if include_archived else "WHERE is_archived = 0"
    cursor.execute(
        f"""
        SELECT
            id,
            title,
            message,
            target_role,
            style_key,
            link_url,
            created_by_username,
            created_by_fullname,
            created_at,
            is_archived,
            archived_at
        FROM notifications
        {where_clause}
        ORDER BY datetime(created_at) DESC, id DESC
        """
    )
    items = [dict(row) for row in cursor.fetchall()]
    connection.close()
    for item in items:
        item["sender_name"] = (
            (item.get("created_by_fullname") or "").strip()
            or (item.get("created_by_username") or "").strip()
            or "System"
        )
        item["message_preview"] = build_notification_preview(item.get("message"))
    return items


def create_notification(title, message, target_role, style_key, link_url="", actor_username=None, actor_fullname=None):
    title = " ".join((title or "").split())
    message = (message or "").strip()
    style_key = " ".join((style_key or "").split()) or "info"
    link_url = (link_url or "").strip()
    target_roles = normalize_role_names(target_role if isinstance(target_role, list) else [target_role])

    if not title or not message:
        return False, "Notification title and message are required."

    if not target_roles:
        target_roles = ["All"]

    connection = connect_db()
    connection.execute(
        """
        INSERT INTO notifications (
            title,
            message,
            target_role,
            style_key,
            link_url,
            created_by_username,
            created_by_fullname,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            title,
            message,
            ",".join(target_roles),
            style_key,
            link_url or None,
            (actor_username or "").strip() or None,
            (actor_fullname or "").strip() or None,
            timestamp_now(),
        ),
    )
    connection.commit()
    connection.close()
    return True, "Notification created."


def delete_notification(notification_id):
    return archive_notification(notification_id)


def archive_notification(notification_id):
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute(
        """
        UPDATE notifications
        SET is_archived = 1, archived_at = ?
        WHERE id = ?
        """,
        (timestamp_now(), notification_id),
    )
    if cursor.rowcount == 0:
        connection.close()
        return False, "Notification not found."
    connection.commit()
    connection.close()
    return True, "Notification archived."


def restore_notification(notification_id):
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute(
        """
        UPDATE notifications
        SET is_archived = 0, archived_at = NULL
        WHERE id = ?
        """,
        (notification_id,),
    )
    if cursor.rowcount == 0:
        connection.close()
        return False, "Notification not found."
    connection.commit()
    connection.close()
    return True, "Notification restored."


def permanently_delete_notification(notification_id):
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute("DELETE FROM notifications WHERE id = ? AND is_archived = 1", (notification_id,))
    if cursor.rowcount == 0:
        connection.close()
        return False, "Archived notification not found."
    connection.commit()
    connection.close()
    return True, "Archived notification deleted."


def hash_remember_token(token):
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def purge_expired_remember_tokens(connection):
    connection.execute(
        """
        DELETE FROM remember_tokens
        WHERE datetime(expires_at) <= datetime(?)
        """,
        (timestamp_now(),),
    )


def create_remember_me_token(username, days=REMEMBER_ME_DAYS):
    username = (username or "").strip()
    if not username:
        return None

    connection = connect_db()
    purge_expired_remember_tokens(connection)

    selector = secrets.token_urlsafe(9)
    raw_token = secrets.token_urlsafe(32)
    expires_at = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")

    connection.execute(
        """
        INSERT INTO remember_tokens (username, selector, token_hash, expires_at, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (username, selector, hash_remember_token(raw_token), expires_at, timestamp_now()),
    )
    connection.commit()
    connection.close()
    return f"{selector}.{raw_token}"


def consume_remember_me_token(cookie_value):
    if not cookie_value or "." not in cookie_value:
        return None

    selector, raw_token = cookie_value.split(".", 1)
    if not selector or not raw_token:
        return None

    connection = connect_db()
    purge_expired_remember_tokens(connection)
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT username, token_hash, expires_at
        FROM remember_tokens
        WHERE selector = ?
        """,
        (selector,),
    )
    row = cursor.fetchone()

    if not row or row["token_hash"] != hash_remember_token(raw_token):
        if row:
            connection.execute("DELETE FROM remember_tokens WHERE selector = ?", (selector,))
            connection.commit()
        connection.close()
        return None

    connection.close()
    return row["username"]


def delete_remember_me_token(cookie_value):
    if not cookie_value or "." not in cookie_value:
        return

    selector = cookie_value.split(".", 1)[0]
    connection = connect_db()
    connection.execute("DELETE FROM remember_tokens WHERE selector = ?", (selector,))
    connection.commit()
    connection.close()


def slugify(value):
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in (value or "").strip())
    parts = [part for part in cleaned.split("-") if part]
    return "-".join(parts) or f"post-{datetime.now().strftime('%Y%m%d%H%M%S')}"


def ensure_unique_slug(connection, title, exclude_post_id=None):
    base_slug = slugify(title)
    candidate = base_slug
    suffix = 2
    cursor = connection.cursor()

    while True:
        if exclude_post_id is None:
            cursor.execute("SELECT id FROM news_posts WHERE slug = ?", (candidate,))
        else:
            cursor.execute("SELECT id FROM news_posts WHERE slug = ? AND id != ?", (candidate, exclude_post_id))

        if not cursor.fetchone():
            return candidate

        candidate = f"{base_slug}-{suffix}"
        suffix += 1


def build_news_summary(summary, content, limit=180):
    manual_summary = " ".join((summary or "").split())
    if manual_summary:
        return manual_summary

    normalized_content = " ".join(strip_image_tokens(content).split())
    if len(normalized_content) <= limit:
        return normalized_content

    return normalized_content[: limit - 1].rstrip() + "..."


def strip_image_tokens(content):
    lines = []
    for raw_line in (content or "").replace("\r\n", "\n").splitlines():
        line = raw_line.strip()
        if line.startswith("[image:") and line.endswith("]"):
            continue
        lines.append(raw_line)
    return "\n".join(lines)


def parse_image_token(block):
    token_body = block[len("[image:") : -1]
    if "|" in token_body:
        filename, caption = token_body.split("|", 1)
    else:
        filename, caption = token_body, ""

    filename = os.path.basename(filename.strip())
    caption = caption.strip()
    if not filename:
        return None

    file_ext = os.path.splitext(filename)[1].lower()
    if file_ext not in ALLOWED_IMAGE_EXTENSIONS:
        return None

    file_path = os.path.join(NEWS_IMAGE_DIR, filename)
    if not os.path.exists(file_path):
        return None

    return {
        "filename": filename,
        "caption": caption,
        "src": f"/static/{NEWS_IMAGE_WEB_PATH}/{filename}",
    }


def render_blog_content(content):
    blocks = [block.strip() for block in (content or "").replace("\r\n", "\n").split("\n\n") if block.strip()]
    rendered_blocks = []

    for block in blocks:
        if block.startswith("[image:") and block.endswith("]"):
            image_meta = parse_image_token(block)
            if image_meta:
                caption_html = f"<figcaption>{escape(image_meta['caption'])}</figcaption>" if image_meta["caption"] else ""
                rendered_blocks.append(
                    '<figure class="blog-image">'
                    f'<img src="{escape(image_meta["src"])}" alt="{escape(image_meta["caption"] or image_meta["filename"])}">'
                    f"{caption_html}"
                    "</figure>"
                )
            continue

        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue

        if all(line.startswith("- ") for line in lines):
            items = "".join(f"<li>{render_inline_markup(line[2:].strip())}</li>" for line in lines)
            rendered_blocks.append(f"<ul>{items}</ul>")
            continue

        if all(re.match(r"^\d+\.\s+", line) for line in lines):
            normalized_items = [re.sub(r"^\d+\.\s+", "", line, count=1) for line in lines]
            items = "".join(f"<li>{render_inline_markup(item)}</li>" for item in normalized_items)
            rendered_blocks.append(f"<ol>{items}</ol>")
            continue

        if len(lines) == 1 and lines[0].startswith("### "):
            rendered_blocks.append(f"<h3>{render_inline_markup(lines[0][4:].strip())}</h3>")
            continue

        if len(lines) == 1 and lines[0].startswith("## "):
            rendered_blocks.append(f"<h2>{render_inline_markup(lines[0][3:].strip())}</h2>")
            continue

        if len(lines) == 1 and lines[0].startswith("# "):
            rendered_blocks.append(f"<h1>{render_inline_markup(lines[0][2:].strip())}</h1>")
            continue

        if all(line.startswith("> ") for line in lines):
            quote_html = "<br>".join(render_inline_markup(line[2:].strip()) for line in lines)
            rendered_blocks.append(f"<blockquote>{quote_html}</blockquote>")
            continue

        rendered_blocks.append("<p>" + "<br>".join(render_inline_markup(line) for line in lines) + "</p>")

    return "\n".join(rendered_blocks)


def render_inline_markup(text):
    escaped = escape(text or "")
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", escaped)
    escaped = re.sub(r"\[([^\]]+)\]\((https?://[^\s)]+)\)", r'<a href="\2" target="_blank" rel="noopener noreferrer">\1</a>', escaped)
    return escaped


def render_notification_markup(text):
    lines = [line.strip() for line in (text or "").splitlines()]
    visible_lines = [line for line in lines if line]
    if not visible_lines:
        return "<p></p>"
    return "<p>" + "<br>".join(render_notification_line(line) for line in visible_lines) + "</p>"


def render_chat_message_markup(text):
    lines = [line.strip() for line in (text or "").splitlines()]
    visible_lines = [line for line in lines if line]
    if not visible_lines:
        return ""
    return "<p>" + "<br>".join(render_notification_line(line) for line in visible_lines) + "</p>"


def build_notification_preview(text, limit=160):
    plain_text = re.sub(r"\[([^\]]+)\]\((https?://[^\s)]+)\)", r"\1", text or "")
    plain_text = " ".join(plain_text.split())
    if len(plain_text) <= limit:
        return plain_text
    return plain_text[: limit - 3].rstrip() + "..."


def render_notification_line(text):
    escaped = escape(text or "")
    link_tokens = []

    def replace_markdown_link(match):
        label = match.group(1)
        href = match.group(2)
        token = f"__notification_link_{len(link_tokens)}__"
        link_tokens.append(
            (token, f'<a href="{href}" target="_blank" rel="noopener noreferrer">{label}</a>')
        )
        return token

    def replace_plain_link(match):
        href = match.group(0)
        token = f"__notification_link_{len(link_tokens)}__"
        link_tokens.append(
            (token, f'<a href="{href}" target="_blank" rel="noopener noreferrer">{href}</a>')
        )
        return token

    escaped = re.sub(r"\[([^\]]+)\]\((https?://[^\s)]+)\)", replace_markdown_link, escaped)
    escaped = re.sub(r"(?<![\"'=])(https?://[^\s<]+)", replace_plain_link, escaped)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", escaped)

    for token, html in link_tokens:
        escaped = escaped.replace(token, html)
    return escaped


def list_news_images():
    ensure_news_image_folder()
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute("SELECT content FROM news_posts")
    all_content = "\n".join((row["content"] or "") for row in cursor.fetchall())
    connection.close()

    images = []
    for filename in sorted(os.listdir(NEWS_IMAGE_DIR), reverse=True):
        file_path = os.path.join(NEWS_IMAGE_DIR, filename)
        if not os.path.isfile(file_path):
            continue

        file_ext = os.path.splitext(filename)[1].lower()
        if file_ext not in ALLOWED_IMAGE_EXTENSIONS:
            continue

        usage_count = all_content.count(f"[image:{filename}|") + all_content.count(f"[image:{filename}]")
        images.append(
            {
                "filename": filename,
                "src": f"/static/{NEWS_IMAGE_WEB_PATH}/{filename}",
                "token": f"[image:{filename}|Optional caption]",
                "usage_count": usage_count,
                "is_used": usage_count > 0,
            }
        )

    return images


def delete_news_image(filename):
    clean_filename = os.path.basename((filename or "").strip())
    if not clean_filename:
        return False, "Image not found."

    file_ext = os.path.splitext(clean_filename)[1].lower()
    if file_ext not in ALLOWED_IMAGE_EXTENSIONS:
        return False, "Unsupported image type."

    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute("SELECT content FROM news_posts")
    all_content = "\n".join((row["content"] or "") for row in cursor.fetchall())
    connection.close()

    usage_count = all_content.count(f"[image:{clean_filename}|") + all_content.count(f"[image:{clean_filename}]")
    if usage_count > 0:
        return False, "This image is still used in one or more posts."

    file_path = os.path.join(NEWS_IMAGE_DIR, clean_filename)
    if not os.path.exists(file_path):
        return False, "Image not found."

    os.remove(file_path)
    return True, "Image deleted successfully."


def get_news_posts(limit=None, include_archived=False):
    connection = connect_db()
    cursor = connection.cursor()
    where_clause = "" if include_archived else "WHERE is_archived = 0"
    query = """
        SELECT id, title, slug, summary, content, author_username, author_fullname, updated_by_fullname, created_at, updated_at
        FROM news_posts
        {where_clause}
        ORDER BY datetime(updated_at) DESC, id DESC
    """
    query = query.format(where_clause=where_clause)
    if limit is not None:
        query += " LIMIT ?"
        cursor.execute(query, (int(limit),))
    else:
        cursor.execute(query)

    posts = []
    for row in cursor.fetchall():
        post = dict(row)
        post["summary_display"] = build_news_summary(post["summary"], post["content"])
        post["editor_name"] = post.get("updated_by_fullname") or post.get("author_fullname") or post["author_username"]
        posts.append(post)

    connection.close()
    return posts


def get_news_post_by_slug(slug):
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT id, title, slug, summary, content, author_username, author_fullname, updated_by_fullname, created_at, updated_at
        FROM news_posts
        WHERE slug = ?
        """,
        (slug,),
    )
    row = cursor.fetchone()
    connection.close()

    if not row:
        return None

    post = dict(row)
    post["summary_display"] = build_news_summary(post["summary"], post["content"])
    post["content_html"] = render_blog_content(post["content"])
    post["editor_name"] = post.get("updated_by_fullname") or post.get("author_fullname") or post["author_username"]
    return post


def create_news_post(title, summary, content, actor_username, actor_fullname=None):
    title = " ".join((title or "").split())
    summary = (summary or "").strip()
    content = (content or "").strip()

    if not title or not content:
        return False, "Title and content are required."

    connection = connect_db()
    slug = ensure_unique_slug(connection, title)
    connection.execute(
        """
        INSERT INTO news_posts (title, slug, summary, content, author_username, author_fullname, updated_by_fullname, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            title,
            slug,
            summary,
            content,
            actor_username or "System",
            (actor_fullname or "").strip() or actor_username or "System",
            (actor_fullname or "").strip() or actor_username or "System",
            timestamp_now(),
            timestamp_now(),
        ),
    )
    connection.commit()
    connection.close()
    return True, "News post created successfully."


def update_news_post(post_id, title, summary, content, actor_fullname=None):
    title = " ".join((title or "").split())
    summary = (summary or "").strip()
    content = (content or "").strip()

    if not title or not content:
        return False, "Title and content are required."

    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute("SELECT id FROM news_posts WHERE id = ? AND is_archived = 0", (post_id,))
    existing_post = cursor.fetchone()
    if not existing_post:
        connection.close()
        return False, "News post not found."

    slug = ensure_unique_slug(connection, title, exclude_post_id=post_id)
    cursor.execute(
        """
        UPDATE news_posts
        SET title = ?, slug = ?, summary = ?, content = ?, updated_by_fullname = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            title,
            slug,
            summary,
            content,
            (actor_fullname or "").strip() or "System",
            timestamp_now(),
            post_id,
        ),
    )
    connection.commit()
    connection.close()
    return True, "News post updated successfully."


def delete_news_post(post_id):
    return archive_news_post(post_id)


def archive_news_post(post_id):
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute(
        """
        UPDATE news_posts
        SET is_archived = 1, archived_at = ?
        WHERE id = ?
        """,
        (timestamp_now(), post_id),
    )
    if cursor.rowcount == 0:
        connection.close()
        return False, "News post not found."
    connection.commit()
    connection.close()
    return True, "News post archived."


def restore_news_post(post_id):
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute(
        """
        UPDATE news_posts
        SET is_archived = 0, archived_at = NULL
        WHERE id = ?
        """,
        (post_id,),
    )
    if cursor.rowcount == 0:
        connection.close()
        return False, "News post not found."
    connection.commit()
    connection.close()
    return True, "News post restored."


def permanently_delete_news_post(post_id):
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute("DELETE FROM news_posts WHERE id = ? AND is_archived = 1", (post_id,))
    if cursor.rowcount == 0:
        connection.close()
        return False, "Archived news post not found."
    connection.commit()
    connection.close()
    return True, "Archived news post deleted."


def validate_user(username, password):
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT username, fullname
        FROM users
        WHERE username = ? AND password = ?
        """,
        (username, password),
    )
    user = cursor.fetchone()
    connection.close()
    return user


def get_user_identity(username):
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT username, fullname
        FROM users
        WHERE username = ?
        """,
        ((username or "").strip(),),
    )
    user = cursor.fetchone()
    connection.close()
    return user


def get_user_roles_by_username(username):
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT r.name
        FROM user_roles ur
        INNER JOIN users u ON u.id = ur.user_id
        INNER JOIN roles r ON r.id = ur.role_id
        WHERE lower(u.username) = lower(?)
        ORDER BY
            CASE lower(r.name)
                WHEN 'superadmin' THEN 0
                WHEN 'admin' THEN 1
                WHEN 'staff' THEN 2
                ELSE 3
            END,
            r.name COLLATE NOCASE
        """,
        (username,),
    )
    roles = [row["name"] for row in cursor.fetchall()]
    connection.close()
    return roles


def user_has_role(username, role_name):
    return role_name.casefold() in {role.casefold() for role in get_user_roles_by_username(username)}


def get_buttons(user_roles):
    role_names = normalize_role_names(user_roles if isinstance(user_roles, (list, tuple, set)) else [user_roles])
    if not role_names:
        return []

    placeholders = ", ".join("?" for _ in role_names)
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute(
        f"""
        SELECT name, route
        FROM buttons
        WHERE required_role IN ({placeholders})
        ORDER BY name COLLATE NOCASE
        """,
        tuple(role_names),
    )
    buttons = cursor.fetchall()
    connection.close()
    return buttons


def get_role_definitions():
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT
            r.id,
            r.name,
            r.is_locked,
            COUNT(ur.user_id) AS assigned_count
        FROM roles r
        LEFT JOIN user_roles ur ON ur.role_id = r.id
        GROUP BY r.id, r.name, r.is_locked
        ORDER BY
            CASE lower(r.name)
                WHEN 'superadmin' THEN 0
                ELSE 1
            END,
            r.name COLLATE NOCASE
        """
    )
    roles = [dict(row) for row in cursor.fetchall()]
    connection.close()
    return roles


def get_role_name_map(connection, requested_roles):
    role_names = normalize_role_names(requested_roles)
    if not role_names:
        return {}

    placeholders = ", ".join("?" for _ in role_names)
    cursor = connection.cursor()
    cursor.execute(
        f"""
        SELECT id, name
        FROM roles
        WHERE lower(name) IN ({placeholders})
        """,
        tuple(role.casefold() for role in role_names),
    )
    return {row["name"].casefold(): dict(row) for row in cursor.fetchall()}


def get_assigned_roles(connection, user_id):
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT r.name
        FROM user_roles ur
        INNER JOIN roles r ON r.id = ur.role_id
        WHERE ur.user_id = ?
        ORDER BY
            CASE lower(r.name)
                WHEN 'superadmin' THEN 0
                WHEN 'admin' THEN 1
                WHEN 'staff' THEN 2
                ELSE 3
            END,
            r.name COLLATE NOCASE
        """,
        (user_id,),
    )
    return [row["name"] for row in cursor.fetchall()]


def count_users_with_role(connection, role_name):
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT COUNT(DISTINCT ur.user_id) AS total
        FROM user_roles ur
        INNER JOIN roles r ON r.id = ur.role_id
        WHERE lower(r.name) = lower(?)
        """,
        (role_name,),
    )
    return cursor.fetchone()["total"]


def log_account_modification(connection, user_id, target_username, target_fullname, actor_username, action, details):
    connection.execute(
        """
        INSERT INTO account_modifications (
            user_id,
            target_username,
            target_fullname,
            actor_username,
            action,
            details,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(user_id),
            target_username,
            target_fullname,
            actor_username or "System",
            action,
            details,
            timestamp_now(),
        ),
    )


def get_all_users():
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT
            u.id,
            u.username,
            u.designation,
            u.fullname,
            u.date_created,
            (
                SELECT MAX(am.created_at)
                FROM account_modifications am
                WHERE am.user_id = u.id
            ) AS last_modified_at
        FROM users u
        ORDER BY
            CASE
                WHEN EXISTS (
                    SELECT 1
                    FROM user_roles ur
                    INNER JOIN roles r ON r.id = ur.role_id
                    WHERE ur.user_id = u.id AND lower(r.name) = 'superadmin'
                ) THEN 0
                WHEN EXISTS (
                    SELECT 1
                    FROM user_roles ur
                    INNER JOIN roles r ON r.id = ur.role_id
                    WHERE ur.user_id = u.id AND lower(r.name) = 'admin'
                ) THEN 1
                ELSE 2
            END,
            u.fullname COLLATE NOCASE,
            u.username COLLATE NOCASE
        """
    )
    users = [dict(row) for row in cursor.fetchall()]

    if not users:
        connection.close()
        return []

    user_ids = [user["id"] for user in users]
    placeholders = ", ".join("?" for _ in user_ids)

    cursor.execute(
        f"""
        SELECT ur.user_id, r.name
        FROM user_roles ur
        INNER JOIN roles r ON r.id = ur.role_id
        WHERE ur.user_id IN ({placeholders})
        ORDER BY
            CASE lower(r.name)
                WHEN 'superadmin' THEN 0
                WHEN 'admin' THEN 1
                WHEN 'staff' THEN 2
                ELSE 3
            END,
            r.name COLLATE NOCASE
        """,
        tuple(user_ids),
    )
    roles_by_user = {}
    for row in cursor.fetchall():
        roles_by_user.setdefault(row["user_id"], []).append(row["name"])

    cursor.execute(
        f"""
        SELECT user_id, actor_username, action, details, created_at
        FROM account_modifications
        WHERE user_id IN ({placeholders})
        ORDER BY datetime(created_at) DESC, id DESC
        """,
        tuple(user_ids),
    )
    history_by_user = {}
    for row in cursor.fetchall():
        history_by_user.setdefault(row["user_id"], []).append(dict(row))

    connection.close()

    for user in users:
        user["roles"] = roles_by_user.get(user["id"], [])
        user["history"] = history_by_user.get(user["id"], [])
        user["role_display"] = ", ".join(user["roles"]) if user["roles"] else "Unassigned"
        user["last_modified_at"] = user["last_modified_at"] or "No recorded changes"

    return users


def create_user_account(username, password, designation, role_names, fullname, actor_username=None):
    username = (username or "").strip()
    password = (password or "").strip()
    designation = (designation or "").strip()
    fullname = (fullname or "").strip()
    normalized_roles = normalize_role_names(role_names)

    if not username or not password or not fullname:
        return False, "Username, full name, and password are required."

    if not normalized_roles:
        return False, "Select at least one account role."

    connection = connect_db()
    role_map = get_role_name_map(connection, normalized_roles)
    if len(role_map) != len(normalized_roles):
        connection.close()
        return False, "One or more selected roles are no longer available."

    cursor = connection.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO users (username, password, designation, userlevel, fullname, date_created)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (username, password, designation, ",".join(normalized_roles), fullname, timestamp_now()),
        )
        user_id = cursor.lastrowid

        for role_name in normalized_roles:
            cursor.execute(
                """
                INSERT OR IGNORE INTO user_roles (user_id, role_id)
                VALUES (?, ?)
                """,
                (user_id, role_map[role_name.casefold()]["id"]),
            )

        log_account_modification(
            connection,
            user_id,
            username,
            fullname,
            actor_username,
            "Created",
            "Account created with roles: " + ", ".join(normalized_roles),
        )
        connection.commit()
    except sqlite3.IntegrityError:
        connection.close()
        return False, "That username is already in use."

    connection.close()
    return True, "Account created successfully."


def update_user_account(user_id, username, designation, role_names, fullname, password="", actor_username=None):
    username = (username or "").strip()
    designation = (designation or "").strip()
    fullname = (fullname or "").strip()
    password = (password or "").strip()
    normalized_roles = normalize_role_names(role_names)

    if not username or not fullname:
        return False, "Username and full name are required."

    if not normalized_roles:
        return False, "Select at least one account role."

    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT id, username, designation, fullname
        FROM users
        WHERE id = ?
        """,
        (user_id,),
    )
    existing_user = cursor.fetchone()

    if not existing_user:
        connection.close()
        return False, "Account not found."

    existing_roles = get_assigned_roles(connection, user_id)
    existing_role_keys = {role.casefold() for role in existing_roles}
    updated_role_keys = {role.casefold() for role in normalized_roles}

    role_map = get_role_name_map(connection, normalized_roles)
    if len(role_map) != len(normalized_roles):
        connection.close()
        return False, "One or more selected roles are no longer available."

    if "superadmin" in existing_role_keys and "superadmin" not in updated_role_keys:
        if count_users_with_role(connection, "SuperAdmin") <= 1:
            connection.close()
            return False, "At least one SuperAdmin account must remain."

    change_log = []

    if existing_user["username"] != username:
        change_log.append(f"Username: {existing_user['username']} -> {username}")
    if (existing_user["fullname"] or "") != fullname:
        change_log.append(f"Full name: {existing_user['fullname']} -> {fullname}")
    if (existing_user["designation"] or "") != designation:
        previous_designation = existing_user["designation"] or "None"
        current_designation = designation or "None"
        change_log.append(f"Designation: {previous_designation} -> {current_designation}")

    added_roles = [role for role in normalized_roles if role.casefold() not in existing_role_keys]
    removed_roles = [role for role in existing_roles if role.casefold() not in updated_role_keys]
    if added_roles:
        change_log.append("Roles added: " + ", ".join(added_roles))
    if removed_roles:
        change_log.append("Roles removed: " + ", ".join(removed_roles))
    if password:
        change_log.append("Password updated")

    if not change_log:
        connection.close()
        return True, "No changes were made."

    try:
        if password:
            cursor.execute(
                """
                UPDATE users
                SET username = ?, password = ?, designation = ?, userlevel = ?, fullname = ?
                WHERE id = ?
                """,
                (username, password, designation, ",".join(normalized_roles), fullname, user_id),
            )
        else:
            cursor.execute(
                """
                UPDATE users
                SET username = ?, designation = ?, userlevel = ?, fullname = ?
                WHERE id = ?
                """,
                (username, designation, ",".join(normalized_roles), fullname, user_id),
            )

        cursor.execute("DELETE FROM user_roles WHERE user_id = ?", (user_id,))
        for role_name in normalized_roles:
            cursor.execute(
                """
                INSERT INTO user_roles (user_id, role_id)
                VALUES (?, ?)
                """,
                (user_id, role_map[role_name.casefold()]["id"]),
            )

        log_account_modification(
            connection,
            user_id,
            username,
            fullname,
            actor_username,
            "Updated",
            "; ".join(change_log),
        )
        connection.commit()
    except sqlite3.IntegrityError:
        connection.close()
        return False, "That username is already in use."

    connection.close()
    return True, "Account updated successfully."


def delete_user_account(user_id, active_username=None, actor_username=None):
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT id, username, fullname
        FROM users
        WHERE id = ?
        """,
        (user_id,),
    )
    existing_user = cursor.fetchone()

    if not existing_user:
        connection.close()
        return False, "Account not found."

    if active_username and existing_user["username"] == active_username:
        connection.close()
        return False, "You cannot delete the account you are currently using."

    existing_roles = get_assigned_roles(connection, user_id)
    if "superadmin" in {role.casefold() for role in existing_roles} and count_users_with_role(connection, "SuperAdmin") <= 1:
        connection.close()
        return False, "At least one SuperAdmin account must remain."

    log_account_modification(
        connection,
        user_id,
        existing_user["username"],
        existing_user["fullname"],
        actor_username,
        "Deleted",
        "Account deleted. Previous roles: " + (", ".join(existing_roles) if existing_roles else "None"),
    )
    cursor.execute("DELETE FROM user_roles WHERE user_id = ?", (user_id,))
    cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
    connection.commit()
    connection.close()
    return True, "Account deleted successfully."


def create_role(role_name):
    normalized_roles = normalize_role_names([role_name])
    if not normalized_roles:
        return False, "Enter a role name before saving."

    role_name = normalized_roles[0]
    connection = connect_db()

    if fetch_role_by_name(connection, role_name):
        connection.close()
        return False, "That role already exists."

    ensure_role(connection, role_name, is_locked=1 if role_name.casefold() == "superadmin" else 0)
    connection.commit()
    connection.close()
    return True, "Role created successfully."


def delete_role(role_id):
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT r.id, r.name, r.is_locked, COUNT(ur.user_id) AS assigned_count
        FROM roles r
        LEFT JOIN user_roles ur ON ur.role_id = r.id
        WHERE r.id = ?
        GROUP BY r.id, r.name, r.is_locked
        """,
        (role_id,),
    )
    role = cursor.fetchone()

    if not role:
        connection.close()
        return False, "Role not found."

    if role["is_locked"]:
        connection.close()
        return False, "Locked roles cannot be deleted."

    if role["assigned_count"] > 0:
        connection.close()
        return False, "Remove this role from all accounts before deleting it."

    cursor.execute("DELETE FROM roles WHERE id = ?", (role_id,))
    connection.commit()
    connection.close()
    return True, "Role deleted successfully."
