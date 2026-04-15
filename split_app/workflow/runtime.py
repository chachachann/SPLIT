import os
import re
from datetime import timedelta

from werkzeug.utils import secure_filename

from logic import (
    connect_db,
    get_initials,
    get_profile_identity_map,
    get_user_roles_by_username,
    normalize_role_names,
    parse_timestamp,
    timestamp_now,
)
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
from split_app.workflow.templates import (
    _form_row_to_dict,
    _user_matches_form_library_access,
    _user_matches_form_submit_access,
)


DATE_FIELD_TYPES = {"date", "calendar"}
CASE_STATUS_ORDER = {
    "in_review": 0,
    "pending_assignment": 1,
    "assigned": 2,
    "open": 3,
    "pending": 4,
    "rejected": 5,
    "cancelled": 6,
    "completed": 7,
    "promoted": 7,
    "archived": 8,
}


def _form_requires_review(form):
    return bool(form and form.get("requires_review") and (form.get("review_stages") or []))


def _reviewer_is_actionable(connection, reviewer):
    if not isinstance(reviewer, dict):
        return False
    reviewer_type = str(reviewer.get("type") or "").strip().lower()
    reviewer_value = str(reviewer.get("value") or "").strip()
    if not reviewer_type or not reviewer_value:
        return False
    if reviewer_type == "user":
        cursor = connection.cursor()
        cursor.execute(
            "SELECT 1 FROM users WHERE lower(username) = lower(?) LIMIT 1",
            (reviewer_value,),
        )
        return bool(cursor.fetchone())
    if reviewer_type == "role":
        return bool(_role_members(connection, reviewer_value))
    return False


def _effective_review_stages(connection, form):
    if not form or not form.get("requires_review"):
        return []
    stages = []
    for raw_stage in form.get("review_stages") or []:
        if not isinstance(raw_stage, dict):
            continue
        reviewers = [
            reviewer
            for reviewer in (raw_stage.get("reviewers") or [])
            if _reviewer_is_actionable(connection, reviewer)
        ]
        if not reviewers:
            continue
        stages.append(
            {
                "name": raw_stage.get("name") or f"Stage {len(stages) + 1}",
                "mode": raw_stage.get("mode") or "sequential",
                "reviewers": reviewers,
            }
        )
    return stages


def _compute_deadline_at(form, submitted_at):
    deadline_days = form.get("deadline_days")
    if deadline_days in (None, ""):
        return None
    submitted_dt = parse_timestamp(submitted_at)
    if not submitted_dt:
        return None
    try:
        days = int(deadline_days)
    except (TypeError, ValueError):
        return None
    if days <= 0:
        return None
    return (submitted_dt + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")


def _compute_deadline_at_from_days(days, submitted_at):
    if days in (None, ""):
        return None
    submitted_dt = parse_timestamp(submitted_at)
    if not submitted_dt:
        return None
    try:
        clean_days = int(days)
    except (TypeError, ValueError):
        return None
    if clean_days <= 0:
        return None
    return (submitted_dt + timedelta(days=clean_days)).strftime("%Y-%m-%d %H:%M:%S")


def _submission_pool_roles(submission):
    return {role.casefold() for role in (_json_loads(submission.get("pool_roles_json"), []) or [])}


def _submission_pool_users(submission):
    return {user.casefold() for user in (_json_loads(submission.get("pool_users_json"), []) or [])}


def _submission_pool_allows_user(submission, username, role_names):
    pool_roles = _submission_pool_roles(submission)
    pool_users = _submission_pool_users(submission)
    role_keys = {role.casefold() for role in (role_names or [])}
    username_key = (username or "").casefold()
    if pool_roles and not (pool_roles & role_keys):
        return False
    if pool_users and username_key not in pool_users:
        return False
    return bool(pool_roles or pool_users)


def _submission_assignment_reviewer_matches(submission, username, role_names):
    username_key = (username or "").casefold()
    role_keys = {role.casefold() for role in (role_names or [])}
    if {"admin", "developer", "superadmin"} & role_keys:
        return True
    reviewer_type = str(submission.get("assignment_review_type") or "").strip().lower()
    reviewer_value = str(submission.get("assignment_review_value") or "").strip().casefold()
    if not reviewer_type or not reviewer_value:
        return False
    if reviewer_type == "user":
        return reviewer_value == username_key
    return reviewer_value in role_keys


def _submission_assignment_claimant_matches(submission, username):
    return (submission.get("assignment_requested_by_username") or "").casefold() == (username or "").casefold()


def _submission_assignment_targets(connection, submission):
    usernames = list(_submission_pool_users(submission))
    for role_name in (_json_loads(submission.get("pool_roles_json"), []) or []):
        usernames.extend(_role_members(connection, role_name))
    return sorted({item for item in usernames if item})


def _build_deadline_state(item):
    deadline_at = parse_timestamp(item.get("deadline_at"))
    if not deadline_at:
        item["deadline_state"] = ""
        item["deadline_state_label"] = ""
        return

    current_time = parse_timestamp(timestamp_now())
    resolved_at = parse_timestamp(item.get("completed_at"))
    status = str(item.get("status") or "").strip().lower()
    if status in {"completed", "promoted"} and resolved_at:
        if resolved_at <= deadline_at:
            item["deadline_state"] = "on_time"
            item["deadline_state_label"] = "On Time"
        else:
            item["deadline_state"] = "late"
            item["deadline_state_label"] = "Late"
        return

    if current_time and current_time > deadline_at:
        item["deadline_state"] = "unfinished"
        item["deadline_state_label"] = "Unfinished"
        return

    item["deadline_state"] = "due"
    item["deadline_state_label"] = "Due"


def _build_submission_lineage(item):
    labels = []
    for value in (item.get("root_form_title"), item.get("parent_form_title"), item.get("form_title")):
        clean = str(value or "").strip()
        if clean and clean not in labels:
            labels.append(clean)
    item["lineage_label"] = " -> ".join(labels)
    item["pool_label"] = (item.get("parent_form_title") or item.get("form_title") or "").strip()


def _submission_status_priority(status):
    return CASE_STATUS_ORDER.get(str(status or "").strip().lower(), 99)


def _summarize_case_status(items):
    statuses = [str(item.get("status") or "").strip().lower() for item in (items or []) if item.get("status")]
    if not statuses:
        return ""
    return sorted(statuses, key=_submission_status_priority)[0]


def _get_case_by_id(connection, case_id):
    if not case_id:
        return None
    cursor = connection.cursor()
    cursor.execute("SELECT * FROM workflow_cases WHERE id = ?", (case_id,))
    row = cursor.fetchone()
    return dict(row) if row else None


def _get_case_by_tracking_number(connection, tracking_number):
    clean_tracking_number = str(tracking_number or "").strip()
    if not clean_tracking_number:
        return None
    cursor = connection.cursor()
    cursor.execute("SELECT * FROM workflow_cases WHERE tracking_number = ?", (clean_tracking_number,))
    row = cursor.fetchone()
    return dict(row) if row else None


def _ensure_case_for_submission(connection, submission, tracking_number=None):
    if not submission:
        return None
    existing_case = _get_case_by_id(connection, submission.get("case_id"))
    if existing_case:
        return existing_case

    root_submission_id = submission.get("root_submission_id") or submission.get("id")
    root_case = None
    root_tracking_number = ""
    if root_submission_id and root_submission_id != submission.get("id"):
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT id, case_id, tracking_number, owner_username, requester_username
            FROM form_submissions
            WHERE id = ?
            """,
            (root_submission_id,),
        )
        root_row = cursor.fetchone()
        if root_row:
            root_row = dict(root_row)
            root_tracking_number = (root_row.get("tracking_number") or "").strip()
            root_case = _get_case_by_id(connection, root_row.get("case_id"))

    if root_case:
        connection.execute("UPDATE form_submissions SET case_id = ? WHERE id = ?", (root_case["id"], submission["id"]))
        submission["case_id"] = root_case["id"]
        return root_case

    case_tracking_number = (
        str(tracking_number or "").strip()
        or root_tracking_number
        or str(submission.get("tracking_number") or "").strip()
        or f"CASE-{root_submission_id or submission.get('id')}"
    )
    existing_case = _get_case_by_tracking_number(connection, case_tracking_number)
    if existing_case:
        case_id = existing_case["id"]
    else:
        created_at = submission.get("submitted_at") or submission.get("created_at") or timestamp_now()
        connection.execute(
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
                case_tracking_number,
                submission["owner_username"],
                submission["requester_username"],
                created_at,
                created_at,
                submission.get("archived_at"),
            ),
        )
        case_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
    connection.execute("UPDATE form_submissions SET case_id = ? WHERE id = ?", (case_id, submission["id"]))
    submission["case_id"] = case_id
    return _get_case_by_id(connection, case_id)


def _get_case_submission_rows(connection, case_id):
    if not case_id:
        return []
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT *
        FROM form_submissions
        WHERE case_id = ?
        ORDER BY datetime(created_at), id
        """,
        (case_id,),
    )
    return [dict(row) for row in cursor.fetchall()]


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
    item["pool_roles"] = _json_loads(item.get("pool_roles_json"), [])
    item["pool_users"] = _json_loads(item.get("pool_users_json"), [])
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
    identity_usernames = [
        item.get("owner_username"),
        item.get("requester_username"),
        item.get("assigned_to_username"),
        item.get("assignment_requested_by_username"),
    ]
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
    assignee_identity = identity_map.get((item.get("assigned_to_username") or "").casefold())
    claimant_identity = identity_map.get((item.get("assignment_requested_by_username") or "").casefold())
    item["owner_display_name"] = (owner_identity.get("display_name") if owner_identity else "") or item.get("owner_username")
    item["owner_profile_url"] = (owner_identity.get("profile_url") if owner_identity else f"/users/{item.get('owner_username')}")
    item["requester_display_name"] = (requester_identity.get("display_name") if requester_identity else "") or item.get("requester_username")
    item["requester_profile_url"] = (requester_identity.get("profile_url") if requester_identity else f"/users/{item.get('requester_username')}")
    item["assigned_to_display_name"] = (
        (assignee_identity.get("display_name") if assignee_identity else "")
        or item.get("assigned_to_username")
        or ""
    )
    item["assignment_requested_by_display_name"] = (
        (claimant_identity.get("display_name") if claimant_identity else "")
        or item.get("assignment_requested_by_username")
        or ""
    )
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


