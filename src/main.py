
# src/main.py
from fastapi import FastAPI, Request, Body, Query
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import sqlite3
from pathlib import Path
from datetime import date, timedelta, datetime
import traceback
from urllib.parse import urlparse, parse_qs

app = FastAPI(title="Zankl-Plan MVP")
BASE_DIR = Path(__file__).resolve().parent  # src/
ROOT_DIR = BASE_DIR.parent                  # project root
DB_PATH = BASE_DIR / "zankl.db"

templates = Jinja2Templates(directory=str(ROOT_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(ROOT_DIR / "static")), name="static")

# ---------------- DB ----------------
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
        CREATE TABLE IF NOT EXISTS week_plans(
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
        CREATE TABLE IF NOT EXISTS week_cells(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          week_plan_id INTEGER,
          row_index INTEGER,
          day_index INTEGER,
          text TEXT,
          UNIQUE(week_plan_id, row_index, day_index)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS employees(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT,
          standort TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS global_small_jobs(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          standort TEXT,
          row_index INTEGER,
          text TEXT,
          UNIQUE(standort, row_index)
        )
    """)
    conn.commit(); conn.close()
init_db()

# ---------------- Helpers ----------------
def build_days(year: int, kw: int):
    kw = max(1, min(kw, 53))
    start = date.fromisocalendar(year, kw, 1)  # Montag
    labels = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag"]
    return [{"label": labels[i], "date": (start + timedelta(days=i)).strftime("%d.%m.%Y")} for i in range(5)]

def canon_standort(s: str | None) -> str:
    s = (s or "").strip()
    if not s:
        return "engelbrechts"
    s_low = " ".join(s.lower().split()).replace("ß", "ss").replace("_", "-")
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

def auto_view_target(now: datetime | None = None) -> tuple[int, int]:
    """Viewer: Normal = aktuelle ISO-KW; ab Fr 12:00 & Sa/So -> nächste KW."""
    now = now or datetime.now()
    y, w, wd = now.isocalendar()
    if (wd == 5 and now.hour >= 12) or (wd >= 6):
        monday = date.fromisocalendar(y, w, 1)
        next_monday = monday + timedelta(days=7)
        y2, w2 = next_monday.isocalendar()[:2]
        return int(y2), int(w2)
    return int(y), int(w)

def _pint(v):
    try: return int(v)
    except Exception: return None

def derive_year_kw_from_request(request: Request, data: dict) -> tuple[int, int]:
    """1) Body, 2) Referer (/week?kw&year), 3) auto_view_target"""
    y = _pint(data.get("year")); w = _pint(data.get("kw"))
    if y is not None and w is not None: return y, w
    ref = request.headers.get("referer") or request.headers.get("Referer") or ""
    try:
        qs = parse_qs(urlparse(ref).query)
        if y is None: y = _pint((qs.get("year") or [""])[0])
        if w is None: w = _pint((qs.get("kw") or [""])[0])
    except Exception:
        pass
    if y is not None and w is not None: return y, w
    ay, aw = auto_view_target()
    return int(y or ay), int(w or aw)

# ---------------- zentrale Week-Logik ----------------
def build_week_context(year: int, kw: int, standort: str):
    st = canon_standort(standort)
    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute("SELECT id,row_count,four_day_week FROM week_plans WHERE year=? AND kw=? AND standort=?", (year, kw, st))
        plan = cur.fetchone()
        if not plan:
            cur.execute(
                "INSERT INTO week_plans(year,kw,standort,row_count,four_day_week) VALUES(?,?,?,?,1)",
                (year, kw, st, 5)
            )
            conn.commit()
            plan_id, rows, four = cur.lastrowid, 5, 1
        else:
            plan_id, rows, four = plan["id"], plan["row_count"], plan["four_day_week"]

        cur.execute("SELECT id,name FROM employees WHERE standort=? ORDER BY id", (st,))
        employees = [{"id": e["id"], "name": e["name"]} for e in cur.fetchall()]
        if employees:
            rows = max(rows, len(employees))

        grid = [[{"text": ""} for _ in range(5)] for _ in range(rows)]
        cur.execute("SELECT row_index,day_index,text FROM week_cells WHERE week_plan_id=?", (plan_id,))
        for r in cur.fetchall():
            ri, di = int(r["row_index"]), int(r["day_index"])
            if 0 <= ri < rows and 0 <= di < 5:
                grid[ri][di]["text"] = r["text"] or ""

        cur.execute("SELECT row_index,text FROM global_small_jobs WHERE standort=? ORDER BY row_index", (st,))
        small_jobs = [{"row_index": s["row_index"], "text": s["text"] or ""} for s in cur.fetchall()]
        max_idx = max([x["row_index"] for x in small_jobs], default=-1)
        while len(small_jobs) < 10:
            max_idx += 1
            small_jobs.append({"row_index": max_idx, "text": ""})

        return {
            "plan_id": plan_id,
            "rows": rows,
            "four_day_week": bool(four),
            "employees": employees,
            "grid": grid,
            "small_jobs": small_jobs,
            "standort": st,
            "days": build_days(year, kw),
        }
    finally:
        conn.close()

# ---------------- Admin/Debug/Health ----------------
@app.get("/")
def root():
    # 200 OK (kein 30x) -> Render-Healthcheck ist happy; Meta-Refresh sendet zur View
    html = """
    <!doctype html><html lang="de"><head>
      <meta charset="utf-8">
      <meta http-equiv="refresh" content="0; url=/view">
      <title>Zankl-Plan</title>
      <style>body{font-family:system-ui,Segoe UI,Arial,sans-serif;padding:24px;color:#0f172a}</style>
    </head><body>
      <h1>Zankl-Plan</h1>
      <p>Weiterleitung zur Ansicht… Falls nichts passiert, /viewhier klicken</a>.</p>
    </body></html>
    """
    return HTMLResponse(html, status_code=200)

@app.get("/admin/routes")
def admin_routes():
    return {"routes": sorted([r.path for r in app.routes])}

@app.get("/admin/peek-week")
def admin_peek_week(standort: str, year: int, kw: int):
    st = canon_standort(standort)
    conn = get_conn(); cur = conn.cursor()
    try:
        out = {"standort": st, "year": year, "kw": kw}
        cur.execute("SELECT id,row_count,four_day_week FROM week_plans WHERE year=? AND kw=? AND standort=?", (year, kw, st))
        p = cur.fetchone()
        if not p:
            out["plan"] = None
            out["cells"] = []
        else:
            out["plan"] = {"id": p["id"], "row_count": p["row_count"], "four_day_week": p["four_day_week"]}
            cur.execute("SELECT row_index,day_index,text FROM week_cells WHERE week_plan_id=? ORDER BY row_index,day_index", (p["id"],))
            out["cells"] = [dict(r) for r in cur.fetchall()]
        cur.execute("SELECT id,name FROM employees WHERE standort=? ORDER BY id", (st,))
        out["employees"] = [dict(r) for r in cur.fetchall()]
        return out
    finally:
        conn.close()

@app.get("/admin/peek-klein")
def admin_peek_klein(standort: str = "engelbrechts"):
    st = canon_standort(standort)
    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute("SELECT row_index,text FROM global_small_jobs WHERE standort=? ORDER BY row_index", (st,))
        return {"standort": st, "items": [dict(r) for r in cur.fetchall()]}
    finally:
        conn.close()

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/favicon.ico")
def favicon():
    return Response(status_code=204)

# ---------------- Einstellungen (Not Found vermeiden) ----------------
@app.get("/settings", response_class=HTMLResponse)
def settings_root():
    html = """
    <h1>Einstellungen</h1>
    <ul>
      <li>/settings/employeesMitarbeiter verwalten</a></li>
      <li>/settings/usersBenutzer-Zuordnung (Viewer → Standort)</a></li>
      <li>/bedienungBedienung / Hilfe</a></li>
    </ul>
    """
    return HTMLResponse(html, status_code=200)

@app.get("/settings/users", response_class=HTMLResponse)
def settings_users_placeholder():
    html = """
    <h1>Benutzer-Zuordnung</h1>
    <p>Platzhalter-Seite. (Später: Viewer → Standort)</p>
    <p>/settingsZurück zu Einstellungen</a></p>
    """
    return HTMLResponse(html, status_code=200)

@app.get("/bedienung", response_class=HTMLResponse)
def bedienung_page():
    html = """
    <h1>Bedienung</h1>
    <p>Kurzbeschreibung folgt. Für jetzt: Navigation über die Leiste oben.</p>
    """
    return HTMLResponse(html, status_code=200)

# ---------------- WEEK – Edit ----------------
@app.get("/week", response_class=HTMLResponse)
def week(
    request: Request,
    kw: int | None = None,
    year: int | None = None,
    standort: str = "engelbrechts"
):
    # Ohne Parameter: aktuelle ISO-KW/Jahr (nicht die Freitag-12-Regel)
    if year is None or kw is None:
        today = date.today(); iso = today.isocalendar()
        year = int(year or iso[0]); kw = int(kw or iso[1])

    standort = canon_standort(standort)
    try:
        ctx = build_week_context(year, kw, standort)
        return templates.TemplateResponse(
            "week.html",
            {
                "request": request,
                "grid": ctx["grid"],
                "employees": ctx["employees"],
                "kw": kw,
                "year": year,
                "days": ctx["days"],
                "standort": standort,
                "four_day_week": ctx["four_day_week"],
                "small_jobs": ctx["small_jobs"],
                "standorte": ["engelbrechts", "gross-gerungs"],
            }
        )
    except Exception:
        return HTMLResponse(f"<pre>{traceback.format_exc()}</pre>", status_code=500)

# ---------------- WEEK API (robust) ----------------
def _ensure_plan(cur, year: int, kw: int, standort: str) -> tuple[int, int]:
    cur.execute("SELECT id,four_day_week FROM week_plans WHERE year=? AND kw=? AND standort=?", (year, kw, standort))
    p = cur.fetchone()
    if p:
        return p["id"], int(p["four_day_week"])
    cur.execute(
        "INSERT INTO week_plans(year,kw,standort,row_count,four_day_week) VALUES(?,?,?,?,1)",
        (year, kw, standort, 5)
    )
    return cur.lastrowid, 1

@app.post("/api/week/set-cell")
async def set_cell(request: Request, data: dict = Body(...), standort_q: str | None = Query(None, alias="standort")):
    conn = get_conn(); cur = conn.cursor()
    try:
        year, kw = derive_year_kw_from_request(request, data)
        standort = resolve_standort(request, data.get("standort"), standort_q)
        row = _pint(data.get("row")); day = _pint(data.get("day"))
        if row is None or day is None:
            return JSONResponse({"ok": False, "error": "row/day invalid"}, status_code=400)
        val = (data.get("value") or "")

        plan_id, four_flag = _ensure_plan(cur, year, kw, standort)
        if four_flag and day == 4:
            return {"ok": True, "skipped": True}

        cur.execute("""
            INSERT INTO week_cells(week_plan_id,row_index,day_index,text)
            VALUES(?,?,?,?)
            ON CONFLICT(week_plan_id,row_index,day_index) DO UPDATE SET text=excluded.text
        """, (plan_id, row, day, val))
        conn.commit()
        return {"ok": True, "standort": standort, "year": year, "kw": kw}
    except Exception:
        return JSONResponse({"ok": False, "error": traceback.format_exc()}, status_code=500)
    finally:
        conn.close()

@app.post("/api/week/batch")
async def save_batch(request: Request, data: dict = Body(...)):
    conn = get_conn(); cur = conn.cursor()
    try:
        year, kw = derive_year_kw_from_request(request, data)
        standort = canon_standort(data.get("standort") or resolve_standort(request, None, None))
        updates = data.get("updates") or []

        plan_id, four_flag = _ensure_plan(cur, year, kw, standort)
        for u in updates:
            row = _pint(u.get("row")); day = _pint(u.get("day"))
            if row is None or day is None: continue
            if four_flag and day == 4: continue
            val = (u.get("value") or "")
            cur.execute("""
                INSERT INTO week_cells(week_plan_id,row_index,day_index,text)
                VALUES(?,?,?,?)
                ON CONFLICT(week_plan_id,row_index,day_index) DO UPDATE SET text=excluded.text
            """, (plan_id, row, day, val))
        conn.commit()
        return {"ok": True, "count": len(updates), "year": year, "kw": kw}
    except Exception:
        return JSONResponse({"ok": False, "error": traceback.format_exc()}, status_code=500)
    finally:
        conn.close()

# ---------------- Kleinbaustellen (fix: 2 Endpunkte + flexible Felder) ----------------
def _save_klein(standort: str, row_index: int, text: str):
    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO global_small_jobs(standort,row_index,text)
            VALUES(?,?,?)
            ON CONFLICT(standort,row_index) DO UPDATE SET text=excluded.text
        """, (standort, row_index, text))
        conn.commit()
    finally:
        conn.close()

