from datetime import datetime, timedelta
from functools import wraps
import os

from flask import abort, Flask, flash, jsonify, redirect, render_template, request, session, url_for
from werkzeug.utils import secure_filename

from logic import (
    ALLOWED_CHAT_ATTACHMENT_EXTENSIONS,
    ALLOWED_IMAGE_EXTENSIONS,
    CHAT_ATTACHMENT_DIR,
    MAX_CHAT_ATTACHMENT_SIZE_BYTES,
    NEWS_IMAGE_DIR,
    REMEMBER_ME_DAYS,
    archive_marquee_item,
    archive_news_post,
    archive_notification,
    consume_remember_me_token,
    connect_db,
    create_role,
    create_news_post,
    create_remember_me_token,
    create_user_account,
    create_marquee_item,
    create_notification,
    delete_remember_me_token,
    delete_marquee_item,
    delete_news_image,
    delete_news_post,
    delete_role,
    delete_user_account,
    delete_notification,
    ensure_chat_attachment_folder,
    ensure_news_image_folder,
    create_chat_message,
    get_password_change_requests_for_user,
    get_password_change_review_queue,
    get_all_users,
    get_chat_overview,
    get_chat_thread_messages,
    get_buttons,
    get_all_notifications,
    get_marquee_settings,
    get_marquee_styles,
    list_news_images,
    mark_user_presence,
    move_marquee_item,
    permanently_delete_marquee_item,
    permanently_delete_news_post,
    permanently_delete_notification,
    get_news_post_by_slug,
    get_news_posts,
    get_notifications_for_user,
    get_profile_context,
    get_profile_notifications_for_user,
    get_profile_request_counts,
    get_public_profile_context,
    get_role_group_settings,
    get_role_definitions,
    get_user_identity,
    get_user_row_by_username,
    get_user_roles_by_username,
    init_db,
    remove_profile_avatar,
    record_user_login,
    restore_marquee_item,
    restore_news_post,
    restore_notification,
    review_password_change_request,
    save_profile_basic,
    save_profile_preferences,
    save_profile_privacy,
    set_notification_state,
    set_profile_notification_state,
    submit_password_change_request,
    update_chat_channel,
    update_marquee_item,
    update_marquee_style,
    update_news_post,
    update_role_group,
    update_user_account,
    validate_user,
)
from forms_workflow import (
    add_submission_comment,
    cancel_submission,
    create_form_template,
    delete_draft_submission,
    delete_form_template,
    get_form_home_context,
    get_form_notifications_for_user,
    get_form_template,
    get_my_requests,
    get_review_queue,
    get_smtp_settings,
    get_submission_detail_context,
    get_submission_editor_context,
    get_workflow_topbar_counts,
    list_dashboard_forms,
    list_forms_for_manager,
    reopen_submission,
    review_submission_action,
    save_form_definition,
    save_smtp_settings,
    save_submission_draft,
    set_form_notification_state,
    start_form_draft,
    submit_submission,
)

app = Flask(__name__)
app.secret_key = "supersecretkey"
app.permanent_session_lifetime = timedelta(days=7)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024
REMEMBER_COOKIE_NAME = "split_remember"


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


@app.before_request
def restore_remembered_session():
    if "user" in session:
        return

    remember_cookie = request.cookies.get(REMEMBER_COOKIE_NAME)
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
        has_access = any(
            role.casefold() in {"superadmin", "developer"}
            for role in current_roles
        )

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


@app.context_processor
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


@app.route("/", methods=["GET", "POST"])
def login():
    if "user" in session:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        remember = request.form.get("remember")

        user = validate_user(username, password)
        if user:
            start_user_session(user, persistent=bool(remember))
            record_user_login(user["username"])
            response = redirect(url_for("dashboard"))

            if remember:
                remember_token = create_remember_me_token(user["username"])
                response.set_cookie(
                    REMEMBER_COOKIE_NAME,
                    remember_token,
                    max_age=REMEMBER_ME_DAYS * 24 * 60 * 60,
                    httponly=True,
                    samesite="Lax",
                )
            else:
                existing_remember_cookie = request.cookies.get(REMEMBER_COOKIE_NAME)
                if existing_remember_cookie:
                    delete_remember_me_token(existing_remember_cookie)
                response.delete_cookie(REMEMBER_COOKIE_NAME)

            return response

        return render_template("login.html", error="Invalid credentials")

    return render_template("login.html")


