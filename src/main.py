from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import sqlite3
from pathlib import Path

app = FastAPI()

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "zankl.db"

templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

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
        CREATE TABLE IF NOT EXISTS week_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            year INTEGER,
            kw INTEGER,
            standort TEXT,
            row_count INTEGER DEFAULT 5,
            UNIQUE(year,kw,standort)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS week_cells (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            week_plan_id INTEGER,
            row_index INTEGER,
            day_index INTEGER,
            text TEXT,
            UNIQUE(week_plan_id,row_index,day_index)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE
        )
    """)

    conn.commit()
    conn.close()

init_db()

# --------------------------------------------------
# WEEK VIEW
# --------------------------------------------------
@app.get("/", response_class=HTMLResponse)
@app.get("/week", response_class=HTMLResponse)
def week(request: Request, kw: int = 1, year: int = 2025, standort: str = "engelbrechts"):
    conn = get_conn()
    cur = conn.cursor()

    # Week Plan holen / anlegen
    cur.execute("""
        SELECT id,row_count FROM week_plans
        WHERE year=? AND kw=? AND standort=?
    """,(year, kw, standort))
    plan = cur.fetchone()

    if not plan:
        cur.execute("""
            INSERT INTO week_plans(year,kw,standort,row_count)
            VALUES(?,?,?,5)
        """,(year, kw, standort))
        conn.commit()
        plan_id = cur.lastrowid
        rows = 5
    else:
        plan_id = plan["id"]
        rows = plan["row_count"]

    # Grid vorbereiten
    grid = [[{"text":""} for _ in range(5)] for _ in range(rows)]
    cur.execute("SELECT row_index,day_index,text FROM week_cells WHERE week_plan_id=?", (plan_id,))
    for r in cur.fetchall():
        grid[r["row_index"]][r["day_index"]]["text"] = r["text"]

    # Mitarbeiterliste
    cur.execute("SELECT name FROM employees ORDER BY id")
    employees = [e["name"] for e in cur.fetchall()]
    if len(employees) < rows:
        # Dummy-Namen falls noch nicht genügend MA
        employees += [f"Mitarbeiter {i+1}" for i in range(len(employees), rows)]

    conn.close()

    # Wochentage
    days = [
        {"label":"Montag","date":"06.01"},
        {"label":"Dienstag","date":"07.01"},
        {"label":"Mittwoch","date":"08.01"},
        {"label":"Donnerstag","date":"09.01"},
        {"label":"Freitag","date":"10.01"},
    ]

    return templates.TemplateResponse("week.html",{
        "request": request,
        "grid": grid,
        "employees": employees,
        "kw": kw,
        "year": year,
        "days": days,
        "standort": standort
    })

# --------------------------------------------------
# CELL SAVE
# --------------------------------------------------
@app.post("/api/week/set-cell")
async def set_cell(data: dict):
    conn = get_conn()
    cur = conn.cursor()

    # Standort aus Payload, Default fallback
    standort = data.get("standort","engelbrechts")

    cur.execute("""
        SELECT id FROM week_plans
        WHERE year=? AND kw=? AND standort=?
    """,(data["year"], data["kw"], standort))
    plan = cur.fetchone()
    if not plan:
        cur.execute("""
            INSERT INTO week_plans(year,kw,standort,row_count)
            VALUES(?,?,?,5)
        """,(data["year"], data["kw"], standort))
        conn.commit()
        plan_id = cur.lastrowid
    else:
        plan_id = plan["id"]

    cur.execute("""
        INSERT INTO week_cells(week_plan_id,row_index,day_index,text)
        VALUES(?,?,?,?)
        ON CONFLICT(week_plan_id,row_index,day_index)
        DO UPDATE SET text=excluded.text
    """,(plan_id,data["row"],data["day"],data["value"]))

    conn.commit()
    conn.close()
    return {"ok": True}

# --------------------------------------------------
# SETTINGS – EMPLOYEES
# --------------------------------------------------
@app.get("/settings/employees", response_class=HTMLResponse)
def employees_settings(request: Request):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id,name FROM employees ORDER BY id")
    employees = [{"id": e["id"], "name": e["name"]} for e in cur.fetchall()]
    conn.close()

    return templates.TemplateResponse("settings_employees.html",{
        "request": request,
        "employees": employees
    })

@app.post("/settings/employees")
async def employees_save(names: list[str] = Form(...)):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("DELETE FROM employees")
    for name in names:
        if name.strip():
            cur.execute("INSERT INTO employees(name) VALUES(?)", (name.strip(),))

    conn.commit()
    conn.close()
    return JSONResponse({"ok": True})
