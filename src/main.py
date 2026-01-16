# src/main.py
from fastapi import FastAPI, Request, Body, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from datetime import date, timedelta
import sqlite3
import traceback
import logging

# =========================
# App / Paths
# =========================
app = FastAPI(title="Zankl-Plan")

BASE_DIR = Path(__file__).resolve().parent      # src/
ROOT_DIR = BASE_DIR.parent                      # project root
DB_PATH = BASE_DIR / "zankl.db"

templates = Jinja2Templates(directory=str(ROOT_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(ROOT_DIR / "static")), name="static")

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("zankl")

STANDORTE = ["engelbrechts", "gross-gerungs"]

# =========================
# DB
# =========================
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# =========================
# Helpers
# =========================
def canon_standort(s: str | None) -> str:
    if not s:
        return "engelbrechts"
    s = s.lower().strip()
    s = s.replace("ß", "ss").replace("_", "-")
    aliases = {
        "engelbrechts": "engelbrechts",
        "eng": "engelbrechts",
        "gross-gerungs": "gross-gerungs",
        "gross gerungs": "gross-gerungs",
        "groß gerungs": "gross-gerungs",
        "gg": "gross-gerungs",
    }
    return aliases.get(s, s)

def get_year_kw(year: int | None, kw: int | None) -> tuple[int, int]:
    today = date.today()
    return year or today.year, kw or today.isocalendar().week

def build_days(year: int, kw: int):
    start = date.fromisocalendar(year, kw, 1)
    labels = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag"]
    return [
        {"label": labels[i], "date": (start + timedelta(days=i)).strftime("%d.%m.%Y")}
        for i in range(5)
    ]

# =========================
# Health
# =========================
@app.get("/health")
def health():
    return {"status": "ok"}

# =========================
# WEEK – EDITIERBAR
# =========================
@app.get("/week", response_class=HTMLResponse)
def week(
    request: Request,
    year: int | None = None,
    kw: int | None = None,
    standort: str = "engelbrechts",
):
    try:
        standort = canon_standort(standort)
        year, kw = get_year_kw(year, kw)

        conn = get_conn()
        cur = conn.cursor()

        # Week Plan
        cur.execute(
            "SELECT id,row_count,four_day_week FROM week_plans WHERE year=? AND kw=? AND standort=?",
            (year, kw, standort),
        )
        plan = cur.fetchone()

        if not plan:
            cur.execute(
                "INSERT INTO week_plans(year,kw,standort,row_count,four_day_week) VALUES(?,?,?,?,1)",
                (year, kw, standort, 5),
            )
            conn.commit()
            plan_id = cur.lastrowid
            rows = 5
            four_day_week = True
        else:
            plan_id = plan["id"]
            rows = plan["row_count"]
            four_day_week = bool(plan["four_day_week"])

        # Employees
        cur.execute(
            "SELECT id,name FROM employees WHERE standort=? ORDER BY id",
            (standort,),
        )
        employees = [{"id": r["id"], "name": r["name"]} for r in cur.fetchall()]
        rows = max(rows, len(employees))

        # Grid
        grid = [[{"text": ""} for _ in range(5)] for _ in range(rows)]
        cur.execute(
            "SELECT row_index,day_index,text FROM week_cells WHERE week_plan_id=?",
            (plan_id,),
        )
        for r in cur.fetchall():
            if r["row_index"] < rows and r["day_index"] < 5:
                grid[r["row_index"]][r["day_index"]]["text"] = r["text"] or ""

        return templates.TemplateResponse(
            "week.html",
            {
                "request": request,
                "year": year,
                "kw": kw,
                "standort": standort,
                "days": build_days(year, kw),
                "grid": grid,
                "employees": employees,
                "four_day_week": four_day_week,
                "standorte": STANDORTE,
            },
        )
    except Exception:
        return HTMLResponse(f"<pre>{traceback.format_exc()}</pre>", status_code=500)
    finally:
        try:
            conn.close()
        except Exception:
            pass

