
# src/main.py
from fastapi import FastAPI, Request, Body
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import sqlite3
from pathlib import Path
from datetime import date, timedelta
import logging
import traceback

app = FastAPI(title="Zankl-Plan MVP")

BASE_DIR = Path(__file__).resolve().parent         # .../src
ROOT_DIR = BASE_DIR.parent                         # Projekt-Root
DB_PATH = BASE_DIR / "zankl.db"                    # DB liegt in src/

templates = Jinja2Templates(directory=str(ROOT_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(ROOT_DIR / "static")), name="static")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("zankl-plan")

# ----------------------------
# Database
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

    # Week plans mit 4-Tage-Woche Flag
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

    # Zellen der Wochenplanung
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

    # Mitarbeiter
    cur.execute("""
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            standort TEXT
        )
    """)

    # Kleinbaustellen: eigene Liste pro Woche/Standort
    cur.execute("""
        CREATE TABLE IF NOT EXISTS small_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            week_plan_id INTEGER,
            row_index INTEGER,
            text TEXT,
            UNIQUE(week_plan_id, row_index)
        )
    """)

    conn.commit()
    conn.close()

init_db()

# ----------------------------
# Helpers
# ----------------------------
def build_days(year: int, kw: int) -> list[dict]:
    """Erzeugt Mo–Fr mit Datum aus ISO-Kalender (KW/Jahr)."""
    kw = max(1, min(kw, 53))
    start = date.fromisocalendar(year, kw, 1)  # Montag
    labels = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag"]
    return [{"label": labels[i], "date": (start + timedelta(days=i)).strftime("%d.%m.%Y")} for i in range(5)]

def is_friday(day_index: int) -> bool:
    return day_index == 4  # 0..4 = Mo..Fr

# ----------------------------
# Health & Diagnose
# ----------------------------
@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/api/ping")
def api_ping():
    return {"ok": True, "message": "api alive"}

@app.get("/week-plain")
def week_plain(kw: int = 1, year: int = 2025, standort: str = "engelbrechts"):
    return {"kw": kw, "year": year, "standort": standort}

# ----------------------------
# Week View
# ----------------------------
@app.get("/", response_class=HTMLResponse)
@app.get("/week", response_class=HTMLResponse)
def week(request: Request, kw: int = 1, year: int = 2025, standort: str = "engelbrechts"):
    conn = get_conn()
    cur = conn.cursor()

    kw = max(1, min(kw, 53))
    year = max(2000, min(year, 2100))

    try:
        # Plan abrufen oder erstellen
        cur.execute("""
            SELECT id,row_count,four_day_week FROM week_plans
            WHERE year=? AND kw=? AND standort=?
        """, (year, kw, standort))
        plan = cur.fetchone()

        if not plan:
            # NEU: Standardmäßig 4-Tage-Woche = aktiv (1)
            cur.execute("INSERT INTO week_plans(year,kw,standort,row_count,four_day_week) VALUES(?,?,?,?,1)",
                        (year, kw, standort, 5))
            conn.commit()
            plan_id = cur.lastrowid
            rows = 5
            four_day_week = 1
        else:
            plan_id = plan["id"]
            rows = plan["row_count"]
            four_day_week = plan["four_day_week"] or 0

        # Mitarbeiter laden
        cur.execute("SELECT id,name FROM employees WHERE standort=? ORDER BY id", (standort,))
        employees = [{"id": e["id"], "name": e["name"]} for e in cur.fetchall()]
        rows = max(rows, len(employees)) if employees else rows

        # Grid vorbereiten (rows × 5 Tage)
        grid = [[{"text": ""} for _ in range(5)] for _ in range(rows)]
        cur.execute("SELECT row_index, day_index, text FROM week_cells WHERE week_plan_id=?", (plan_id,))
        for r in cur.fetchall():
            row = r["row_index"]
            day = r["day_index"]
            if 0 <= row < rows and 0 <= day < 5:
                grid[row][day]["text"] = r["text"]

        # Kleinbaustellen laden (Liste mit mindestens 10 Einträgen)
        cur.execute("SELECT row_index, text FROM small_jobs WHERE week_plan_id=? ORDER BY row_index", (plan_id,))
        sj = [{"row_index": s["row_index"], "text": s["text"] or ""} for s in cur.fetchall()]
        max_idx = max([x["row_index"] for x in sj], default=-1)
        while len(sj) < 10:
            max_idx += 1
            sj.append({"row_index": max_idx, "text": ""})

        days = build_days(year, kw)

        return templates.TemplateResponse("week.html", {
            "request": request,
            "grid": grid,
            "employees": employees,
            "kw": kw,
            "year": year,
            "days": days,
            "standort": standort,
            "four_day_week": bool(four_day_week),
            "small_jobs": sj,
        })

    except Exception:
        tb = traceback.format_exc()
        logger.error("Fehler in /week:\n%s", tb)
        return HTMLResponse(f"<h1>Fehler beim Laden der Woche</h1><pre>{tb}</pre>", status_code=500)
    finally:
        conn.close()

