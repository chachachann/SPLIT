from datetime import datetime
from html import escape
import os
import re

from split_app.services.core import (
    ALLOWED_IMAGE_EXTENSIONS,
    DEFAULT_MARQUEE_STYLE,
    MARQUEE_STYLE_CHOICES,
    NEWS_IMAGE_DIR,
    NEWS_IMAGE_WEB_PATH,
    connect_db,
    ensure_news_image_folder,
    normalize_role_names,
    timestamp_now,
)
from split_app.services.validation import validate_http_url


def get_marquee_styles():
    return [{"key": key, "label": label} for key, label in MARQUEE_STYLE_CHOICES]


def _find_active_marquee_item_by_message(cursor, message, exclude_item_id=None):
    query = """
        SELECT id
        FROM marquee_items
        WHERE is_archived = 0 AND lower(message) = lower(?)
    """
    params = [message]

    if exclude_item_id is not None:
        query += " AND id != ?"
        params.append(exclude_item_id)

    query += " LIMIT 1"
    cursor.execute(query, tuple(params))
    return cursor.fetchone()


def get_marquee_settings():
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute("SELECT style_key FROM marquee_settings WHERE id = 1")
    settings_row = cursor.fetchone()
    cursor.execute(
        """
        SELECT id, message, sort_order, created_at, is_archived, archived_at
        FROM marquee_items
        WHERE is_archived = 0
        ORDER BY sort_order ASC, id ASC
        """
    )
    items = [dict(row) for row in cursor.fetchall()]
    cursor.execute(
        """
        SELECT id, message, sort_order, created_at, is_archived, archived_at
        FROM marquee_items
        WHERE is_archived = 1
        ORDER BY datetime(archived_at) DESC, id DESC
        """
    )
    archived_items = [dict(row) for row in cursor.fetchall()]
    connection.close()
    return {
        "style_key": settings_row["style_key"] if settings_row else DEFAULT_MARQUEE_STYLE,
        "items": items,
        "archived_items": archived_items,
    }


def update_marquee_style(style_key):
    valid_keys = {key for key, _ in MARQUEE_STYLE_CHOICES}
    if style_key not in valid_keys:
        return False, "Unsupported marquee style."

    connection = connect_db()
    connection.execute(
        """
        UPDATE marquee_settings
        SET style_key = ?, updated_at = ?
        WHERE id = 1
        """,
        (style_key, timestamp_now()),
    )
    connection.commit()
    connection.close()
    return True, "Marquee style updated."


def create_marquee_item(message):
    message = " ".join((message or "").split())
    if not message:
        return False, "Marquee message is required."

    connection = connect_db()
    cursor = connection.cursor()
    if _find_active_marquee_item_by_message(cursor, message):
        connection.close()
        return False, "That marquee message already exists."
    cursor.execute("SELECT COALESCE(MAX(sort_order), 0) + 1 AS next_order FROM marquee_items")
    next_order = cursor.fetchone()["next_order"]
    cursor.execute(
        """
        INSERT INTO marquee_items (message, sort_order, created_at)
        VALUES (?, ?, ?)
        """,
        (message, next_order, timestamp_now()),
    )
    connection.commit()
    connection.close()
    return True, "Marquee item added."


def update_marquee_item(item_id, message):
    message = " ".join((message or "").split())
    if not message:
        return False, "Marquee message is required."

    connection = connect_db()
    cursor = connection.cursor()
    if _find_active_marquee_item_by_message(cursor, message, exclude_item_id=item_id):
        connection.close()
        return False, "That marquee message already exists."
    cursor.execute(
        """
        UPDATE marquee_items
        SET message = ?
        WHERE id = ?
        """,
        (message, item_id),
    )
    if cursor.rowcount == 0:
        connection.close()
        return False, "Marquee item not found."
    connection.commit()
    connection.close()
    return True, "Marquee item updated."


def delete_marquee_item(item_id):
    return archive_marquee_item(item_id)


def archive_marquee_item(item_id):
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute(
        """
        UPDATE marquee_items
        SET is_archived = 1, archived_at = ?
        WHERE id = ?
        """,
        (timestamp_now(), item_id),
    )
    if cursor.rowcount == 0:
        connection.close()
        return False, "Marquee item not found."
    connection.commit()
    connection.close()
    return True, "Marquee item archived."


