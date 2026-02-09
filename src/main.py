
from fastapi import FastAPI, Request, Body, Query
from starlette.middleware.sessions import SessionMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import sqlite3
from pathlib import Path
from datetime import date, timedelta, datetime
import traceback
from urllib.parse import urlparse, parse_qs
import hashlib
import hmac

app = FastAPI(title="Zankl-Plan MVP")
app.add_middleware(
    SessionMiddleware,
    secret_key="zankl-plan-secret-change-me"
)
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
    conn = get_conn()
    cur = conn.cursor()

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

    # ---- Users / Login ----
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          username TEXT UNIQUE,
          password_hash TEXT,
          is_write INTEGER NOT NULL DEFAULT 0,
          can_view_eb INTEGER NOT NULL DEFAULT 0,
          can_view_gg INTEGER NOT NULL DEFAULT 0
        )
    """)

    # Migration
    if not column_exists(cur, "users", "is_write"):
        cur.execute("ALTER TABLE users ADD COLUMN is_write INTEGER NOT NULL DEFAULT 0")

    if not column_exists(cur, "users", "can_view_eb"):
        cur.execute("ALTER TABLE users ADD COLUMN can_view_eb INTEGER NOT NULL DEFAULT 0")

    if not column_exists(cur, "users", "can_view_gg"):
        cur.execute("ALTER TABLE users ADD COLUMN can_view_gg INTEGER NOT NULL DEFAULT 0")

    # ---- YEAR PLAN (Jahresplanung) ----
    cur.execute("""
        CREATE TABLE IF NOT EXISTS year_rows(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          section TEXT NOT NULL,               -- 'eb' | 'res' | 'gg'
          row_index INTEGER NOT NULL,
          name TEXT NOT NULL,
          UNIQUE(section, row_index)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS year_jobs(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          title TEXT NOT NULL UNIQUE,          -- "Name, Ort"
          start_date TEXT NOT NULL,            -- 'YYYY-MM-DD'
          duration_days INTEGER NOT NULL,      -- Arbeitstage
          height_rows INTEGER NOT NULL,        -- Mitarbeiter/Zeilen-Höhe
          section TEXT NOT NULL,               -- 'eb'|'res'|'gg'
          row_index INTEGER NOT NULL,          -- Startzeile (0-basiert innerhalb section)
          color TEXT NOT NULL,                 -- 'blue'|'yellow'|'red'|'green'
          note TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS year_week_overrides(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          year INTEGER NOT NULL,
          kw INTEGER NOT NULL,
          show_friday INTEGER NOT NULL DEFAULT 0,
          UNIQUE(year, kw)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS year_holidays(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          day TEXT NOT NULL UNIQUE,            -- 'YYYY-MM-DD'
          label TEXT
        )
    """)

    # ---- SEED default row names (nur wenn leer) ----
    def seed_rows(section: str, default_count: int, prefix: str):
        cur.execute("SELECT COUNT(*) AS n FROM year_rows WHERE section=?", (section,))
        if cur.fetchone()["n"] == 0:
            for i in range(default_count):
                name = f"{prefix} {i+1}"
                cur.execute(
                    "INSERT INTO year_rows(section,row_index,name) VALUES(?,?,?)",
                    (section, i, name)
                )

    seed_rows("eb", 12, "Team EB")
    seed_rows("gg", 12, "Team GG")
    seed_rows("res", 8, "Ressource")

    
    conn.commit()
    conn.close()


@app.on_event("startup")
def _startup():
    init_db()
    ensure_admin_user()


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

def auto_view_target(now: datetime | None = None) -> tuple[int, int]:
    # Viewer: Normal = aktuelle ISO-KW; ab Fr 12:00 & Sa/So -> nächste KW
    now = now or datetime.now()
    y, w, wd = now.isocalendar()
    if (wd == 5 and now.hour >= 12) or (wd >= 6):
        monday = date.fromisocalendar(y, w, 1)
        next_monday = monday + timedelta(days=7)
        y2, w2 = next_monday.isocalendar()[:2]
        return int(y2), int(w2)
    return int(y), int(w)


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def verify_password(password: str, password_hash: str) -> bool:
    return hmac.compare_digest(
        hashlib.sha256(password.encode("utf-8")).hexdigest(),
        password_hash
    )
def ensure_admin_user():

    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT id FROM users WHERE username=?", ("admin",))
        row = cur.fetchone()
        if not row:
            cur.execute(
                "INSERT INTO users(username, password_hash, is_write, can_view_eb, can_view_gg) VALUES(?,?,?,?,?)",
                ("admin", hash_password("admin"), 1, 1, 1)
            )
        else:
            cur.execute(
                "UPDATE users SET password_hash=?, is_write=1, can_view_eb=1, can_view_gg=1 WHERE username=?",
                (hash_password("admin"), "admin")
            )
        conn.commit()
    finally:
        conn.close()



# ---------------- YEAR helpers ----------------
def iso_monday(year: int, kw: int) -> date:
    return date.fromisocalendar(year, kw, 1)

def parse_ymd(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()

def fmt_ymd(d: date) -> str:
    return d.strftime("%Y-%m-%d")

def is_holiday(cur, d: date) -> bool:
    cur.execute("SELECT 1 FROM year_holidays WHERE day=?", (fmt_ymd(d),))
    return cur.fetchone() is not None

def get_friday_override(cur, year: int, kw: int) -> int | None:
    cur.execute("SELECT show_friday FROM year_week_overrides WHERE year=? AND kw=?", (year, kw))
    r = cur.fetchone()
    if not r:
        return None
    return int(r["show_friday"])

def should_show_friday(cur, year: int, kw: int) -> bool:
    """
    Default-Regel:
      - Sommer (KW 14..42): Fr AUS (4-Tage)
      - Winter (KW 43..13): Fr AN
    Override pro KW in year_week_overrides hat Vorrang.
    """
    ov = get_friday_override(cur, year, kw)
    if ov is not None:
        return bool(ov)

    if 14 <= int(kw) <= 42:
        return False
    return True

def is_workday(cur, d: date) -> bool:
    # nur Mo–Fr, Fr evtl. ausgeblendet
    wd = d.isoweekday()  # 1..7
    if wd >= 6:
        return False
    if is_holiday(cur, d):
        return False
    if wd == 5:
        y, w, _ = d.isocalendar()
        return should_show_friday(cur, int(y), int(w))
    return True

def add_workdays(cur, start: date, workdays: int) -> date:
    """
    Gibt das Enddatum zurück (exklusiv gedacht),
    indem workdays Arbeitstage ab start gezählt werden.
    """
    d = start
    remaining = int(workdays)
    while remaining > 0:
        if is_workday(cur, d):
            remaining -= 1
        d = d + timedelta(days=1)
    return d  # Tag NACH dem letzten gezählten Arbeitstag

def build_year_days(cur, center: date) -> list[dict]:
    """
    Sichtbereich ~ 3 Wochen (ca. 15 Arbeitstage).
    Wir zeigen: 15 Arbeitstage, so dass center ungefähr in der Mitte liegt.
    """
    # wir gehen 7 Arbeitstage zurück
    d = center
    back = 7
    while back > 0:
        d -= timedelta(days=1)
        if is_workday(cur, d):
            back -= 1

    days = []
    d2 = d
    want = 15
    while len(days) < want:
        if is_workday(cur, d2):
            y, w, _ = d2.isocalendar()
            days.append({
                "ymd": fmt_ymd(d2),
                "label": ["Mo", "Di", "Mi", "Do", "Fr"][d2.isoweekday()-1],
                "date": d2.strftime("%d.%m."),
                "year": int(y),
                "kw": int(w),
                "is_friday": (d2.isoweekday() == 5),
            })
        d2 += timedelta(days=1)

    return days

def build_year_days_for_year(cur, year: int) -> list[dict]:
    """
    Liefert ALLE Arbeitstage eines Jahres (Mo–Fr, Fr nach Regel/Override, Feiertage raus).
    Zusätzlich: date_full als dd.mm.yy für die Anzeige.
    """
    start = date(year, 1, 1)
    end = date(year, 12, 31)

    out = []
    d = start
    while d <= end:
        if is_workday(cur, d):
            y, w, _ = d.isocalendar()
            out.append({
                "ymd": fmt_ymd(d),
                "label": ["Mo", "Di", "Mi", "Do", "Fr"][d.isoweekday()-1],
                "date": d.strftime("%d.%m."),      # kurz (falls du es noch wo brauchst)
                "date_full": d.strftime("%d.%m.%y"),  # NEU: dd.mm.yy
                "year": int(y),
                "kw": int(w),
                "is_friday": (d.isoweekday() == 5),
            })
        d += timedelta(days=1)

    return out


# 👉 GENAU HIER EINFÜGEN
def password_ok(pw: str) -> bool:
    if pw is None:
        return False
    pw = str(pw)
    if len(pw) < 8:
        return False
    has_letter = any(c.isalpha() for c in pw)
    has_digit = any(c.isdigit() for c in pw)
    has_special = any(not c.isalnum() for c in pw)
    return has_letter and has_digit and has_special
# 👈 BIS HIER


def get_current_user(request: Request):
    return request.session.get("user")


def require_write(request: Request):
    u = request.session.get("user")
    if not u:
        return RedirectResponse("/login", status_code=303)
    if not u.get("is_write"):
        return RedirectResponse("/view/week", status_code=303)
    return None

# ---------------- YEAR – Jahresplanung ----------------
@app.get("/year", response_class=HTMLResponse)
def year_page(request: Request, year: int | None = Query(None)):
    guard = require_write(request)
    if guard:
        return guard

    year_sel = int(year) if year else date.today().year


    conn = get_conn(); cur = conn.cursor()
    try:
        days = build_year_days_for_year(cur, year_sel)

        # rows
        cur.execute("SELECT id, section, row_index, name FROM year_rows ORDER BY section, row_index")
        rows_all = [dict(r) for r in cur.fetchall()]

        # section split
        rows = {"eb": [], "res": [], "gg": []}
        for r in rows_all:
            rows[r["section"]].append(r)

        # jobs
        cur.execute("SELECT * FROM year_jobs ORDER BY start_date")
        jobs_db = [dict(r) for r in cur.fetchall()]

        # map day -> col index
        day_to_col = {d["ymd"]: i for i, d in enumerate(days)}

        # build jobs for view (position + span)
        jobs = []
        for j in jobs_db:
            try:
                start = parse_ymd(j["start_date"])
            except Exception:
                continue

            end_excl = add_workdays(cur, start, int(j["duration_days"]))

            # find first visible workday col >= start
            # and last visible workday col < end_excl
            visible_cols = []
            for d in days:
                dd = parse_ymd(d["ymd"])
                if dd >= start and dd < end_excl:
                    visible_cols.append(day_to_col[d["ymd"]])

            if not visible_cols:
                continue

            col_start = min(visible_cols)
            col_end = max(visible_cols)
            col_span = (col_end - col_start + 1)

            jobs.append({
                **j,
                "col_start": col_start,
                "col_span": col_span,
                "row_index": int(j["row_index"]),
                "height_rows": int(j["height_rows"]),
            })

        # friday visibility map per KW (für Checkboxen im Header)
kw_map = {}
for d in days:
    if d.get("label") != "Mo":
        continue
    key = f'{d["year"]}-KW{d["kw"]}'
    kw_map[key] = {
        "year": d["year"],
        "kw": d["kw"],
        "show_friday": 1 if should_show_friday(cur, d["year"], d["kw"]) else 0
    }


return templates.TemplateResponse(
    "year.html",
    {
        "request": request,
        "year": year_sel,   # <-- NEU
        "days": days,
        "kw_map": list(kw_map.values()),
        "rows": rows,
        "jobs": jobs,
    }
)

    finally:
        conn.close()


@app.post("/api/year/toggle-holiday")
async def api_year_toggle_holiday(request: Request, data: dict = Body(...)):
    guard = require_write(request)
    if guard:
        return JSONResponse({"ok": False, "redirect": "/login"}, status_code=401)

    day = (data.get("day") or "").strip()  # 'YYYY-MM-DD'
    label = (data.get("label") or "").strip()

    if not day:
        return JSONResponse({"ok": False, "error": "missing day"}, status_code=400)

    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute("SELECT id FROM year_holidays WHERE day=?", (day,))
        r = cur.fetchone()
        if r:
            cur.execute("DELETE FROM year_holidays WHERE day=?", (day,))
            conn.commit()
            return {"ok": True, "holiday": False}
        else:
            cur.execute("INSERT INTO year_holidays(day,label) VALUES(?,?)", (day, label or None))
            conn.commit()
            return {"ok": True, "holiday": True}
    finally:
        conn.close()


@app.post("/api/year/set-friday")
async def api_year_set_friday(request: Request, data: dict = Body(...)):
    guard = require_write(request)
    if guard:
        return JSONResponse({"ok": False, "redirect": "/login"}, status_code=401)

    year = int(data.get("year"))
    kw = int(data.get("kw"))
    show = 1 if bool(data.get("show_friday")) else 0

    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO year_week_overrides(year,kw,show_friday)
            VALUES(?,?,?)
            ON CONFLICT(year,kw) DO UPDATE SET show_friday=excluded.show_friday
        """, (year, kw, show))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()
@app.post("/api/year/update-row-name")
async def api_year_update_row_name(request: Request, data: dict = Body(...)):
    guard = require_write(request)
    if guard:
        return JSONResponse({"ok": False, "redirect": "/login"}, status_code=401)

    row_id = int(data.get("row_id") or 0)
    name = (data.get("name") or "").strip()

    if not row_id or not name:
        return JSONResponse({"ok": False, "error": "missing row_id/name"}, status_code=400)

    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute("SELECT id, section FROM year_rows WHERE id=?", (row_id,))
        r = cur.fetchone()
        if not r:
            return JSONResponse({"ok": False, "error": "row not found"}, status_code=404)

        # nur Ressourcen editierbar (wie gewünscht)
        if (r["section"] or "") != "res":
            return JSONResponse({"ok": False, "error": "only resources editable"}, status_code=400)

        cur.execute("UPDATE year_rows SET name=? WHERE id=?", (name, row_id))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@app.post("/api/year/create-job")
async def api_year_create_job(request: Request, data: dict = Body(...)):
    guard = require_write(request)
    if guard:
        return JSONResponse({"ok": False, "redirect": "/login"}, status_code=401)

    title = (data.get("title") or "").strip()
    start_date = (data.get("start_date") or "").strip()  # YYYY-MM-DD
    duration_days = int(data.get("duration_days") or 1)
    height_rows = int(data.get("height_rows") or 1)
    section = (data.get("section") or "eb").strip()
    row_index = int(data.get("row_index") or 0)
    color = (data.get("color") or "yellow").strip()
    note = (data.get("note") or "").strip()

    if not title or not start_date:
        return JSONResponse({"ok": False, "error": "missing title/start_date"}, status_code=400)

    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO year_jobs(title,start_date,duration_days,height_rows,section,row_index,color,note)
            VALUES(?,?,?,?,?,?,?,?)
        """, (title, start_date, duration_days, height_rows, section, row_index, color, note or None))
        conn.commit()
        return {"ok": True}
    except sqlite3.IntegrityError as e:
        return JSONResponse({"ok": False, "error": "title must be unique"}, status_code=400)
    finally:
        conn.close()


@app.post("/api/year/delete-job")
async def api_year_delete_job(request: Request, data: dict = Body(...)):
    guard = require_write(request)
    if guard:
        return JSONResponse({"ok": False, "redirect": "/login"}, status_code=401)

    job_id = int(data.get("id") or 0)
    if not job_id:
        return JSONResponse({"ok": False, "error": "missing id"}, status_code=400)

    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute("DELETE FROM year_jobs WHERE id=?", (job_id,))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


# ---------------- zentrale Week-Logik ----------------
def build_week_context(year: int, kw: int, standort: str):
    st = canon_standort(standort)
    conn = get_conn(); cur = conn.cursor()
    try:
        # Plan holen/erzeugen
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

        # Mitarbeiter
        cur.execute("SELECT id,name FROM employees WHERE standort=? ORDER BY id", (st,))
        employees = [{"id": e["id"], "name": e["name"]} for e in cur.fetchall()]
        if employees:
            rows = max(rows, len(employees))

        # Grid
        grid = [[{"text": ""} for _ in range(5)] for _ in range(rows)]
        cur.execute("SELECT row_index,day_index,text FROM week_cells WHERE week_plan_id=?", (plan_id,))
        for r in cur.fetchall():
            ri, di = int(r["row_index"]), int(r["day_index"])
            if 0 <= ri < rows and 0 <= di < 5:
                grid[ri][di]["text"] = r["text"] or ""

        # Kleinbaustellen (standortweit)
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
# ---------------- Login ----------------
@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "error": request.query_params.get("error")
        }
    )

@app.post("/login")
async def login(request: Request):
    form = await request.form()
    username = (form.get("username") or "").strip()
    password = form.get("password") or ""

    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE username=?", (username,))
    user = cur.fetchone()
    conn.close()

    if not user or not verify_password(password, user["password_hash"]):
        return RedirectResponse("/login?error=1", status_code=303)

    request.session["user"] = {
        "id": user["id"],
        "username": user["username"],
        "is_write": int(user["is_write"]),
        "can_view_eb": int(user["can_view_eb"]),
        "can_view_gg": int(user["can_view_gg"]),
    }

    # write/admin → Edit
    if int(user["is_write"]) == 1:
        return RedirectResponse("/week?standort=engelbrechts", status_code=303)

    # viewer → bevorzugter Standort
    if int(user["can_view_eb"]) == 1:
        return RedirectResponse("/view/week?standort=engelbrechts", status_code=303)
    if int(user["can_view_gg"]) == 1:
        return RedirectResponse("/view/week?standort=gross-gerungs", status_code=303)

    return RedirectResponse("/login?error=1", status_code=303)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)

# ---------------- Root/Health/Admin ----------------
@app.get("/")
def root(request: Request):
    if request.session.get("user"):
        return RedirectResponse("/view/week", status_code=303)
    return RedirectResponse("/login", status_code=303)
    # 200 OK + Meta-Refresh → verhindert Render-Healthcheck-Probleme
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

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/favicon.ico")
def favicon():
    return Response(status_code=204)


@app.get("/admin/routes")
def admin_routes(request: Request):
    guard = require_write(request)
    if guard:
        return guard
        
    return {"routes": sorted([r.path for r in app.routes])}


@app.get("/admin/users")
def admin_users(request: Request):
    guard = require_write(request)
    if guard:
        return guard

    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute("SELECT id, username, is_write, can_view_eb, can_view_gg FROM users ORDER BY id")
        return {"users": [dict(r) for r in cur.fetchall()]}
    finally:
        conn.close()

@app.get("/admin/seed-admin")
def seed_admin(request: Request):
    guard = require_write(request)
    if guard:
        return guard

    conn = get_conn(); cur = conn.cursor()
    try:
        # Admin-User: admin / admin (nur initial)
        cur.execute("SELECT id FROM users WHERE username=?", ("admin",))
        if cur.fetchone():
            return {"ok": True, "note": "admin exists"}

        cur.execute(
            "INSERT INTO users(username, password_hash, is_write, can_view_eb, can_view_gg) VALUES(?,?,?,?,?)",
            ("admin", hash_password("admin"), 1, 1, 1)
        )

        conn.commit()
        return {"ok": True, "note": "admin created"}
    finally:
        conn.close()
@app.get("/admin/seed-viewer-eb")
def seed_viewer_eb(request: Request):
    guard = require_write(request)
    if guard:
        return guard
    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute("SELECT id FROM users WHERE username=?", ("viewer_eb",))
        if cur.fetchone():
            return {"ok": True, "note": "viewer_eb exists"}

        cur.execute(
            "INSERT INTO users(username, password_hash, is_write, can_view_eb, can_view_gg) VALUES(?,?,?,?,?)",
            ("viewer_eb", hash_password("viewer_eb!1"), 0, 1, 0)
        )
        conn.commit()
        return {"ok": True, "note": "viewer_eb created (viewer_eb / viewer_eb!1)"}
    finally:
        conn.close()


@app.get("/admin/seed-viewer-gg")
def seed_viewer_gg(request: Request):
    guard = require_write(request)
    if guard:
        return guard

    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute("SELECT id FROM users WHERE username=?", ("viewer_gg",))
        if cur.fetchone():
            return {"ok": True, "note": "viewer_gg exists"}

        cur.execute(
            "INSERT INTO users(username, password_hash, is_write, can_view_eb, can_view_gg) VALUES(?,?,?,?,?)",
            ("viewer_gg", hash_password("viewer_gg!1"), 0, 0, 1)
        )
        conn.commit()
        return {"ok": True, "note": "viewer_gg created (viewer_gg / viewer_gg!1)"}
    finally:
        conn.close()


@app.get("/admin/seed-viewer-both")
def seed_viewer_both(request: Request):
    guard = require_write(request)
    if guard:
        return guard

    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute("SELECT id FROM users WHERE username=?", ("viewer_both",))
        if cur.fetchone():
            return {"ok": True, "note": "viewer_both exists"}

        cur.execute(
            "INSERT INTO users(username, password_hash, is_write, can_view_eb, can_view_gg) VALUES(?,?,?,?,?)",
            ("viewer_both", hash_password("viewer_both!1"), 0, 1, 1)
        )
        conn.commit()
        return {"ok": True, "note": "viewer_both created (viewer_both / viewer_both!1)"}
    finally:
        conn.close()


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
@app.get("/admin/debug-login")
def admin_debug_login(request: Request):
    guard = require_write(request)
    if guard:
        return guard

    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute("SELECT id, username, password_hash, is_write, can_view_eb, can_view_gg FROM users WHERE username=?", ("admin",))
        row = cur.fetchone()
        if not row:
            return {"found": False}
        return {
            "found": True,
            "user": {
                "id": row["id"],
                "username": row["username"],
                "is_write": row["is_write"],
                "can_view_eb": row["can_view_eb"],
                "can_view_gg": row["can_view_gg"],
                "password_hash_prefix": (row["password_hash"] or "")[:12]
            }
        }
    finally:
        conn.close()


# ---------------- Einstellungen: Mitarbeiter (unverändert) ----------------
@app.get("/settings/users", response_class=HTMLResponse)
def settings_users_page(request: Request):
    guard = require_write(request)
    if guard:
        return guard

    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute("SELECT id, username, is_write, can_view_eb, can_view_gg FROM users ORDER BY username")
        users = [dict(r) for r in cur.fetchall()]
        return templates.TemplateResponse(
            "settings_users.html",
            {"request": request, "users": users}
        )
    finally:
        conn.close()
@app.post("/settings/users/create")
async def settings_users_create(request: Request):
    guard = require_write(request)
    if guard:
        return guard

    form = await request.form()
    username = (form.get("username") or "").strip()
    password = form.get("password") or ""

    is_write = 1 if form.get("is_write") else 0
    can_view_eb = 1 if form.get("can_view_eb") else 0
    can_view_gg = 1 if form.get("can_view_gg") else 0

    if not username:
        return RedirectResponse("/settings/users?error=1", status_code=303)

    if not password_ok(password):
        return RedirectResponse("/settings/users?pw=bad", status_code=303)

    # write darf immer beide Views
    if is_write:
        can_view_eb, can_view_gg = 1, 1

    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute("SELECT id FROM users WHERE username=?", (username,))
        if cur.fetchone():
            return RedirectResponse("/settings/users?exists=1", status_code=303)

        cur.execute(
            "INSERT INTO users(username, password_hash, is_write, can_view_eb, can_view_gg) VALUES(?,?,?,?,?)",
            (username, hash_password(password), is_write, can_view_eb, can_view_gg)
        )
        conn.commit()
        return RedirectResponse("/settings/users?created=1", status_code=303)
    finally:
        conn.close()
@app.post("/settings/users/update")
async def settings_users_update(request: Request):
    guard = require_write(request)
    if guard:
        return guard

    form = await request.form()
    user_id = int(form.get("user_id") or "0")

    # Checkboxen
    is_write = 1 if form.get("is_write") else 0
    can_view_eb = 1 if form.get("can_view_eb") else 0
    can_view_gg = 1 if form.get("can_view_gg") else 0

    # write darf immer beide Views
    if is_write:
        can_view_eb, can_view_gg = 1, 1

    # Optional: Passwort ändern
    new_pw = (form.get("new_password") or "").strip()
    new_pw2 = (form.get("new_password2") or "").strip()

    # Safety: nicht selbst aussperren (wenn du dich selbst editierst)
    me = request.session.get("user") or {}
    if me.get("id") == user_id and is_write == 0:
        return RedirectResponse("/settings/users?self_lock=1", status_code=303)

    if new_pw or new_pw2:
        if new_pw != new_pw2:
            return RedirectResponse("/settings/users?pw=mismatch", status_code=303)
        if not password_ok(new_pw):
            return RedirectResponse("/settings/users?pw=bad", status_code=303)

    conn = get_conn(); cur = conn.cursor()
    try:
        # existiert der User?
        cur.execute("SELECT id FROM users WHERE id=?", (user_id,))
        if not cur.fetchone():
            return RedirectResponse("/settings/users?missing=1", status_code=303)

        if new_pw:
            cur.execute(
                "UPDATE users SET is_write=?, can_view_eb=?, can_view_gg=?, password_hash=? WHERE id=?",
                (is_write, can_view_eb, can_view_gg, hash_password(new_pw), user_id)
            )
        else:
            cur.execute(
                "UPDATE users SET is_write=?, can_view_eb=?, can_view_gg=? WHERE id=?",
                (is_write, can_view_eb, can_view_gg, user_id)
            )

        conn.commit()
    finally:
        conn.close()

    # Session aktualisieren, falls du dich selbst geändert hast (zB Views)
    if me.get("id") == user_id:
        me["is_write"] = is_write
        me["can_view_eb"] = can_view_eb
        me["can_view_gg"] = can_view_gg
        request.session["user"] = me

    return RedirectResponse("/settings/users?updated=1", status_code=303)


@app.post("/settings/users/delete")
async def settings_users_delete(request: Request):
    guard = require_write(request)
    if guard:
        return guard

    form = await request.form()
    user_id = int(form.get("user_id") or "0")

    # Safety: nicht sich selbst löschen
    me = request.session.get("user") or {}
    if me.get("id") == user_id:
        return RedirectResponse("/settings/users?self=1", status_code=303)

    conn = get_conn(); cur = conn.cursor()
    try:
        if user_id:
            cur.execute("DELETE FROM users WHERE id=?", (user_id,))
            conn.commit()
        return RedirectResponse("/settings/users?deleted=1", status_code=303)
    finally:
        conn.close()


@app.get("/settings/employees", response_class=HTMLResponse)
def settings_employees_page(request: Request, standort: str = "engelbrechts"):
    guard = require_write(request)
    if guard:
        return guard
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
        return HTMLResponse("<h1>Mitarbeiter</h1><p>Template fehlt.</p>", status_code=200)
    finally:
        conn.close()
@app.post("/settings/employees", response_class=HTMLResponse)
async def settings_employees_save(request: Request):
    guard = require_write(request)
    if guard:
        return guard

    form = await request.form()
    new_list = []

    try:
        if hasattr(form, "getlist"):
            for v in form.getlist("emp_name_new[]"):
                t = (v or "").strip()
                if t:
                    new_list.append(t)
        else:
            for k, v in form.multi_items():
                if k == "emp_name_new[]":
                    t = (v or "").strip()
                    if t:
                        new_list.append(t)
    except Exception:
        pass

    st = resolve_standort(
        request,
        form.get("standort"),
        request.query_params.get("standort")
    )

    conn = get_conn(); cur = conn.cursor()
    try:
        for n in new_list:
            cur.execute(
                "INSERT INTO employees(name, standort) VALUES(?, ?)",
                (n, st)
            )
        conn.commit()
        return RedirectResponse(
            f"/settings/employees?standort={st}&saved=1",
            status_code=303
        )
    finally:
        conn.close()

                 
@app.post("/settings/employees/delete")
async def settings_employees_delete(request: Request):
    guard = require_write(request)
    if guard:
        return guard
    form = await request.form()
    emp_id = int(((form.get("emp_id") or "0") or 0))
    st = form.get("standort") or request.query_params.get("standort") or "engelbrechts"
    conn = get_conn(); cur = conn.cursor()
    try:
        if emp_id:
            cur.execute("DELETE FROM employees WHERE id=?", (emp_id,))
            conn.commit()
        return RedirectResponse(url=f"/settings/employees?standort={canon_standort(st)}", status_code=303)
    finally:
        conn.close()

# ---------------- WEEK – Edit  (Öffnet OHNE Parameter immer die aktuelle ISO-KW/Jahr) ----------------
from datetime import date as _date

@app.get("/week", response_class=HTMLResponse)
def week(
    request: Request,
    kw: int | None = Query(None),
    year: int | None = Query(None),
    standort: str = "engelbrechts"
):
    guard = require_write(request)
    if guard:
        return guard

    if year is None or kw is None:
        iso = _date.today().isocalendar()  # (year, week, weekday)
        if year is None:
            year = int(iso[0])
        if kw is None:
            kw = int(iso[1])

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

# ---------------- WEEK API (unverändert) ----------------
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

# ---------------- VIEW (Read-only) – Freitag-12-Regel ----------------
@app.get("/view/week", response_class=HTMLResponse)
def view_week(
  request: Request,
  year: int | None = None,
  kw: int | None = None,
  standort: str = "engelbrechts"
):
    if not request.session.get("user"):
        return RedirectResponse("/login", status_code=303)
    user = request.session.get("user") or {}

    # write sieht alles
    if not user.get("is_write"):
        st = canon_standort(standort)
        if st == "engelbrechts" and not user.get("can_view_eb"):
            # wenn er GG darf, dorthin
            if user.get("can_view_gg"):
                return RedirectResponse("/view/week?standort=gross-gerungs", status_code=303)
            return RedirectResponse("/login?error=1", status_code=303)

        if st == "gross-gerungs" and not user.get("can_view_gg"):
            if user.get("can_view_eb"):
                return RedirectResponse("/view/week?standort=engelbrechts", status_code=303)
            return RedirectResponse("/login?error=1", status_code=303)

    try:
        if year is None or kw is None:
            year, kw = auto_view_target()
        else:
            year, kw = int(year), int(kw)
        # --- Navigation: nur aktuelle + 1 Woche erlauben ---
        now = datetime.now()
        cur_year, cur_kw = auto_view_target(now)

        # ISO-Wochen sauber vergleichen
        max_year, max_kw = cur_year, cur_kw + 1
        if max_kw > 53:
            max_kw = 1
            max_year += 1

        allow_next = (
            year < max_year
            or (year == max_year and kw <= max_kw)
        )

        ctx = build_week_context(year, kw, standort)
        return templates.TemplateResponse(
            "week_view.html",
            {
                "request": request,
                "year": year,
                "kw": kw,
                "allow_next": allow_next,
                "standort": ctx["standort"],
                "grid": ctx["grid"],
                "employees": ctx["employees"],
                "four_day_week": ctx["four_day_week"],
                "days": ctx["days"],
            }
        )
    except Exception:
        return HTMLResponse(f"<pre>{traceback.format_exc()}</pre>", status_code=500)

# ---------------- Kleinbaustellen – exakt nach deiner Word-Logik ----------------
@app.post("/api/klein/set")
async def klein_set(data: dict = Body(...)):
    """
    Erwartet JSON:
      { "standort": str, "row_index": int, "text": str }
    Upsert in global_small_jobs (UNIQUE (standort, row_index)).
    """
    try:
        standort = canon_standort(data.get("standort") or "engelbrechts")
        row_index = int(data.get("row_index") or 0)
        text = (data.get("text") or "").strip()

        conn = get_conn(); cur = conn.cursor()
        cur.execute("""
            INSERT INTO global_small_jobs(standort,row_index,text)
            VALUES(?,?,?)
            ON CONFLICT(standort,row_index) DO UPDATE SET text=excluded.text
        """, (standort, row_index, text))
        conn.commit(); conn.close()
        return {"ok": True}
    except Exception:
        return JSONResponse({"ok": False, "error": traceback.format_exc()}, status_code=500)
