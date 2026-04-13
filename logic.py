"""Core schema/bootstrap module plus compatibility re-exports for extracted services."""

import json
import os
import re
import sqlite3
import hashlib
import secrets
from datetime import datetime, timedelta
from html import escape
from werkzeug.security import check_password_hash
from werkzeug.utils import secure_filename

from split_app.services.core import (
    ALLOWED_CHAT_ATTACHMENT_EXTENSIONS,
    ALLOWED_IMAGE_EXTENSIONS,
    ALLOWED_PROFILE_IMAGE_EXTENSIONS,
    CHAT_ATTACHMENT_DIR,
    CHAT_ATTACHMENT_WEB_PATH,
    CHAT_CHANNEL_COUNT,
    CHAT_PRESENCE_WINDOW_SECONDS,
    DB_PATH,
    DEFAULT_MARQUEE_STYLE,
    DEFAULT_ROLES,
    MARQUEE_STYLE_CHOICES,
    MAX_CHAT_ATTACHMENT_SIZE_BYTES,
    MAX_PROFILE_IMAGE_SIZE_BYTES,
    NEWS_IMAGE_DIR,
    NEWS_IMAGE_WEB_PATH,
    PASSWORD_REQUEST_STATUSES,
    PROFILE_AUDIT_EVENT_LABELS,
    PROFILE_FIELD_LABELS,
    PROFILE_IMAGE_DIR,
    PROFILE_IMAGE_WEB_PATH,
    PROFILE_PRIVATE_FIELDS,
    REMEMBER_ME_DAYS,
    THEME_CHOICES,
    build_profile_private_fields,
    build_static_upload_url,
    connect_db,
    ensure_chat_attachment_folder,
    ensure_db_folder,
    ensure_news_image_folder,
    ensure_profile_image_folder,
    get_initials,
    hash_password,
    is_password_hash,
    json_dumps,
    json_loads,
    normalize_role_names,
    normalize_theme,
    parse_timestamp,
    timestamp_now,
)
from split_app.services.content import (
    archive_marquee_item,
    archive_news_post,
    archive_notification,
    build_news_summary,
    build_notification_preview,
    create_marquee_item,
    create_news_post,
    create_notification,
    delete_marquee_item,
    delete_news_image,
    delete_news_post,
    delete_notification,
    ensure_unique_slug,
    get_all_notifications,
    get_marquee_settings,
    get_marquee_styles,
    get_news_post_by_slug,
    get_news_posts,
    get_notifications_for_user,
    list_news_images,
    move_marquee_item,
    parse_image_token,
    permanently_delete_marquee_item,
    permanently_delete_news_post,
    permanently_delete_notification,
    render_blog_content,
    render_chat_message_markup,
    render_inline_markup,
    render_notification_line,
    render_notification_markup,
    restore_marquee_item,
    restore_news_post,
    restore_notification,
    set_notification_state,
    slugify,
    strip_image_tokens,
    update_marquee_item,
    update_marquee_style,
    update_news_post,
)
from split_app.services.accounts import (
    count_users_with_role,
    create_role,
    create_user_account,
    delete_role,
    delete_user_account,
    ensure_role,
    fetch_role_by_name,
    get_all_users,
    get_assigned_roles,
    get_buttons,
    get_role_definitions,
    get_role_name_map,
    log_account_modification,
    migrate_legacy_user_roles,
    seed_default_roles,
    update_user_account,
)
from split_app.services.profiles import (
    build_editable_profile,
    build_profile_identity,
    build_profile_visibility_rows,
    create_profile_notifications,
    ensure_user_profile,
    get_password_change_requests_for_user,
    get_password_change_review_queue,
    get_profile_audit_entries,
    get_profile_context,
    get_profile_identity_map,
    get_profile_notifications_for_user,
    get_profile_request_counts,
    get_public_profile_context,
    get_role_members,
    log_profile_audit,
    migrate_plaintext_passwords,
    remove_profile_avatar,
    review_password_change_request,
    save_profile_avatar,
    save_profile_basic,
    save_profile_preferences,
    save_profile_privacy,
    seed_default_user_profiles,
    set_profile_notification_state,
    submit_password_change_request,
    build_profile_avatar,
)
from split_app.services.chat_auth import (
    build_chat_attachment_payload,
    build_chat_message_payload,
    build_chat_message_preview,
    build_direct_room_key,
    build_presence_state,
    consume_remember_me_token,
    create_chat_message,
    create_remember_me_token,
    delete_remember_me_token,
    ensure_direct_thread,
    ensure_member_record,
    ensure_thread_memberships_for_user,
    get_chat_favorite_map,
    get_chat_overview,
    get_chat_thread_messages,
    get_presence_snapshot_map,
    get_role_group_settings,
    is_chat_favorite,
    move_chat_favorite,
    get_user_identity,
    get_user_roles_by_username,
    hash_remember_token,
    mark_chat_thread_read,
    mark_user_presence,
    purge_expired_remember_tokens,
    record_user_login,
    resolve_chat_thread,
    set_chat_favorite,
    update_chat_channel,
    update_role_group,
    user_has_role,
    validate_user,
)


