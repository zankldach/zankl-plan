
# --- Diagnose-Endpunkte ---
@app.get("/debug/env")
def debug_env():
    import os
    return {
        "SESSION_SECRET_set": bool(os.getenv("SESSION_SECRET")),
    }

@app.get("/debug/db")
def debug_db():
    try:
        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r["name"] for r in c.fetchall()]
        counts = {}
        for t in ["users","standorte","settings","week_plans","week_cells","jobs","small_jobs","resource_types","year_events"]:
            try:
                c.execute(f"SELECT COUNT(*) AS n FROM {t}")
                counts[t] = c.fetchone()["n"]
            except Exception as e:
                counts[t] = f"ERR: {e}"
        conn.close()
        return {"ok": True, "tables": tables, "counts": counts}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# src/main.py
from fastapi import FastAPI, Request, Form
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

import os
from pathlib import Path

# -------- Pfade & Templates/Static --------
BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# -------- App, Static, Sessions --------
app = FastAPI()
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

SESSION_SECRET = os.getenv("SESSION_SECRET", "dev-key")  # auf Render ENV setzen
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)

# -------- Eigene Module (src/*) --------
from .db import init_db, get_conn
from .util import (
    current_kw_and_year,
    next_week_if_after_friday_noon,
    kw_date_range,
    workdays_auto_dst,
)

# (optional) Auth-Router, falls vorhanden:
try:
    from .auth import router as auth_router
    app.include_router(auth_router, prefix="/auth")
except Exception:
    # Falls noch kein auth.py existiert, App trotzdem starten
    pass

# --- Diagnose-Endpunkte ---
@app.get("/debug/env")
def debug_env():
    import os
    return {
        "SESSION_SECRET_set": bool(os.getenv("SESSION_SECRET")),
    }

@app.get("/debug/db")
def debug_db():
    try:
        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r["name"] for r in c.fetchall()]
        counts = {}
        for t in ["users","standorte","settings","week_plans","week_cells","jobs","small_jobs","resource_types","year_events"]:
            try:
                c.execute(f"SELECT COUNT(*) AS n FROM {t}")
                counts[t] = c.fetchone()["n"]
            except Exception as e:
                counts[t] = f"ERR: {e}"
        conn.close()
        return {"ok": True, "tables": tables, "counts": counts}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# -------- Login-Helfer (MVP: auto-login Viewer) --------
def require_login(request: Request) -> bool:
    user = request.session.get("user")
    if user:
        return True
    # MVP: automatischer Login des Demo-Viewers, um sofort testen zu können
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE email=?", ("viewer@demo",))
    row = c.fetchone()
    conn.close()
    if row:
        request.session["user"] = dict(row)
        return True
    return False

# -------- Startup: DB initialisieren --------
@app.on_event("startup")
def on_startup():
    init_db()

# -------- Healthcheck (einmalig) --------
@app.get("/health")
def health():
    return {"status": "ok"}

# -------- Startseite: Redirect auf Wochenansicht --------
@app.get("/", response_class=RedirectResponse)
def root():
    return RedirectResponse(url="/week", status_code=303)

# -------------------- Wochenplanung --------------------
@app.get("/week", response_class=HTMLResponse)
def week_view(request: Request, standort_id: int = None, year: int = None, kw: int = None):
    if not require_login(request):
        return RedirectResponse("/login")

    user = request.session["user"]

    conn = get_conn()
    c = conn.cursor()

    # Standorte
    c.execute("SELECT * FROM standorte")
    standorte = c.fetchall()

    # Default Standort
    if standort_id is None:
        standort_id = user.get("viewer_standort_id") or (standorte[0]["id"] if standorte else 1)

    # KW/Year default
    cur_kw, cur_year = current_kw_and_year()
    year = year or cur_year
    if user["role"] == "view" and next_week_if_after_friday_noon():
        cur_kw += 1
        if cur_kw > 52:
            cur_kw = 1
            year += 1
    kw = kw or cur_kw

    # Einstellungen
    c.execute("SELECT * FROM settings WHERE standort_id=?", (standort_id,))
    settings = c.fetchone()
    workdays = workdays_auto_dst()
    employee_lines = settings["employee_lines"] if settings else 10

    # Week plan sicherstellen
    c.execute("SELECT * FROM week_plans WHERE year=? AND kw=? AND standort_id=?", (year, kw, standort_id))
    wp = c.fetchone()
    if not wp:
        c.execute("INSERT INTO week_plans(year, kw, standort_id) VALUES (?,?,?)", (year, kw, standort_id))
        conn.commit()
        c.execute("SELECT * FROM week_plans WHERE year=? AND kw=? AND standort_id=?", (year, kw, standort_id))
        wp = c.fetchone()

    # Zellen initialisieren
    c.execute("SELECT COUNT(*) AS n FROM week_cells WHERE week_plan_id=?", (wp["id"],))
    if c.fetchone()["n"] == 0:
        for day in range(workdays):
            for row in range(employee_lines):
                c.execute(
                    "INSERT INTO week_cells(week_plan_id, day_index, row_index, job_id) VALUES (?,?,?,NULL)",
                    (wp["id"], day, row),
                )
        conn.commit()

    # Daten für die Ansicht
    c.execute("""
        SELECT wc.*, j.title, j.customer_name, j.color
        FROM week_cells wc
        LEFT JOIN jobs j ON wc.job_id=j.id
        WHERE wc.week_plan_id=?
        ORDER BY wc.row_index, wc.day_index
    """, (wp["id"],))
    cells = c.fetchall()

    c.execute("SELECT * FROM jobs WHERE standort_id=? AND status!='fertig'", (standort_id,))
    jobs = c.fetchall()

    c.execute("SELECT * FROM small_jobs WHERE standort_id=?", (standort_id,))
    small_jobs = c.fetchall()

    conn.close()

    days = kw_date_range(year, kw, workdays)
    can_edit = (user["role"] in ("admin", "write"))

    return templates.TemplateResponse("week.html", {
        "request": request,
        "standorte": standorte,
        "standort_id": standort_id,
        "year": year,
        "kw": kw,
        "days": days,
        "employee_lines": employee_lines,
        "cells": cells,
        "jobs": jobs,
        "small_jobs": small_jobs,
        "can_edit": can_edit,
        "role": user["role"]
    })


