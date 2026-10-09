"""API endpoints for the historical data paper-mode simulator."""
from fastapi import APIRouter, Request, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Config
from app.routers.auth import ensure_config
from app.auth import require_user
from app.historical_sim import start_sim, stop_sim, get_sim_status

router = APIRouter(prefix="/api/sim")


def get_cfg(db: Session, request: Request) -> Config:
    user = require_user(request, db)
    return ensure_config(db, user)


@router.post("/start")
def sim_start(request: Request, db: Session = Depends(get_db)):
    """Start historical data paper mode — fetches real market data and replays it."""
    get_cfg(db, request)  # auth check
    result = start_sim()
    return result


@router.post("/stop")
def sim_stop(request: Request, db: Session = Depends(get_db)):
    """Stop the historical data simulation."""
    get_cfg(db, request)
    result = stop_sim()
    return result


@router.get("/status")
def sim_status(request: Request, db: Session = Depends(get_db)):
    """Get current simulation status."""
    get_cfg(db, request)
    return get_sim_status()