def restore_marquee_item(item_id):
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute("SELECT COALESCE(MAX(sort_order), 0) + 1 AS next_order FROM marquee_items WHERE is_archived = 0")
    next_order = cursor.fetchone()["next_order"]
    cursor.execute(
        """
        UPDATE marquee_items
        SET is_archived = 0, archived_at = NULL, sort_order = ?
        WHERE id = ?
        """,
        (next_order, item_id),
    )
    if cursor.rowcount == 0:
        connection.close()
        return False, "Marquee item not found."
    connection.commit()
    connection.close()
    return True, "Marquee item restored."


def permanently_delete_marquee_item(item_id):
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute("DELETE FROM marquee_items WHERE id = ? AND is_archived = 1", (item_id,))
    if cursor.rowcount == 0:
        connection.close()
        return False, "Archived marquee item not found."
    connection.commit()
    connection.close()
    return True, "Archived marquee item deleted."


def move_marquee_item(item_id, direction):
    if direction not in {"up", "down"}:
        return False, "Unsupported move direction."

    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT id, sort_order
        FROM marquee_items
        WHERE id = ?
        """,
        (item_id,),
    )
    current_item = cursor.fetchone()
    if not current_item:
        connection.close()
        return False, "Marquee item not found."

    comparison = "<" if direction == "up" else ">"
    ordering = "DESC" if direction == "up" else "ASC"
    cursor.execute(
        f"""
        SELECT id, sort_order
        FROM marquee_items
        WHERE sort_order {comparison} ?
        ORDER BY sort_order {ordering}, id {ordering}
        LIMIT 1
        """,
        (current_item["sort_order"],),
    )
    swap_item = cursor.fetchone()
    if not swap_item:
        connection.close()
        return False, "Item is already at the edge of the list."

    cursor.execute("UPDATE marquee_items SET sort_order = ? WHERE id = ?", (swap_item["sort_order"], current_item["id"]))
    cursor.execute("UPDATE marquee_items SET sort_order = ? WHERE id = ?", (current_item["sort_order"], swap_item["id"]))
    connection.commit()
    connection.close()
    return True, "Marquee order updated."


def get_notifications_for_user(username, role_names, fullname):
    normalized_roles = {role.casefold() for role in (role_names or [])}
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT id, title, message, target_role, style_key, link_url, created_at, created_by_username, created_by_fullname
        FROM notifications
        WHERE is_archived = 0
        ORDER BY datetime(created_at) DESC, id DESC
        """
    )
    notifications = []
    for row in cursor.fetchall():
        item = dict(row)
        target_roles = normalize_role_names((item["target_role"] or "").replace(";", ",").split(","))
        target_role_keys = {role.casefold() for role in target_roles}
        if "all" not in target_role_keys and not (target_role_keys & normalized_roles):
            continue
        item["notification_key"] = f"db:{item['id']}"
        item["sender_name"] = (
            (item.get("created_by_fullname") or "").strip()
            or (item.get("created_by_username") or "").strip()
            or "System"
        )
        item["target_role_display"] = ", ".join(target_roles) if target_roles else "All"
        item["message_preview"] = build_notification_preview(item.get("message"))
        item["message_html"] = render_notification_markup(item.get("message"))
        notifications.append(item)

    welcome_name = (fullname or "").strip() or "User"
    notifications.insert(
        0,
        {
            "id": "welcome",
            "notification_key": "entry:welcome",
            "title": f"Hello, {welcome_name}",
            "message": "Welcome back. Review current notices and updates before proceeding with your work.",
            "message_preview": "Welcome back. Review current notices and updates before proceeding with your work.",
            "message_html": "<p>Welcome back. Review current notices and updates before proceeding with your work.</p>",
            "target_role": "all",
            "style_key": "success",
            "created_at": timestamp_now(),
            "sender_name": "System",
        },
    )

    if not username:
        connection.close()
        for item in notifications:
            item["is_read"] = False
            item["is_hidden"] = False
        return notifications

    notification_keys = [item["notification_key"] for item in notifications]
    placeholders = ", ".join("?" for _ in notification_keys)
    cursor.execute(
        f"""
        SELECT notification_key, is_read, is_hidden
        FROM notification_user_states
        WHERE username = ? AND notification_key IN ({placeholders})
        """,
        (username, *notification_keys),
    )
    state_map = {row["notification_key"]: dict(row) for row in cursor.fetchall()}
    connection.close()

    visible_notifications = []
    for item in notifications:
        state = state_map.get(item["notification_key"], {})
        item["is_read"] = bool(state.get("is_read"))
        item["is_hidden"] = bool(state.get("is_hidden"))
        if item["is_hidden"]:
            continue
        visible_notifications.append(item)
    return visible_notifications