@app.route("/logout")
def logout():
    remember_cookie = request.cookies.get(REMEMBER_COOKIE_NAME)
    if remember_cookie:
        delete_remember_me_token(remember_cookie)
    session.clear()
    response = redirect(url_for("login"))
    response.delete_cookie(REMEMBER_COOKIE_NAME)
    return response


@app.route("/dashboard")
@login_required
def dashboard():
    current_roles = get_current_roles()
    roles_display = ", ".join(current_roles) if current_roles else "Unassigned"
    buttons = get_buttons(current_roles)
    news_posts = get_news_posts(limit=6)
    marquee = get_marquee_settings()
    notifications, unread_notifications = get_topbar_notifications()
    workflow_counts = get_combined_workflow_counts(current_roles)
    workflow_forms = list_dashboard_forms(session.get("user"), current_roles)

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
        is_superadmin=any(role.casefold() == "superadmin" for role in current_roles),
        is_developer=any(role.casefold() == "developer" for role in current_roles),
    )


@app.route("/notifications/action", methods=["POST"])
@login_required
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


@app.route("/chat/bootstrap")
@login_required
def chat_bootstrap():
    current_roles = get_current_roles()
    mark_user_presence(session.get("user"), source="bootstrap")
    return jsonify({"ok": True, "overview": get_chat_overview(session.get("user"), current_roles)})


@app.route("/chat/thread")
@login_required
def chat_thread():
    current_roles = get_current_roles()
    thread_type = (request.args.get("type") or "").strip().lower()
    target = (request.args.get("target") or "").strip()
    limit = request.args.get("limit", 40)
    before_id = (request.args.get("before_id") or "").strip()
    after_id = (request.args.get("after_id") or "").strip()

    try:
        limit_value = max(1, min(int(limit), 200))
    except (TypeError, ValueError):
        limit_value = 40

    try:
        before_id_value = int(before_id) if before_id else None
    except (TypeError, ValueError):
        before_id_value = None

    try:
        after_id_value = int(after_id) if after_id else None
    except (TypeError, ValueError):
        after_id_value = None

    mark_user_presence(session.get("user"), source="thread-open")
    ok, message, payload = get_chat_thread_messages(
        session.get("user"),
        session.get("fullname"),
        current_roles,
        thread_type,
        target,
        limit=limit_value,
        before_id=before_id_value,
        after_id=after_id_value,
    )
    if not ok:
        return jsonify({"ok": False, "message": message}), 400

    return jsonify(
        {
            "ok": True,
            "message": message,
            "thread": payload["thread"],
            "messages": payload["messages"],
            "message_meta": payload["message_meta"],
            "overview": get_chat_overview(session.get("user"), current_roles),
        }
    )


@app.route("/chat/send", methods=["POST"])
@login_required
def chat_send():
    current_roles = get_current_roles()
    thread_type = (request.form.get("type") or "").strip().lower()
    target = (request.form.get("target") or "").strip()
    body = request.form.get("message")
    upload = request.files.get("attachment_file")

    mark_user_presence(session.get("user"), source="send-message")
    ok, error_message, attachment_meta = save_chat_attachment(upload)
    if not ok:
        return jsonify({"ok": False, "message": error_message}), 400

    ok, message = create_chat_message(
        session.get("user"),
        session.get("fullname"),
        current_roles,
        thread_type,
        target,
        body,
        attachment_meta=attachment_meta,
    )
    if not ok:
        if attachment_meta:
            attachment_path = os.path.join(os.path.dirname(__file__), "static", attachment_meta["path"])
            if os.path.exists(attachment_path):
                os.remove(attachment_path)
        return jsonify({"ok": False, "message": message}), 400

    thread_ok, thread_message, payload = get_chat_thread_messages(
        session.get("user"),
        session.get("fullname"),
        current_roles,
        thread_type,
        target,
        limit=40,
    )
    if not thread_ok:
        return jsonify({"ok": False, "message": thread_message}), 400

    return jsonify(
        {
            "ok": True,
            "message": message,
            "thread": payload["thread"],
            "messages": payload["messages"],
            "message_meta": payload["message_meta"],
            "overview": get_chat_overview(session.get("user"), current_roles),
        }
    )


