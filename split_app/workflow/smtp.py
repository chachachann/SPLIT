from logic import connect_db, timestamp_now
from split_app.workflow.common import _audit


def get_smtp_settings():
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute("SELECT * FROM smtp_settings WHERE id = 1")
    row = cursor.fetchone()
    connection.close()
    return dict(row) if row else {
        "host": "",
        "port": 587,
        "username": "",
        "password_obfuscated": "",
        "from_email": "",
        "from_name": "",
        "use_tls": 1,
    }


def save_smtp_settings(payload, actor_username):
    host = str(payload.get("host") or "").strip()
    username = str(payload.get("username") or "").strip()
    from_email = str(payload.get("from_email") or "").strip()
    from_name = str(payload.get("from_name") or "").strip()
    password = str(payload.get("password") or "")
    use_tls = 1 if payload.get("use_tls") else 0
    try:
        port = int(payload.get("port") or 0)
    except (TypeError, ValueError):
        port = 0
    if host and not port:
        return False, "SMTP port is required when SMTP host is provided."
    connection = connect_db()
    connection.execute(
        """
        UPDATE smtp_settings
        SET
            host = ?,
            port = ?,
            username = ?,
            password_obfuscated = CASE WHEN ? != '' THEN ? ELSE password_obfuscated END,
            from_email = ?,
            from_name = ?,
            use_tls = ?,
            updated_by_username = ?,
            updated_at = ?
        WHERE id = 1
        """,
        (
            host or None,
            port or None,
            username or None,
            password,
            password.encode("utf-8").hex() if password else "",
            from_email or None,
            from_name or None,
            use_tls,
            actor_username,
            timestamp_now(),
        ),
    )
    _audit(connection, "smtp.updated", actor_username, "smtp", 1, payload={"host": host, "port": port, "username": username, "from_email": from_email})
    connection.commit()
    connection.close()
    return True, "SMTP settings saved."
