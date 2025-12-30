# src/main.py
import os
from datetime import date, timedelta

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from db import get_conn, init_db

# --------------------------------------------------
# App
# --------------------------------------------------
app = FastAPI(title="Zankl Plan")

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SESSION_SECRET", "dev-secret"),
)

# --------------------------------------------------
# Startup
# --------------------------------------------------
@app.on_event("startup")
def startup():
    init_db()


# --------------------------------------------------
# Dummy Login (vorerst)
# --------------------------------------------------
def require_login(request: Request):
    if "user" not in request.session:
        request.session["user"] = {
            "role": "write",
            "standort_id": 1,
        }


# --------------------------------------------------
# Helpers
# --------------------------------------------------
def get_week_days(year: int, kw: int, workdays: int = 5):
    monday = date.fromisocalendar(year, kw, 1)
    labels = ["Mo", "Di", "Mi", "Do", "Fr"]
    days = []

    for i in range(workdays):
        d = monday + timedelta(days=i)
        days.append({
            "label": labels[i],
            "date": d.strftime("%d.%m.%Y"),
        })

    return days


def get_or_create_week_plan(conn, year, kw, standort_id):
    c = conn.cursor()
    c.execute(
        """
        SELECT id FROM week_plans
        WHERE year=? AND kw=? AND standort_id=?
        """,
        (year, kw, standort_id),
    )
    row = c.fetchone()
    if row:
        return row["id"]

    c.execute(
        """
        INSERT INTO week_plans (year, kw, standort_id)
        VALUES (?,?,?)
        """,
        (year, kw, standort_id),
    )
    conn.commit()
    return c.lastrowid


# --------------------------------------------------
# Root
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
    standort_id: int = 1,
    kw: int | None = None,
    year: int | None = None,
):
    require_login(request)

    today = date.today()
    kw = kw or today.isocalendar()[1]
    year = year or today.year
    workdays = 5

    conn = get_conn()
    c = conn.cursor()

    # Standorte
    c.execute("SELECT * FROM standorte ORDER BY id")
    standorte = [dict(r) for r in c.fetchall()]

    # Mitarbeiter (fixe Zeilen!)
    c.execute(
        """
        SELECT * FROM mitarbeiter
        WHERE standort_id=? AND aktiv=1
        ORDER BY sort_order
        """,
        (standort_id,),
    )
    mitarbeiter = [dict(r) for r in c.fetchall()]

    # Weekplan
    week_plan_id = get_or_create_week_plan(conn, year, kw, standort_id)

    # Zellen laden
    c.execute(
        """
        SELECT * FROM week_cells
        WHERE week_plan_id=?
        """,
        (week_plan_id,),
    )
    cells = [dict(r) for r in c.fetchall()]

    # Falls noch keine Zellen existieren → anlegen
    if not cells:
        for m in mitarbeiter:
            for d in range(workdays):
                c.execute(
                    """
                    INSERT INTO week_cells
                    (week_plan_id, mitarbeiter_id, day_index, text, color)
                    VALUES (?,?,?,?,?)
                    """,
                    (week_plan_id, m["id"], d, "", None),
                )
        conn.commit()

        c.execute(
            "SELECT * FROM week_cells WHERE week_plan_id=?",
            (week_plan_id,),
        )
        cells = [dict(r) for r in c.fetchall()]

    # Grid bauen: mitarbeiter_id → tage
    grid = {}
    for m in mitarbeiter:
        grid[m["id"]] = [None] * workdays

    for cell in cells:
        grid[cell["mitarbeiter_id"]][cell["day_index"]] = cell

    days = get_week_days(year, kw, workdays)

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
            "mitarbeiter": mitarbeiter,
            "grid": grid,
            "week_plan_id": week_plan_id,
        },
    )


# --------------------------------------------------
# API: Zelle speichern (AUTO-SAVE)
# --------------------------------------------------
@app.post("/api/week/set-cell", response_class=JSONResponse)
def set_cell(
    request: Request,
    week_plan_id: int = Form(...),
    mitarbeiter_id: int = Form(...),
    day_index: int = Form(...),
    text: str = Form(""),
    color: str | None = Form(None),
):
    require_login(request)

    conn = get_conn()
    c = conn.cursor()

    c.execute(
        """
        UPDATE week_cells
        SET text=?, color=?
        WHERE week_plan_id=? AND mitarbeiter_id=? AND day_index=?
        """,
        (text, color, week_plan_id, mitarbeiter_id, day_index),
    )

    conn.commit()
    conn.close()

    return {"success": True}
