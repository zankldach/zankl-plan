from fastapi import FastAPI, Request, Body, Query, Depends
from fastapi.responses import HTMLResponse, JSONResponse, Response, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
import sqlite3
from pathlib import Path
from datetime import date, timedelta, datetime
import traceback
from urllib.parse import urlparse, parse_qs
import hashlib
import hmac

app = FastAPI(title="Zankl-Plan MVP")
app.add_middleware(SessionMiddleware, secret_key="CHANGE_ME_SECRET")

BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent
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

    # 🔐 Users
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          username TEXT UNIQUE,
          password_hash TEXT,
          role TEXT CHECK(role IN ('admin','viewer')),
          standort TEXT
        )
    """)

    conn.commit(); conn.close()

init_db()

# ---------------- Passwort (ohne externe Libs) ----------------
def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()

def verify_password(password: str, stored_hash: str) -> bool:
    return hmac.compare_digest(
        hashlib.sha256(password.encode("utf-8")).hexdigest(),
        stored_hash
    )

# ---------------- Auth Helper ----------------
def get_user(request: Request):
    return request.session.get("user")

def require_login(request: Request):
    user = get_user(request)
    if not user:
        raise RedirectResponse("/login", status_code=303)
    return user

def require_admin(user=Depends(require_login)):
    if user["role"] != "admin":
        raise RedirectResponse("/view/week", status_code=303)
    return user

# ---------------- Login ----------------
@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
async def login(request: Request):
    form = await request.form()
    username = (form.get("username") or "").strip()
    password = form.get("password") or ""

    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE username=?", (username,))
    u = cur.fetchone()
    conn.close()

    if not u or not verify_password(password, u["password_hash"]):
        return RedirectResponse("/login?error=1", status_code=303)

    request.session["user"] = {
        "id": u["id"],
        "username": u["username"],
        "role": u["role"],
        "standort": u["standort"],
    }
    return RedirectResponse("/week", status_code=303)

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)

# ---------------- Helpers ----------------
def build_days(year: int, kw: int):
    kw = max(1, min(kw, 53))
    start = date.fromisocalendar(year, kw, 1)
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
    ref = request.headers.get("referer")
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
    now = now or datetime.now()
    y, w, wd = now.isocalendar()
    if (wd == 5 and now.hour >= 12) or (wd >= 6):
        monday = date.fromisocalendar(y, w, 1)
        next_monday = monday + timedelta(days=7)
        y2, w2 = next_monday.isocalendar()[:2]
        return int(y2), int(w2)
    return int(y), int(w)

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

# ---------------- Root ----------------
@app.get("/")
def root():
    return RedirectResponse("/view/week", status_code=303)

# ---------------- WEEK – Edit (ADMIN) ----------------
@app.get("/week", response_class=HTMLResponse)
def week(
    request: Request,
    kw: int | None = Query(None),
    year: int | None = Query(None),
    standort: str = "engelbrechts",
    user=Depends(require_admin)
):
    if year is None or kw is None:
        iso = date.today().isocalendar()
        year = year or int(iso[0])
        kw = kw or int(iso[1])

    standort = canon_standort(standort)
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

# ---------------- VIEW – Read-only ----------------
@app.get("/view/week", response_class=HTMLResponse)
def view_week(
    request: Request,
    year: int | None = None,
    kw: int | None = None,
    standort: str = "engelbrechts",
    user=Depends(require_login)
):
    if user["role"] == "viewer":
        standort = user["standort"]
        cur_y, cur_kw = auto_view_target()
        if year is None or kw is None:
            year, kw = cur_y, cur_kw
        elif (int(year), int(kw)) > (cur_y, cur_kw + 1):
            kw = cur_kw + 1

    if year is None or kw is None:
        year, kw = auto_view_target()

    ctx = build_week_context(int(year), int(kw), standort)
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

# ---------------- APIs (unverändert) ----------------
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
        return {"ok": True}
    finally:
        conn.close()