@app.route("/chat/channel/update", methods=["POST"])
@login_required
def chat_channel_update():
    room_key = (request.form.get("room_key") or "").strip()
    title = request.form.get("title")
    description = request.form.get("description")
    current_roles = get_current_roles()

    mark_user_presence(session.get("user"), source="channel-update")
    ok, message = update_chat_channel(room_key, title, description, session.get("user"))
    status_code = 200 if ok else 400
    return jsonify(
        {
            "ok": ok,
            "message": message,
            "overview": get_chat_overview(session.get("user"), current_roles),
        }
    ), status_code


@app.route("/settings", methods=["GET", "POST"])
@admin_or_developer_required
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
        role_groups=get_role_group_settings(),
    )


@app.route("/forms/manage", methods=["GET", "POST"])
@admin_or_developer_required
def forms_manage():
    if request.method == "POST":
        action = (request.form.get("action") or "").strip()
        if action == "create-form":
            ok, message, form_key = create_form_template(request.form.get("title"), session.get("user"))
            flash(message, "success" if ok else "error")
            if ok and form_key:
                return redirect(url_for("forms_builder", form_key=form_key))
            return redirect(url_for("forms_manage"))
        flash("Unsupported form manager action.", "error")
        return redirect(url_for("forms_manage"))

    topbar_notifications, unread_notifications = get_topbar_notifications()
    listing = list_forms_for_manager((request.args.get("status") or "all").strip().lower())
    return render_template(
        "forms_manager.html",
        username=session.get("user"),
        fullname=session.get("fullname"),
        topbar_notifications=topbar_notifications,
        unread_notifications=unread_notifications,
        workflow_counts=get_combined_workflow_counts(get_current_roles()),
        forms=listing["forms"],
        form_counts=listing["counts"],
        status_filter=(request.args.get("status") or "all").strip().lower(),
    )


@app.route("/forms/manage/<form_key>", methods=["GET", "POST"])
@admin_or_developer_required
def forms_builder(form_key):
    if request.method == "POST":
        action = (request.form.get("action") or "").strip()
        if action == "save-form":
            payload = {
                "title": request.form.get("title"),
                "description": request.form.get("description"),
                "quick_label": request.form.get("quick_label"),
                "tracking_prefix": request.form.get("tracking_prefix"),
                "status": request.form.get("status"),
                "allow_cancel": bool(request.form.get("allow_cancel")),
                "allow_multiple_active": bool(request.form.get("allow_multiple_active")),
                "access_roles": request.form.getlist("access_roles"),
                "access_users": request.form.getlist("access_users"),
                "schema_json": request.form.get("schema_json"),
                "review_stages_json": request.form.get("review_stages_json"),
                "quick_icon_type": request.form.get("quick_icon_type"),
                "quick_icon_value": request.form.get("quick_icon_value"),
                "card_accent": request.form.get("card_accent"),
                "card_tone": request.form.get("card_tone"),
            }
            ok, message = save_form_definition(form_key, payload, session.get("user"), icon_upload=request.files.get("quick_icon_upload"))
        elif action == "delete-form":
            ok, message = delete_form_template(form_key, session.get("user"))
            flash(message, "success" if ok else "error")
            return redirect(url_for("forms_manage"))
        else:
            ok, message = False, "Unsupported form action."

        flash(message, "success" if ok else "error")
        return redirect(url_for("forms_builder", form_key=form_key))

    topbar_notifications, unread_notifications = get_topbar_notifications()
    form = get_form_template(form_key)
    if not form:
        abort(404)
    return render_template(
        "form_builder.html",
        username=session.get("user"),
        fullname=session.get("fullname"),
        topbar_notifications=topbar_notifications,
        unread_notifications=unread_notifications,
        workflow_counts=get_combined_workflow_counts(get_current_roles()),
        form=form,
    )


