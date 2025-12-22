import sqlite3
from pathlib import Path
from passlib.hash import bcrypt

DB_PATH = Path("data.db")

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    c = conn.cursor()

    # USERS
    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      email TEXT UNIQUE NOT NULL,
      name TEXT NOT NULL,
      role TEXT CHECK(role IN ('admin','write','view')) NOT NULL,
      password_hash TEXT NOT NULL,
      viewer_standort_id INTEGER,
      created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # STANDORTE
    c.execute("""
    CREATE TABLE IF NOT EXISTS standorte (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL
    );
    """)

    # SETTINGS pro Standort
    c.execute("""
    CREATE TABLE IF NOT EXISTS settings (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      standort_id INTEGER NOT NULL,
      workdays INTEGER CHECK(workdays IN (4,5)) NOT NULL DEFAULT 5,
      employee_lines INTEGER NOT NULL DEFAULT 10,
      FOREIGN KEY (standort_id) REFERENCES standorte(id)
    );
    """)

    # JOBS
    c.execute("""
    CREATE TABLE IF NOT EXISTS jobs (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      title TEXT NOT NULL,
      customer_name TEXT NOT NULL,
      address TEXT,
      standort_id INTEGER NOT NULL,
      status TEXT CHECK(status IN ('geplant','in_arbeit','fertig')) NOT NULL DEFAULT 'geplant',
      color TEXT,
      fixed_date INTEGER DEFAULT 0,
      internal INTEGER DEFAULT 0,
      vacation INTEGER DEFAULT 0,
      notes TEXT,
      FOREIGN KEY (standort_id) REFERENCES standorte(id)
    );
    """)

    # YEAR EVENTS (Jahresplanung-Blöcke)
    c.execute("""
    CREATE TABLE IF NOT EXISTS year_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      job_id INTEGER,
      standort_id INTEGER NOT NULL,
      start_date TEXT NOT NULL,
      end_date TEXT NOT NULL,
      row_start INTEGER NOT NULL,
      row_span INTEGER NOT NULL,
      color TEXT,
      completed INTEGER DEFAULT 0,
      extra_info TEXT,
      FOREIGN KEY (job_id) REFERENCES jobs(id),
      FOREIGN KEY (standort_id) REFERENCES standorte(id)
    );
    """)

    # SMALL JOBS (Kleinbaustellen)
    c.execute("""
    CREATE TABLE IF NOT EXISTS small_jobs (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      standort_id INTEGER NOT NULL,
      name TEXT NOT NULL,
      team_size INTEGER NOT NULL,
      hours INTEGER NOT NULL,
      notes TEXT,
      FOREIGN KEY (standort_id) REFERENCES standorte(id)
    );
    """)

    # WEEK PLANS
    c.execute("""
    CREATE TABLE IF NOT EXISTS week_plans (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      year INTEGER NOT NULL,
      kw INTEGER NOT NULL,
      standort_id INTEGER NOT NULL,
      UNIQUE(year, kw, standort_id),
      FOREIGN KEY (standort_id) REFERENCES standorte(id)
    );
    """)

    # WEEK CELLS
    c.execute("""
    CREATE TABLE IF NOT EXISTS week_cells (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      week_plan_id INTEGER NOT NULL,
      day_index INTEGER NOT NULL,   -- 0..4 (Mo..Fr) oder 0..3 (Mo..Do)
      row_index INTEGER NOT NULL,
      job_id INTEGER,               -- NULL => frei
      copied_from_row INTEGER,
      FOREIGN KEY (week_plan_id) REFERENCES week_plans(id),
      FOREIGN KEY (job_id) REFERENCES jobs(id)
    );
    """)

    # CHANGELOG
    c.execute("""
    CREATE TABLE IF NOT EXISTS changelog (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      entity TEXT NOT NULL,
      entity_id INTEGER NOT NULL,
      action TEXT NOT NULL,
      before_json TEXT,
      after_json TEXT,
      user_id INTEGER,
      ts TEXT DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY (user_id) REFERENCES users(id)
    );
    """)

    # RESOURCES
    c.execute("""
    CREATE TABLE IF NOT EXISTS resource_types (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL
    );
    """)
    c.execute("""
    CREATE TABLE IF NOT EXISTS resource_bookings (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      resource_type_id INTEGER NOT NULL,
      start_date TEXT NOT NULL,
      end_date TEXT NOT NULL,
      job_id INTEGER,
      notes TEXT,
      FOREIGN KEY (resource_type_id) REFERENCES resource_types(id),
      FOREIGN KEY (job_id) REFERENCES jobs(id)
    );
    """)

    # PRINT JOBS (optional Ablage)
    c.execute("""
    CREATE TABLE IF NOT EXISTS print_jobs (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      type TEXT CHECK(type IN ('week','year')) NOT NULL,
      standort_id INTEGER,
      year INTEGER,
      kw INTEGER,
      file_path TEXT,
      created_at TEXT DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY (standort_id) REFERENCES standorte(id)
    );
    """)

    conn.commit()

    # Seeds
    c.execute("SELECT COUNT(*) AS n FROM standorte;")
    if c.fetchone()["n"] == 0:
        c.execute("INSERT INTO standorte(name) VALUES (?)", ("Engelbrechts",))
        c.execute("INSERT INTO standorte(name) VALUES (?)", ("Groß Gerungs",))
        conn.commit()

    c.execute("SELECT id,name FROM standorte;")
    for st in c.fetchall():
        c.execute("SELECT COUNT(*) AS n FROM settings WHERE standort_id=?", (st["id"],))
        if c.fetchone()["n"] == 0:
            c.execute("INSERT INTO settings(standort_id, workdays, employee_lines) VALUES (?,?,?)",
                      (st["id"], 5, 10))
    conn.commit()

    c.execute("SELECT COUNT(*) AS n FROM users;")
    if c.fetchone()["n"] == 0:
        admin_pw = bcrypt.hash("admin123")
        write_pw = bcrypt.hash("write123")
        view_pw  = bcrypt.hash("view123")
        c.execute("SELECT id FROM standorte WHERE name=?", ("Engelbrechts",))
        viewer_st_id = c.fetchone()["id"]
        c.execute("INSERT INTO users(email,name,role,password_hash,viewer_standort_id) VALUES (?,?,?,?,?)",
                  ("admin@demo", "Admin", "admin", admin_pw, viewer_st_id))
        c.execute("INSERT INTO users(email,name,role,password_hash,viewer_standort_id) VALUES (?,?,?,?,?)",
                  ("dispo@demo", "Disponent", "write", write_pw, viewer_st_id))
        c.execute("INSERT INTO users(email,name,role,password_hash,viewer_standort_id) VALUES (?,?,?,?,?)",
                  ("viewer@demo", "Viewer", "view", view_pw, viewer_st_id))
        conn.commit()

    c.execute("SELECT COUNT(*) AS n FROM jobs;")
    if c.fetchone()["n"] == 0:
        jobs = [
            ("Huber", "Affenhausen", None, 1, "geplant", "#f0c000", 0, 0, 0, "Dachdeckung"),
            ("Mayer", "Zwettl", None, 2, "geplant", "#00a0f0", 1, 0, 0, "Fixtermin KW 01"),
            ("Schmidt", "Gmünd", None, 1, "in_arbeit", "#30c060", 0, 1, 0, "Interner Einsatz"),
            ("Urlaub Team A", "Engelbrechts", None, 1, "geplant", "#ff0000", 0, 0, 1, "Urlaub"),
        ]
        for j in jobs:
            c.execute("""
                INSERT INTO jobs(title,customer_name,address,standort_id,status,color,fixed_date,internal,vacation,notes)
                VALUES (?,?,?,?,?,?,?,?,?,?)
            """, j)
        conn.commit()

    c.execute("SELECT COUNT(*) AS n FROM small_jobs;")
    if c.fetchone()["n"] == 0:
        small = [
            (1, "Dachrinne reinigen", 2, 4, ""),
            (1, "Kaminabdeckung tauschen", 2, 3, ""),
            (2, "Kleines Blechdetail", 1, 2, ""),
        ]
        c.executemany("""
            INSERT INTO small_jobs(standort_id,name,team_size,hours,notes)
            VALUES (?,?,?,?,?)
        """, small)
        conn.commit()

    conn.close()