def _get_submission_task_map(connection, submission_ids):
    clean_ids = sorted({int(submission_id) for submission_id in (submission_ids or []) if submission_id})
    if not clean_ids:
        return {}
    cursor = connection.cursor()
    placeholders = ", ".join("?" for _ in clean_ids)
    cursor.execute(
        f"""
        SELECT *
        FROM form_review_tasks
        WHERE submission_id IN ({placeholders})
        ORDER BY stage_index, task_order, id
        """,
        tuple(clean_ids),
    )
    task_map = {}
    for row in cursor.fetchall():
        task_map.setdefault(row["submission_id"], []).append(dict(row))
    return task_map


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


def _build_submission_preview_rows(schema, values, file_groups, limit=3, visible_fields=None):
    detail_rows = []
    for field in (visible_fields if visible_fields is not None else _visible_fields(schema, values)):
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


def _enrich_submission_rows(connection, submission_rows, viewer_username=None, viewer_role_names=None):
    if not submission_rows:
        return []
    form_map = _get_form_map(connection, [item.get("form_id") for item in submission_rows])
    version_map = _get_form_version_map(connection, [item.get("form_version_id") for item in submission_rows])
    file_map = _get_submission_file_map(connection, [item.get("id") for item in submission_rows])
    related_submission_ids = sorted(
        {
            int(submission_id)
            for item in submission_rows
            for submission_id in (
                item.get("parent_submission_id"),
                item.get("root_submission_id"),
                item.get("promoted_to_submission_id"),
            )
            if submission_id
        }
    )
    related_map = {}
    if related_submission_ids:
        cursor = connection.cursor()
        placeholders = ", ".join("?" for _ in related_submission_ids)
        cursor.execute(
            f"""
            SELECT
                s.id,
                s.tracking_number,
                s.form_id,
                f.title AS form_title,
                f.form_key
            FROM form_submissions s
            INNER JOIN forms f ON f.id = s.form_id
            WHERE s.id IN ({placeholders})
            """,
            tuple(related_submission_ids),
        )
        related_map = {row["id"]: dict(row) for row in cursor.fetchall()}
    for item in submission_rows:
        item["data"] = _json_loads(item.get("data_json"), {})
        item["pool_roles"] = _json_loads(item.get("pool_roles_json"), [])
        item["pool_users"] = _json_loads(item.get("pool_users_json"), [])
        item["files"] = file_map.get(item["id"], [])
        item["file_groups"] = _submission_file_groups(item["files"])
        form = form_map.get(item.get("form_id")) or {"schema": [], "current_version": None}
        item["form_title"] = item.get("form_title") or form.get("title") or "Form"
        item["form_key"] = item.get("form_key") or form.get("form_key") or ""
        parent_info = related_map.get(item.get("parent_submission_id"))
        root_info = related_map.get(item.get("root_submission_id"))
        promoted_info = related_map.get(item.get("promoted_to_submission_id"))
        item["parent_form_title"] = parent_info["form_title"] if parent_info else ""
        item["parent_form_key"] = parent_info["form_key"] if parent_info else ""
        item["parent_tracking_number"] = parent_info["tracking_number"] if parent_info else ""
        item["root_form_title"] = root_info["form_title"] if root_info else ""
        item["root_form_key"] = root_info["form_key"] if root_info else ""
        item["root_tracking_number"] = root_info["tracking_number"] if root_info else ""
        item["promoted_to_form_title"] = promoted_info["form_title"] if promoted_info else ""
        item["promoted_to_form_key"] = promoted_info["form_key"] if promoted_info else ""
        item["promoted_to_tracking_number"] = promoted_info["tracking_number"] if promoted_info else ""
        item["review_required"] = _form_requires_review(form)
        item["next_form_title"] = form.get("next_form_title") or ""
        schema, schema_version = _resolve_submission_schema(form, item, version_map)
        visible_fields = _visible_fields_for_viewer(
            form,
            item,
            schema,
            item["data"],
            viewer_username,
            viewer_role_names,
        )
        filtered_file_groups = _filter_file_groups_for_viewer(
            schema,
            item["file_groups"],
            _submission_has_private_field_access(form, item, viewer_username, viewer_role_names),
        )
        item["file_groups"] = filtered_file_groups
        preview_rows, detail_rows = _build_submission_preview_rows(
            schema,
            item["data"],
            filtered_file_groups,
            visible_fields=visible_fields,
        )
        item["preview_rows"] = preview_rows
        item["detail_rows"] = detail_rows
        item["schema_version"] = schema_version
        item["schema_version_number"] = (schema_version or {}).get("version_number")
        _build_deadline_state(item)
        _build_submission_lineage(item)
    return submission_rows


def _submission_is_visible(form, submission, username, role_names):
    username_key = (username or "").casefold()
    role_keys = {role.casefold() for role in (role_names or [])}
    if submission.get("status") == "archived" and not {"admin", "developer", "superadmin"} & role_keys:
        return False
    if username_key in {
        (submission.get("owner_username") or "").casefold(),
        (submission.get("requester_username") or "").casefold(),
        (submission.get("assigned_to_username") or "").casefold(),
        (submission.get("assignment_requested_by_username") or "").casefold(),
    }:
        return True
    if {"admin", "developer", "superadmin"} & role_keys:
        return True
    submission_status = str(submission.get("status") or "").strip().lower()
    if submission_status in {"open", "pending_assignment", "assigned"} and _submission_pool_allows_user(submission, username, role_names):
        return True
    if submission_status == "pending_assignment" and _submission_assignment_reviewer_matches(submission, username, role_names):
        return True
    for task in submission.get("tasks") or []:
        reviewer_type = (task.get("reviewer_type") or "").casefold()
        reviewer_value = (task.get("reviewer_value") or "").casefold()
        if reviewer_type == "user" and reviewer_value == username_key:
            return True
        if reviewer_type == "role" and reviewer_value in role_keys:
            return True
    return _user_matches_form_library_access(form, username, role_names)


def _submission_can_edit(submission, username):
    username_key = (username or "").casefold()
    status = str(submission.get("status") or "").strip().lower()
    if status == "draft":
        return (submission.get("owner_username") or "").casefold() == username_key
    if status == "assigned":
        return (submission.get("assigned_to_username") or submission.get("owner_username") or "").casefold() == username_key
    return False


def _submission_can_admin_delete_pending(submission, role_names):
    role_keys = {role.casefold() for role in (role_names or [])}
    return submission.get("status") == "pending" and bool({"admin", "superadmin", "developer"} & role_keys)


def _submission_can_developer_archive(submission, role_names):
    role_keys = {role.casefold() for role in (role_names or [])}
    return submission.get("status") in {"completed", "rejected", "cancelled", "promoted"} and bool({"admin", "superadmin", "developer"} & role_keys)


def _submission_can_developer_delete_archived(submission, role_names):
    role_keys = {role.casefold() for role in (role_names or [])}
    return submission.get("status") == "archived" and bool({"admin", "superadmin", "developer"} & role_keys)


def _submission_can_comment(form, submission, username, role_names):
    username_key = (username or "").casefold()
    role_keys = {role.casefold() for role in (role_names or [])}
    if username_key in {
        (submission.get("owner_username") or "").casefold(),
        (submission.get("requester_username") or "").casefold(),
        (submission.get("assigned_to_username") or "").casefold(),
    }:
        return True
    if {"admin", "developer", "superadmin"} & role_keys:
        return True
    if str(submission.get("status") or "").strip().lower() in {"open", "pending_assignment", "assigned"} and _submission_pool_allows_user(submission, username, role_names):
        return True
    if str(submission.get("status") or "").strip().lower() == "pending_assignment" and _submission_assignment_reviewer_matches(submission, username, role_names):
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


