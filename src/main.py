from fastapi import FastAPI, Request, Form
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

import os
from pathlib import Path

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
# MVP Login (immer aktiv)
# --------------------------------------------------
def require_login(request: Request):
    if "user" not in request.session:
        request.session["user"] = {
            "role": "write",
            "viewer_standort_id": 1,
        }

# --------------------------------------------------
# Health
# --------------------------------------------------
@app.get("/health")
def health():
    return {"status": "ok"}

# --------------------------------------------------
# Root → week
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
    try:
        require_login(request)

        conn = get_conn()
        c = conn.cursor()

        # Standorte
        c.execute("SELECT * FROM standorte")
        standorte = c.fetchall()

        standort_id = standort_id or standorte[0]["id"]

        # KW / Jahr
        cur_kw, cur_year = current_kw_and_year()
        year = year or cur_year
        kw = kw or cur_kw

        # workdays
        workdays = workdays_auto_dst()
        if not workdays:
            raise Exception("workdays_auto_dst() returned None or 0")

        # settings
        c.execute("SELECT * FROM settings WHERE standort_id=?", (standort_id,))
        settings = c.fetchone()
        employee_lines = settings["employee_lines"] if settings else 10

        # week plan
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

        # cells
        c.execute(
            """
            SELECT wc.*, j.title
            FROM week_cells wc
            LEFT JOIN jobs j ON wc.job_id=j.id
            WHERE wc.week_plan_id=?
            """,
            (wp["id"],),
        )
        cells = c.fetchall()

        # grid
        grid = [[None for _ in range(workdays)] for _ in range(employee_lines)]
        for cell in cells:
            r = cell["row_index"]
            d = cell["day_index"]
            grid[r][d] = dict(cell)

        # days
       raw_days = kw_date_range(year, kw, workdays)

days = []
for d in raw_days:
    # Fall 1: Tuple (date, label)
    if isinstance(d, (list, tuple)) and len(d) == 2:
        date_obj, label = d
    else:
        # Fall 2: nur date
        date_obj = d
        label = date_obj.strftime("%a")

    days.append({
        "label": label,
        "date": date_obj.strftime("%d.%m.%Y")
    })
        if not days:
            raise Exception("kw_date_range() returned None or empty")

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
            },
        )

    except Exception as e:
        return HTMLResponse(
            f"""
            <h1>WEEK VIEW ERROR</h1>
            <pre>{repr(e)}</pre>
            """,
            status_code=500,
        )

@app.get("/debug/db")
def debug_db():
    try:
        conn = get_conn()
        c = conn.cursor()

        c.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r["name"] for r in c.fetchall()]

        conn.close()
        return {
            "ok": True,
            "tables": tables,
        }

    except Exception as e:
        return {
            "ok": False,
            "error": str(e),
        }
