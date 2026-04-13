import json
import os
import re

from werkzeug.utils import secure_filename

from split_app.services.content import build_notification_preview, render_notification_markup
from split_app.services.core import (
    ALLOWED_PROFILE_IMAGE_EXTENSIONS,
    MAX_PROFILE_IMAGE_SIZE_BYTES,
    PROFILE_AUDIT_EVENT_LABELS,
    PROFILE_FIELD_LABELS,
    PROFILE_IMAGE_DIR,
    PROFILE_IMAGE_WEB_PATH,
    PROFILE_PRIVATE_FIELDS,
    build_profile_private_fields,
    build_static_upload_url,
    connect_db,
    ensure_profile_image_folder,
    get_initials,
    hash_password,
    is_password_hash,
    json_dumps,
    normalize_theme,
    timestamp_now,
    THEME_CHOICES,
)


def ensure_user_profile(connection, user_row):
    if not user_row:
        return None

    cursor = connection.cursor()
    cursor.execute("SELECT * FROM user_profiles WHERE user_id = ?", (user_row["id"],))
    profile_row = cursor.fetchone()
    now = timestamp_now()
    fallback_display = (user_row["fullname"] or "").strip() or user_row["username"]

    if not profile_row:
        cursor.execute(
            """
            INSERT INTO user_profiles (
                user_id,
                display_name,
                private_fields_json,
                theme_preference,
                created_at,
                updated_at
            )
            VALUES (?, ?, '[]', 'dark', ?, ?)
            """,
            (user_row["id"], fallback_display, now, now),
        )
        connection.commit()
        cursor.execute("SELECT * FROM user_profiles WHERE user_id = ?", (user_row["id"],))
        return cursor.fetchone()

    profile_data = dict(profile_row)
    display_name = (profile_data.get("display_name") or "").strip()
    created_at = profile_data.get("created_at")
    updated_at = profile_data.get("updated_at")
    needs_update = False

    if not display_name:
        profile_data["display_name"] = fallback_display
        needs_update = True
    if not created_at:
        profile_data["created_at"] = now
        needs_update = True
    if not updated_at:
        profile_data["updated_at"] = now
        needs_update = True

    if needs_update:
        cursor.execute(
            """
            UPDATE user_profiles
            SET display_name = ?, created_at = COALESCE(created_at, ?), updated_at = COALESCE(updated_at, ?)
            WHERE user_id = ?
            """,
            (profile_data["display_name"], profile_data["created_at"], profile_data["updated_at"], user_row["id"]),
        )
        connection.commit()
        cursor.execute("SELECT * FROM user_profiles WHERE user_id = ?", (user_row["id"],))
        return cursor.fetchone()

    return profile_row


