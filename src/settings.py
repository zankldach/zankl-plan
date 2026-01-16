from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates
from pathlib import Path
import sqlite3

router = APIRouter()

BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent
DB_PATH = BASE_DIR / "zankl.db"

templates = Jinja2Templates(directory=str(ROOT_DIR / "templates"))

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

@router.get("/settings/employees")
def settings_employees(request: Request):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, name, standort FROM employees ORDER BY standort, name")
    employees = cur.fetchall()
    conn.close()

    return templates.TemplateResponse(
        "settings_employees.html",
        {
            "request": request,
            "employees": employees
        }
    )