@app.route("/smtp-settings", methods=["GET", "POST"])
@admin_or_developer_required
def smtp_settings():
    if request.method == "POST":
        ok, message = save_smtp_settings(request.form, session.get("user"))
        flash(message, "success" if ok else "error")
        return redirect(url_for("smtp_settings"))

    topbar_notifications, unread_notifications = get_topbar_notifications()
    return render_template(
        "smtp_settings.html",
        username=session.get("user"),
        fullname=session.get("fullname"),
        topbar_notifications=topbar_notifications,
        unread_notifications=unread_notifications,
        workflow_counts=get_combined_workflow_counts(get_current_roles()),
        smtp_settings=get_smtp_settings(),
    )


@app.route("/profile", methods=["GET", "POST"])
@login_required
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


@app.route("/profile/theme", methods=["POST"])
@login_required
def profile_theme_sync():
    payload = request.get_json(silent=True) or {}
    theme = payload.get("theme") or request.form.get("theme")
    ok, message, _profile = save_profile_preferences(session.get("user"), theme, audit_event="profile.theme-toggled")
    if ok:
        refresh_user_session_identity()
        return jsonify({"ok": True, "message": message, "theme": session.get("theme_preference")})
    return jsonify({"ok": False, "message": message}), 400


@app.route("/users/<username>")
@login_required
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
        is_superadmin=any(role.casefold() == "superadmin" for role in current_roles),
        is_developer=any(role.casefold() == "developer" for role in current_roles),
    )


@app.route("/profile/password-requests/<int:request_id>/review", methods=["POST"])
@login_required
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


@app.route("/forms/my-requests")
@login_required
def my_requests():
    current_roles = get_current_roles()
    topbar_notifications, unread_notifications = get_topbar_notifications()
    return render_template(
        "my_requests.html",
        username=session.get("user"),
        fullname=session.get("fullname"),
        topbar_notifications=topbar_notifications,
        unread_notifications=unread_notifications,
        workflow_counts=get_combined_workflow_counts(current_roles),
        requests=get_my_requests(session.get("user"), current_roles, form_filter=(request.args.get("form") or "").strip()),
        password_requests=get_password_change_requests_for_user(session.get("user")),
    )


@app.route("/forms/review-queue")
@login_required
def review_queue():
    current_roles = get_current_roles()
    topbar_notifications, unread_notifications = get_topbar_notifications()
    return render_template(
        "review_queue.html",
        username=session.get("user"),
        fullname=session.get("fullname"),
        topbar_notifications=topbar_notifications,
        unread_notifications=unread_notifications,
        workflow_counts=get_combined_workflow_counts(current_roles),
        queue_items=get_review_queue(session.get("user"), current_roles),
        password_queue_items=get_password_change_review_queue(session.get("user"), current_roles),
    )


@app.route("/forms/<form_key>", methods=["GET", "POST"])
@login_required
def form_home(form_key):
    current_roles = get_current_roles()
    if request.method == "POST":
        ok, message, submission_id = start_form_draft(form_key, session.get("user"), current_roles)
        flash(message, "success" if ok else "error")
        if ok and submission_id:
            return redirect(url_for("form_edit_submission", submission_id=submission_id))
        return redirect(url_for("form_home", form_key=form_key))

    ok, message, payload = get_form_home_context(form_key, session.get("user"), current_roles)
    if not ok:
        flash(message, "error")
        return redirect(url_for("dashboard"))
    topbar_notifications, unread_notifications = get_topbar_notifications()
    return render_template(
        "form_home.html",
        username=session.get("user"),
        fullname=session.get("fullname"),
        topbar_notifications=topbar_notifications,
        unread_notifications=unread_notifications,
        workflow_counts=get_combined_workflow_counts(current_roles),
        form=payload["form"],
        submissions=payload["submissions"],
    )