# =========================
# WEEK – VIEW ONLY
# =========================
@app.get("/view/week", response_class=HTMLResponse)
def view_week(
    request: Request,
    year: int | None = None,
    kw: int | None = None,
    standort: str = "engelbrechts",
):
    try:
        standort = canon_standort(standort)
        year, kw = get_year_kw(year, kw)

        conn = get_conn()
        cur = conn.cursor()

        cur.execute(
            "SELECT id,row_count,four_day_week FROM week_plans WHERE year=? AND kw=? AND standort=?",
            (year, kw, standort),
        )
        plan = cur.fetchone()

        if not plan:
            return HTMLResponse("Kein Wochenplan vorhanden", status_code=404)

        plan_id = plan["id"]
        rows = plan["row_count"]
        four_day_week = bool(plan["four_day_week"])

        cur.execute(
            "SELECT id,name FROM employees WHERE standort=? ORDER BY id",
            (standort,),
        )
        employees = [{"id": r["id"], "name": r["name"]} for r in cur.fetchall()]
        rows = max(rows, len(employees))

        grid = [[{"text": ""} for _ in range(5)] for _ in range(rows)]
        cur.execute(
            "SELECT row_index,day_index,text FROM week_cells WHERE week_plan_id=?",
            (plan_id,),
        )
        for r in cur.fetchall():
            if r["row_index"] < rows and r["day_index"] < 5:
                grid[r["row_index"]][r["day_index"]]["text"] = r["text"] or ""

        return templates.TemplateResponse(
            "week_view.html",
            {
                "request": request,
                "year": year,
                "kw": kw,
                "standort": standort,
                "days": build_days(year, kw),
                "grid": grid,
                "employees": employees,
                "four_day_week": four_day_week,
            },
        )
    except Exception:
        return HTMLResponse(f"<pre>{traceback.format_exc()}</pre>", status_code=500)
    finally:
        try:
            conn.close()
        except Exception:
            pass

# =========================
# SETTINGS – EMPLOYEES
# =========================
@app.get("/settings/employees", response_class=HTMLResponse)
def settings_employees(request: Request, standort: str = "engelbrechts"):
    try:
        standort = canon_standort(standort)
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT id,name FROM employees WHERE standort=? ORDER BY id",
            (standort,),
        )
        employees = [{"id": r["id"], "name": r["name"]} for r in cur.fetchall()]

        return templates.TemplateResponse(
            "settings_employees.html",
            {
                "request": request,
                "standort": standort,
                "employees": employees,
            },
        )
    except Exception:
        return HTMLResponse(f"<pre>{traceback.format_exc()}</pre>", status_code=500)
    finally:
        try:
            conn.close()
        except Exception:
            pass

@app.post("/settings/employees", response_class=HTMLResponse)
async def settings_employees_save(request: Request):
    try:
        form = await request.form()
        standort = canon_standort(form.get("standort"))

        names = []
        for k, v in form.multi_items():
            if k == "emp_name_new[]" and v.strip():
                names.append(v.strip())

        conn = get_conn()
        cur = conn.cursor()
        for n in names:
            cur.execute(
                "INSERT INTO employees(name,standort) VALUES(?,?)",
                (n, standort),
            )
        conn.commit()

        cur.execute(
            "SELECT id,name FROM employees WHERE standort=? ORDER BY id",
            (standort,),
        )
        employees = [{"id": r["id"], "name": r["name"]} for r in cur.fetchall()]

        return templates.TemplateResponse(
            "settings_employees.html",
            {
                "request": request,
                "standort": standort,
                "employees": employees,
                "saved": True,
            },
        )
    except Exception:
        return HTMLResponse(f"<pre>{traceback.format_exc()}</pre>", status_code=500)
    finally:
        try:
            conn.close()
        except Exception:
            pass
