
# src/main.py
from fastapi import FastAPI, Request, Body, Query, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import sqlite3
from pathlib import Path
from datetime import date, timedelta, datetime
import logging, traceback
from urllib.parse import urlparse, parse_qs

app = FastAPI(title="Zankl-Plan MVP")
BASE_DIR = Path(__file__).resolve().parent  # src/
ROOT_DIR = BASE_DIR.parent                  # project root
DB_PATH = BASE_DIR / "zankl.db"

templates = Jinja2Templates(directory=str(ROOT_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(ROOT_DIR / "static")), name="static")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("zankl-plan")

STANDORTE = ["engelbrechts", "gross-gerungs"]  # Kanonisierte Werte

# -----------------------------------------------------------------------------
# TEMPLATES SCHREIBEN (Admin) - unverändert
# -----------------------------------------------------------------------------
BASE_HTML_SAFE = """<!DOCTYPE html>
<html lang="de">
<head>
 <meta charset="UTF-8">
 <title>{% block title %}Zankl Plan{% endblock %}</title>
 <meta name="viewport" content="width=device-width, initial-scale=1">
 <!-- Ein einziges, verlässliches Stylesheet -->
 /static/style.v2.css
 <!-- KEIN globales app.js laden, damit nichts mit week.html kollidiert -->
 <!-- /static/app.js</script> -->
 <style>
 :root { --blue: #003a8f; --bg: #f4f6f8; }
 html, body { height: 100%; }
 body { font-family: Arial, sans-serif; margin: 0; background: var(--bg); color: #0f172a; }
 header.site { background: var(--blue); color: #fff; padding: 10px 20px;
 display: flex; justify-content: space-between; align-items: center; }
 nav.site { background: var(--blue); padding: 6px 20px; display: flex; gap: 16px; align-items: center;
 position: sticky; top: 0; z-index: 1000; }
 nav.site a { color: white; text-decoration: none; font-weight: 600; padding: 6px 10px; border-radius: 6px; }
 nav.site a:hover { background: rgba(255,255,255,0.14); }
 nav.site a.is-active { background: rgba(255,255,255,0.22); }
 #settingsGear { cursor: pointer; font-size: 20px; }
 main { padding: 20px; }
 /* Tabellen Defaults */
 table { width: 100%; border-collapse: collapse; background: #fff; }
 th, td { border: 1px solid #ddd; padding: 6px; text-align: center; }
 th { background: #eef2f6; }
 td input, td textarea {
 width: 100%; height: 100%; padding: 6px; box-sizing: border-box; border: none;
 background: transparent; text-align: center; font-size: 14px;
 }
 </style>
 {% block head %}{% endblock %}
</head>
<body>
 <!-- 4-Tage-Woche Flag (robust auch auf Seiten ohne 'four_day_week') -->
 <script>
 try { window.__fourDay = {{ 'true' if (four_day_week
 default(false)) else 'false' }}; }
 catch (e) { window.__fourDay = false; }
 </script>
 <header class="site">
 <strong>Zankl Plan</strong>
 <div id="settingsGear" title="Einstellungen">⚙️</div>
 </header>
 <!-- DIREKTE Navbar (kein Include, keine externe Datei nötig) -->
 <nav class="site" role="navigation" aria-label="Hauptnavigation">
 <week?standort=engelbrechtsEngelbrechts</a>
 /week?standort=gross-gerungsGroß Gerungs</a>
 /settings/employeesEinstellungen</a>
 <yearJahr</a>
 /healthHealth</a>
 </nav>
 <main>
 {% block content %}{% endblock %}
 </main>
 <script>
 // Zahnrad → Einstellungen
 const gear = document.getElementById('settingsGear');
 if (gear) gear.addEventListener('click', () => { window.location.href = '/settings/employees'; });
 // Aktiven Menüpunkt markieren
 const currentPath = window.location.pathname;
 document.querySelectorAll('nav.site a').forEach(a => {
 const aPath = new URL(a.href, window.location.origin).pathname;
 if (currentPath === aPath || currentPath.startsWith(aPath)) a.classList.add('is-active');
 });
 </script>
 {% block scripts %}{% endblock %}
</body>
</html>
"""

