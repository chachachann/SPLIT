import json
import os
import re
from html import escape

from logic import connect_db, get_initials, get_profile_identity_map, normalize_role_names, timestamp_now


FORM_UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", "static", "uploads", "forms")
FORM_ICON_DIR = os.path.join(FORM_UPLOAD_DIR, "icons")
FORM_FILE_DIR = os.path.join(FORM_UPLOAD_DIR, "submissions")

ALLOWED_FORM_IMAGE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
    ".heic",
    ".heif",
}
ALLOWED_FORM_DOCUMENT_EXTENSIONS = {
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".txt",
}
MAX_FORM_FILE_SIZE_BYTES = 50 * 1024 * 1024
MAX_FORM_IMAGE_COUNT = 5
MAX_FORM_DOCUMENT_COUNT = 20

FORM_STATUSES = {"draft", "published", "archived"}
SUBMISSION_STATUSES = {
    "draft",
    "pending",
    "accepted",
    "rejected",
    "cancelled",
    "promoted",
    "completed",
    "archived",
}
FIELD_TYPES = {
    "short_text",
    "long_text",
    "number",
    "date",
    "dropdown",
    "checkbox",
    "image_upload",
    "file_upload",
}
STAGE_MODES = {"sequential", "parallel"}


def ensure_form_workflow_folders():
    os.makedirs(FORM_ICON_DIR, exist_ok=True)
    os.makedirs(FORM_FILE_DIR, exist_ok=True)


def _json_loads(value, fallback):
    if not value:
        return fallback
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if isinstance(parsed, type(fallback)) else fallback


def _json_dumps(value):
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _slugify(value):
    clean = re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower())
    clean = clean.strip("-")
    return clean or "form"


def _field_key(value, fallback_prefix="field"):
    clean = re.sub(r"[^a-z0-9_]+", "_", (value or "").strip().lower())
    clean = clean.strip("_")
    return clean or fallback_prefix


def _serialize_note(value):
    return " ".join((value or "").split()).strip()


def _is_truthy(value):
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _normalize_username_list(values):
    items = []
    seen = set()
    for value in values or []:
        clean = " ".join((value or "").split())
        if not clean:
            continue
        key = clean.casefold()
        if key in seen:
            continue
        seen.add(key)
        items.append(clean)
    return items


def _resolve_fullname(connection, username):
    identity_map = get_profile_identity_map(connection, [username], viewer_username=username)
    identity = identity_map.get((username or "").strip().casefold())
    if not identity:
        return (username or "").strip()
    return (identity.get("display_name") or "").strip() or (username or "").strip()


def _role_members(connection, role_name):
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT u.username
        FROM users u
        INNER JOIN user_roles ur ON ur.user_id = u.id
        INNER JOIN roles r ON r.id = ur.role_id
        WHERE lower(r.name) = lower(?)
        ORDER BY u.username COLLATE NOCASE
        """,
        (role_name,),
    )
    return [row["username"] for row in cursor.fetchall()]


def _audit(connection, event_type, actor_username, entity_type, entity_id=None, tracking_number=None, payload=None):
    connection.execute(
        """
        INSERT INTO form_audit_log (
            event_type,
            actor_username,
            actor_fullname_snapshot,
            entity_type,
            entity_id,
            tracking_number,
            payload_json,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_type,
            (actor_username or "").strip() or None,
            _resolve_fullname(connection, actor_username) if actor_username else None,
            entity_type,
            entity_id,
            tracking_number,
            _json_dumps(payload or {}),
            timestamp_now(),
        ),
    )