@app.route("/forms/submissions/<int:submission_id>/edit", methods=["GET", "POST"])
@login_required
def form_edit_submission(submission_id):
    current_roles = get_current_roles()
    if request.method == "POST":
        action = (request.form.get("action") or "").strip()
        remove_file_ids = request.form.getlist("remove_file_ids")
        if action == "save-draft":
            ok, message, _payload = save_submission_draft(
                submission_id,
                session.get("user"),
                current_roles,
                request.form,
                request.files,
                remove_file_ids=remove_file_ids,
                autosave=False,
            )
        elif action == "submit":
            ok, message, _payload = submit_submission(
                submission_id,
                session.get("user"),
                current_roles,
                request.form,
                request.files,
                remove_file_ids=remove_file_ids,
            )
            if ok:
                flash(message, "success")
                return redirect(url_for("form_submission_detail", submission_id=submission_id))
        else:
            ok, message = False, "Unsupported submission action."
        flash(message, "success" if ok else "error")
        return redirect(url_for("form_edit_submission", submission_id=submission_id))

    ok, message, payload = get_submission_editor_context(submission_id, session.get("user"), current_roles)
    if not ok:
        flash(message, "error")
        return redirect(url_for("my_requests"))
    topbar_notifications, unread_notifications = get_topbar_notifications()
    return render_template(
        "form_edit.html",
        username=session.get("user"),
        fullname=session.get("fullname"),
        topbar_notifications=topbar_notifications,
        unread_notifications=unread_notifications,
        workflow_counts=get_combined_workflow_counts(current_roles),
        form=payload["form"],
        submission=payload["submission"],
        schema=payload["schema"],
        visible_fields=payload["visible_fields"],
        file_groups=payload["file_groups"],
    )


@app.route("/forms/submissions/<int:submission_id>/autosave", methods=["POST"])
@login_required
def form_autosave_submission(submission_id):
    current_roles = get_current_roles()
    payload = request.get_json(silent=True) or {}
    field_values = payload.get("fields") or {}
    proxy_form = {}
    for key, value in field_values.items():
        proxy_form[f"field__{key}"] = value
    ok, message, updated = save_submission_draft(
        submission_id,
        session.get("user"),
        current_roles,
        proxy_form,
        {},
        remove_file_ids=[],
        autosave=True,
    )
    if not ok:
        return jsonify({"ok": False, "message": message}), 400
    return jsonify({"ok": True, "message": message, "updated_at": updated.get("updated_at")})


@app.route("/forms/submissions/<int:submission_id>")
@login_required
def form_submission_detail(submission_id):
    current_roles = get_current_roles()
    ok, message, payload = get_submission_detail_context(submission_id, session.get("user"), current_roles)
    if not ok:
        flash(message, "error")
        return redirect(url_for("dashboard"))
    topbar_notifications, unread_notifications = get_topbar_notifications()
    return render_template(
        "form_submission_detail.html",
        username=session.get("user"),
        fullname=session.get("fullname"),
        topbar_notifications=topbar_notifications,
        unread_notifications=unread_notifications,
        workflow_counts=get_combined_workflow_counts(current_roles),
        form=payload["form"],
        submission=payload["submission"],
        schema=payload["schema"],
        visible_fields=payload["visible_fields"],
        file_groups=payload["file_groups"],
        active_task_ids=payload["active_task_ids"],
        actionable_task_ids=payload["actionable_task_ids"],
        can_cancel=payload["can_cancel"],
        can_reopen=payload["can_reopen"],
        can_delete_draft=payload["can_delete_draft"],
        can_edit=payload["can_edit"],
        can_comment=payload["can_comment"],
    )