SETTINGS_EMPLOYEES_HTML = """{% extends "base.html" %}
{% block title %}Einstellungen · Mitarbeiter{% endblock %}
{% block content %}
<h1>Einstellungen · Mitarbeiter</h1>
/settings/employees
 <label>Standort:
 <select name="standort" onchange="document.getElementById('standortForm').submit()">
 <option value="engelbrechts" {{ 'selected' if standort=='engelbrechts' else '' }}>Engelbrechts</option>
 <option value="gross-gerungs" {{ 'selected' if standort=='gross-gerungs' else '' }}>Groß Gerungs</option>
 </select>
 </label>
</form>
{% if saved %}
 <div style="padding:8px; background:#e8ffe8; border:1px solid #9bd49b; margin-bottom:10px;">
 Gespeichert.
 </div>
{% endif %}
<table class="table" style="margin-bottom:10px; width:100%; border-collapse:collapse;">
 <thead>
 <tr>
 <th style="width:80px; text-align:left;">ID</th>
 <th style="text-align:left;">Name</th>
 </tr>
 </thead>
 <tbody id="empTableBody">
 {% for e in employees or [] %}
 <tr>
 <td style="text-align:left;">{{ e.id }}</td>
 <td style="text-align:left;">
 <input type="text" value="{{ e.name }}" disabled style="width:100%; background:#f8fafc; color:#111;">
 </td>
 </tr>
 {% endfor %}
 {% if (not employees) or (employees|length==0) %}
 <tr>
 <td colspan="2" style="text-align:left; color:#64748b;">Noch keine Mitarbeiter für diesen Standort erfasst.</td>
 </tr>
 {% endif %}
 </tbody>
</table>
/settings/employees
 <input type="hidden" name="standort" value="{{ standort }}"/>
 <fieldset style="border:1px solid #e5e7eb; padding:10px; border-radius:6px;">
 <legend style="padding:0 6px; color:#334155; font-weight:600;">Neue Mitarbeiter</legend>
 <p style="margin:0 0 8px 0; color:#64748b;">
 Trage die Namen ein. Leere Felder werden ignoriert. Es gibt <strong>immer eine leere Zeile am Ende</strong>.
 </p>
 <div id="newInputs" style="display:flex; flex-direction:column; gap:8px;"></div>
 <div style="margin-top:8px; display:flex; gap:8px;">
 <button type="button" id="addBtn">Weiteres Feld</button>
 <button type="submit" id="saveBtn">Speichern</button>
 </div>
 </fieldset>
</form>
{% endblock %}
{% block scripts %}
<script>
document.addEventListener('DOMContentLoaded', ()=>{
 const wrap = document.getElementById('newInputs');
 const addBtn = document.getElementById('addBtn');
 function makeRow(value=""){
   const row = document.createElement('div');
   row.className = 'new-row';
   row.style.display = 'grid';
   row.style.gridTemplateColumns = '180px 1fr';
   row.style.gap = '8px';
   row.style.alignItems = 'center';
   row.innerHTML = `
   <label>Neuer Mitarbeiter:</label>
   <div style="display:flex; gap:6px; align-items:center;">
     <input type="text" name="emp_name_new[]" placeholder="Name eingeben"
       style="flex:1; padding:6px 8px; border:1px solid #d9dee5; border-radius:6px;">
     <button type="button" class="btn-remove" title="Zeile entfernen" style="padding:6px 10px;">✕</button>
   </div>`;
   const inp = row.querySelector('input[name="emp_name_new[]"]');
   const rmv = row.querySelector('.btn-remove');
   if (value) inp.value = value;
   rmv.addEventListener('click', ()=>{
     const rows = wrap.querySelectorAll('.new-row');
     if (rows.length > 1) { row.remove(); ensureTrailingEmpty(); } else { inp.value = ''; }
   });
   inp.addEventListener('input', ensureTrailingEmpty);
   return row;
 }
 function ensureTrailingEmpty(){
   const inputs = Array.from(wrap.querySelectorAll('input[name="emp_name_new[]"]'));
   const needEmpty = !(inputs.length > 0 && inputs[inputs.length-1].value.trim() === '');
   if (needEmpty) wrap.appendChild(makeRow(""));
 }
 ensureTrailingEmpty();
 if (addBtn) {
   addBtn.addEventListener('click', ()=>{
     wrap.appendChild(makeRow(""));
     const all = wrap.querySelectorAll('input[name="emp_name_new[]"]');
     all[all.length-1]?.focus();
   });
 }
});
</script>
{% endblock %}
"""