def _notify_users(connection, usernames, title, message, link_url="", style_key="info", sender_name="System"):
    now = timestamp_now()
    clean_usernames = _normalize_username_list(usernames)
    for username in clean_usernames:
        connection.execute(
            """
            INSERT INTO form_user_notifications (
                username,
                title,
                message,
                link_url,
                style_key,
                sender_name,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                username,
                title,
                message,
                link_url or None,
                style_key or "info",
                sender_name or "System",
                now,
            ),
        )


def _build_preview(value, limit=140):
    text = re.sub(r"\s+", " ", (value or "").strip())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def ensure_form_workflow_schema(connection):
    ensure_form_workflow_folders()
    cursor = connection.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS forms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            form_key TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            description TEXT,
            quick_label TEXT NOT NULL,
            quick_icon_type TEXT NOT NULL DEFAULT 'emoji',
            quick_icon_value TEXT,
            quick_card_style_json TEXT NOT NULL DEFAULT '{}',
            tracking_prefix TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft',
            allow_cancel INTEGER NOT NULL DEFAULT 1,
            allow_multiple_active INTEGER NOT NULL DEFAULT 1,
            access_roles_json TEXT NOT NULL DEFAULT '[]',
            access_users_json TEXT NOT NULL DEFAULT '[]',
            review_stages_json TEXT NOT NULL DEFAULT '[]',
            current_version_id INTEGER,
            created_by_username TEXT NOT NULL,
            updated_by_username TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            archived_at TEXT
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS form_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            form_id INTEGER NOT NULL,
            version_number INTEGER NOT NULL,
            schema_json TEXT NOT NULL DEFAULT '[]',
            created_by_username TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS form_submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            form_id INTEGER NOT NULL,
            form_version_id INTEGER NOT NULL,
            owner_username TEXT NOT NULL,
            requester_username TEXT NOT NULL,
            tracking_number TEXT UNIQUE,
            tracking_prefix TEXT,
            status TEXT NOT NULL DEFAULT 'draft',
            data_json TEXT NOT NULL DEFAULT '{}',
            current_stage_index INTEGER NOT NULL DEFAULT 0,
            current_task_order INTEGER NOT NULL DEFAULT 0,
            cancel_reason TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            submitted_at TEXT,
            completed_at TEXT,
            archived_at TEXT
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS form_submission_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            submission_id INTEGER NOT NULL,
            field_key TEXT NOT NULL,
            file_name TEXT NOT NULL,
            file_path TEXT NOT NULL,
            file_kind TEXT NOT NULL,
            uploaded_by_username TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS form_review_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            submission_id INTEGER NOT NULL,
            stage_index INTEGER NOT NULL,
            task_order INTEGER NOT NULL DEFAULT 0,
            reviewer_type TEXT NOT NULL,
            reviewer_value TEXT NOT NULL,
            task_status TEXT NOT NULL DEFAULT 'pending',
            note TEXT,
            acted_by_username TEXT,
            acted_at TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS form_comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            submission_id INTEGER NOT NULL,
            author_username TEXT NOT NULL,
            author_fullname_snapshot TEXT,
            body TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS form_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            actor_username TEXT,
            actor_fullname_snapshot TEXT,
            entity_type TEXT NOT NULL,
            entity_id INTEGER,
            tracking_number TEXT,
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS form_user_notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            link_url TEXT,
            style_key TEXT NOT NULL DEFAULT 'info',
            sender_name TEXT,
            is_read INTEGER NOT NULL DEFAULT 0,
            is_hidden INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS form_tracking_sequence (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            next_number INTEGER NOT NULL DEFAULT 1
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS smtp_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            host TEXT,
            port INTEGER,
            username TEXT,
            password_obfuscated TEXT,
            from_email TEXT,
            use_tls INTEGER NOT NULL DEFAULT 1,
            updated_by_username TEXT,
            updated_at TEXT NOT NULL
        )
        """
    )

    cursor.execute("SELECT id FROM form_tracking_sequence WHERE id = 1")
    if not cursor.fetchone():
        cursor.execute("INSERT INTO form_tracking_sequence (id, next_number) VALUES (1, 1)")

    cursor.execute("SELECT id FROM smtp_settings WHERE id = 1")
    if not cursor.fetchone():
        cursor.execute(
            """
            INSERT INTO smtp_settings (id, use_tls, updated_at)
            VALUES (1, 1, ?)
            """,
            (timestamp_now(),),
        )

    connection.commit()


def get_form_notifications_for_user(username):
    username = (username or "").strip()
    if not username:
        return []
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT
            id,
            title,
            message,
            link_url,
            style_key,
            sender_name,
            is_read,
            is_hidden,
            created_at
        FROM form_user_notifications
        WHERE username = ? AND is_hidden = 0
        ORDER BY datetime(created_at) DESC, id DESC
        """,
        (username,),
    )
    items = []
    for row in cursor.fetchall():
        item = dict(row)
        item["notification_key"] = f"form:{item['id']}"
        item["message_preview"] = _build_preview(item.get("message"))
        item["message_html"] = "<p>" + escape(item.get("message") or "") + "</p>"
        items.append(item)
    connection.close()
    return items


def set_form_notification_state(username, notification_key, *, is_read=None, is_hidden=None):
    username = (username or "").strip()
    key = (notification_key or "").strip()
    if not username or not key.startswith("form:"):
        return False
    try:
        notification_id = int(key.split(":", 1)[1])
    except (TypeError, ValueError):
        return False
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT id, is_read, is_hidden
        FROM form_user_notifications
        WHERE id = ? AND username = ?
        """,
        (notification_id, username),
    )
    row = cursor.fetchone()
    if not row:
        connection.close()
        return False
    next_read = int(row["is_read"]) if is_read is None else (1 if is_read else 0)
    next_hidden = int(row["is_hidden"]) if is_hidden is None else (1 if is_hidden else 0)
    connection.execute(
        """
        UPDATE form_user_notifications
        SET is_read = ?, is_hidden = ?
        WHERE id = ? AND username = ?
        """,
        (next_read, next_hidden, notification_id, username),
    )
    connection.commit()
    connection.close()
    return True
