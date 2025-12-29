import os
import sqlite3
from datetime import date, timedelta

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
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
    c = conn.cursor()

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
            text TEXT
        )
    """)

    conn.commit()
    conn.close()


@app.on_event("startup")
def startup():
    init_db()


# ---------------- Login ----------------
def require_login(request: Request):
    if "user" not in request.session:
        request.session["user"] = {"role": "write"}


# ---------------- Helpers ----------------
def get_week_days(year: int, kw: int, workdays=5):
    monday = date.fromisocalendar(year, kw, 1)
    labels = ["Mo", "Di", "Mi", "Do", "Fr"]
    days = []
    for i in range(workdays):
        d = monday + timedelta(days=i)
        days.append({
            "date": d.strftime("%d.%m.%Y"),
            "label": labels[i],
        })
    return days


# ---------------- Root ----------------
@app.get("/", response_class=RedirectResponse)
def root():
    return RedirectResponse("/week", status_code=303)


# ---------------- Wochenansicht ----------------
@app.get("/week", response_class=HTMLResponse)
def week_view(
    request: Request,
    standort_id: int = 1,
    kw: int = None,
    year: int = None,
):
    require_login(request)

    today = date.today()
    kw = kw or today.isocalendar()[1]
    year = year or today.year

    workdays = 5
    employee_lines = 10

    conn = get_conn()
    c = conn.cursor()

    # Standorte initialisieren
    c.execute("SELECT * FROM standorte")
    standorte = [dict(r) for r in c.fetchall()]

    if not standorte:
        c.executemany(
            "INSERT INTO standorte(name) VALUES (?)",
            [("Engelbrechts",), ("Groß Gerungs",)],
        )
        conn.commit()
        c.execute("SELECT * FROM standorte")
        standorte = [dict(r) for r in c.fetchall()]

    # Weekplan
    c.execute(
        "SELECT * FROM week_plans WHERE year=? AND kw=? AND standort_id=?",
        (year, kw, standort_id),
    )
    wp = c.fetchone()

    if not wp:
        c.execute(
            "INSERT INTO week_plans(year, kw, standort_id) VALUES (?,?,?)",
            (year, kw, standort_id),
        )
        conn.commit()
        c.execute(
            "SELECT * FROM week_plans WHERE year=? AND kw=? AND standort_id=?",
            (year, kw, standort_id),
        )
        wp = c.fetchone()

    week_plan_id = wp["id"]

    # Zellen anlegen falls leer
    c.execute(
        "SELECT COUNT(*) AS n FROM week_cells WHERE week_plan_id=?",
        (week_plan_id,),
    )
    if c.fetchone()["n"] == 0:
        for r in range(employee_lines):
            for d in range(workdays):
                c.execute(
                    """
                    INSERT INTO week_cells
                    (week_plan_id, day_index, row_index, text)
                    VALUES (?,?,?,?)
                    """,
                    (week_plan_id, d, r, ""),
                )
        conn.commit()

    # Zellen laden
    c.execute(
        """
        SELECT * FROM week_cells
        WHERE week_plan_id=?
        ORDER BY row_index, day_index
        """,
        (week_plan_id,),
    )

    rows = [dict(r) for r in c.fetchall()]
    conn.close()

    # Grid bauen
    grid = [
        [None for _ in range(workdays)]
        for _ in range(employee_lines)
    ]

    for cell in rows:
        r = cell["row_index"]
        d = cell["day_index"]
        grid[r][d] = cell

    days = get_week_days(year, kw, workdays)

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
        },
    )


# ---------------- API: Zelle speichern ----------------
@app.post("/api/week/set-cell")
def set_cell(
    request: Request,
    week_plan_id: int = Form(...),
    day_index: int = Form(...),
    row_index: int = Form(...),
    text: str = Form(""),
):
    require_login(request)

    conn = get_conn()
    c = conn.cursor()

    c.execute(
        """
        UPDATE week_cells
        SET text=?
        WHERE week_plan_id=? AND day_index=? AND row_index=?
        """,
        (text, week_plan_id, day_index, row_index),
    )

    conn.commit()
    conn.close()

    return {"success": True}