# ----------------------------
# Optionen (z. B. 4-Tage-Woche)
# ----------------------------
@app.post("/api/week/options")
async def week_options(data: dict = Body(...)):
    """
    body: {year, kw, standort, four_day_week: true/false}
    """
    conn = get_conn()
    cur = conn.cursor()
    try:
        year = int(data.get("year"))
        kw = int(data.get("kw"))
        standort = data.get("standort") or "engelbrechts"
        four_day_week = 1 if bool(data.get("four_day_week")) else 0

        cur.execute("SELECT id FROM week_plans WHERE year=? AND kw=? AND standort=?", (year, kw, standort))
        plan = cur.fetchone()
        if not plan:
            cur.execute("INSERT INTO week_plans(year,kw,standort,row_count,four_day_week) VALUES(?,?,?,?,?)",
                        (year, kw, standort, 5, four_day_week))
            conn.commit()
        else:
            cur.execute("UPDATE week_plans SET four_day_week=? WHERE id=?", (four_day_week, plan["id"]))
            conn.commit()

        return {"ok": True, "four_day_week": bool(four_day_week)}
    except Exception:
        tb = traceback.format_exc()
        logger.error("Fehler in /api/week/options:\n%s", tb)
        return JSONResponse({"ok": False, "error": "server"}, status_code=500)
    finally:
        conn.close()

# ----------------------------
# Kleinbaustellen – Set/Upsert
# ----------------------------
@app.post("/api/klein/set")
async def small_job_set(data: dict = Body(...)):
    """
    body: {year, kw, standort, row_index, text}
    """
    conn = get_conn()
    cur = conn.cursor()
    try:
        year = int(data.get("year"))
        kw = int(data.get("kw"))
        standort = data.get("standort") or "engelbrechts"
        row_index = int(data.get("row_index"))
        text = (data.get("text") or "")

        cur.execute("SELECT id FROM week_plans WHERE year=? AND kw=? AND standort=?", (year, kw, standort))
        plan = cur.fetchone()
        if not plan:
            return JSONResponse({"ok": False, "error": "Week plan not found"}, status_code=400)
        plan_id = plan["id"]

        cur.execute("""
            INSERT INTO small_jobs(week_plan_id,row_index,text)
            VALUES(?,?,?)
            ON CONFLICT(week_plan_id,row_index) DO UPDATE SET text=excluded.text
        """, (plan_id, row_index, text))
        conn.commit()
        return {"ok": True}
    except Exception:
        tb = traceback.format_exc()
        logger.error("Fehler in /api/klein/set:\n%s", tb)
        return JSONResponse({"ok": False, "error": "server"}, status_code=500)
    finally:
        conn.close()