def _submission_can_take(submission, username, role_names):
    return str(submission.get("status") or "").strip().lower() == "open" and _submission_pool_allows_user(submission, username, role_names)


def _submission_can_review_assignment(submission, username, role_names):
    return str(submission.get("status") or "").strip().lower() == "pending_assignment" and _submission_assignment_reviewer_matches(submission, username, role_names)


def _submission_can_reopen_to_pool(submission, username, role_names):
    return str(submission.get("status") or "").strip().lower() in {"assigned", "pending_assignment"} and _submission_assignment_reviewer_matches(submission, username, role_names)


def _submission_can_reassign(submission, username, role_names):
    return str(submission.get("status") or "").strip().lower() in {"open", "assigned", "pending_assignment"} and _submission_assignment_reviewer_matches(submission, username, role_names)


def _user_matches_submission_pool(submission, target_username):
    target_roles = get_user_roles_by_username(target_username)
    return _submission_pool_allows_user(submission, target_username, target_roles)


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


def _field_is_private(field):
    return bool(field.get("is_private") or field.get("private"))


def _submission_has_private_field_access(form, submission, username, role_names):
    username_key = (username or "").casefold()
    role_keys = {role.casefold() for role in (role_names or [])}
    if not username_key and not role_keys:
        return True
    if username_key in {
        (submission.get("owner_username") or "").casefold(),
        (submission.get("requester_username") or "").casefold(),
        (submission.get("assigned_to_username") or "").casefold(),
        (submission.get("assignment_requested_by_username") or "").casefold(),
    }:
        return True
    if {"admin", "developer", "superadmin"} & role_keys:
        return True
    submission_status = str(submission.get("status") or "").strip().lower()
    if submission_status in {"open", "pending_assignment", "assigned"} and _submission_pool_allows_user(submission, username, role_names):
        return True
    if submission_status == "pending_assignment" and _submission_assignment_reviewer_matches(submission, username, role_names):
        return True
    for task in submission.get("tasks") or []:
        reviewer_type = (task.get("reviewer_type") or "").casefold()
        reviewer_value = (task.get("reviewer_value") or "").casefold()
        if reviewer_type == "user" and reviewer_value == username_key:
            return True
        if reviewer_type == "role" and reviewer_value in role_keys:
            return True
    return False


def _visible_fields_for_viewer(form, submission, schema, values, username=None, role_names=None):
    visible_fields = _visible_fields(schema, values)
    if _submission_has_private_field_access(form, submission, username, role_names):
        return visible_fields
    return [field for field in visible_fields if not _field_is_private(field)]


def _filter_file_groups_for_viewer(schema, file_groups, can_view_private):
    if can_view_private:
        return dict(file_groups or {})
    field_map = {field.get("key"): field for field in (schema or []) if field.get("key")}
    filtered_groups = {}
    for field_key, files in (file_groups or {}).items():
        field = field_map.get(field_key)
        if field and _field_is_private(field):
            continue
        filtered_groups[field_key] = files
    return filtered_groups


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
    if form["status"] != "published" or not _user_matches_form_submit_access(form, username, role_names):
        connection.close()
        return False, "You do not have access to this form.", None
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT s.*
        FROM form_submissions s
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
    for item in submissions:
        item["is_editable"] = _submission_can_edit(item, username)
    connection.close()
    return True, "", {"form": form, "submissions": submissions}


def start_form_draft(form_key, username, role_names):
    connection = connect_db()
    form = _get_form_by_key(connection, form_key)
    if not form:
        connection.close()
        return False, "Form not found.", None
    if form["status"] != "published" or not _user_matches_form_submit_access(form, username, role_names):
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


def _get_form_by_id(connection, form_id):
    if not form_id:
        return None
    cursor = connection.cursor()
    cursor.execute("SELECT * FROM forms WHERE id = ?", (form_id,))
    row = cursor.fetchone()
    return _form_row_to_dict(connection, row) if row else None


def _field_default_value(field):
    default_value = field.get("default_value")
    if default_value is None:
        return None
    if field.get("type") == "checkbox":
        return default_value if isinstance(default_value, bool) else _is_truthy(default_value)
    value = str(default_value).strip()
    return value if value else None


def _build_promoted_values(source_form, source_submission, target_form, source_schema):
    hidden_keys = {
        field.get("key")
        for field in source_schema or []
        if field.get("hide_on_promotion") and field.get("key")
    }
    values = {
        key: value
        for key, value in (source_submission.get("data") or {}).items()
        if key not in hidden_keys
    }
    for field in target_form.get("schema") or []:
        if field.get("key") in values:
            continue
        default_value = _field_default_value(field)
        if default_value is not None:
            values[field["key"]] = default_value
    return values, hidden_keys