@app.route("/forms/submissions/<int:submission_id>/comment", methods=["POST"])
@login_required
def form_submission_comment(submission_id):
    ok, message = add_submission_comment(
        submission_id,
        session.get("user"),
        session.get("fullname"),
        get_current_roles(),
        request.form.get("comment"),
    )
    flash(message, "success" if ok else "error")
    return redirect(url_for("form_submission_detail", submission_id=submission_id))


@app.route("/forms/submissions/<int:submission_id>/cancel", methods=["POST"])
@login_required
def form_submission_cancel(submission_id):
    ok, message = cancel_submission(
        submission_id,
        session.get("user"),
        get_current_roles(),
        request.form.get("reason"),
    )
    flash(message, "success" if ok else "error")
    return redirect(url_for("form_submission_detail", submission_id=submission_id))


@app.route("/forms/submissions/<int:submission_id>/reopen", methods=["POST"])
@login_required
def form_submission_reopen(submission_id):
    ok, message = reopen_submission(submission_id, session.get("user"), get_current_roles())
    flash(message, "success" if ok else "error")
    return redirect(url_for("form_submission_detail", submission_id=submission_id))


@app.route("/forms/submissions/<int:submission_id>/delete-draft", methods=["POST"])
@login_required
def form_submission_delete_draft(submission_id):
    ok, message = delete_draft_submission(submission_id, session.get("user"), get_current_roles())
    flash(message, "success" if ok else "error")
    return redirect(url_for("my_requests"))


@app.route("/forms/submissions/<int:submission_id>/review", methods=["POST"])
@login_required
def form_submission_review(submission_id):
    ok, message = review_submission_action(
        submission_id,
        request.form.get("task_id"),
        session.get("user"),
        session.get("fullname"),
        get_current_roles(),
        request.form.get("review_action"),
        request.form.get("note"),
    )
    flash(message, "success" if ok else "error")
    return redirect(url_for("form_submission_detail", submission_id=submission_id))


@app.route("/account-manager", methods=["GET", "POST"])
@admin_or_developer_required
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
    return render_template(
        "account_manager.html",
        username=session.get("user"),
        fullname=session.get("fullname"),
        users=users,
        available_roles=roles,
        topbar_notifications=topbar_notifications,
        unread_notifications=unread_notifications,
        workflow_counts=get_combined_workflow_counts(get_current_roles()),
        open_account=(request.args.get("open") or "").strip(),
        is_superadmin=is_superadmin(),
        is_developer=any(role.casefold() == "developer" for role in get_current_roles()),
    )


