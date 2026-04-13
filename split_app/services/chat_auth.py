import hashlib
import os
import secrets
from datetime import datetime, timedelta

from werkzeug.security import check_password_hash

from split_app.services.content import render_chat_message_markup
from split_app.services.core import (
    CHAT_PRESENCE_WINDOW_SECONDS,
    REMEMBER_ME_DAYS,
    connect_db,
    get_initials,
    hash_password,
    is_password_hash,
    parse_timestamp,
    timestamp_now,
)


def build_direct_room_key(username_a, username_b):
    participants = sorted(
        [(username_a or "").strip().casefold(), (username_b or "").strip().casefold()]
    )
    return f"dm:{participants[0]}|{participants[1]}"


def build_presence_state(last_seen_at, last_login_at):
    now = datetime.now()
    last_seen_dt = parse_timestamp(last_seen_at)
    last_login_dt = parse_timestamp(last_login_at)
    is_online = bool(
        last_seen_dt and (now - last_seen_dt).total_seconds() <= CHAT_PRESENCE_WINDOW_SECONDS
    )
    return {
        "status": "online" if is_online else "offline",
        "is_online": is_online,
        "last_seen_at": last_seen_at or "",
        "last_login_at": last_login_at or "",
        "last_activity_at": last_seen_at or last_login_at or "",
        "status_label": "Online" if is_online else "Offline",
        "last_seen_label": last_seen_at or (last_login_at or "No login recorded"),
        "last_login_label": last_login_at or "No login recorded",
    }


def can_manage_chat(role_names):
    return "superadmin" in {str(role or "").casefold() for role in (role_names or [])} or "developer" in {
        str(role or "").casefold() for role in (role_names or [])
    }


def record_user_login(username):
    clean_username = (username or "").strip()
    if not clean_username:
        return

    now = timestamp_now()
    connection = connect_db()
    connection.execute(
        """
        UPDATE users
        SET last_login_at = ?
        WHERE lower(username) = lower(?)
        """,
        (now, clean_username),
    )
    connection.execute(
        """
        INSERT INTO user_presence (username, last_seen_at, last_login_at, heartbeat_source)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(username) DO UPDATE SET
            last_seen_at = excluded.last_seen_at,
            last_login_at = excluded.last_login_at,
            heartbeat_source = excluded.heartbeat_source
        """,
        (clean_username, now, now, "login"),
    )
    connection.commit()
    connection.close()


def mark_user_presence(username, source="poll"):
    clean_username = (username or "").strip()
    if not clean_username:
        return

    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT last_login_at
        FROM users
        WHERE lower(username) = lower(?)
        """,
        (clean_username,),
    )
    user_row = cursor.fetchone()
    if not user_row:
        connection.close()
        return

    now = timestamp_now()
    connection.execute(
        """
        INSERT INTO user_presence (username, last_seen_at, last_login_at, heartbeat_source)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(username) DO UPDATE SET
            last_seen_at = excluded.last_seen_at,
            last_login_at = COALESCE(user_presence.last_login_at, excluded.last_login_at),
            heartbeat_source = excluded.heartbeat_source
        """,
        (clean_username, now, user_row["last_login_at"], source),
    )
    connection.commit()
    connection.close()


def get_presence_snapshot_map(connection):
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT
            u.username,
            u.last_login_at,
            p.last_seen_at,
            p.last_login_at AS presence_last_login_at
        FROM users u
        LEFT JOIN user_presence p ON lower(p.username) = lower(u.username)
        """
    )
    snapshot = {}
    for row in cursor.fetchall():
        state = build_presence_state(row["last_seen_at"], row["last_login_at"] or row["presence_last_login_at"])
        snapshot[row["username"].casefold()] = state
    return snapshot


def ensure_thread_memberships_for_user(connection, username, role_names):
    from logic import ensure_chat_defaults

    clean_username = (username or "").strip()
    if not clean_username:
        return

    normalized_roles = {role.casefold() for role in (role_names or [])}
    is_superadmin_role = "superadmin" in normalized_roles
    cursor = connection.cursor()
    ensure_chat_defaults(connection)

    if is_superadmin_role:
        cursor.execute(
            """
            SELECT id
            FROM chat_threads
            WHERE (thread_type = 'channel' OR thread_type = 'role') AND is_enabled = 1
            """
        )
    else:
        accessible_roles = [role for role in normalized_roles]
        role_clause = ""
        params = []
        if accessible_roles:
            placeholders = ", ".join("?" for _ in accessible_roles)
            role_clause = f" OR (thread_type = 'role' AND is_enabled = 1 AND lower(role_name) IN ({placeholders}))"
            params.extend(accessible_roles)
        cursor.execute(
            f"""
            SELECT id
            FROM chat_threads
            WHERE (thread_type = 'channel' AND is_enabled = 1){role_clause}
            """,
            tuple(params),
        )

    thread_ids = [row["id"] for row in cursor.fetchall()]
    if not thread_ids:
        return

    now = timestamp_now()
    cursor.executemany(
        """
        INSERT OR IGNORE INTO chat_thread_members (thread_id, username, joined_at, last_read_at)
        VALUES (?, ?, ?, ?)
        """,
        [(thread_id, clean_username, now, now) for thread_id in thread_ids],
    )


