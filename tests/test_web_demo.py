import json
import re
import sqlite3

import pytest
import corequarry as cq

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient
from corequarry.web import create_app


@pytest.fixture(scope="module")
def web_catalog(tmp_path_factory):
    root = tmp_path_factory.mktemp("web")
    catalog = root / "catalog"
    catalog.mkdir()
    for name in ("research", "briefs"):
        source = root / (name + ".ndjson")
        source.write_text("".join(json.dumps({"title": f"{name} note {i}",
            "body": "A café virus vaccine study. <script>alert(1)</script>", "count": i+1},
            ensure_ascii=False)+"\n" for i in range(6)), encoding="utf-8")
        database = root / name
        cq.index_file(database, source, doctype="NDJSON", memory_mb=32)
        (catalog / (name + ".ini")).write_text(
            f"[Collection]\ntitle={name.title()}\ndatabase=../{name}\n")
    return catalog


def complete(client, collections=None):
    response = client.post("/api/search", json={"query": "virus vaccine PEER:130", "syntax": "rpn",
                           "collections": collections or ["research"], "limit": 2})
    assert response.status_code == 202, response.text
    events = client.get(response.json()["events_url"])
    data = [json.loads(line[6:]) for line in events.text.splitlines() if line.startswith("data: ")]
    assert data[-1]["status"] == "complete", data
    return data[-1]["search_id"]


def test_browser_routes_autocomplete_paging_feedback_and_admin(web_catalog, tmp_path):
    app = create_app(web_catalog, state_dir=tmp_path, admin_token="test-admin-secret")
    with TestClient(app) as client:
        home = client.get("/")
        assert home.status_code == 200 and "Research" in home.text
        assert client.get("/static/htmx.min.js").status_code == 200
        assert {f["name"] for f in client.get("/api/fields?collection=research").json()} >= {"BODY", "TITLE"}
        suggestions = client.get("/suggestions?collection=research&field=BODY&q=vi")
        assert suggestions.status_code == 200 and 'value="virus"' in suggestions.text
        search_id = complete(client, ["research", "briefs"])
        page = client.get(f"/search/{search_id}?limit=2")
        assert page.status_code == 200 and "12" in page.text
        assert "<mark>virus</mark>" in page.text
        assert "<script>alert(1)</script>" not in page.text
        ids = re.findall(r'<article[^>]+data-result-id="([^"]+)"', page.text)
        assert len(ids) == 2
        assert client.get(f"/search/{search_id}?start=2&limit=2").status_code == 200
        assert client.post("/api/events", json={"kind": "impression", "result_ids": ids}).status_code == 204
        assert client.post("/api/events", json={"kind": "click", "result_ids": ids[:1]}).status_code == 204
        source = client.get(f"/record/{ids[0]}?field=BODY")
        assert source.status_code == 200 and "café" in source.text
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in source.text
        assert client.get("/admin").status_code == 401
        admin = client.get("/admin", auth=("admin", "test-admin-secret"))
        assert admin.status_code == 200 and "impression" in admin.text and "click" in admin.text
        assert client.get(f"/admin/search/{search_id}", auth=("admin", "test-admin-secret")).status_code == 200
        # The owner is a signed browser session, not possession of a result URL.
        client.cookies.clear()
        assert client.get(f"/search/{search_id}").status_code == 410
        assert client.get(f"/record/{ids[0]}").status_code == 410
    with sqlite3.connect(tmp_path / "events.sqlite") as connection:
        kinds = {row[0] for row in connection.execute("SELECT kind FROM events")}
        assert kinds >= {"search", "impression", "click"}


def test_invalid_selection_and_pending_failure(web_catalog, tmp_path):
    with TestClient(create_app(web_catalog, state_dir=tmp_path)) as client:
        assert client.get("/admin").status_code == 404
        assert client.get("/api/fields?collection=../../outside").status_code == 400
        assert client.get("/api/jobs/missing/events").status_code == 404
        response = client.post("/api/search", json={"query": "virus", "collections": ["outside"]})
        events = client.get(response.json()["events_url"])
        assert '"status": "failed"' in events.text
        assert client.post("/api/events", json={"kind": "click", "result_ids": ["fake.0"]}).status_code == 400