def seed_default_user_profiles(connection):
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT id, username, fullname
        FROM users
        ORDER BY id
        """
    )
    for user_row in cursor.fetchall():
        ensure_user_profile(connection, user_row)


def migrate_plaintext_passwords(connection):
    cursor = connection.cursor()
    cursor.execute("SELECT id, password FROM users")
    for row in cursor.fetchall():
        raw_password = (row["password"] or "").strip()
        if raw_password and not is_password_hash(raw_password):
            cursor.execute(
                """
                UPDATE users
                SET password = ?
                WHERE id = ?
                """,
                (hash_password(raw_password), row["id"]),
            )


def build_profile_avatar(relative_path, display_name):
    return {
        "path": (relative_path or "").strip(),
        "url": build_static_upload_url(relative_path),
        "initials": get_initials(display_name, "U"),
    }


def build_profile_identity(connection, user_row, profile_row=None, viewer_username=None):
    if not user_row:
        return None

    profile_row = profile_row or ensure_user_profile(connection, user_row)
    profile_data = dict(profile_row or {})
    full_name = (user_row["fullname"] or "").strip()
    display_name = (profile_data.get("display_name") or "").strip() or full_name or user_row["username"]
    private_fields = set(build_profile_private_fields(profile_data.get("private_fields_json")))
    is_self = (viewer_username or "").casefold() == (user_row["username"] or "").casefold()
    designation = (user_row["designation"] or "").strip()

    def visible(field_key, value):
        if is_self or field_key not in private_fields:
            return value
        return ""

    avatar = build_profile_avatar(profile_data.get("avatar_path"), display_name)
    return {
        "user_id": user_row["id"],
        "username": user_row["username"],
        "full_name": full_name,
        "display_name": display_name,
        "designation": visible("designation", designation),
        "designation_raw": designation,
        "department": visible("department", (profile_data.get("department") or "").strip()),
        "phone": visible("phone", (profile_data.get("phone") or "").strip()),
        "email": visible("email", (profile_data.get("email") or "").strip()),
        "address": visible("address", (profile_data.get("address") or "").strip()),
        "birthday": visible("birthday", (profile_data.get("birthday") or "").strip()),
        "bio": visible("bio", (profile_data.get("bio") or "").strip()),
        "theme_preference": normalize_theme(profile_data.get("theme_preference")),
        "private_fields": sorted(private_fields),
        "avatar_path": avatar["path"],
        "avatar_url": avatar["url"],
        "avatar_initials": avatar["initials"],
        "profile_url": f"/users/{user_row['username']}",
        "last_login_at": user_row["last_login_at"] or "",
        "is_self": is_self,
    }


def get_profile_identity_map(connection, usernames, viewer_username=None):
    clean_usernames = []
    seen = set()
    for username in usernames or []:
        clean_username = " ".join((username or "").split())
        if not clean_username:
            continue
        key = clean_username.casefold()
        if key in seen:
            continue
        seen.add(key)
        clean_usernames.append(clean_username)

    if not clean_usernames:
        return {}

    placeholders = ", ".join("?" for _ in clean_usernames)
    cursor = connection.cursor()
    cursor.execute(
        f"""
        SELECT
            u.id,
            u.username,
            u.password,
            u.designation,
            u.userlevel,
            u.fullname,
            u.date_created,
            u.last_login_at,
            p.display_name,
            p.department,
            p.phone,
            p.email,
            p.address,
            p.birthday,
            p.bio,
            p.avatar_path,
            p.private_fields_json,
            p.theme_preference,
            p.created_at AS profile_created_at,
            p.updated_at AS profile_updated_at
        FROM users u
        LEFT JOIN user_profiles p ON p.user_id = u.id
        WHERE lower(u.username) IN ({placeholders})
        """,
        tuple(item.casefold() for item in clean_usernames),
    )
    mapping = {}
    for row in cursor.fetchall():
        user_data = {
            "id": row["id"],
            "username": row["username"],
            "password": row["password"],
            "designation": row["designation"],
            "userlevel": row["userlevel"],
            "fullname": row["fullname"],
            "date_created": row["date_created"],
            "last_login_at": row["last_login_at"],
        }
        profile_data = {
            "user_id": row["id"],
            "display_name": row["display_name"],
            "department": row["department"],
            "phone": row["phone"],
            "email": row["email"],
            "address": row["address"],
            "birthday": row["birthday"],
            "bio": row["bio"],
            "avatar_path": row["avatar_path"],
            "private_fields_json": row["private_fields_json"],
            "theme_preference": row["theme_preference"],
            "created_at": row["profile_created_at"],
            "updated_at": row["profile_updated_at"],
        }
        if not profile_data["created_at"] or not profile_data["updated_at"] or not (profile_data["display_name"] or "").strip():
            profile_row = ensure_user_profile(connection, user_data)
            profile_data = dict(profile_row)
        mapping[row["username"].casefold()] = build_profile_identity(connection, user_data, profile_data, viewer_username=viewer_username)
    return mapping


def log_profile_audit(connection, user_id, actor_username, event_type, payload=None):
    connection.execute(
        """
        INSERT INTO profile_audit_log (
            user_id,
            actor_username,
            event_type,
            payload_json,
            created_at
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            int(user_id),
            (actor_username or "").strip() or None,
            event_type,
            json_dumps(payload or {}),
            timestamp_now(),
        ),
    )


def _get_profile_audit_field_label(field_key):
    clean_key = str(field_key or "").strip().lower()
    if clean_key == "display_name":
        return "Display Name"
    if clean_key == "avatar":
        return "Avatar"
    if clean_key in PROFILE_FIELD_LABELS:
        return PROFILE_FIELD_LABELS[clean_key]
    return clean_key.replace("_", " ").title() if clean_key else "Field"


def _format_profile_audit_event_label(event_type):
    clean_event = str(event_type or "").strip()
    if not clean_event:
        return "Audit Event"
    if clean_event in PROFILE_AUDIT_EVENT_LABELS:
        return PROFILE_AUDIT_EVENT_LABELS[clean_event]
    return clean_event.replace(".", " ").replace("-", " ").title()


def _format_profile_audit_value(value):
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if value is None:
        return "Blank"
    if isinstance(value, list):
        items = [_format_profile_audit_value(item) for item in value if item not in (None, "")]
        return ", ".join(items) if items else "None"
    text = str(value).strip()
    return text or "Blank"


