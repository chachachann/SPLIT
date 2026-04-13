import json
import os
import re
import sqlite3
from datetime import datetime

from werkzeug.security import generate_password_hash


BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
DB_PATH = os.environ.get("SPLIT_DB_PATH", r"C:\SPLIT\db\database.db")
NEWS_IMAGE_DIR = os.path.join(BASE_DIR, "static", "uploads", "news")
NEWS_IMAGE_WEB_PATH = "uploads/news"
CHAT_ATTACHMENT_DIR = os.path.join(BASE_DIR, "static", "uploads", "chat")
CHAT_ATTACHMENT_WEB_PATH = "uploads/chat"
PROFILE_IMAGE_DIR = os.path.join(BASE_DIR, "static", "uploads", "profiles")
PROFILE_IMAGE_WEB_PATH = "uploads/profiles"
ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
ALLOWED_PROFILE_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
ALLOWED_CHAT_ATTACHMENT_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".heic",
    ".heif",
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".txt",
    ".csv",
    ".zip",
    ".rar",
}
REMEMBER_ME_DAYS = int(os.environ.get("SPLIT_REMEMBER_DAYS", "7"))
CHAT_PRESENCE_WINDOW_SECONDS = 150
CHAT_CHANNEL_COUNT = 10
MAX_CHAT_ATTACHMENT_SIZE_BYTES = int(os.environ.get("SPLIT_MAX_CHAT_ATTACHMENT_BYTES", str(15 * 1024 * 1024)))
MAX_PROFILE_IMAGE_SIZE_BYTES = int(os.environ.get("SPLIT_MAX_PROFILE_IMAGE_BYTES", str(50 * 1024 * 1024)))
DEFAULT_ROLES = (
    ("SuperAdmin", 1),
    ("Admin", 0),
    ("Staff", 0),
    ("Developer", 0),
)
PROFILE_FIELD_LABELS = {
    "full_name": "Full Name",
    "designation": "Designation",
    "department": "Department or Office",
    "phone": "Phone",
    "email": "Email",
    "address": "Address",
    "birthday": "Birthday",
    "bio": "About",
}
PROFILE_PRIVATE_FIELDS = tuple(PROFILE_FIELD_LABELS.keys())
PASSWORD_REQUEST_STATUSES = {"pending", "approved", "rejected", "archived"}
THEME_CHOICES = {"dark", "light"}
PROFILE_AUDIT_EVENT_LABELS = {
    "profile.avatar-removed": "Avatar Removed",
    "profile.basic-updated": "Profile Updated",
    "profile.password-request-approved": "Password Change Approved",
    "profile.password-request-rejected": "Password Change Rejected",
    "profile.password-request-submitted": "Password Change Requested",
    "profile.preferences-updated": "Preferences Updated",
    "profile.privacy-updated": "Privacy Updated",
}
DEFAULT_MARQUEE_STYLE = "broadcast"
MARQUEE_STYLE_CHOICES = (
    ("broadcast", "Broadcast"),
    ("signal", "Signal"),
    ("bulletin", "Bulletin"),
)


def timestamp_now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def parse_timestamp(value):
    try:
        return datetime.strptime(value or "", "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return None


def normalize_role_names(role_names):
    seen = set()
    normalized = []

    for role_name in role_names or []:
        clean_name = " ".join((role_name or "").split())
        if not clean_name:
            continue

        role_key = clean_name.casefold()
        if role_key in seen:
            continue

        seen.add(role_key)
        normalized.append(clean_name)

    return normalized


def ensure_db_folder():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)


def ensure_news_image_folder():
    os.makedirs(NEWS_IMAGE_DIR, exist_ok=True)


def ensure_chat_attachment_folder():
    os.makedirs(CHAT_ATTACHMENT_DIR, exist_ok=True)


def ensure_profile_image_folder():
    os.makedirs(PROFILE_IMAGE_DIR, exist_ok=True)


def connect_db():
    ensure_db_folder()
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def json_loads(value, fallback):
    if not value:
        return fallback
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if isinstance(parsed, type(fallback)) else fallback


def json_dumps(value):
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def normalize_theme(value):
    theme = (value or "").strip().lower()
    return theme if theme in THEME_CHOICES else "dark"


def get_initials(value, fallback="U"):
    words = [item for item in re.split(r"\s+", str(value or "").strip()) if item]
    if not words:
        return fallback
    if len(words) == 1:
        return words[0][:2].upper()
    return (words[0][:1] + words[1][:1]).upper()


def build_static_upload_url(relative_path):
    clean_path = (relative_path or "").strip().replace("\\", "/")
    return f"/static/{clean_path}" if clean_path else ""


def is_password_hash(value):
    clean_value = (value or "").strip()
    return clean_value.startswith("pbkdf2:") or clean_value.startswith("scrypt:")


def hash_password(value):
    return generate_password_hash((value or "").strip())


def build_profile_private_fields(value):
    items = []
    seen = set()
    for field_key in json_loads(value, []):
        clean_key = str(field_key or "").strip().lower()
        if clean_key not in PROFILE_FIELD_LABELS or clean_key in seen:
            continue
        seen.add(clean_key)
        items.append(clean_key)
    return items
