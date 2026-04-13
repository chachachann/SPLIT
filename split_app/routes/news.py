import os

from flask import abort, flash, redirect, render_template, request, session, url_for
from werkzeug.utils import secure_filename

from logic import (
    ALLOWED_IMAGE_EXTENSIONS,
    NEWS_IMAGE_DIR,
    archive_marquee_item,
    archive_news_post,
    archive_notification,
    create_marquee_item,
    create_news_post,
    create_notification,
    delete_news_image,
    get_all_notifications,
    get_marquee_settings,
    get_marquee_styles,
    get_news_post_by_slug,
    get_news_posts,
    get_role_definitions,
    list_news_images,
    permanently_delete_marquee_item,
    permanently_delete_news_post,
    permanently_delete_notification,
    restore_marquee_item,
    restore_news_post,
    restore_notification,
    update_marquee_item,
    update_marquee_style,
    update_news_post,
    ensure_news_image_folder,
    move_marquee_item,
)
from split_app.support import get_combined_workflow_counts, get_current_roles, get_topbar_notifications, is_superadmin


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
            ok, message = update_marquee_item(request.form.get("item_id"), request.form.get("message"))
        elif action == "delete-marquee-item":
            ok, message = archive_marquee_item(request.form.get("item_id"))
        elif action == "restore-marquee-item":
            ok, message = restore_marquee_item(request.form.get("item_id"))
        elif action == "permanently-delete-marquee-item":
            ok, message = permanently_delete_marquee_item(request.form.get("item_id"))
        elif action == "move-marquee-item":
            ok, message = move_marquee_item(request.form.get("item_id"), request.form.get("direction"))
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
    current_roles = get_current_roles()

    return render_template(
        "news_manager.html",
        username=session.get("user"),
        fullname=session.get("fullname"),
        topbar_notifications=topbar_notifications,
        unread_notifications=unread_notifications,
        workflow_counts=get_combined_workflow_counts(current_roles),
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
        is_developer=any(role.casefold() == "developer" for role in current_roles),
    )


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
