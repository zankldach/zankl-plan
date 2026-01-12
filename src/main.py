
# src/main.py
from fastapi import FastAPI, Request, Body, Form, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import sqlite3
from pathlib import Path
from datetime import date, timedelta
import logging, traceback
from urllib.parse import urlparse, parse_qs

app = FastAPI(title="Zankl-Plan MVP")

BASE_DIR = Path(__file__).resolve().parent  # src/
ROOT_DIR = BASE_DIR.parent                  # project root
DB_PATH  = BASE_DIR / "zankl.db"

templates = Jinja2Templates(directory=str(ROOT_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(ROOT_DIR / "static")), name="static")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("zankl-plan")

# -------------------- DB Init --------------------
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def column_exists(cur, table: str, column: str) -> bool:
    cur.execute(f"PRAGMA table_info({table})")
    return any(r[1] == column for r in cur.fetchall())

def init_db():
    conn = get_conn(); cur = conn.cursor()
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
    cur.execute("""
    CREATE TABLE IF NOT EXISTS global_small_jobs (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      standort TEXT,
      row_index INTEGER,
      text TEXT,
      UNIQUE(standort, row_index)
    )
    """)
    conn.commit(); conn.close()

init_db()

# -------------------- Helpers --------------------
def build_days(year: int, kw: int):
    kw = max(1, min(kw, 53))
    start = date.fromisocalendar(year, kw, 1)  # Montag
    labels = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag"]
    return [{"label": labels[i], "date": (start + timedelta(days=i)).strftime("%d.%m.%Y")} for i in range(5)]

def canon_standort(s: str | None) -> str:
    s = (s or "").strip()
    if not s: return "engelbrechts"
    s_low = " ".join(s.lower().split())
    s_low = s_low.replace("ß", "ss").replace("_", "-")
    aliases = {
        "engelbrechts": "engelbrechts", "eng": "engelbrechts", "e": "engelbrechts",
        "gross gerungs": "gross-gerungs", "gross-gerungs": "gross-gerungs",
        "grossgerungs": "gross-gerungs", "groß gerungs": "gross-gerungs",
        "groß-gerungs": "gross-gerungs", "großgerungs": "gross-gerungs", "gg": "gross-gerungs",
    }
    return aliases.get(s_low, s_low)

def resolve_standort(request: Request, body_standort: str | None, query_standort: str | None) -> str:
    if body_standort and body_standort.strip(): return canon_standort(body_standort)
    if query_standort and query_standort.strip(): return canon_standort(query_standort)
    ref = request.headers.get("referer") or request.headers.get("Referer")
    if ref:
        try:
            qs = parse_qs(urlparse(ref).query)
            ref_st = (qs.get("standort") or [""])[0]
            if ref_st.strip(): return canon_standort(ref_st)
        except Exception: pass
    return "engelbrechts"

# -------------------- Admin (optional) --------------------
@app.get("/admin/normalize-standorte")
def admin_normalize():
    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute("SELECT id, standort FROM employees")
        for r in cur.fetchall():
            st_new = canon_standort(r["standort"])
            if st_new != (r["standort"] or ""):
                cur.execute("UPDATE employees SET standort=? WHERE id=?", (st_new, r["id"]))
        cur.execute("SELECT id, standort FROM week_plans")
        for r in cur.fetchall():
            st_new = canon_standort(r["standort"])
            if st_new != (r["standort"] or ""):
                cur.execute("UPDATE week_plans SET standort=? WHERE id=?", (st_new, r["id"]))
        cur.execute("SELECT id, standort FROM global_small_jobs")
        for r in cur.fetchall():
            st_new = canon_standort(r["standort"])
            if st_new != (r["standort"] or ""):
                cur.execute("UPDATE global_small_jobs SET standort=? WHERE id=?", (st_new, r["id"]))
        conn.commit()
        return {"ok": True}
    except Exception:
        return HTMLResponse(f"<pre>{traceback.format_exc()}</pre>", status_code=500)
    finally:
        conn.close()

@app.get("/admin/debug")
def admin_debug():
    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute("SELECT id,name,standort FROM employees ORDER BY standort,id")
        emps = [dict(id=r["id"], name=r["name"], standort=r["standort"]) for r in cur.fetchall()]
        return {"employees": emps}
    finally:
        conn.close()

# -------------------- Routes --------------------
@app.get("/health")
def health(): return {"status": "ok"}

