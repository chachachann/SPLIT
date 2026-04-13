import re
from urllib.parse import urlparse


USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{3,64}$")
PASSWORD_LOWER_PATTERN = re.compile(r"[a-z]")
PASSWORD_UPPER_PATTERN = re.compile(r"[A-Z]")
PASSWORD_DIGIT_PATTERN = re.compile(r"\d")


def normalize_username(value):
    return " ".join(str(value or "").split())


def validate_username(value):
    username = normalize_username(value)
    if not username:
        return False, "Username is required."
    if not USERNAME_PATTERN.fullmatch(username):
        return False, "Username must be 3-64 characters and use only letters, numbers, dots, dashes, or underscores."
    return True, ""


def validate_password_strength(value, *, allow_blank=False):
    password = str(value or "")
    if allow_blank and not password:
        return True, ""
    if len(password) < 8:
        return False, "Password must be at least 8 characters."
    if not PASSWORD_LOWER_PATTERN.search(password):
        return False, "Password must include at least one lowercase letter."
    if not PASSWORD_UPPER_PATTERN.search(password):
        return False, "Password must include at least one uppercase letter."
    if not PASSWORD_DIGIT_PATTERN.search(password):
        return False, "Password must include at least one number."
    return True, ""


def validate_email_address(value, *, allow_blank=True):
    email = str(value or "").strip()
    if not email:
        return (True, "") if allow_blank else (False, "Email is required.")
    if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        return True, ""
    return False, "Enter a valid email address."


def validate_http_url(value, *, allow_blank=True):
    url = str(value or "").strip()
    if not url:
        return (True, "") if allow_blank else (False, "A URL is required.")
    parsed = urlparse(url)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return True, ""
    if url.startswith("/"):
        return True, ""
    return False, "Use an absolute http(s) URL or an internal path starting with /."
