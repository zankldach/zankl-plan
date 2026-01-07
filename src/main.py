
# src/main.py
from fastapi import FastAPI, Request, Body, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import sqlite3
from pathlib import Path
from datetime import date, timedelta
import logging
import traceback

app = FastAPI(title="Zankl-Plan MVP")

BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent
DB_PATH = BASE_DIR / "zankl.db"

templates = Jinja2Templates(directory=str(ROOT_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(ROOT_DIR / "static")), name="static")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("zankl-plan")

# ----------------------------
# DB Init
# ----------------------------
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def column_exists(cur, table: str, column: str) -> bool:
    cur.execute(f"PRAGMA table_info({table})")
    return any(r[1] == column for r in cur.fetchall())

def init_db():
    conn = get_conn()
    cur = conn.cursor()

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
            name TEXT UNIQUE,
            standort TEXT
        )
    """)

    # Globale Kleinbaustellen mit Standort
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

# ----------------------------
# Helpers
# ----------------------------
def build_days(year: int, kw: int):
    kw = max(1, min(kw, 53))
    start = date.fromisocalendar(year, kw, 1)
    labels = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag"]
    return [{"label": labels[i], "date": (start + timedelta(days=i)).strftime("%d.%m.%Y")} for i in range(5)]

def is_friday(day_index: int) -> bool:
    return day_index == 4

# ----------------------------
# Routes
# ----------------------------
@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/week", response_class=HTMLResponse)
def week(request: Request, kw: int = 1, year: int = 2025, standort: str = "engelbrechts"):
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT id,row_count,four_day_week FROM week_plans WHERE year=? AND kw=? AND standort=?", (year, kw, standort))
        plan = cur.fetchone()
        if not plan:
            cur.execute("INSERT INTO week_plans(year,kw,standort,row_count,four_day_week) VALUES(?,?,?,?,1)", (year, kw, standort, 5))
            conn.commit()
            plan_id = cur.lastrowid
            rows = 5
            four_day_week = 1
        else:
            plan_id = plan["id"]
            rows = plan["row_count"]
            four_day_week = plan["four_day_week"]

        cur.execute("SELECT id,name FROM employees WHERE standort=? ORDER BY id", (standort,))
        employees = [{"id": e["id"], "name": e["name"]} for e in cur.fetchall()]
        rows = max(rows, len(employees)) if employees else rows

        grid = [[{"text": ""} for _ in range(5)] for _ in range(rows)]
        cur.execute("SELECT row_index,day_index,text FROM week_cells WHERE week_plan_id=?", (plan_id,))
        for r in cur.fetchall():
            if 0 <= r["row_index"] < rows and 0 <= r["day_index"] < 5:
                grid[r["row_index"]][r["day_index"]]["text"] = r["text"]

        # Standortabhängige Kleinbaustellen
        cur.execute("SELECT row_index,text FROM global_small_jobs WHERE standort=? ORDER BY row_index", (standort,))
        sj = [{"row_index": s["row_index"], "text": s["text"] or ""} for s in cur.fetchall()]
        max_idx = max([x["row_index"] for x in sj], default=-1)
        while len(sj) < 10:
            max_idx += 1
            sj.append({"row_index": max_idx, "text": ""})

        return templates.TemplateResponse("week.html", {
            "request": request,
            "grid": grid,
            "employees": employees,
            "kw": kw,
            "year": year,
            "days": build_days(year, kw),
            "standort": standort,
            "four_day_week": bool(four_day_week),
            "small_jobs": sj
        })
    except Exception:
        return HTMLResponse(f"<pre>{traceback.format_exc()}</pre>", status_code=500)
    finally:
        conn.close()

@app.post("/api/klein/set")
async def klein_set(data: dict = Body(...)):
    conn = get_conn()
    cur = conn.cursor()
    try:
        standort = data.get("standort") or "engelbrechts"
        row_index = int(data.get("row_index"))
        text = data.get("text") or ""
        cur.execute("""
            INSERT INTO global_small_jobs(standort,row_index,text)
            VALUES(?,?,?)
            ON CONFLICT(standort,row_index) DO UPDATE SET text=excluded.text
        """, (standort, row_index, text))
        conn.commit()
        return {"ok": True}
    except Exception:
        return JSONResponse({"ok": False, "error": traceback.format_exc()}, status_code=500)
    finally:
        conn.close()

@app.post("/api/week/set-cell")
async def set_cell(data: dict = Body(...)):
    conn = get_conn()
    cur = conn.cursor()
    try:
        year = int(data.get("year"))
        kw = int(data.get("kw"))
        standort = data.get("standort") or "engelbrechts"
        row = int(data.get("row"))
        day = int(data.get("day"))
        val = data.get("value") or ""

        cur.execute("SELECT id,four_day_week FROM week_plans WHERE year=? AND kw=? AND standort=?", (year, kw, standort))
        plan = cur.fetchone()
        if not plan:
            return {"ok": False, "error": "Plan not found"}
        if plan["four_day_week"] and is_friday(day):
            return {"ok": True, "skipped": True}

        cur.execute("""
            INSERT INTO week_cells(week_plan_id,row_index,day_index,text)
            VALUES(?,?,?,?)
            ON CONFLICT(week_plan_id,row_index,day_index) DO UPDATE SET text=excluded.text
        """, (plan["id"], row, day, val))
        conn.commit()
        return {"ok": True}
    except Exception:
        return JSONResponse({"ok": False, "error": traceback.format_exc()}, status_code=500)
    finally:
        conn.close()
