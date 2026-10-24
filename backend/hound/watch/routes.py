"""FastAPI routes owned by Jinka. In api.py:  app.include_router(hound.watch.routes.router)"""

from fastapi import APIRouter, HTTPException, Query

from .. import chain
from .check import check

router = APIRouter()


@router.get("/check")
def get_check(chain_name: str = Query("ethereum", alias="chain"), address: str = Query(...)):
    try:
        return check(chain_name, address)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except chain.ChainAPIError as e:
        raise HTTPException(status_code=502, detail=f"chain data unavailable: {e}")