def _build_profile_audit_payload_lines(event_type, payload):
    if not payload:
        return []
    if not isinstance(payload, dict):
        return [_format_profile_audit_value(payload)]

    if event_type == "profile.preferences-updated":
        theme_value = str(payload.get("theme_preference") or "").strip().lower()
        return [f"Theme preference: {theme_value.title()}"] if theme_value in THEME_CHOICES else []

    if event_type == "profile.privacy-updated":
        private_fields = [
            _get_profile_audit_field_label(field_key)
            for field_key in (payload.get("private_fields") or [])
        ]
        return [f"Private fields: {', '.join(private_fields)}" if private_fields else "Private fields: None"]

    if event_type in {"profile.password-request-approved", "profile.password-request-rejected"}:
        request_id = payload.get("request_id")
        return [f"Request ID: {request_id}"] if request_id is not None else []

    lines = []
    for field_key, change in payload.items():
        label = _get_profile_audit_field_label(field_key)
        if field_key == "avatar":
            lines.append("Avatar updated")
            continue
        if isinstance(change, dict) and ("from" in change or "to" in change):
            previous_value = _format_profile_audit_value(change.get("from"))
            next_value = _format_profile_audit_value(change.get("to"))
            lines.append(f"{label}: {next_value}" if previous_value == next_value else f"{label}: {previous_value} -> {next_value}")
            continue
        if field_key == "theme_preference":
            theme_value = str(change or "").strip().lower()
            lines.append(f"{label}: {theme_value.title()}" if theme_value in THEME_CHOICES else f"{label}: {_format_profile_audit_value(change)}")
            continue
        lines.append(f"{label}: {_format_profile_audit_value(change)}")
    return lines


def get_role_members(connection, role_name):
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT u.id, u.username
        FROM users u
        INNER JOIN user_roles ur ON ur.user_id = u.id
        INNER JOIN roles r ON r.id = ur.role_id
        WHERE lower(r.name) = lower(?)
        ORDER BY u.username COLLATE NOCASE
        """,
        (role_name,),
    )
    return [dict(row) for row in cursor.fetchall()]


def build_editable_profile(user_row, profile_row):
    profile_data = dict(profile_row or {})
    full_name = (user_row["fullname"] or "").strip()
    display_name = (profile_data.get("display_name") or "").strip() or full_name or user_row["username"]
    private_fields = set(build_profile_private_fields(profile_data.get("private_fields_json")))
    avatar = build_profile_avatar(profile_data.get("avatar_path"), display_name)
    return {
        "user_id": user_row["id"],
        "username": user_row["username"],
        "full_name": full_name,
        "display_name": display_name,
        "designation": (user_row["designation"] or "").strip(),
        "department": (profile_data.get("department") or "").strip(),
        "phone": (profile_data.get("phone") or "").strip(),
        "email": (profile_data.get("email") or "").strip(),
        "address": (profile_data.get("address") or "").strip(),
        "birthday": (profile_data.get("birthday") or "").strip(),
        "bio": (profile_data.get("bio") or "").strip(),
        "theme_preference": normalize_theme(profile_data.get("theme_preference")),
        "private_fields": sorted(private_fields),
        "avatar_path": avatar["path"],
        "avatar_url": avatar["url"],
        "avatar_initials": avatar["initials"],
        "profile_url": f"/users/{user_row['username']}",
    }


def save_profile_avatar(connection, user_row, upload):
    if not upload or not upload.filename:
        return True, "", None

    ensure_profile_image_folder()
    filename = secure_filename(upload.filename)
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_PROFILE_IMAGE_EXTENSIONS:
        return False, "Use PNG, JPG, JPEG, GIF, or WEBP for profile photos.", None

    try:
        upload.stream.seek(0, os.SEEK_END)
        file_size = upload.stream.tell()
        upload.stream.seek(0)
    except (AttributeError, OSError):
        file_size = None

    if file_size is not None and file_size > MAX_PROFILE_IMAGE_SIZE_BYTES:
        max_size_mb = MAX_PROFILE_IMAGE_SIZE_BYTES // (1024 * 1024)
        return False, f"Profile photos must be {max_size_mb} MB or smaller.", None

    existing_profile = ensure_user_profile(connection, user_row)
    existing_path = (existing_profile["avatar_path"] or "").strip() if existing_profile else ""
    candidate = f"user-{user_row['id']}{ext}"
    target_path = os.path.join(PROFILE_IMAGE_DIR, candidate)
    upload.save(target_path)
    relative_path = f"{PROFILE_IMAGE_WEB_PATH}/{candidate}"

    if existing_path and existing_path != relative_path:
        previous_file = os.path.join(os.path.dirname(__file__), "..", "..", "static", existing_path)
        previous_file = os.path.normpath(previous_file)
        if os.path.exists(previous_file):
            os.remove(previous_file)

    return True, "", relative_path


def remove_profile_avatar(connection, user_row):
    profile_row = ensure_user_profile(connection, user_row)
    existing_path = (profile_row["avatar_path"] or "").strip() if profile_row else ""
    if not existing_path:
        return False, "No profile photo is set."

    absolute_path = os.path.join(os.path.dirname(__file__), "..", "..", "static", existing_path)
    absolute_path = os.path.normpath(absolute_path)
    if os.path.exists(absolute_path):
        os.remove(absolute_path)

    connection.execute(
        """
        UPDATE user_profiles
        SET avatar_path = NULL, updated_at = ?
        WHERE user_id = ?
        """,
        (timestamp_now(), user_row["id"]),
    )
    log_profile_audit(connection, user_row["id"], user_row["username"], "profile.avatar-removed")
    connection.commit()
    return True, "Profile photo removed."


def create_profile_notifications(connection, user_ids, title, message, link_url="", style_key="info", sender_name="System"):
    seen = set()
    for user_id in user_ids or []:
        try:
            clean_user_id = int(user_id)
        except (TypeError, ValueError):
            continue
        if clean_user_id in seen:
            continue
        seen.add(clean_user_id)
        connection.execute(
            """
            INSERT INTO profile_notifications (
                user_id,
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
                clean_user_id,
                " ".join((title or "").split()),
                (message or "").strip(),
                (link_url or "").strip() or None,
                (style_key or "").strip() or "info",
                (sender_name or "").strip() or "System",
                timestamp_now(),
            ),
        )