@app.post("/admin/write-base")
def admin_write_base():
    try:
        tpl_dir = ROOT_DIR / "templates"
        tpl_dir.mkdir(parents=True, exist_ok=True)
        (tpl_dir / "base.html").write_text(BASE_HTML_SAFE, encoding="utf-8")
        return {"ok": True, "wrote": ["base.html"]}
    except Exception as e:
        return Response(str(e), status_code=500, media_type="text/plain")

@app.get("/admin/write-base")
def admin_write_base_get():
    return admin_write_base()

@app.post("/admin/write-settings")
def admin_write_settings():
    try:
        tpl_dir = ROOT_DIR / "templates"
        tpl_dir.mkdir(parents=True, exist_ok=True)
        (tpl_dir / "settings_employees.html").write_text(SETTINGS_EMPLOYEES_HTML, encoding="utf-8")
        return {"ok": True, "wrote": ["settings_employees.html"]}
    except Exception as e:
        return Response(str(e), status_code=500, media_type="text/plain")

@app.get("/admin/write-settings")
def admin_write_settings_get():
    return admin_write_settings()

def _tpl_dir():
    return ROOT_DIR / "templates"

def _tpl_path(name: str):
    return _tpl_dir() / name

@app.get("/admin/verify-templates")
def admin_verify_templates():
    out = {"root": str(ROOT_DIR), "templates_dir": str(_tpl_dir()), "files": []}
    for name in ["base.html", "settings_employees.html", "week_view.html", "week.html"]:
        p = _tpl_path(name)
        info = {
            "name": name,
            "exists": p.exists(),
            "size": p.stat().st_size if p.exists() else 0,
            "mtime": datetime.fromtimestamp(p.stat().st_mtime).isoformat() if p.exists() else None,
            "first_lines": []
        }
        if p.exists():
            try:
                txt = p.read_text(encoding="utf-8")
                info["first_lines"] = txt.splitlines()[:20]
            except Exception as e:
                info["first_lines"] = [f"ERROR reading {name}: {e}"]
        out["files"].append(info)
    return out

@app.get("/admin/show-file")
def admin_show_file(name: str):
    p = _tpl_path(name)
    if not p.exists():
        return Response(f"{p} not found", status_code=404, media_type="text/plain")
    return Response(p.read_text(encoding="utf-8"), media_type="text/plain")

# -----------------------------------------------------------------------------
# DB INIT (unverändert)
# -----------------------------------------------------------------------------
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
    )""")
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
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS employees (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        standort TEXT
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS global_small_jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        standort TEXT,
        row_index INTEGER,
        text TEXT,
        UNIQUE(standort, row_index)
    )""")
    conn.commit(); conn.close()

init_db()

# -----------------------------------------------------------------------------
# HILFSFUNKTIONEN (Kanons, Tage)
# -----------------------------------------------------------------------------
def build_days(year: int, kw: int):
    kw = max(1, min(kw, 53))
    start = date.fromisocalendar(year, kw, 1)  # Montag
    labels = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag"]
    return [{"label": labels[i], "date": (start + timedelta(days=i)).strftime("%d.%m.%Y")} for i in range(5)]

def canon_standort(s: str | None) -> str:
    s = (s or "").strip()
    if not s:
        return "engelbrechts"
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
    if body_standort and body_standort.strip():
        return canon_standort(body_standort)
    if query_standort and query_standort.strip():
        return canon_standort(query_standort)
    ref = request.headers.get("referer") or request.headers.get("Referer")
    if ref:
        try:
            qs = parse_qs(urlparse(ref).query)
            ref_st = (qs.get("standort") or [""])[0]
            if ref_st.strip():
                return canon_standort(ref_st)
        except Exception:
            pass
    return "engelbrechts"