def ensure_direct_thread(connection, username, other_username):
    from logic import build_profile_identity

    clean_username = (username or "").strip()
    clean_other_username = (other_username or "").strip()
    if not clean_username or not clean_other_username:
        return None, None, "Direct message target is required."
    if clean_username.casefold() == clean_other_username.casefold():
        return None, None, "You cannot open a direct chat with yourself."

    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT id, username, password, designation, userlevel, fullname, date_created, last_login_at
        FROM users
        WHERE lower(username) IN (lower(?), lower(?))
        """,
        (clean_username, clean_other_username),
    )
    users = {row["username"].casefold(): row for row in cursor.fetchall()}
    current_user = users.get(clean_username.casefold())
    other_user = users.get(clean_other_username.casefold())
    if not current_user or not other_user:
        return None, None, "User not found."

    room_key = build_direct_room_key(current_user["username"], other_user["username"])
    cursor.execute(
        """
        SELECT *
        FROM chat_threads
        WHERE room_key = ?
        """,
        (room_key,),
    )
    thread = cursor.fetchone()
    now = timestamp_now()
    if not thread:
        cursor.execute(
            """
            INSERT INTO chat_threads (
                room_key,
                thread_type,
                title,
                description,
                role_name,
                is_enabled,
                created_by_username,
                updated_by_username,
                created_at,
                updated_at
            )
            VALUES (?, 'direct', ?, ?, NULL, 1, ?, ?, ?, ?)
            """,
            (room_key, "Direct Message", "", current_user["username"], current_user["username"], now, now),
        )
        thread_id = cursor.lastrowid
        cursor.executemany(
            """
            INSERT OR IGNORE INTO chat_thread_members (thread_id, username, joined_at, last_read_at)
            VALUES (?, ?, ?, ?)
            """,
            [
                (thread_id, current_user["username"], now, now),
                (thread_id, other_user["username"], now, None),
            ],
        )
        cursor.execute("SELECT * FROM chat_threads WHERE id = ?", (thread_id,))
        thread = cursor.fetchone()
    else:
        thread_id = thread["id"]
        cursor.executemany(
            """
            INSERT OR IGNORE INTO chat_thread_members (thread_id, username, joined_at, last_read_at)
            VALUES (?, ?, ?, ?)
            """,
            [
                (thread_id, current_user["username"], now, now),
                (thread_id, other_user["username"], now, None),
            ],
        )

    other_identity = build_profile_identity(connection, other_user, viewer_username=clean_username)
    return dict(thread), other_identity, ""


def resolve_chat_thread(connection, username, role_names, thread_type, target):
    from logic import ensure_chat_defaults

    clean_username = (username or "").strip()
    normalized_roles = {role.casefold() for role in (role_names or [])}
    ensure_chat_defaults(connection)
    cursor = connection.cursor()

    if thread_type == "direct":
        return ensure_direct_thread(connection, clean_username, target)

    if thread_type == "channel":
        if (target or "").startswith("channel:"):
            room_key = target
        else:
            try:
                room_key = f"channel:{int(target)}"
            except (TypeError, ValueError):
                return None, None, "Channel not found."
        cursor.execute(
            """
            SELECT *
            FROM chat_threads
            WHERE room_key = ? AND thread_type = 'channel'
            """,
            (room_key,),
        )
        thread = cursor.fetchone()
        if not thread:
            return None, None, "Channel not found."
        if not thread["is_enabled"]:
            return None, None, "This channel is currently disabled."
        return dict(thread), None, ""

    if thread_type == "role":
        room_key = target if (target or "").startswith("role:") else f"role:{(target or '').strip().casefold()}"
        cursor.execute(
            """
            SELECT *
            FROM chat_threads
            WHERE room_key = ? AND thread_type = 'role'
            """,
            (room_key,),
        )
        thread = cursor.fetchone()
        if not thread:
            return None, None, "Role group not found."
        if not thread["is_enabled"]:
            return None, None, "This role group is currently disabled."
        if "superadmin" not in normalized_roles and (thread["role_name"] or "").casefold() not in normalized_roles:
            return None, None, "You do not have access to this role group."
        return dict(thread), None, ""

    return None, None, "Unsupported chat type."


def ensure_member_record(connection, thread_id, username, *, initial_read_at=None):
    clean_username = (username or "").strip()
    if not clean_username:
        return
    now = timestamp_now()
    connection.execute(
        """
        INSERT OR IGNORE INTO chat_thread_members (thread_id, username, joined_at, last_read_at)
        VALUES (?, ?, ?, ?)
        """,
        (thread_id, clean_username, now, initial_read_at),
    )


def mark_chat_thread_read(connection, thread_id, username):
    clean_username = (username or "").strip()
    if not clean_username:
        return
    ensure_member_record(connection, thread_id, clean_username, initial_read_at=timestamp_now())
    connection.execute(
        """
        UPDATE chat_thread_members
        SET last_read_at = ?
        WHERE thread_id = ? AND lower(username) = lower(?)
        """,
        (timestamp_now(), thread_id, clean_username),
    )


def build_chat_message_preview(body, attachment_name=None, limit=72):
    text = " ".join((body or "").split())
    if text:
        if len(text) > limit:
            text = text[: limit - 3].rstrip() + "..."
        return text
    if attachment_name:
        return attachment_name
    return "No messages yet"


def normalize_chat_favorite_target(username):
    return (username or "").strip()


def compact_chat_favorite_order(connection, owner_username):
    clean_owner_username = normalize_chat_favorite_target(owner_username)
    if not clean_owner_username:
        return

    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT favorite_username
        FROM chat_favorites
        WHERE lower(owner_username) = lower(?)
        ORDER BY sort_order, favorite_username COLLATE NOCASE
        """,
        (clean_owner_username,),
    )
    rows = cursor.fetchall()
    for index, row in enumerate(rows, start=1):
        connection.execute(
            """
            UPDATE chat_favorites
            SET sort_order = ?, updated_at = ?
            WHERE lower(owner_username) = lower(?) AND lower(favorite_username) = lower(?)
            """,
            (index, timestamp_now(), clean_owner_username, row["favorite_username"]),
        )