@app.post("/api/week/set-cell")
def set_cell(request: Request,
             week_plan_id: int = Form(...),
             day_index: int = Form(...),
             row_index: int = Form(...),
             job_id: int = Form(None)):
    user = request.session.get("user")
    if not user or user["role"] not in ("admin", "write"):
        return RedirectResponse("/week")
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        UPDATE week_cells SET job_id=? WHERE week_plan_id=? AND day_index=? AND row_index=?
    """, (job_id, week_plan_id, day_index, row_index))
    conn.commit()
    conn.close()
    return RedirectResponse("/week", status_code=303)

# -------------------- Jahresplanung (MVP) --------------------
@app.get("/year", response_class=HTMLResponse)
def year_view(request: Request, year: int = None):
    if not require_login(request):
        return RedirectResponse("/login")
    user = request.session["user"]
    year = year or current_kw_and_year()[1]

    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM standorte")
    standorte = c.fetchall()
    c.execute("""
        SELECT ye.*, j.title, j.customer_name, j.color, j.status
        FROM year_events ye LEFT JOIN jobs j ON ye.job_id=j.id
        ORDER BY ye.standort_id, ye.start_date
    """)
    events = c.fetchall()
    c.execute("SELECT * FROM resource_types")
    resource_types = c.fetchall()
    conn.close()

    return templates.TemplateResponse("year.html", {
        "request": request,
        "role": user["role"],
        "year": year,
        "standorte": standorte,
        "events": events,
        "resource_types": resource_types,
    })

# -------------------- Einstellungen --------------------
@app.get("/settings", response_class=HTMLResponse)
def settings_view(request: Request):
    if not require_login(request):
        return RedirectResponse("/login")
    user = request.session["user"]
    if user["role"] != "admin":
        return RedirectResponse("/", status_code=303)

    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM standorte")
    standorte = c.fetchall()
    c.execute("SELECT * FROM settings")
    settings = c.fetchall()
    conn.close()

    return templates.TemplateResponse("settings.html", {
        "request": request,
        "standorte": standorte,
        "settings": settings
    })


@app.post("/settings/update")
def settings_update(request: Request,
                    standort_id: int = Form(...),
                    workdays: int = Form(...),
                    employee_lines: int = Form(...)):
    user = request.session.get("user")
    if not user or user["role"] != "admin":
        return RedirectResponse("/")

    conn = get_conn()
    c = conn.cursor()
    c.execute("""UPDATE settings SET workdays=?, employee_lines=? WHERE standort_id=?""",
              (workdays, employee_lines, standort_id))
    conn.commit()
    conn.close()
    return RedirectResponse("/settings", status_code=303)

# -------------------- Benutzer-Zuordnung Viewer -> Standort --------------------
from fastapi import Form as _Form

@app.get("/settings/users", response_class=HTMLResponse)
def settings_users_view(request: Request):
    if not require_login(request):
        return RedirectResponse("/login")
    u = request.session["user"]
    if u["role"] != "admin":
        return RedirectResponse("/", status_code=303)
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM users ORDER BY role, name")
    users = c.fetchall()
    c.execute("SELECT * FROM standorte")
    standorte = c.fetchall()
    conn.close()
    return templates.TemplateResponse("settings_users.html", {
        "request": request,
        "users": users,
        "standorte": standorte
    })

@app.post("/settings/users/set-viewer-standort")
def set_viewer_standort(request: Request, user_id: int = _Form(...), standort_id: int = _Form(...)):
    u = request.session.get("user")
    if not u or u["role"] != "admin":
        return RedirectResponse("/", status_code=303)
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE users SET viewer_standort_id=? WHERE id=?", (standort_id, user_id))
    conn.commit()
    conn.close()
    return RedirectResponse("/settings/users", status_code=303)
