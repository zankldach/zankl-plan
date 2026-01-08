
# src/main.py
from fastapi import FastAPI, Request, Body, Form, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import sqlite3
from pathlib import Path
from datetime import date, timedelta
import logging
import traceback
from urllib.parse import urlparse, parse_qs

app = FastAPI(title="Zankl-Plan MVP")

BASE_DIR = Path(__file__).resolve().parent          # src/
ROOT_DIR = BASE_DIR.parent                           # Projektwurzel
DB_PATH = BASE_DIR / "zankl.db"

# Templates/Static laden
templates = Jinja2Templates(directory=str(ROOT_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(ROOT_DIR / "static")), name="static")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("zankl-plan")

# -------------------------------------------------------------------
# DB Init
# -------------------------------------------------------------------
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def column_exists(cur, table: str, column: str) -> bool:
    cur.execute(f"PRAGMA table_info({table})")
    return any(r[1] == column for r in cur.fetchall())

def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS week_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            year INTEGER,
            kw INTEGER,
            standort TEXT,
            row_count INTEGER DEFAULT 5,
            four_day_week INTEGER DEFAULT 1,
            UNIQUE(year, kw, standort)
        )
    """)
    if not column_exists(cur, "week_plans", "four_day_week"):
        cur.execute("ALTER TABLE week_plans ADD COLUMN four_day_week INTEGER DEFAULT 1")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS week_cells (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            week_plan_id INTEGER,
            row_index INTEGER,
            day_index INTEGER,
            text TEXT,
            UNIQUE(week_plan_id, row_index, day_index)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            standort TEXT
        )
    """)

    # Globale Kleinbaustellen je Standort
    cur.execute("""
        CREATE TABLE IF NOT EXISTS global_small_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            standort TEXT,
            row_index INTEGER,
            text TEXT,
            UNIQUE(standort, row_index)
        )
    """)
    conn.commit()
    conn.close()

init_db()

# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------
def build_days(year: int, kw: int):
    """Gibt Liste mit 5 Einträgen {label, date} für Mo–Fr zurück."""
    kw = max(1, min(kw, 53))
    start = date.fromisocalendar(year, kw, 1)  # ISO: Montag=1
    labels = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag"]
    return [{"label": labels[i], "date": (start + timedelta(days=i)).strftime("%d.%m.%Y")} for i in range(5)]

def is_friday(day_index: int) -> bool:
    return day_index == 4

def resolve_standort(request: Request, body_standort: str | None, query_standort: str | None) -> str:
    """
    Standort robust ermitteln:
    1) Body (JSON/Form)
    2) Query-Param des aktuellen Calls
    3) Referer-URL (z.B. /week?standort=gross-gerungs)
    4) Fallback: 'engelbrechts'
    """
    if body_standort and body_standort.strip():
        return body_standort.strip()
    if query_standort and query_standort.strip():
        return query_standort.strip()

    ref = request.headers.get("referer") or request.headers.get("Referer")
    if ref:
        try:
            qs = parse_qs(urlparse(ref).query)
            ref_st = (qs.get("standort") or [""])[0].strip()
            if ref_st:
                return ref_st
        except Exception:
            pass

    return "engelbrechts"

