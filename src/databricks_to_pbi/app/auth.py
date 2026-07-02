"""OBO (on-behalf-of) auth middleware for Databricks Apps."""

from __future__ import annotations

from fastapi import Header, HTTPException, status

__all__ = ["OBO_HEADER", "current_obo_token"]


OBO_HEADER = "X-Forwarded-Access-Token"


async def current_obo_token(
    x_forwarded_access_token: str | None = Header(None, alias=OBO_HEADER),
) -> str:
    """Return the OBO access token, or 401 if missing/empty.

    Databricks Apps inject this header on every authenticated request. In local
    dev (no App harness) you set it manually via the API client.
    """
    if not x_forwarded_access_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "missing_obo_token",
                "message": f"{OBO_HEADER} header is required",
                "suggestion": (
                    "Deploy via Databricks Apps (auto-injected) or set the "
                    "header manually for local dev."
                ),
            },
        )
    return x_forwarded_access_token
