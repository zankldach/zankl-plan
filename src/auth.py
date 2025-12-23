from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse
from passlib.hash import bcrypt
from .db import get_conn

router = APIRouter()

def get_current_user(request: Request):
    return request.session.get("user")

@router.get("/login")
def login_page(request: Request):
    from fastapi.templating import Jinja2Templates
    templates = Jinja2Templates(directory="src/templates")
    return templates.TemplateResponse("login.html", {"request": request})

@router.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...)):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE email=?", (email,))
    user = c.fetchone()
    conn.close()
    if not user or not bcrypt.verify(password, user["password_hash"]):
        return RedirectResponse("/login?error=1", status_code=303)
    request.session["user"] = {
        "id": user["id"],
        "email": user["email"],
        "name": user["name"],
        "role": user["role"],
        "viewer_standort_id": user["viewer_standort_id"]
    }
    return RedirectResponse("/", status_code=303)

@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
