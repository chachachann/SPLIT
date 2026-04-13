import os

from flask import jsonify, request, session

from split_app.services.chat_auth import (
    create_chat_message,
    get_chat_overview,
    get_chat_thread_messages,
    mark_user_presence,
    move_chat_favorite,
    set_chat_favorite,
    update_chat_channel,
)
from split_app.support import get_current_roles, save_chat_attachment


def chat_bootstrap():
    current_roles = get_current_roles()
    mark_user_presence(session.get("user"), source="bootstrap")
    return jsonify({"ok": True, "overview": get_chat_overview(session.get("user"), current_roles)})


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
            attachment_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "static", attachment_meta["path"])
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


def chat_favorite_toggle():
    current_roles = get_current_roles()
    target_username = (request.form.get("username") or request.form.get("target_username") or "").strip()
    desired_state = (request.form.get("state") or "").strip().lower()
    is_favorite = desired_state != "off"

    mark_user_presence(session.get("user"), source="favorite-toggle")
    ok, message = set_chat_favorite(session.get("user"), target_username, is_favorite=is_favorite)
    status_code = 200 if ok else 400
    return jsonify(
        {
            "ok": ok,
            "message": message,
            "overview": get_chat_overview(session.get("user"), current_roles),
        }
    ), status_code


def chat_favorite_move():
    current_roles = get_current_roles()
    target_username = (request.form.get("username") or request.form.get("target_username") or "").strip()
    direction = (request.form.get("direction") or "").strip().lower()

    mark_user_presence(session.get("user"), source="favorite-move")
    ok, message = move_chat_favorite(session.get("user"), target_username, direction)
    status_code = 200 if ok else 400
    return jsonify(
        {
            "ok": ok,
            "message": message,
            "overview": get_chat_overview(session.get("user"), current_roles),
        }
    ), status_code
