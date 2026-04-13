import os
import re

from werkzeug.utils import secure_filename

from logic import connect_db, get_initials, get_profile_identity_map, normalize_role_names, timestamp_now
from split_app.workflow.common import (
    ALLOWED_FORM_DOCUMENT_EXTENSIONS,
    ALLOWED_FORM_IMAGE_EXTENSIONS,
    FIELD_TYPES,
    FORM_FILE_DIR,
    FORM_STATUSES,
    MAX_FORM_DOCUMENT_COUNT,
    MAX_FORM_FILE_SIZE_BYTES,
    MAX_FORM_IMAGE_COUNT,
    SUBMISSION_STATUSES,
    _audit,
    _field_key,
    _is_truthy,
    _json_dumps,
    _json_loads,
    _notify_users,
    _resolve_fullname,
    _role_members,
    _serialize_note,
    ensure_form_workflow_folders,
)
from split_app.workflow.templates import _form_row_to_dict, _user_matches_form_access


DATE_FIELD_TYPES = {"date", "calendar"}


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
        FROM form_comments
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


def _get_form_map(connection, form_ids):
    clean_ids = sorted({int(form_id) for form_id in (form_ids or []) if form_id})
    if not clean_ids:
        return {}
    cursor = connection.cursor()
    placeholders = ", ".join("?" for _ in clean_ids)
    cursor.execute(f"SELECT * FROM forms WHERE id IN ({placeholders})", tuple(clean_ids))
    return {row["id"]: _form_row_to_dict(connection, row) for row in cursor.fetchall()}


def _get_form_version_map(connection, form_version_ids):
    clean_ids = sorted({int(version_id) for version_id in (form_version_ids or []) if version_id})
    if not clean_ids:
        return {}
    cursor = connection.cursor()
    placeholders = ", ".join("?" for _ in clean_ids)
    cursor.execute(
        f"""
        SELECT id, version_number, schema_json, created_by_username, created_at
        FROM form_versions
        WHERE id IN ({placeholders})
        """,
        tuple(clean_ids),
    )
    versions = {}
    for row in cursor.fetchall():
        item = dict(row)
        item["schema"] = _json_loads(item.get("schema_json"), [])
        versions[item["id"]] = item
    return versions


def _get_submission_file_map(connection, submission_ids):
    clean_ids = sorted({int(submission_id) for submission_id in (submission_ids or []) if submission_id})
    if not clean_ids:
        return {}
    cursor = connection.cursor()
    placeholders = ", ".join("?" for _ in clean_ids)
    cursor.execute(
        f"""
        SELECT *
        FROM form_submission_files
        WHERE submission_id IN ({placeholders})
        ORDER BY created_at, id
        """,
        tuple(clean_ids),
    )
    file_map = {}
    for row in cursor.fetchall():
        file_map.setdefault(row["submission_id"], []).append(dict(row))
    return file_map


def _resolve_submission_schema(form, submission, version_map=None):
    version = (version_map or {}).get(submission.get("form_version_id"))
    if version:
        return version.get("schema") or [], version
    current_version = form.get("current_version") or {}
    if current_version and current_version.get("id") == submission.get("form_version_id"):
        return form.get("schema") or [], current_version
    return form.get("schema") or [], current_version or None


def _get_submission_schema(connection, form, submission):
    version_map = _get_form_version_map(connection, [submission.get("form_version_id")])
    return _resolve_submission_schema(form, submission, version_map)


def _preview_text(value, limit=72):
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _format_submission_field_value(field, value, files=None):
    field_type = field.get("type")
    if field_type in {"image_upload", "file_upload"}:
        total = len(files or [])
        if total <= 0:
            return ""
        noun = "image" if field_type == "image_upload" else "file"
        return f"{total} {noun}{'' if total == 1 else 's'}"
    if field_type == "checkbox":
        return "Yes" if value else ""
    return str(value or "").strip()


def _build_submission_preview_rows(schema, values, file_groups, limit=3):
    detail_rows = []
    for field in _visible_fields(schema, values):
        files = file_groups.get(field["key"]) or []
        display_value = _format_submission_field_value(field, values.get(field["key"]), files)
        if not display_value and not files:
            continue
        detail_rows.append(
            {
                "label": field.get("label") or field.get("key") or "Field",
                "value": display_value,
                "preview_value": _preview_text(display_value, limit=60),
                "field_type": field.get("type") or "short_text",
                "is_multiline": field.get("type") == "long_text",
                "files": files,
            }
        )
    return detail_rows[:limit], detail_rows