def _copy_promoted_files(connection, source_submission_id, target_submission_id, hidden_keys):
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT
            field_key,
            original_name,
            stored_name,
            file_ext,
            mime_type,
            file_size_bytes,
            file_kind,
            uploaded_by_username,
            created_at
        FROM form_submission_files
        WHERE submission_id = ?
        ORDER BY created_at, id
        """,
        (source_submission_id,),
    )
    for row in cursor.fetchall():
        if row["field_key"] in hidden_keys:
            continue
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
                target_submission_id,
                row["field_key"],
                row["original_name"],
                row["stored_name"],
                row["file_ext"],
                row["mime_type"],
                row["file_size_bytes"],
                row["file_kind"],
                row["uploaded_by_username"],
                row["created_at"],
            ),
        )


def _resolve_promotion_rules(form, selected_rule_ids=None):
    rules = list(form.get("promotion_rules") or [])
    if not rules:
        return []
    if not selected_rule_ids:
        automatic_rules = [rule for rule in rules if str(rule.get("spawn_mode") or "automatic").strip().lower() == "automatic"]
        return automatic_rules or rules
    selected_ids = {int(rule_id) for rule_id in (selected_rule_ids or []) if str(rule_id).isdigit()}
    return [rule for rule in rules if int(rule.get("id") or 0) in selected_ids]


def _finalize_submission(connection, form, submission, actor_username, actor_fullname, note="", selected_promotion_rule_ids=None):
    resolved_at = timestamp_now()
    promotion_rules = _resolve_promotion_rules(form, selected_promotion_rule_ids)

    if promotion_rules:
        created_children = []
        for rule in promotion_rules:
            target_form = _get_form_by_id(connection, rule.get("target_form_id"))
            if not target_form or target_form.get("status") != "published":
                continue
            child_submission_id, child_message = _create_promoted_submission(
                connection,
                form,
                submission,
                target_form,
                actor_username,
                actor_fullname,
                note=note,
                promotion_rule=rule,
            )
            created_children.append(
                {
                    "submission_id": child_submission_id,
                    "message": child_message,
                    "target_form": target_form,
                }
            )
        if created_children:
            first_child = created_children[0]
            promoted_targets = [
                {
                    "target_form_key": item["target_form"].get("form_key"),
                    "target_submission_id": item["submission_id"],
                }
                for item in created_children
            ]
            child_titles = ", ".join(item["target_form"].get("title") or "Form" for item in created_children[:3])
            if len(created_children) > 3:
                child_titles += ", ..."
            primary_message = first_child["message"] or f"Submission promoted to {first_child['target_form'].get('title') or 'the next form'}."
        else:
            first_child = None
            promoted_targets = []
            child_titles = ""
            primary_message = ""

    else:
        created_children = []
        first_child = None
        promoted_targets = []
        child_titles = ""
        primary_message = ""

    if first_child:
        connection.execute(
            """
            UPDATE form_submissions
            SET
                status = 'promoted',
                promoted_to_submission_id = ?,
                updated_at = ?,
                completed_at = ?,
                acceptance_note = ?
            WHERE id = ?
            """,
            (first_child["submission_id"], resolved_at, resolved_at, note or None, submission["id"]),
        )
        _audit(
            connection,
            "submission.promoted",
            actor_username,
            "submission",
            submission["id"],
            tracking_number=submission.get("tracking_number"),
            payload={"targets": promoted_targets},
        )
        _notify_users(
            connection,
            [submission["owner_username"]],
            f"Promoted: {form['title']}",
            f"{submission.get('tracking_number') or ('Submission #' + str(submission['id']))} moved into {child_titles or 'the next workflow tabs'}.",
            link_url=f"/forms/submissions/{submission['id']}",
            style_key="info",
            sender_name=(actor_fullname or "").strip() or actor_username,
        )
        return "promoted", primary_message or f"Submission promoted into {child_titles or 'new workflow tabs'}."

    connection.execute(
        """
        UPDATE form_submissions
        SET status = 'completed', completed_at = ?, updated_at = ?, acceptance_note = ?
        WHERE id = ?
        """,
        (resolved_at, resolved_at, note or None, submission["id"]),
    )
    _audit(
        connection,
        "submission.completed",
        actor_username,
        "submission",
        submission["id"],
        tracking_number=submission.get("tracking_number"),
    )
    _notify_users(
        connection,
        [submission["owner_username"]],
        f"Completed: {form['title']}",
        f"{submission.get('tracking_number') or ('Submission #' + str(submission['id']))} was completed.",
        link_url=f"/forms/submissions/{submission['id']}",
        style_key="success",
        sender_name=(actor_fullname or "").strip() or actor_username,
    )
    return "completed", "Submission completed."


def _create_promoted_submission(connection, source_form, source_submission, target_form, actor_username, actor_fullname, note="", promotion_rule=None):
    submitted_at = timestamp_now()
    source_schema, _ = _get_submission_schema(connection, source_form, source_submission)
    values, hidden_keys = _build_promoted_values(source_form, source_submission, target_form, source_schema)
    tracking_number = _allocate_tracking_number(connection, target_form["tracking_prefix"])
    deadline_at = _compute_deadline_at_from_days((promotion_rule or {}).get("default_deadline_days"), submitted_at) or _compute_deadline_at(target_form, submitted_at)
    root_submission_id = source_submission.get("root_submission_id") or source_submission.get("id")
    case = _ensure_case_for_submission(connection, source_submission, source_submission.get("tracking_number"))
    pool_roles = list(target_form.get("access_roles") or [])
    pool_users = list(target_form.get("access_users") or [])
    cursor = connection.cursor()
    cursor.execute(
        """
        INSERT INTO form_submissions (
            case_id,
            form_id,
            form_version_id,
            owner_username,
            requester_username,
            parent_submission_id,
            root_submission_id,
            tracking_number,
            tracking_prefix,
            status,
            data_json,
            pool_roles_json,
            pool_users_json,
            assignment_review_type,
            assignment_review_value,
            created_at,
            updated_at,
            submitted_at,
            deadline_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            (case or {}).get("id"),
            target_form["id"],
            target_form["current_version_id"],
            source_submission["requester_username"],
            source_submission["requester_username"],
            source_submission["id"],
            root_submission_id,
            tracking_number,
            target_form["tracking_prefix"],
            "open",
            _json_dumps(values),
            _json_dumps(pool_roles),
            _json_dumps(pool_users),
            (target_form.get("assignment_review_type") or "").strip() or None,
            (target_form.get("assignment_review_value") or "").strip() or None,
            submitted_at,
            submitted_at,
            submitted_at,
            deadline_at,
        ),
    )
    child_submission_id = cursor.lastrowid
    _copy_promoted_files(connection, source_submission["id"], child_submission_id, hidden_keys)
    _audit(
        connection,
        "submission.promoted-created",
        actor_username,
        "submission",
        child_submission_id,
        tracking_number=tracking_number,
        payload={
            "source_submission_id": source_submission["id"],
            "source_form_key": source_form.get("form_key"),
            "target_form_key": target_form.get("form_key"),
            "spawn_mode": (promotion_rule or {}).get("spawn_mode") or "automatic",
        },
    )
    _audit(
        connection,
        "submission.submitted",
        actor_username,
        "submission",
        child_submission_id,
        tracking_number=tracking_number,
        payload={"promoted_from_submission_id": source_submission["id"]},
    )
    pool_targets = _submission_assignment_targets(connection, {"pool_roles_json": _json_dumps(pool_roles), "pool_users_json": _json_dumps(pool_users)})
    if pool_targets:
        _notify_users(
            connection,
            pool_targets,
            f"Open Task: {target_form['title']}",
            f"{(case or {}).get('tracking_number') or tracking_number} has a new open workflow tab waiting in the pool.",
            link_url=f"/forms/submissions/{child_submission_id}",
            style_key="warning",
            sender_name=(actor_fullname or "").strip() or actor_username,
        )
    _notify_users(
        connection,
        [source_submission["requester_username"]],
        f"Promoted: {target_form['title']}",
        f"{(case or {}).get('tracking_number') or tracking_number} added a new workflow tab for {target_form['title']}.",
        link_url=f"/forms/cases/{(case or {}).get('tracking_number') or source_submission.get('tracking_number')}",
        style_key="info",
        sender_name=(actor_fullname or "").strip() or actor_username,
    )
    return child_submission_id, f"Submission promoted to {target_form['title']} and opened in the pool."


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
    if form.get("status") != "published":
        connection.close()
        return False, "Only published forms can be submitted.", None
    schema, _schema_version = _get_submission_schema(connection, form, submission)
    files_by_field = _submission_file_groups(submission.get("files"))
    values = submission.get("data") or {}
    errors = _validate_visible_fields(schema, values, files_by_field)
    if errors:
        connection.close()
        return False, " ".join(errors[:3]), None

    stages = _effective_review_stages(connection, form)
    requires_review = bool(stages)
    tracking_number = submission.get("tracking_number") or _allocate_tracking_number(connection, form["tracking_prefix"])
    submitted_at = submission.get("submitted_at") or timestamp_now()
    deadline_at = _compute_deadline_at(form, submitted_at)
    case = _ensure_case_for_submission(connection, submission, tracking_number)
    connection.execute("DELETE FROM form_review_tasks WHERE submission_id = ?", (submission_id,))
    connection.execute(
        """
        UPDATE form_submissions
        SET
            case_id = ?,
            tracking_number = ?,
            tracking_prefix = ?,
            submitted_at = COALESCE(submitted_at, ?),
            status = ?,
            updated_at = ?,
            current_stage_index = ?,
            current_task_order = ?,
            cancel_reason = NULL,
            reject_reason = NULL,
            acceptance_note = NULL,
            promoted_to_submission_id = NULL,
            completed_at = NULL,
            deadline_at = ?
        WHERE id = ?
        """,
        (
            (case or {}).get("id"),
            tracking_number,
            form["tracking_prefix"],
            submitted_at,
            "pending" if requires_review else "draft",
            submitted_at,
            0,
            1 if requires_review else 0,
            deadline_at,
            submission_id,
        ),
    )
    _audit(connection, "submission.submitted", username, "submission", submission_id, tracking_number=tracking_number)

    if requires_review:
        _create_stage_tasks(connection, submission_id, stages, 0)
        _notify_stage_reviewers(connection, form, submission_id, stages, 0)
        _notify_users(
            connection,
            [submission["owner_username"]],
            f"Submitted: {form['title']}",
            f"Tracking number {tracking_number} is now pending review.",
            link_url=f"/forms/submissions/{submission_id}",
            style_key="success",
        )
        final_message = "Submission sent for review."
    else:
        refreshed_submission = _get_submission(connection, submission_id)
        _status, final_message = _finalize_submission(
            connection,
            form,
            refreshed_submission,
            username,
            "",
            note="",
        )

    connection.commit()
    updated = _get_submission(connection, submission_id)
    connection.close()
    return True, final_message, updated


def _assignment_reviewer_notification_targets(connection, submission):
    reviewer_type = str(submission.get("assignment_review_type") or "").strip().lower()
    reviewer_value = str(submission.get("assignment_review_value") or "").strip()
    if not reviewer_type or not reviewer_value:
        return []
    if reviewer_type == "user":
        return [reviewer_value]
    return _role_members(connection, reviewer_value)


def take_submission(submission_id, username, role_names, note=""):
    connection = connect_db()
    form, submission, message = _ensure_submission_access(connection, submission_id, username, role_names)
    if not form:
        connection.close()
        return False, message
    if not _submission_can_take(submission, username, role_names):
        connection.close()
        return False, "This workflow tab is not open to your current user or roles."

    acted_at = timestamp_now()
    note_text = str(note or "").strip()
    if submission.get("assignment_review_type") and submission.get("assignment_review_value"):
        connection.execute(
            """
            UPDATE form_submissions
            SET
                status = 'pending_assignment',
                assignment_requested_by_username = ?,
                assignment_requested_at = ?,
                assignment_note = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (username, acted_at, note_text or None, acted_at, submission_id),
        )
        _audit(
            connection,
            "submission.assignment-requested",
            username,
            "submission",
            submission_id,
            tracking_number=submission.get("tracking_number"),
            payload={"requested_by": username},
        )
        approvers = _assignment_reviewer_notification_targets(connection, submission)
        if approvers:
            _notify_users(
                connection,
                approvers,
                f"Assignment approval needed: {form['title']}",
                f"{submission.get('tracking_number') or ('Submission #' + str(submission_id))} is waiting for assignment approval.",
                link_url=f"/forms/submissions/{submission_id}",
                style_key="warning",
                sender_name=username,
            )
        connection.commit()
        connection.close()
        return True, "Assignment request sent."

    connection.execute(
        """
        UPDATE form_submissions
        SET
            status = 'assigned',
            owner_username = ?,
            assigned_to_username = ?,
            assignment_requested_by_username = NULL,
            assignment_requested_at = NULL,
            assignment_note = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (username, username, note_text or None, acted_at, submission_id),
    )
    _audit(
        connection,
        "submission.assigned",
        username,
        "submission",
        submission_id,
        tracking_number=submission.get("tracking_number"),
        payload={"assigned_to": username},
    )
    _notify_users(
        connection,
        [username, submission.get("requester_username")],
        f"Assigned: {form['title']}",
        f"{submission.get('tracking_number') or ('Submission #' + str(submission_id))} is now assigned to {username}.",
        link_url=f"/forms/submissions/{submission_id}",
        style_key="info",
        sender_name=username,
    )
    connection.commit()
    connection.close()
    return True, "Form assigned to you."


