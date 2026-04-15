from urllib.parse import urlsplit

from flask import current_app, redirect, render_template, request, session, url_for
from werkzeug.exceptions import MethodNotAllowed, NotFound
from werkzeug.routing import RequestRedirect

from logic import (
    connect_db,
    get_buttons,
    get_marquee_settings,
    get_news_posts,
    get_notifications_for_user,
    get_profile_notifications_for_user,
    set_notification_state,
    set_profile_notification_state,
)
from forms_workflow import get_form_notifications_for_user, list_dashboard_forms, set_form_notification_state
from split_app.support import discard_flash_message, get_combined_workflow_counts, get_current_roles, get_topbar_notifications
from split_app.workflow.common import workflow_notification_target_exists
from split_app.workflow.runtime import get_quick_access_work_items


def _apply_notification_action(username, notification_key, action):
    key = (notification_key or "").strip()
    if not username or not key:
        return False

    if key.startswith("form:"):
        if action == "mark-read":
            return set_form_notification_state(username, key, is_read=True)
        if action == "mark-unread":
            return set_form_notification_state(username, key, is_read=False)
        if action == "hide":
            return set_form_notification_state(username, key, is_hidden=True, is_read=True)
        return False

    if key.startswith("profile:"):
        if action == "mark-read":
            return set_profile_notification_state(username, key, is_read=True)
        if action == "mark-unread":
            return set_profile_notification_state(username, key, is_read=False)
        if action == "hide":
            return set_profile_notification_state(username, key, is_hidden=True, is_read=True)
        return False

    if action == "mark-read":
        return set_notification_state(username, key, is_read=True)
    if action == "mark-unread":
        return set_notification_state(username, key, is_read=False)
    if action == "hide":
        return set_notification_state(username, key, is_hidden=True, is_read=True)
    return False


def _resolve_notification_item(notification_key):
    key = (notification_key or "").strip()
    username = session.get("user")
    if not key or not username:
        return None

    if key.startswith("form:"):
        items = get_form_notifications_for_user(username)
    elif key.startswith("profile:"):
        items = get_profile_notifications_for_user(username)
    else:
        items = get_notifications_for_user(username, get_current_roles(), session.get("fullname"))

    for item in items:
        if (item.get("notification_key") or "").strip() == key:
            return item
    return None


def _notification_target_exists(target_url):
    clean_target = str(target_url or "").strip()
    if not clean_target:
        return False

    parsed = urlsplit(clean_target)
    if parsed.scheme and parsed.netloc:
        request_hosts = {str(request.host or "").strip().lower()}
        request_host_only = request_hosts.copy()
        request_host_only.update(host.split(":", 1)[0] for host in request_hosts if host)
        target_host = parsed.netloc.strip().lower()
        if target_host not in request_host_only:
            return True

    path = parsed.path or "/"
    adapter = current_app.url_map.bind(request.host or "localhost", script_name=request.script_root or "")
    try:
        adapter.match(path, method="GET")
    except RequestRedirect:
        pass
    except (NotFound, MethodNotAllowed):
        return False

    static_form_paths = {
        "/forms/manage",
        "/forms/manage/library",
        "/forms/my-requests",
        "/forms/review-queue",
    }
    requires_workflow_entity_check = (
        path.startswith("/forms/submissions/")
        or path.startswith("/forms/cases/")
        or path.startswith("/forms/manage/")
        or (path.startswith("/forms/") and path not in static_form_paths)
    )
    if not requires_workflow_entity_check:
        return True

    connection = connect_db()
    try:
        return workflow_notification_target_exists(connection, clean_target)
    finally:
        connection.close()


def dashboard():
    current_roles = get_current_roles()
    discard_flash_message("Form not found.")
    roles_display = ", ".join(current_roles) if current_roles else "Unassigned"
    buttons = get_buttons(current_roles)
    news_posts = get_news_posts(limit=6)
    marquee = get_marquee_settings()
    notifications, unread_notifications = get_topbar_notifications()
    workflow_counts = get_combined_workflow_counts(current_roles)
    workflow_forms = list_dashboard_forms(session.get("user"), current_roles)
    workflow_work_items = get_quick_access_work_items(session.get("user"), current_roles)

    return render_template(
        "dashboard.html",
        username=session.get("user"),
        userlevel=roles_display,
        fullname=session.get("fullname"),
        buttons=buttons,
        marquee=marquee,
        news_posts=news_posts,
        notifications=notifications,
        unread_notifications=unread_notifications,
        workflow_counts=workflow_counts,
        workflow_forms=workflow_forms,
        workflow_work_items=workflow_work_items,
        is_superadmin=any(role.casefold() == "superadmin" for role in current_roles),
        is_developer=any(role.casefold() == "developer" for role in current_roles),
    )


def notification_action():
    action = (request.form.get("action") or "").strip()
    notification_key = request.form.get("notification_key")
    username = session.get("user")

    _apply_notification_action(username, notification_key, action)

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return ("", 204)

    return redirect(request.referrer or url_for("dashboard"))


def notification_open():
    notification_key = request.args.get("notification_key")
    fallback_url = request.referrer or url_for("dashboard")
    username = session.get("user")
    item = _resolve_notification_item(notification_key)
    if not item:
        discard_flash_message("Form not found.")
        return redirect(fallback_url)

    _apply_notification_action(username, notification_key, "mark-read")
    target_url = str(item.get("link_url") or "").strip()
    if not target_url:
        discard_flash_message("Form not found.")
        return redirect(fallback_url)
    if not _notification_target_exists(target_url):
        _apply_notification_action(username, notification_key, "hide")
        discard_flash_message("Form not found.")
        return redirect(fallback_url)

    return redirect(target_url)
