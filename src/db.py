
# src/db.py
import sqlite3
from pathlib import Path

DB_DIR = Path(__file__).resolve().parent.parent / "data"
DB_DIR.mkdir(exist_ok=True)
DB_PATH = DB_DIR / "app.db"

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        email TEXT UNIQUE,
        role TEXT CHECK(role IN ('admin','write','view')) NOT NULL DEFAULT 'view',
        viewer_standort_id INTEGER
    )""")

    c.execute("""
    CREATE TABLE IF NOT EXISTS standorte (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL
    )""")

    c.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        standort_id INTEGER NOT NULL,
        workdays INTEGER NOT NULL DEFAULT 5,
        employee_lines INTEGER NOT NULL DEFAULT 10,
        UNIQUE(standort_id)
    )""")

    c.execute("""
    CREATE TABLE IF NOT EXISTS week_plans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        year INTEGER NOT NULL,
        kw INTEGER NOT NULL,
        standort_id INTEGER NOT NULL,
        UNIQUE(year, kw, standort_id)
    )""")

    c.execute("""
    CREATE TABLE IF NOT EXISTS week_cells (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        week_plan_id INTEGER NOT NULL,
        day_index INTEGER NOT NULL,
        row_index INTEGER NOT NULL,
        job_id INTEGER
    )""")

    c.execute("""
    CREATE TABLE IF NOT EXISTS jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        standort_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        customer_name TEXT,
        color TEXT DEFAULT '#4cc9f0',
        status TEXT DEFAULT 'offen'
    )""")

    c.execute("""
    CREATE TABLE IF NOT EXISTS small_jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        standort_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        info TEXT
    )""")

    c.execute("""
    CREATE TABLE IF NOT EXISTS resource_types (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL
    )""")

    c.execute("""
    CREATE TABLE IF NOT EXISTS year_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        standort_id INTEGER NOT NULL,
        job_id INTEGER,
        start_date TEXT NOT NULL,
        end_date TEXT NOT NULL
    )""")

    # Seed: Standorte
    c.execute("SELECT COUNT(*) AS n FROM standorte")
    if c.fetchone()["n"] == 0:
        c.executemany("INSERT INTO standorte(name) VALUES (?)",
                      [("Engelbrechts",), ("Groß Gerungs",)])
        conn.commit()

    # Seed: Settings je Standort
    c.execute("SELECT id FROM standorte")
    for row in c.fetchall():
        sid = row["id"]
        c.execute("SELECT 1 FROM settings WHERE standort_id=?", (sid,))
        if not c.fetchone():
            c.execute("INSERT INTO settings(standort_id, workdays, employee_lines) VALUES (?,?,?)",
                      (sid, 5, 10))

    # Seed: Demo-Viewer
    c.execute("SELECT 1 FROM users WHERE email=?", ("viewer@demo",))
    if not c.fetchone():
        c.execute("INSERT INTO users(name, email, role, viewer_standort_id) VALUES (?,?,?,?)",
                  ("Viewer", "viewer@demo", "view", 1))

    # Optional: Admin
    c.execute("SELECT 1 FROM users WHERE email=?", ("admin@demo",))
    if not c.fetchone():
        c.execute("INSERT INTO users(name, email, role) VALUES (?,?,?)",
                  ("Admin", "admin@demo", "admin"))

    conn.commit()
    conn.close()