def get_profile_notifications_for_user(username):
    from logic import get_user_row_by_username

    connection = connect_db()
    user_row = get_user_row_by_username(connection, username)
    if not user_row:
        connection.close()
        return []

    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT id, title, message, link_url, style_key, sender_name, created_at
        FROM profile_notifications
        WHERE user_id = ?
        ORDER BY datetime(created_at) DESC, id DESC
        """,
        (user_row["id"],),
    )
    items = [dict(row) for row in cursor.fetchall()]
    if not items:
        connection.close()
        return []

    notification_keys = [f"profile:{item['id']}" for item in items]
    placeholders = ", ".join("?" for _ in notification_keys)
    cursor.execute(
        f"""
        SELECT notification_key, is_read, is_hidden
        FROM profile_notification_states
        WHERE user_id = ? AND notification_key IN ({placeholders})
        """,
        (user_row["id"], *notification_keys),
    )
    state_map = {row["notification_key"]: dict(row) for row in cursor.fetchall()}
    connection.close()

    visible_items = []
    for item in items:
        notification_key = f"profile:{item['id']}"
        state = state_map.get(notification_key, {})
        item["notification_key"] = notification_key
        item["sender_name"] = (item.get("sender_name") or "").strip() or "System"
        item["message_preview"] = build_notification_preview(item.get("message"))
        item["message_html"] = render_notification_markup(item.get("message"))
        item["is_read"] = bool(state.get("is_read"))
        item["is_hidden"] = bool(state.get("is_hidden"))
        if item["is_hidden"]:
            continue
        visible_items.append(item)
    return visible_items


def set_profile_notification_state(username, notification_key, *, is_read=None, is_hidden=None):
    from logic import get_user_row_by_username

    key = (notification_key or "").strip()
    if not key.startswith("profile:"):
        return False

    try:
        notification_id = int(key.split(":", 1)[1])
    except (TypeError, ValueError):
        return False

    connection = connect_db()
    user_row = get_user_row_by_username(connection, username)
    if not user_row:
        connection.close()
        return False

    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT is_read, is_hidden
        FROM profile_notification_states
        WHERE user_id = ? AND notification_key = ?
        """,
        (user_row["id"], key),
    )
    existing = cursor.fetchone()
    next_read = int(existing["is_read"]) if existing else 0
    next_hidden = int(existing["is_hidden"]) if existing else 0
    if is_read is not None:
        next_read = 1 if is_read else 0
    if is_hidden is not None:
        next_hidden = 1 if is_hidden else 0

    cursor.execute(
        """
        SELECT id
        FROM profile_notifications
        WHERE id = ? AND user_id = ?
        """,
        (notification_id, user_row["id"]),
    )
    if not cursor.fetchone():
        connection.close()
        return False

    cursor.execute(
        """
        INSERT INTO profile_notification_states (
            user_id,
            notification_key,
            is_read,
            is_hidden,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id, notification_key) DO UPDATE SET
            is_read = excluded.is_read,
            is_hidden = excluded.is_hidden,
            updated_at = excluded.updated_at
        """,
        (user_row["id"], key, next_read, next_hidden, timestamp_now()),
    )
    connection.commit()
    connection.close()
    return True


