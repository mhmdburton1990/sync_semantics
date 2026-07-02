"""Mount the built React frontend (or a friendly stub if missing).

SPA routing: the React app uses client-side routes like /target, /preview,
/apply, /history. The browser hits those URLs directly on reload or via
links. Vanilla StaticFiles returns 404 for those because no matching file
exists on disk. We mount the asset directory at /assets and add a catch-all
route that serves index.html for everything else — that's the standard
React-SPA + FastAPI pattern.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

__all__ = ["mount_frontend"]


_STUB = """<!doctype html><html><body>
<h1>databricks-to-pbi backend running</h1>
<p>Frontend bundle not found. Build it:</p>
<pre>cd frontend && pnpm install && pnpm build</pre>
<p>Or set <code>DBX2PBI_FRONTEND_DIST</code> to a folder containing index.html.</p>
</body></html>"""


def mount_frontend(app: FastAPI) -> None:
    raw = os.environ.get("DBX2PBI_FRONTEND_DIST") or "frontend/dist"
    dist = Path(raw)
    if not (dist.exists() and (dist / "index.html").exists()):

        @app.get("/", response_class=HTMLResponse)
        def _stub() -> str:
            return _STUB

        return

    index_path = dist / "index.html"

    # Serve hashed JS/CSS bundles under /assets/.
    assets_dir = dist / "assets"
    if assets_dir.exists():
        app.mount(
            "/assets",
            StaticFiles(directory=str(assets_dir)),
            name="assets",
        )

    # Any other top-level static file in dist (favicon, robots.txt, etc.).
    @app.get("/{filename}")
    def _root_static(filename: str) -> FileResponse:
        candidate = dist / filename
        if candidate.is_file():
            return FileResponse(candidate)
        # Fall through to SPA catch-all
        return FileResponse(index_path, media_type="text/html")

    # SPA catch-all: any unknown path (incl. /target, /preview, /apply, /history)
    # returns index.html so client-side routing can take over. Unknown /api/*
    # and /metrics paths must still 404 so callers get a proper error, not HTML.
    @app.get("/")
    @app.get("/{full_path:path}")
    def _spa(full_path: str = "") -> FileResponse:
        if full_path.startswith("api/") or full_path == "api" or full_path == "metrics":
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Not Found")
        return FileResponse(index_path, media_type="text/html")