def set_notification_state(username, notification_key, *, is_read=None, is_hidden=None):
    username = (username or "").strip()
    notification_key = (notification_key or "").strip()
    if not username or not notification_key:
        return False

    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT is_read, is_hidden
        FROM notification_user_states
        WHERE username = ? AND notification_key = ?
        """,
        (username, notification_key),
    )
    existing = cursor.fetchone()
    current_read = int(existing["is_read"]) if existing else 0
    current_hidden = int(existing["is_hidden"]) if existing else 0
    next_read = current_read if is_read is None else (1 if is_read else 0)
    next_hidden = current_hidden if is_hidden is None else (1 if is_hidden else 0)

    cursor.execute(
        """
        INSERT INTO notification_user_states (username, notification_key, is_read, is_hidden, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(username, notification_key) DO UPDATE SET
            is_read = excluded.is_read,
            is_hidden = excluded.is_hidden,
            updated_at = excluded.updated_at
        """,
        (username, notification_key, next_read, next_hidden, timestamp_now()),
    )
    connection.commit()
    connection.close()
    return True


def get_all_notifications(include_archived=False):
    connection = connect_db()
    cursor = connection.cursor()
    where_clause = "" if include_archived else "WHERE is_archived = 0"
    cursor.execute(
        f"""
        SELECT
            id,
            title,
            message,
            target_role,
            style_key,
            link_url,
            created_by_username,
            created_by_fullname,
            created_at,
            is_archived,
            archived_at
        FROM notifications
        {where_clause}
        ORDER BY datetime(created_at) DESC, id DESC
        """
    )
    items = [dict(row) for row in cursor.fetchall()]
    connection.close()
    for item in items:
        item["sender_name"] = (
            (item.get("created_by_fullname") or "").strip()
            or (item.get("created_by_username") or "").strip()
            or "System"
        )
        item["message_preview"] = build_notification_preview(item.get("message"))
    return items


def create_notification(title, message, target_role, style_key, link_url="", actor_username=None, actor_fullname=None):
    title = " ".join((title or "").split())
    message = (message or "").strip()
    style_key = " ".join((style_key or "").split()) or "info"
    link_url = (link_url or "").strip()
    target_roles = normalize_role_names(target_role if isinstance(target_role, list) else [target_role])

    if not title or not message:
        return False, "Notification title and message are required."
    ok, validation_message = validate_http_url(link_url, allow_blank=True)
    if not ok:
        return False, validation_message

    if not target_roles:
        target_roles = ["All"]

    connection = connect_db()
    connection.execute(
        """
        INSERT INTO notifications (
            title,
            message,
            target_role,
            style_key,
            link_url,
            created_by_username,
            created_by_fullname,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            title,
            message,
            ",".join(target_roles),
            style_key,
            link_url or None,
            (actor_username or "").strip() or None,
            (actor_fullname or "").strip() or None,
            timestamp_now(),
        ),
    )
    connection.commit()
    connection.close()
    return True, "Notification created."


def delete_notification(notification_id):
    return archive_notification(notification_id)


def archive_notification(notification_id):
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute(
        """
        UPDATE notifications
        SET is_archived = 1, archived_at = ?
        WHERE id = ?
        """,
        (timestamp_now(), notification_id),
    )
    if cursor.rowcount == 0:
        connection.close()
        return False, "Notification not found."
    connection.commit()
    connection.close()
    return True, "Notification archived."


def restore_notification(notification_id):
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute(
        """
        UPDATE notifications
        SET is_archived = 0, archived_at = NULL
        WHERE id = ?
        """,
        (notification_id,),
    )
    if cursor.rowcount == 0:
        connection.close()
        return False, "Notification not found."
    connection.commit()
    connection.close()
    return True, "Notification restored."


