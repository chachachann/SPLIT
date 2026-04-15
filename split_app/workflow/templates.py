import os
import re

from werkzeug.utils import secure_filename

from logic import connect_db, get_profile_identity_map, normalize_role_names, timestamp_now
from split_app.workflow.common import (
    ALLOWED_FORM_IMAGE_EXTENSIONS,
    FIELD_TYPES,
    FORM_FILE_DIR,
    FORM_ICON_DIR,
    FORM_STATUSES,
    STAGE_MODES,
    ensure_form_workflow_folders,
    get_workflow_queue_last_viewed_at,
    _audit,
    _field_key,
    _json_dumps,
    _json_loads,
    _normalize_username_list,
    _slugify,
)

PROMOTION_SPAWN_MODES = {"automatic", "reviewer_choice"}


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
                "placeholder": str(raw_field.get("placeholder") or "").strip(),
                "required": bool(raw_field.get("required")),
                "default_value": raw_field.get("default_value"),
                "validation": validation,
                "options": [str(option).strip() for option in options if str(option).strip()],
                "conditional_logic": conditional_logic,
                "is_private": bool(raw_field.get("is_private") or raw_field.get("private")),
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


def _normalize_deadline_days(value):
    raw_value = str(value or "").strip()
    if not raw_value:
        return None
    try:
        deadline_days = int(raw_value)
    except (TypeError, ValueError):
        raise ValueError("Deadline days must be a whole number.")
    if deadline_days <= 0:
        raise ValueError("Deadline days must be greater than zero.")
    if deadline_days > 3650:
        raise ValueError("Deadline days must be 3650 days or fewer.")
    return deadline_days


def _parse_assignment_reviewer(reviewer_type, reviewer_value):
    clean_type = str(reviewer_type or "").strip().lower()
    clean_value = " ".join(str(reviewer_value or "").split()).strip()
    if not clean_type and not clean_value:
        return "", ""
    if clean_type not in {"role", "user"}:
        raise ValueError("Assignment claim reviewer must be a role or user.")
    if not clean_value:
        raise ValueError("Assignment claim reviewer value is required.")
    return clean_type, clean_value


def _parse_promotion_rules(rules_json):
    rules = _json_loads(rules_json, [])
    parsed = []
    seen_targets = set()
    for index, raw_rule in enumerate(rules, start=1):
        if not isinstance(raw_rule, dict):
            continue
        raw_target = str(raw_rule.get("target_form_id") or "").strip()
        if not raw_target:
            continue
        if not raw_target.isdigit():
            raise ValueError(f"Promotion rule {index} must target a valid form.")
        target_form_id = int(raw_target)
        if target_form_id in seen_targets:
            raise ValueError("A promotion target can only appear once per form.")
        seen_targets.add(target_form_id)
        spawn_mode = str(raw_rule.get("spawn_mode") or "automatic").strip().lower() or "automatic"
        if spawn_mode not in PROMOTION_SPAWN_MODES:
            raise ValueError(f"Promotion rule {index} has an unsupported spawn mode.")
        parsed.append(
            {
                "target_form_id": target_form_id,
                "spawn_mode": spawn_mode,
                "default_deadline_days": _normalize_deadline_days(raw_rule.get("default_deadline_days")),
            }
        )
    return parsed


def _load_promotion_rules(connection, form_id):
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT
            r.*,
            f.form_key AS target_form_key,
            f.title AS target_form_title,
            f.status AS target_form_status
        FROM form_promotion_rules r
        INNER JOIN forms f ON f.id = r.target_form_id
        WHERE r.source_form_id = ?
        ORDER BY r.rule_order, r.id
        """,
        (form_id,),
    )
    rules = []
    for row in cursor.fetchall():
        item = dict(row)
        item["target_form_id"] = int(item["target_form_id"])
        item["default_deadline_days"] = (
            int(item["default_deadline_days"]) if item.get("default_deadline_days") not in (None, "") else None
        )
        rules.append(item)
    return rules


def _load_rule_targets(connection, form_id):
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT target_form_id
        FROM form_promotion_rules
        WHERE source_form_id = ?
        ORDER BY rule_order, id
        """,
        (form_id,),
    )
    return [int(row["target_form_id"]) for row in cursor.fetchall()]


def _validate_promotion_chain(connection, form_id, promotion_rules):
    source_form_id = int(form_id)
    pending_targets = [int(rule["target_form_id"]) for rule in (promotion_rules or [])]

    def walk(current_form_id, visited):
        targets = pending_targets if current_form_id == source_form_id else _load_rule_targets(connection, current_form_id)
        for target_form_id in targets:
            if target_form_id == source_form_id:
                raise ValueError("Promotion chain cannot loop back to this form.")
            if target_form_id in visited:
                continue
            walk(target_form_id, visited | {target_form_id})

    walk(source_form_id, {source_form_id})