# -----------------------------------------------------------------------------
# *** NEU: View-Helper, die vorher gefehlt haben ***
# -----------------------------------------------------------------------------
def get_year_kw(year: int | None, kw: int | None) -> tuple[int, int]:
    """Fallback auf aktuelle ISO-Woche/Jahr, wenn Parameter None sind."""
    today = date.today()
    y = year or today.isocalendar()[0]
    w = kw or today.isocalendar()[1]
    return int(y), int(w)

def ensure_week_plan(year: int, kw: int, standort: str) -> dict:
    """Holt oder erzeugt den Week-Plan (inkl. four_day_week, row_count)."""
    standort = canon_standort(standort)
    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute("SELECT id, row_count, four_day_week FROM week_plans WHERE year=? AND kw=? AND standort=?",
                    (year, kw, standort))
        row = cur.fetchone()
        if row:
            return {"id": row["id"], "row_count": int(row["row_count"] or 5), "four_day_week": int(row["four_day_week"] or 0)}
        # neu anlegen (Default 5 Zeilen, 4-Tage-Woche aktiv = 1, wie bisheriger Default)
        cur.execute("INSERT INTO week_plans(year,kw,standort,row_count,four_day_week) VALUES(?,?,?,?,1)",
                    (year, kw, standort, 5))
        conn.commit()
        pid = cur.lastrowid
        return {"id": pid, "row_count": 5, "four_day_week": 1}
    finally:
        conn.close()

def load_employees_by_standort(standort: str) -> list[dict]:
    """Lädt Mitarbeiterliste für Standort (sortiert nach id)."""
    standort = canon_standort(standort)
    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute("SELECT id, name FROM employees WHERE standort=? ORDER BY id", (standort,))
        return [{"id": r["id"], "name": r["name"]} for r in cur.fetchall()]
    finally:
        conn.close()

def load_week_cells_as_grid(plan_id: int, rows: int) -> list[list[dict]]:
    """Lädt Zellen zu plan_id in ein Grid [rows x 5] mit {'text': ...}."""
    grid = [[{"text": ""} for _ in range(5)] for _ in range(rows)]
    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute("SELECT row_index, day_index, text FROM week_cells WHERE week_plan_id=?", (plan_id,))
        for r in cur.fetchall():
            ri, di = int(r["row_index"]), int(r["day_index"])
            if 0 <= ri < rows and 0 <= di < 5:
                grid[ri][di]["text"] = r["text"] or ""
    finally:
        conn.close()
    return grid

# -----------------------------------------------------------------------------
# ADMIN/DEBUG/HEALTH – unverändert
# -----------------------------------------------------------------------------
@app.get("/admin/normalize-standorte")
def admin_normalize():
    conn = get_conn(); cur = conn.cursor()
    try:
        for table, col in [("employees", "standort"), ("week_plans", "standort"), ("global_small_jobs", "standort")]:
            cur.execute(f"SELECT id, {col} FROM {table}")
            for r in cur.fetchall():
                st_new = canon_standort(r[col])
                if st_new != (r[col] or ""):
                    cur.execute(f"UPDATE {table} SET {col}=? WHERE id=?", (st_new, r["id"]))
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

@app.get("/health")
def health():
    return {"status": "ok"}

# -----------------------------------------------------------------------------
# PLAIN TEST / EMPLOYEES (unverändert)
# -----------------------------------------------------------------------------
@app.get("/settings/employees_plain", response_class=HTMLResponse)
def employees_plain():
    return HTMLResponse("""
<!DOCTYPE html>
<html lang="de"><head><meta charset="utf-8"><title>Plain · Mitarbeiter</title></head>
<body>
 <h1>Plain · Mitarbeiter</h1>
 /settings/employees<input type="hidden" name="standort" value="gross-gerungs" />
 <p><label>Neuer Mitarbeiter 1: <input type="text" name="emp_name_new[]" /></label></p>
 <p><label>Neuer Mitarbeiter 2: <input type="text" name="emp_name_new[]" /></label></p>
 <p><button type="submit">Speichern</button></p>
 </form>
</body>
</html>
""".strip())

