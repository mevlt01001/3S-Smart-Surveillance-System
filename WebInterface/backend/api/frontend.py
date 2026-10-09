"""Serves the web interface."""

import os

from fastapi import APIRouter, FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

FRONTEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend"))

router = APIRouter(include_in_schema=False)

# Before the interface moved to /ui it was served from /static without cache headers, so a
# browser can keep such a page (and its scripts) for a day or two. A leftover page that asks
# for one of its old scripts receives this stand-in instead: it satisfies the names the old
# page imports and reloads once, which brings up the current interface.
_LEGACY_EXPORTS = (
    "addCamera classifyScore createRule deleteCamera deleteRule destroyLiveModule escapeHTML fetchCameras "
    "fetchInterfaces fetchRules fetchSystemStats getSnapshotUrl initEventsModule initHomeModule initLiveModule "
    "initRulesModule initSettingsModule isConfirmSkipped pauseEventsModule pauseHomeModule reconnectCamera "
    "renderJournal resetConfirmPreference resumeHomeModule showConfirmDialog showToast triggerOnvifScan "
    "updateCamera updateRule updateSidebarAlertBadge"
).split()

_LEGACY_SCRIPT = (
    "// This address belongs to a previous version of the interface.\n"
    "const noop = () => {};\n"
    + "".join(f"export const {name} = noop;\n" for name in _LEGACY_EXPORTS)
    + """try {
  const key = "aegis-ui-refreshed";
  if (Date.now() - Number(sessionStorage.getItem(key) || 0) > 60000) {
    sessionStorage.setItem(key, String(Date.now()));
    location.reload();
  }
} catch (_) { /* storage blocked: stay on the page rather than risk a reload loop */ }
"""
)


@router.api_route("/", methods=["GET", "HEAD"])
async def index():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


@router.api_route("/static/js/{filename}", methods=["GET", "HEAD"])
async def legacy_script(filename: str):
    if not filename.endswith(".js"):
        raise HTTPException(status_code=404, detail="Not Found")
    return Response(content=_LEGACY_SCRIPT, media_type="text/javascript", headers={"Cache-Control": "no-store"})


def mount_frontend(app: FastAPI) -> None:
    """Registers the page and its assets; every asset is revalidated by the browser on each load."""
    app.include_router(router)
    app.mount("/ui", StaticFiles(directory=FRONTEND_DIR), name="ui")

    @app.middleware("http")
    async def revalidate_assets(request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path == "/" or path.startswith("/ui/"):
            response.headers.setdefault("Cache-Control", "no-cache")
        return response
