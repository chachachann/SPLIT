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
    "open",
    "pending_assignment",
    "assigned",
    "in_review",
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
    "calendar",
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
    if clean_usernames:
        try:
            from split_app.workflow.smtp import send_email_to_usernames

            send_email_to_usernames(
                clean_usernames,
                title,
                message,
                link_url=link_url,
                sender_name=sender_name,
            )
        except Exception:
            pass


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
            requires_review INTEGER NOT NULL DEFAULT 1,
            deadline_days INTEGER,
            next_form_id INTEGER,
            assignment_review_type TEXT,
            assignment_review_value TEXT,
            access_roles_json TEXT NOT NULL DEFAULT '[]',
            access_users_json TEXT NOT NULL DEFAULT '[]',
            library_roles_json TEXT NOT NULL DEFAULT '[]',
            library_users_json TEXT NOT NULL DEFAULT '[]',
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
        CREATE TABLE IF NOT EXISTS form_promotion_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_form_id INTEGER NOT NULL,
            target_form_id INTEGER NOT NULL,
            rule_order INTEGER NOT NULL DEFAULT 1,
            spawn_mode TEXT NOT NULL DEFAULT 'automatic',
            default_deadline_days INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_cases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tracking_number TEXT NOT NULL UNIQUE,
            owner_username TEXT NOT NULL,
            requester_username TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            archived_at TEXT
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS form_submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id INTEGER,
            form_id INTEGER NOT NULL,
            form_version_id INTEGER NOT NULL,
            owner_username TEXT NOT NULL,
            requester_username TEXT NOT NULL,
            parent_submission_id INTEGER,
            root_submission_id INTEGER,
            tracking_number TEXT UNIQUE,
            tracking_prefix TEXT,
            status TEXT NOT NULL DEFAULT 'draft',
            data_json TEXT NOT NULL DEFAULT '{}',
            current_stage_index INTEGER NOT NULL DEFAULT 0,
            current_task_order INTEGER NOT NULL DEFAULT 0,
            promoted_to_submission_id INTEGER,
            cancel_reason TEXT,
            reject_reason TEXT,
            acceptance_note TEXT,
            assigned_to_username TEXT,
            assignment_requested_by_username TEXT,
            assignment_requested_at TEXT,
            assignment_note TEXT,
            pool_roles_json TEXT NOT NULL DEFAULT '[]',
            pool_users_json TEXT NOT NULL DEFAULT '[]',
            assignment_review_type TEXT,
            assignment_review_value TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            submitted_at TEXT,
            deadline_at TEXT,
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
            original_name TEXT NOT NULL,
            stored_name TEXT NOT NULL,
            file_ext TEXT NOT NULL,
            mime_type TEXT,
            file_size_bytes INTEGER NOT NULL DEFAULT 0,
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
            is_active INTEGER NOT NULL DEFAULT 1,
            acted_at TEXT,
            acted_by_username TEXT,
            action_note TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT
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
            from_name TEXT,
            use_tls INTEGER NOT NULL DEFAULT 1,
            use_ssl INTEGER NOT NULL DEFAULT 0,
            is_enabled INTEGER NOT NULL DEFAULT 0,
            last_tested_at TEXT,
            last_error TEXT,
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

    cursor.execute("PRAGMA table_info(smtp_settings)")
    smtp_columns = {row["name"] for row in cursor.fetchall()}
    if "from_name" not in smtp_columns:
        cursor.execute("ALTER TABLE smtp_settings ADD COLUMN from_name TEXT")
    if "use_ssl" not in smtp_columns:
        cursor.execute("ALTER TABLE smtp_settings ADD COLUMN use_ssl INTEGER NOT NULL DEFAULT 0")
    if "is_enabled" not in smtp_columns:
        cursor.execute("ALTER TABLE smtp_settings ADD COLUMN is_enabled INTEGER NOT NULL DEFAULT 0")
    if "last_tested_at" not in smtp_columns:
        cursor.execute("ALTER TABLE smtp_settings ADD COLUMN last_tested_at TEXT")
    if "last_error" not in smtp_columns:
        cursor.execute("ALTER TABLE smtp_settings ADD COLUMN last_error TEXT")

    cursor.execute("PRAGMA table_info(forms)")
    form_columns = {row["name"] for row in cursor.fetchall()}
    if "requires_review" not in form_columns:
        cursor.execute("ALTER TABLE forms ADD COLUMN requires_review INTEGER NOT NULL DEFAULT 1")
    if "deadline_days" not in form_columns:
        cursor.execute("ALTER TABLE forms ADD COLUMN deadline_days INTEGER")
    if "next_form_id" not in form_columns:
        cursor.execute("ALTER TABLE forms ADD COLUMN next_form_id INTEGER")
    if "assignment_review_type" not in form_columns:
        cursor.execute("ALTER TABLE forms ADD COLUMN assignment_review_type TEXT")
    if "assignment_review_value" not in form_columns:
        cursor.execute("ALTER TABLE forms ADD COLUMN assignment_review_value TEXT")
    if "library_roles_json" not in form_columns:
        cursor.execute("ALTER TABLE forms ADD COLUMN library_roles_json TEXT NOT NULL DEFAULT '[]'")
    if "library_users_json" not in form_columns:
        cursor.execute("ALTER TABLE forms ADD COLUMN library_users_json TEXT NOT NULL DEFAULT '[]'")
    cursor.execute(
        """
        UPDATE forms
        SET
            library_roles_json = CASE
                WHEN COALESCE(trim(library_roles_json), '') IN ('', '[]') THEN access_roles_json
                ELSE library_roles_json
            END,
            library_users_json = CASE
                WHEN COALESCE(trim(library_users_json), '') IN ('', '[]') THEN access_users_json
                ELSE library_users_json
            END
        """
    )

    cursor.execute("PRAGMA table_info(form_submissions)")
    form_submission_columns = {row["name"] for row in cursor.fetchall()}
    if "case_id" not in form_submission_columns:
        cursor.execute("ALTER TABLE form_submissions ADD COLUMN case_id INTEGER")
    if "parent_submission_id" not in form_submission_columns:
        cursor.execute("ALTER TABLE form_submissions ADD COLUMN parent_submission_id INTEGER")
    if "root_submission_id" not in form_submission_columns:
        cursor.execute("ALTER TABLE form_submissions ADD COLUMN root_submission_id INTEGER")
    if "promoted_to_submission_id" not in form_submission_columns:
        cursor.execute("ALTER TABLE form_submissions ADD COLUMN promoted_to_submission_id INTEGER")
    if "reject_reason" not in form_submission_columns:
        cursor.execute("ALTER TABLE form_submissions ADD COLUMN reject_reason TEXT")
    if "acceptance_note" not in form_submission_columns:
        cursor.execute("ALTER TABLE form_submissions ADD COLUMN acceptance_note TEXT")
    if "deadline_at" not in form_submission_columns:
        cursor.execute("ALTER TABLE form_submissions ADD COLUMN deadline_at TEXT")
    if "assigned_to_username" not in form_submission_columns:
        cursor.execute("ALTER TABLE form_submissions ADD COLUMN assigned_to_username TEXT")
    if "assignment_requested_by_username" not in form_submission_columns:
        cursor.execute("ALTER TABLE form_submissions ADD COLUMN assignment_requested_by_username TEXT")
    if "assignment_requested_at" not in form_submission_columns:
        cursor.execute("ALTER TABLE form_submissions ADD COLUMN assignment_requested_at TEXT")
    if "assignment_note" not in form_submission_columns:
        cursor.execute("ALTER TABLE form_submissions ADD COLUMN assignment_note TEXT")
    if "pool_roles_json" not in form_submission_columns:
        cursor.execute("ALTER TABLE form_submissions ADD COLUMN pool_roles_json TEXT NOT NULL DEFAULT '[]'")
    if "pool_users_json" not in form_submission_columns:
        cursor.execute("ALTER TABLE form_submissions ADD COLUMN pool_users_json TEXT NOT NULL DEFAULT '[]'")
    if "assignment_review_type" not in form_submission_columns:
        cursor.execute("ALTER TABLE form_submissions ADD COLUMN assignment_review_type TEXT")
    if "assignment_review_value" not in form_submission_columns:
        cursor.execute("ALTER TABLE form_submissions ADD COLUMN assignment_review_value TEXT")

    cursor.execute("PRAGMA table_info(form_submission_files)")
    form_file_columns = {row["name"] for row in cursor.fetchall()}
    if "original_name" not in form_file_columns:
        cursor.execute("ALTER TABLE form_submission_files ADD COLUMN original_name TEXT")
    if "stored_name" not in form_file_columns:
        cursor.execute("ALTER TABLE form_submission_files ADD COLUMN stored_name TEXT")
    if "file_ext" not in form_file_columns:
        cursor.execute("ALTER TABLE form_submission_files ADD COLUMN file_ext TEXT")
    if "mime_type" not in form_file_columns:
        cursor.execute("ALTER TABLE form_submission_files ADD COLUMN mime_type TEXT")
    if "file_size_bytes" not in form_file_columns:
        cursor.execute("ALTER TABLE form_submission_files ADD COLUMN file_size_bytes INTEGER NOT NULL DEFAULT 0")
    if {"file_name", "file_path"} & form_file_columns:
        original_expr = "COALESCE(original_name, file_name)" if "file_name" in form_file_columns else "COALESCE(original_name, '')"
        stored_expr = "COALESCE(stored_name, file_path)" if "file_path" in form_file_columns else "COALESCE(stored_name, '')"
        cursor.execute(
            f"""
            UPDATE form_submission_files
            SET
                original_name = {original_expr},
                stored_name = {stored_expr},
                file_ext = COALESCE(file_ext, ''),
                file_size_bytes = COALESCE(file_size_bytes, 0)
            WHERE
                (original_name IS NULL OR original_name = '')
                OR (stored_name IS NULL OR stored_name = '')
                OR file_ext IS NULL
            """
        )

    cursor.execute("PRAGMA table_info(form_review_tasks)")
    form_task_columns = {row["name"] for row in cursor.fetchall()}
    if "action_note" not in form_task_columns:
        cursor.execute("ALTER TABLE form_review_tasks ADD COLUMN action_note TEXT")
    if "updated_at" not in form_task_columns:
        cursor.execute("ALTER TABLE form_review_tasks ADD COLUMN updated_at TEXT")

    cursor.execute(
        """
        SELECT
            id,
            case_id,
            root_submission_id,
            tracking_number,
            owner_username,
            requester_username,
            status,
            created_at,
            submitted_at,
            archived_at
        FROM form_submissions
        WHERE case_id IS NULL
          AND status != 'draft'
        ORDER BY COALESCE(root_submission_id, id), id
        """
    )
    orphaned_submissions = [dict(row) for row in cursor.fetchall()]
    case_map = {}
    for row in orphaned_submissions:
        root_id = row["root_submission_id"] or row["id"]
        case_id = case_map.get(root_id)
        if not case_id:
            tracking_number = (row.get("tracking_number") or f"CASE-{root_id}").strip()
            cursor.execute("SELECT id FROM workflow_cases WHERE tracking_number = ?", (tracking_number,))
            existing_case = cursor.fetchone()
            if existing_case:
                case_id = existing_case["id"]
            else:
                created_at = row.get("submitted_at") or row.get("created_at") or timestamp_now()
                updated_at = row.get("archived_at") or row.get("submitted_at") or row.get("created_at") or created_at
                cursor.execute(
                    """
                    INSERT INTO workflow_cases (
                        tracking_number,
                        owner_username,
                        requester_username,
                        created_at,
                        updated_at,
                        archived_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        tracking_number,
                        row["owner_username"],
                        row["requester_username"],
                        created_at,
                        updated_at,
                        row.get("archived_at"),
                    ),
                )
                case_id = cursor.lastrowid
            case_map[root_id] = case_id
        cursor.execute("UPDATE form_submissions SET case_id = ? WHERE id = ?", (case_id, row["id"]))

    cursor.execute(
        """
        SELECT id, next_form_id
        FROM forms
        WHERE next_form_id IS NOT NULL
        """
    )
    for row in cursor.fetchall():
        cursor.execute(
            """
            SELECT id
            FROM form_promotion_rules
            WHERE source_form_id = ? AND target_form_id = ?
            """,
            (row["id"], row["next_form_id"]),
        )
        if cursor.fetchone():
            continue
        now = timestamp_now()
        cursor.execute(
            """
            INSERT INTO form_promotion_rules (
                source_form_id,
                target_form_id,
                rule_order,
                spawn_mode,
                default_deadline_days,
                created_at,
                updated_at
            )
            VALUES (?, ?, 1, 'automatic', NULL, ?, ?)
            """,
            (row["id"], row["next_form_id"], now, now),
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
