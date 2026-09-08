"""Translate Mem0 exceptions into stable HTTP semantics."""

from fastapi import HTTPException
from mem0.exceptions import MemoryError as Mem0Error
from mem0.exceptions import MemoryNotFoundError, ValidationError


def to_http_exception(exc: Exception) -> HTTPException:
    """Keep client errors in 4xx and reserve 5xx for server failures."""
    if isinstance(exc, HTTPException):
        return exc

    message = str(exc)
    if isinstance(exc, MemoryNotFoundError) or (isinstance(exc, ValueError) and "not found" in message.lower()):
        return HTTPException(status_code=404, detail=message)
    if isinstance(exc, (ValidationError, ValueError)):
        return HTTPException(status_code=400, detail=message)
    if isinstance(exc, Mem0Error):
        return HTTPException(status_code=502, detail=message)
    return HTTPException(status_code=500, detail="Internal server error")
