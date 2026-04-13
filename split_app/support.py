from datetime import datetime
from functools import wraps
import os

from flask import abort, current_app, redirect, request, session, url_for
from werkzeug.utils import secure_filename

from split_app.services.chat_auth import (
    consume_remember_me_token,
    get_user_identity,
    get_user_roles_by_username,
    mark_user_presence,
)
from split_app.services.content import get_notifications_for_user
from split_app.services.core import (
    ALLOWED_CHAT_ATTACHMENT_EXTENSIONS,
    ALLOWED_IMAGE_EXTENSIONS,
    CHAT_ATTACHMENT_DIR,
    MAX_CHAT_ATTACHMENT_SIZE_BYTES,
    REMEMBER_ME_DAYS,
    ensure_chat_attachment_folder,
)
from split_app.services.profiles import (
    get_profile_notifications_for_user,
    get_profile_request_counts,
)
from split_app.workflow.common import get_form_notifications_for_user
from split_app.workflow.templates import get_workflow_topbar_counts


def get_remember_cookie_name():
    return current_app.config["REMEMBER_COOKIE_NAME"]


def get_remember_me_days():
    return current_app.config.get("REMEMBER_ME_DAYS", REMEMBER_ME_DAYS)


def start_user_session(user, persistent=False):
    session.clear()
    session["user"] = user["username"]
    session["fullname"] = user.get("display_name") or user.get("fullname") or user["username"]
    session["display_name"] = user.get("display_name") or user.get("fullname") or user["username"]
    session["profile_full_name"] = user.get("full_name") or ""
    session["designation"] = user.get("designation") or ""
    session["avatar_url"] = user.get("avatar_url") or ""
    session["avatar_initials"] = user.get("avatar_initials") or ""
    session["theme_preference"] = user.get("theme_preference") or "dark"
    session["login_time"] = datetime.now().isoformat()
    session.permanent = bool(persistent)
    session.modified = True


def refresh_user_session_identity(username=None):
    target_username = username or session.get("user")
    if not target_username:
        return

    user = get_user_identity(target_username)
    if not user:
        return

    session["user"] = user["username"]
    session["fullname"] = user.get("display_name") or user.get("fullname") or user["username"]
    session["display_name"] = user.get("display_name") or user.get("fullname") or user["username"]
    session["profile_full_name"] = user.get("full_name") or ""
    session["designation"] = user.get("designation") or ""
    session["avatar_url"] = user.get("avatar_url") or ""
    session["avatar_initials"] = user.get("avatar_initials") or ""
    session["theme_preference"] = user.get("theme_preference") or session.get("theme_preference") or "dark"
    session.modified = True


def restore_remembered_session():
    if "user" in session:
        return

    remember_cookie = request.cookies.get(get_remember_cookie_name())
    remembered_username = consume_remember_me_token(remember_cookie)
    if not remembered_username:
        return

    user = get_user_identity(remembered_username)
    if user:
        start_user_session(user, persistent=True)
        mark_user_presence(user["username"], source="remembered-session")


def get_current_roles():
    if "user" not in session:
        return []
    return get_user_roles_by_username(session.get("user"))


def is_superadmin():
    return any(role.casefold() == "superadmin" for role in get_current_roles())


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped_view


def superadmin_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        if not is_superadmin():
            abort(403)
        return view(*args, **kwargs)

    return wrapped_view


def admin_or_developer_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))

        current_roles = get_current_roles()
        has_access = any(role.casefold() in {"superadmin", "developer"} for role in current_roles)
        if not has_access:
            abort(403)
        return view(*args, **kwargs)

    return wrapped_view


def get_topbar_notifications():
    current_roles = get_current_roles()
    items = get_notifications_for_user(session.get("user"), current_roles, session.get("fullname"))
    items.extend(get_form_notifications_for_user(session.get("user")))
    items.extend(get_profile_notifications_for_user(session.get("user")))
    items.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    unread_count = sum(1 for item in items if not item.get("is_read"))
    return items, unread_count


def get_combined_workflow_counts(current_roles=None):
    if "user" not in session:
        return {"my_requests": 0, "review_queue": 0}

    resolved_roles = current_roles if current_roles is not None else get_current_roles()
    workflow_counts = get_workflow_topbar_counts(session.get("user"), resolved_roles)
    profile_counts = get_profile_request_counts(session.get("user"), resolved_roles)
    return {
        "my_requests": int(workflow_counts.get("my_requests") or 0) + int(profile_counts.get("my_requests") or 0),
        "review_queue": int(workflow_counts.get("review_queue") or 0) + int(profile_counts.get("review_queue") or 0),
    }


def inject_shell_context():
    return {
        "current_theme": session.get("theme_preference", "dark"),
        "current_avatar_url": session.get("avatar_url", ""),
        "current_avatar_initials": session.get("avatar_initials", ""),
        "current_display_name": session.get("fullname", ""),
        "current_username": session.get("user", ""),
    }


def save_chat_attachment(upload):
    if not upload or not upload.filename:
        return True, "", None

    ensure_chat_attachment_folder()
    filename = secure_filename(upload.filename)
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_CHAT_ATTACHMENT_EXTENSIONS:
        return False, "Unsupported attachment type.", None

    try:
        upload.stream.seek(0, os.SEEK_END)
        file_size = upload.stream.tell()
        upload.stream.seek(0)
    except (AttributeError, OSError):
        file_size = None

    if file_size is not None and file_size > MAX_CHAT_ATTACHMENT_SIZE_BYTES:
        max_size_mb = MAX_CHAT_ATTACHMENT_SIZE_BYTES // (1024 * 1024)
        return False, f"Attachments must be {max_size_mb} MB or smaller.", None

    stem = os.path.splitext(filename)[0] or "attachment"
    candidate = filename
    suffix = 2
    while os.path.exists(os.path.join(CHAT_ATTACHMENT_DIR, candidate)):
        candidate = f"{stem}-{suffix}{ext}"
        suffix += 1

    upload.save(os.path.join(CHAT_ATTACHMENT_DIR, candidate))
    return True, "", {
        "path": f"uploads/chat/{candidate}",
        "name": candidate,
        "kind": "image" if ext in ALLOWED_IMAGE_EXTENSIONS else "file",
    }