def build_profile_visibility_rows(profile_data, *, viewer_is_owner=False, include_empty=False):
    private_fields = set(profile_data.get("private_fields") or [])
    rows = []
    for field_key, label in PROFILE_FIELD_LABELS.items():
        value = (profile_data.get(field_key) or "").strip()
        if not viewer_is_owner and field_key in private_fields:
            continue
        if not include_empty and not value:
            continue
        rows.append(
            {
                "key": field_key,
                "label": label,
                "value": value,
                "is_private": field_key in private_fields,
            }
        )
    return rows


def get_profile_audit_entries(target_user_id):
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT id, actor_username, event_type, payload_json, created_at
        FROM profile_audit_log
        WHERE user_id = ?
        ORDER BY datetime(created_at) DESC, id DESC
        LIMIT 40
        """,
        (target_user_id,),
    )
    entries = [dict(row) for row in cursor.fetchall()]
    actor_map = get_profile_identity_map(
        connection,
        [entry["actor_username"] for entry in entries if entry.get("actor_username")],
        viewer_username="",
    )
    connection.close()
    for entry in entries:
        actor_identity = actor_map.get((entry.get("actor_username") or "").casefold())
        entry["actor_display_name"] = (
            (actor_identity.get("display_name") if actor_identity else "")
            or (entry.get("actor_username") or "System")
        )
        entry["event_label"] = _format_profile_audit_event_label(entry.get("event_type"))
        entry["payload_summary_lines"] = []
        payload_json = str(entry.get("payload_json") or "").strip()
        if payload_json and payload_json != "{}":
            try:
                payload = json.loads(payload_json)
            except (TypeError, ValueError):
                entry["payload_summary_lines"] = [payload_json]
            else:
                entry["payload_summary_lines"] = _build_profile_audit_payload_lines(entry.get("event_type"), payload) or [payload_json]
    return entries


def get_profile_context(username):
    from logic import get_user_row_by_username

    connection = connect_db()
    user_row = get_user_row_by_username(connection, username)
    if not user_row:
        connection.close()
        return None
    profile_row = ensure_user_profile(connection, user_row)
    profile = build_editable_profile(user_row, profile_row)
    connection.close()
    return {
        "profile": profile,
        "privacy_options": [
            {
                "key": field_key,
                "label": PROFILE_FIELD_LABELS[field_key],
                "checked": field_key in set(profile["private_fields"]),
            }
            for field_key in PROFILE_PRIVATE_FIELDS
        ],
        "password_requests": get_password_change_requests_for_user(username),
    }


def get_public_profile_context(target_username, viewer_username, viewer_roles):
    from logic import get_user_row_by_username

    connection = connect_db()
    user_row = get_user_row_by_username(connection, target_username)
    if not user_row:
        connection.close()
        return False, "User not found.", None

    profile_row = ensure_user_profile(connection, user_row)
    editable_profile = build_editable_profile(user_row, profile_row)
    identity = build_profile_identity(connection, user_row, profile_row, viewer_username=viewer_username)
    connection.close()

    can_view_audit = any((role or "").casefold() == "developer" for role in (viewer_roles or []))
    context = {
        "profile": {
            **editable_profile,
            "display_name": identity["display_name"],
            "designation": identity["designation"],
        },
        "field_rows": build_profile_visibility_rows(
            {
                **editable_profile,
                "designation": identity["designation"],
            },
            viewer_is_owner=identity["is_self"],
            include_empty=identity["is_self"],
        ),
        "is_self": identity["is_self"],
        "can_view_audit": can_view_audit,
        "audit_entries": get_profile_audit_entries(user_row["id"]) if can_view_audit else [],
    }
    return True, "", context


def save_profile_basic(username, form_data, avatar_upload=None):
    from logic import get_user_row_by_username

    connection = connect_db()
    user_row = get_user_row_by_username(connection, username)
    if not user_row:
        connection.close()
        return False, "User not found.", None

    profile_row = ensure_user_profile(connection, user_row)
    current_profile = build_editable_profile(user_row, profile_row)
    next_full_name = " ".join((form_data.get("full_name") or "").split()).strip() or current_profile["full_name"]
    next_display_name = " ".join((form_data.get("display_name") or "").split()).strip()
    next_department = " ".join((form_data.get("department") or "").split()).strip()
    next_phone = (form_data.get("phone") or "").strip()
    next_email = (form_data.get("email") or "").strip()
    next_address = (form_data.get("address") or "").strip()
    next_birthday = (form_data.get("birthday") or "").strip()
    next_bio = (form_data.get("bio") or "").strip()

    if next_birthday and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", next_birthday):
        connection.close()
        return False, "Birthday must use YYYY-MM-DD.", None

    changes = {}
    if next_full_name != current_profile["full_name"]:
        changes["full_name"] = {"from": current_profile["full_name"], "to": next_full_name}
    if next_display_name != (profile_row["display_name"] or "").strip():
        changes["display_name"] = {"from": (profile_row["display_name"] or "").strip(), "to": next_display_name}
    if next_department != current_profile["department"]:
        changes["department"] = {"from": current_profile["department"], "to": next_department}
    if next_phone != current_profile["phone"]:
        changes["phone"] = {"from": current_profile["phone"], "to": next_phone}
    if next_email != current_profile["email"]:
        changes["email"] = {"from": current_profile["email"], "to": next_email}
    if next_address != current_profile["address"]:
        changes["address"] = {"from": current_profile["address"], "to": next_address}
    if next_birthday != current_profile["birthday"]:
        changes["birthday"] = {"from": current_profile["birthday"], "to": next_birthday}
    if next_bio != current_profile["bio"]:
        changes["bio"] = {"from": current_profile["bio"], "to": next_bio}

    next_avatar_path = None
    if avatar_upload and avatar_upload.filename:
        ok, message, saved_path = save_profile_avatar(connection, user_row, avatar_upload)
        if not ok:
            connection.close()
            return False, message, None
        next_avatar_path = saved_path
        changes["avatar"] = {"from": current_profile["avatar_path"], "to": saved_path}

    if not changes:
        updated_profile = get_profile_context(username)
        connection.close()
        return True, "No changes were made.", updated_profile["profile"] if updated_profile else None

    connection.execute(
        """
        UPDATE users
        SET fullname = ?
        WHERE id = ?
        """,
        (next_full_name, user_row["id"]),
    )
    connection.execute(
        """
        UPDATE user_profiles
        SET
            display_name = ?,
            department = ?,
            phone = ?,
            email = ?,
            address = ?,
            birthday = ?,
            bio = ?,
            avatar_path = COALESCE(?, avatar_path),
            updated_at = ?
        WHERE user_id = ?
        """,
        (
            next_display_name,
            next_department,
            next_phone,
            next_email,
            next_address,
            next_birthday,
            next_bio,
            next_avatar_path,
            timestamp_now(),
            user_row["id"],
        ),
    )
    log_profile_audit(connection, user_row["id"], username, "profile.basic-updated", payload=changes)
    connection.commit()
    connection.close()
    updated_profile = get_profile_context(username)
    return True, "Profile updated.", updated_profile["profile"] if updated_profile else None


def save_profile_privacy(username, private_fields):
    from logic import get_user_row_by_username

    connection = connect_db()
    user_row = get_user_row_by_username(connection, username)
    if not user_row:
        connection.close()
        return False, "User not found.", None

    profile_row = ensure_user_profile(connection, user_row)
    next_private_fields = []
    seen = set()
    for field_key in private_fields or []:
        clean_key = str(field_key or "").strip().lower()
        if clean_key not in PROFILE_FIELD_LABELS or clean_key in seen:
            continue
        seen.add(clean_key)
        next_private_fields.append(clean_key)

    previous_private_fields = build_profile_private_fields(profile_row["private_fields_json"])
    if previous_private_fields == next_private_fields:
        profile_context = get_profile_context(username)
        connection.close()
        return True, "No privacy changes were made.", profile_context["profile"] if profile_context else None

    connection.execute(
        """
        UPDATE user_profiles
        SET private_fields_json = ?, updated_at = ?
        WHERE user_id = ?
        """,
        (json_dumps(next_private_fields), timestamp_now(), user_row["id"]),
    )
    log_profile_audit(
        connection,
        user_row["id"],
        username,
        "profile.privacy-updated",
        payload={"private_fields": next_private_fields},
    )
    connection.commit()
    connection.close()
    profile_context = get_profile_context(username)
    return True, "Privacy settings updated.", profile_context["profile"] if profile_context else None


def save_profile_preferences(username, theme, *, audit_event="profile.preferences-updated"):
    from logic import get_user_row_by_username

    connection = connect_db()
    user_row = get_user_row_by_username(connection, username)
    if not user_row:
        connection.close()
        return False, "User not found.", None

    profile_row = ensure_user_profile(connection, user_row)
    next_theme = normalize_theme(theme)
    previous_theme = normalize_theme(profile_row["theme_preference"])
    if previous_theme == next_theme:
        profile_context = get_profile_context(username)
        connection.close()
        return True, "Theme preference already applied.", profile_context["profile"] if profile_context else None

    connection.execute(
        """
        UPDATE user_profiles
        SET theme_preference = ?, updated_at = ?
        WHERE user_id = ?
        """,
        (next_theme, timestamp_now(), user_row["id"]),
    )
    if audit_event:
        log_profile_audit(
            connection,
            user_row["id"],
            username,
            audit_event,
            payload={"theme_preference": next_theme},
        )
    connection.commit()
    connection.close()
    profile_context = get_profile_context(username)
    return True, "Theme preference saved.", profile_context["profile"] if profile_context else None


def get_profile_request_counts(username, role_names):
    from logic import get_user_row_by_username

    connection = connect_db()
    user_row = get_user_row_by_username(connection, username)
    if not user_row:
        connection.close()
        return {"my_requests": 0, "review_queue": 0}

    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT COUNT(*) AS total
        FROM password_change_requests
        WHERE requester_user_id = ? AND status != 'archived'
        """,
        (user_row["id"],),
    )
    my_requests = int(cursor.fetchone()["total"] or 0)
    role_keys = {str(role or "").casefold() for role in (role_names or [])}
    review_queue = 0
    if role_keys & {"developer", "superadmin"}:
        cursor.execute(
            """
            SELECT COUNT(*) AS total
            FROM password_change_requests
            WHERE status = 'pending'
            """,
        )
        review_queue = int(cursor.fetchone()["total"] or 0)

    connection.close()
    return {"my_requests": my_requests, "review_queue": review_queue}


