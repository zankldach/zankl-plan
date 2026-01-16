from fastapi import FastAPI, Request, Body
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import sqlite3
from datetime import date, timedelta

# --------------------------------------------------
# APP
# --------------------------------------------------

app = FastAPI(title="Zankl Planungstool – STABLE")

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
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS employees (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        standort TEXT NOT NULL
    )
    """)

    cur.execute("""
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

    cur.execute("""
    CREATE TABLE IF NOT EXISTS week_cells (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        week_plan_id INTEGER,
        row_index INTEGER,
        day_index INTEGER,
        text TEXT,
        UNIQUE(week_plan_id, row_index, day_index)
    )
    """)

    conn.commit()
    conn.close()

init_db()

# --------------------------------------------------
# HELPER
# --------------------------------------------------

def canon_standort(s: str | None) -> str:
    if not s:
        return "engelbrechts"
    s = s.lower().replace("ß", "ss")
    if "gross" in s or "gerungs" in s or s == "gg":
        return "gross-gerungs"
    return "engelbrechts"

def get_current_year_kw():
    today = date.today()
    return today.year, today.isocalendar().week

def build_days(year: int, kw: int):
    start = date.fromisocalendar(year, kw, 1)
    labels = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag"]
    return [
        {"label": labels[i], "date": (start + timedelta(days=i)).strftime("%d.%m.%Y")}
        for i in range(5)
    ]

# --------------------------------------------------
# ZENTRALE WOCHENLOGIK
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

    cur.execute(
        "SELECT id, name FROM employees WHERE standort=? ORDER BY id",
        (standort,)
    )
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
# WEEK – EDIT
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
# WEEK – SAVE  ✅ FIX
# --------------------------------------------------

@app.post("/week/save")
def save_week(payload: dict = Body(...)):
    conn = get_conn()
    cur = conn.cursor()

    year = payload["year"]
    kw = payload["kw"]
    standort = payload["standort"]
    cells = payload["cells"]

    cur.execute(
        "SELECT id FROM week_plans WHERE year=? AND kw=? AND standort=?",
        (year, kw, standort)
    )
    plan = cur.fetchone()
    if not plan:
        conn.close()
        return JSONResponse({"status": "error"}, status_code=400)

    plan_id = plan["id"]

    for cell in cells:
        cur.execute("""
            INSERT INTO week_cells (week_plan_id, row_index, day_index, text)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(week_plan_id, row_index, day_index)
            DO UPDATE SET text=excluded.text
        """, (
            plan_id,
            cell["row"],
            cell["col"],
            cell["text"]
        ))

    conn.commit()
    conn.close()
    return {"status": "ok"}

# --------------------------------------------------
# WEEK – VIEW (READ ONLY)
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
# SETTINGS – EMPLOYEES  ✅ FIX
# --------------------------------------------------

@app.get("/settings/employees", response_class=HTMLResponse)
def settings_employees(request: Request):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, name, standort FROM employees ORDER BY standort, name")
    employees = cur.fetchall()
    conn.close()

    return templates.TemplateResponse(
        "settings_employees.html",
        {
            "request": request,
            "employees": employees
        }
    )

# --------------------------------------------------
# HEALTH
# --------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok"}
