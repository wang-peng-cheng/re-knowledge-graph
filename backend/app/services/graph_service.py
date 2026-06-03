from __future__ import annotations

from datetime import datetime

from app.domain.models import ExtractionResult, GraphWriteRequest, TemporalGraphSnapshot
from app.repositories.graph_repository import TemporalGraphRepository


class TemporalGraphService:
    """Application service for persisting and querying time-aware graph knowledge."""

    def __init__(self, repository: TemporalGraphRepository) -> None:
        """Bind the service to the graph repository implementation."""

        self.repository = repository

    async def build_write_request(self, result: ExtractionResult) -> GraphWriteRequest:
        """Transform an extraction result into a graph write payload."""

        raise NotImplementedError

    async def write_extraction_result(self, result: ExtractionResult) -> None:
        """Persist extracted entities and relations into the temporal graph store."""

        raise NotImplementedError

    async def load_snapshot(
        self,
        window_start: datetime | None,
        window_end: datetime | None,
        entity_ids: list[str] | None = None,
    ) -> TemporalGraphSnapshot:
        """Load a graph snapshot aligned to a temporal window and optional entity scope."""

        raise NotImplementedError