def review_assignment_request(submission_id, username, fullname, role_names, action, note=""):
    clean_action = str(action or "").strip().lower()
    clean_note = str(note or "").strip()
    if clean_action not in {"approve", "reject"}:
        return False, "Unsupported assignment action."

    connection = connect_db()
    form, submission, message = _ensure_submission_access(connection, submission_id, username, role_names)
    if not form:
        connection.close()
        return False, message
    if not _submission_can_review_assignment(submission, username, role_names):
        connection.close()
        return False, "You are not allowed to review this assignment request."
    requested_by = (submission.get("assignment_requested_by_username") or "").strip()
    if not requested_by:
        connection.close()
        return False, "This submission does not have a pending claimant."

    acted_at = timestamp_now()
    if clean_action == "approve":
        connection.execute(
            """
            UPDATE form_submissions
            SET
                status = 'assigned',
                owner_username = ?,
                assigned_to_username = ?,
                assignment_note = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (requested_by, requested_by, clean_note or None, acted_at, submission_id),
        )
        _audit(
            connection,
            "submission.assignment-approved",
            username,
            "submission",
            submission_id,
            tracking_number=submission.get("tracking_number"),
            payload={"assigned_to": requested_by},
        )
        _notify_users(
            connection,
            [requested_by, submission.get("requester_username")],
            f"Assignment approved: {form['title']}",
            f"{submission.get('tracking_number') or ('Submission #' + str(submission_id))} is now assigned to {requested_by}.",
            link_url=f"/forms/submissions/{submission_id}",
            style_key="success",
            sender_name=(fullname or "").strip() or username,
        )
        connection.commit()
        connection.close()
        return True, "Assignment approved."

    connection.execute(
        """
        UPDATE form_submissions
        SET
            status = 'open',
            owner_username = requester_username,
            assigned_to_username = NULL,
            assignment_requested_by_username = NULL,
            assignment_requested_at = NULL,
            assignment_note = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (clean_note or None, acted_at, submission_id),
    )
    _audit(
        connection,
        "submission.assignment-rejected",
        username,
        "submission",
        submission_id,
        tracking_number=submission.get("tracking_number"),
        payload={"reason": clean_note},
    )
    _notify_users(
        connection,
        [requested_by],
        f"Assignment rejected: {form['title']}",
        f"{submission.get('tracking_number') or ('Submission #' + str(submission_id))} returned to the open pool.",
        link_url=f"/forms/submissions/{submission_id}",
        style_key="warning",
        sender_name=(fullname or "").strip() or username,
    )
    connection.commit()
    connection.close()
    return True, "Assignment rejected and returned to the pool."


def reopen_submission_to_pool(submission_id, username, role_names):
    connection = connect_db()
    form, submission, message = _ensure_submission_access(connection, submission_id, username, role_names)
    if not form:
        connection.close()
        return False, message
    if not _submission_can_reopen_to_pool(submission, username, role_names):
        connection.close()
        return False, "You cannot reopen this workflow tab to the pool."
    acted_at = timestamp_now()
    connection.execute(
        """
        UPDATE form_submissions
        SET
            status = 'open',
            owner_username = requester_username,
            assigned_to_username = NULL,
            assignment_requested_by_username = NULL,
            assignment_requested_at = NULL,
            assignment_note = NULL,
            updated_at = ?
        WHERE id = ?
        """,
        (acted_at, submission_id),
    )
    _audit(
        connection,
        "submission.reopened-to-pool",
        username,
        "submission",
        submission_id,
        tracking_number=submission.get("tracking_number"),
    )
    pool_targets = _submission_assignment_targets(connection, submission)
    if pool_targets:
        _notify_users(
            connection,
            pool_targets,
            f"Open Task: {form['title']}",
            f"{submission.get('tracking_number') or ('Submission #' + str(submission_id))} returned to the open pool.",
            link_url=f"/forms/submissions/{submission_id}",
            style_key="warning",
            sender_name=username,
        )
    connection.commit()
    connection.close()
    return True, "Workflow tab reopened to the pool."


def reassign_submission(submission_id, username, role_names, assignee_username):
    target_username = " ".join(str(assignee_username or "").split()).strip()
    if not target_username:
        return False, "Enter the username to assign this workflow tab to."

    connection = connect_db()
    form, submission, message = _ensure_submission_access(connection, submission_id, username, role_names)
    if not form:
        connection.close()
        return False, message
    if not _submission_can_reassign(submission, username, role_names):
        connection.close()
        return False, "You cannot reassign this workflow tab."
    if not _user_matches_submission_pool(submission, target_username):
        connection.close()
        return False, "The selected user is not part of this workflow tab's pool."

    acted_at = timestamp_now()
    connection.execute(
        """
        UPDATE form_submissions
        SET
            status = 'assigned',
            owner_username = ?,
            assigned_to_username = ?,
            assignment_requested_by_username = NULL,
            assignment_requested_at = NULL,
            assignment_note = NULL,
            updated_at = ?
        WHERE id = ?
        """,
        (target_username, target_username, acted_at, submission_id),
    )
    _audit(
        connection,
        "submission.reassigned",
        username,
        "submission",
        submission_id,
        tracking_number=submission.get("tracking_number"),
        payload={"assigned_to": target_username},
    )
    _notify_users(
        connection,
        [target_username, submission.get("requester_username")],
        f"Assigned: {form['title']}",
        f"{submission.get('tracking_number') or ('Submission #' + str(submission_id))} is now assigned to {target_username}.",
        link_url=f"/forms/submissions/{submission_id}",
        style_key="info",
        sender_name=username,
    )
    connection.commit()
    connection.close()
    return True, "Workflow tab reassigned."


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
        item["is_editable"] = _submission_can_edit(item, username)
        owner_identity = identity_map.get((item.get("owner_username") or "").casefold())
        requester_identity = identity_map.get((item.get("requester_username") or "").casefold())
        item["owner_display_name"] = (owner_identity.get("display_name") if owner_identity else "") or item.get("owner_username")
        item["requester_display_name"] = (requester_identity.get("display_name") if requester_identity else "") or item.get("requester_username")
        items.append(item)
    connection.close()
    return items


def get_submission_library(username, role_names, status_filter="active", form_filter="", sort_by="updated"):
    connection = connect_db()
    cursor = connection.cursor()
    role_keys = {role.casefold() for role in (role_names or [])}
    can_view_archived = bool({"admin", "superadmin", "developer"} & role_keys)
    where_clauses = ["s.status != 'draft'"]
    params = []
    if status_filter == "archived":
        if not can_view_archived:
            connection.close()
            return []
        where_clauses.append("s.status = 'archived'")
    elif status_filter == "all":
        if not can_view_archived:
            where_clauses.append("s.status != 'archived'")
    else:
        where_clauses.append("s.status != 'archived'")
    if form_filter:
        where_clauses.append("(lower(f.form_key) LIKE lower(?) OR lower(f.title) LIKE lower(?))")
        like_value = f"%{form_filter}%"
        params.extend([like_value, like_value])

    if sort_by == "submitted":
        order_clause = "datetime(s.submitted_at) DESC, datetime(s.updated_at) DESC, s.id DESC"
    elif sort_by == "deadline":
        order_clause = (
            "CASE WHEN s.deadline_at IS NULL THEN 1 ELSE 0 END, "
            "datetime(s.deadline_at) ASC, datetime(s.updated_at) DESC, s.id DESC"
        )
    elif sort_by == "status":
        order_clause = (
            "CASE s.status "
            "WHEN 'pending' THEN 0 "
            "WHEN 'promoted' THEN 1 "
            "WHEN 'completed' THEN 2 "
            "WHEN 'rejected' THEN 3 "
            "WHEN 'cancelled' THEN 4 "
            "WHEN 'archived' THEN 5 "
            "ELSE 6 END, "
            "datetime(s.updated_at) DESC, s.id DESC"
        )
    else:
        order_clause = "datetime(s.updated_at) DESC, s.id DESC"

    cursor.execute(
        f"""
        SELECT
            s.*,
            f.title AS form_title,
            f.form_key
        FROM form_submissions s
        INNER JOIN forms f ON f.id = s.form_id
        WHERE {' AND '.join(where_clauses)}
        ORDER BY {order_clause}
        """,
        tuple(params),
    )
    items = [dict(row) for row in cursor.fetchall()]
    task_map = _get_submission_task_map(connection, [item.get("id") for item in items])
    for item in items:
        item["tasks"] = task_map.get(item["id"], [])
    _enrich_submission_rows(connection, items, viewer_username=username, viewer_role_names=role_names)
    form_map = _get_form_map(connection, [item.get("form_id") for item in items])
    visible_items = []
    for item in items:
        if item.get("status") == "archived" and not can_view_archived:
            continue
        form = form_map.get(item.get("form_id")) or {}
        if not _submission_is_visible(form, item, username, role_names):
            continue
        visible_items.append(item)
    identity_map = get_profile_identity_map(
        connection,
        [item["owner_username"] for item in visible_items] + [item["requester_username"] for item in visible_items],
        viewer_username=username,
    )
    for item in visible_items:
        owner_identity = identity_map.get((item.get("owner_username") or "").casefold())
        requester_identity = identity_map.get((item.get("requester_username") or "").casefold())
        item["owner_display_name"] = (owner_identity.get("display_name") if owner_identity else "") or item.get("owner_username")
        item["requester_display_name"] = (requester_identity.get("display_name") if requester_identity else "") or item.get("requester_username")
        item["can_admin_delete_pending"] = _submission_can_admin_delete_pending(item, role_names)
        item["can_archive_submission"] = _submission_can_developer_archive(item, role_names)
        item["can_delete_archived_submission"] = _submission_can_developer_delete_archived(item, role_names)
    connection.close()
    return visible_items


