"""FastAPI routes owned by Jinka. In api.py:  app.include_router(hound.watch.routes.router)"""

from fastapi import APIRouter, HTTPException, Query, Request

from .. import chain
from .check import check

router = APIRouter()


def _live_evidence(result) -> bool:
    """True when the hold comes from a real victim's case (live file or intake): its path names the
    victim's wallet and tx hash."""
    from hound import api  # lazy: api imports this module at startup
    ids = (result.get("evidence") or {}).get("case_ids") or []
    return any(cid in api.LIVE_CASES or str(cid).startswith("intake-") for cid in ids)


@router.get("/check")
def get_check(request: Request, chain_name: str = Query("ethereum", alias="chain"), address: str = Query(...)):
    try:
        result = check(chain_name, address)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except chain.CacheMiss:
        raise HTTPException(status_code=503, detail="not checked: data not cached (offline mode)")
    except chain.ChainAPIError:
        raise HTTPException(status_code=502, detail="chain data unavailable")
    from hound import api
    if _live_evidence(result) and not api._is_local(request):
        result = {**result, "evidence": api._redact_live(result["evidence"]),
                  "reasons": api._redact_live(result.get("reasons") or [])}
    return result
