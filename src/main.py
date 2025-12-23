
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
app = FastAPI(title="Zankl Plan")

static_dir = BASE_DIR / "static"
if static_dir.is_dir():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

SESSION_SECRET = os.getenv("SESSION_SECRET", "dev-key")  # auf Render ENV gesetzt?
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
    return {
        "SESSION_SECRET_set": bool(os.getenv("SESSION_SECRET")),
        "cwd": str(BASE_DIR.parent),
        "db": str((BASE_DIR.parent / "data" / "app.db").resolve()),
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
    # Session schon gesetzt?
    if request.session.get("user"):
        return True

    # Versuch: Demo-Viewer aus DB
    try:
        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE email=?", ("viewer@demo",))
        row = c.fetchone()
        conn.close()
        if row:
            request.session["user"] = dict(row)
            return True
    except Exception:
        pass

    # MVP-Fallback: Session setzen, damit /week nicht 500 wird
    request.session["user"] = {"role": "view", "viewer_standort_id": 1}
    return True

# -------- Startup: DB initialisieren --------
@app.on_event("startup")
def on_startup():
    try:
        init_db()
    except Exception as e:
        print("INIT_DB ERROR:", e)

# -------- Healthcheck --------
@app.get("/health")
def health():
    return {"status": "ok"}

# -------- Rausnehmen --------
@app.get("/debug/make-viewer-write")
def make_viewer_write():
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE users SET role='write' WHERE email=?", ("viewer@demo",))
    conn.commit()
    conn.close()
    return {"ok": True}


# -------- Startseite: Redirect auf Wochenansicht --------
@app.get("/", response_class=RedirectResponse)
def root():
    return RedirectResponse(url="/week", status_code=303)

# -------------------- Wochenplanung --------------------
@app.get("/week", response_class=HTMLResponse)

@app.get("/week", response_class=HTMLResponse)
def week_view(request: Request, standort_id: int = None, year: int = None, kw: int = None):
    try:
        require_login(request)
        user = request.session.get("user", {"role": "view", "viewer_standort_id": 1})

        conn = get_conn()
        c = conn.cursor()

        # Standorte holen / notfalls seeden
        c.execute("SELECT * FROM standorte")
        standorte = c.fetchall()
        if not standorte:
            c.executemany("INSERT INTO standorte(name) VALUES (?)", [("Engelbrechts",), ("Groß Gerungs",)])
            conn.commit()
            c.execute("SELECT * FROM standorte")
            standorte = c.fetchall()

        # Default Standort
        if standort_id is None:
            standort_id = user.get("viewer_standort_id") or (standorte[0]["id"] if standorte else 1)

        # KW/Year default
        cur_kw, cur_year = current_kw_and_year()
        year = year or cur_year
        if user.get("role") == "view" and next_week_if_after_friday_noon():
            cur_kw += 1
            if cur_kw > 52:
                cur_kw = 1
                year += 1
        kw = kw or cur_kw

        # Einstellungen je Standort
        c.execute("SELECT * FROM settings WHERE standort_id=?", (standort_id,))
        settings_row = c.fetchone()
        workdays = workdays_auto_dst()
        employee_lines = settings_row["employee_lines"] if settings_row else 10

        # Week plan sicherstellen
        c.execute("SELECT * FROM week_plans WHERE year=? AND kw=? AND standort_id=?", (year, kw, standort_id))
        wp = c.fetchone()
        if not wp:
            c.execute("INSERT INTO week_plans(year, kw, standort_id) VALUES (?,?,?)", (year, kw, standort_id))
            conn.commit()
            c.execute("SELECT * FROM week_plans WHERE year=? AND kw=? AND standort_id=?", (year, kw, standort_id))
            wp = c.fetchone()

        # Zellen initialisieren (falls leer)
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
            SELECT wc.*, j.title, j.customer_name, j.color, j.status
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

        # Grid bauen: rows = Mitarbeiterlinien, cols = Arbeitstage
        grid = [[None for _ in range(workdays)] for _ in range(employee_lines)]
        for cell in cells:
            r = cell["row_index"]
            d = cell["day_index"]
            if 0 <= r < employee_lines and 0 <= d < workdays:
                grid[r][d] = dict(cell)

        days = kw_date_range(year, kw, workdays)
        can_edit = (user.get("role") in ("admin", "write"))

        return templates.TemplateResponse("week.html", {
            "request": request,
            "standorte": standorte,
            "standort_id": standort_id,
            "year": year,
            "kw": kw,
            "days": days,
            "employee_lines": employee_lines,
            "workdays": workdays,
            "grid": grid,                  # << neu: fertiges Grid
            "week_plan_id": wp["id"],      # << neu: für POST
            "jobs": jobs,
            "small_jobs": small_jobs,
            "can_edit": can_edit,
            "role": user.get("role"),
        })

    except Exception as e:
        print("WEEK ERROR:", repr(e))
        return HTMLResponse(
            content=f"<h1>Fehler in der Wochenansicht</h1><pre>{e}</pre>",
            status_code=200
        )


# -------------------- Jahresplanung (MVP) --------------------
@app.get("/year", response_class=HTMLResponse)
def year_view(request: Request, year: int = None):
    require_login(request)
    user = request.session.get("user", {"role": "view", "viewer_standort_id": 1})
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
        "role": user.get("role"),
        "year": year,
        "standorte": standorte,
        "events": events,
        "resource_types": resource_types,
    })

# -------------------- Zelle setzen (MVP) --------------------
@app.post("/api/week/set-cell")
def set_cell(request: Request,
             week_plan_id: int = Form(...),
             day_index: int = Form(...),
             row_index: int = Form(...),
             job_id: int = Form(None)):
    user = request.session.get("user", {"role": "view"})
    if user.get("role") not in ("admin", "write"):
        return RedirectResponse("/week")

    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE week_cells SET job_id=? WHERE week_plan_id=? AND day_index=? AND row_index=?",
              (job_id, week_plan_id, day_index, row_index))
    conn.commit()
    conn.close()
    return RedirectResponse("/week", status_code=303)
