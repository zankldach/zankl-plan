import os
import sqlite3
from datetime import date, timedelta

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

# ---------------- App ----------------
app = FastAPI(title="Zankl Plan")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SESSION_SECRET", "dev-secret"),
)

# ---------------- DB ----------------
DB_PATH = os.path.join(os.getcwd(), "database.db")

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
            year INTEGER NOT NULL,
            kw INTEGER NOT NULL,
            standort TEXT NOT NULL,
            row_count INTEGER NOT NULL DEFAULT 5,
            UNIQUE(year, kw, standort)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS week_cells (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            week_plan_id INTEGER NOT NULL,
            row_index INTEGER NOT NULL,
            day_index INTEGER NOT NULL,
            text TEXT,
            UNIQUE(week_plan_id, row_index, day_index)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            standort TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()

@app.on_event("startup")
def startup():
    init_db()

# ---------------- Helpers ----------------
def get_prev_week(year: int, kw: int):
    if kw > 1:
        return year, kw - 1
    return year - 1, 52

def get_week_days(year: int, kw: int):
    monday = date.fromisocalendar(year, kw, 1)
    labels = ["Montag","Dienstag","Mittwoch","Donnerstag","Freitag"]
    return [
        {
            "label": labels[i],
            "date": (monday + timedelta(days=i)).strftime("%d.%m")
        }
        for i in range(5)
    ]

# ---------------- Root ----------------
@app.get("/", response_class=RedirectResponse)
def root():
    return RedirectResponse("/week", status_code=303)

# ---------------- Wochenansicht ----------------
@app.get("/week", response_class=HTMLResponse)
def week_view(
    request: Request,
    kw: int = None,
    year: int = None,
    standort: str = "Engelbrechts",
):
    today = date.today()
    kw = kw or today.isocalendar()[1]
    year = year or today.year

    conn = get_conn()
    cur = conn.cursor()

    # Woche holen
    cur.execute(
        "SELECT * FROM week_plans WHERE year=? AND kw=? AND standort=?",
        (year, kw, standort),
    )
    plan = cur.fetchone()

    # Falls neue Woche → Struktur aus Vorwoche übernehmen
    if not plan:
        py, pkw = get_prev_week(year, kw)
        cur.execute(
            "SELECT row_count FROM week_plans WHERE year=? AND kw=? AND standort=?",
            (py, pkw, standort),
        )
        prev = cur.fetchone()
        row_count = prev["row_count"] if prev else 5

        cur.execute(
            "INSERT INTO week_plans (year, kw, standort, row_count) VALUES (?,?,?,?)",
            (year, kw, standort, row_count),
        )
        conn.commit()

        cur.execute(
            "SELECT * FROM week_plans WHERE year=? AND kw=? AND standort=?",
            (year, kw, standort),
        )
        plan = cur.fetchone()

    plan_id = plan["id"]
    row_count = plan["row_count"]

    # Grid vorbereiten
    grid = [
        [{"text": ""} for _ in range(5)]
        for _ in range(row_count)
    ]

    cur.execute(
        "SELECT row_index, day_index, text FROM week_cells WHERE week_plan_id=?",
        (plan_id,),
    )
    for r, d, text in cur.fetchall():
        if r < row_count and d < 5:
            grid[r][d]["text"] = text

    # Mitarbeiterliste
    cur.execute("SELECT * FROM employees WHERE standort=? ORDER BY id", (standort,))
    employees = [row["name"] for row in cur.fetchall()]

    conn.close()

    return templates.TemplateResponse(
        "week.html",
        {
            "request": request,
            "grid": grid,
            "days": get_week_days(year, kw),
            "kw": kw,
            "year": year,
            "standort": standort,
            "employees": employees
        },
    )

# ---------------- API: Zelle speichern ----------------
@app.post("/api/week/set-cell")
async def set_cell(request: Request):
    data = await request.json()

    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        "SELECT id FROM week_plans WHERE year=? AND kw=? AND standort=?",
        (data["year"], data["kw"], data.get("standort", "Engelbrechts")),
    )
    plan_id = cur.fetchone()["id"]

    cur.execute(
        """
        INSERT INTO week_cells (week_plan_id, row_index, day_index, text)
        VALUES (?,?,?,?)
        ON CONFLICT(week_plan_id, row_index, day_index)
        DO UPDATE SET text=excluded.text
        """,
        (
            plan_id,
            data["row"],
            data["day"],
            data["value"],
        ),
    )

    conn.commit()
    conn.close()

    return {"ok": True}

# ---------------- API: Zeile + ----------------
@app.post("/api/week/add-row")
async def add_row(request: Request):
    data = await request.json()

    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        "UPDATE week_plans SET row_count = row_count + 1 WHERE year=? AND kw=? AND standort=?",
        (data["year"], data["kw"], data.get("standort", "Engelbrechts")),
    )

    conn.commit()
    conn.close()
    return {"ok": True}

# ---------------- API: Zeile - ----------------
@app.post("/api/week/remove-row")
async def remove_row(request: Request):
    data = await request.json()

    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        "SELECT id, row_count FROM week_plans WHERE year=? AND kw=? AND standort=?",
        (data["year"], data["kw"], data.get("standort", "Engelbrechts")),
    )
    plan = cur.fetchone()

    if not plan or plan["row_count"] <= 1:
        return {"ok": False}

    last_row = plan["row_count"] - 1

    cur.execute(
        "DELETE FROM week_cells WHERE week_plan_id=? AND row_index=?",
        (plan["id"], last_row),
    )

    cur.execute(
        "UPDATE week_plans SET row_count = row_count - 1 WHERE id=?",
        (plan["id"],),
    )

    conn.commit()
    conn.close()
    return {"ok": True}

# ---------------- Einstellungen: Mitarbeiter ----------------
@app.get("/settings/employees", response_class=HTMLResponse)
def settings_employees(request: Request):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM employees ORDER BY id")
    employees = [row["name"] for row in cur.fetchall()]
    conn.close()
    return templates.TemplateResponse(
        "settings_employees.html",
        {"request": request, "employees": employees}
    )

@app.post("/api/settings/employees")
async def save_employees(request: Request):
    data = await request.json()
    names = data.get("names", [])
    standort = data.get("standort", "Engelbrechts")

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM employees WHERE standort=?", (standort,))
    for name in names:
        cur.execute("INSERT INTO employees (name, standort) VALUES (?, ?)", (name, standort))

    conn.commit()
    conn.close()
    return {"ok": True}
