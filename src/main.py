
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

# ----------------------------
# App Setup
# ----------------------------
app = FastAPI(title="Zankl-Plan MVP")

# Verzeichnisstruktur:
# project_root/
#   src/main.py
#   templates/
#   static/
BASE_DIR = Path(__file__).resolve().parent            # .../src
ROOT_DIR = BASE_DIR.parent                            # Projekt-Root
DB_PATH = BASE_DIR / "zankl.db"                       # DB liegt in src/

templates = Jinja2Templates(directory=str(ROOT_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(ROOT_DIR / "static")), name="static")

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("zankl-plan")

# ----------------------------
# Database
# ----------------------------
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

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

    cur.execute("""
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            standort TEXT
        )
    """)

    conn.commit()
    conn.close()

init_db()

# ----------------------------
# Hilfsfunktionen
# ----------------------------
def build_days(year: int, kw: int) -> list[dict]:
    """Erzeugt Mo–Fr mit Datum aus ISO-Kalender (KW/Jahr)."""
    start = date.fromisocalendar(year, kw, 1)  # Montag
    labels = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag"]
    return [{"label": labels[i], "date": (start + timedelta(days=i)).strftime("%d.%m.%Y")} for i in range(5)]

# ----------------------------
# Healthcheck & Diagnose
# ----------------------------
@app.get("/health")
def health():
    return {"status": "ok"}

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

    try:
        # Plan abrufen oder erstellen
        cur.execute("""
            SELECT id,row_count FROM week_plans
            WHERE year=? AND kw=? AND standort=?
        """, (year, kw, standort))
        plan = cur.fetchone()

        if not plan:
            cur.execute("INSERT INTO week_plans(year,kw,standort,row_count) VALUES(?,?,?,5)", (year, kw, standort))
            conn.commit()
            plan_id = cur.lastrowid
            rows = 5
        else:
            plan_id = plan["id"]
            rows = plan["row_count"]

        # Mitarbeiter laden
        cur.execute("SELECT id,name FROM employees WHERE standort=? ORDER BY id", (standort,))
        employees = [{"id": e["id"], "name": e["name"]} for e in cur.fetchall()]

        # Zeilenanzahl mindestens so groß wie Mitarbeiterliste
        rows = max(rows, len(employees)) if employees else rows

        # Grid vorbereiten (rows × 5 Tage)
        grid = [[{"text": ""} for _ in range(5)] for _ in range(rows)]
        cur.execute("SELECT row_index, day_index, text FROM week_cells WHERE week_plan_id=?", (plan_id,))
        for r in cur.fetchall():
            row = r["row_index"]
            day = r["day_index"]
            if 0 <= row < rows and 0 <= day < 5:
                grid[row][day]["text"] = r["text"]

        # Tage berechnen aus KW/Jahr (Mo–Fr)
        days = build_days(year, kw)

        return templates.TemplateResponse("week.html", {
            "request": request,
            "grid": grid,
            "employees": employees,
            "kw": kw,
            "year": year,
            "days": days,
            "standort": standort
        })

    except Exception as e:
        tb = traceback.format_exc()
        logger.error("Fehler in /week:\n%s", tb)
        return HTMLResponse(f"<h1>Fehler beim Laden der Woche</h1><pre>{tb}</pre>", status_code=500)
    finally:
        conn.close()

# ----------------------------
# Set Cell
# ----------------------------
@app.post("/api/week/set-cell")
async def set_cell(data: dict = Body(...)):
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT id FROM week_plans WHERE year=? AND kw=? AND standort=?", (data.get("year"), data.get("kw"), data.get("standort")))
        plan = cur.fetchone()
        if not plan:
            return JSONResponse({"ok": False, "error": "Week plan not found"}, status_code=400)

        plan_id = plan["id"]

        cur.execute("""
            INSERT INTO week_cells(week_plan_id,row_index,day_index,text)
            VALUES(?,?,?,?)
            ON CONFLICT(week_plan_id,row_index,day_index) DO UPDATE SET text=excluded.text
        """, (plan_id, data.get("row",0), data.get("day",0), data.get("value","")))
        conn.commit()
        return {"ok": True}
    except Exception as e:
        tb = traceback.format_exc()
        logger.error("Fehler in /api/week/set-cell:\n%s", tb)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
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
    except Exception as e:
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
    except Exception as e:
        tb = traceback.format_exc()
        logger.error("Fehler in /settings/employees POST:\n%s", tb)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
    finally:
        conn.close()

# ----------------------------
# Year View (Optional)
# ----------------------------
@app.get("/year", response_class=HTMLResponse)
def year_view(request: Request, year: int = 2025):
    ctx = {"request": request, "year": year}
    return templates.TemplateResponse("year.html", ctx)
