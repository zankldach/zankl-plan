from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import sqlite3
from datetime import date

app = FastAPI()
templates = Jinja2Templates(directory="src/templates")

DB_PATH = "data.db"


# -------------------------------------------------
# DB HELPER
# -------------------------------------------------
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    # week_plans
    cur.execute("""
        CREATE TABLE IF NOT EXISTS week_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            year INTEGER NOT NULL,
            kw INTEGER NOT NULL,
            standort TEXT NOT NULL,
            row_count INTEGER DEFAULT 5,
            four_day_week INTEGER DEFAULT 0
        )
    """)

    # employees
    cur.execute("""
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            standort TEXT NOT NULL,
            active INTEGER DEFAULT 1
        )
    """)

    conn.commit()
    conn.close()


@app.on_event("startup")
def startup():
    init_db()


# -------------------------------------------------
# WEEK – EDITIERBAR
# -------------------------------------------------
@app.get("/week", response_class=HTMLResponse)
def week(request: Request, year: int | None = None, kw: int | None = None, standort: str = "Hauptbetrieb"):
    today = date.today()
    year = year or today.year
    kw = kw or today.isocalendar().week

    conn = get_conn()
    cur = conn.cursor()

    # Week Plan
    cur.execute(
        "SELECT * FROM week_plans WHERE year=? AND kw=? AND standort=?",
        (year, kw, standort)
    )
    plan = cur.fetchone()

    if not plan:
        cur.execute(
            "INSERT INTO week_plans (year, kw, standort) VALUES (?, ?, ?)",
            (year, kw, standort)
        )
        conn.commit()
        cur.execute(
            "SELECT * FROM week_plans WHERE year=? AND kw=? AND standort=?",
            (year, kw, standort)
        )
        plan = cur.fetchone()

    # Employees
    cur.execute(
        "SELECT * FROM employees WHERE standort=? AND active=1 ORDER BY name",
        (standort,)
    )
    employees = cur.fetchall()

    rows = max(5, len(employees))

    conn.close()

    return templates.TemplateResponse(
        "week.html",
        {
            "request": request,
            "year": year,
            "kw": kw,
            "standort": standort,
            "plan": plan,
            "employees": employees,
            "rows": rows,
        },
    )


# -------------------------------------------------
# WEEK – VIEW ONLY
# -------------------------------------------------
@app.get("/view/week", response_class=HTMLResponse)
def view_week(request: Request, year: int | None = None, kw: int | None = None, standort: str = "Hauptbetrieb"):
    today = date.today()
    year = year or today.year
    kw = kw or today.isocalendar().week

    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        "SELECT * FROM week_plans WHERE year=? AND kw=? AND standort=?",
        (year, kw, standort)
    )
    plan = cur.fetchone()

    cur.execute(
        "SELECT * FROM employees WHERE standort=? AND active=1 ORDER BY name",
        (standort,)
    )
    employees = cur.fetchall()

    rows = max(5, len(employees))
    conn.close()

    return templates.TemplateResponse(
        "week_view.html",
        {
            "request": request,
            "year": year,
            "kw": kw,
            "standort": standort,
            "plan": plan,
            "employees": employees,
            "rows": rows,
        },
    )