def get_chat_favorite_map(connection, owner_username):
    clean_owner_username = normalize_chat_favorite_target(owner_username)
    if not clean_owner_username:
        return {}

    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT favorite_username, sort_order
        FROM chat_favorites
        WHERE lower(owner_username) = lower(?)
        ORDER BY sort_order, favorite_username COLLATE NOCASE
        """,
        (clean_owner_username,),
    )
    return {
        row["favorite_username"].casefold(): {
            "username": row["favorite_username"],
            "sort_order": int(row["sort_order"] or 0),
        }
        for row in cursor.fetchall()
    }


def is_chat_favorite(owner_username, target_username):
    clean_owner_username = normalize_chat_favorite_target(owner_username)
    clean_target_username = normalize_chat_favorite_target(target_username)
    if not clean_owner_username or not clean_target_username:
        return False

    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT 1
        FROM chat_favorites
        WHERE lower(owner_username) = lower(?) AND lower(favorite_username) = lower(?)
        """,
        (clean_owner_username, clean_target_username),
    )
    row = cursor.fetchone()
    connection.close()
    return bool(row)


def set_chat_favorite(owner_username, target_username, is_favorite=True):
    clean_owner_username = normalize_chat_favorite_target(owner_username)
    clean_target_username = normalize_chat_favorite_target(target_username)
    if not clean_owner_username:
        return False, "Authentication required."
    if not clean_target_username:
        return False, "A username is required."
    if clean_owner_username.casefold() == clean_target_username.casefold():
        return False, "You cannot favorite yourself."

    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT username
        FROM users
        WHERE lower(username) = lower(?)
        """,
        (clean_target_username,),
    )
    target_row = cursor.fetchone()
    if not target_row:
        connection.close()
        return False, "User not found."

    canonical_target_username = target_row["username"]
    if is_favorite:
        cursor.execute(
            """
            SELECT COALESCE(MAX(sort_order), 0) AS max_sort_order
            FROM chat_favorites
            WHERE lower(owner_username) = lower(?)
            """,
            (clean_owner_username,),
        )
        max_sort_row = cursor.fetchone()
        next_sort_order = int(max_sort_row["max_sort_order"] or 0) + 1 if max_sort_row else 1
        connection.execute(
            """
            INSERT OR IGNORE INTO chat_favorites (
                owner_username,
                favorite_username,
                sort_order,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                clean_owner_username,
                canonical_target_username,
                next_sort_order,
                timestamp_now(),
                timestamp_now(),
            ),
        )
        compact_chat_favorite_order(connection, clean_owner_username)
        connection.commit()
        connection.close()
        return True, "User added to favorites."

    connection.execute(
        """
        DELETE FROM chat_favorites
        WHERE lower(owner_username) = lower(?) AND lower(favorite_username) = lower(?)
        """,
        (clean_owner_username, canonical_target_username),
    )
    compact_chat_favorite_order(connection, clean_owner_username)
    connection.commit()
    connection.close()
    return True, "User removed from favorites."


