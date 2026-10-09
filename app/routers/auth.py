from fastapi import APIRouter, Request, Depends, HTTPException, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User, Config
from app.auth import hash_password, verify_password, create_access_token, get_current_user
from app.schemas import UserCreate, UserLogin

router = APIRouter()


def ensure_config(db: Session, user: User) -> Config:
    cfg = db.query(Config).filter(Config.user_id == user.id).first()
    if not cfg:
        cfg = Config(user_id=user.id)
        db.add(cfg)
        db.commit()
        db.refresh(cfg)
    return cfg


@router.post("/register")
def register(payload: UserCreate, response: Response, db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == payload.username).first():
        raise HTTPException(status_code=400, detail="Username already exists")
    user = User(username=payload.username, password_hash=hash_password(payload.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    ensure_config(db, user)
    token = create_access_token({"sub": str(user.id)})
    response.set_cookie("session", token, httponly=True, samesite="lax")
    return {"ok": True, "username": user.username}


@router.post("/login")
def login(payload: UserLogin, response: Response, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == payload.username).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_access_token({"sub": str(user.id)})
    response.set_cookie("session", token, httponly=True, samesite="lax")
    return {"ok": True, "username": user.username}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie("session")
    return {"ok": True}