# -------------------------------------------------------------------
# Routes
# -------------------------------------------------------------------
@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/week", response_class=HTMLResponse)
def week(request: Request, kw: int = 1, year: int = 2025, standort: str = "engelbrechts"):
    conn = get_conn()
    cur = conn.cursor()
    try:
        # Plan holen/erstellen
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
            four_day_week = 1
        else:
            plan_id = plan["id"]
            rows = plan["row_count"]
            four_day_week = plan["four_day_week"]

        # Mitarbeiter für Standort
        cur.execute("SELECT id,name FROM employees WHERE standort=? ORDER BY id", (standort,))
        employees = [{"id": e["id"], "name": e["name"]} for e in cur.fetchall()]
        rows = max(rows, len(employees)) if employees else rows

        # Grid initialisieren + Zellen laden
        grid = [[{"text": ""} for _ in range(5)] for _ in range(rows)]
        cur.execute("SELECT row_index,day_index,text FROM week_cells WHERE week_plan_id=?", (plan_id,))
        for r in cur.fetchall():
            if 0 <= r["row_index"] < rows and 0 <= r["day_index"] < 5:
                grid[r["row_index"]][r["day_index"]]["text"] = r["text"]

        # Standortabhängige Kleinbaustellen
        cur.execute(
            "SELECT row_index,text FROM global_small_jobs WHERE standort=? ORDER BY row_index",
            (standort,),
        )
        sj = [{"row_index": s["row_index"], "text": s["text"] or ""} for s in cur.fetchall()]
        max_idx = max([x["row_index"] for x in sj], default=-1)
        while len(sj) < 10:
            max_idx += 1
            sj.append({"row_index": max_idx, "text": ""})

        return templates.TemplateResponse(
            "week.html",
            {
                "request": request,
                "grid": grid,
                "employees": employees,
                "kw": kw,
                "year": year,
                "days": build_days(year, kw),
                "standort": standort,
                "four_day_week": bool(four_day_week),
                "small_jobs": sj,
            },
        )
    except Exception:
        return HTMLResponse(f"<pre>{traceback.format_exc()}</pre>", status_code=500)
    finally:
        conn.close()

# --- API: Kleinbaustellen setzen (mit Standort-Fallback) -----------------------
@app.post("/api/klein/set")
async def klein_set(
    request: Request,
    data: dict = Body(...),
    standort_q: str | None = Query(None, alias="standort"),
):
    conn = get_conn()
    cur = conn.cursor()
    try:
        standort = resolve_standort(request, data.get("standort"), standort_q)
        row_index = int(data.get("row_index"))
        text = data.get("text") or ""
        cur.execute(
            """
            INSERT INTO global_small_jobs(standort,row_index,text)
            VALUES(?,?,?)
            ON CONFLICT(standort,row_index) DO UPDATE SET text=excluded.text
            """,
            (standort, row_index, text),
        )
        conn.commit()
        return {"ok": True, "standort": standort, "row_index": row_index}
    except Exception:
        return JSONResponse({"ok": False, "error": traceback.format_exc()}, status_code=500)
    finally:
        conn.close()

# --- API: Zelle im Wochenplan setzen (mit Standort-Fallback) -------------------
@app.post("/api/week/set-cell")

@app.post("/api/week/set-four-day")
async def set_four_day(data: dict = Body(...)):
    """
    Setzt four_day_week (0/1) für den aktuellen Plan (year, kw, standort).
    """
    conn = get_conn()
    cur = conn.cursor()
    try:
        year = int(data.get("year"))
        kw = int(data.get("kw"))
        standort = data.get("standort") or "engelbrechts"
        value = 1 if bool(data.get("value")) else 0

        # Sicherstellen, dass der Plan existiert
        cur.execute(
            "SELECT id FROM week_plans WHERE year=? AND kw=? AND standort=?",
            (year, kw, standort),
        )
        row = cur.fetchone()
        if not row:
            # Falls kein Plan → anlegen (wie in week()) und dann setzen
            cur.execute(
                "INSERT INTO week_plans(year,kw,standort,row_count,four_day_week) VALUES(?,?,?,?,?)",
                (year, kw, standort, 5, value),
            )
            conn.commit()
        else:
            cur.execute(
                "UPDATE week_plans SET four_day_week=? WHERE year=? AND kw=? AND standort=?",
                (value, year, kw, standort),
            )
            conn.commit()

        return {"ok": True, "four_day_week": bool(value)}
    except Exception:
        return JSONResponse({"ok": False, "error": traceback.format_exc()}, status_code=500)
    finally:
        conn.close()
``