def move_chat_favorite(owner_username, target_username, direction):
    clean_owner_username = normalize_chat_favorite_target(owner_username)
    clean_target_username = normalize_chat_favorite_target(target_username)
    clean_direction = (direction or "").strip().lower()
    if not clean_owner_username:
        return False, "Authentication required."
    if clean_direction not in {"up", "down"}:
        return False, "Unsupported favorite move."

    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT favorite_username
        FROM chat_favorites
        WHERE lower(owner_username) = lower(?)
        ORDER BY sort_order, favorite_username COLLATE NOCASE
        """,
        (clean_owner_username,),
    )
    ordered_rows = [row["favorite_username"] for row in cursor.fetchall()]
    current_index = next(
        (
            index
            for index, favorite_username in enumerate(ordered_rows)
            if favorite_username.casefold() == clean_target_username.casefold()
        ),
        -1,
    )
    if current_index < 0:
        connection.close()
        return False, "Favorite not found."

    swap_index = current_index - 1 if clean_direction == "up" else current_index + 1
    if swap_index < 0 or swap_index >= len(ordered_rows):
        connection.close()
        return False, "Favorite is already at that edge."

    ordered_rows[current_index], ordered_rows[swap_index] = ordered_rows[swap_index], ordered_rows[current_index]
    for index, favorite_username in enumerate(ordered_rows, start=1):
        connection.execute(
            """
            UPDATE chat_favorites
            SET sort_order = ?, updated_at = ?
            WHERE lower(owner_username) = lower(?) AND lower(favorite_username) = lower(?)
            """,
            (index, timestamp_now(), clean_owner_username, favorite_username),
        )

    connection.commit()
    connection.close()
    return True, "Favorite order updated."


def get_chat_overview(username, role_names):
    from logic import ensure_chat_defaults, get_profile_identity_map

    clean_username = (username or "").strip()
    if not clean_username:
        return {
            "channels": [],
            "role_groups": [],
            "direct_threads": [],
            "users": [],
            "unread_total": 0,
        }

    connection = connect_db()
    ensure_chat_defaults(connection)
    ensure_thread_memberships_for_user(connection, clean_username, role_names)
    cursor = connection.cursor()
    normalized_roles = {role.casefold() for role in (role_names or [])}
    is_superadmin_role = "superadmin" in normalized_roles
    favorite_map = get_chat_favorite_map(connection, clean_username)

    cursor.execute(
        """
        SELECT t.*, m.last_read_at
        FROM chat_threads t
        LEFT JOIN chat_thread_members m
            ON m.thread_id = t.id AND lower(m.username) = lower(?)
        WHERE t.thread_type = 'channel' AND t.is_enabled = 1
        ORDER BY CAST(substr(t.room_key, 9) AS INTEGER), t.id
        """,
        (clean_username,),
    )
    channel_rows = [dict(row) for row in cursor.fetchall()]

    if is_superadmin_role:
        cursor.execute(
            """
            SELECT t.*, m.last_read_at
            FROM chat_threads t
            LEFT JOIN chat_thread_members m
                ON m.thread_id = t.id AND lower(m.username) = lower(?)
            WHERE t.thread_type = 'role' AND t.is_enabled = 1
            ORDER BY t.title COLLATE NOCASE, t.id
            """,
            (clean_username,),
        )
    else:
        accessible_roles = [role for role in normalized_roles]
        if accessible_roles:
            placeholders = ", ".join("?" for _ in accessible_roles)
            cursor.execute(
                f"""
                SELECT t.*, m.last_read_at
                FROM chat_threads t
                LEFT JOIN chat_thread_members m
                    ON m.thread_id = t.id AND lower(m.username) = lower(?)
                WHERE t.thread_type = 'role'
                  AND t.is_enabled = 1
                  AND lower(t.role_name) IN ({placeholders})
                ORDER BY t.title COLLATE NOCASE, t.id
                """,
                (clean_username, *accessible_roles),
            )
        else:
            cursor.execute(
                """
                SELECT t.*, m.last_read_at
                FROM chat_threads t
                LEFT JOIN chat_thread_members m
                    ON m.thread_id = t.id AND lower(m.username) = lower(?)
                WHERE 1 = 0
                """,
                (clean_username,),
            )
    role_rows = [dict(row) for row in cursor.fetchall()]

    cursor.execute(
        """
        SELECT t.*, m.last_read_at
        FROM chat_threads t
        INNER JOIN chat_thread_members m
            ON m.thread_id = t.id AND lower(m.username) = lower(?)
        WHERE t.thread_type = 'direct'
        ORDER BY datetime(t.updated_at) DESC, t.id DESC
        """,
        (clean_username,),
    )
    direct_rows = [dict(row) for row in cursor.fetchall()]

    all_thread_rows = channel_rows + role_rows + direct_rows
    thread_ids = [row["id"] for row in all_thread_rows]
    unread_map = {}
    last_message_map = {}
    member_count_map = {}
    direct_partner_map = {}

    if thread_ids:
        placeholders = ", ".join("?" for _ in thread_ids)
        cursor.execute(
            f"""
            SELECT thread_id, COUNT(*) AS member_count
            FROM chat_thread_members
            WHERE thread_id IN ({placeholders})
            GROUP BY thread_id
            """,
            tuple(thread_ids),
        )
        member_count_map = {row["thread_id"]: int(row["member_count"] or 0) for row in cursor.fetchall()}

        cursor.execute(
            f"""
            SELECT m.thread_id, COUNT(*) AS unread_count
            FROM chat_messages m
            LEFT JOIN chat_thread_members tm
                ON tm.thread_id = m.thread_id AND lower(tm.username) = lower(?)
            WHERE m.thread_id IN ({placeholders})
              AND lower(m.sender_username) <> lower(?)
              AND (tm.last_read_at IS NULL OR datetime(m.created_at) > datetime(tm.last_read_at))
            GROUP BY m.thread_id
            """,
            (clean_username, *thread_ids, clean_username),
        )
        unread_map = {row["thread_id"]: row["unread_count"] for row in cursor.fetchall()}

        cursor.execute(
            f"""
            SELECT cm.*
            FROM chat_messages cm
            INNER JOIN (
                SELECT thread_id, MAX(id) AS max_id
                FROM chat_messages
                WHERE thread_id IN ({placeholders})
                GROUP BY thread_id
            ) latest ON latest.max_id = cm.id
            """,
            tuple(thread_ids),
        )
        last_message_map = {row["thread_id"]: dict(row) for row in cursor.fetchall()}

        direct_thread_ids = [row["id"] for row in direct_rows]
        if direct_thread_ids:
            direct_placeholders = ", ".join("?" for _ in direct_thread_ids)
            cursor.execute(
                f"""
                SELECT tm.thread_id, u.username, u.last_login_at
                FROM chat_thread_members tm
                INNER JOIN users u ON lower(u.username) = lower(tm.username)
                WHERE tm.thread_id IN ({direct_placeholders})
                  AND lower(tm.username) <> lower(?)
                """,
                (*direct_thread_ids, clean_username),
            )
            direct_partner_map = {row["thread_id"]: dict(row) for row in cursor.fetchall()}

    presence_map = get_presence_snapshot_map(connection)
    cursor.execute(
        """
        SELECT u.id, u.username, u.password, u.designation, u.userlevel, u.fullname, u.date_created, u.last_login_at
        FROM users u
        WHERE lower(u.username) <> lower(?)
        ORDER BY u.fullname COLLATE NOCASE, u.username COLLATE NOCASE
        """,
        (clean_username,),
    )
    online_user_rows = [dict(row) for row in cursor.fetchall()]
    identity_lookup_usernames = {clean_username}
    for partner in direct_partner_map.values():
        identity_lookup_usernames.add(partner["username"])
    for row in online_user_rows:
        identity_lookup_usernames.add(row["username"])
    for message_row in last_message_map.values():
        identity_lookup_usernames.add(message_row["sender_username"])
    identity_map = get_profile_identity_map(connection, sorted(identity_lookup_usernames), viewer_username=clean_username)

    def enrich_thread(row, *, direct_partner=None):
        last_message = last_message_map.get(row["id"])
        sender_identity = identity_map.get((last_message.get("sender_username") or "").casefold()) if last_message else None
        item = {
            "room_key": row["room_key"],
            "thread_type": row["thread_type"],
            "title": row["title"],
            "description": row["description"] or "",
            "member_count": int(member_count_map.get(row["id"], 0) or 0),
            "unread_count": int(unread_map.get(row["id"], 0) or 0),
            "last_message_preview": build_chat_message_preview(
                last_message.get("body") if last_message else "",
                last_message.get("attachment_name") if last_message else "",
            ),
            "last_message_at": last_message.get("created_at") if last_message else row["updated_at"],
            "last_message_sender_name": (
                (
                    (sender_identity.get("display_name") if sender_identity else "")
                    or (last_message.get("sender_fullname") or "").strip()
                    or last_message.get("sender_username", "")
                )
                if last_message else ""
            ),
            "last_message_sender_username": last_message.get("sender_username") if last_message else "",
            "last_message_is_self": bool(
                last_message and (last_message.get("sender_username") or "").casefold() == clean_username.casefold()
            ),
            "last_message_has_attachment": bool(last_message and last_message.get("attachment_name")),
            "last_message_attachment_kind": last_message.get("attachment_kind") if last_message else "",
            "editable": row["thread_type"] == "channel",
        }
        if row["thread_type"] == "role":
            item["role_name"] = row["role_name"]
        if direct_partner:
            partner_identity = identity_map.get(direct_partner["username"].casefold())
            partner_state = presence_map.get(
                direct_partner["username"].casefold(),
                build_presence_state("", direct_partner.get("last_login_at")),
            )
            favorite_state = favorite_map.get(direct_partner["username"].casefold())
            item.update(
                {
                    "target_username": direct_partner["username"],
                    "title": (partner_identity.get("display_name") if partner_identity else "") or direct_partner["username"],
                    "description": (partner_identity.get("designation") if partner_identity else "") or "",
                    "presence": partner_state["status"],
                    "presence_label": partner_state["status_label"],
                    "last_seen_at": partner_state["last_seen_at"],
                    "last_login_at": partner_state["last_login_at"],
                    "avatar_url": (partner_identity.get("avatar_url") if partner_identity else "") or "",
                    "avatar_initials": (partner_identity.get("avatar_initials") if partner_identity else get_initials(direct_partner["username"], "U")),
                    "profile_url": (partner_identity.get("profile_url") if partner_identity else f"/users/{direct_partner['username']}"),
                    "is_favorite": bool(favorite_state),
                    "favorite_sort_order": int(favorite_state["sort_order"]) if favorite_state else None,
                }
            )
        return item

    channels = [enrich_thread(row) for row in channel_rows]
    role_groups = [enrich_thread(row) for row in role_rows]
    direct_threads = [enrich_thread(row, direct_partner=direct_partner_map.get(row["id"])) for row in direct_rows]

    users = []
    for row in online_user_rows:
        identity = identity_map.get(row["username"].casefold())
        state = presence_map.get(row["username"].casefold(), build_presence_state("", row["last_login_at"]))
        users.append(
            {
                "username": row["username"],
                "fullname": (identity.get("display_name") if identity else "") or row["username"],
                "display_name": (identity.get("display_name") if identity else "") or row["username"],
                "designation": (identity.get("designation") if identity else "") or "",
                "room_key": build_direct_room_key(clean_username, row["username"]),
                "presence": state["status"],
                "presence_label": state["status_label"],
                "last_seen_at": state["last_seen_at"],
                "last_login_at": state["last_login_at"],
                "last_seen_label": state["last_seen_label"],
                "avatar_url": (identity.get("avatar_url") if identity else "") or "",
                "avatar_initials": (identity.get("avatar_initials") if identity else get_initials(row["username"], "U")),
                "profile_url": (identity.get("profile_url") if identity else f"/users/{row['username']}"),
                "is_favorite": row["username"].casefold() in favorite_map,
                "favorite_sort_order": (
                    int(favorite_map[row["username"].casefold()]["sort_order"])
                    if row["username"].casefold() in favorite_map
                    else None
                ),
            }
        )

    direct_threads.sort(
        key=lambda item: (
            0 if item.get("is_favorite") else 1,
            int(item.get("favorite_sort_order") or 999999),
            -(parse_timestamp(item.get("last_message_at")).timestamp() if parse_timestamp(item.get("last_message_at")) else 0),
            item["title"].casefold(),
        )
    )
    users.sort(
        key=lambda item: (
            0 if item["is_favorite"] else 1,
            int(item["favorite_sort_order"] or 999999),
            0 if item["presence"] == "online" else 1,
            item["fullname"].casefold(),
            item["username"].casefold(),
        )
    )
    favorites = [item for item in users if item["is_favorite"]]
    connection.commit()
    connection.close()
    return {
        "channels": channels,
        "role_groups": role_groups,
        "direct_threads": direct_threads,
        "users": users,
        "favorites": favorites,
        "unread_total": sum(item["unread_count"] for item in channels + role_groups + direct_threads),
    }


def build_chat_attachment_payload(attachment_path, attachment_name, attachment_kind):
    if not attachment_path:
        return None
    return {
        "url": f"/static/{attachment_path}",
        "name": attachment_name or os.path.basename(attachment_path),
        "kind": attachment_kind or "file",
    }


def build_chat_message_payload(row, username, sender_identity=None):
    clean_username = (username or "").strip()
    attachment = build_chat_attachment_payload(row.get("attachment_path"), row.get("attachment_name"), row.get("attachment_kind"))
    display_name = (
        (sender_identity.get("display_name") if sender_identity else "")
        or (row.get("sender_fullname") or "").strip()
        or row["sender_username"]
    )
    is_deleted = bool(row.get("is_deleted"))
    edited_at = row.get("edited_at") or ""
    body_html = "<p><em>Message deleted.</em></p>" if is_deleted else render_chat_message_markup(row.get("body"))
    return {
        "id": row["id"],
        "sender_username": row["sender_username"],
        "sender_fullname": display_name,
        "sender_avatar_url": (sender_identity.get("avatar_url") if sender_identity else "") or "",
        "sender_avatar_initials": (sender_identity.get("avatar_initials") if sender_identity else get_initials(display_name, "U")),
        "sender_profile_url": (sender_identity.get("profile_url") if sender_identity else f"/users/{row['sender_username']}"),
        "created_at": row["created_at"],
        "is_self": row["sender_username"].casefold() == clean_username.casefold(),
        "body": "" if is_deleted else (row.get("body") or ""),
        "body_html": body_html,
        "attachment": None if is_deleted else attachment,
        "is_deleted": is_deleted,
        "edited_at": edited_at,
        "is_edited": bool(edited_at and not is_deleted),
        "can_edit": row["sender_username"].casefold() == clean_username.casefold() and not is_deleted,
        "can_delete": (row["sender_username"].casefold() == clean_username.casefold() or bool(row.get("viewer_can_moderate"))) and not is_deleted,
    }


def get_chat_thread_messages(username, fullname, role_names, thread_type, target, limit=80, before_id=None, after_id=None):
    from logic import ensure_chat_defaults, get_profile_identity_map

    clean_username = (username or "").strip()
    if not clean_username:
        return False, "Authentication required.", None

    connection = connect_db()
    ensure_chat_defaults(connection)
    if thread_type in {"channel", "role"}:
        ensure_thread_memberships_for_user(connection, clean_username, role_names)

    thread, direct_partner, error_message = resolve_chat_thread(connection, clean_username, role_names, thread_type, target)
    if not thread:
        connection.close()
        return False, error_message, None

    ensure_member_record(connection, thread["id"], clean_username, initial_read_at=timestamp_now())
    cursor = connection.cursor()
    page_size = max(1, min(int(limit or 80), 200))
    viewer_can_moderate = 1 if can_manage_chat(role_names) else 0

    if after_id is not None:
        cursor.execute(
            """
            SELECT id, sender_username, sender_fullname, body, attachment_path, attachment_name, attachment_kind, created_at, edited_at, is_deleted, ? AS viewer_can_moderate
            FROM chat_messages
            WHERE thread_id = ? AND id > ?
            ORDER BY id ASC
            LIMIT ?
            """,
            (viewer_can_moderate, thread["id"], int(after_id), page_size),
        )
        rows = [dict(row) for row in cursor.fetchall()]
    elif before_id is not None:
        cursor.execute(
            """
            SELECT id, sender_username, sender_fullname, body, attachment_path, attachment_name, attachment_kind, created_at, edited_at, is_deleted, ? AS viewer_can_moderate
            FROM chat_messages
            WHERE thread_id = ? AND id < ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (viewer_can_moderate, thread["id"], int(before_id), page_size),
        )
        rows = list(reversed([dict(row) for row in cursor.fetchall()]))
    else:
        cursor.execute(
            """
            SELECT id, sender_username, sender_fullname, body, attachment_path, attachment_name, attachment_kind, created_at, edited_at, is_deleted, ? AS viewer_can_moderate
            FROM chat_messages
            WHERE thread_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (viewer_can_moderate, thread["id"], page_size),
        )
        rows = list(reversed([dict(row) for row in cursor.fetchall()]))

    cursor.execute(
        """
        SELECT COUNT(*) AS total_count, MIN(id) AS oldest_id, MAX(id) AS newest_id
        FROM chat_messages
        WHERE thread_id = ?
        """,
        (thread["id"],),
    )
    thread_stats = dict(cursor.fetchone() or {})
    cursor.execute(
        """
        SELECT COUNT(*) AS member_count
        FROM chat_thread_members
        WHERE thread_id = ?
        """,
        (thread["id"],),
    )
    member_row = cursor.fetchone()
    member_count = int(member_row["member_count"] or 0) if member_row else 0
    sender_identities = get_profile_identity_map(
        connection,
        [row["sender_username"] for row in rows],
        viewer_username=clean_username,
    )
    messages = [
        build_chat_message_payload(
            row,
            clean_username,
            sender_identities.get((row.get("sender_username") or "").casefold()),
        )
        for row in rows
    ]
    window_oldest_id = messages[0]["id"] if messages else None
    window_newest_id = messages[-1]["id"] if messages else None
    thread_oldest_id = thread_stats.get("oldest_id")
    thread_newest_id = thread_stats.get("newest_id")

    mark_chat_thread_read(connection, thread["id"], clean_username)
    connection.commit()

    thread_payload = {
        "room_key": thread["room_key"],
        "thread_type": thread["thread_type"],
        "title": thread["title"],
        "description": thread["description"] or "",
        "member_count": member_count,
        "editable": thread["thread_type"] == "channel" and can_manage_chat(role_names),
    }
    if thread["thread_type"] == "direct" and direct_partner:
        presence_map = get_presence_snapshot_map(connection)
        thread_payload["title"] = (direct_partner.get("display_name") or "").strip() or direct_partner["username"]
        thread_payload["description"] = direct_partner.get("designation") or ""
        thread_payload["target_username"] = direct_partner["username"]
        thread_payload["avatar_url"] = direct_partner.get("avatar_url") or ""
        thread_payload["avatar_initials"] = direct_partner.get("avatar_initials") or get_initials(direct_partner["username"], "U")
        thread_payload["profile_url"] = direct_partner.get("profile_url") or f"/users/{direct_partner['username']}"
        thread_payload["presence"] = presence_map.get(
            direct_partner["username"].casefold(),
            build_presence_state("", direct_partner.get("last_login_at")),
        )

    connection.close()
    return True, "Thread loaded.", {
        "thread": thread_payload,
        "messages": messages,
        "message_meta": {
            "total_count": int(thread_stats.get("total_count") or 0),
            "thread_oldest_id": thread_oldest_id,
            "thread_newest_id": thread_newest_id,
            "window_oldest_id": window_oldest_id,
            "window_newest_id": window_newest_id,
            "returned_count": len(messages),
            "has_more_before": bool(messages and thread_oldest_id is not None and window_oldest_id and window_oldest_id > thread_oldest_id),
            "has_more_after": bool(messages and thread_newest_id is not None and window_newest_id and window_newest_id < thread_newest_id),
        },
    }


def create_chat_message(username, fullname, role_names, thread_type, target, body, attachment_meta=None):
    from logic import ensure_chat_defaults

    clean_username = (username or "").strip()
    clean_body = (body or "").strip()
    if not clean_username:
        return False, "Authentication required."
    if not clean_body and not attachment_meta:
        return False, "Enter a message or attach a file."

    connection = connect_db()
    ensure_chat_defaults(connection)
    if thread_type in {"channel", "role"}:
        ensure_thread_memberships_for_user(connection, clean_username, role_names)

    thread, direct_partner, error_message = resolve_chat_thread(connection, clean_username, role_names, thread_type, target)
    if not thread:
        connection.close()
        return False, error_message

    now = timestamp_now()
    ensure_member_record(connection, thread["id"], clean_username, initial_read_at=now)
    connection.execute(
        """
        INSERT INTO chat_messages (
            thread_id,
            sender_username,
            sender_fullname,
            body,
            attachment_path,
            attachment_name,
            attachment_kind,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            thread["id"],
            clean_username,
            (fullname or "").strip() or clean_username,
            clean_body or None,
            attachment_meta.get("path") if attachment_meta else None,
            attachment_meta.get("name") if attachment_meta else None,
            attachment_meta.get("kind") if attachment_meta else None,
            now,
        ),
    )
    connection.execute(
        """
        UPDATE chat_threads
        SET updated_at = ?, updated_by_username = ?
        WHERE id = ?
        """,
        (now, clean_username, thread["id"]),
    )
    mark_chat_thread_read(connection, thread["id"], clean_username)
    if thread["thread_type"] == "direct" and direct_partner:
        ensure_member_record(connection, thread["id"], direct_partner["username"], initial_read_at=None)
    connection.commit()
    connection.close()
    return True, "Message sent."