def _form_row_to_dict(connection, row, include_version=True):
    item = dict(row)
    item["access_roles"] = _json_loads(item.get("access_roles_json"), [])
    item["access_users"] = _json_loads(item.get("access_users_json"), [])
    item["library_roles"] = _json_loads(item.get("library_roles_json"), [])
    item["library_users"] = _json_loads(item.get("library_users_json"), [])
    item["review_stages"] = _json_loads(item.get("review_stages_json"), [])
    item["quick_card_style"] = _json_loads(item.get("quick_card_style_json"), {})
    item["assignment_review_type"] = str(item.get("assignment_review_type") or "").strip().lower()
    item["assignment_review_value"] = str(item.get("assignment_review_value") or "").strip()
    item["allow_cancel"] = bool(item.get("allow_cancel"))
    item["allow_multiple_active"] = bool(item.get("allow_multiple_active"))
    item["requires_review"] = bool(item.get("requires_review", 1))
    item["deadline_days"] = int(item["deadline_days"]) if item.get("deadline_days") not in (None, "") else None
    item["next_form_id"] = int(item["next_form_id"]) if item.get("next_form_id") not in (None, "") else None
    item["next_form"] = None
    item["next_form_title"] = ""
    item["promotion_rules"] = _load_promotion_rules(connection, item["id"])
    item["schema"] = []
    if item["promotion_rules"]:
        first_rule = item["promotion_rules"][0]
        item["next_form_id"] = first_rule["target_form_id"]
        item["next_form"] = {
            "id": first_rule["target_form_id"],
            "form_key": first_rule.get("target_form_key") or "",
            "title": first_rule.get("target_form_title") or "",
            "status": first_rule.get("target_form_status") or "",
        }
        item["next_form_title"] = first_rule.get("target_form_title") or ""
    elif item.get("next_form_id"):
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT id, form_key, title, status
            FROM forms
            WHERE id = ?
            """,
            (item["next_form_id"],),
        )
        next_form_row = cursor.fetchone()
        if next_form_row:
            item["next_form"] = dict(next_form_row)
            item["next_form_title"] = next_form_row["title"]
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
        SELECT id, form_key, title, status
        FROM forms
        WHERE id != ?
        ORDER BY title COLLATE NOCASE
        """,
        (form["id"],),
    )
    form["available_forms"] = [dict(row) for row in cursor.fetchall()]
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
            library_roles_json,
            library_users_json,
            review_stages_json,
            created_by_username,
            updated_by_username,
            created_at,
            updated_at
        )
        VALUES (?, ?, '', ?, 'emoji', ?, ?, ?, 'draft', 1, 1, '[]', '[]', '[]', '[]', '[]', ?, ?, ?, ?)
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
    library_roles = normalize_role_names(payload.get("library_roles") or [])
    library_users = _normalize_username_list(payload.get("library_users") or [])
    requires_review = True if payload.get("requires_review") is None else bool(payload.get("requires_review"))

    try:
        schema = _parse_field_schema(payload.get("schema_json") or "[]")
        review_stages = _parse_review_stages(payload.get("review_stages_json") or "[]")
        deadline_days = _normalize_deadline_days(payload.get("deadline_days"))
        assignment_review_type, assignment_review_value = _parse_assignment_reviewer(
            payload.get("assignment_review_type"),
            payload.get("assignment_review_value"),
        )
        promotion_rules = _parse_promotion_rules(payload.get("promotion_rules_json") or "[]")
    except ValueError as error:
        return False, str(error)

    if status == "published":
        if not schema:
            return False, "Published forms must contain at least one field."
        if not access_roles:
            return False, "Published forms must have at least one access role."
        if requires_review and not review_stages:
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
    if not promotion_rules:
        raw_next_form_id = str(payload.get("next_form_id") or "").strip()
        if raw_next_form_id:
            if not raw_next_form_id.isdigit():
                connection.close()
                return False, "Select a valid promotion target."
            promotion_rules = [
                {
                    "target_form_id": int(raw_next_form_id),
                    "spawn_mode": "automatic",
                    "default_deadline_days": None,
                }
            ]

    next_form_row = None
    for rule in promotion_rules:
        if rule["target_form_id"] == current_form["id"]:
            connection.close()
            return False, "A form cannot promote to itself."
        cursor.execute(
            """
            SELECT id, form_key, title, status
            FROM forms
            WHERE id = ?
            """,
            (rule["target_form_id"],),
        )
        target_form_row = cursor.fetchone()
        if not target_form_row:
            connection.close()
            return False, "One of the promotion targets was not found."
        if status == "published" and target_form_row["status"] != "published":
            connection.close()
            return False, "Published forms can only promote into another published form."
        if next_form_row is None:
            next_form_row = target_form_row
    try:
        _validate_promotion_chain(connection, current_form["id"], promotion_rules)
    except ValueError as error:
        connection.close()
        return False, str(error)
    next_form_id = promotion_rules[0]["target_form_id"] if promotion_rules else None
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
            requires_review = ?,
            deadline_days = ?,
            next_form_id = ?,
            assignment_review_type = ?,
            assignment_review_value = ?,
            access_roles_json = ?,
            access_users_json = ?,
            library_roles_json = ?,
            library_users_json = ?,
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
            1 if requires_review else 0,
            deadline_days,
            next_form_id,
            assignment_review_type or None,
            assignment_review_value or None,
            _json_dumps(access_roles),
            _json_dumps(access_users),
            _json_dumps(library_roles),
            _json_dumps(library_users),
            _json_dumps(review_stages),
            version_id,
            actor_username,
            timestamp_now(),
            status,
            timestamp_now(),
            current_form["id"],
        ),
    )
    cursor.execute("DELETE FROM form_promotion_rules WHERE source_form_id = ?", (current_form["id"],))
    for order, rule in enumerate(promotion_rules, start=1):
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
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                current_form["id"],
                rule["target_form_id"],
                order,
                rule["spawn_mode"],
                rule["default_deadline_days"],
                timestamp_now(),
                timestamp_now(),
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
            "library_roles": library_roles,
            "library_users": library_users,
            "requires_review": requires_review,
            "deadline_days": deadline_days,
            "next_form_id": next_form_id,
            "next_form_title": next_form_row["title"] if next_form_row else "",
            "assignment_review_type": assignment_review_type,
            "assignment_review_value": assignment_review_value,
            "promotion_rule_count": len(promotion_rules),
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


