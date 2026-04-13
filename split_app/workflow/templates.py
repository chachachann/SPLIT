import os
import re

from werkzeug.utils import secure_filename

from logic import connect_db, get_profile_identity_map, normalize_role_names, timestamp_now
from split_app.workflow.common import (
    ALLOWED_FORM_IMAGE_EXTENSIONS,
    FIELD_TYPES,
    FORM_ICON_DIR,
    FORM_STATUSES,
    STAGE_MODES,
    ensure_form_workflow_folders,
    _audit,
    _field_key,
    _json_dumps,
    _json_loads,
    _normalize_username_list,
    _slugify,
)


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


def _normalize_card_accent(value, fallback="#43e493"):
    clean = str(value or "").strip()
    if re.fullmatch(r"#[0-9a-fA-F]{6}", clean):
        return clean.lower()
    if re.fullmatch(r"#[0-9a-fA-F]{3}", clean):
        return "#" + "".join(char * 2 for char in clean[1:]).lower()
    if re.fullmatch(r"[0-9a-fA-F]{6}", clean):
        return ("#" + clean).lower()
    if re.fullmatch(r"[0-9a-fA-F]{3}", clean):
        return "#" + "".join(char * 2 for char in clean).lower()
    return fallback


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
        "accent": _normalize_card_accent(payload.get("card_accent")),
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