def permanently_delete_notification(notification_id):
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute("DELETE FROM notifications WHERE id = ? AND is_archived = 1", (notification_id,))
    if cursor.rowcount == 0:
        connection.close()
        return False, "Archived notification not found."
    connection.commit()
    connection.close()
    return True, "Archived notification deleted."


def slugify(value):
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in (value or "").strip())
    parts = [part for part in cleaned.split("-") if part]
    return "-".join(parts) or f"post-{datetime.now().strftime('%Y%m%d%H%M%S')}"


def ensure_unique_slug(connection, title, exclude_post_id=None):
    base_slug = slugify(title)
    candidate = base_slug
    suffix = 2
    cursor = connection.cursor()

    while True:
        if exclude_post_id is None:
            cursor.execute("SELECT id FROM news_posts WHERE slug = ?", (candidate,))
        else:
            cursor.execute("SELECT id FROM news_posts WHERE slug = ? AND id != ?", (candidate, exclude_post_id))

        if not cursor.fetchone():
            return candidate

        candidate = f"{base_slug}-{suffix}"
        suffix += 1


def build_news_summary(summary, content, limit=180):
    manual_summary = " ".join((summary or "").split())
    if manual_summary:
        return manual_summary

    normalized_content = " ".join(strip_image_tokens(content).split())
    if len(normalized_content) <= limit:
        return normalized_content

    return normalized_content[: limit - 1].rstrip() + "..."


def strip_image_tokens(content):
    lines = []
    for raw_line in (content or "").replace("\r\n", "\n").splitlines():
        line = raw_line.strip()
        if line.startswith("[image:") and line.endswith("]"):
            continue
        lines.append(raw_line)
    return "\n".join(lines)


def parse_image_token(block):
    token_body = block[len("[image:") : -1]
    if "|" in token_body:
        filename, caption = token_body.split("|", 1)
    else:
        filename, caption = token_body, ""

    filename = os.path.basename(filename.strip())
    caption = caption.strip()
    if not filename:
        return None

    file_ext = os.path.splitext(filename)[1].lower()
    if file_ext not in ALLOWED_IMAGE_EXTENSIONS:
        return None

    file_path = os.path.join(NEWS_IMAGE_DIR, filename)
    if not os.path.exists(file_path):
        return None

    return {
        "filename": filename,
        "caption": caption,
        "src": f"/static/{NEWS_IMAGE_WEB_PATH}/{filename}",
    }


def render_blog_content(content):
    blocks = [block.strip() for block in (content or "").replace("\r\n", "\n").split("\n\n") if block.strip()]
    rendered_blocks = []

    for block in blocks:
        if block.startswith("[image:") and block.endswith("]"):
            image_meta = parse_image_token(block)
            if image_meta:
                caption_html = f"<figcaption>{escape(image_meta['caption'])}</figcaption>" if image_meta["caption"] else ""
                rendered_blocks.append(
                    '<figure class="blog-image">'
                    f'<img src="{escape(image_meta["src"])}" alt="{escape(image_meta["caption"] or image_meta["filename"])}">'
                    f"{caption_html}"
                    "</figure>"
                )
            continue

        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue

        if all(line.startswith("- ") for line in lines):
            items = "".join(f"<li>{render_inline_markup(line[2:].strip())}</li>" for line in lines)
            rendered_blocks.append(f"<ul>{items}</ul>")
            continue

        if all(re.match(r"^\d+\.\s+", line) for line in lines):
            normalized_items = [re.sub(r"^\d+\.\s+", "", line, count=1) for line in lines]
            items = "".join(f"<li>{render_inline_markup(item)}</li>" for item in normalized_items)
            rendered_blocks.append(f"<ol>{items}</ol>")
            continue

        if len(lines) == 1 and lines[0].startswith("### "):
            rendered_blocks.append(f"<h3>{render_inline_markup(lines[0][4:].strip())}</h3>")
            continue

        if len(lines) == 1 and lines[0].startswith("## "):
            rendered_blocks.append(f"<h2>{render_inline_markup(lines[0][3:].strip())}</h2>")
            continue

        if len(lines) == 1 and lines[0].startswith("# "):
            rendered_blocks.append(f"<h1>{render_inline_markup(lines[0][2:].strip())}</h1>")
            continue

        if all(line.startswith("> ") for line in lines):
            quote_html = "<br>".join(render_inline_markup(line[2:].strip()) for line in lines)
            rendered_blocks.append(f"<blockquote>{quote_html}</blockquote>")
            continue

        rendered_blocks.append("<p>" + "<br>".join(render_inline_markup(line) for line in lines) + "</p>")

    return "\n".join(rendered_blocks)