@app.route("/news-manager", methods=["GET", "POST"])
@admin_or_developer_required
def news_manager():
    if request.method == "POST":
        action = (request.form.get("action") or "").strip()
        redirect_kwargs = {}

        if action == "upload-image":
            upload = request.files.get("image_file")
            if not upload or not upload.filename:
                ok, message = False, "Choose an image file to upload."
            else:
                ensure_news_image_folder()
                filename = secure_filename(upload.filename)
                ext = os.path.splitext(filename)[1].lower()

                if ext not in ALLOWED_IMAGE_EXTENSIONS:
                    ok, message = False, "Unsupported image type. Use PNG, JPG, JPEG, GIF, or WEBP."
                else:
                    base_name = os.path.splitext(filename)[0]
                    candidate = filename
                    suffix = 2
                    while os.path.exists(os.path.join(NEWS_IMAGE_DIR, candidate)):
                        candidate = f"{base_name}-{suffix}{ext}"
                        suffix += 1

                    upload.save(os.path.join(NEWS_IMAGE_DIR, candidate))
                    ok, message = True, "Image uploaded. Copy its token into the blog content where you want it to appear."
        elif action == "delete-image":
            ok, message = delete_news_image(request.form.get("filename"))
        elif action == "create-post":
            ok, message = create_news_post(
                request.form.get("title"),
                request.form.get("summary"),
                request.form.get("content"),
                actor_username=session.get("user"),
                actor_fullname=session.get("fullname"),
            )
        elif action == "update-post":
            post_id = request.form.get("post_id")
            redirect_kwargs["open"] = post_id
            ok, message = update_news_post(
                post_id,
                request.form.get("title"),
                request.form.get("summary"),
                request.form.get("content"),
                actor_fullname=session.get("fullname"),
            )
        elif action == "delete-post":
            ok, message = archive_news_post(request.form.get("post_id"))
        elif action == "restore-post":
            ok, message = restore_news_post(request.form.get("post_id"))
        elif action == "update-marquee-style":
            ok, message = update_marquee_style(request.form.get("style_key"))
        elif action == "create-marquee-item":
            ok, message = create_marquee_item(request.form.get("message"))
        elif action == "update-marquee-item":
            ok, message = update_marquee_item(
                request.form.get("item_id"),
                request.form.get("message"),
            )
        elif action == "delete-marquee-item":
            ok, message = archive_marquee_item(request.form.get("item_id"))
        elif action == "restore-marquee-item":
            ok, message = restore_marquee_item(request.form.get("item_id"))
        elif action == "permanently-delete-marquee-item":
            ok, message = permanently_delete_marquee_item(request.form.get("item_id"))
        elif action == "move-marquee-item":
            ok, message = move_marquee_item(
                request.form.get("item_id"),
                request.form.get("direction"),
            )
        elif action == "create-notification":
            ok, message = create_notification(
                request.form.get("title"),
                request.form.get("message"),
                request.form.getlist("target_role"),
                request.form.get("style_key"),
                request.form.get("link_url"),
                actor_username=session.get("user"),
                actor_fullname=session.get("fullname"),
            )
        elif action == "delete-notification":
            ok, message = archive_notification(request.form.get("notification_id"))
        elif action == "restore-notification":
            ok, message = restore_notification(request.form.get("notification_id"))
        elif action == "permanently-delete-notification":
            ok, message = permanently_delete_notification(request.form.get("notification_id"))
        elif action == "permanently-delete-post":
            ok, message = permanently_delete_news_post(request.form.get("post_id"))
        else:
            ok, message = False, "Unsupported news action."

        flash(message, "success" if ok else "error")
        return redirect(url_for("news_manager", **redirect_kwargs))

    topbar_notifications, unread_notifications = get_topbar_notifications()
    all_notifications = get_all_notifications(include_archived=True)
    active_notifications = [item for item in all_notifications if not item.get("is_archived")]
    archived_notifications = [item for item in all_notifications if item.get("is_archived")]
    all_posts = get_news_posts(include_archived=True)
    active_posts = [post for post in all_posts if not post.get("is_archived")]
    archived_posts = [post for post in all_posts if post.get("is_archived")]

    return render_template(
        "news_manager.html",
        username=session.get("user"),
        fullname=session.get("fullname"),
        topbar_notifications=topbar_notifications,
        unread_notifications=unread_notifications,
        workflow_counts=get_combined_workflow_counts(get_current_roles()),
        marquee=get_marquee_settings(),
        marquee_styles=get_marquee_styles(),
        notifications=active_notifications,
        archived_notifications=archived_notifications,
        notification_roles=list(dict.fromkeys(["All"] + [role["name"] for role in get_role_definitions()])),
        uploaded_images=list_news_images(),
        posts=active_posts,
        archived_posts=archived_posts,
        open_post=(request.args.get("open") or "").strip(),
        is_superadmin=is_superadmin(),
        is_developer=any(role.casefold() == "developer" for role in get_current_roles()),
    )


@app.route("/news/<slug>")
def news_post(slug):
    post = get_news_post_by_slug(slug)
    if not post:
        abort(404)

    topbar_notifications = []
    unread_notifications = 0
    if "user" in session:
        topbar_notifications, unread_notifications = get_topbar_notifications()

    return render_template(
        "news_post.html",
        post=post,
        topbar_notifications=topbar_notifications,
        unread_notifications=unread_notifications,
        workflow_counts=get_combined_workflow_counts(get_current_roles()) if "user" in session else {"my_requests": 0, "review_queue": 0},
        is_authenticated="user" in session,
        is_superadmin=is_superadmin() if "user" in session else False,
    )


portX = 777


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=portX, debug=True)
