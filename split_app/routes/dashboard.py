from flask import redirect, render_template, request, session, url_for

from logic import (
    get_buttons,
    get_marquee_settings,
    get_news_posts,
    set_notification_state,
    set_profile_notification_state,
)
from forms_workflow import list_dashboard_forms, set_form_notification_state
from split_app.workflow.runtime import get_quick_access_work_items
from split_app.support import get_combined_workflow_counts, get_current_roles, get_topbar_notifications


def dashboard():
    current_roles = get_current_roles()
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

    if (notification_key or "").startswith("form:"):
        if action == "mark-read":
            set_form_notification_state(username, notification_key, is_read=True)
        elif action == "mark-unread":
            set_form_notification_state(username, notification_key, is_read=False)
        elif action == "hide":
            set_form_notification_state(username, notification_key, is_hidden=True, is_read=True)
    elif (notification_key or "").startswith("profile:"):
        if action == "mark-read":
            set_profile_notification_state(username, notification_key, is_read=True)
        elif action == "mark-unread":
            set_profile_notification_state(username, notification_key, is_read=False)
        elif action == "hide":
            set_profile_notification_state(username, notification_key, is_hidden=True, is_read=True)
    else:
        if action == "mark-read":
            set_notification_state(username, notification_key, is_read=True)
        elif action == "mark-unread":
            set_notification_state(username, notification_key, is_read=False)
        elif action == "hide":
            set_notification_state(username, notification_key, is_hidden=True, is_read=True)

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return ("", 204)

    return redirect(url_for("dashboard"))