def get_case_library(username, role_names, status_filter="active", template_filter="", sort_by="updated"):
    connection = connect_db()
    cursor = connection.cursor()
    role_keys = {role.casefold() for role in (role_names or [])}
    can_view_archived = bool({"admin", "superadmin", "developer"} & role_keys)
    where_clauses = ["s.status != 'draft'"]
    params = []
    if status_filter == "archived":
        if not can_view_archived:
            connection.close()
            return []
        where_clauses.append("wc.archived_at IS NOT NULL")
    elif status_filter == "all":
        if not can_view_archived:
            where_clauses.append("wc.archived_at IS NULL")
    else:
        where_clauses.append("wc.archived_at IS NULL")
    if template_filter:
        where_clauses.append("(lower(f.form_key) LIKE lower(?) OR lower(f.title) LIKE lower(?))")
        like_value = f"%{template_filter}%"
        params.extend([like_value, like_value])

    cursor.execute(
        f"""
        SELECT
            s.*,
            f.title AS form_title,
            f.form_key,
            wc.tracking_number AS case_tracking_number,
            wc.created_at AS case_created_at,
            wc.updated_at AS case_updated_at,
            wc.archived_at AS case_archived_at
        FROM form_submissions s
        INNER JOIN forms f ON f.id = s.form_id
        LEFT JOIN workflow_cases wc ON wc.id = s.case_id
        WHERE {' AND '.join(where_clauses)}
        ORDER BY datetime(s.updated_at) DESC, s.id DESC
        """,
        tuple(params),
    )
    rows = [dict(row) for row in cursor.fetchall()]
    task_map = _get_submission_task_map(connection, [row.get("id") for row in rows])
    for row in rows:
        row["tasks"] = task_map.get(row["id"], [])
    _enrich_submission_rows(connection, rows, viewer_username=username, viewer_role_names=role_names)
    form_map = _get_form_map(connection, [row.get("form_id") for row in rows])
    visible_rows = []
    for row in rows:
        form = form_map.get(row.get("form_id")) or {}
        if _submission_is_visible(form, row, username, role_names):
            visible_rows.append(row)

    identity_map = get_profile_identity_map(
        connection,
        [item["owner_username"] for item in visible_rows] + [item["requester_username"] for item in visible_rows],
        viewer_username=username,
    )
    grouped_cases = {}
    active_case_statuses = {"pending", "draft", "open", "assigned", "pending_assignment", "in_review"}
    for row in visible_rows:
        owner_identity = identity_map.get((row.get("owner_username") or "").casefold())
        requester_identity = identity_map.get((row.get("requester_username") or "").casefold())
        row["owner_display_name"] = (owner_identity.get("display_name") if owner_identity else "") or row.get("owner_username")
        row["requester_display_name"] = (requester_identity.get("display_name") if requester_identity else "") or row.get("requester_username")

        case_key = row.get("case_id") or f"submission:{row['id']}"
        case_item = grouped_cases.setdefault(
            case_key,
            {
                "case_id": row.get("case_id"),
                "tracking_number": row.get("case_tracking_number") or row.get("tracking_number") or f"Case {row['id']}",
                "created_at": row.get("case_created_at") or row.get("submitted_at") or row.get("created_at"),
                "updated_at": row.get("case_updated_at") or row.get("updated_at") or row.get("created_at"),
                "archived_at": row.get("case_archived_at"),
                "requester_display_name": row.get("requester_display_name"),
                "owner_display_name": row.get("owner_display_name"),
                "rows": [],
                "tabs": [],
                "template_titles": [],
            },
        )
        case_item["rows"].append(row)
        case_item["tabs"].append(
            {
                "submission_id": row["id"],
                "form_title": row.get("form_title") or "Form",
                "form_key": row.get("form_key") or "",
                "status": row.get("status") or "",
                "updated_at": row.get("updated_at") or "",
            }
        )
        if row.get("form_title") and row["form_title"] not in case_item["template_titles"]:
            case_item["template_titles"].append(row["form_title"])
        if (row.get("updated_at") or "") > (case_item.get("updated_at") or ""):
            case_item["updated_at"] = row.get("updated_at")

    case_items = []
    for case_item in grouped_cases.values():
        rows_in_case = case_item.pop("rows")
        rows_in_case.sort(key=lambda item: ((item.get("created_at") or ""), int(item.get("id") or 0)))
        case_item["tabs"].sort(key=lambda item: (item.get("updated_at") or "", item.get("submission_id") or 0), reverse=True)
        case_item["summary_status"] = _summarize_case_status(rows_in_case)
        case_item["summary_status_label"] = case_item["summary_status"].replace("_", " ").title() if case_item["summary_status"] else "Unknown"
        case_item["tab_count"] = len(rows_in_case)
        case_item["primary_submission_id"] = case_item["tabs"][0]["submission_id"] if case_item["tabs"] else None
        latest_row = sorted(
            rows_in_case,
            key=lambda item: (_submission_status_priority(item.get("status")), item.get("updated_at") or "", item.get("id") or 0),
        )[0]
        case_item["preview_rows"] = latest_row.get("preview_rows") or []
        case_item["lineage_label"] = latest_row.get("lineage_label") or ""
        case_item["pool_label"] = latest_row.get("pool_label") or ""
        case_item["deadline_at"] = latest_row.get("deadline_at") or ""
        case_item["deadline_state"] = latest_row.get("deadline_state") or ""
        case_item["deadline_state_label"] = latest_row.get("deadline_state_label") or ""
        case_item["template_summary"] = ", ".join(case_item["template_titles"][:3])
        case_item["can_archive_case"] = bool({"admin", "superadmin", "developer"} & role_keys) and not case_item.get("archived_at") and not any(
            str(item.get("status") or "").strip().lower() in active_case_statuses for item in rows_in_case
        )
        case_item["can_delete_archived_case"] = bool({"admin", "superadmin", "developer"} & role_keys) and all(
            str(item.get("status") or "").strip().lower() == "archived" for item in rows_in_case
        )
        case_items.append(case_item)

    if sort_by == "submitted":
        case_items.sort(key=lambda item: (item.get("created_at") or "", item.get("updated_at") or ""), reverse=True)
    elif sort_by == "deadline":
        case_items.sort(key=lambda item: (item.get("deadline_at") in {"", None}, item.get("deadline_at") or "", item.get("updated_at") or ""))
    elif sort_by == "status":
        case_items.sort(key=lambda item: (_submission_status_priority(item.get("summary_status")), -(int(item.get("primary_submission_id") or 0))))
    else:
        case_items.sort(key=lambda item: (item.get("updated_at") or "", item.get("created_at") or ""), reverse=True)
    connection.close()
    return case_items


