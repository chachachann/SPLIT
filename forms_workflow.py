import json
import os
import re
from html import escape

from werkzeug.utils import secure_filename

from logic import connect_db, get_initials, get_profile_identity_map, normalize_role_names, timestamp_now


FORM_UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "static", "uploads", "forms")
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
            reject_reason TEXT,
            acceptance_note TEXT,
            submitted_at TEXT,
            completed_at TEXT,
            archived_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
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
            task_order INTEGER NOT NULL,
            reviewer_type TEXT NOT NULL,
            reviewer_value TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 0,
            task_status TEXT NOT NULL DEFAULT 'pending',
            acted_at TEXT,
            acted_by_username TEXT,
            action_note TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS form_submission_comments (
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
            sender_name TEXT NOT NULL DEFAULT 'System',
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
            next_number INTEGER NOT NULL
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
            updated_by_username TEXT,
            updated_at TEXT
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_forms_status ON forms(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_form_submissions_owner ON form_submissions(owner_username, status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_form_submissions_requester ON form_submissions(requester_username, status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_form_review_tasks_lookup ON form_review_tasks(reviewer_type, reviewer_value, is_active, task_status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_form_notifications_user ON form_user_notifications(username, is_hidden, is_read, created_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_form_comments_submission ON form_submission_comments(submission_id, created_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_form_audit_entity ON form_audit_log(entity_type, entity_id, created_at)")

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


def _parse_field_schema(schema_json):
    fields = _json_loads(schema_json, [])
    parsed = []
    seen_keys = set()
    for index, raw_field in enumerate(fields, start=1):
        if not isinstance(raw_field, dict):
            continue
        field_type = str(raw_field.get("type") or "").strip()
        if field_type not in FIELD_TYPES:
            continue
        field_key = _field_key(raw_field.get("key") or raw_field.get("label") or f"field_{index}", f"field_{index}")
        if field_key in seen_keys:
            raise ValueError(f"Duplicate field key: {field_key}")
        seen_keys.add(field_key)
        label = " ".join(str(raw_field.get("label") or "").split()).strip() or f"Field {index}"
        validation = raw_field.get("validation") if isinstance(raw_field.get("validation"), dict) else {}
        conditional_logic = raw_field.get("conditional_logic")
        if conditional_logic not in (None, "") and not isinstance(conditional_logic, dict):
            raise ValueError(f"Conditional logic for {field_key} must be a JSON object.")
        options = raw_field.get("options") if isinstance(raw_field.get("options"), list) else []
        parsed.append(
            {
                "key": field_key,
                "label": label,
                "type": field_type,
                "help_text": str(raw_field.get("help_text") or "").strip(),
                "required": bool(raw_field.get("required")),
                "default_value": raw_field.get("default_value"),
                "validation": validation,
                "options": [str(option).strip() for option in options if str(option).strip()],
                "conditional_logic": conditional_logic,
                "hide_on_promotion": bool(raw_field.get("hide_on_promotion")),
            }
        )
    return parsed


def _parse_review_stages(stages_json):
    stages = _json_loads(stages_json, [])
    parsed = []
    for index, raw_stage in enumerate(stages, start=1):
        if not isinstance(raw_stage, dict):
            continue
        mode = str(raw_stage.get("mode") or "").strip().lower() or "sequential"
        if mode not in STAGE_MODES:
            raise ValueError(f"Unsupported review stage mode at stage {index}.")
        name = " ".join(str(raw_stage.get("name") or "").split()).strip() or f"Stage {index}"
        reviewers = []
        for order, raw_reviewer in enumerate(raw_stage.get("reviewers") or [], start=1):
            if not isinstance(raw_reviewer, dict):
                continue
            reviewer_type = str(raw_reviewer.get("type") or "").strip().lower()
            reviewer_value = " ".join(str(raw_reviewer.get("value") or "").split()).strip()
            if reviewer_type not in {"role", "user"} or not reviewer_value:
                continue
            reviewers.append(
                {
                    "type": reviewer_type,
                    "value": reviewer_value,
                    "order": order,
                }
            )
        if not reviewers:
            raise ValueError(f"Review stage {name} must contain at least one reviewer.")
        parsed.append(
            {
                "name": name,
                "mode": mode,
                "reviewers": reviewers,
            }
        )
    return parsed


def _form_row_to_dict(connection, row, include_version=True):
    item = dict(row)
    item["access_roles"] = _json_loads(item.get("access_roles_json"), [])
    item["access_users"] = _json_loads(item.get("access_users_json"), [])
    item["review_stages"] = _json_loads(item.get("review_stages_json"), [])
    item["quick_card_style"] = _json_loads(item.get("quick_card_style_json"), {})
    item["allow_cancel"] = bool(item.get("allow_cancel"))
    item["allow_multiple_active"] = bool(item.get("allow_multiple_active"))
    item["schema"] = []
    if include_version and item.get("current_version_id"):
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT id, version_number, schema_json, created_by_username, created_at
            FROM form_versions
            WHERE id = ?
            """,
            (item["current_version_id"],),
        )
        version = cursor.fetchone()
        if version:
            item["current_version"] = dict(version)
            item["schema"] = _json_loads(version["schema_json"], [])
        else:
            item["current_version"] = None
    else:
        item["current_version"] = None
    return item


def list_forms_for_manager(status_filter="all"):
    connection = connect_db()
    cursor = connection.cursor()
    params = []
    where_clause = ""
    if status_filter in FORM_STATUSES:
        where_clause = "WHERE status = ?"
        params.append(status_filter)
    cursor.execute(
        f"""
        SELECT
            f.*,
            (
                SELECT COUNT(*)
                FROM form_submissions s
                WHERE s.form_id = f.id
            ) AS submission_count
        FROM forms f
        {where_clause}
        ORDER BY
            CASE f.status
                WHEN 'published' THEN 0
                WHEN 'draft' THEN 1
                ELSE 2
            END,
            f.title COLLATE NOCASE
        """,
        tuple(params),
    )
    forms = [_form_row_to_dict(connection, row) for row in cursor.fetchall()]
    cursor.execute(
        """
        SELECT
            status,
            COUNT(*) AS total
        FROM forms
        GROUP BY status
        """
    )
    counts = {"draft": 0, "published": 0, "archived": 0}
    for row in cursor.fetchall():
        counts[row["status"]] = row["total"]
    connection.close()
    return {"forms": forms, "counts": counts}


def get_form_template(form_key):
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute("SELECT * FROM forms WHERE form_key = ?", ((form_key or "").strip(),))
    row = cursor.fetchone()
    if not row:
        connection.close()
        return None
    form = _form_row_to_dict(connection, row)
    cursor.execute(
        """
        SELECT id, version_number, created_by_username, created_at
        FROM form_versions
        WHERE form_id = ?
        ORDER BY version_number DESC
        """,
        (form["id"],),
    )
    form["versions"] = [dict(item) for item in cursor.fetchall()]
    cursor.execute("SELECT username FROM users ORDER BY username COLLATE NOCASE")
    available_users = [dict(item) for item in cursor.fetchall()]
    identity_map = get_profile_identity_map(connection, [item["username"] for item in available_users], viewer_username="")
    form["available_users"] = []
    for item in available_users:
        identity = identity_map.get(item["username"].casefold())
        form["available_users"].append(
            {
                "username": item["username"],
                "fullname": (identity.get("display_name") if identity else "") or item["username"],
            }
        )
    cursor.execute("SELECT name FROM roles ORDER BY name COLLATE NOCASE")
    form["available_roles"] = [row["name"] for row in cursor.fetchall()]
    cursor.execute(
        """
        SELECT COUNT(*) AS total
        FROM form_submissions
        WHERE form_id = ?
        """,
        (form["id"],),
    )
    form["submission_count"] = cursor.fetchone()["total"]
    connection.close()
    return form


def create_form_template(title, actor_username):
    title = " ".join((title or "").split()).strip()
    if not title:
        return False, "Enter a form title.", None
    form_key = _slugify(title)
    connection = connect_db()
    cursor = connection.cursor()
    candidate = form_key
    suffix = 2
    while True:
        cursor.execute("SELECT id FROM forms WHERE form_key = ?", (candidate,))
        if not cursor.fetchone():
            break
        candidate = f"{form_key}-{suffix}"
        suffix += 1
    now = timestamp_now()
    cursor.execute(
        """
        INSERT INTO forms (
            form_key,
            title,
            description,
            quick_label,
            quick_icon_type,
            quick_icon_value,
            quick_card_style_json,
            tracking_prefix,
            status,
            allow_cancel,
            allow_multiple_active,
            access_roles_json,
            access_users_json,
            review_stages_json,
            created_by_username,
            updated_by_username,
            created_at,
            updated_at
        )
        VALUES (?, ?, '', ?, 'emoji', ?, ?, ?, 'draft', 1, 1, '[]', '[]', '[]', ?, ?, ?, ?)
        """,
        (
            candidate,
            title,
            title,
            "FM",
            _json_dumps({"accent": "#43e493"}),
            _slugify(title).replace("-", "").upper()[:10] or "FORM",
            actor_username,
            actor_username,
            now,
            now,
        ),
    )
    form_id = cursor.lastrowid
    cursor.execute(
        """
        INSERT INTO form_versions (
            form_id,
            version_number,
            schema_json,
            created_by_username,
            created_at
        )
        VALUES (?, 1, '[]', ?, ?)
        """,
        (form_id, actor_username, now),
    )
    version_id = cursor.lastrowid
    cursor.execute("UPDATE forms SET current_version_id = ? WHERE id = ?", (version_id, form_id))
    _audit(connection, "form.created", actor_username, "form", form_id, payload={"form_key": candidate, "title": title})
    connection.commit()
    connection.close()
    return True, "Form created.", candidate


def _save_icon_upload(upload):
    if not upload or not upload.filename:
        return None, ""
    ensure_form_workflow_folders()
    filename = secure_filename(upload.filename)
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_FORM_IMAGE_EXTENSIONS:
        return None, "Unsupported form icon type."
    stem = os.path.splitext(filename)[0] or "form-icon"
    candidate = filename
    suffix = 2
    while os.path.exists(os.path.join(FORM_ICON_DIR, candidate)):
        candidate = f"{stem}-{suffix}{ext}"
        suffix += 1
    upload.save(os.path.join(FORM_ICON_DIR, candidate))
    return f"uploads/forms/icons/{candidate}", ""


def save_form_definition(form_key, payload, actor_username, icon_upload=None):
    form = get_form_template(form_key)
    if not form:
        return False, "Form not found."

    title = " ".join(str(payload.get("title") or "").split()).strip()
    if not title:
        return False, "Form title is required."

    quick_label = " ".join(str(payload.get("quick_label") or "").split()).strip() or title
    description = str(payload.get("description") or "").strip()
    tracking_prefix = re.sub(r"[^A-Z0-9]+", "", str(payload.get("tracking_prefix") or "").upper())[:12]
    if not tracking_prefix:
        return False, "Tracking prefix is required."

    status = str(payload.get("status") or "draft").strip().lower()
    if status not in FORM_STATUSES:
        return False, "Unsupported form status."

    access_roles = normalize_role_names(payload.get("access_roles") or [])
    access_users = _normalize_username_list(payload.get("access_users") or [])

    try:
        schema = _parse_field_schema(payload.get("schema_json") or "[]")
        review_stages = _parse_review_stages(payload.get("review_stages_json") or "[]")
    except ValueError as error:
        return False, str(error)

    if status == "published":
        if not schema:
            return False, "Published forms must contain at least one field."
        if not access_roles:
            return False, "Published forms must have at least one access role."
        if not review_stages:
            return False, "Published forms must have at least one review stage."

    icon_type = str(payload.get("quick_icon_type") or "emoji").strip().lower() or "emoji"
    icon_value = str(payload.get("quick_icon_value") or "").strip()
    if icon_type not in {"emoji", "text", "image"}:
        icon_type = "emoji"
    if icon_type == "image":
        icon_path, error_message = _save_icon_upload(icon_upload)
        if error_message:
            return False, error_message
        if icon_path:
            icon_value = icon_path
        elif not icon_value:
            icon_type = "emoji"
            icon_value = "FM"

    card_style = {
        "accent": str(payload.get("card_accent") or "#43e493").strip() or "#43e493",
        "tone": str(payload.get("card_tone") or "mint").strip() or "mint",
    }
    allow_cancel = bool(payload.get("allow_cancel"))
    allow_multiple_active = bool(payload.get("allow_multiple_active"))

    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute("SELECT * FROM forms WHERE form_key = ?", (form_key,))
    row = cursor.fetchone()
    if not row:
        connection.close()
        return False, "Form not found."
    current_form = _form_row_to_dict(connection, row)
    current_schema_json = _json_dumps(current_form.get("schema") or [])
    next_schema_json = _json_dumps(schema)
    version_id = current_form.get("current_version_id")
    if current_schema_json != next_schema_json:
        next_version = int(current_form["current_version"]["version_number"]) + 1 if current_form.get("current_version") else 1
        cursor.execute(
            """
            INSERT INTO form_versions (
                form_id,
                version_number,
                schema_json,
                created_by_username,
                created_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (current_form["id"], next_version, next_schema_json, actor_username, timestamp_now()),
        )
        version_id = cursor.lastrowid

    cursor.execute(
        """
        UPDATE forms
        SET
            title = ?,
            description = ?,
            quick_label = ?,
            quick_icon_type = ?,
            quick_icon_value = ?,
            quick_card_style_json = ?,
            tracking_prefix = ?,
            status = ?,
            allow_cancel = ?,
            allow_multiple_active = ?,
            access_roles_json = ?,
            access_users_json = ?,
            review_stages_json = ?,
            current_version_id = ?,
            updated_by_username = ?,
            updated_at = ?,
            archived_at = CASE WHEN ? = 'archived' THEN COALESCE(archived_at, ?) ELSE NULL END
        WHERE id = ?
        """,
        (
            title,
            description,
            quick_label,
            icon_type,
            icon_value or None,
            _json_dumps(card_style),
            tracking_prefix,
            status,
            1 if allow_cancel else 0,
            1 if allow_multiple_active else 0,
            _json_dumps(access_roles),
            _json_dumps(access_users),
            _json_dumps(review_stages),
            version_id,
            actor_username,
            timestamp_now(),
            status,
            timestamp_now(),
            current_form["id"],
        ),
    )
    _audit(
        connection,
        "form.updated",
        actor_username,
        "form",
        current_form["id"],
        payload={
            "status": status,
            "title": title,
            "access_roles": access_roles,
            "access_users": access_users,
            "review_stage_count": len(review_stages),
            "field_count": len(schema),
        },
    )
    connection.commit()
    connection.close()
    return True, "Form saved."


def delete_form_template(form_key, actor_username):
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute("SELECT id FROM forms WHERE form_key = ?", ((form_key or "").strip(),))
    row = cursor.fetchone()
    if not row:
        connection.close()
        return False, "Form not found."
    form_id = row["id"]
    cursor.execute("SELECT COUNT(*) AS total FROM form_submissions WHERE form_id = ?", (form_id,))
    if cursor.fetchone()["total"] > 0:
        connection.close()
        return False, "Forms with submissions must be archived instead of deleted."
    _audit(connection, "form.deleted", actor_username, "form", form_id)
    cursor.execute("DELETE FROM form_versions WHERE form_id = ?", (form_id,))
    cursor.execute("DELETE FROM forms WHERE id = ?", (form_id,))
    connection.commit()
    connection.close()
    return True, "Form deleted."


def get_workflow_topbar_counts(username, role_names):
    username = (username or "").strip()
    if not username:
        return {"my_requests": 0, "review_queue": 0}
    normalized_roles = {role.casefold() for role in (role_names or [])}
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT COUNT(*) AS total
        FROM form_submissions
        WHERE (owner_username = ? OR requester_username = ?)
          AND status != 'archived'
        """,
        (username, username),
    )
    my_requests = cursor.fetchone()["total"]
    if normalized_roles:
        role_placeholders = ", ".join("?" for _ in normalized_roles)
        cursor.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM form_review_tasks
            WHERE is_active = 1
              AND task_status = 'pending'
              AND (
                    (reviewer_type = 'user' AND lower(reviewer_value) = lower(?))
                    OR (reviewer_type = 'role' AND lower(reviewer_value) IN ({role_placeholders}))
              )
            """,
            (username, *normalized_roles),
        )
    else:
        cursor.execute(
            """
            SELECT COUNT(*) AS total
            FROM form_review_tasks
            WHERE is_active = 1
              AND task_status = 'pending'
              AND reviewer_type = 'user'
              AND lower(reviewer_value) = lower(?)
            """,
            (username,),
        )
    review_queue = cursor.fetchone()["total"]
    connection.close()
    return {"my_requests": my_requests, "review_queue": review_queue}


def _user_matches_form_access(form, username, role_names):
    access_roles = {role.casefold() for role in (form.get("access_roles") or [])}
    access_users = {item.casefold() for item in (form.get("access_users") or [])}
    current_roles = {role.casefold() for role in (role_names or [])}
    if not access_roles:
        return False
    if not (access_roles & current_roles):
        return False
    if access_users and (username or "").casefold() not in access_users:
        return False
    return True


def list_dashboard_forms(username, role_names):
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT *
        FROM forms
        WHERE status = 'published'
        ORDER BY title COLLATE NOCASE
        """
    )
    items = []
    for row in cursor.fetchall():
        form = _form_row_to_dict(connection, row)
        if not _user_matches_form_access(form, username, role_names):
            continue
        items.append(form)
    connection.close()
    return items


def _get_form_by_key(connection, form_key):
    cursor = connection.cursor()
    cursor.execute("SELECT * FROM forms WHERE form_key = ?", ((form_key or "").strip(),))
    row = cursor.fetchone()
    return _form_row_to_dict(connection, row) if row else None


def _get_submission(connection, submission_id):
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT *
        FROM form_submissions
        WHERE id = ?
        """,
        (submission_id,),
    )
    row = cursor.fetchone()
    if not row:
        return None
    item = dict(row)
    item["data"] = _json_loads(item.get("data_json"), {})
    cursor.execute(
        """
        SELECT *
        FROM form_submission_files
        WHERE submission_id = ?
        ORDER BY created_at, id
        """,
        (submission_id,),
    )
    item["files"] = [dict(file_row) for file_row in cursor.fetchall()]
    cursor.execute(
        """
        SELECT *
        FROM form_review_tasks
        WHERE submission_id = ?
        ORDER BY stage_index, task_order, id
        """,
        (submission_id,),
    )
    item["tasks"] = [dict(task_row) for task_row in cursor.fetchall()]
    cursor.execute(
        """
        SELECT *
        FROM form_submission_comments
        WHERE submission_id = ?
        ORDER BY datetime(created_at), id
        """,
        (submission_id,),
    )
    item["comments"] = [dict(comment_row) for comment_row in cursor.fetchall()]
    cursor.execute(
        """
        SELECT *
        FROM form_audit_log
        WHERE entity_type = 'submission' AND entity_id = ?
        ORDER BY datetime(created_at) DESC, id DESC
        """,
        (submission_id,),
    )
    item["audit_entries"] = [dict(entry) for entry in cursor.fetchall()]
    identity_usernames = [item.get("owner_username"), item.get("requester_username")]
    for task in item["tasks"]:
        if task.get("acted_by_username"):
            identity_usernames.append(task["acted_by_username"])
    for comment in item["comments"]:
        if comment.get("author_username"):
            identity_usernames.append(comment["author_username"])
    for entry in item["audit_entries"]:
        if entry.get("actor_username"):
            identity_usernames.append(entry["actor_username"])
    identity_map = get_profile_identity_map(connection, identity_usernames, viewer_username=item.get("owner_username") or "")
    owner_identity = identity_map.get((item.get("owner_username") or "").casefold())
    requester_identity = identity_map.get((item.get("requester_username") or "").casefold())
    item["owner_display_name"] = (owner_identity.get("display_name") if owner_identity else "") or item.get("owner_username")
    item["owner_profile_url"] = (owner_identity.get("profile_url") if owner_identity else f"/users/{item.get('owner_username')}")
    item["requester_display_name"] = (requester_identity.get("display_name") if requester_identity else "") or item.get("requester_username")
    item["requester_profile_url"] = (requester_identity.get("profile_url") if requester_identity else f"/users/{item.get('requester_username')}")
    for task in item["tasks"]:
        actor_identity = identity_map.get((task.get("acted_by_username") or "").casefold())
        task["acted_by_display_name"] = (
            (actor_identity.get("display_name") if actor_identity else "")
            or task.get("acted_by_username")
            or ""
        )
    for comment in item["comments"]:
        author_identity = identity_map.get((comment.get("author_username") or "").casefold())
        comment["author_display_name"] = (
            (author_identity.get("display_name") if author_identity else "")
            or comment.get("author_fullname_snapshot")
            or comment.get("author_username")
        )
        comment["author_profile_url"] = (
            (author_identity.get("profile_url") if author_identity else "")
            or f"/users/{comment.get('author_username')}"
        )
        comment["author_avatar_url"] = (author_identity.get("avatar_url") if author_identity else "") or ""
        comment["author_avatar_initials"] = (
            (author_identity.get("avatar_initials") if author_identity else "")
            or get_initials(_resolve_fullname(connection, comment.get("author_username")), "U")
        )
    for entry in item["audit_entries"]:
        actor_identity = identity_map.get((entry.get("actor_username") or "").casefold())
        entry["actor_display_name"] = (
            (actor_identity.get("display_name") if actor_identity else "")
            or entry.get("actor_fullname_snapshot")
            or entry.get("actor_username")
            or "System"
        )
    return item


def _submission_is_visible(form, submission, username, role_names):
    username_key = (username or "").casefold()
    role_keys = {role.casefold() for role in (role_names or [])}
    if username_key in {
        (submission.get("owner_username") or "").casefold(),
        (submission.get("requester_username") or "").casefold(),
        (form.get("created_by_username") or "").casefold(),
    }:
        return True
    if {"developer", "superadmin"} & role_keys:
        return True
    for task in submission.get("tasks") or []:
        reviewer_type = (task.get("reviewer_type") or "").casefold()
        reviewer_value = (task.get("reviewer_value") or "").casefold()
        if reviewer_type == "user" and reviewer_value == username_key:
            return True
        if reviewer_type == "role" and reviewer_value in role_keys:
            return True
    return False


def _submission_can_edit(submission, username):
    return (
        (submission.get("owner_username") or "").casefold() == (username or "").casefold()
        and submission.get("status") == "draft"
    )


def _submission_can_comment(form, submission, username, role_names):
    username_key = (username or "").casefold()
    role_keys = {role.casefold() for role in (role_names or [])}
    if username_key in {
        (submission.get("owner_username") or "").casefold(),
        (submission.get("requester_username") or "").casefold(),
        (form.get("created_by_username") or "").casefold(),
    }:
        return True
    if {"developer", "superadmin"} & role_keys:
        return True

    matched_future_task = False
    for task in submission.get("tasks") or []:
        reviewer_type = (task.get("reviewer_type") or "").casefold()
        reviewer_value = (task.get("reviewer_value") or "").casefold()
        task_matches = (
            (reviewer_type == "user" and reviewer_value == username_key)
            or (reviewer_type == "role" and reviewer_value in role_keys)
        )
        if not task_matches:
            continue
        if task.get("is_active") or task.get("task_status") in {"approved", "rejected"}:
            return True
        matched_future_task = True

    if matched_future_task:
        return False
    return False


def _ensure_submission_access(connection, submission_id, username, role_names):
    submission = _get_submission(connection, submission_id)
    if not submission:
        return None, None, "Submission not found."
    cursor = connection.cursor()
    cursor.execute("SELECT * FROM forms WHERE id = ?", (submission["form_id"],))
    form_row = cursor.fetchone()
    if not form_row:
        return None, None, "Form not found."
    form = _form_row_to_dict(connection, form_row)
    if not _submission_is_visible(form, submission, username, role_names):
        return None, None, "You do not have access to this submission."
    return form, submission, ""


def _evaluate_single_rule(rule, values):
    field_key = _field_key(rule.get("field"))
    operator = str(rule.get("op") or "").strip().lower()
    expected = rule.get("value")
    actual = values.get(field_key)
    if isinstance(actual, list):
        actual_text = ",".join(str(item) for item in actual)
    else:
        actual_text = "" if actual is None else str(actual)
    if operator == "equals":
        return actual == expected or actual_text == str(expected)
    if operator == "not_equals":
        return not _evaluate_single_rule({"field": field_key, "op": "equals", "value": expected}, values)
    if operator == "contains":
        return str(expected or "") in actual_text
    if operator == "greater_than":
        try:
            return float(actual or 0) > float(expected)
        except (TypeError, ValueError):
            return False
    if operator == "less_than":
        try:
            return float(actual or 0) < float(expected)
        except (TypeError, ValueError):
            return False
    if operator == "is_empty":
        if isinstance(actual, list):
            return len(actual) == 0
        return actual in (None, "", False)
    return False


def evaluate_condition_group(group, values):
    if not group or not isinstance(group, dict):
        return True
    rules = group.get("rules") or []
    logic = str(group.get("logic") or "all").strip().lower()
    if not rules:
        return True
    results = []
    for rule in rules:
        if isinstance(rule, dict) and "rules" in rule:
            results.append(evaluate_condition_group(rule, values))
        elif isinstance(rule, dict):
            results.append(_evaluate_single_rule(rule, values))
    if not results:
        return True
    return all(results) if logic != "any" else any(results)


def _visible_fields(schema, values):
    visible = []
    for field in schema or []:
        if evaluate_condition_group(field.get("conditional_logic"), values):
            visible.append(field)
    return visible


def _coerce_value(field, raw_value):
    field_type = field.get("type")
    if field_type == "checkbox":
        return bool(raw_value) and str(raw_value).strip().lower() not in {"0", "false", ""}
    if field_type == "number":
        return str(raw_value or "").strip()
    return str(raw_value or "").strip()


def _extract_field_values(schema, form_data):
    values = {}
    for field in schema or []:
        input_name = f"field__{field['key']}"
        values[field["key"]] = _coerce_value(field, form_data.get(input_name))
    return values


def _submission_file_groups(files):
    groups = {}
    for item in files or []:
        groups.setdefault(item["field_key"], []).append(item)
    return groups


def _validate_visible_fields(schema, values, files_by_field):
    errors = []
    visible_fields = _visible_fields(schema, values)
    for field in visible_fields:
        field_key = field["key"]
        field_type = field["type"]
        value = values.get(field_key)
        validation = field.get("validation") or {}
        if field.get("required"):
            if field_type in {"image_upload", "file_upload"}:
                if not files_by_field.get(field_key):
                    errors.append(f"{field['label']} is required.")
            elif field_type == "checkbox":
                if not value:
                    errors.append(f"{field['label']} is required.")
            elif value in (None, ""):
                errors.append(f"{field['label']} is required.")
        if value not in (None, "") and field_type == "number":
            try:
                numeric_value = float(value)
            except (TypeError, ValueError):
                errors.append(f"{field['label']} must be a number.")
                continue
            min_value = validation.get("min")
            max_value = validation.get("max")
            try:
                if min_value not in (None, "") and numeric_value < float(min_value):
                    errors.append(f"{field['label']} must be at least {min_value}.")
            except (TypeError, ValueError):
                pass
            try:
                if max_value not in (None, "") and numeric_value > float(max_value):
                    errors.append(f"{field['label']} must be at most {max_value}.")
            except (TypeError, ValueError):
                pass
        if field_type in {"short_text", "long_text"} and value not in (None, ""):
            min_length = validation.get("min_length")
            max_length = validation.get("max_length")
            try:
                if min_length not in (None, "") and len(value) < int(min_length):
                    errors.append(f"{field['label']} must be at least {min_length} characters.")
            except (TypeError, ValueError):
                pass
            try:
                if max_length not in (None, "") and len(value) > int(max_length):
                    errors.append(f"{field['label']} must be at most {max_length} characters.")
            except (TypeError, ValueError):
                pass
        if field_type == "dropdown" and value not in (None, ""):
            options = field.get("options") or []
            if options and value not in options:
                errors.append(f"{field['label']} contains an unsupported option.")
    return errors


def _save_submission_file(upload, field_key, field_type, username):
    if not upload or not upload.filename:
        return False, "Missing upload.", None
    ensure_form_workflow_folders()
    filename = secure_filename(upload.filename)
    ext = os.path.splitext(filename)[1].lower()
    allowed_exts = ALLOWED_FORM_IMAGE_EXTENSIONS if field_type == "image_upload" else ALLOWED_FORM_DOCUMENT_EXTENSIONS
    if ext not in allowed_exts:
        return False, "Unsupported file type.", None
    try:
        upload.stream.seek(0, os.SEEK_END)
        file_size = upload.stream.tell()
        upload.stream.seek(0)
    except (AttributeError, OSError):
        file_size = 0
    if file_size > MAX_FORM_FILE_SIZE_BYTES:
        return False, "Each attachment must be 50 MB or smaller.", None
    stem = os.path.splitext(filename)[0] or "submission-file"
    candidate = filename
    suffix = 2
    while os.path.exists(os.path.join(FORM_FILE_DIR, candidate)):
        candidate = f"{stem}-{suffix}{ext}"
        suffix += 1
    upload.save(os.path.join(FORM_FILE_DIR, candidate))
    return True, "", {
        "field_key": field_key,
        "original_name": filename,
        "stored_name": candidate,
        "file_ext": ext,
        "mime_type": upload.mimetype,
        "file_size_bytes": file_size,
        "file_kind": "image" if field_type == "image_upload" else "document",
        "uploaded_by_username": username,
    }


def get_form_home_context(form_key, username, role_names):
    connection = connect_db()
    form = _get_form_by_key(connection, form_key)
    if not form:
        connection.close()
        return False, "Form not found.", None
    if form["status"] != "published" or not _user_matches_form_access(form, username, role_names):
        connection.close()
        return False, "You do not have access to this form.", None
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT id, tracking_number, status, submitted_at, updated_at, created_at
        FROM form_submissions
        WHERE form_id = ?
          AND (owner_username = ? OR requester_username = ?)
        ORDER BY datetime(updated_at) DESC, id DESC
        """,
        (form["id"], username, username),
    )
    submissions = [dict(row) for row in cursor.fetchall()]
    connection.close()
    return True, "", {"form": form, "submissions": submissions}


def start_form_draft(form_key, username, role_names):
    connection = connect_db()
    form = _get_form_by_key(connection, form_key)
    if not form:
        connection.close()
        return False, "Form not found.", None
    if form["status"] != "published" or not _user_matches_form_access(form, username, role_names):
        connection.close()
        return False, "You do not have access to this form.", None

    if not form["allow_multiple_active"]:
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT id
            FROM form_submissions
            WHERE form_id = ?
              AND owner_username = ?
              AND status IN ('draft', 'pending')
            ORDER BY id DESC
            LIMIT 1
            """,
            (form["id"], username),
        )
        existing = cursor.fetchone()
        if existing:
            connection.close()
            return True, "Existing submission opened.", existing["id"]

    now = timestamp_now()
    cursor = connection.cursor()
    cursor.execute(
        """
        INSERT INTO form_submissions (
            form_id,
            form_version_id,
            owner_username,
            requester_username,
            status,
            data_json,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, 'draft', '{}', ?, ?)
        """,
        (form["id"], form["current_version_id"], username, username, now, now),
    )
    submission_id = cursor.lastrowid
    _audit(connection, "submission.draft-created", username, "submission", submission_id, payload={"form_key": form["form_key"]})
    connection.commit()
    connection.close()
    return True, "Draft created.", submission_id


def get_submission_editor_context(submission_id, username, role_names):
    connection = connect_db()
    form, submission, message = _ensure_submission_access(connection, submission_id, username, role_names)
    if not form:
        connection.close()
        return False, message, None
    if not _submission_can_edit(submission, username):
        connection.close()
        return False, "This submission is no longer editable.", None
    schema = form.get("schema") or []
    data = submission.get("data") or {}
    payload = {
        "form": form,
        "submission": submission,
        "schema": schema,
        "visible_fields": _visible_fields(schema, data),
        "file_groups": _submission_file_groups(submission.get("files")),
    }
    connection.close()
    return True, "", payload


def save_submission_draft(submission_id, username, role_names, form_data, form_files, remove_file_ids=None, autosave=False):
    connection = connect_db()
    form, submission, message = _ensure_submission_access(connection, submission_id, username, role_names)
    if not form:
        connection.close()
        return False, message, None
    if not _submission_can_edit(submission, username):
        connection.close()
        return False, "This submission is no longer editable.", None
    schema = form.get("schema") or []
    values = submission.get("data") or {}
    values.update(_extract_field_values(schema, form_data))

    remove_ids = {int(item) for item in (remove_file_ids or []) if str(item).isdigit()}
    if remove_ids:
        cursor = connection.cursor()
        placeholders = ", ".join("?" for _ in remove_ids)
        cursor.execute(
            f"""
            SELECT id, stored_name
            FROM form_submission_files
            WHERE submission_id = ? AND id IN ({placeholders})
            """,
            (submission_id, *sorted(remove_ids)),
        )
        for row in cursor.fetchall():
            path = os.path.join(FORM_FILE_DIR, row["stored_name"])
            if os.path.exists(path):
                os.remove(path)
        cursor.execute(
            f"""
            DELETE FROM form_submission_files
            WHERE submission_id = ? AND id IN ({placeholders})
            """,
            (submission_id, *sorted(remove_ids)),
        )

    remaining_files = [item for item in submission.get("files") or [] if item.get("id") not in remove_ids]
    images_total = len([item for item in remaining_files if item.get("file_kind") == "image"])
    docs_total = len([item for item in remaining_files if item.get("file_kind") == "document"])
    added_files = []

    for field in schema:
        field_key = field["key"]
        input_name = f"field_file__{field_key}"
        uploads = form_files.getlist(input_name) if hasattr(form_files, "getlist") else []
        if not uploads:
            continue
        for upload in uploads:
            ok, error_message, meta = _save_submission_file(upload, field_key, field["type"], username)
            if not ok:
                for item in added_files:
                    cleanup = os.path.join(FORM_FILE_DIR, item["stored_name"])
                    if os.path.exists(cleanup):
                        os.remove(cleanup)
                connection.rollback()
                connection.close()
                return False, error_message, None
            if meta["file_kind"] == "image":
                images_total += 1
                if images_total > MAX_FORM_IMAGE_COUNT:
                    cleanup = os.path.join(FORM_FILE_DIR, meta["stored_name"])
                    if os.path.exists(cleanup):
                        os.remove(cleanup)
                    for item in added_files:
                        added_path = os.path.join(FORM_FILE_DIR, item["stored_name"])
                        if os.path.exists(added_path):
                            os.remove(added_path)
                    connection.rollback()
                    connection.close()
                    return False, "A submission can contain at most 5 images.", None
            else:
                docs_total += 1
                if docs_total > MAX_FORM_DOCUMENT_COUNT:
                    cleanup = os.path.join(FORM_FILE_DIR, meta["stored_name"])
                    if os.path.exists(cleanup):
                        os.remove(cleanup)
                    for item in added_files:
                        added_path = os.path.join(FORM_FILE_DIR, item["stored_name"])
                        if os.path.exists(added_path):
                            os.remove(added_path)
                    connection.rollback()
                    connection.close()
                    return False, "A submission can contain at most 20 document attachments.", None
            added_files.append(meta)
            connection.execute(
                """
                INSERT INTO form_submission_files (
                    submission_id,
                    field_key,
                    original_name,
                    stored_name,
                    file_ext,
                    mime_type,
                    file_size_bytes,
                    file_kind,
                    uploaded_by_username,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    submission_id,
                    meta["field_key"],
                    meta["original_name"],
                    meta["stored_name"],
                    meta["file_ext"],
                    meta["mime_type"],
                    meta["file_size_bytes"],
                    meta["file_kind"],
                    meta["uploaded_by_username"],
                    timestamp_now(),
                ),
            )

    connection.execute(
        """
        UPDATE form_submissions
        SET data_json = ?, updated_at = ?
        WHERE id = ?
        """,
        (_json_dumps(values), timestamp_now(), submission_id),
    )
    if not autosave:
        _audit(connection, "submission.draft-saved", username, "submission", submission_id, payload={"fields": sorted(values.keys())})
    connection.commit()
    payload = _get_submission(connection, submission_id)
    connection.close()
    return True, "Draft saved." if not autosave else "Autosaved.", payload


def _allocate_tracking_number(connection, prefix):
    cursor = connection.cursor()
    cursor.execute("SELECT next_number FROM form_tracking_sequence WHERE id = 1")
    row = cursor.fetchone()
    next_number = int(row["next_number"]) if row else 1
    cursor.execute("UPDATE form_tracking_sequence SET next_number = ? WHERE id = 1", (next_number + 1,))
    return f"{prefix}-{next_number:06d}"


def _create_stage_tasks(connection, submission_id, stages, stage_index):
    if stage_index >= len(stages):
        return
    stage = stages[stage_index]
    now = timestamp_now()
    if stage["mode"] == "parallel":
        for order, reviewer in enumerate(stage["reviewers"], start=1):
            connection.execute(
                """
                INSERT INTO form_review_tasks (
                    submission_id,
                    stage_index,
                    task_order,
                    reviewer_type,
                    reviewer_value,
                    is_active,
                    task_status,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, 1, 'pending', ?)
                """,
                (submission_id, stage_index, order, reviewer["type"], reviewer["value"], now),
            )
    else:
        for order, reviewer in enumerate(stage["reviewers"], start=1):
            connection.execute(
                """
                INSERT INTO form_review_tasks (
                    submission_id,
                    stage_index,
                    task_order,
                    reviewer_type,
                    reviewer_value,
                    is_active,
                    task_status,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
                """,
                (
                    submission_id,
                    stage_index,
                    order,
                    reviewer["type"],
                    reviewer["value"],
                    1 if order == 1 else 0,
                    now,
                ),
            )


def _notify_stage_reviewers(connection, form, submission_id, stages, stage_index):
    if stage_index >= len(stages):
        return
    stage = stages[stage_index]
    usernames = []
    for reviewer in stage["reviewers"]:
        if reviewer["type"] == "user":
            usernames.append(reviewer["value"])
        elif reviewer["type"] == "role":
            usernames.extend(_role_members(connection, reviewer["value"]))
    if not usernames:
        return
    _notify_users(
        connection,
        sorted({item for item in usernames if item}),
        f"Review required: {form['title']}",
        f"A submission is waiting in {stage['name']}.",
        link_url=f"/forms/submissions/{submission_id}",
        style_key="warning",
    )


def submit_submission(submission_id, username, role_names, form_data, form_files, remove_file_ids=None):
    ok, message, _payload = save_submission_draft(
        submission_id,
        username,
        role_names,
        form_data,
        form_files,
        remove_file_ids=remove_file_ids,
        autosave=False,
    )
    if not ok:
        return False, message, None

    connection = connect_db()
    form, submission, access_message = _ensure_submission_access(connection, submission_id, username, role_names)
    if not form:
        connection.close()
        return False, access_message, None
    schema = form.get("schema") or []
    files_by_field = _submission_file_groups(submission.get("files"))
    values = submission.get("data") or {}
    errors = _validate_visible_fields(schema, values, files_by_field)
    if errors:
        connection.close()
        return False, errors[0], None

    stages = form.get("review_stages") or []
    if not stages:
        connection.close()
        return False, "This form has no review workflow configured.", None

    tracking_number = submission.get("tracking_number") or _allocate_tracking_number(connection, form["tracking_prefix"])
    now = timestamp_now()
    connection.execute("DELETE FROM form_review_tasks WHERE submission_id = ?", (submission_id,))
    _create_stage_tasks(connection, submission_id, stages, 0)
    connection.execute(
        """
        UPDATE form_submissions
        SET
            tracking_number = ?,
            tracking_prefix = ?,
            status = 'pending',
            submitted_at = COALESCE(submitted_at, ?),
            updated_at = ?,
            current_stage_index = 0,
            current_task_order = 1,
            cancel_reason = NULL,
            reject_reason = NULL,
            acceptance_note = NULL
        WHERE id = ?
        """,
        (tracking_number, form["tracking_prefix"], now, now, submission_id),
    )
    _notify_stage_reviewers(connection, form, submission_id, stages, 0)
    _notify_users(
        connection,
        [submission["owner_username"]],
        f"Submitted: {form['title']}",
        f"Tracking number {tracking_number} is now pending review.",
        link_url=f"/forms/submissions/{submission_id}",
        style_key="success",
    )
    _audit(connection, "submission.submitted", username, "submission", submission_id, tracking_number=tracking_number)
    connection.commit()
    updated = _get_submission(connection, submission_id)
    connection.close()
    return True, "Submission sent for review.", updated


def get_my_requests(username, role_names, form_filter=""):
    connection = connect_db()
    cursor = connection.cursor()
    params = [username, username]
    filter_clause = ""
    if form_filter:
        filter_clause = "AND lower(f.form_key) = lower(?)"
        params.append(form_filter)
    cursor.execute(
        f"""
        SELECT
            s.*,
            f.title AS form_title,
            f.form_key,
            f.status AS form_status
        FROM form_submissions s
        INNER JOIN forms f ON f.id = s.form_id
        WHERE (s.owner_username = ? OR s.requester_username = ?)
          AND s.status != 'archived'
          {filter_clause}
        ORDER BY
            CASE s.status
                WHEN 'pending' THEN 0
                WHEN 'draft' THEN 1
                WHEN 'rejected' THEN 2
                WHEN 'cancelled' THEN 3
                WHEN 'completed' THEN 4
                ELSE 5
            END,
            datetime(s.updated_at) DESC,
            s.id DESC
        """,
        tuple(params),
    )
    items = []
    identity_map = {}
    fetched_rows = [dict(row) for row in cursor.fetchall()]
    if fetched_rows:
        identity_map = get_profile_identity_map(
            connection,
            [item["owner_username"] for item in fetched_rows] + [item["requester_username"] for item in fetched_rows],
            viewer_username=username,
        )
    for item in fetched_rows:
        item["can_reopen"] = item["status"] in {"rejected", "cancelled"}
        item["is_editable"] = item["status"] == "draft"
        owner_identity = identity_map.get((item.get("owner_username") or "").casefold())
        requester_identity = identity_map.get((item.get("requester_username") or "").casefold())
        item["owner_display_name"] = (owner_identity.get("display_name") if owner_identity else "") or item.get("owner_username")
        item["requester_display_name"] = (requester_identity.get("display_name") if requester_identity else "") or item.get("requester_username")
        items.append(item)
    connection.close()
    return items


def get_review_queue(username, role_names):
    connection = connect_db()
    cursor = connection.cursor()
    role_keys = [role.casefold() for role in (role_names or [])]
    if role_keys:
        placeholders = ", ".join("?" for _ in role_keys)
        cursor.execute(
            f"""
            SELECT
                t.*,
                s.status AS submission_status,
                s.tracking_number,
                s.owner_username,
                s.requester_username,
                s.updated_at,
                f.title AS form_title,
                f.form_key
            FROM form_review_tasks t
            INNER JOIN form_submissions s ON s.id = t.submission_id
            INNER JOIN forms f ON f.id = s.form_id
            WHERE s.status = 'pending'
              AND t.task_status = 'pending'
              AND (
                    (t.reviewer_type = 'user' AND lower(t.reviewer_value) = lower(?))
                    OR (t.reviewer_type = 'role' AND lower(t.reviewer_value) IN ({placeholders}))
              )
            ORDER BY t.is_active DESC, t.stage_index ASC, t.task_order ASC, datetime(s.updated_at) DESC
            """,
            (username, *role_keys),
        )
    else:
        cursor.execute(
            """
            SELECT
                t.*,
                s.status AS submission_status,
                s.tracking_number,
                s.owner_username,
                s.requester_username,
                s.updated_at,
                f.title AS form_title,
                f.form_key
            FROM form_review_tasks t
            INNER JOIN form_submissions s ON s.id = t.submission_id
            INNER JOIN forms f ON f.id = s.form_id
            WHERE s.status = 'pending'
              AND t.task_status = 'pending'
              AND t.reviewer_type = 'user'
              AND lower(t.reviewer_value) = lower(?)
            ORDER BY t.is_active DESC, t.stage_index ASC, t.task_order ASC, datetime(s.updated_at) DESC
            """,
            (username,),
        )
    items = [dict(row) for row in cursor.fetchall()]
    identity_map = get_profile_identity_map(
        connection,
        [item["owner_username"] for item in items] + [item["requester_username"] for item in items],
        viewer_username=username,
    )
    for item in items:
        item["is_actionable"] = bool(item.get("is_active")) and item.get("task_status") == "pending"
        owner_identity = identity_map.get((item.get("owner_username") or "").casefold())
        requester_identity = identity_map.get((item.get("requester_username") or "").casefold())
        item["owner_display_name"] = (owner_identity.get("display_name") if owner_identity else "") or item.get("owner_username")
        item["requester_display_name"] = (requester_identity.get("display_name") if requester_identity else "") or item.get("requester_username")
        item["owner_profile_url"] = (owner_identity.get("profile_url") if owner_identity else "") or f"/users/{item.get('owner_username')}"
    connection.close()
    return items


def get_submission_detail_context(submission_id, username, role_names):
    connection = connect_db()
    form, submission, message = _ensure_submission_access(connection, submission_id, username, role_names)
    if not form:
        connection.close()
        return False, message, None
    schema = form.get("schema") or []
    file_groups = _submission_file_groups(submission.get("files"))
    active_task_ids = set()
    actionable_task_ids = set()
    username_key = (username or "").casefold()
    role_keys = {role.casefold() for role in (role_names or [])}
    for task in submission.get("tasks") or []:
        if task.get("is_active"):
            active_task_ids.add(task["id"])
            reviewer_type = (task.get("reviewer_type") or "").casefold()
            reviewer_value = (task.get("reviewer_value") or "").casefold()
            if task.get("task_status") == "pending":
                if reviewer_type == "user" and reviewer_value == username_key:
                    actionable_task_ids.add(task["id"])
                elif reviewer_type == "role" and reviewer_value in role_keys:
                    actionable_task_ids.add(task["id"])
    payload = {
        "form": form,
        "submission": submission,
        "schema": schema,
        "visible_fields": _visible_fields(schema, submission.get("data") or {}),
        "file_groups": file_groups,
        "active_task_ids": active_task_ids,
        "actionable_task_ids": actionable_task_ids,
        "can_cancel": (
            (submission.get("owner_username") or "").casefold() == username_key
            and submission.get("status") == "pending"
            and form.get("allow_cancel")
            and not any(task.get("task_status") in {"approved", "rejected"} for task in submission.get("tasks") or [])
        ),
        "can_reopen": (
            (submission.get("owner_username") or "").casefold() == username_key
            and submission.get("status") in {"rejected", "cancelled"}
        ),
        "can_delete_draft": (
            (submission.get("owner_username") or "").casefold() == username_key
            and submission.get("status") == "draft"
        ),
        "can_edit": _submission_can_edit(submission, username),
        "can_comment": _submission_can_comment(form, submission, username, role_names),
    }
    connection.close()
    return True, "", payload


def add_submission_comment(submission_id, username, fullname, role_names, body):
    body = str(body or "").strip()
    if not body:
        return False, "Comment cannot be empty."
    connection = connect_db()
    form, submission, message = _ensure_submission_access(connection, submission_id, username, role_names)
    if not form:
        connection.close()
        return False, message
    if not _submission_can_comment(form, submission, username, role_names):
        connection.close()
        return False, "Comments are read-only until your review stage is active."
    connection.execute(
        """
        INSERT INTO form_submission_comments (
            submission_id,
            author_username,
            author_fullname_snapshot,
            body,
            created_at
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (submission_id, username, (fullname or "").strip() or username, body, timestamp_now()),
    )
    _audit(connection, "submission.comment-added", username, "submission", submission_id, tracking_number=submission.get("tracking_number"), payload={"body": body})
    connection.commit()
    connection.close()
    return True, "Comment added."


def cancel_submission(submission_id, username, role_names, reason):
    reason = str(reason or "").strip()
    if not reason:
        return False, "Cancellation reason is required."
    connection = connect_db()
    form, submission, message = _ensure_submission_access(connection, submission_id, username, role_names)
    if not form:
        connection.close()
        return False, message
    if not form.get("allow_cancel"):
        connection.close()
        return False, "This form cannot be cancelled."
    if (submission.get("owner_username") or "").casefold() != (username or "").casefold():
        connection.close()
        return False, "Only the requester can cancel this submission."
    if submission.get("status") != "pending":
        connection.close()
        return False, "Only pending submissions can be cancelled."
    if any(task.get("task_status") in {"approved", "rejected"} for task in submission.get("tasks") or []):
        connection.close()
        return False, "This submission can no longer be cancelled."
    connection.execute(
        """
        UPDATE form_submissions
        SET status = 'cancelled', cancel_reason = ?, updated_at = ?
        WHERE id = ?
        """,
        (reason, timestamp_now(), submission_id),
    )
    connection.execute(
        """
        UPDATE form_review_tasks
        SET is_active = 0
        WHERE submission_id = ?
        """,
        (submission_id,),
    )
    _audit(connection, "submission.cancelled", username, "submission", submission_id, tracking_number=submission.get("tracking_number"), payload={"reason": reason})
    _notify_users(
        connection,
        [submission["owner_username"]],
        f"Cancelled: {form['title']}",
        f"Submission {submission.get('tracking_number') or ('Draft #' + str(submission_id))} was cancelled.",
        link_url=f"/forms/submissions/{submission_id}",
        style_key="warning",
    )
    connection.commit()
    connection.close()
    return True, "Submission cancelled."


def reopen_submission(submission_id, username, role_names):
    connection = connect_db()
    form, submission, message = _ensure_submission_access(connection, submission_id, username, role_names)
    if not form:
        connection.close()
        return False, message
    if (submission.get("owner_username") or "").casefold() != (username or "").casefold():
        connection.close()
        return False, "Only the requester can reopen this submission."
    if submission.get("status") not in {"rejected", "cancelled"}:
        connection.close()
        return False, "Only rejected or cancelled submissions can be reopened."
    connection.execute("DELETE FROM form_review_tasks WHERE submission_id = ?", (submission_id,))
    connection.execute(
        """
        UPDATE form_submissions
        SET
            status = 'draft',
            cancel_reason = NULL,
            reject_reason = NULL,
            acceptance_note = NULL,
            current_stage_index = 0,
            current_task_order = 0,
            updated_at = ?
        WHERE id = ?
        """,
        (timestamp_now(), submission_id),
    )
    _audit(connection, "submission.reopened", username, "submission", submission_id, tracking_number=submission.get("tracking_number"))
    connection.commit()
    connection.close()
    return True, "Submission reopened as draft."


def delete_draft_submission(submission_id, username, role_names):
    connection = connect_db()
    form, submission, message = _ensure_submission_access(connection, submission_id, username, role_names)
    if not form:
        connection.close()
        return False, message
    if not _submission_can_edit(submission, username):
        connection.close()
        return False, "Only drafts can be deleted."
    for file_row in submission.get("files") or []:
        path = os.path.join(FORM_FILE_DIR, file_row["stored_name"])
        if os.path.exists(path):
            os.remove(path)
    _audit(connection, "submission.draft-deleted", username, "submission", submission_id)
    connection.execute("DELETE FROM form_submission_files WHERE submission_id = ?", (submission_id,))
    connection.execute("DELETE FROM form_submission_comments WHERE submission_id = ?", (submission_id,))
    connection.execute("DELETE FROM form_audit_log WHERE entity_type = 'submission' AND entity_id = ?", (submission_id,))
    connection.execute("DELETE FROM form_submissions WHERE id = ?", (submission_id,))
    connection.commit()
    connection.close()
    return True, "Draft deleted."


def review_submission_action(submission_id, task_id, username, fullname, role_names, action, note):
    action = str(action or "").strip().lower()
    note = str(note or "").strip()
    if action not in {"approve", "reject"}:
        return False, "Unsupported review action."
    if action == "reject" and not note:
        return False, "Rejection reason is required."

    connection = connect_db()
    form, submission, message = _ensure_submission_access(connection, submission_id, username, role_names)
    if not form:
        connection.close()
        return False, message

    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT *
        FROM form_review_tasks
        WHERE id = ? AND submission_id = ?
        """,
        (task_id, submission_id),
    )
    task = cursor.fetchone()
    if not task:
        connection.close()
        return False, "Review task not found."
    task = dict(task)
    if not task.get("is_active") or task.get("task_status") != "pending":
        connection.close()
        return False, "This review step is not currently actionable."

    username_key = (username or "").casefold()
    role_keys = {role.casefold() for role in (role_names or [])}
    reviewer_type = (task.get("reviewer_type") or "").casefold()
    reviewer_value = (task.get("reviewer_value") or "").casefold()
    if reviewer_type == "user":
        allowed = reviewer_value == username_key
    else:
        allowed = reviewer_value in role_keys
    if not allowed:
        connection.close()
        return False, "You are not assigned to this review step."

    acted_at = timestamp_now()
    connection.execute(
        """
        UPDATE form_review_tasks
        SET task_status = ?, acted_at = ?, acted_by_username = ?, action_note = ?, is_active = 0
        WHERE id = ?
        """,
        ("approved" if action == "approve" else "rejected", acted_at, username, note or None, task_id),
    )
    if note:
        connection.execute(
            """
            INSERT INTO form_submission_comments (
                submission_id,
                author_username,
                author_fullname_snapshot,
                body,
                created_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (submission_id, username, (fullname or "").strip() or username, note, acted_at),
        )

    stages = form.get("review_stages") or []
    stage_index = int(task["stage_index"])
    stage = stages[stage_index] if 0 <= stage_index < len(stages) else {"mode": "parallel", "reviewers": []}

    if action == "reject":
        connection.execute(
            """
            UPDATE form_submissions
            SET status = 'rejected', reject_reason = ?, updated_at = ?
            WHERE id = ?
            """,
            (note, acted_at, submission_id),
        )
        connection.execute(
            """
            UPDATE form_review_tasks
            SET is_active = 0
            WHERE submission_id = ?
            """,
            (submission_id,),
        )
        _audit(connection, "submission.rejected", username, "submission", submission_id, tracking_number=submission.get("tracking_number"), payload={"reason": note})
        _notify_users(
            connection,
            [submission["owner_username"]],
            f"Rejected: {form['title']}",
            f"{submission.get('tracking_number') or ('Submission #' + str(submission_id))} was rejected.",
            link_url=f"/forms/submissions/{submission_id}",
            style_key="warning",
            sender_name=(fullname or "").strip() or username,
        )
        connection.commit()
        connection.close()
        return True, "Submission rejected."

    cursor.execute(
        """
        SELECT *
        FROM form_review_tasks
        WHERE submission_id = ? AND stage_index = ?
        ORDER BY task_order, id
        """,
        (submission_id, stage_index),
    )
    stage_tasks = [dict(row) for row in cursor.fetchall()]

    if stage["mode"] == "parallel":
        if all(item["task_status"] == "approved" for item in stage_tasks):
            next_stage_index = stage_index + 1
            if next_stage_index >= len(stages):
                connection.execute(
                    """
                    UPDATE form_submissions
                    SET status = 'completed', completed_at = ?, updated_at = ?, acceptance_note = ?
                    WHERE id = ?
                    """,
                    (acted_at, acted_at, note or None, submission_id),
                )
                _audit(connection, "submission.completed", username, "submission", submission_id, tracking_number=submission.get("tracking_number"))
                _notify_users(
                    connection,
                    [submission["owner_username"]],
                    f"Completed: {form['title']}",
                    f"{submission.get('tracking_number') or ('Submission #' + str(submission_id))} was completed.",
                    link_url=f"/forms/submissions/{submission_id}",
                    style_key="success",
                    sender_name=(fullname or "").strip() or username,
                )
            else:
                _create_stage_tasks(connection, submission_id, stages, next_stage_index)
                connection.execute(
                    """
                    UPDATE form_submissions
                    SET current_stage_index = ?, current_task_order = 1, updated_at = ?
                    WHERE id = ?
                    """,
                    (next_stage_index, acted_at, submission_id),
                )
                _notify_stage_reviewers(connection, form, submission_id, stages, next_stage_index)
        _audit(connection, "submission.approved-step", username, "submission", submission_id, tracking_number=submission.get("tracking_number"), payload={"stage_index": stage_index})
        connection.commit()
        connection.close()
        return True, "Review recorded."

    next_pending = None
    for item in stage_tasks:
        if item["task_status"] == "pending":
            next_pending = item
            break
    if next_pending:
        connection.execute(
            """
            UPDATE form_review_tasks
            SET is_active = 1
            WHERE id = ?
            """,
            (next_pending["id"],),
        )
        connection.execute(
            """
            UPDATE form_submissions
            SET current_stage_index = ?, current_task_order = ?, updated_at = ?
            WHERE id = ?
            """,
            (stage_index, next_pending["task_order"], acted_at, submission_id),
        )
        if next_pending["reviewer_type"] == "user":
            notify_targets = [next_pending["reviewer_value"]]
        else:
            notify_targets = _role_members(connection, next_pending["reviewer_value"])
        _notify_users(
            connection,
            notify_targets,
            f"Review required: {form['title']}",
            f"{submission.get('tracking_number') or ('Submission #' + str(submission_id))} is waiting for your action.",
            link_url=f"/forms/submissions/{submission_id}",
            style_key="warning",
        )
    else:
        next_stage_index = stage_index + 1
        if next_stage_index >= len(stages):
            connection.execute(
                """
                UPDATE form_submissions
                SET status = 'completed', completed_at = ?, updated_at = ?, acceptance_note = ?
                WHERE id = ?
                """,
                (acted_at, acted_at, note or None, submission_id),
            )
            _notify_users(
                connection,
                [submission["owner_username"]],
                f"Completed: {form['title']}",
                f"{submission.get('tracking_number') or ('Submission #' + str(submission_id))} was completed.",
                link_url=f"/forms/submissions/{submission_id}",
                style_key="success",
                sender_name=(fullname or "").strip() or username,
            )
            _audit(connection, "submission.completed", username, "submission", submission_id, tracking_number=submission.get("tracking_number"))
        else:
            _create_stage_tasks(connection, submission_id, stages, next_stage_index)
            connection.execute(
                """
                UPDATE form_submissions
                SET current_stage_index = ?, current_task_order = 1, updated_at = ?
                WHERE id = ?
                """,
                (next_stage_index, acted_at, submission_id),
            )
            _notify_stage_reviewers(connection, form, submission_id, stages, next_stage_index)
    _audit(connection, "submission.approved-step", username, "submission", submission_id, tracking_number=submission.get("tracking_number"), payload={"stage_index": stage_index})
    connection.commit()
    connection.close()
    return True, "Review recorded."


def get_smtp_settings():
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute("SELECT * FROM smtp_settings WHERE id = 1")
    row = cursor.fetchone()
    connection.close()
    return dict(row) if row else {
        "host": "",
        "port": 587,
        "username": "",
        "password_obfuscated": "",
        "from_email": "",
        "from_name": "",
        "use_tls": 1,
    }


def save_smtp_settings(payload, actor_username):
    host = str(payload.get("host") or "").strip()
    username = str(payload.get("username") or "").strip()
    from_email = str(payload.get("from_email") or "").strip()
    from_name = str(payload.get("from_name") or "").strip()
    password = str(payload.get("password") or "")
    use_tls = 1 if payload.get("use_tls") else 0
    try:
        port = int(payload.get("port") or 0)
    except (TypeError, ValueError):
        port = 0
    if host and not port:
        return False, "SMTP port is required when SMTP host is provided."
    connection = connect_db()
    connection.execute(
        """
        UPDATE smtp_settings
        SET
            host = ?,
            port = ?,
            username = ?,
            password_obfuscated = CASE WHEN ? != '' THEN ? ELSE password_obfuscated END,
            from_email = ?,
            from_name = ?,
            use_tls = ?,
            updated_by_username = ?,
            updated_at = ?
        WHERE id = 1
        """,
        (
            host or None,
            port or None,
            username or None,
            password,
            password.encode("utf-8").hex() if password else "",
            from_email or None,
            from_name or None,
            use_tls,
            actor_username,
            timestamp_now(),
        ),
    )
    _audit(connection, "smtp.updated", actor_username, "smtp", 1, payload={"host": host, "port": port, "username": username, "from_email": from_email})
    connection.commit()
    connection.close()
    return True, "SMTP settings saved."