# ----------------------------
# Set Cell (einzelne Zelle)
# ----------------------------
@app.post("/api/week/set-cell")
async def set_cell(data: dict = Body(...)):
    conn = get_conn()
    cur = conn.cursor()
    try:
        year = int(data.get("year"))
        kw = int(data.get("kw"))
        standort = data.get("standort") or "engelbrechts"
        row = int(data.get("row", 0))
        day = int(data.get("day", 0))
        val = data.get("value", "")

        cur.execute("SELECT id,four_day_week FROM week_plans WHERE year=? AND kw=? AND standort=?", (year, kw, standort))
        plan = cur.fetchone()
        if not plan:
            return JSONResponse({"ok": False, "error": "Week plan not found"}, status_code=400)

        # Freitag gesperrt bei 4-Tage-Woche
        if plan["four_day_week"] and is_friday(day):
            return {"ok": True, "skipped": True}

        plan_id = plan["id"]
        cur.execute("""
            INSERT INTO week_cells(week_plan_id,row_index,day_index,text)
            VALUES(?,?,?,?)
            ON CONFLICT(week_plan_id,row_index,day_index) DO UPDATE SET text=excluded.text
        """, (plan_id, row, day, val))
        conn.commit()
        return {"ok": True}
    except Exception:
        tb = traceback.format_exc()
        logger.error("Fehler in /api/week/set-cell:\n%s", tb)
        return JSONResponse({"ok": False, "error": "server"}, status_code=500)
    finally:
        conn.close()

# ----------------------------
# Batch-Updates
# ----------------------------
@app.post("/api/week/batch")
async def week_batch(data: dict = Body(...)):
    """
    {
      "year": 2025,
      "kw": 1,
      "standort": "engelbrechts",
      "updates": [ {"row":0,"day":0,"value":"Text"}, ... ]
    }
    """
    conn = get_conn()
    cur = conn.cursor()
    try:
        year = int(data.get("year"))
        kw = int(data.get("kw"))
        standort = data.get("standort") or "engelbrechts"
        updates = data.get("updates") or []

        cur.execute("SELECT id,four_day_week FROM week_plans WHERE year=? AND kw=? AND standort=?", (year, kw, standort))
        plan = cur.fetchone()
        if not plan:
            return JSONResponse({"ok": False, "error": "Week plan not found"}, status_code=400)

        plan_id = plan["id"]
        four_day_week = plan["four_day_week"]

        cur.execute("BEGIN")
        count = 0
        for u in updates:
            row = int(u.get("row", 0))
            day = int(u.get("day", 0))
            val = u.get("value", "")

            if four_day_week and is_friday(day):
                continue

            cur.execute("""
                INSERT INTO week_cells(week_plan_id,row_index,day_index,text)
                VALUES(?,?,?,?)
                ON CONFLICT(week_plan_id,row_index,day_index) DO UPDATE SET text=excluded.text
            """, (plan_id, row, day, val))
            count += 1
        conn.commit()
        return {"ok": True, "count": count}
    except Exception:
        conn.rollback()
        tb = traceback.format_exc()
        logger.error("Fehler in /api/week/batch:\n%s", tb)
        return JSONResponse({"ok": False, "error": "server"}, status_code=500)
    finally:
        conn.close()

# ----------------------------
# Employees Settings
# ----------------------------
@app.get("/settings/employees", response_class=HTMLResponse)
def employees_settings(request: Request):
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT id,name,standort FROM employees ORDER BY id")
        employees = [{"id": e["id"], "name": e["name"], "standort": e["standort"]} for e in cur.fetchall()]
        return templates.TemplateResponse("settings_employees.html", {"request": request, "employees": employees})
    except Exception:
        tb = traceback.format_exc()
        logger.error("Fehler in /settings/employees GET:\n%s", tb)
        return HTMLResponse(f"<h1>Fehler Mitarbeiter</h1><pre>{tb}</pre>", status_code=500)
    finally:
        conn.close()

@app.post("/settings/employees")
async def employees_save(data: dict = Body(...)):
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM employees")
        for e in data.get("employees", []):
            name = (e.get("name") or "").strip()
            standort = e.get("standort") or "engelbrechts"
            if name:
                cur.execute("INSERT INTO employees(name,standort) VALUES(?,?)", (name, standort))
        conn.commit()
        return {"ok": True}
    except Exception:
        conn.rollback()
        tb = traceback.format_exc()
        logger.error("Fehler in /settings/employees POST:\n%s", tb)
        return JSONResponse({"ok": False, "error": "server"}, status_code=500)
    finally:
        conn.close()

# ----------------------------
# Year View
# ----------------------------
@app.get("/year", response_class=HTMLResponse)
def year_view(request: Request, year: int = 2025):
    ctx = {"request": request, "year": year}
    return templates.TemplateResponse("year.html", ctx)