def get_case_detail_context(case_tracking_number, username, role_names, selected_submission_id=None):
    connection = connect_db()
    case = _get_case_by_tracking_number(connection, case_tracking_number)
    if not case:
        connection.close()
        return False, "Case not found.", None

    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT
            s.*,
            f.title AS form_title,
            f.form_key
        FROM form_submissions s
        INNER JOIN forms f ON f.id = s.form_id
        WHERE s.case_id = ?
        ORDER BY datetime(s.created_at), s.id
        """,
        (case["id"],),
    )
    rows = [dict(row) for row in cursor.fetchall()]
    _enrich_submission_rows(connection, rows)
    task_map = _get_submission_task_map(connection, [row.get("id") for row in rows])
    form_map = _get_form_map(connection, [row.get("form_id") for row in rows])
    visible_rows = []
    for row in rows:
        row["tasks"] = task_map.get(row["id"], [])
        form = form_map.get(row.get("form_id")) or {}
        if _submission_is_visible(form, row, username, role_names):
            visible_rows.append(row)
    connection.close()

    if not visible_rows:
        return False, "You do not have access to this case.", None

    visible_ids = {item["id"] for item in visible_rows}
    selected_id = None
    if selected_submission_id:
        try:
            requested_id = int(selected_submission_id)
        except (TypeError, ValueError):
            requested_id = None
        if requested_id in visible_ids:
            selected_id = requested_id
    if not selected_id:
        selected_id = sorted(visible_rows, key=lambda item: (item.get("updated_at") or "", item.get("id") or 0), reverse=True)[0]["id"]

    ok, message, detail_payload = get_submission_detail_context(selected_id, username, role_names)
    if not ok:
        return False, message, None

    active_case_statuses = {"pending", "draft", "open", "assigned", "pending_assignment", "in_review"}
    tabs = [
        {
            "submission_id": item["id"],
            "form_title": item.get("form_title") or "Form",
            "form_key": item.get("form_key") or "",
            "status": item.get("status") or "",
            "updated_at": item.get("updated_at") or "",
        }
        for item in visible_rows
    ]
    tabs.sort(key=lambda item: (item.get("updated_at") or "", item.get("submission_id") or 0), reverse=True)
    detail_payload["can_archive_submission"] = bool({"admin", "superadmin", "developer"} & {role.casefold() for role in (role_names or [])}) and not case.get("archived_at") and not any(
        str(item.get("status") or "").strip().lower() in active_case_statuses for item in rows
    )
    detail_payload["can_delete_archived_submission"] = bool({"admin", "superadmin", "developer"} & {role.casefold() for role in (role_names or [])}) and bool(rows) and all(
        str(item.get("status") or "").strip().lower() == "archived" for item in rows
    )
    detail_payload["case"] = {
        "id": case["id"],
        "tracking_number": case["tracking_number"],
        "created_at": case.get("created_at") or "",
        "updated_at": case.get("updated_at") or "",
        "archived_at": case.get("archived_at") or "",
        "summary_status": _summarize_case_status(visible_rows),
        "summary_status_label": _summarize_case_status(visible_rows).replace("_", " ").title() if visible_rows else "",
    }
    detail_payload["tabs"] = tabs
    detail_payload["selected_tab_id"] = selected_id
    return True, "", detail_payload


def get_quick_access_work_items(username, role_names):
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT
            s.*,
            f.title AS form_title,
            f.form_key,
            f.quick_label,
            f.quick_icon_type,
            f.quick_icon_value,
            f.quick_card_style_json,
            wc.tracking_number AS case_tracking_number
        FROM form_submissions s
        INNER JOIN forms f ON f.id = s.form_id
        LEFT JOIN workflow_cases wc ON wc.id = s.case_id
        WHERE s.status IN ('open', 'pending_assignment', 'assigned')
        ORDER BY
            CASE s.status
                WHEN 'assigned' THEN 0
                WHEN 'pending_assignment' THEN 1
                ELSE 2
            END,
            datetime(s.updated_at) DESC,
            s.id DESC
        """
    )
    rows = [dict(row) for row in cursor.fetchall()]
    _enrich_submission_rows(connection, rows)
    form_map = _get_form_map(connection, [row.get("form_id") for row in rows])
    items = []
    for row in rows:
        form = form_map.get(row.get("form_id")) or {}
        status = str(row.get("status") or "").strip().lower()
        if status == "open" and not _submission_pool_allows_user(row, username, role_names):
            continue
        if status == "assigned" and not (
            (row.get("assigned_to_username") or row.get("owner_username") or "").casefold() == (username or "").casefold()
            or _submission_pool_allows_user(row, username, role_names)
        ):
            continue
        if status == "pending_assignment" and not (
            _submission_assignment_claimant_matches(row, username)
            or _submission_assignment_reviewer_matches(row, username, role_names)
        ):
            continue
        if not _submission_is_visible(form, row, username, role_names):
            continue
        items.append(
            {
                "card_kind": "work_item",
                "id": row["id"],
                "quick_label": row.get("quick_label") or row.get("form_title") or "Task",
                "title": row.get("form_title") or "Workflow Task",
                "note": f"{row.get('case_tracking_number') or row.get('tracking_number') or ('Submission #' + str(row['id']))} • {status.replace('_', ' ').title()}",
                "href": f"/forms/submissions/{row['id']}/edit" if status == "assigned" and _submission_can_edit(row, username) else f"/forms/submissions/{row['id']}",
                "quick_icon_type": row.get("quick_icon_type") or "text",
                "quick_icon_value": row.get("quick_icon_value") or "WF",
                "quick_card_style": _json_loads(row.get("quick_card_style_json"), {}),
                "status": status,
                "status_label": status.replace("_", " ").title(),
                "tracking_number": row.get("case_tracking_number") or row.get("tracking_number") or "",
            }
        )
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
                s.deadline_at,
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
                s.deadline_at,
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
    cursor.execute(
        """
        SELECT
            s.id AS submission_id,
            s.status AS submission_status,
            s.tracking_number,
            s.owner_username,
            s.requester_username,
            s.assignment_requested_by_username,
            s.assignment_review_type,
            s.assignment_review_value,
            s.deadline_at,
            s.updated_at,
            f.title AS form_title,
            f.form_key,
            wc.tracking_number AS case_tracking_number
        FROM form_submissions s
        INNER JOIN forms f ON f.id = s.form_id
        LEFT JOIN workflow_cases wc ON wc.id = s.case_id
        WHERE s.status = 'pending_assignment'
        ORDER BY datetime(s.updated_at) DESC, s.id DESC
        """
    )
    assignment_items = []
    for row in cursor.fetchall():
        item = dict(row)
        if not _submission_assignment_reviewer_matches(item, username, role_names):
            continue
        item["queue_kind"] = "assignment"
        item["is_actionable"] = True
        item["tracking_number"] = item.get("case_tracking_number") or item.get("tracking_number")
        items.append(item)
        assignment_items.append(item)
    identity_map = get_profile_identity_map(
        connection,
        [item["owner_username"] for item in items]
        + [item["requester_username"] for item in items]
        + [item.get("assignment_requested_by_username") for item in assignment_items],
        viewer_username=username,
    )
    for item in items:
        if item.get("queue_kind") == "assignment":
            claimant_identity = identity_map.get((item.get("assignment_requested_by_username") or "").casefold())
            owner_identity = identity_map.get((item.get("owner_username") or "").casefold())
            requester_identity = identity_map.get((item.get("requester_username") or "").casefold())
            item["owner_display_name"] = (owner_identity.get("display_name") if owner_identity else "") or item.get("owner_username")
            item["requester_display_name"] = (requester_identity.get("display_name") if requester_identity else "") or item.get("requester_username")
            item["assignment_requested_by_display_name"] = (
                (claimant_identity.get("display_name") if claimant_identity else "")
                or item.get("assignment_requested_by_username")
                or ""
            )
            _build_deadline_state(item)
            continue
        item["is_actionable"] = bool(item.get("is_active")) and item.get("task_status") == "pending"
        _build_deadline_state(item)
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
    can_view_private_fields = _submission_has_private_field_access(form, submission, username, role_names)
    file_groups = _filter_file_groups_for_viewer(
        schema,
        _submission_file_groups(submission.get("files")),
        can_view_private_fields,
    )
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
    submission["form_title"] = form.get("title") or "Form"
    submission["form_key"] = form.get("form_key") or ""
    related_submission_ids = sorted(
        {
            int(submission_id_value)
            for submission_id_value in (
                submission.get("parent_submission_id"),
                submission.get("root_submission_id"),
                submission.get("promoted_to_submission_id"),
            )
            if submission_id_value
        }
    )
    related_map = {}
    if related_submission_ids:
        cursor = connection.cursor()
        placeholders = ", ".join("?" for _ in related_submission_ids)
        cursor.execute(
            f"""
            SELECT
                s.id,
                s.tracking_number,
                f.title AS form_title,
                f.form_key
            FROM form_submissions s
            INNER JOIN forms f ON f.id = s.form_id
            WHERE s.id IN ({placeholders})
            """,
            tuple(related_submission_ids),
        )
        related_map = {row["id"]: dict(row) for row in cursor.fetchall()}
    parent_info = related_map.get(submission.get("parent_submission_id"))
    root_info = related_map.get(submission.get("root_submission_id"))
    promoted_info = related_map.get(submission.get("promoted_to_submission_id"))
    submission["parent_form_title"] = parent_info["form_title"] if parent_info else ""
    submission["parent_form_key"] = parent_info["form_key"] if parent_info else ""
    submission["parent_tracking_number"] = parent_info["tracking_number"] if parent_info else ""
    submission["root_form_title"] = root_info["form_title"] if root_info else ""
    submission["root_form_key"] = root_info["form_key"] if root_info else ""
    submission["root_tracking_number"] = root_info["tracking_number"] if root_info else ""
    submission["promoted_to_form_title"] = promoted_info["form_title"] if promoted_info else ""
    submission["promoted_to_form_key"] = promoted_info["form_key"] if promoted_info else ""
    submission["promoted_to_tracking_number"] = promoted_info["tracking_number"] if promoted_info else ""
    _build_deadline_state(submission)
    _build_submission_lineage(submission)
    payload = {
        "form": form,
        "submission": submission,
        "schema": schema,
        "schema_version": schema_version,
        "visible_fields": _visible_fields_for_viewer(form, submission, schema, submission.get("data") or {}, username, role_names),
        "file_groups": file_groups,
        "can_view_private_fields": can_view_private_fields,
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
        "can_admin_delete_pending": _submission_can_admin_delete_pending(submission, role_names),
        "can_archive_submission": _submission_can_developer_archive(submission, role_names),
        "can_delete_archived_submission": _submission_can_developer_delete_archived(submission, role_names),
        "can_edit": _submission_can_edit(submission, username),
        "can_comment": _submission_can_comment(form, submission, username, role_names),
        "can_take_submission": _submission_can_take(submission, username, role_names),
        "can_review_assignment": _submission_can_review_assignment(submission, username, role_names),
        "can_reopen_to_pool": _submission_can_reopen_to_pool(submission, username, role_names),
        "can_reassign_submission": _submission_can_reassign(submission, username, role_names),
        "promotion_rules": form.get("promotion_rules") or [],
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
            s.*
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
            promoted_to_submission_id = NULL,
            current_stage_index = 0,
            current_task_order = 0,
            submitted_at = NULL,
            deadline_at = NULL,
            completed_at = NULL,
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


def admin_delete_pending_submission(submission_id, username, role_names):
    connection = connect_db()
    form, submission, message = _ensure_submission_access(connection, submission_id, username, role_names)
    if not form:
        connection.close()
        return False, message
    if not _submission_can_admin_delete_pending(submission, role_names):
        connection.close()
        return False, "Only admins can delete pending submissions."

    for file_row in submission.get("files") or []:
        path = os.path.join(FORM_FILE_DIR, file_row["stored_name"])
        if os.path.exists(path):
            os.remove(path)
    _audit(
        connection,
        "submission.pending-deleted",
        username,
        "submission",
        submission_id,
        tracking_number=submission.get("tracking_number"),
        payload={"status": submission.get("status")},
    )
    connection.execute("DELETE FROM form_submission_files WHERE submission_id = ?", (submission_id,))
    connection.execute("DELETE FROM form_review_tasks WHERE submission_id = ?", (submission_id,))
    connection.execute("DELETE FROM form_comments WHERE submission_id = ?", (submission_id,))
    connection.execute("DELETE FROM form_audit_log WHERE entity_type = 'submission' AND entity_id = ?", (submission_id,))
    connection.execute("DELETE FROM form_submissions WHERE id = ?", (submission_id,))
    connection.commit()
    connection.close()
    return True, "Pending submission deleted."


def archive_submission(submission_id, username, role_names):
    connection = connect_db()
    form, submission, message = _ensure_submission_access(connection, submission_id, username, role_names)
    if not form:
        connection.close()
        return False, message
    if not _submission_can_developer_archive(submission, role_names):
        connection.close()
        return False, "Only developers and regional admins can archive resolved submissions."
    case = _ensure_case_for_submission(connection, submission, submission.get("tracking_number"))
    case_submissions = _get_case_submission_rows(connection, (case or {}).get("id"))
    active_statuses = {"pending", "draft", "open", "assigned", "pending_assignment", "in_review"}
    if any(str(item.get("status") or "").strip().lower() in active_statuses for item in case_submissions):
        connection.close()
        return False, "Pending cases cannot be archived."
    archived_at = timestamp_now()
    connection.execute(
        """
        UPDATE workflow_cases
        SET archived_at = ?, updated_at = ?
        WHERE id = ?
        """,
        (archived_at, archived_at, (case or {}).get("id")),
    )
    connection.execute(
        """
        UPDATE form_submissions
        SET status = 'archived', archived_at = ?, updated_at = ?
        WHERE case_id = ?
        """,
        (archived_at, archived_at, (case or {}).get("id")),
    )
    connection.execute(
        """
        UPDATE form_review_tasks
        SET is_active = 0
        WHERE submission_id IN (
            SELECT id
            FROM form_submissions
            WHERE case_id = ?
        )
        """,
        ((case or {}).get("id"),),
    )
    _audit(
        connection,
        "case.archived",
        username,
        "case",
        (case or {}).get("id"),
        tracking_number=(case or {}).get("tracking_number") or submission.get("tracking_number"),
        payload={"submission_ids": [item["id"] for item in case_submissions]},
    )
    connection.commit()
    connection.close()
    return True, "Case archived."


def developer_delete_archived_submission(submission_id, username, role_names):
    connection = connect_db()
    form, submission, message = _ensure_submission_access(connection, submission_id, username, role_names)
    if not form:
        connection.close()
        return False, message
    if not _submission_can_developer_delete_archived(submission, role_names):
        connection.close()
        return False, "Only developers and regional admins can permanently delete archived submissions."
    case = _ensure_case_for_submission(connection, submission, submission.get("tracking_number"))
    case_submissions = [_get_submission(connection, item["id"]) for item in _get_case_submission_rows(connection, (case or {}).get("id"))]
    if any(item and item.get("status") != "archived" for item in case_submissions):
        connection.close()
        return False, "Only archived cases can be permanently deleted."

    for case_submission in case_submissions:
        for file_row in (case_submission or {}).get("files") or []:
            path = os.path.join(FORM_FILE_DIR, file_row["stored_name"])
            if os.path.exists(path):
                os.remove(path)
    _audit(
        connection,
        "case.archived-deleted",
        username,
        "case",
        (case or {}).get("id"),
        tracking_number=(case or {}).get("tracking_number") or submission.get("tracking_number"),
    )
    connection.execute(
        """
        DELETE FROM form_submission_files
        WHERE submission_id IN (
            SELECT id
            FROM form_submissions
            WHERE case_id = ?
        )
        """,
        ((case or {}).get("id"),),
    )
    connection.execute(
        """
        DELETE FROM form_review_tasks
        WHERE submission_id IN (
            SELECT id
            FROM form_submissions
            WHERE case_id = ?
        )
        """,
        ((case or {}).get("id"),),
    )
    connection.execute(
        """
        DELETE FROM form_comments
        WHERE submission_id IN (
            SELECT id
            FROM form_submissions
            WHERE case_id = ?
        )
        """,
        ((case or {}).get("id"),),
    )
    connection.execute(
        """
        DELETE FROM form_audit_log
        WHERE
            (entity_type = 'submission' AND entity_id IN (
                SELECT id
                FROM form_submissions
                WHERE case_id = ?
            ))
            OR (entity_type = 'case' AND entity_id = ?)
        """,
        ((case or {}).get("id"), (case or {}).get("id")),
    )
    connection.execute("DELETE FROM form_submissions WHERE case_id = ?", ((case or {}).get("id"),))
    connection.execute("DELETE FROM workflow_cases WHERE id = ?", ((case or {}).get("id"),))
    connection.commit()
    connection.close()
    return True, "Archived case deleted."


def review_submission_action(submission_id, task_id, username, fullname, role_names, action, note, selected_promotion_rule_ids=None):
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

    stages = _effective_review_stages(connection, form)
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
        response_message = "Review recorded."
        if all(item["task_status"] == "approved" for item in stage_tasks):
            next_stage_index = stage_index + 1
            if next_stage_index >= len(stages):
                submission["completed_at"] = acted_at
                status, response_message = _finalize_submission(
                    connection,
                    form,
                    submission,
                    username,
                    fullname,
                    note=note,
                    selected_promotion_rule_ids=selected_promotion_rule_ids,
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
                response_message = "Submission moved to the next review stage."
        _audit(connection, "submission.approved-step", username, "submission", submission_id, tracking_number=submission.get("tracking_number"), payload={"stage_index": stage_index})
        connection.commit()
        connection.close()
        return True, response_message

    next_pending = None
    for item in stage_tasks:
        if item["task_status"] == "pending":
            next_pending = item
            break
    response_message = "Review recorded."
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
        response_message = "Review recorded. Next reviewer notified."
    else:
        next_stage_index = stage_index + 1
        if next_stage_index >= len(stages):
            submission["completed_at"] = acted_at
            _status, response_message = _finalize_submission(
                connection,
                form,
                submission,
                username,
                fullname,
                note=note,
                selected_promotion_rule_ids=selected_promotion_rule_ids,
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
            response_message = "Submission moved to the next review stage."
    _audit(connection, "submission.approved-step", username, "submission", submission_id, tracking_number=submission.get("tracking_number"), payload={"stage_index": stage_index})
    connection.commit()
    connection.close()
    return True, response_message