# ---- Wochenansicht ----
@app.get("/week", response_class=HTMLResponse)
def week(request: Request, kw: int = 1, year: int = 2025, standort: str = "engelbrechts"):
    standort = canon_standort(standort)
    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute("SELECT id,row_count,four_day_week FROM week_plans WHERE year=? AND kw=? AND standort=?", (year, kw, standort))
        plan = cur.fetchone()
        if not plan:
            cur.execute("INSERT INTO week_plans(year,kw,standort,row_count,four_day_week) VALUES(?,?,?,?,1)", (year, kw, standort, 5))
            conn.commit()
            plan_id, rows, four_day_week = cur.lastrowid, 5, 1
        else:
            plan_id = plan["id"]; rows = plan["row_count"]; four_day_week = plan["four_day_week"]

        cur.execute("SELECT id,name FROM employees WHERE standort=? ORDER BY id", (standort,))
        employees = [{"id": e["id"], "name": e["name"]} for e in cur.fetchall()]
        if employees: rows = max(rows, len(employees))

        grid = [[{"text": ""} for _ in range(5)] for _ in range(rows)]
        cur.execute("SELECT row_index,day_index,text FROM week_cells WHERE week_plan_id=?", (plan_id,))
        for r in cur.fetchall():
            if 0 <= r["row_index"] < rows and 0 <= r["day_index"] < 5:
                grid[r["row_index"]][r["day_index"]]["text"] = r["text"] or ""

        cur.execute("SELECT row_index,text FROM global_small_jobs WHERE standort=? ORDER BY row_index", (standort,))
        sj = [{"row_index": s["row_index"], "text": s["text"] or ""} for s in cur.fetchall()]
        max_idx = max([x["row_index"] for x in sj], default=-1)
        while len(sj) < 10:
            max_idx += 1
            sj.append({"row_index": max_idx, "text": ""})

        return templates.TemplateResponse(
            "week.html",
            {"request": request, "grid": grid, "employees": employees, "kw": kw, "year": year,
             "days": build_days(year, kw), "standort": standort, "four_day_week": bool(four_day_week), "small_jobs": sj}
        )
    except Exception:
        return HTMLResponse(f"<pre>{traceback.format_exc()}</pre>", status_code=500)
    finally:
        conn.close()

# ---- Zelle setzen (einzeln) ----
@app.post("/api/week/set-cell")
async def set_cell(request: Request, data: dict = Body(...), standort_q: str | None = Query(None, alias="standort")):
    conn = get_conn(); cur = conn.cursor()
    try:
        year = int(data.get("year")); kw = int(data.get("kw"))
        standort = resolve_standort(request, data.get("standort"), standort_q)
        row = int(data.get("row")); day = int(data.get("day")); val = data.get("value") or ""
        cur.execute("SELECT id,four_day_week FROM week_plans WHERE year=? AND kw=? AND standort=?", (year, kw, standort))
        plan = cur.fetchone()
        if not plan: return {"ok": False, "error": "Plan not found"}
        if plan["four_day_week"] and day == 4: return {"ok": True, "skipped": True}
        cur.execute("""
            INSERT INTO week_cells(week_plan_id,row_index,day_index,text)
            VALUES(?,?,?,?)
            ON CONFLICT(week_plan_id,row_index,day_index) DO UPDATE SET text=excluded.text
        """, (plan["id"], row, day, val))
        conn.commit()
        return {"ok": True, "standort": standort}
    except Exception:
        return JSONResponse({"ok": False, "error": traceback.format_exc()}, status_code=500)
    finally:
        conn.close()

# ---- Batch speichern ----
@app.post("/api/week/batch")
async def save_batch(data: dict = Body(...)):
    conn = get_conn(); cur = conn.cursor()
    try:
        year = int(data.get("year")); kw = int(data.get("kw"))
        standort = canon_standort(data.get("standort") or "engelbrechts")
        updates = data.get("updates") or []
        cur.execute("SELECT id,four_day_week FROM week_plans WHERE year=? AND kw=? AND standort=?", (year, kw, standort))
        plan = cur.fetchone()
        if not plan: return {"ok": False, "error": "Plan not found"}
        for u in updates:
            row = int(u.get("row")); day = int(u.get("day"))
            if plan["four_day_week"] and day == 4: continue
            val = u.get("value") or ""
            cur.execute("""
                INSERT INTO week_cells(week_plan_id,row_index,day_index,text)
                VALUES(?,?,?,?)
                ON CONFLICT(week_plan_id,row_index,day_index) DO UPDATE SET text=excluded.text
            """, (plan["id"], row, day, val))
        conn.commit()
        return {"ok": True, "count": len(updates)}
    except Exception:
        return JSONResponse({"ok": False, "error": traceback.format_exc()}, status_code=500)
    finally:
        conn.close()

