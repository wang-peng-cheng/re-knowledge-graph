from __future__ import annotations

from app.domain.models import DocumentIngestRequest, RawDocumentRecord
from app.repositories.mysql_repository import MySQLDocumentRepository


class DocumentIngestionService:
    """Application service responsible for source intake and raw-record creation."""

    def __init__(self, repository: MySQLDocumentRepository) -> None:
        """Bind the service to the relational repository used for raw data persistence."""

        self.repository = repository

    async def ingest(self, request: DocumentIngestRequest) -> RawDocumentRecord:
        """Create a raw document record from a user-provided URL or uploaded file."""

        raise NotImplementedError

    async def ingest_url(self, source_url: str, requested_by: str | None = None) -> RawDocumentRecord:
        """Resolve and persist a URL-based source as a raw document record."""

        raise NotImplementedError

    async def ingest_file(
        self,
        filename: str,
        media_type: str,
        content_bytes: bytes,
        requested_by: str | None = None,
    ) -> RawDocumentRecord:
        """Persist an uploaded file source as a raw document record."""

        raise NotImplementedError
