# src/main.py
from fastapi import FastAPI, Request, Body, Query, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import sqlite3
from pathlib import Path
from datetime import date, timedelta
import logging, traceback
from urllib.parse import urlparse, parse_qs

# --------------------------------------------------
# App / Paths
# --------------------------------------------------
app = FastAPI(title="Zankl-Plan MVP")

BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent
DB_PATH  = BASE_DIR / "zankl.db"

templates = Jinja2Templates(directory=str(ROOT_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(ROOT_DIR / "static")), name="static")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("zankl-plan")

STANDORTE = ["engelbrechts", "gross-gerungs"]

# --------------------------------------------------
# DB
# --------------------------------------------------
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def column_exists(cur, table: str, column: str) -> bool:
    cur.execute(f"PRAGMA table_info({table})")
    return any(r[1] == column for r in cur.fetchall())

def init_db():
    conn = get_conn(); cur = conn.cursor()

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
    if not column_exists(cur, "week_plans", "four_day_week"):
        cur.execute("ALTER TABLE week_plans ADD COLUMN four_day_week INTEGER DEFAULT 1")

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

    cur.execute("""
    CREATE TABLE IF NOT EXISTS employees (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        standort TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS global_small_jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        standort TEXT,
        row_index INTEGER,
        text TEXT,
        UNIQUE(standort, row_index)
    )
    """)

    conn.commit()
    conn.close()

init_db()

# --------------------------------------------------
# Helpers
# --------------------------------------------------
def build_days(year: int, kw: int, workdays: int = 5):
    start = date.fromisocalendar(year, kw, 1)
    labels = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag"]
    return [
        {
            "label": labels[i],
            "date": (start + timedelta(days=i)).strftime("%d.%m.%Y")
        }
        for i in range(workdays)
    ]

def canon_standort(s: str | None) -> str:
    s = (s or "").strip().lower()
    s = s.replace("ß", "ss").replace("_", "-")
    aliases = {
        "engelbrechts": "engelbrechts",
        "gross gerungs": "gross-gerungs",
        "gross-gerungs": "gross-gerungs",
        "grossgerungs": "gross-gerungs",
        "groß gerungs": "gross-gerungs",
        "gg": "gross-gerungs",
        "eng": "engelbrechts",
    }
    return aliases.get(s, s or "engelbrechts")

def resolve_standort(request: Request, body: str | None, query: str | None):
    if body:
        return canon_standort(body)
    if query:
        return canon_standort(query)

    ref = request.headers.get("referer")
    if ref:
        try:
            qs = parse_qs(urlparse(ref).query)
            return canon_standort(qs.get("standort", ["engelbrechts"])[0])
        except Exception:
            pass

    return "engelbrechts"

def get_year_kw(year: int | None, kw: int | None):
    today = date.today()
    return (
        year or today.isocalendar()[0],
        kw or today.isocalendar()[1]
    )

# --------------------------------------------------
# Health
# --------------------------------------------------
@app.get("/health")
def health():
    return {"status": "ok"}

# --------------------------------------------------
# WEEK (Edit-Ansicht – unverändert stabil)
# --------------------------------------------------
@app.get("/week", response_class=HTMLResponse)
def week(request: Request, kw: int = 1, year: int = 2025, standort: str = "engelbrechts"):
    standort = canon_standort(standort)
    conn = get_conn(); cur = conn.cursor()

    try:
        cur.execute("""
            SELECT id,row_count,four_day_week
            FROM week_plans
            WHERE year=? AND kw=? AND standort=?
        """, (year, kw, standort))
        plan = cur.fetchone()

        if not plan:
            cur.execute("""
                INSERT INTO week_plans(year,kw,standort,row_count,four_day_week)
                VALUES(?,?,?,?,1)
            """, (year, kw, standort, 5))
            conn.commit()
            plan_id, rows, four_day_week = cur.lastrowid, 5, 1
        else:
            plan_id = plan["id"]
            rows = plan["row_count"]
            four_day_week = plan["four_day_week"]

        cur.execute("SELECT id,name FROM employees WHERE standort=? ORDER BY id", (standort,))
        employees = cur.fetchall()
        rows = max(rows, len(employees))

        grid = [[{"text": ""} for _ in range(5)] for _ in range(rows)]
        cur.execute("""
            SELECT row_index,day_index,text
            FROM week_cells WHERE week_plan_id=?
        """, (plan_id,))
        for r in cur.fetchall():
            grid[r["row_index"]][r["day_index"]]["text"] = r["text"] or ""

        return templates.TemplateResponse(
            "week.html",
            {
                "request": request,
                "grid": grid,
                "employees": employees,
                "kw": kw,
                "year": year,
                "days": build_days(year, kw),
                "standort": standort,
                "four_day_week": bool(four_day_week),
                "standorte": STANDORTE,
            }
        )
    except Exception:
        return HTMLResponse(f"<pre>{traceback.format_exc()}</pre>", status_code=500)
    finally:
        conn.close()

# --------------------------------------------------
# VIEW WEEK (NEU – READ ONLY)
# --------------------------------------------------
@app.get("/view/week", response_class=HTMLResponse)
def view_week(
    request: Request,
    year: int | None = None,
    kw: int | None = None,
    standort: str = "engelbrechts"
):
    year, kw = get_year_kw(year, kw)
    standort = canon_standort(standort)

    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute("""
            SELECT id,row_count,four_day_week
            FROM week_plans
            WHERE year=? AND kw=? AND standort=?
        """, (year, kw, standort))
        plan = cur.fetchone()
        if not plan:
            return HTMLResponse("<h1>Kein Wochenplan vorhanden</h1>", status_code=404)

        workdays = 4 if plan["four_day_week"] else 5

        cur.execute("SELECT id,name FROM employees WHERE standort=? ORDER BY id", (standort,))
        employees = cur.fetchall()
        rows = max(plan["row_count"], len(employees))

        grid = [[{"text": ""} for _ in range(workdays)] for _ in range(rows)]
        cur.execute("""
            SELECT row_index,day_index,text
            FROM week_cells
            WHERE week_plan_id=?
        """, (plan["id"],))
        for r in cur.fetchall():
            if r["day_index"] < workdays:
                grid[r["row_index"]][r["day_index"]]["text"] = r["text"] or ""

        return templates.TemplateResponse(
            "week_view.html",
            {
                "request": request,
                "year": year,
                "kw": kw,
                "standort": standort,
                "employees": employees,
                "grid": grid,
                "days": build_days(year, kw, workdays),
                "four_day_week": bool(plan["four_day_week"]),
            }
        )
    except Exception:
        return HTMLResponse(f"<pre>{traceback.format_exc()}</pre>", status_code=500)
    finally:
        conn.close()
