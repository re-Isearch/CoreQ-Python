"""Optional local web interface; native work is owned by spawned processes."""

from contextlib import asynccontextmanager
from pathlib import Path
import argparse
import asyncio
import json
import os
import re
import secrets
import sqlite3
import time
import uuid

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.security import HTTPBasic
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape
from pydantic import BaseModel, Field

from .service import read_catalog
from .workers import SearchWorkers

ASSETS = Path(__file__).with_name("web_assets")
basic = HTTPBasic(auto_error=False)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=8192)
    collections: list[str] = Field(min_length=1, max_length=32)
    syntax: str = "infix"
    field: str = Field(default="", max_length=256)
    normalization: str = "default"
    limit: int = Field(default=10, ge=1, le=50)


class EventRequest(BaseModel):
    kind: str
    result_ids: list[str] = Field(max_length=50)


def create_app(catalog, *, state_dir, admin_token=None, worker_options=None):
    collections = read_catalog(catalog)
    directory = Path(state_dir).resolve()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    secret_file = directory / "cookie-secret"
    try:
        descriptor = os.open(secret_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(descriptor, "w") as file:
            file.write(secrets.token_hex(32))

    @asynccontextmanager
    async def lifespan(app):
        app.state.workers = SearchWorkers(collections, directory=directory, **(worker_options or {}))
        app.state.jobs, app.state.presented = {}, {}
        connection = sqlite3.connect(directory / "events.sqlite")
        connection.execute("CREATE TABLE IF NOT EXISTS events "
            "(id INTEGER PRIMARY KEY, timestamp REAL, owner TEXT, kind TEXT, search_id TEXT, data TEXT)")
        app.state.events = connection
        try:
            yield
        finally:
            tasks = [j["task"] for j in app.state.jobs.values() if not j["task"].done()]
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            await asyncio.to_thread(app.state.workers.close)
            connection.close()

    app = FastAPI(title="CoreQuarry search", lifespan=lifespan)
    from starlette.middleware.sessions import SessionMiddleware
    app.add_middleware(SessionMiddleware, secret_key=secret_file.read_text(),
                       same_site="strict", max_age=86400)
    app.mount("/static", StaticFiles(directory=ASSETS / "static"), name="static")
    templates = Jinja2Templates(directory=ASSETS / "templates")

    def evidence(text):
        # Escape source content first. Only our fixed highlight tags become HTML.
        return Markup(re.sub(r"\*\*(.*?)\*\*", r"<mark>\1</mark>", str(escape(text)), flags=re.S))
    templates.env.filters["evidence"] = evidence

    def owner(request):
        if "sid" not in request.session:
            request.session["sid"] = uuid.uuid4().hex
        return request.session["sid"]

    def log(request, kind, search_id, data):
        request.app.state.events.execute("INSERT INTO events VALUES(NULL,?,?,?,?,?)",
            (time.time(), owner(request), kind, search_id, json.dumps(data, ensure_ascii=False)))
        request.app.state.events.commit()

    async def call(request, operation, *args, **kwargs):
        try:
            return await request.app.state.workers.call(operation, *args, **kwargs)
        except KeyError as error:
            raise HTTPException(410, error.args[0]) from None
        except (ValueError, RuntimeError) as error:
            raise HTTPException(400, str(error)) from None

    def remember(request, page):
        rows = request.app.state.presented.setdefault(owner(request), {})
        for row in page["results"]:
            rows[row["result_id"]] = {key: row[key] for key in ("key", "volume", "rank", "score")}
        while len(rows) > 500:
            rows.pop(next(iter(rows)))
        # Bound browser metadata separately from the native search cache.
        while len(request.app.state.presented) > 128:
            request.app.state.presented.pop(next(iter(request.app.state.presented)))

    async def admin(credentials=Depends(basic)):
        if not admin_token:
            raise HTTPException(404)
        if (not credentials or credentials.username != "admin" or
                not secrets.compare_digest(credentials.password.encode(), admin_token.encode())):
            raise HTTPException(401, "Administrator sign-in required", headers={"WWW-Authenticate": "Basic"})

    @app.exception_handler(HTTPException)
    async def handle_error(request, error):
        if request.headers.get("HX-Request"):
            return HTMLResponse(f'<div class="notice">{escape(str(error.detail))}</div>',
                                status_code=error.status_code, headers=error.headers)
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": error.detail}, status_code=error.status_code, headers=error.headers)

    @app.get("/", response_class=HTMLResponse)
    async def home(request: Request):
        owner(request)
        return templates.TemplateResponse(request=request, name="index.html",
                                          context={"collections": collections})

    @app.get("/api/fields")
    async def fields(request: Request, collection: list[str] = Query(default=[])):
        return await call(request, "fields", collection)

    @app.get("/suggestions", response_class=HTMLResponse)
    async def suggestions(request: Request, q: str = "", field: str = "",
                          collection: list[str] = Query(default=[])):
        token = re.search(r"[^\s()]+$", q)
        if not token or len(q) > 8192:
            return HTMLResponse("")
        values = await call(request, "scan", collection, field, token.group(), 12)
        base = q[:token.start()]
        return HTMLResponse("".join(f'<option value="{escape(base+v["term"])}">'
                            f'{escape(v["term"])} · {v["frequency"]}</option>' for v in values))

    @app.post("/api/search", status_code=202)
    async def search(request: Request, body: SearchRequest):
        jobs = request.app.state.jobs
        for key, job in list(jobs.items()):
            if job["task"].done() and time.time()-job["created"] > 900:
                del jobs[key]
        if sum(not j["task"].done() for j in jobs.values()) >= 16:
            raise HTTPException(429, "The search queue is full; try again shortly")
        while len(jobs) >= 128:
            completed = next((k for k, j in jobs.items() if j["task"].done()), None)
            if completed is None:
                break
            del jobs[completed]
        job_id = uuid.uuid4().hex
        session = owner(request)
        job = {"owner": session, "created": time.time(), "status": "pending",
               "query": body.query, "collections": body.collections, "search_id": None}

        async def evaluate():
            try:
                page = await request.app.state.workers.call("search", session, body.collections,
                    body.query, body.syntax, body.field, body.normalization, 0, body.limit)
                job.update(status="complete", search_id=page["search_id"], page=page)
                log(request, "search", page["search_id"], {key: page[key] for key in
                    ("query", "query_rpn", "collections", "databases", "ib_revision", "syntax", "field", "normalization",
                     "total_found", "elapsed_ms")})
            except Exception as error:
                job.update(status="failed", error=str(error))
        job["task"] = asyncio.create_task(evaluate())
        jobs[job_id] = job
        return {"job_id": job_id, "events_url": f"/api/jobs/{job_id}/events"}

    @app.get("/api/jobs/{job_id}/events")
    async def events(request: Request, job_id: str):
        job = request.app.state.jobs.get(job_id)
        if not job or job["owner"] != owner(request):
            raise HTTPException(404, "Unknown search request")
        async def stream():
            while True:
                payload = {key: job[key] for key in ("status", "search_id")}
                if "error" in job:
                    payload["error"] = job["error"]
                yield "data: " + json.dumps(payload) + "\n\n"
                if job["status"] != "pending" or await request.is_disconnected():
                    break
                try:
                    await asyncio.wait_for(asyncio.shield(job["task"]), timeout=5)
                except asyncio.TimeoutError:
                    pass
        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/search/{search_id}", response_class=HTMLResponse)
    async def page(request: Request, search_id: str, start: int = Query(0, ge=0),
                   limit: int = Query(10, ge=1, le=50)):
        data = await call(request, "page", owner(request), search_id, start, limit)
        remember(request, data)
        return templates.TemplateResponse(request=request, name="results.html", context={"page": data})

    @app.get("/record/{result_id}", response_class=HTMLResponse)
    async def record(request: Request, result_id: str, field: str | None = None,
                     start: int = Query(0, ge=0)):
        data = await call(request, "fetch", owner(request), result_id, field or None, start, 12000)
        return templates.TemplateResponse(request=request, name="record.html", context={"record": data})

    @app.post("/api/events", status_code=204)
    async def feedback(request: Request, body: EventRequest):
        if body.kind not in {"impression", "click"}:
            raise HTTPException(400, "Unknown event")
        known = request.app.state.presented.get(owner(request), {})
        if any(key not in known for key in body.result_ids):
            raise HTTPException(400, "The event contains an undisplayed result")
        grouped = {}
        for result_id in body.result_ids:
            grouped.setdefault(result_id.split(".")[0], []).append({"result_id": result_id, **known[result_id]})
        for search_id, rows in grouped.items():
            log(request, body.kind, search_id, {"results": rows})

    @app.get("/admin", dependencies=[Depends(admin)], response_class=HTMLResponse)
    async def administration(request: Request):
        events = request.app.state.events.execute(
            "SELECT timestamp,kind,search_id,data FROM events ORDER BY id DESC LIMIT 100").fetchall()
        jobs = [dict(job_id=key, **{k: v for k, v in job.items() if k not in {"task", "page", "owner"}})
                for key, job in reversed(list(request.app.state.jobs.items()))]
        return templates.TemplateResponse(request=request, name="admin.html",
                                          context={"jobs": jobs, "events": events})

    @app.get("/admin/search/{search_id}", dependencies=[Depends(admin)], response_class=HTMLResponse)
    async def inspect_search(request: Request, search_id: str):
        job = next((j for j in request.app.state.jobs.values() if j["search_id"] == search_id), None)
        if job is None:
            raise HTTPException(410, "Search unavailable")
        data = await call(request, "page", job["owner"], search_id, 0, 10)
        return templates.TemplateResponse(request=request, name="inspect.html", context={"page": data})

    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("catalog", help="Directory of collection INI files")
    parser.add_argument("--state-dir", default=".corequarry-web")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    import uvicorn
    app = create_app(args.catalog, state_dir=args.state_dir,
                     admin_token=os.environ.get("COREQUARRY_ADMIN_TOKEN"))
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