# ---- 4-Tage-Woche ----
@app.post("/api/week/set-four-day")
async def set_four_day(data: dict = Body(...)):
    conn = get_conn(); cur = conn.cursor()
    try:
        year = int(data.get("year")); kw = int(data.get("kw"))
        standort = canon_standort(data.get("standort") or "engelbrechts")
        value = 1 if bool(data.get("four_day_week") or data.get("value")) else 0
        cur.execute("SELECT id FROM week_plans WHERE year=? AND kw=? AND standort=?", (year, kw, standort))
        row = cur.fetchone()
        if not row:
            cur.execute("INSERT INTO week_plans(year,kw,standort,row_count,four_day_week) VALUES(?,?,?,?,?)", (year, kw, standort, 5, value))
        else:
            cur.execute("UPDATE week_plans SET four_day_week=? WHERE year=? AND kw=? AND standort=?", (value, year, kw, standort))
        conn.commit()
        return {"ok": True, "four_day_week": bool(value)}
    except Exception:
        return JSONResponse({"ok": False, "error": traceback.format_exc()}, status_code=500)
    finally:
        conn.close()

@app.post("/api/week/options")
async def options_alias(data: dict = Body(...)):
    return await set_four_day(data)

# ---- Kleinbaustellen: einzeln ----
@app.post("/api/klein/set")
async def klein_set(request: Request, data: dict = Body(...)):
    conn = get_conn(); cur = conn.cursor()
    try:
        standort = resolve_standort(request, data.get("standort"), None)
        idx = int(data.get("row_index")); text = (data.get("text") or "").strip()
        cur.execute("""
            INSERT INTO global_small_jobs(standort,row_index,text)
            VALUES(?,?,?)
            ON CONFLICT(standort,row_index) DO UPDATE SET text=excluded.text
        """, (standort, idx, text))
        conn.commit()
        return {"ok": True}
    except Exception:
        return JSONResponse({"ok": False, "error": traceback.format_exc()}, status_code=500)
    finally:
        conn.close()

# ---- Kleinbaustellen: Liste ----
@app.post("/api/klein/save-list")
async def klein_save_list(request: Request, data: dict = Body(...)):
    conn = get_conn(); cur = conn.cursor()
    try:
        standort = resolve_standort(request, data.get("standort"), None)
        items = data.get("items") or []
        if items and isinstance(items[0], dict):
            items = sorted(items, key=lambda x: int(x.get("row_index", 0)))
            normalized = [(int(x.get("row_index", i)), (x.get("text") or "").strip()) for i, x in enumerate(items)]
        else:
            normalized = [(i, (str(x) if x is not None else "").strip()) for i, x in enumerate(items)]
        cur.execute("DELETE FROM global_small_jobs WHERE standort=?", (standort,))
        for idx, text in normalized:
            cur.execute("INSERT INTO global_small_jobs(standort,row_index,text) VALUES(?,?,?)", (standort, idx, text))
        conn.commit()
        return {"ok": True, "count": len(normalized)}
    except Exception:
        return JSONResponse({"ok": False, "error": traceback.format_exc()}, status_code=500)
    finally:
        conn.close()

# ---- Einstellungen: Mitarbeiter ----
@app.get("/settings/employees", response_class=HTMLResponse)
def settings_employees_page(request: Request, standort: str = "engelbrechts"):
    standort = canon_standort(standort)
    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute("SELECT id,name FROM employees WHERE standort=? ORDER BY id", (standort,))
        employees = [{"id": r["id"], "name": r["name"]} for r in cur.fetchall()]
        return templates.TemplateResponse("settings_employees.html", {"request": request, "standort": standort, "employees": employees})
    except Exception:
        return HTMLResponse(f"<pre>{traceback.format_exc()}</pre>", status_code=500)
    finally:
        conn.close()



@app.post("/settings/employees", response_class=HTMLResponse)
async def settings_employees_save(request: Request):
    form = await request.form()

    # Standort robust
    st = form.get("standort") or request.query_params.get("standort") or None
    st = resolve_standort(request, st, request.query_params.get("standort"))

    conn = get_conn(); cur = conn.cursor()
    try:
        # Inserts: emp_name_new[] (mehrere)
        new_list = []
        for key, val in form.multi_items():
            if key == "emp_name_new[]":
                t = (val or "").strip()
                if t:
                    new_list.append(t)

        for n in new_list:
            cur.execute("INSERT INTO employees(name, standort) VALUES(?, ?)", (n, st))

        conn.commit()

        # Reload
        cur.execute("SELECT id,name FROM employees WHERE standort=? ORDER BY id", (st,))
        employees = [{"id": r["id"], "name": r["name"]} for r in cur.fetchall()]
        return templates.TemplateResponse("settings_employees.html",
            {"request": request, "standort": st, "employees": employees, "saved": True})
    except Exception:
        return HTMLResponse(f"<pre>{traceback.format_exc()}</pre>", status_code=500)
    finally:
        conn.close()



# ---- Jahresseite ----
@app.get("/year", response_class=HTMLResponse)
def year_page(request: Request, year: int = 2025):
    try:
        return templates.TemplateResponse("year.html", {"request": request, "year": year})
    except Exception:
        return HTMLResponse(f"<h1>Jahresplanung</h1><p>year={year}</p>", status_code=200)
