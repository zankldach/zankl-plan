# src/db.py
import sqlite3
from pathlib import Path

# --------------------------------------------------
# Datenbank-Pfad
# --------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
DB_DIR = BASE_DIR / "data"
DB_DIR.mkdir(exist_ok=True)
DB_PATH = DB_DIR / "app.db"


# --------------------------------------------------
# Connection Helper
# --------------------------------------------------
def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


# --------------------------------------------------
# Initialisierung
# --------------------------------------------------
def init_db():
    conn = get_conn()
    c = conn.cursor()

    # --------------------------------------------------
    # Standorte
    # --------------------------------------------------
    c.execute("""
    CREATE TABLE IF NOT EXISTS standorte (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE
    )
    """)

    # --------------------------------------------------
    # Mitarbeiter (fixe Zeilen!)
    # --------------------------------------------------
    c.execute("""
    CREATE TABLE IF NOT EXISTS mitarbeiter (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        standort_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        aktiv INTEGER NOT NULL DEFAULT 1,
        sort_order INTEGER NOT NULL,
        UNIQUE(standort_id, sort_order)
    )
    """)

    # --------------------------------------------------
    # Wochenplanung (Kopf)
    # --------------------------------------------------
    c.execute("""
    CREATE TABLE IF NOT EXISTS week_plans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        year INTEGER NOT NULL,
        kw INTEGER NOT NULL,
        standort_id INTEGER NOT NULL,
        UNIQUE(year, kw, standort_id)
    )
    """)

    # --------------------------------------------------
    # Wochenzellen (jede Eingabe!)
    # --------------------------------------------------
    c.execute("""
    CREATE TABLE IF NOT EXISTS week_cells (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        week_plan_id INTEGER NOT NULL,
        mitarbeiter_id INTEGER NOT NULL,
        day_index INTEGER NOT NULL,   -- 0=Mo … 4=Fr
        text TEXT,
        color TEXT,
        UNIQUE(week_plan_id, mitarbeiter_id, day_index)
    )
    """)

    # --------------------------------------------------
    # Benutzer (für späteres Login)
    # --------------------------------------------------
    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password_hash TEXT,
        role TEXT CHECK(role IN ('admin','write','view')) NOT NULL DEFAULT 'view',
        standort_id INTEGER
    )
    """)

    conn.commit()

    # --------------------------------------------------
    # SEED: Standorte
    # --------------------------------------------------
    c.execute("SELECT COUNT(*) AS n FROM standorte")
    if c.fetchone()["n"] == 0:
        c.executemany(
            "INSERT INTO standorte (name) VALUES (?)",
            [("Engelbrechts",), ("Groß Gerungs",)]
        )
        conn.commit()

    # --------------------------------------------------
    # SEED: Mitarbeiter Engelbrechts (10 fixe Zeilen)
    # --------------------------------------------------
    c.execute("SELECT id FROM standorte WHERE name='Engelbrechts'")
    engelbrechts_id = c.fetchone()["id"]

    c.execute(
        "SELECT COUNT(*) AS n FROM mitarbeiter WHERE standort_id=?",
        (engelbrechts_id,)
    )
    if c.fetchone()["n"] == 0:
        for i in range(1, 11):
            c.execute(
                """
                INSERT INTO mitarbeiter (standort_id, name, sort_order)
                VALUES (?, ?, ?)
                """,
                (engelbrechts_id, f"Mitarbeiter {i}", i)
            )
        conn.commit()

    # --------------------------------------------------
    # SEED: Mitarbeiter Groß Gerungs (10 fixe Zeilen)
    # --------------------------------------------------
    c.execute("SELECT id FROM standorte WHERE name='Groß Gerungs'")
    gr_id = c.fetchone()["id"]

    c.execute(
        "SELECT COUNT(*) AS n FROM mitarbeiter WHERE standort_id=?",
        (gr_id,)
    )
    if c.fetchone()["n"] == 0:
        for i in range(1, 11):
            c.execute(
                """
                INSERT INTO mitarbeiter (standort_id, name, sort_order)
                VALUES (?, ?, ?)
                """,
                (gr_id, f"Mitarbeiter {i}", i)
            )
        conn.commit()

    conn.close()