def update_chat_channel(room_key, title, description, actor_username):
    clean_title = " ".join((title or "").split())
    clean_description = (description or "").strip()
    if not clean_title:
        return False, "Channel title is required."

    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute(
        """
        UPDATE chat_threads
        SET title = ?, description = ?, updated_by_username = ?, updated_at = ?
        WHERE room_key = ? AND thread_type = 'channel'
        """,
        (clean_title, clean_description, (actor_username or "").strip() or "System", timestamp_now(), room_key),
    )
    if cursor.rowcount == 0:
        connection.close()
        return False, "Channel not found."
    connection.commit()
    connection.close()
    return True, "Channel updated."


def get_channel_settings():
    from logic import ensure_chat_defaults

    connection = connect_db()
    ensure_chat_defaults(connection)
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT room_key, title, description, is_enabled, updated_at
        FROM chat_threads
        WHERE thread_type = 'channel'
        ORDER BY id
        """
    )
    items = [dict(row) for row in cursor.fetchall()]
    connection.commit()
    connection.close()
    return items


def update_channel_settings(room_key, title, description, is_enabled, actor_username):
    clean_title = " ".join((title or "").split())
    clean_description = (description or "").strip()
    if not clean_title:
        return False, "Channel title is required."

    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute(
        """
        UPDATE chat_threads
        SET title = ?, description = ?, is_enabled = ?, updated_by_username = ?, updated_at = ?
        WHERE room_key = ? AND thread_type = 'channel'
        """,
        (
            clean_title,
            clean_description,
            1 if is_enabled else 0,
            (actor_username or "").strip() or "System",
            timestamp_now(),
            room_key,
        ),
    )
    if cursor.rowcount == 0:
        connection.close()
        return False, "Channel not found."
    connection.commit()
    connection.close()
    return True, "Channel updated."


def get_role_group_settings():
    from logic import ensure_chat_defaults

    connection = connect_db()
    ensure_chat_defaults(connection)
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT room_key, title, description, role_name, is_enabled, updated_at
        FROM chat_threads
        WHERE thread_type = 'role'
        ORDER BY title COLLATE NOCASE, id
        """
    )
    items = [dict(row) for row in cursor.fetchall()]
    connection.commit()
    connection.close()
    return items