def force_delete_form_template(form_key, actor_username):
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute("SELECT * FROM forms WHERE form_key = ?", ((form_key or "").strip(),))
    row = cursor.fetchone()
    if not row:
        connection.close()
        return False, "Form not found."

    form = _form_row_to_dict(connection, row, include_version=False)
    form_id = form["id"]

    cursor.execute("SELECT id, stored_name FROM form_submission_files WHERE submission_id IN (SELECT id FROM form_submissions WHERE form_id = ?)", (form_id,))
    file_rows = [dict(item) for item in cursor.fetchall()]
    stored_names = sorted({item.get("stored_name") for item in file_rows if item.get("stored_name")})

    cursor.execute("SELECT id FROM form_submissions WHERE form_id = ?", (form_id,))
    submission_ids = [row["id"] for row in cursor.fetchall()]
    if submission_ids:
        placeholders = ", ".join("?" for _ in submission_ids)
        cursor.execute(f"DELETE FROM form_review_tasks WHERE submission_id IN ({placeholders})", tuple(submission_ids))
        cursor.execute(f"DELETE FROM form_comments WHERE submission_id IN ({placeholders})", tuple(submission_ids))
        cursor.execute(f"DELETE FROM form_submission_files WHERE submission_id IN ({placeholders})", tuple(submission_ids))
        cursor.execute(
            f"DELETE FROM form_audit_log WHERE entity_type = 'submission' AND entity_id IN ({placeholders})",
            tuple(submission_ids),
        )
        cursor.execute(f"DELETE FROM form_submissions WHERE id IN ({placeholders})", tuple(submission_ids))

    cursor.execute("DELETE FROM form_promotion_rules WHERE source_form_id = ? OR target_form_id = ?", (form_id, form_id))
    cursor.execute("UPDATE forms SET next_form_id = NULL WHERE next_form_id = ?", (form_id,))
    cursor.execute("DELETE FROM form_versions WHERE form_id = ?", (form_id,))
    cursor.execute("DELETE FROM form_audit_log WHERE entity_type = 'form' AND entity_id = ?", (form_id,))
    cursor.execute("DELETE FROM forms WHERE id = ?", (form_id,))

    cursor.execute(
        """
        DELETE FROM workflow_cases
        WHERE id IN (
            SELECT wc.id
            FROM workflow_cases wc
            LEFT JOIN form_submissions s ON s.case_id = wc.id
            GROUP BY wc.id
            HAVING COUNT(s.id) = 0
        )
        """
    )

    icon_value = str(form.get("quick_icon_value") or "").strip()
    icon_path = ""
    if form.get("quick_icon_type") == "image" and icon_value:
        icon_path = os.path.join(os.path.dirname(FORM_ICON_DIR), os.path.basename(icon_value)) if "\\" not in icon_value and "/" not in icon_value else ""
        if not icon_path:
            normalized = icon_value.replace("/", os.sep).replace("\\", os.sep)
            root_dir = os.path.dirname(os.path.dirname(FORM_ICON_DIR))
            icon_path = os.path.join(root_dir, normalized)

    _audit(connection, "form.force-deleted", actor_username, "form", form_id, payload={"form_key": form_key, "submission_count": len(submission_ids)})
    connection.commit()
    connection.close()

    for stored_name in stored_names:
        path = os.path.join(FORM_FILE_DIR, stored_name)
        if os.path.exists(path):
            os.remove(path)
    if icon_path and os.path.exists(icon_path):
        os.remove(icon_path)
    return True, "Form force deleted."


