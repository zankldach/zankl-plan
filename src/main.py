from fastapi import FastAPI, Request, Form
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

import os
from pathlib import Path
from datetime import date

# --------------------------------------------------
# Pfade
# --------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# --------------------------------------------------
# App
# --------------------------------------------------
app = FastAPI(title="Zankl Plan")

# --------------------------------------------------
# Static Files
# --------------------------------------------------
static_dir = BASE_DIR / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# --------------------------------------------------
# Sessions
# --------------------------------------------------
SESSION_SECRET = os.getenv("SESSION_SECRET", "dev-secret")
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)

# --------------------------------------------------
# Eigene Module
# --------------------------------------------------
from .db import init_db, get_conn
from .util import (
    current_kw_and_year,
    next_week_if_after_friday_noon,
    kw_date_range,
    workdays_auto_dst,
)

# --------------------------------------------------
# Startup
# --------------------------------------------------
@app.on_event("startup")
def startup():
    init_db()

# --------------------------------------------------
# MVP Login (immer write – TESTBETRIEB)
# --------------------------------------------------
def require_login(request: Request):
    if "user" not in request.session:
        request.session["user"] = {
            "role": "write",
            "viewer_standort_id": 1
        }

# --------------------------------------------------
# Healthcheck
# --------------------------------------------------
@app.get("/health")
def health():
    return {"status": "ok"}

# --------------------------------------------------
# Startseite
# --------------------------------------------------
@app.get("/", response_class=RedirectResponse)
def root():
    return RedirectResponse("/week", status_code=303)

# --------------------------------------------------
# Wochenansicht
# --------------------------------------------------
@app.get("/week", response_class=HTMLResponse)
def week_view(
    request: Request,
    standort_id: int | None = None,
    year: int | None = None,
    kw: int | None = None,
):
    require_login(request)
    user = request.session["user"]

    conn = get_conn()
    c = conn.cursor()

    # ---------------- Standorte ----------------
    c.execute("SELECT * FROM standorte")
    standorte = c.fetchall()

    if not standorte:
        c.executemany(
            "INSERT INTO standorte(name) VALUES (?)",
            [("Engelbrechts",), ("Groß Gerungs",)]
        )
        conn.commit()
        c.execute("SELECT * FROM standorte")
        standorte = c.fetchall()

    standort_id = standort_id or standorte[0]["id"]

    # ---------------- KW / Jahr ----------------
    cur_kw, cur_year = current_kw_and_year()
    year = year or cur_year

    if next_week_if_after_friday_noon():
        cur_kw += 1

    kw = kw or cur_kw

    # ---------------- Settings ----------------
    c.execute("SELECT * FROM settings WHERE standort_id=?", (standort_id,))
    settings = c.fetchone()

    employee_lines = settings["employee_lines"] if settings else 10
    workdays = workdays_auto_dst()

    # ---------------- WeekPlan ----------------
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

    # ---------------- WeekCells ----------------
    c.execute("SELECT COUNT(*) AS n FROM week_cells WHERE week_plan_id=?", (wp["id"],))
    if c.fetchone()["n"] == 0:
        for d in range(workdays):
            for r in range(employee_lines):
                c.execute(
                    """
                    INSERT INTO week_cells
                    (week_plan_id, day_index, row_index, job_id)
                    VALUES (?,?,?,NULL)
                    """,
                    (wp["id"], d, r),
                )
        conn.commit()

    # ---------------- Cells laden ----------------
    c.execute(
        """
        SELECT wc.*, j.title, j.customer_name, j.color, j.status
        FROM week_cells wc
        LEFT JOIN jobs j ON wc.job_id=j.id
        WHERE wc.week_plan_id=?
        ORDER BY wc.row_index, wc.day_index
        """,
        (wp["id"],),
    )
    cells = c.fetchall()

    # ---------------- Grid bauen ----------------
    grid = [[None for _ in range(workdays)] for _ in range(employee_lines)]
    for cell in cells:
        r = cell["row_index"]
        d = cell["day_index"]
        grid[r][d] = dict(cell)

    # ---------------- Tage sauber aufbereiten ----------------
    raw_days = kw_date_range(year, kw, workdays)
    days = []

    for d in raw_days:
        if isinstance(d, (list, tuple)) and len(d) == 2:
            date_obj, label = d
        else:
            date_obj = d
            label = date_obj.strftime("%a")

        days.append({
            "label": label,
            "date": date_obj.strftime("%d.%m.%Y")
        })

    # ---------------- Jobs ----------------
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
            "week_plan_id": wp["id"],
            "jobs": jobs,
            "can_edit": True,
            "role": user["role"],
        },
    )

# --------------------------------------------------
# Zelle setzen
# --------------------------------------------------
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
        """
        UPDATE week_cells
        SET job_id=?
        WHERE week_plan_id=? AND day_index=? AND row_index=?
        """,
        (job_id, week_plan_id, day_index, row_index),
    )
    conn.commit()
    conn.close()

    return RedirectResponse("/week", status_code=303)
