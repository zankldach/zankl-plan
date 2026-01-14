# src/main.py
from fastapi import FastAPI, Request, Body, Query, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from datetime import date, timedelta, datetime
from urllib.parse import urlparse, parse_qs
import sqlite3
import logging, traceback

app = FastAPI(title="Zankl-Plan MVP")

# =========================
# BASE DIRS & TEMPLATES
# =========================
BASE_DIR = Path(__file__).resolve().parent           # src/
ROOT_DIR = BASE_DIR.parent                           # project root
DB_PATH  = BASE_DIR / "zankl.db"

templates = Jinja2Templates(directory=str(ROOT_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(ROOT_DIR / "static")), name="static")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("zankl-plan")

STANDORTE = ["engelbrechts", "gross-gerungs"]

# =========================
# DB HELPERS
# =========================
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

# =========================
# STANDORT HELPERS
# =========================
def canon_standort(s: str | None) -> str:
    s = (s or "").strip()
    if not s:
        return "engelbrechts"
    s_low = s.lower().replace("ß", "ss").replace("_", "-").strip()
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

# =========================
# DATE / KW HELPERS
# =========================
def build_days(year: int, kw: int):
    kw = max(1, min(kw, 53))
    start = date.fromisocalendar(year, kw, 1)
    labels = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag"]
    return [{"label": labels[i], "date": (start + timedelta(days=i)).strftime("%d.%m.%Y")} for i in range(5)]

def get_year_kw(year: int | None, kw: int | None):
    today = date.today()
    if year is None or kw is None:
        iso = today.isocalendar()
        return iso[0] if year is None else year, iso[1] if kw is None else kw
    return year, kw

# =========================
# ROOT & HEALTH
# =========================
@app.get("/")
def root():
    return RedirectResponse(url="/week")

@app.get("/health")
def health():
    return {"status": "ok"}

# =========================
# WEEK EDITABLE
# =========================
@app.get("/week", response_class=HTMLResponse)
def week(request: Request, kw: int = None, year: int = None, standort: str = "engelbrechts"):
    year, kw = get_year_kw(year, kw)
    standort = canon_standort(standort)

    conn = get_conn(); cur = conn.cursor()
    try:
        # Week plan
        cur.execute("SELECT id,row_count,four_day_week FROM week_plans WHERE year=? AND kw=? AND standort=?", (year, kw, standort))
        plan = cur.fetchone()
        if not plan:
            cur.execute("INSERT INTO week_plans(year,kw,standort,row_count,four_day_week) VALUES(?,?,?,?,1)", (year, kw, standort, 5))
            conn.commit()
            plan_id, rows, four_day_week = cur.lastrowid, 5, 1
        else:
            plan_id, rows, four_day_week = plan["id"], plan["row_count"], plan["four_day_week"]

        # Employees
        cur.execute("SELECT id,name FROM employees WHERE standort=? ORDER BY id", (standort,))
        employees = [{"id": r["id"], "name": r["name"]} for r in cur.fetchall()]
        if employees:
            rows = max(rows, len(employees))

        # Week cells
        grid = [[{"text": ""} for _ in range(5)] for _ in range(rows)]
        cur.execute("SELECT row_index,day_index,text FROM week_cells WHERE week_plan_id=?", (plan_id,))
        for r in cur.fetchall():
            if 0 <= r["row_index"] < rows and 0 <= r["day_index"] < 5:
                grid[r["row_index"]][r["day_index"]]["text"] = r["text"] or ""

        # Small jobs
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
                "standorte": STANDORTE,
            }
        )
    finally:
        conn.close()

# =========================
# WEEK VIEW ONLY
# =========================
def load_week_plan(year, kw, standort):
    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute("SELECT * FROM week_plans WHERE year=? AND kw=? AND standort=?", (year, kw, standort))
        return cur.fetchone()
    finally:
        conn.close()

def load_week_cells(plan_id):
    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute("SELECT row_index,day_index,text FROM week_cells WHERE week_plan_id=?", (plan_id,))
        data = cur.fetchall()
        cells = {}
        for r in data:
            cells.setdefault(r["row_index"], {})[r["day_index"]] = r["text"] or ""
        return cells
    finally:
        conn.close()

def load_employees_by_standort(standort):
    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute("SELECT id,name FROM employees WHERE standort=? ORDER BY id", (standort,))
        return [{"id": r["id"], "name": r["name"]} for r in cur.fetchall()]
    finally:
        conn.close()

@app.get("/view/week", response_class=HTMLResponse)
def view_week(request: Request, year: int | None = None, kw: int | None = None, standort: str = "engelbrechts"):
    year, kw = get_year_kw(year, kw)
    standort = canon_standort(standort)

    plan = load_week_plan(year, kw, standort)
    cells = load_week_cells(plan["id"]) if plan else {}
    employees = load_employees_by_standort(standort)

    return templates.TemplateResponse(
        "week_view.html",
        {
            "request": request,
            "year": year,
            "kw": kw,
            "standort": standort,
            "plan": plan,
            "cells": cells,
            "employees": employees,
            "four_day_week": plan["four_day_week"] if plan else False,
        }
    )

# =========================
# WEEK CELL API (editable)
# =========================
@app.post("/api/week/set-cell")
async def set_cell(request: Request, data: dict = Body(...), standort_q: str | None = Query(None, alias="standort")):
    conn = get_conn(); cur = conn.cursor()
    try:
        year, kw = int(data.get("year")), int(data.get("kw"))
        standort = resolve_standort(request, data.get("standort"), standort_q)
        row, day = int(data.get("row")), int(data.get("day"))
        val = data.get("value") or ""

        cur.execute("SELECT id,four_day_week FROM week_plans WHERE year=? AND kw=? AND standort=?", (year, kw, standort))
        plan = cur.fetchone()
        if not plan: return {"ok": False, "error": "Plan not found"}

        if plan["four_day_week"] and day == 4:
            return {"ok": True, "skipped": True}

        cur.execute("""
            INSERT INTO week_cells(week_plan_id,row_index,day_index,text)
            VALUES(?,?,?,?)
            ON CONFLICT(week_plan_id,row_index,day_index) DO UPDATE SET text=excluded.text
        """, (plan["id"], row, day, val))
        conn.commit()
        return {"ok": True, "standort": standort}
    finally:
        conn.close()
