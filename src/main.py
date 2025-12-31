from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import sqlite3
from pathlib import Path

# ----------------------------
# App Setup
# ----------------------------
app = FastAPI()

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "zankl.db"

templates = Jinja2Templates(directory=str(BASE_DIR.parent / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR.parent / "static")), name="static")

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

        # Grid vorbereiten
        grid = [[{"text": ""} for _ in range(5)] for _ in range(rows)]
        cur.execute("SELECT row_index, day_index, text FROM week_cells WHERE week_plan_id=?", (plan_id,))
        for r in cur.fetchall():
            row = r["row_index"]
            day = r["day_index"]
            if 0 <= row < rows and 0 <= day < 5:
                grid[row][day]["text"] = r["text"]

        # Mitarbeiter
        cur.execute("SELECT id,name FROM employees WHERE standort=? ORDER BY id", (standort,))
        employees = [{"id": e["id"], "name": e["name"]} for e in cur.fetchall()]

        # Default-Tage
        days = [
            {"label":"Montag","date":"06.01"},
            {"label":"Dienstag","date":"07.01"},
            {"label":"Mittwoch","date":"08.01"},
            {"label":"Donnerstag","date":"09.01"},
            {"label":"Freitag","date":"10.01"},
        ]

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
        print("Fehler in /week:", e)
        return HTMLResponse(f"<h1>Fehler beim Laden der Woche</h1><pre>{e}</pre>", status_code=500)
    finally:
        conn.close()

# ----------------------------
# Set Cell
# ----------------------------
@app.post("/api/week/set-cell")
async def set_cell(data: dict):
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
    finally:
        conn.close()

@app.post("/settings/employees")
async def employees_save(data: dict):
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM employees")
        for e in data.get("employees", []):
            name = e.get("name","").strip()
            standort = e.get("standort","engelbrechts")
            if name:
                cur.execute("INSERT INTO employees(name,standort) VALUES(?,?)", (name, standort))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()
