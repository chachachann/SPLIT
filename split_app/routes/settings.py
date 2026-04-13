from flask import flash, redirect, render_template, request, session, url_for

from logic import get_channel_settings, get_role_group_settings, update_channel_settings, update_role_group
from split_app.support import get_combined_workflow_counts, get_current_roles, get_topbar_notifications


def settings():
    if request.method == "POST":
        action = (request.form.get("action") or "").strip()
        if action == "update-role-group":
            ok, message = update_role_group(
                request.form.get("room_key"),
                request.form.get("title"),
                request.form.get("description"),
                bool(request.form.get("is_enabled")),
                session.get("user"),
            )
        elif action == "update-channel":
            ok, message = update_channel_settings(
                request.form.get("room_key"),
                request.form.get("title"),
                request.form.get("description"),
                bool(request.form.get("is_enabled")),
                session.get("user"),
            )
        else:
            ok, message = False, "Unsupported configuration action."

        flash(message, "success" if ok else "error")
        return redirect(url_for("settings"))

    topbar_notifications, unread_notifications = get_topbar_notifications()
    return render_template(
        "settings.html",
        fullname=session.get("fullname"),
        username=session.get("user"),
        topbar_notifications=topbar_notifications,
        unread_notifications=unread_notifications,
        workflow_counts=get_combined_workflow_counts(get_current_roles()),
        channels=get_channel_settings(),
        role_groups=get_role_group_settings(),
    )
