from flask import abort, flash, jsonify, redirect, render_template, request, session, url_for

from logic import (
    connect_db,
    get_profile_context,
    get_public_profile_context,
    get_user_row_by_username,
    remove_profile_avatar,
    review_password_change_request,
    save_profile_basic,
    save_profile_preferences,
    save_profile_privacy,
    submit_password_change_request,
)
from split_app.services.chat_auth import is_chat_favorite
from split_app.support import (
    get_combined_workflow_counts,
    get_current_roles,
    get_topbar_notifications,
    refresh_user_session_identity,
)


def profile():
    if request.method == "POST":
        action = (request.form.get("action") or "").strip()
        active_tab = "basic"
        if action == "save-basic":
            ok, message, _profile = save_profile_basic(
                session.get("user"),
                request.form,
                avatar_upload=request.files.get("avatar_file"),
            )
            active_tab = "basic"
        elif action == "remove-avatar":
            connection = connect_db()
            user_row = get_user_row_by_username(connection, session.get("user"))
            if not user_row:
                ok, message = False, "User not found."
            else:
                ok, message = remove_profile_avatar(connection, user_row)
            connection.close()
            active_tab = "basic"
        elif action == "save-privacy":
            ok, message, _profile = save_profile_privacy(session.get("user"), request.form.getlist("private_fields"))
            active_tab = "privacy"
        elif action == "save-preferences":
            ok, message, _profile = save_profile_preferences(session.get("user"), request.form.get("theme_preference"))
            active_tab = "preferences"
        elif action == "submit-password-request":
            ok, message = submit_password_change_request(
                session.get("user"),
                request.form.get("new_password"),
                request.form.get("confirm_password"),
            )
            active_tab = "security"
        else:
            ok, message = False, "Unsupported profile action."

        if ok:
            refresh_user_session_identity()
        flash(message, "success" if ok else "error")
        return redirect(url_for("profile", tab=active_tab))

    profile_context = get_profile_context(session.get("user"))
    if not profile_context:
        abort(404)

    topbar_notifications, unread_notifications = get_topbar_notifications()
    current_roles = get_current_roles()
    return render_template(
        "profile.html",
        username=session.get("user"),
        fullname=session.get("fullname"),
        topbar_notifications=topbar_notifications,
        unread_notifications=unread_notifications,
        workflow_counts=get_combined_workflow_counts(current_roles),
        profile_context=profile_context,
        active_tab=(request.args.get("tab") or "basic").strip().lower(),
        is_superadmin=any(role.casefold() == "superadmin" for role in current_roles),
        is_developer=any(role.casefold() == "developer" for role in current_roles),
    )


def profile_theme_sync():
    payload = request.get_json(silent=True) or {}
    theme = payload.get("theme") or request.form.get("theme")
    ok, message, _profile = save_profile_preferences(session.get("user"), theme, audit_event="profile.theme-toggled")
    if ok:
        refresh_user_session_identity()
        return jsonify({"ok": True, "message": message, "theme": session.get("theme_preference")})
    return jsonify({"ok": False, "message": message}), 400


def user_profile_view(username):
    if (username or "").strip().casefold() == (session.get("user") or "").casefold():
        return redirect(url_for("profile"))

    current_roles = get_current_roles()
    ok, message, payload = get_public_profile_context(username, session.get("user"), current_roles)
    if not ok:
        flash(message, "error")
        return redirect(url_for("dashboard"))

    topbar_notifications, unread_notifications = get_topbar_notifications()
    return render_template(
        "user_profile.html",
        username=session.get("user"),
        fullname=session.get("fullname"),
        topbar_notifications=topbar_notifications,
        unread_notifications=unread_notifications,
        workflow_counts=get_combined_workflow_counts(current_roles),
        profile_context=payload,
        profile_is_favorite=is_chat_favorite(session.get("user"), payload["profile"]["username"]),
        is_superadmin=any(role.casefold() == "superadmin" for role in current_roles),
        is_developer=any(role.casefold() == "developer" for role in current_roles),
    )


def review_profile_password_request(request_id):
    ok, message = review_password_change_request(
        request_id,
        session.get("user"),
        get_current_roles(),
        request.form.get("review_action"),
        request.form.get("rejection_note"),
    )
    flash(message, "success" if ok else "error")
    return redirect(url_for("review_queue"))
