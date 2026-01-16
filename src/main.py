# --- unverändert: Imports & App-Setup ---
from fastapi import FastAPI, Request, Body, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import sqlite3
from pathlib import Path
from datetime import date, timedelta
import traceback

app = FastAPI(title="Zankl-Plan MVP")

BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent
DB_PATH = BASE_DIR / "zankl.db"

templates = Jinja2Templates(directory=str(ROOT_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(ROOT_DIR / "static")), name="static")

# --------------------------------------------------
# DB
# --------------------------------------------------

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS week_plans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        year INTEGER,
        kw INTEGER,
        standort TEXT,
        row_count INTEGER DEFAULT 5,
        four_day_week INTEGER DEFAULT 1,
        UNIQUE(year, kw, standort)
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS week_cells (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        week_plan_id INTEGER,
        row_index INTEGER,
        day_index INTEGER,
        text TEXT,
        UNIQUE(week_plan_id, row_index, day_index)
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS employees (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        standort TEXT
    )
    """)

    conn.commit()
    conn.close()

init_db()

# --------------------------------------------------
# Helper
# --------------------------------------------------

def canon_standort(s: str | None) -> str:
    if not s:
        return "engelbrechts"
    s = s.lower().replace("ß", "ss").replace("_", "-").strip()
    if "gross" in s or "groß" in s or "gg" == s:
        return "gross-gerungs"
    return "engelbrechts"

def build_days(year: int, kw: int):
    start = date.fromisocalendar(year, kw, 1)
    labels = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag"]
    return [
        {"label": labels[i], "date": (start + timedelta(days=i)).strftime("%d.%m.%Y")}
        for i in range(5)
    ]

def get_current_year_kw():
    today = date.today()
    return today.year, today.isocalendar().week

# --------------------------------------------------
# ZENTRALE WOCHENLOGIK  (NEU – wird von /week UND /view genutzt)
# --------------------------------------------------

def load_week_data(year: int, kw: int, standort: str):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        "SELECT id, row_count, four_day_week FROM week_plans WHERE year=? AND kw=? AND standort=?",
        (year, kw, standort)
    )
    plan = cur.fetchone()

    if not plan:
        cur.execute(
            "INSERT INTO week_plans (year, kw, standort, row_count, four_day_week) VALUES (?, ?, ?, ?, ?)",
            (year, kw, standort, 5, 1)
        )
        conn.commit()
        plan_id = cur.lastrowid
        rows = 5
        four_day_week = True
    else:
        plan_id = plan["id"]
        rows = plan["row_count"]
        four_day_week = bool(plan["four_day_week"])

    cur.execute("SELECT id, name FROM employees WHERE standort=? ORDER BY id", (standort,))
    employees = cur.fetchall()
    if employees:
        rows = max(rows, len(employees))

    grid = [[{"text": ""} for _ in range(5)] for _ in range(rows)]

    cur.execute(
        "SELECT row_index, day_index, text FROM week_cells WHERE week_plan_id=?",
        (plan_id,)
    )
    for r in cur.fetchall():
        if r["row_index"] < rows and r["day_index"] < 5:
            grid[r["row_index"]][r["day_index"]]["text"] = r["text"] or ""

    conn.close()

    return {
        "grid": grid,
        "employees": employees,
        "four_day_week": four_day_week
    }

# --------------------------------------------------
# WEEK – EDITOR
# --------------------------------------------------

@app.get("/week", response_class=HTMLResponse)
def week(request: Request, year: int | None = None, kw: int | None = None, standort: str = "engelbrechts"):
    year = year or get_current_year_kw()[0]
    kw = kw or get_current_year_kw()[1]
    standort = canon_standort(standort)

    data = load_week_data(year, kw, standort)

    return templates.TemplateResponse(
        "week.html",
        {
            "request": request,
            "grid": data["grid"],
            "employees": data["employees"],
            "four_day_week": data["four_day_week"],
            "days": build_days(year, kw),
            "year": year,
            "kw": kw,
            "standort": standort,
            "editable": True
        }
    )

# --------------------------------------------------
# WEEK – VIEW (READ ONLY)  ✅ FIX
# --------------------------------------------------

@app.get("/view/week", response_class=HTMLResponse)
def week_view(request: Request, year: int | None = None, kw: int | None = None, standort: str = "engelbrechts"):
    year = year or get_current_year_kw()[0]
    kw = kw or get_current_year_kw()[1]
    standort = canon_standort(standort)

    data = load_week_data(year, kw, standort)

    return templates.TemplateResponse(
        "week_view.html",
        {
            "request": request,
            "grid": data["grid"],
            "employees": data["employees"],
            "four_day_week": data["four_day_week"],
            "days": build_days(year, kw),
            "year": year,
            "kw": kw,
            "standort": standort,
            "editable": False
        }
    )

# --------------------------------------------------
# HEALTH
# --------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok"}
