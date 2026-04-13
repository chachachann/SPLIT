import os
import sqlite3

from split_app.services.core import DEFAULT_ROLES, connect_db, hash_password, normalize_role_names, timestamp_now


def fetch_role_by_name(connection, role_name):
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT id, name, is_locked, created_at
        FROM roles
        WHERE lower(name) = lower(?)
        """,
        (role_name,),
    )
    return cursor.fetchone()


def ensure_role(connection, role_name, is_locked=0):
    existing_role = fetch_role_by_name(connection, role_name)
    if existing_role:
        if is_locked and not existing_role["is_locked"]:
            connection.execute(
                """
                UPDATE roles
                SET is_locked = 1
                WHERE id = ?
                """,
                (existing_role["id"],),
            )
        return existing_role["id"], existing_role["name"]

    cursor = connection.cursor()
    cursor.execute(
        """
        INSERT INTO roles (name, is_locked, created_at)
        VALUES (?, ?, ?)
        """,
        (role_name, 1 if is_locked else 0, timestamp_now()),
    )
    return cursor.lastrowid, role_name


def seed_default_roles(connection):
    for role_name, is_locked in DEFAULT_ROLES:
        ensure_role(connection, role_name, is_locked=is_locked)


def migrate_legacy_user_roles(connection):
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT id, userlevel
        FROM users
        """
    )

    for row in cursor.fetchall():
        legacy_roles = normalize_role_names((row["userlevel"] or "").replace(";", ",").split(","))
        for legacy_role in legacy_roles:
            role_id, _ = ensure_role(connection, legacy_role, is_locked=1 if legacy_role.casefold() == "superadmin" else 0)
            cursor.execute(
                """
                INSERT OR IGNORE INTO user_roles (user_id, role_id)
                VALUES (?, ?)
                """,
                (row["id"], role_id),
            )


def get_buttons(user_roles):
    role_names = normalize_role_names(user_roles if isinstance(user_roles, (list, tuple, set)) else [user_roles])
    if not role_names:
        return []

    placeholders = ", ".join("?" for _ in role_names)
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute(
        f"""
        SELECT name, route
        FROM buttons
        WHERE required_role IN ({placeholders})
        ORDER BY name COLLATE NOCASE
        """,
        tuple(role_names),
    )
    buttons = cursor.fetchall()
    connection.close()
    return buttons


def get_role_definitions():
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT
            r.id,
            r.name,
            r.is_locked,
            COUNT(ur.user_id) AS assigned_count
        FROM roles r
        LEFT JOIN user_roles ur ON ur.role_id = r.id
        GROUP BY r.id, r.name, r.is_locked
        ORDER BY
            CASE lower(r.name)
                WHEN 'superadmin' THEN 0
                ELSE 1
            END,
            r.name COLLATE NOCASE
        """
    )
    roles = [dict(row) for row in cursor.fetchall()]
    connection.close()
    return roles


def get_role_name_map(connection, requested_roles):
    role_names = normalize_role_names(requested_roles)
    if not role_names:
        return {}

    placeholders = ", ".join("?" for _ in role_names)
    cursor = connection.cursor()
    cursor.execute(
        f"""
        SELECT id, name
        FROM roles
        WHERE lower(name) IN ({placeholders})
        """,
        tuple(role.casefold() for role in role_names),
    )
    return {row["name"].casefold(): dict(row) for row in cursor.fetchall()}


def get_assigned_roles(connection, user_id):
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT r.name
        FROM user_roles ur
        INNER JOIN roles r ON r.id = ur.role_id
        WHERE ur.user_id = ?
        ORDER BY
            CASE lower(r.name)
                WHEN 'superadmin' THEN 0
                WHEN 'admin' THEN 1
                WHEN 'staff' THEN 2
                ELSE 3
            END,
            r.name COLLATE NOCASE
        """,
        (user_id,),
    )
    return [row["name"] for row in cursor.fetchall()]