def get_password_change_requests_for_user(username):
    from logic import get_user_row_by_username

    connection = connect_db()
    user_row = get_user_row_by_username(connection, username)
    if not user_row:
        connection.close()
        return []

    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT id, status, reviewed_by_username, rejection_note, created_at, updated_at, reviewed_at
        FROM password_change_requests
        WHERE requester_user_id = ?
        ORDER BY datetime(created_at) DESC, id DESC
        """,
        (user_row["id"],),
    )
    items = [dict(row) for row in cursor.fetchall()]
    reviewer_map = get_profile_identity_map(
        connection,
        [item["reviewed_by_username"] for item in items if item.get("reviewed_by_username")],
        viewer_username=username,
    )
    connection.close()

    for item in items:
        reviewer_identity = reviewer_map.get((item.get("reviewed_by_username") or "").casefold())
        item["title"] = "Password Change Request"
        item["request_type"] = "password_change"
        item["reviewed_by_display_name"] = (
            (reviewer_identity.get("display_name") if reviewer_identity else "")
            or item.get("reviewed_by_username")
            or ""
        )
        item["status_label"] = item["status"].replace("_", " ").title()
    return items


def get_password_change_review_queue(username, role_names):
    role_keys = {str(role or "").casefold() for role in (role_names or [])}
    if not (role_keys & {"developer", "superadmin"}):
        return []

    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT r.id, r.requester_user_id, r.created_at, r.updated_at, u.username, u.fullname, u.designation
        FROM password_change_requests r
        INNER JOIN users u ON u.id = r.requester_user_id
        WHERE r.status = 'pending'
        ORDER BY datetime(r.created_at) ASC, r.id ASC
        """
    )
    items = [dict(row) for row in cursor.fetchall()]
    identity_map = get_profile_identity_map(connection, [item["username"] for item in items], viewer_username=username)
    connection.close()

    for item in items:
        identity = identity_map.get(item["username"].casefold())
        item["title"] = "Password Change Request"
        item["request_type"] = "password_change"
        item["requester_display_name"] = (identity.get("display_name") if identity else "") or item["username"]
        item["requester_designation"] = (identity.get("designation") if identity else "") or ""
        item["requester_avatar_url"] = (identity.get("avatar_url") if identity else "") or ""
        item["requester_avatar_initials"] = (identity.get("avatar_initials") if identity else get_initials(item["username"], "U"))
        item["requester_profile_url"] = (identity.get("profile_url") if identity else f"/users/{item['username']}")
    return items