# -----------------------------------------------------------------------------
# WEEK (GET) – unverändert aus deiner Basis
# -----------------------------------------------------------------------------
@app.get("/week", response_class=HTMLResponse)
def week(request: Request, kw: int = 1, year: int = 2025, standort: str = "engelbrechts"):
    standort = canon_standort(standort)
    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute("SELECT id,row_count,four_day_week FROM week_plans WHERE year=? AND kw=? AND standort=?",
                    (year, kw, standort))
        plan = cur.fetchone()
        if not plan:
            cur.execute(
                "INSERT INTO week_plans(year,kw,standort,row_count,four_day_week) VALUES(?,?,?,?,1)",
                (year, kw, standort, 5)
            )
            conn.commit()
            plan_id, rows, four_day_week = cur.lastrowid, 5, 1
        else:
            plan_id = plan["id"]; rows = plan["row_count"]; four_day_week = plan["four_day_week"]
        cur.execute("SELECT id,name FROM employees WHERE standort=? ORDER BY id", (standort,))
        employees = [{"id": e["id"], "name": e["name"]} for e in cur.fetchall()]
        if employees:
            rows = max(rows, len(employees))
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
                "standorte": STANDORTE,  # für Standort-Dropdown
            }
        )
    except Exception:
        return HTMLResponse(f"<pre>{traceback.format_exc()}</pre>", status_code=500)
    finally:
        conn.close()

# -----------------------------------------------------------------------------
# WEEK API (POST) – unverändert aus deiner Basis
# -----------------------------------------------------------------------------
@app.post("/api/week/set-cell")
async def set_cell(request: Request, data: dict = Body(...), standort_q: str | None = Query(None, alias="standort")):
    conn = get_conn(); cur = conn.cursor()
    try:
        year = int(data.get("year")); kw = int(data.get("kw"))
        standort = resolve_standort(request, data.get("standort"), standort_q)
        row = int(data.get("row")); day = int(data.get("day")); val = data.get("value") or ""
        cur.execute("SELECT id,four_day_week FROM week_plans WHERE year=? AND kw=? AND standort=?", (year, kw, standort))
        plan = cur.fetchone()
        if not plan:
            return {"ok": False, "error": "Plan not found"}
        if plan["four_day_week"] and day == 4:
            return {"ok": True, "skipped": True}
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

@app.post("/api/week/batch")
async def save_batch(data: dict = Body(...)):
    conn = get_conn(); cur = conn.cursor()
    try:
        year = int(data.get("year")); kw = int(data.get("kw"))
        standort = canon_standort(data.get("standort") or "engelbrechts")
        updates = data.get("updates") or []
        cur.execute("SELECT id,four_day_week FROM week_plans WHERE year=? AND kw=? AND standort=?", (year, kw, standort))
        plan = cur.fetchone()
        if not plan:
            return {"ok": False, "error": "Plan not found"}
        for u in updates:
            row = int(u.get("row")); day = int(u.get("day"))
            if plan["four_day_week"] and day == 4:
                continue
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
            cur.execute("INSERT INTO week_plans(year,kw,standort,row_count,four_day_week) VALUES(?,?,?,?,?)",
                        (year, kw, standort, 5, value))
        else:
            cur.execute("UPDATE week_plans SET four_day_week=? WHERE year=? AND kw=? AND standort=?",
                        (value, year, kw, standort))
        conn.commit()
        return {"ok": True, "four_day_week": bool(value)}
    except Exception:
        return JSONResponse({"ok": False, "error": traceback.format_exc()}, status_code=500)
    finally:
        conn.close()

@app.post("/api/week/options")
async def options_alias(data: dict = Body(...)):
    return await set_four_day(data)

