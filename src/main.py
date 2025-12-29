from fastapi import FastAPI, Request, Form
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from datetime import date, timedelta
import sqlite3
import os

# ---------------- App ----------------
app = FastAPI(title="Zankl Plan")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SESSION_SECRET", "dev-secret"))

DB_PATH = "database.db"

# ---------------- DB Helper ----------------
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    c = conn.cursor()
    # Tabellen anlegen, falls nicht existieren
    c.execute("""
        CREATE TABLE IF NOT EXISTS standorte (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS week_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            year INTEGER NOT NULL,
            kw INTEGER NOT NULL,
            standort_id INTEGER NOT NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS week_cells (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            week_plan_id INTEGER NOT NULL,
            day_index INTEGER NOT NULL,
            row_index INTEGER NOT NULL,
            job_id INTEGER
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            customer_name TEXT,
            color TEXT,
            status TEXT,
            standort_id INTEGER
        )
    """)
    conn.commit()
    conn.close()

@app.on_event("startup")
def startup():
    init_db()

# ---------------- Login Helper ----------------
def require_login(request: Request):
    if "user" not in request.session:
        request.session["user"] = {"role": "write", "viewer_standort_id": 1}

# ---------------- Weekdays Helper ----------------
def get_week_days(year: int, kw: int, workdays=5):
    monday = date.fromisocalendar(year, kw, 1)
    days = []
    for i in range(workdays):
        d = monday + timedelta(days=i)
        days.append({"date": d.strftime("%d.%m.%Y"), "label": d.strftime("%a")})
    return days

# ---------------- Root ----------------
@app.get("/", response_class=RedirectResponse)
def root():
    return RedirectResponse("/week", status_code=303)

# ---------------- Wochenansicht ----------------
@app.get("/week", response_class=HTMLResponse, name="week_view")
def week_view(request: Request, standort_id: int = None, kw: int = None, year: int = None):
    require_login(request)
    user = request.session["user"]

    conn = get_conn()
    c = conn.cursor()

    # Standorte
    c.execute("SELECT * FROM standorte")
    standorte = c.fetchall()
    if not standorte:
        c.executemany("INSERT INTO standorte(name) VALUES (?)", [("Engelbrechts",), ("Groß Gerungs",)])
        conn.commit()
        c.execute("SELECT * FROM standorte")
        standorte = c.fetchall()

    standort_id = standort_id or standorte[0]["id"]

    # Kalenderwoche / Jahr
    today = date.today()
    cur_kw = today.isocalendar()[1]
    cur_year = today.year
    kw = kw or cur_kw
    year = year or cur_year

    # Wochentage & Grid
    workdays = 5
    employee_lines = 10
    days = get_week_days(year, kw, workdays)

    # Weekplan
    c.execute("SELECT * FROM week_plans WHERE year=? AND kw=? AND standort_id=?", (year, kw, standort_id))
    wp = c.fetchone()
    if not wp:
        c.execute("INSERT INTO week_plans(year, kw, standort_id) VALUES (?,?,?)", (year, kw, standort_id))
        conn.commit()
        c.execute("SELECT * FROM week_plans WHERE year=? AND kw=? AND standort_id=?", (year, kw, standort_id))
        wp = c.fetchone()

    week_plan_id = wp["id"]

    # Week Cells
    c.execute("SELECT COUNT(*) AS n FROM week_cells WHERE week_plan_id=?", (week_plan_id,))
    if c.fetchone()["n"] == 0:
        for d in range(workdays):
            for r in range(employee_lines):
                c.execute(
                    "INSERT INTO week_cells(week_plan_id, day_index, row_index, job_id) VALUES (?,?,?,NULL)",
                    (week_plan_id, d, r)
                )
        conn.commit()

    # Cells laden
    c.execute("""
        SELECT wc.*, j.title, j.customer_name, j.color, j.status
        FROM week_cells wc
        LEFT JOIN jobs j ON wc.job_id=j.id
        WHERE wc.week_plan_id=?
        ORDER BY wc.row_index, wc.day_index
    """, (week_plan_id,))
    cells = c.fetchall()

    # Grid bauen
    grid = [[None for _ in range(workdays)] for _ in range(employee_lines)]
    for cell in cells:
        r = cell["row_index"]
        d = cell["day_index"]
        grid[r][d] = dict(cell)

    # Jobs
    c.execute("SELECT * FROM jobs WHERE standort_id=?", (standort_id,))
    jobs = c.fetchall()

    conn.close()

    return templates.TemplateResponse(
        "week.html",
        {
            "request": request,
            "standorte": standorte,
            "standort_id": standort_id,
            "year": year,
            "kw": kw,
            "days": days,
            "grid": grid,
            "employee_lines": employee_lines,
            "workdays": workdays,
            "week_plan_id": week_plan_id,
            "jobs": jobs,
            "can_edit": True,
            "role": user["role"],
        }
    )

# ---------------- Dummy-Routen für base.html ----------------
@app.get("/year", name="year_view")
def year_view(request: Request):
    return HTMLResponse("<h1>Jahresplanung</h1>")

@app.get("/settings", name="settings_view")
def settings_view(request: Request):
    return HTMLResponse("<h1>Einstellungen</h1>")

@app.get("/auth/logout", name="logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/week")

# ---------------- API: Zelle setzen ----------------
@app.post("/api/week/set-cell")
def set_cell(
    request: Request,
    week_plan_id: int = Form(...),
    day_index: int = Form(...),
    row_index: int = Form(...),
    job_id: int = Form(None),
):
    require_login(request)
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "UPDATE week_cells SET job_id=? WHERE week_plan_id=? AND day_index=? AND row_index=?",
        (job_id, week_plan_id, day_index, row_index),
    )
    conn.commit()
    conn.close()
    return RedirectResponse("/week", status_code=303)
