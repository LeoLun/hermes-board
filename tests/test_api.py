from __future__ import annotations

import importlib.util
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from helpers import ROOT, BoardTestCase

import cardkit
from hermes_board_core.board import get_board

PREFIX = "/api/plugins/hermes-board"


def load_api():
    spec = importlib.util.spec_from_file_location("hermes_board_dashboard_api_test", ROOT / "dashboard" / "plugin_api.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ApiTest(BoardTestCase):
    def setUp(self):
        super().setUp()
        app = FastAPI()
        app.include_router(load_api().router, prefix=PREFIX)
        self.client = TestClient(app)
        self.board = get_board()
        self.wait_runs(self.board)

    def get(self, path, **kw):
        return self.client.get(PREFIX + path, **kw)

    def put(self, path, body):
        return self.client.put(PREFIX + path, json=body)

    def post(self, path, body):
        return self.client.post(PREFIX + path, json=body)

    def delete(self, path):
        return self.client.delete(PREFIX + path)

    def assert_error(self, resp, status, code):
        self.assertEqual(resp.status_code, status, resp.text)
        self.assertEqual(resp.headers["cache-control"], "no-store")
        detail = resp.json()["detail"]
        self.assertEqual(detail["code"], code)
        self.assertTrue(detail["message"])
        return detail

    def test_health(self):
        resp = self.get("/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers["cache-control"], "no-store")
        self.assertEqual(resp.json(), {"ok": True, "pluginVersion": "0.1.0", "apiVersion": 1, "schemaVersion": 1,
                                       "cronAvailable": True, "aiAvailable": False})

    def test_board_view(self):
        data = self.get("/board").json()
        self.assertEqual(data["layout"]["revision"], 1)
        self.assertEqual([i["card"] for i in data["layout"]["items"]], ["alpha", "beta"])
        alpha = next(c for c in data["cards"] if c["id"] == "alpha")
        self.assertEqual(alpha["status"], "ok")
        self.assertTrue(alpha["onBoard"])
        self.assertNotIn("manifest", alpha)
        fetch = alpha["scripts"][0]
        self.assertEqual(fetch["name"], "fetch")
        self.assertEqual(fetch["cron"]["paused"], False)
        self.assertEqual(fetch["lastRun"]["trigger"], "install")

    def test_put_board_conflict_and_invalid(self):
        items = [{"id": "alpha", "card": "alpha", "x": 0, "y": 0, "w": 4, "h": 4},
                 {"id": "beta", "card": "beta", "x": 0, "y": 4, "w": 6, "h": 4}]
        resp = self.put("/board", {"baseRevision": 1, "items": items})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["layout"]["revision"], 2)
        detail = self.assert_error(self.put("/board", {"baseRevision": 1, "items": items}), 409, "conflict")
        self.assertEqual(detail["current"]["revision"], 2)
        overlap = [dict(items[0]), dict(items[1], y=2)]
        self.assert_error(self.put("/board", {"baseRevision": 2, "items": overlap}), 400, "invalid")
        self.assert_error(self.client.put(PREFIX + "/board", json=[1]), 400, "invalid")

    def test_items_add_remove_pause_resume_cron(self):
        job = next(iter(self.cron.jobs.values()))
        resp = self.delete("/board/items/alpha?baseRevision=1")
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual([i["card"] for i in resp.json()["layout"]["items"]], ["beta"])
        self.assertFalse(self.cron.jobs[job["id"]]["enabled"])
        self.assert_error(self.delete("/board/items/alpha"), 404, "not_found")
        resp = self.post("/board/items", {"baseRevision": 2, "card": "alpha"})
        self.assertEqual(resp.status_code, 200, resp.text)
        placed = next(i for i in resp.json()["layout"]["items"] if i["card"] == "alpha")
        self.assertEqual((placed["x"], placed["y"], placed["w"], placed["h"]), (0, 0, 4, 4))
        self.assertTrue(self.cron.jobs[job["id"]]["enabled"])
        self.assert_error(self.post("/board/items", {"card": "alpha"}), 409, "exists")
        self.assert_error(self.post("/board/items", {"card": "ghost"}), 404, "not_found")
        self.delete("/board/items/beta")
        self.assert_error(self.post("/board/items", {"card": "beta", "size": "12x8"}), 400, "invalid")

    def test_document_known(self):
        doc = self.get("/cards/alpha/document").json()
        self.assertIn("HermesCard.ready", doc["html"])
        self.assertEqual(doc["revision"], 1)
        again = self.get(f"/cards/alpha/document?known={doc['sha256']}").json()
        self.assertTrue(again["unchanged"])
        self.assert_error(self.get("/cards/ghost/document"), 404, "not_found")
        self.assert_error(self.get("/cards/Bad/document"), 400, "invalid")

    def test_data_series_state(self):
        self.assertEqual(self.get("/cards/alpha/data").json()["items"]["current"]["value"], {"n": 1})
        self.assertEqual(self.get("/cards/alpha/data/current").json()["value"], {"n": 1})
        self.assertEqual(self.get("/cards/alpha/data/missing").json(), {"value": None, "updatedAt": None})
        self.assert_error(self.get("/cards/alpha/data/bad%20key"), 400, "invalid")
        self.assertEqual(len(self.get("/cards/alpha/series/count").json()["points"]), 1)
        self.assert_error(self.get("/cards/alpha/series/count?limit=99999"), 400, "invalid")
        self.assertEqual(self.get("/cards/alpha/state/city").json(), {"value": "北京", "updatedAt": None})
        self.assertIsInstance(self.put("/cards/alpha/state/city", {"value": "上海"}).json()["updatedAt"], int)
        self.assertEqual(self.get("/cards/alpha/state/city").json()["value"], "上海")
        self.assertEqual(self.delete("/cards/alpha/state/city").json(), {"deleted": True})
        self.assert_error(self.put("/cards/alpha/state/city", {"v": 1}), 400, "invalid")
        self.assert_error(self.get("/cards/ghost/data"), 404, "not_found")

    def test_runs(self):
        started = self.post("/cards/alpha/runs", {"script": "fetch", "args": {"n": 3}}).json()
        self.assertEqual(started["status"], "queued")
        self.board.runner.wait(started["runId"], timeout=20)
        run = self.get(f"/runs/{started['runId']}").json()
        self.assertEqual(run["status"], "succeeded")
        self.assertEqual(run["result"], {"ok": True, "n": 3})
        self.assertEqual(self.get("/cards/alpha/runs?limit=1").json()["runs"][0]["runId"], started["runId"])
        self.assert_error(self.post("/cards/alpha/runs", {"script": "nope"}), 404, "not_found")
        self.assert_error(self.post("/cards/alpha/runs", {"script": "fetch", "args": {"n": -1}}), 400, "invalid")
        self.assert_error(self.get("/runs/nope"), 404, "not_found")

    def test_ai_unavailable_and_missing(self):
        pkg = cardkit.package("gamma", ai={"pick": {"system": "选择最快的节点", "inputSchema": {"type": "object"},
                                                    "outputSchema": {"type": "object"}}})
        self.board.install_card(pkg)
        self.assert_error(self.post("/cards/gamma/ai/pick", {"input": {}}), 501, "ai_unavailable")
        self.assert_error(self.post("/cards/gamma/ai/nope", {"input": {}}), 404, "not_found")

    def test_changes(self):
        head = self.get("/changes").json()
        self.assertEqual(head["changes"], [])
        self.put("/cards/alpha/state/city", {"value": "广州"})
        delta = self.get(f"/changes?since={head['seq']}").json()
        self.assertEqual(delta["changes"], [{"card": "alpha", "kind": "state", "name": "city"}])
        self.assertTrue(self.get("/changes?since=999999").json()["reset"])


if __name__ == "__main__":
    unittest.main()