def submit_password_change_request(username, new_password, confirm_password):
    from logic import get_user_row_by_username

    clean_password = (new_password or "").strip()
    clean_confirm = (confirm_password or "").strip()
    if not clean_password:
        return False, "Enter the new password you want to request."
    if clean_password != clean_confirm:
        return False, "The password confirmation does not match."

    connection = connect_db()
    user_row = get_user_row_by_username(connection, username)
    if not user_row:
        connection.close()
        return False, "User not found."

    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT id
        FROM password_change_requests
        WHERE requester_user_id = ? AND status = 'pending'
        """,
        (user_row["id"],),
    )
    if cursor.fetchone():
        connection.close()
        return False, "You already have a pending password change request."

    now = timestamp_now()
    cursor.execute(
        """
        INSERT INTO password_change_requests (
            requester_user_id,
            password_hash,
            status,
            created_at,
            updated_at
        )
        VALUES (?, ?, 'pending', ?, ?)
        """,
        (user_row["id"], hash_password(clean_password), now, now),
    )

    reviewer_user_ids = []
    for role_name in ("Developer", "SuperAdmin"):
        reviewer_user_ids.extend([row["id"] for row in get_role_members(connection, role_name)])
    create_profile_notifications(
        connection,
        reviewer_user_ids,
        "Password change request pending",
        f"{(user_row['fullname'] or '').strip() or user_row['username']} submitted a password change request.",
        link_url="/forms/review-queue",
        style_key="warning",
        sender_name=(user_row["fullname"] or "").strip() or user_row["username"],
    )
    log_profile_audit(connection, user_row["id"], username, "profile.password-request-submitted")
    connection.commit()
    connection.close()
    return True, "Password change request submitted."


def review_password_change_request(request_id, reviewer_username, role_names, action, rejection_note=""):
    from logic import get_user_row_by_id

    role_keys = {str(role or "").casefold() for role in (role_names or [])}
    if not (role_keys & {"developer", "superadmin"}):
        return False, "You do not have access to review password change requests."

    review_action = (action or "").strip().lower()
    if review_action not in {"approve", "reject"}:
        return False, "Unsupported review action."

    rejection_note = (rejection_note or "").strip()
    if review_action == "reject" and not rejection_note:
        return False, "A rejection note is required."

    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT id, requester_user_id, password_hash, status
        FROM password_change_requests
        WHERE id = ?
        """,
        (request_id,),
    )
    request_row = cursor.fetchone()
    if not request_row:
        connection.close()
        return False, "Password change request not found."
    if request_row["status"] != "pending":
        connection.close()
        return False, "This password change request has already been resolved."

    requester_row = get_user_row_by_id(connection, request_row["requester_user_id"])
    reviewer_identity = get_user_identity(reviewer_username) or {"fullname": reviewer_username}
    acted_at = timestamp_now()
    next_status = "approved" if review_action == "approve" else "rejected"

    if review_action == "approve":
        cursor.execute(
            """
            UPDATE users
            SET password = ?
            WHERE id = ?
            """,
            (request_row["password_hash"], request_row["requester_user_id"]),
        )
        if requester_row:
            cursor.execute(
                """
                DELETE FROM remember_tokens
                WHERE lower(username) = lower(?)
                """,
                (requester_row["username"],),
            )

    cursor.execute(
        """
        UPDATE password_change_requests
        SET status = ?, reviewed_by_username = ?, rejection_note = ?, reviewed_at = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            next_status,
            reviewer_username,
            rejection_note if review_action == "reject" else None,
            acted_at,
            acted_at,
            request_id,
        ),
    )

    notification_title = "Password change approved" if review_action == "approve" else "Password change rejected"
    notification_message = (
        "Your password change request was approved and applied immediately."
        if review_action == "approve"
        else f"Your password change request was rejected. Reason: {rejection_note}"
    )
    create_profile_notifications(
        connection,
        [request_row["requester_user_id"]],
        notification_title,
        notification_message,
        link_url="/profile?tab=security",
        style_key="success" if review_action == "approve" else "danger",
        sender_name=(reviewer_identity.get("fullname") or "").strip() or reviewer_username,
    )
    log_profile_audit(
        connection,
        request_row["requester_user_id"],
        reviewer_username,
        f"profile.password-request-{next_status}",
        payload={"request_id": int(request_id)},
    )
    connection.commit()
    connection.close()

    requester_name = (requester_row["fullname"] or "").strip() if requester_row else ""
    if review_action == "approve":
        return True, f"Password updated for {(requester_name or 'the user')}."
    return True, "Password change request rejected."
