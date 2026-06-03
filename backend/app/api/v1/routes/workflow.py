from __future__ import annotations

from fastapi import APIRouter

from app.domain.models import DocumentIngestRequest, ExtractionResult, ReasoningRequest, ReasoningResult


router = APIRouter(prefix="/workflow", tags=["workflow"])


@router.post("/ingest-and-extract", response_model=ExtractionResult)
async def ingest_and_extract(request: DocumentIngestRequest) -> ExtractionResult:
    """Create an end-to-end extraction task from a URL or uploaded document source."""

    raise NotImplementedError


@router.post("/reason", response_model=ReasoningResult)
async def run_reasoning(request: ReasoningRequest) -> ReasoningResult:
    """Trigger temporal graph reasoning and return future relation hypotheses."""

    raise NotImplementedError