def _enrich_submission_rows(connection, submission_rows):
    if not submission_rows:
        return []
    form_map = _get_form_map(connection, [item.get("form_id") for item in submission_rows])
    version_map = _get_form_version_map(connection, [item.get("form_version_id") for item in submission_rows])
    file_map = _get_submission_file_map(connection, [item.get("id") for item in submission_rows])
    for item in submission_rows:
        item["data"] = _json_loads(item.get("data_json"), {})
        item["files"] = file_map.get(item["id"], [])
        item["file_groups"] = _submission_file_groups(item["files"])
        form = form_map.get(item.get("form_id")) or {"schema": [], "current_version": None}
        schema, schema_version = _resolve_submission_schema(form, item, version_map)
        preview_rows, detail_rows = _build_submission_preview_rows(schema, item["data"], item["file_groups"])
        item["preview_rows"] = preview_rows
        item["detail_rows"] = detail_rows
        item["schema_version"] = schema_version
        item["schema_version_number"] = (schema_version or {}).get("version_number")
    return submission_rows


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
        if field_type in DATE_FIELD_TYPES and value not in (None, ""):
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(value)):
                errors.append(f"{field['label']} must use YYYY-MM-DD.")
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
        SELECT
            id,
            form_id,
            form_version_id,
            tracking_number,
            status,
            data_json,
            submitted_at,
            updated_at,
            created_at
        FROM form_submissions
        WHERE form_id = ?
          AND (owner_username = ? OR requester_username = ?)
        ORDER BY
            CASE status
                WHEN 'draft' THEN 0
                WHEN 'pending' THEN 1
                ELSE 2
            END,
            datetime(updated_at) DESC,
            id DESC
        """,
        (form["id"], username, username),
    )
    submissions = [dict(row) for row in cursor.fetchall()]
    _enrich_submission_rows(connection, submissions)
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

    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT id
        FROM form_submissions
        WHERE form_id = ?
          AND owner_username = ?
          AND status = 'draft'
        ORDER BY datetime(updated_at) DESC, id DESC
        LIMIT 1
        """,
        (form["id"], username),
    )
    existing_draft = cursor.fetchone()
    if existing_draft:
        connection.close()
        return True, "Existing draft opened.", existing_draft["id"]

    if not form["allow_multiple_active"]:
        cursor.execute(
            """
            SELECT id
            FROM form_submissions
            WHERE form_id = ?
              AND owner_username = ?
              AND status = 'pending'
            ORDER BY datetime(updated_at) DESC, id DESC
            LIMIT 1
            """,
            (form["id"], username),
        )
        existing = cursor.fetchone()
        if existing:
            connection.close()
            return True, "Existing submission opened.", existing["id"]

    now = timestamp_now()
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
    schema, schema_version = _get_submission_schema(connection, form, submission)
    data = submission.get("data") or {}
    payload = {
        "form": form,
        "submission": submission,
        "schema": schema,
        "schema_version": schema_version,
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
    schema, _schema_version = _get_submission_schema(connection, form, submission)
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
    schema, _schema_version = _get_submission_schema(connection, form, submission)
    files_by_field = _submission_file_groups(submission.get("files"))
    values = submission.get("data") or {}
    errors = _validate_visible_fields(schema, values, files_by_field)
    if errors:
        connection.close()
        return False, " ".join(errors[:3]), None

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
    _enrich_submission_rows(connection, fetched_rows)
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
    schema, schema_version = _get_submission_schema(connection, form, submission)
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
        "schema_version": schema_version,
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


def get_manager_form_preview_context(form_key):
    connection = connect_db()
    form = _get_form_by_key(connection, form_key)
    if not form:
        connection.close()
        return False, "Form not found.", None

    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT
            s.id,
            s.form_id,
            s.form_version_id,
            s.owner_username,
            s.requester_username,
            s.tracking_number,
            s.status,
            s.data_json,
            s.created_at,
            s.updated_at,
            s.submitted_at,
            s.completed_at
        FROM form_submissions s
        WHERE s.form_id = ?
        ORDER BY datetime(s.updated_at) DESC, s.id DESC
        LIMIT 25
        """,
        (form["id"],),
    )
    submissions = [dict(row) for row in cursor.fetchall()]
    _enrich_submission_rows(connection, submissions)

    if submissions:
        identity_map = get_profile_identity_map(
            connection,
            [item["owner_username"] for item in submissions] + [item["requester_username"] for item in submissions],
            viewer_username=form.get("created_by_username") or "",
        )
        for item in submissions:
            owner_identity = identity_map.get((item.get("owner_username") or "").casefold())
            requester_identity = identity_map.get((item.get("requester_username") or "").casefold())
            item["owner_display_name"] = (owner_identity.get("display_name") if owner_identity else "") or item.get("owner_username")
            item["requester_display_name"] = (requester_identity.get("display_name") if requester_identity else "") or item.get("requester_username")

    preview_values = {}
    for field in form.get("schema") or []:
        default_value = field.get("default_value")
        if field.get("type") == "checkbox":
            preview_values[field["key"]] = default_value if isinstance(default_value, bool) else _is_truthy(default_value)
        else:
            preview_values[field["key"]] = "" if default_value is None else str(default_value)

    payload = {
        "form": form,
        "submissions": submissions,
        "preview_values": preview_values,
        "visible_preview_fields": _visible_fields(form.get("schema") or [], preview_values),
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
        INSERT INTO form_comments (
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
    connection.execute("DELETE FROM form_comments WHERE submission_id = ?", (submission_id,))
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
            INSERT INTO form_comments (
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


