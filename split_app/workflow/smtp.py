import os
import smtplib
import socket
from email.message import EmailMessage
from urllib.parse import urljoin

from logic import connect_db, timestamp_now
from split_app.services.validation import validate_email_address
from split_app.workflow.common import _audit


def get_smtp_settings():
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute("SELECT * FROM smtp_settings WHERE id = 1")
    row = cursor.fetchone()
    connection.close()
    settings = dict(row) if row else {
        "host": "",
        "port": 587,
        "username": "",
        "password_obfuscated": "",
        "from_email": "",
        "from_name": "",
        "use_tls": 1,
        "use_ssl": 0,
        "is_enabled": 0,
        "last_tested_at": None,
        "last_error": "",
    }
    settings["password_configured"] = bool(_resolve_smtp_password(settings))
    return settings


def smtp_is_ready(settings=None):
    resolved = settings or get_smtp_settings()
    return bool(
        resolved.get("is_enabled")
        and str(resolved.get("host") or "").strip()
        and int(resolved.get("port") or 0) > 0
        and str(resolved.get("from_email") or "").strip()
    )


def _resolve_smtp_password(settings):
    env_password = os.environ.get("SPLIT_SMTP_PASSWORD", "")
    if env_password:
        return env_password
    encoded = str((settings or {}).get("password_obfuscated") or "").strip()
    if not encoded:
        return ""
    try:
        return bytes.fromhex(encoded).decode("utf-8")
    except ValueError:
        return ""


def _build_absolute_link(link_url):
    clean_link = str(link_url or "").strip()
    if not clean_link:
        return ""
    if clean_link.startswith("http://") or clean_link.startswith("https://"):
        return clean_link
    public_base_url = os.environ.get("SPLIT_PUBLIC_BASE_URL", "").strip()
    if public_base_url:
        return urljoin(public_base_url.rstrip("/") + "/", clean_link.lstrip("/"))
    return clean_link


def _build_message(subject, text_body, recipients, settings):
    message = EmailMessage()
    from_email = str(settings.get("from_email") or "").strip()
    from_name = str(settings.get("from_name") or "").strip()
    message["Subject"] = subject
    message["From"] = f"{from_name} <{from_email}>" if from_name else from_email
    message["To"] = ", ".join(recipients)
    message.set_content(text_body)
    return message


def _open_smtp_client(settings):
    host = str(settings.get("host") or "").strip()
    port = int(settings.get("port") or 0)
    timeout = int(os.environ.get("SPLIT_SMTP_TIMEOUT_SECONDS", "10"))
    if settings.get("use_ssl"):
        client = smtplib.SMTP_SSL(host, port, timeout=timeout)
    else:
        client = smtplib.SMTP(host, port, timeout=timeout)
    client.ehlo()
    if settings.get("use_tls") and not settings.get("use_ssl"):
        client.starttls()
        client.ehlo()
    username = str(settings.get("username") or "").strip()
    password = _resolve_smtp_password(settings)
    if username and password:
        client.login(username, password)
    return client


def send_smtp_message(settings, recipients, subject, text_body):
    clean_recipients = [str(item or "").strip() for item in (recipients or []) if str(item or "").strip()]
    if not clean_recipients:
        return False, "No recipient email addresses are configured."
    if not smtp_is_ready(settings):
        return False, "SMTP is not fully configured."
    message = _build_message(subject, text_body, clean_recipients, settings)
    try:
        client = _open_smtp_client(settings)
        try:
            client.send_message(message)
        finally:
            client.quit()
    except (OSError, smtplib.SMTPException, socket.timeout) as exc:
        return False, str(exc)
    return True, "Email sent."


def send_email_to_usernames(usernames, subject, message, *, link_url="", sender_name="System"):
    clean_usernames = [str(item or "").strip() for item in (usernames or []) if str(item or "").strip()]
    settings = get_smtp_settings()
    if not clean_usernames or not smtp_is_ready(settings):
        return {"ok": False, "message": "SMTP is not enabled.", "delivered_count": 0}

    placeholders = ", ".join("?" for _ in clean_usernames)
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute(
        f"""
        SELECT DISTINCT p.email
        FROM users u
        INNER JOIN user_profiles p ON p.user_id = u.id
        WHERE lower(u.username) IN ({placeholders})
          AND COALESCE(trim(p.email), '') != ''
        """,
        tuple(username.casefold() for username in clean_usernames),
    )
    recipients = [str(row["email"]).strip() for row in cursor.fetchall()]
    connection.close()
    if not recipients:
        return {"ok": False, "message": "No recipient profiles have email addresses configured.", "delivered_count": 0}

    link = _build_absolute_link(link_url)
    lines = [str(message or "").strip(), "", f"Sender: {sender_name or 'System'}"]
    if link:
        lines.extend(["", f"Open: {link}"])
    ok, result_message = send_smtp_message(settings, recipients, subject, "\n".join(lines))
    return {"ok": ok, "message": result_message, "delivered_count": len(recipients) if ok else 0}


def send_test_email(target_email, actor_username):
    email = str(target_email or "").strip()
    ok, message = validate_email_address(email, allow_blank=False)
    if not ok:
        return False, message
    settings = get_smtp_settings()
    test_settings = dict(settings)
    test_settings["is_enabled"] = 1
    ok, result_message = send_smtp_message(
        test_settings,
        [email],
        "SPLIT SMTP test message",
        "\n".join(
            [
                "This is a test email from SPLIT.",
                "",
                f"Triggered by: {actor_username or 'System'}",
                f"Sent at: {timestamp_now()}",
            ]
        ),
    )
    connection = connect_db()
    connection.execute(
        """
        UPDATE smtp_settings
        SET last_tested_at = ?, last_error = ?
        WHERE id = 1
        """,
        (timestamp_now(), "" if ok else result_message),
    )
    _audit(connection, "smtp.tested", actor_username, "smtp", 1, payload={"target_email": email, "ok": ok})
    connection.commit()
    connection.close()
    return ok, ("Test email sent." if ok else f"SMTP test failed: {result_message}")


def save_smtp_settings(payload, actor_username):
    host = str(payload.get("host") or "").strip()
    username = str(payload.get("username") or "").strip()
    from_email = str(payload.get("from_email") or "").strip()
    from_name = str(payload.get("from_name") or "").strip()
    password = str(payload.get("password") or "")
    use_tls = 1 if payload.get("use_tls") else 0
    use_ssl = 1 if payload.get("use_ssl") else 0
    is_enabled = 1 if payload.get("is_enabled") else 0
    try:
        port = int(payload.get("port") or 0)
    except (TypeError, ValueError):
        port = 0
    if host and not port:
        return False, "SMTP port is required when SMTP host is provided."
    if use_ssl and use_tls:
        return False, "Choose either SSL or TLS, not both."
    if is_enabled:
        if not host or not port or not from_email:
            return False, "Host, port, and from email are required before SMTP can be enabled."
        ok, email_message = validate_email_address(from_email, allow_blank=False)
        if not ok:
            return False, email_message
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
            use_ssl = ?,
            is_enabled = ?,
            last_error = NULL,
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
            use_ssl,
            is_enabled,
            actor_username,
            timestamp_now(),
        ),
    )
    _audit(
        connection,
        "smtp.updated",
        actor_username,
        "smtp",
        1,
        payload={
            "host": host,
            "port": port,
            "username": username,
            "from_email": from_email,
            "from_name": from_name,
            "use_tls": bool(use_tls),
            "use_ssl": bool(use_ssl),
            "is_enabled": bool(is_enabled),
        },
    )
    connection.commit()
    connection.close()
    return True, "SMTP settings saved."