def count_users_with_role(connection, role_name):
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT COUNT(DISTINCT ur.user_id) AS total
        FROM user_roles ur
        INNER JOIN roles r ON r.id = ur.role_id
        WHERE lower(r.name) = lower(?)
        """,
        (role_name,),
    )
    return cursor.fetchone()["total"]


def log_account_modification(connection, user_id, target_username, target_fullname, actor_username, action, details):
    connection.execute(
        """
        INSERT INTO account_modifications (
            user_id,
            target_username,
            target_fullname,
            actor_username,
            action,
            details,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(user_id),
            target_username,
            target_fullname,
            actor_username or "System",
            action,
            details,
            timestamp_now(),
        ),
    )


def get_all_users():
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT
            u.id,
            u.username,
            u.designation,
            u.fullname,
            u.date_created,
            (
                SELECT MAX(am.created_at)
                FROM account_modifications am
                WHERE am.user_id = u.id
            ) AS last_modified_at
        FROM users u
        ORDER BY
            CASE
                WHEN EXISTS (
                    SELECT 1
                    FROM user_roles ur
                    INNER JOIN roles r ON r.id = ur.role_id
                    WHERE ur.user_id = u.id AND lower(r.name) = 'superadmin'
                ) THEN 0
                WHEN EXISTS (
                    SELECT 1
                    FROM user_roles ur
                    INNER JOIN roles r ON r.id = ur.role_id
                    WHERE ur.user_id = u.id AND lower(r.name) = 'admin'
                ) THEN 1
                ELSE 2
            END,
            u.fullname COLLATE NOCASE,
            u.username COLLATE NOCASE
        """
    )
    users = [dict(row) for row in cursor.fetchall()]

    if not users:
        connection.close()
        return []

    user_ids = [user["id"] for user in users]
    placeholders = ", ".join("?" for _ in user_ids)

    cursor.execute(
        f"""
        SELECT ur.user_id, r.name
        FROM user_roles ur
        INNER JOIN roles r ON r.id = ur.role_id
        WHERE ur.user_id IN ({placeholders})
        ORDER BY
            CASE lower(r.name)
                WHEN 'superadmin' THEN 0
                WHEN 'admin' THEN 1
                WHEN 'staff' THEN 2
                ELSE 3
            END,
            r.name COLLATE NOCASE
        """,
        tuple(user_ids),
    )
    roles_by_user = {}
    for row in cursor.fetchall():
        roles_by_user.setdefault(row["user_id"], []).append(row["name"])

    cursor.execute(
        f"""
        SELECT user_id, actor_username, action, details, created_at
        FROM account_modifications
        WHERE user_id IN ({placeholders})
        ORDER BY datetime(created_at) DESC, id DESC
        """,
        tuple(user_ids),
    )
    history_by_user = {}
    for row in cursor.fetchall():
        history_by_user.setdefault(row["user_id"], []).append(dict(row))

    connection.close()

    for user in users:
        user["roles"] = roles_by_user.get(user["id"], [])
        user["history"] = history_by_user.get(user["id"], [])
        user["role_display"] = ", ".join(user["roles"]) if user["roles"] else "Unassigned"
        user["last_modified_at"] = user["last_modified_at"] or "No recorded changes"

    return users


def create_user_account(username, password, designation, role_names, fullname, actor_username=None):
    username = (username or "").strip()
    password = (password or "").strip()
    designation = (designation or "").strip()
    fullname = (fullname or "").strip()
    normalized_roles = normalize_role_names(role_names)

    if not username or not password or not fullname:
        return False, "Username, full name, and password are required."

    if not normalized_roles:
        return False, "Select at least one account role."

    connection = connect_db()
    role_map = get_role_name_map(connection, normalized_roles)
    if len(role_map) != len(normalized_roles):
        connection.close()
        return False, "One or more selected roles are no longer available."

    cursor = connection.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO users (username, password, designation, userlevel, fullname, date_created)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (username, hash_password(password), designation, ",".join(normalized_roles), fullname, timestamp_now()),
        )
        user_id = cursor.lastrowid

        for role_name in normalized_roles:
            cursor.execute(
                """
                INSERT OR IGNORE INTO user_roles (user_id, role_id)
                VALUES (?, ?)
                """,
                (user_id, role_map[role_name.casefold()]["id"]),
            )

        cursor.execute(
            """
            INSERT INTO user_profiles (
                user_id,
                display_name,
                private_fields_json,
                theme_preference,
                created_at,
                updated_at
            )
            VALUES (?, ?, '[]', 'dark', ?, ?)
            """,
            (user_id, fullname or username, timestamp_now(), timestamp_now()),
        )

        log_account_modification(
            connection,
            user_id,
            username,
            fullname,
            actor_username,
            "Created",
            "Account created with roles: " + ", ".join(normalized_roles),
        )
        connection.commit()
    except sqlite3.IntegrityError:
        connection.close()
        return False, "That username is already in use."

    connection.close()
    return True, "Account created successfully."


def update_user_account(user_id, username, designation, role_names, fullname, password="", actor_username=None):
    from logic import ensure_user_profile

    username = (username or "").strip()
    designation = (designation or "").strip()
    fullname = (fullname or "").strip()
    password = (password or "").strip()
    normalized_roles = normalize_role_names(role_names)

    if not username or not fullname:
        return False, "Username and full name are required."

    if not normalized_roles:
        return False, "Select at least one account role."

    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT id, username, designation, fullname
        FROM users
        WHERE id = ?
        """,
        (user_id,),
    )
    existing_user = cursor.fetchone()

    if not existing_user:
        connection.close()
        return False, "Account not found."

    existing_roles = get_assigned_roles(connection, user_id)
    existing_role_keys = {role.casefold() for role in existing_roles}
    updated_role_keys = {role.casefold() for role in normalized_roles}

    role_map = get_role_name_map(connection, normalized_roles)
    if len(role_map) != len(normalized_roles):
        connection.close()
        return False, "One or more selected roles are no longer available."

    if "superadmin" in existing_role_keys and "superadmin" not in updated_role_keys:
        if count_users_with_role(connection, "SuperAdmin") <= 1:
            connection.close()
            return False, "At least one SuperAdmin account must remain."

    change_log = []
    profile_row = ensure_user_profile(connection, existing_user)
    profile_display_name = (profile_row["display_name"] or "").strip() if profile_row else ""

    if existing_user["username"] != username:
        change_log.append(f"Username: {existing_user['username']} -> {username}")
    if (existing_user["fullname"] or "") != fullname:
        change_log.append(f"Full name: {existing_user['fullname']} -> {fullname}")
    if (existing_user["designation"] or "") != designation:
        previous_designation = existing_user["designation"] or "None"
        current_designation = designation or "None"
        change_log.append(f"Designation: {previous_designation} -> {current_designation}")

    added_roles = [role for role in normalized_roles if role.casefold() not in existing_role_keys]
    removed_roles = [role for role in existing_roles if role.casefold() not in updated_role_keys]
    if added_roles:
        change_log.append("Roles added: " + ", ".join(added_roles))
    if removed_roles:
        change_log.append("Roles removed: " + ", ".join(removed_roles))
    if password:
        change_log.append("Password updated")

    if not change_log:
        connection.close()
        return True, "No changes were made."

    try:
        if password:
            cursor.execute(
                """
                UPDATE users
                SET username = ?, password = ?, designation = ?, userlevel = ?, fullname = ?
                WHERE id = ?
                """,
                (username, hash_password(password), designation, ",".join(normalized_roles), fullname, user_id),
            )
        else:
            cursor.execute(
                """
                UPDATE users
                SET username = ?, designation = ?, userlevel = ?, fullname = ?
                WHERE id = ?
                """,
                (username, designation, ",".join(normalized_roles), fullname, user_id),
            )

        if profile_row and (not profile_display_name or profile_display_name == (existing_user["fullname"] or "").strip()):
            cursor.execute(
                """
                UPDATE user_profiles
                SET display_name = ?, updated_at = ?
                WHERE user_id = ?
                """,
                (fullname or username, timestamp_now(), user_id),
            )

        cursor.execute("DELETE FROM user_roles WHERE user_id = ?", (user_id,))
        for role_name in normalized_roles:
            cursor.execute(
                """
                INSERT INTO user_roles (user_id, role_id)
                VALUES (?, ?)
                """,
                (user_id, role_map[role_name.casefold()]["id"]),
            )

        log_account_modification(
            connection,
            user_id,
            username,
            fullname,
            actor_username,
            "Updated",
            "; ".join(change_log),
        )
        connection.commit()
    except sqlite3.IntegrityError:
        connection.close()
        return False, "That username is already in use."

    connection.close()
    return True, "Account updated successfully."