def get_workflow_topbar_counts(username, role_names):
    username = (username or "").strip()
    if not username:
        return {"my_requests": 0, "review_queue": 0}
    normalized_roles = {role.casefold() for role in (role_names or [])}
    last_my_requests_viewed_at = get_workflow_queue_last_viewed_at(username, "my_requests")
    last_review_queue_viewed_at = get_workflow_queue_last_viewed_at(username, "review_queue")
    connection = connect_db()
    cursor = connection.cursor()
    if last_my_requests_viewed_at:
        cursor.execute(
            """
            SELECT COUNT(*) AS total
            FROM form_submissions
            WHERE (owner_username = ? OR requester_username = ?)
              AND status != 'archived'
              AND datetime(updated_at) > datetime(?)
            """,
            (username, username, last_my_requests_viewed_at),
        )
    else:
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
        if last_review_queue_viewed_at:
            cursor.execute(
                f"""
                SELECT COUNT(*) AS total
                FROM form_review_tasks
                WHERE is_active = 1
                  AND task_status = 'pending'
                  AND datetime(COALESCE(updated_at, created_at)) > datetime(?)
                  AND (
                        (reviewer_type = 'user' AND lower(reviewer_value) = lower(?))
                        OR (reviewer_type = 'role' AND lower(reviewer_value) IN ({role_placeholders}))
                  )
                """,
                (last_review_queue_viewed_at, username, *normalized_roles),
            )
        else:
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
        if last_review_queue_viewed_at:
            cursor.execute(
                """
                SELECT COUNT(*) AS total
                FROM form_review_tasks
                WHERE is_active = 1
                  AND task_status = 'pending'
                  AND datetime(COALESCE(updated_at, created_at)) > datetime(?)
                  AND reviewer_type = 'user'
                  AND lower(reviewer_value) = lower(?)
                """,
                (last_review_queue_viewed_at, username),
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
    if last_review_queue_viewed_at:
        cursor.execute(
            """
            SELECT assignment_review_type, assignment_review_value
            FROM form_submissions
            WHERE status = 'pending_assignment'
              AND datetime(updated_at) > datetime(?)
            """,
            (last_review_queue_viewed_at,),
        )
    else:
        cursor.execute(
            """
            SELECT assignment_review_type, assignment_review_value
            FROM form_submissions
            WHERE status = 'pending_assignment'
            """
        )
    assignment_queue = 0
    for row in cursor.fetchall():
        reviewer_type = str(row["assignment_review_type"] or "").strip().lower()
        reviewer_value = str(row["assignment_review_value"] or "").strip().casefold()
        if {"admin", "superadmin", "developer"} & normalized_roles:
            assignment_queue += 1
            continue
        if reviewer_type == "user" and reviewer_value == username.casefold():
            assignment_queue += 1
        elif reviewer_type == "role" and reviewer_value in normalized_roles:
            assignment_queue += 1
    connection.close()
    return {"my_requests": my_requests, "review_queue": review_queue + assignment_queue}


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


def _user_matches_form_submit_access(form, username, role_names):
    return _user_matches_form_access(form, username, role_names)


def _user_matches_form_library_access(form, username, role_names):
    library_roles = {role.casefold() for role in (form.get("library_roles") or [])}
    library_users = {item.casefold() for item in (form.get("library_users") or [])}
    current_roles = {role.casefold() for role in (role_names or [])}
    username_key = (username or "").casefold()
    if library_users and username_key in library_users:
        return True
    if library_roles and library_roles & current_roles:
        return True
    return False


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