def update_role_group(room_key, title, description, is_enabled, actor_username):
    clean_title = " ".join((title or "").split())
    clean_description = (description or "").strip()
    enabled_value = 1 if is_enabled else 0
    if not clean_title:
        return False, "Role group title is required."

    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute(
        """
        UPDATE chat_threads
        SET title = ?, description = ?, is_enabled = ?, updated_by_username = ?, updated_at = ?
        WHERE room_key = ? AND thread_type = 'role'
        """,
        (
            clean_title,
            clean_description,
            enabled_value,
            (actor_username or "").strip() or "System",
            timestamp_now(),
            room_key,
        ),
    )
    if cursor.rowcount == 0:
        connection.close()
        return False, "Role group not found."
    connection.commit()
    connection.close()
    return True, "Role group updated."


def update_chat_message(message_id, username, role_names, body):
    clean_body = str(body or "").strip()
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT id, sender_username, attachment_path, is_deleted
        FROM chat_messages
        WHERE id = ?
        """,
        (message_id,),
    )
    message_row = cursor.fetchone()
    if not message_row:
        connection.close()
        return False, "Message not found."
    if message_row["sender_username"].casefold() != (username or "").casefold():
        connection.close()
        return False, "Only the sender can edit this message."
    if message_row["is_deleted"]:
        connection.close()
        return False, "Deleted messages cannot be edited."
    if not clean_body and not message_row["attachment_path"]:
        connection.close()
        return False, "Message body cannot be blank."

    connection.execute(
        """
        UPDATE chat_messages
        SET body = ?, edited_at = ?, edited_by_username = ?
        WHERE id = ?
        """,
        (clean_body or None, timestamp_now(), username, message_id),
    )
    connection.commit()
    connection.close()
    return True, "Message updated."


def delete_chat_message(message_id, username, role_names):
    role_keys = {str(role or "").casefold() for role in (role_names or [])}
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT id, sender_username, attachment_path, is_deleted
        FROM chat_messages
        WHERE id = ?
        """,
        (message_id,),
    )
    message_row = cursor.fetchone()
    if not message_row:
        connection.close()
        return False, "Message not found."
    if message_row["is_deleted"]:
        connection.close()
        return False, "Message already deleted."
    can_delete = message_row["sender_username"].casefold() == (username or "").casefold() or bool(
        {"superadmin", "developer"} & role_keys
    )
    if not can_delete:
        connection.close()
        return False, "You do not have permission to delete this message."

    attachment_path = (message_row["attachment_path"] or "").strip()
    if attachment_path:
        absolute_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "static", attachment_path)
        if os.path.exists(absolute_path):
            os.remove(absolute_path)
    connection.execute(
        """
        UPDATE chat_messages
        SET
            body = NULL,
            attachment_path = NULL,
            attachment_name = NULL,
            attachment_kind = NULL,
            is_deleted = 1,
            deleted_at = ?,
            deleted_by_username = ?,
            edited_at = NULL,
            edited_by_username = NULL
        WHERE id = ?
        """,
        (timestamp_now(), username, message_id),
    )
    connection.commit()
    connection.close()
    return True, "Message deleted."


