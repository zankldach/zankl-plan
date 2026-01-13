
# src/main.py
from fastapi import FastAPI, Request, Body, Form, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import sqlite3
from pathlib import Path
from datetime import date, timedelta
import logging, traceback, os
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

# -------------------- Admin / Debug --------------------
@app.get("/admin/db-info")
def db_info():
    exists = DB_PATH.exists()
    size = DB_PATH.stat().st_size if exists else 0
    info = {
        "db_path": str(DB_PATH),
        "exists": exists,
        "size_bytes": size,
        "cwd": os.getcwd(),
        "db_dir_writable": os.access(DB_PATH.parent, os.W_OK),
        "db_file_writable": (os.access(DB_PATH, os.W_OK) if exists else None),
    }
    return info

@app.get("/admin/debug")
def admin_debug():
    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute("SELECT id,name,standort FROM employees ORDER BY standort,id")
        emps = [dict(id=r["id"], name=r["name"], standort=r["standort"]) for r in cur.fetchall()]
        return {"employees": emps}
    finally:
        conn.close()

@app.get("/admin/employees-all", response_class=HTMLResponse)
def employees_all():
    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute("SELECT id,name,standort FROM employees ORDER BY standort,id")
        rows = cur.fetchall()
        html = ["<h1>Employees · ALL</h1>", "<table border='1' cellpadding='6'><tr><th>ID</th><th>Name</th><th>Standort</th></tr>"]
        for r in rows:
            html.append(f"<tr><td>{r['id']}</td><td>{(r['name'] or '')}</td><td>{(r['standort'] or '')}</td></tr>")
        html.append("</table>")
        if not rows: html.append("<p><em>Keine Einträge</em></p>")
        return HTMLResponse("".join(html))
    finally:
        conn.close()

# -------------------- Routes --------------------
@app.get("/health")
def health(): return {"status": "ok"}

# ---- Plain-Testseite (Frontend ausschließen) ----
@app.get("/settings/employees_plain", response_class=HTMLResponse)
def employees_plain():
    return HTMLResponse("""
<!DOCTYPE html>
<html lang="de"><head><meta charset="utf-8"><title>Plain · Mitarbeiter</title></head>
<body>
  <h1>Plain · Mitarbeiter</h1>
  <settings/employees
    <input type="hidden" name="standort" value="gross-gerungs">
    <p><label>Neuer Mitarbeiter 1: <input type="text" name="emp_name_new[]" /></label></p>
    <p><label>Neuer Mitarbeiter 2: <input type="text" name="emp_name_new[]" /></label></p>
    <button type="submit">Speichern</button>
  </form>
  <p>/admin/employees-allListe prüfen</a></p>
</body>
</html>
""".strip())

# ---- Wochenansicht, API, Kleinbaustellen ----
# (DEINE bisher funktionierenden Routen bleiben unverändert – ausgelassen zur Kürze)
#  ...  HIER BLEIBT DEIN RESTLICHER CODE UNVERÄNDERT  ...

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
    logger.info("FORM RAW: %s", dict(form))  # <-- zeigt uns standort / emp_name_new[] etc.

    # Standort robust
    st = form.get("standort") or request.query_params.get("standort") or None
    st = resolve_standort(request, st, request.query_params.get("standort"))

    # Neue: emp_name_new[]
    new_list = []
    for key, val in form.multi_items():
        if key == "emp_name_new[]":
            t = (val or "").strip()
            if t: new_list.append(t)

    conn = get_conn(); cur = conn.cursor()
    try:
        for n in new_list:
            cur.execute("INSERT INTO employees(name, standort) VALUES(?, ?)", (n, st))
        conn.commit()

        cur.execute("SELECT id,name FROM employees WHERE standort=? ORDER BY id", (st,))
        employees = [{"id": r["id"], "name": r["name"]} for r in cur.fetchall()]
        return templates.TemplateResponse("settings_employees.html", {"request": request, "standort": st, "employees": employees, "saved": True})
    except Exception:
        return HTMLResponse(f"<pre>{traceback.format_exc()}</pre>", status_code=500)
    finally:
        conn.close()
