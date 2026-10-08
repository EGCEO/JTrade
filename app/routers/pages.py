from fastapi import APIRouter, Request, Depends
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app.auth import get_current_user

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


PAGES = {
    "dashboard": "dashboard.html",
    "wallet": "wallet.html",
    "capital": "capital.html",
    "risk": "risk.html",
    "performance": "performance.html",
    "analytics": "analytics.html",
    "net-profit": "net_profit.html",
    "bots": "bots.html",
    "logs": "logs.html",
    "history": "history.html",
    "compounding": "compounding.html",
    "notifications": "notifications.html",
    "onboarding": "onboarding.html",
    "security": "security.html",
    "settings": "settings.html",
    "integration": "integration.html",
}


@router.get("/")
def index(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    return RedirectResponse("/dashboard", status_code=302)


@router.get("/login")
def login_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if user:
        return RedirectResponse("/dashboard", status_code=302)
    return templates.TemplateResponse(request, "login.html", {"request": request})


@router.get("/{page}")
def render_page(page: str, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    if page not in PAGES:
        return RedirectResponse("/dashboard", status_code=302)
    return templates.TemplateResponse(request, PAGES[page], {
        "request": request,
        "username": user.username,
        "active_page": page,
    })