# -----------------------------------------------------------------------------
# KLEINBAUSTELLEN – unverändert aus deiner Basis
# -----------------------------------------------------------------------------
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

# -----------------------------------------------------------------------------
# EINSTELLUNGEN: MITARBEITER – unverändert aus deiner Basis
# -----------------------------------------------------------------------------
@app.get("/settings/employees", response_class=HTMLResponse)
def settings_employees_page(request: Request, standort: str = "engelbrechts"):
    st = canon_standort(standort)
    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute("SELECT id,name FROM employees WHERE standort=? ORDER BY id", (st,))
        employees = [{"id": r["id"], "name": r["name"]} for r in cur.fetchall()]
        return templates.TemplateResponse(
            "settings_employees.html",
            {"request": request, "standort": st, "employees": employees}
        )
    except Exception:
        return HTMLResponse(f"<pre>{traceback.format_exc()}</pre>", status_code=500)
    finally:
        conn.close()

@app.post("/settings/employees", response_class=HTMLResponse)
async def settings_employees_save(request: Request):
    form = await request.form()
    # DEBUG: eingehende Form-Schlüssel loggen
    try:
        items_preview = [(k, v) for k, v in form.items()]
        logger.info("POST /settings/employees · items=%s", items_preview)
    except Exception:
        logger.info("POST /settings/employees · (items preview nicht möglich)")
    st = form.get("standort") or request.query_params.get("standort") or None
    st = resolve_standort(request, st, request.query_params.get("standort"))
    # Neue: emp_name_new[]
    new_list = []
    for key, val in form.multi_items():
        if key == "emp_name_new[]":
            t = (val or "").strip()
            if t:
                new_list.append(t)
    logger.info("POST /settings/employees · standort=%s · new_list=%s", st, new_list)
    conn = get_conn(); cur = conn.cursor()
    try:
        for n in new_list:
            cur.execute("INSERT INTO employees(name, standort) VALUES(?, ?)", (n, st))
        conn.commit()
        cur.execute("SELECT id,name FROM employees WHERE standort=? ORDER BY id", (st,))
        employees = [{"id": r["id"], "name": r["name"]} for r in cur.fetchall()]
        return templates.TemplateResponse(
            "settings_employees.html",
            {"request": request, "standort": st, "employees": employees, "saved": True}
        )
    except Exception:
        return HTMLResponse(f"<pre>{traceback.format_exc()}</pre>", status_code=500)
    finally:
        conn.close()

# -----------------------------------------------------------------------------
# YEAR (Platzhalter) – unverändert
# -----------------------------------------------------------------------------
@app.get("/year", response_class=HTMLResponse)
def year_page(request: Request, year: int = 2025):
    try:
        return templates.TemplateResponse("year.html", {"request": request, "year": year})
    except Exception:
        return HTMLResponse(f"<h1>Jahresplanung</h1><p>year={year}</p>", status_code=200)

# -----------------------------------------------------------------------------
# *** FIXED: VIEW / READ-ONLY – funktioniert jetzt stabil ***
# -----------------------------------------------------------------------------
@app.get("/view/week", response_class=HTMLResponse)
def view_week(
    request: Request,
    year: int | None = None,
    kw: int | None = None,
    standort: str = "engelbrechts"
):
    try:
        year, kw = get_year_kw(year, kw)
        st = canon_standort(standort)
        # Plan sicherstellen + Daten laden
        plan = ensure_week_plan(year, kw, st)
        employees = load_employees_by_standort(st)
        rows = max(int(plan["row_count"] or 5), len(employees) or 0)
        grid = load_week_cells_as_grid(int(plan["id"]), rows)
        return templates.TemplateResponse(
            "week_view.html",
            {
                "request": request,
                "year": year,
                "kw": kw,
                "standort": st,
                "plan": plan,
                "grid": grid,
                "employees": employees,
                "four_day_week": bool(plan.get("four_day_week") or 0),
                "days": build_days(year, kw),
            }
        )
    except Exception:
        return HTMLResponse(f"<pre>{traceback.format_exc()}</pre>", status_code=500)
``
