"""The hosted boundary protects both the built frontend and every API route."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from tests.test_market_data import ENVIRONMENT
import database as db
import hosted


class HostedTests(unittest.TestCase):
    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.db_path = root / "journal.db"
        self.enterContext(patch.object(db, "DB_PATH", self.db_path))
        dist = root / "dist"
        dist.mkdir()
        (dist / "index.html").write_text("<title>Journal test</title>")
        (dist / "assets").mkdir()
        (dist / "assets" / "app.js").write_text("console.log('test')")
        self.enterContext(patch.object(hosted, "FRONTEND_DIST", dist))
        self.enterContext(patch.dict(os.environ, {**ENVIRONMENT,
            "JOURNAL_PASSWORD": "test-only-password", "JOURNAL_DB_PATH": str(self.db_path)}))
        self.login = ("journal", "test-only-password")

    def client(self):
        return TestClient(hosted.create_app(), base_url="https://journal.example")

    def test_health_is_public_and_app_asset_and_api_paths_require_login(self):
        with self.client() as client:
            self.assertEqual(client.get("/healthz").text, "ok")
            for method, path in [("GET", "/"), ("GET", "/assets/app.js"), ("GET", "/api/docs"),
                                 ("GET", "/api/journals"), ("GET", "/api/strategy-profiles"),
                                 ("POST", "/api/journal/generate"), ("DELETE", "/api/journals/1")]:
                with self.subTest(path=path):
                    response = client.request(method, path)
                    self.assertEqual(response.status_code, 401)
                    self.assertIn("Basic", response.headers["www-authenticate"])
            self.assertEqual(client.get("/", auth=("journal", "incorrect")).status_code, 401)
            self.assertEqual(client.get("/", headers={"Authorization": "Basic invalid"}).status_code, 401)

    def test_login_serves_ui_and_both_journal_apis_from_same_origin(self):
        with self.client() as client:
            for path in ("/", "/assets/app.js", "/api/journals", "/api/range-journals"):
                response = client.get(path, auth=self.login)
                self.assertEqual(response.status_code, 200, path)
                self.assertEqual(response.headers["cache-control"], "no-store")
            self.assertEqual(client.get("/api/no-such-api", auth=self.login).status_code, 404)
            self.assertEqual(client.get("/backend/.env", auth=self.login).status_code, 404)

    def test_foreign_origin_cannot_write_and_authorized_data_survives_restart(self):
        body = {"name": "Hosted profile", "rules": "Compare close to EMA20"}
        with self.client() as client:
            for headers in ({"Origin": "https://other.example"}, {"Origin": "null"}, {"Sec-Fetch-Site": "cross-site"}):
                response = client.post("/api/strategy-profiles", json=body, auth=self.login, headers=headers)
                self.assertEqual(response.status_code, 403)
            response = client.post("/api/strategy-profiles", json=body, auth=self.login,
                                   headers={"Origin": "https://journal.example"})
            self.assertEqual(response.status_code, 201)
        with self.client() as restarted:
            items = restarted.get("/api/strategy-profiles", auth=self.login).json()["items"]
            self.assertEqual([item["name"] for item in items], ["Hosted profile"])

    def test_startup_requires_credentials_storage_and_built_ui(self):
        for changes in ({"JOURNAL_PASSWORD": ""}, {"JOURNAL_DB_PATH": "relative.db"},
                        {"JOURNAL_DB_PATH": str(self.db_path.parent / "missing" / "journal.db")}):
            with self.subTest(changes=changes), patch.dict(os.environ, changes), self.assertRaises(RuntimeError):
                hosted.create_app()
        with patch.object(hosted, "FRONTEND_DIST", self.db_path.parent / "missing"), self.assertRaises(RuntimeError):
            hosted.create_app()