async def set_cell(
    request: Request,
    data: dict = Body(...),
    standort_q: str | None = Query(None, alias="standort"),
):
    conn = get_conn()
    cur = conn.cursor()
    try:
        year = int(data.get("year"))
        kw = int(data.get("kw"))
        standort = resolve_standort(request, data.get("standort"), standort_q)
        row = int(data.get("row"))
        day = int(data.get("day"))
        val = data.get("value") or ""

        cur.execute(
            "SELECT id,four_day_week FROM week_plans WHERE year=? AND kw=? AND standort=?",
            (year, kw, standort),
        )
        plan = cur.fetchone()
        if not plan:
            return {"ok": False, "error": "Plan not found"}
        if plan["four_day_week"] and is_friday(day):
            # Bei 4-Tage-Woche Freitag überspringen (kein Fehler)
            return {"ok": True, "skipped": True}

        cur.execute(
            """
            INSERT INTO week_cells(week_plan_id,row_index,day_index,text)
            VALUES(?,?,?,?)
            ON CONFLICT(week_plan_id,row_index,day_index) DO UPDATE SET text=excluded.text
            """,
            (plan["id"], row, day, val),
        )
        conn.commit()
        return {"ok": True, "standort": standort}
    except Exception:
        return JSONResponse({"ok": False, "error": traceback.format_exc()}, status_code=500)
    finally:
        conn.close()

# --- Einstellungen: Mitarbeiter (GET zeigt, POST speichert) --------------------
@app.get("/settings/employees", response_class=HTMLResponse)
def settings_employees_page(request: Request, standort: str = "engelbrechts"):
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT id,name FROM employees WHERE standort=? ORDER BY id", (standort,))
        employees = [{"id": r["id"], "name": r["name"]} for r in cur.fetchall()]
        return templates.TemplateResponse(
            "settings_employees.html",
            {"request": request, "standort": standort, "employees": employees},
        )
    except Exception:
        return HTMLResponse(f"<pre>{traceback.format_exc()}</pre>", status_code=500)
    finally:
        conn.close()

@app.post("/settings/employees", response_class=HTMLResponse)
async def settings_employees_save(
    request: Request,
    standort: str = Form(...),
    ids: str = Form(""),
    names: str = Form(""),
    new_names: str = Form(""),
    delete_ids: str = Form(""),
):
    conn = get_conn()
    cur = conn.cursor()
    try:
        # Delete
        if delete_ids.strip():
            for sid in [x for x in delete_ids.split(",") if x.strip()]:
                try:
                    cur.execute("DELETE FROM employees WHERE id=? AND standort=?", (int(sid.strip()), standort))
                except Exception:
                    pass

        # Update bestehende
        ids_list = [x.strip() for x in ids.split(",")] if ids else []
        names_list = [x.strip() for x in names.split(",")] if names else []
        for i, n in zip(ids_list, names_list):
            if i and n:
                cur.execute("UPDATE employees SET name=? WHERE id=? AND standort=?", (n, int(i), standort))

        # Insert neue
        if new_names.strip():
            for n in [x.strip() for x in new_names.split(",") if x.strip()]:
                cur.execute("INSERT OR IGNORE INTO employees(name, standort) VALUES(?, ?)", (n, standort))

        conn.commit()

        # zurück zur Seite
        cur.execute("SELECT id,name FROM employees WHERE standort=? ORDER BY id", (standort,))
        employees = [{"id": r["id"], "name": r["name"]} for r in cur.fetchall()]
        return templates.TemplateResponse(
            "settings_employees.html",
            {"request": request, "standort": standort, "employees": employees, "saved": True},
        )
    except Exception:
        return HTMLResponse(f"<pre>{traceback.format_exc()}</pre>", status_code=500)
    finally:
        conn.close()

# --- Jahresseite minimal --------------------------------------------------------
@app.get("/year", response_class=HTMLResponse)
def year_page(request: Request, year: int = 2025):
    try:
        return templates.TemplateResponse("year.html", {"request": request, "year": year})
    except Exception:
        return HTMLResponse(f"<h1>Jahresplanung</h1><p>year={year}</p>", status_code=200)