def render_inline_markup(text):
    escaped = escape(text or "")
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", escaped)
    escaped = re.sub(r"\[([^\]]+)\]\((https?://[^\s)]+)\)", r'<a href="\2" target="_blank" rel="noopener noreferrer">\1</a>', escaped)
    return escaped


def render_notification_markup(text):
    lines = [line.strip() for line in (text or "").splitlines()]
    visible_lines = [line for line in lines if line]
    if not visible_lines:
        return "<p></p>"
    return "<p>" + "<br>".join(render_notification_line(line) for line in visible_lines) + "</p>"


def render_chat_message_markup(text):
    lines = [line.strip() for line in (text or "").splitlines()]
    visible_lines = [line for line in lines if line]
    if not visible_lines:
        return ""
    return "<p>" + "<br>".join(render_notification_line(line) for line in visible_lines) + "</p>"


def build_notification_preview(text, limit=160):
    plain_text = re.sub(r"\[([^\]]+)\]\((https?://[^\s)]+)\)", r"\1", text or "")
    plain_text = " ".join(plain_text.split())
    if len(plain_text) <= limit:
        return plain_text
    return plain_text[: limit - 3].rstrip() + "..."


def render_notification_line(text):
    escaped = escape(text or "")
    link_tokens = []

    def replace_markdown_link(match):
        label = match.group(1)
        href = match.group(2)
        token = f"__notification_link_{len(link_tokens)}__"
        link_tokens.append((token, f'<a href="{href}" target="_blank" rel="noopener noreferrer">{label}</a>'))
        return token

    def replace_plain_link(match):
        href = match.group(0)
        token = f"__notification_link_{len(link_tokens)}__"
        link_tokens.append((token, f'<a href="{href}" target="_blank" rel="noopener noreferrer">{href}</a>'))
        return token

    escaped = re.sub(r"\[([^\]]+)\]\((https?://[^\s)]+)\)", replace_markdown_link, escaped)
    escaped = re.sub(r"(?<![\"'=])(https?://[^\s<]+)", replace_plain_link, escaped)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", escaped)

    for token, html in link_tokens:
        escaped = escaped.replace(token, html)
    return escaped


def list_news_images():
    ensure_news_image_folder()
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute("SELECT content FROM news_posts")
    all_content = "\n".join((row["content"] or "") for row in cursor.fetchall())
    connection.close()

    images = []
    for filename in sorted(os.listdir(NEWS_IMAGE_DIR), reverse=True):
        file_path = os.path.join(NEWS_IMAGE_DIR, filename)
        if not os.path.isfile(file_path):
            continue

        file_ext = os.path.splitext(filename)[1].lower()
        if file_ext not in ALLOWED_IMAGE_EXTENSIONS:
            continue

        usage_count = all_content.count(f"[image:{filename}|") + all_content.count(f"[image:{filename}]")
        images.append(
            {
                "filename": filename,
                "src": f"/static/{NEWS_IMAGE_WEB_PATH}/{filename}",
                "token": f"[image:{filename}|Optional caption]",
                "usage_count": usage_count,
                "is_used": usage_count > 0,
            }
        )

    return images


def delete_news_image(filename):
    clean_filename = os.path.basename((filename or "").strip())
    if not clean_filename:
        return False, "Image not found."

    file_ext = os.path.splitext(clean_filename)[1].lower()
    if file_ext not in ALLOWED_IMAGE_EXTENSIONS:
        return False, "Unsupported image type."

    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute("SELECT content FROM news_posts")
    all_content = "\n".join((row["content"] or "") for row in cursor.fetchall())
    connection.close()

    usage_count = all_content.count(f"[image:{clean_filename}|") + all_content.count(f"[image:{clean_filename}]")
    if usage_count > 0:
        return False, "This image is still used in one or more posts."

    file_path = os.path.join(NEWS_IMAGE_DIR, clean_filename)
    if not os.path.exists(file_path):
        return False, "Image not found."

    os.remove(file_path)
    return True, "Image deleted successfully."


