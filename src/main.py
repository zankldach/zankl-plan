from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import sqlite3
from datetime import date

# --------------------------------------------------
# APP SETUP
# --------------------------------------------------
app = FastAPI(title="Zankl Plan – Stable")

BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent
DB_PATH = BASE_DIR / "zankl.db"

templates = Jinja2Templates(directory=str(ROOT_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(ROOT_DIR / "static")), name="static")


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
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            standort TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS week_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            year INTEGER,
            kw INTEGER,
            standort TEXT
        )
    """)

    conn.commit()
    conn.close()


@app.on_event("startup")
def startup():
    init_db()


# --------------------------------------------------
# HEALTH (RENDER!)
# --------------------------------------------------
@app.get("/health")
def health():
    return {"status": "ok"}


# --------------------------------------------------
# ROOT
# --------------------------------------------------
@app.get("/")
def root():
    return RedirectResponse("/week")


# --------------------------------------------------
# WEEK (EDIT)
# --------------------------------------------------
@app.get("/week", response_class=HTMLResponse)
def week(request: Request, standort: str = "engelbrechts"):
    today = date.today()
    year = today.year
    kw = today.isocalendar().week

    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        "SELECT * FROM employees WHERE standort=? ORDER BY id",
        (standort,)
    )
    employees = cur.fetchall()

    conn.close()

    return templates.TemplateResponse(
        "week.html",
        {
            "request": request,
            "year": year,
            "kw": kw,
            "standort": standort,
            "employees": employees,
        }
    )


# --------------------------------------------------
# SETTINGS – EMPLOYEES ✅ (WAR WEG!)
# --------------------------------------------------
@app.get("/settings/employees", response_class=HTMLResponse)
def settings_employees(request: Request, standort: str = "engelbrechts"):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        "SELECT * FROM employees WHERE standort=? ORDER BY id",
        (standort,)
    )
    employees = cur.fetchall()

    conn.close()

    return templates.TemplateResponse(
        "settings_employees.html",
        {
            "request": request,
            "employees": employees,
            "standort": standort,
        }
    )


@app.post("/settings/employees/add")
def add_employee(
    name: str = Form(...),
    standort: str = Form(...)
):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        "INSERT INTO employees (name, standort) VALUES (?, ?)",
        (name, standort)
    )

    conn.commit()
    conn.close()

    return RedirectResponse(
        f"/settings/employees?standort={standort}",
        status_code=303
    )

