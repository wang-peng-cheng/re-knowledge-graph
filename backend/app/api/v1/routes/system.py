from __future__ import annotations

from fastapi import APIRouter


router = APIRouter(prefix="/system", tags=["system"])


@router.get("/health")
async def health_check() -> dict[str, str]:
    """Expose a minimal health endpoint for runtime and deployment checks."""

    raise NotImplementedError