def _row_index_from_payload(d: dict) -> int:
    # akzeptiere row_index ODER row
    ri = _pint(d.get("row_index"))
    if ri is None:
        ri = _pint(d.get("row"))
    return int(ri or 0)

@app.post("/api/klein/set")
async def klein_set(data: dict = Body(...)):
    st = canon_standort(data.get("standort") or "engelbrechts")
    ri = _row_index_from_payload(data)
    txt = (data.get("text") or "").strip()
    _save_klein(st, ri, txt)
    return {"ok": True}

@app.post("/api/klein/set-cell")  # Alias für ältere/neue Frontends
async def klein_set_cell(data: dict = Body(...)):
    st = canon_standort(data.get("standort") or "engelbrechts")
    ri = _row_index_from_payload(data)
    txt = (data.get("text") or "").strip()
    _save_klein(st, ri, txt)
    return {"ok": True}

# ---------------- VIEW (read-only) ----------------
@app.get("/view", response_class=HTMLResponse)
def view_shortcut(
    request: Request,
    standort: str = "engelbrechts",
    year: int | None = None,
    kw: int | None = None
):
    try:
        if year is None or kw is None:
            year, kw = auto_view_target()
        else:
            year, kw = int(year), int(kw)
        ctx = build_week_context(year, kw, standort)
        return templates.TemplateResponse(
            "week_view.html",
            {
                "request": request,
                "year": year,
                "kw": kw,
                "standort": ctx["standort"],
                "grid": ctx["grid"],
                "employees": ctx["employees"],
                "four_day_week": ctx["four_day_week"],
                "days": ctx["days"],
            }
        )
    except Exception:
        return HTMLResponse(f"<pre>{traceback.format_exc()}</pre>", status_code=500)

@app.get("/view/week", response_class=HTMLResponse)
def view_week(
    request: Request,
    year: int | None = None,
    kw: int | None = None,
    standort: str = "engelbrechts"
):
    try:
        if year is None or kw is None:
            year, kw = auto_view_target()
        else:
            year, kw = int(year), int(kw)
        ctx = build_week_context(year, kw, standort)
        return templates.TemplateResponse(
            "week_view.html",
            {
                "request": request,
                "year": year,
                "kw": kw,
                "standort": ctx["standort"],
                "grid": ctx["grid"],
                "employees": ctx["employees"],
                "four_day_week": ctx["four_day_week"],
                "days": ctx["days"],
            }
        )
    except Exception:
        return HTMLResponse(f"<pre>{traceback.format_exc()}</pre>", status_code=500)