def hash_remember_token(token):
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def purge_expired_remember_tokens(connection):
    connection.execute(
        """
        DELETE FROM remember_tokens
        WHERE datetime(expires_at) <= datetime(?)
        """,
        (timestamp_now(),),
    )


def create_remember_me_token(username, days=REMEMBER_ME_DAYS):
    username = (username or "").strip()
    if not username:
        return None

    connection = connect_db()
    purge_expired_remember_tokens(connection)

    selector = secrets.token_urlsafe(9)
    raw_token = secrets.token_urlsafe(32)
    expires_at = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")

    connection.execute(
        """
        INSERT INTO remember_tokens (username, selector, token_hash, expires_at, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (username, selector, hash_remember_token(raw_token), expires_at, timestamp_now()),
    )
    connection.commit()
    connection.close()
    return f"{selector}.{raw_token}"


def consume_remember_me_token(cookie_value):
    if not cookie_value or "." not in cookie_value:
        return None

    selector, raw_token = cookie_value.split(".", 1)
    if not selector or not raw_token:
        return None

    connection = connect_db()
    purge_expired_remember_tokens(connection)
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT username, token_hash, expires_at
        FROM remember_tokens
        WHERE selector = ?
        """,
        (selector,),
    )
    row = cursor.fetchone()

    if not row or row["token_hash"] != hash_remember_token(raw_token):
        if row:
            connection.execute("DELETE FROM remember_tokens WHERE selector = ?", (selector,))
            connection.commit()
        connection.close()
        return None

    connection.close()
    return row["username"]


