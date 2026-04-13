from flask import flash, redirect, render_template, request, session, url_for

from logic import create_role, create_user_account, delete_role, delete_user_account, get_all_users, get_role_definitions, update_user_account
from split_app.support import get_combined_workflow_counts, get_current_roles, get_topbar_notifications, is_superadmin, refresh_user_session_identity


def account_manager():
    if request.method == "POST":
        action = (request.form.get("action") or "").strip()
        redirect_kwargs = {}

        if action == "create-account":
            ok, message = create_user_account(
                request.form.get("username"),
                request.form.get("password"),
                request.form.get("designation"),
                request.form.getlist("roles"),
                request.form.get("fullname"),
                actor_username=session.get("user"),
            )
        elif action == "update-account":
            user_id = request.form.get("user_id")
            redirect_kwargs["open"] = user_id
            ok, message = update_user_account(
                user_id,
                request.form.get("username"),
                request.form.get("designation"),
                request.form.getlist("roles"),
                request.form.get("fullname"),
                request.form.get("password"),
                actor_username=session.get("user"),
            )

            edited_username = (request.form.get("current_username") or "").strip()
            new_username = (request.form.get("username") or "").strip()
            if ok and edited_username.casefold() == (session.get("user") or "").casefold():
                refresh_user_session_identity(new_username)
                if not is_superadmin():
                    flash(message, "success")
                    return redirect(url_for("dashboard"))
        elif action == "delete-account":
            ok, message = delete_user_account(
                request.form.get("user_id"),
                active_username=session.get("user"),
                actor_username=session.get("user"),
            )
        elif action == "create-role":
            ok, message = create_role(request.form.get("role_name"))
        elif action == "delete-role":
            ok, message = delete_role(request.form.get("role_id"))
        else:
            ok, message = False, "Unsupported account action."

        flash(message, "success" if ok else "error")
        return redirect(url_for("account_manager", **redirect_kwargs))

    users = get_all_users()
    roles = get_role_definitions()
    topbar_notifications, unread_notifications = get_topbar_notifications()
    current_roles = get_current_roles()
    return render_template(
        "account_manager.html",
        username=session.get("user"),
        fullname=session.get("fullname"),
        users=users,
        available_roles=roles,
        topbar_notifications=topbar_notifications,
        unread_notifications=unread_notifications,
        workflow_counts=get_combined_workflow_counts(current_roles),
        open_account=(request.args.get("open") or "").strip(),
        is_superadmin=is_superadmin(),
        is_developer=any(role.casefold() == "developer" for role in current_roles),
    )
