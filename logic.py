import sqlite3
import os
from datetime import datetime

DB_PATH = r"C:\SPLIT\db\database.db"

def validate_user(username, password):
    conn = connect_db()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT username, userlevel, fullname 
    FROM users 
    WHERE username = ? AND password = ?
    """, (username, password))

    user = cursor.fetchone()
    conn.close()

    return user

def ensure_db_folder():
    folder = os.path.dirname(DB_PATH)

    print("DB Folder:", folder)  # DEBUG
    print("Exists:", os.path.exists(folder))  # DEBUG

    if not os.path.exists(folder):
        os.makedirs(folder)
        print("Folder created!")


def connect_db():
    ensure_db_folder()

    # 🔥 Test file creation permission
    test_file = os.path.join(os.path.dirname(DB_PATH), "test.txt")
    try:
        with open(test_file, "w") as f:
            f.write("test")
        os.remove(test_file)
    except Exception as e:
        print("Permission error:", e)

    return sqlite3.connect(DB_PATH)


def init_db():
    conn = connect_db()
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT,
        designation TEXT,
        userlevel TEXT,
        fullname TEXT,
        date_created TEXT
    )
    """)

    conn.commit()

    cursor.execute("SELECT * FROM users WHERE username = ?", ("RO_Admin",))
    user = cursor.fetchone()

    if not user:
        cursor.execute("""
        INSERT INTO users (username, password, designation, userlevel, fullname, date_created)
        VALUES (?, ?, ?, ?, ?, ?)
        """, (
            "RO_Admin",
            "1234",
            "admin",
            "SuperAdmin",
            "Regional Admin",
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ))
        conn.commit()

    conn.close()