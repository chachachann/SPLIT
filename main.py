from datetime import datetime, timedelta
from functools import wraps
import os

from flask import abort, Flask, flash, jsonify, redirect, render_template, request, session, url_for
from werkzeug.utils import secure_filename

from logic import (
    ALLOWED_CHAT_ATTACHMENT_EXTENSIONS,
    ALLOWED_IMAGE_EXTENSIONS,
    CHAT_ATTACHMENT_DIR,
    NEWS_IMAGE_DIR,
    REMEMBER_ME_DAYS,
    archive_marquee_item,
    archive_news_post,
    archive_notification,
    consume_remember_me_token,
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
    get_role_group_settings,
    get_role_definitions,
    get_user_identity,
    get_user_roles_by_username,
    init_db,
    record_user_login,
    restore_marquee_item,
    restore_news_post,
    restore_notification,
    set_notification_state,
    update_chat_channel,
    update_marquee_item,
    update_marquee_style,
    update_news_post,
    update_role_group,
    update_user_account,
    validate_user,
)

app = Flask(__name__)
app.secret_key = "supersecretkey"
app.permanent_session_lifetime = timedelta(days=7)
REMEMBER_COOKIE_NAME = "split_remember"


def start_user_session(user, persistent=False):
    session.clear()
    session["user"] = user["username"]
    session["fullname"] = user["fullname"]
    session["login_time"] = datetime.now().isoformat()
    session.permanent = bool(persistent)
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
    unread_count = sum(1 for item in items if not item.get("is_read"))
    return items, unread_count


def save_chat_attachment(upload):
    if not upload or not upload.filename:
        return True, "", None

    ensure_chat_attachment_folder()
    filename = secure_filename(upload.filename)
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_CHAT_ATTACHMENT_EXTENSIONS:
        return False, "Unsupported attachment type.", None

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
    notifications = get_notifications_for_user(session.get("user"), current_roles, session.get("fullname"))
    unread_notifications = sum(1 for item in notifications if not item.get("is_read"))

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
        is_superadmin=any(role.casefold() == "superadmin" for role in current_roles),
        is_developer=any(role.casefold() == "developer" for role in current_roles),
    )


@app.route("/notifications/action", methods=["POST"])
@login_required
def notification_action():
    action = (request.form.get("action") or "").strip()
    notification_key = request.form.get("notification_key")
    username = session.get("user")

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
@superadmin_required
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
        role_groups=get_role_group_settings(),
    )


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
            new_fullname = (request.form.get("fullname") or "").strip()

            if ok and edited_username.casefold() == (session.get("user") or "").casefold():
                session["user"] = new_username
                session["fullname"] = new_fullname

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
        open_account=(request.args.get("open") or "").strip(),
        is_superadmin=is_superadmin(),
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
        is_authenticated="user" in session,
        is_superadmin=is_superadmin() if "user" in session else False,
    )


portX = 777


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=portX, debug=True)