def delete_user_account(user_id, active_username=None, actor_username=None):
    from logic import ensure_user_profile

    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT id, username, fullname
        FROM users
        WHERE id = ?
        """,
        (user_id,),
    )
    existing_user = cursor.fetchone()

    if not existing_user:
        connection.close()
        return False, "Account not found."

    if active_username and existing_user["username"] == active_username:
        connection.close()
        return False, "You cannot delete the account you are currently using."

    existing_roles = get_assigned_roles(connection, user_id)
    if "superadmin" in {role.casefold() for role in existing_roles} and count_users_with_role(connection, "SuperAdmin") <= 1:
        connection.close()
        return False, "At least one SuperAdmin account must remain."

    profile_row = ensure_user_profile(connection, existing_user)
    avatar_path = (profile_row["avatar_path"] or "").strip() if profile_row else ""
    if avatar_path:
        absolute_avatar_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "static", avatar_path)
        if os.path.exists(absolute_avatar_path):
            os.remove(absolute_avatar_path)

    log_account_modification(
        connection,
        user_id,
        existing_user["username"],
        existing_user["fullname"],
        actor_username,
        "Deleted",
        "Account deleted. Previous roles: " + (", ".join(existing_roles) if existing_roles else "None"),
    )
    cursor.execute("DELETE FROM profile_notification_states WHERE user_id = ?", (user_id,))
    cursor.execute("DELETE FROM profile_notifications WHERE user_id = ?", (user_id,))
    cursor.execute("DELETE FROM profile_audit_log WHERE user_id = ?", (user_id,))
    cursor.execute("DELETE FROM password_change_requests WHERE requester_user_id = ?", (user_id,))
    cursor.execute("DELETE FROM user_profiles WHERE user_id = ?", (user_id,))
    cursor.execute("DELETE FROM user_roles WHERE user_id = ?", (user_id,))
    cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
    connection.commit()
    connection.close()
    return True, "Account deleted successfully."


def create_role(role_name):
    normalized_roles = normalize_role_names([role_name])
    if not normalized_roles:
        return False, "Enter a role name before saving."

    role_name = normalized_roles[0]
    connection = connect_db()

    if fetch_role_by_name(connection, role_name):
        connection.close()
        return False, "That role already exists."

    ensure_role(connection, role_name, is_locked=1 if role_name.casefold() == "superadmin" else 0)
    connection.commit()
    connection.close()
    return True, "Role created successfully."


def delete_role(role_id):
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT r.id, r.name, r.is_locked, COUNT(ur.user_id) AS assigned_count
        FROM roles r
        LEFT JOIN user_roles ur ON ur.role_id = r.id
        WHERE r.id = ?
        GROUP BY r.id, r.name, r.is_locked
        """,
        (role_id,),
    )
    role = cursor.fetchone()

    if not role:
        connection.close()
        return False, "Role not found."

    if role["is_locked"]:
        connection.close()
        return False, "Locked roles cannot be deleted."

    if role["assigned_count"] > 0:
        connection.close()
        return False, "Remove this role from all accounts before deleting it."

    cursor.execute("DELETE FROM roles WHERE id = ?", (role_id,))
    connection.commit()
    connection.close()
    return True, "Role deleted successfully."