def get_user_row_by_username(connection, username):
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT id, username, password, designation, userlevel, fullname, date_created, last_login_at
        FROM users
        WHERE lower(username) = lower(?)
        """,
        ((username or "").strip(),),
    )
    return cursor.fetchone()


def get_user_row_by_id(connection, user_id):
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT id, username, password, designation, userlevel, fullname, date_created, last_login_at
        FROM users
        WHERE id = ?
        """,
        (user_id,),
    )
    return cursor.fetchone()


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
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_favorites (
            owner_username TEXT NOT NULL,
            favorite_username TEXT NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (owner_username, favorite_username)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS user_profiles (
            user_id INTEGER PRIMARY KEY,
            display_name TEXT,
            department TEXT,
            phone TEXT,
            email TEXT,
            address TEXT,
            birthday TEXT,
            bio TEXT,
            avatar_path TEXT,
            private_fields_json TEXT NOT NULL DEFAULT '[]',
            theme_preference TEXT NOT NULL DEFAULT 'dark',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS profile_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            actor_username TEXT,
            event_type TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS profile_notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            link_url TEXT,
            style_key TEXT NOT NULL DEFAULT 'info',
            sender_name TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS profile_notification_states (
            user_id INTEGER NOT NULL,
            notification_key TEXT NOT NULL,
            is_read INTEGER NOT NULL DEFAULT 0,
            is_hidden INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (user_id, notification_key)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS password_change_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            requester_user_id INTEGER NOT NULL,
            password_hash TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            reviewed_by_username TEXT,
            rejection_note TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            reviewed_at TEXT
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_chat_threads_type ON chat_threads(thread_type)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_chat_messages_thread_created ON chat_messages(thread_id, created_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_chat_members_username ON chat_thread_members(username)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_chat_favorites_owner_sort ON chat_favorites(owner_username, sort_order)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_profiles_theme ON user_profiles(theme_preference)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_profile_audit_user ON profile_audit_log(user_id, created_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_profile_notifications_user ON profile_notifications(user_id, created_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_password_requests_user ON password_change_requests(requester_user_id, created_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_password_requests_status ON password_change_requests(status, created_at)")
    connection.commit()

    from forms_workflow import ensure_form_workflow_schema

    ensure_form_workflow_schema(connection)

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

    cursor.execute("PRAGMA table_info(user_profiles)")
    user_profile_columns = {row["name"] for row in cursor.fetchall()}
    if "display_name" not in user_profile_columns:
        cursor.execute("ALTER TABLE user_profiles ADD COLUMN display_name TEXT")
    if "department" not in user_profile_columns:
        cursor.execute("ALTER TABLE user_profiles ADD COLUMN department TEXT")
    if "phone" not in user_profile_columns:
        cursor.execute("ALTER TABLE user_profiles ADD COLUMN phone TEXT")
    if "email" not in user_profile_columns:
        cursor.execute("ALTER TABLE user_profiles ADD COLUMN email TEXT")
    if "address" not in user_profile_columns:
        cursor.execute("ALTER TABLE user_profiles ADD COLUMN address TEXT")
    if "birthday" not in user_profile_columns:
        cursor.execute("ALTER TABLE user_profiles ADD COLUMN birthday TEXT")
    if "bio" not in user_profile_columns:
        cursor.execute("ALTER TABLE user_profiles ADD COLUMN bio TEXT")
    if "avatar_path" not in user_profile_columns:
        cursor.execute("ALTER TABLE user_profiles ADD COLUMN avatar_path TEXT")
    if "private_fields_json" not in user_profile_columns:
        cursor.execute("ALTER TABLE user_profiles ADD COLUMN private_fields_json TEXT NOT NULL DEFAULT '[]'")
    if "theme_preference" not in user_profile_columns:
        cursor.execute("ALTER TABLE user_profiles ADD COLUMN theme_preference TEXT NOT NULL DEFAULT 'dark'")
    if "created_at" not in user_profile_columns:
        cursor.execute("ALTER TABLE user_profiles ADD COLUMN created_at TEXT")
    if "updated_at" not in user_profile_columns:
        cursor.execute("ALTER TABLE user_profiles ADD COLUMN updated_at TEXT")

    cursor.execute("PRAGMA table_info(password_change_requests)")
    password_request_columns = {row["name"] for row in cursor.fetchall()}
    if "reviewed_by_username" not in password_request_columns:
        cursor.execute("ALTER TABLE password_change_requests ADD COLUMN reviewed_by_username TEXT")
    if "rejection_note" not in password_request_columns:
        cursor.execute("ALTER TABLE password_change_requests ADD COLUMN rejection_note TEXT")
    if "reviewed_at" not in password_request_columns:
        cursor.execute("ALTER TABLE password_change_requests ADD COLUMN reviewed_at TEXT")

    cursor.execute("SELECT id FROM users WHERE username = ?", ("RO_Admin",))
    if not cursor.fetchone():
        cursor.execute(
            """
            INSERT INTO users (username, password, designation, userlevel, fullname, date_created)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("RO_Admin", hash_password("1234"), "admin", "SuperAdmin", "Regional Admin", timestamp_now()),
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

    seed_default_user_profiles(connection)
    migrate_plaintext_passwords(connection)

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