def delete_remember_me_token(cookie_value):
    if not cookie_value or "." not in cookie_value:
        return

    selector = cookie_value.split(".", 1)[0]
    connection = connect_db()
    connection.execute("DELETE FROM remember_tokens WHERE selector = ?", (selector,))
    connection.commit()
    connection.close()


def validate_user(username, password):
    from logic import build_profile_identity, ensure_user_profile

    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT id, username, password, designation, userlevel, fullname, date_created, last_login_at
        FROM users
        WHERE lower(username) = lower(?)
        """,
        ((username or "").strip(),),
    )
    user = cursor.fetchone()
    if not user:
        connection.close()
        return None

    stored_password = (user["password"] or "").strip()
    candidate_password = (password or "").strip()
    password_is_valid = False

    if stored_password and is_password_hash(stored_password):
        try:
            password_is_valid = check_password_hash(stored_password, candidate_password)
        except ValueError:
            password_is_valid = False
    else:
        password_is_valid = stored_password == candidate_password
        if password_is_valid and stored_password:
            cursor.execute(
                """
                UPDATE users
                SET password = ?
                WHERE id = ?
                """,
                (hash_password(candidate_password), user["id"]),
            )
            connection.commit()

    if not password_is_valid:
        connection.close()
        return None

    profile = ensure_user_profile(connection, user)
    identity = build_profile_identity(connection, user, profile, viewer_username=user["username"])
    connection.close()
    return {
        "username": identity["username"],
        "fullname": identity["display_name"],
        "full_name": identity["full_name"],
        "display_name": identity["display_name"],
        "designation": identity["designation_raw"],
        "avatar_url": identity["avatar_url"],
        "avatar_initials": identity["avatar_initials"],
        "theme_preference": identity["theme_preference"],
    }


def get_user_identity(username):
    from logic import build_profile_identity, ensure_user_profile, get_user_row_by_username

    connection = connect_db()
    user = get_user_row_by_username(connection, username)
    if not user:
        connection.close()
        return None
    profile = ensure_user_profile(connection, user)
    identity = build_profile_identity(connection, user, profile, viewer_username=username)
    connection.close()
    return {
        "username": identity["username"],
        "fullname": identity["display_name"],
        "full_name": identity["full_name"],
        "display_name": identity["display_name"],
        "designation": identity["designation_raw"],
        "avatar_url": identity["avatar_url"],
        "avatar_initials": identity["avatar_initials"],
        "theme_preference": identity["theme_preference"],
    }


def get_user_roles_by_username(username):
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT r.name
        FROM user_roles ur
        INNER JOIN users u ON u.id = ur.user_id
        INNER JOIN roles r ON r.id = ur.role_id
        WHERE lower(u.username) = lower(?)
        ORDER BY
            CASE lower(r.name)
                WHEN 'superadmin' THEN 0
                WHEN 'admin' THEN 1
                WHEN 'staff' THEN 2
                ELSE 3
            END,
            r.name COLLATE NOCASE
        """,
        (username,),
    )
    roles = [row["name"] for row in cursor.fetchall()]
    connection.close()
    return roles


def user_has_role(username, role_name):
    return role_name.casefold() in {role.casefold() for role in get_user_roles_by_username(username)}
