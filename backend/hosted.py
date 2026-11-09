"""Single-user HTTPS deployment: serve the built UI and existing API together."""
import os
import secrets
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse
from fastapi.security import HTTPBasic
from fastapi.staticfiles import StaticFiles


FRONTEND_DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"


def create_app():
    password = os.environ.get("JOURNAL_PASSWORD", "")
    if not password.strip() or not password.isascii():
        raise RuntimeError("Set JOURNAL_PASSWORD to a nonempty ASCII password in Render.")
    db_path = Path(os.environ.get("JOURNAL_DB_PATH", ""))
    if not db_path.is_absolute() or not db_path.parent.is_dir():
        raise RuntimeError("JOURNAL_DB_PATH must point to a file on the mounted persistent disk.")
    if not (FRONTEND_DIST / "index.html").is_file():
        raise RuntimeError("The frontend production build is missing. Run npm run build in frontend.")

    from main import app as api, lifespan

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    auth = HTTPBasic(auto_error=False, realm="Forex Journal")

    @app.middleware("http")
    async def require_login(request: Request, call_next):
        if request.url.path == "/healthz" and request.method in {"GET", "HEAD"}:
            return await call_next(request)
        try:
            credentials = await auth(request)
        except HTTPException:
            credentials = None
        if (credentials is None or credentials.username != "journal"
                or not secrets.compare_digest(credentials.password, password)):
            return PlainTextResponse("Sign in to your journal.", status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="Forex Journal"', "Cache-Control": "no-store"})
        # Browsers may reuse Basic credentials across requests. Only our HTTPS
        # page should be able to initiate writes using those credentials.
        origin = request.headers.get("origin")
        if request.method not in {"GET", "HEAD", "OPTIONS"} and (
                request.headers.get("sec-fetch-site") == "cross-site"
                or (origin is not None and origin != f"https://{request.url.netloc}")):
            return PlainTextResponse("This action must come from the journal page.", status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    @app.api_route("/healthz", methods=["GET", "HEAD"])
    def health():
        return PlainTextResponse("ok")

    app.mount("/api", api)
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
    return app