def get_news_posts(limit=None, include_archived=False):
    connection = connect_db()
    cursor = connection.cursor()
    where_clause = "" if include_archived else "WHERE is_archived = 0"
    query = """
        SELECT id, title, slug, summary, content, author_username, author_fullname, updated_by_fullname, created_at, updated_at
        FROM news_posts
        {where_clause}
        ORDER BY datetime(updated_at) DESC, id DESC
    """
    query = query.format(where_clause=where_clause)
    if limit is not None:
        query += " LIMIT ?"
        cursor.execute(query, (int(limit),))
    else:
        cursor.execute(query)

    posts = []
    for row in cursor.fetchall():
        post = dict(row)
        post["summary_display"] = build_news_summary(post["summary"], post["content"])
        post["editor_name"] = post.get("updated_by_fullname") or post.get("author_fullname") or post["author_username"]
        posts.append(post)

    connection.close()
    return posts


def get_news_post_by_slug(slug):
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT id, title, slug, summary, content, author_username, author_fullname, updated_by_fullname, created_at, updated_at
        FROM news_posts
        WHERE slug = ?
        """,
        (slug,),
    )
    row = cursor.fetchone()
    connection.close()

    if not row:
        return None

    post = dict(row)
    post["summary_display"] = build_news_summary(post["summary"], post["content"])
    post["content_html"] = render_blog_content(post["content"])
    post["editor_name"] = post.get("updated_by_fullname") or post.get("author_fullname") or post["author_username"]
    return post


def create_news_post(title, summary, content, actor_username, actor_fullname=None):
    title = " ".join((title or "").split())
    summary = (summary or "").strip()
    content = (content or "").strip()

    if not title or not content:
        return False, "Title and content are required."

    connection = connect_db()
    slug = ensure_unique_slug(connection, title)
    connection.execute(
        """
        INSERT INTO news_posts (title, slug, summary, content, author_username, author_fullname, updated_by_fullname, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            title,
            slug,
            summary,
            content,
            actor_username or "System",
            (actor_fullname or "").strip() or actor_username or "System",
            (actor_fullname or "").strip() or actor_username or "System",
            timestamp_now(),
            timestamp_now(),
        ),
    )
    connection.commit()
    connection.close()
    return True, "News post created successfully."


def update_news_post(post_id, title, summary, content, actor_fullname=None):
    title = " ".join((title or "").split())
    summary = (summary or "").strip()
    content = (content or "").strip()

    if not title or not content:
        return False, "Title and content are required."

    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute("SELECT id FROM news_posts WHERE id = ? AND is_archived = 0", (post_id,))
    existing_post = cursor.fetchone()
    if not existing_post:
        connection.close()
        return False, "News post not found."

    slug = ensure_unique_slug(connection, title, exclude_post_id=post_id)
    cursor.execute(
        """
        UPDATE news_posts
        SET title = ?, slug = ?, summary = ?, content = ?, updated_by_fullname = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            title,
            slug,
            summary,
            content,
            (actor_fullname or "").strip() or "System",
            timestamp_now(),
            post_id,
        ),
    )
    connection.commit()
    connection.close()
    return True, "News post updated successfully."


def delete_news_post(post_id):
    return archive_news_post(post_id)


def archive_news_post(post_id):
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute(
        """
        UPDATE news_posts
        SET is_archived = 1, archived_at = ?
        WHERE id = ?
        """,
        (timestamp_now(), post_id),
    )
    if cursor.rowcount == 0:
        connection.close()
        return False, "News post not found."
    connection.commit()
    connection.close()
    return True, "News post archived."


def restore_news_post(post_id):
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute(
        """
        UPDATE news_posts
        SET is_archived = 0, archived_at = NULL
        WHERE id = ?
        """,
        (post_id,),
    )
    if cursor.rowcount == 0:
        connection.close()
        return False, "News post not found."
    connection.commit()
    connection.close()
    return True, "News post restored."


def permanently_delete_news_post(post_id):
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute("DELETE FROM news_posts WHERE id = ? AND is_archived = 1", (post_id,))
    if cursor.rowcount == 0:
        connection.close()
        return False, "Archived news post not found."
    connection.commit()
    connection.close()
    return True, "Archived news post deleted."
