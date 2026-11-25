"""Unit and HTTP tests for Daylight. Run: python -m unittest discover -s tests -v"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import app  # noqa: E402
import coach  # noqa: E402
from store import PLANT_STAGES, Store  # noqa: E402


class ServerCase(unittest.TestCase):
    """One real HTTP server per test, on an ephemeral port, with its own database."""

    connector = None

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="daylight-test-")
        self.connector = self.connector or coach.Connector("", "")
        self._start()

    def _start(self):
        self.httpd = app.make_server(
            "127.0.0.1", 0, self.tmp, quiet=True, connector=self.connector
        )
        self.port = self.httpd.server_address[1]
        self.base = "http://127.0.0.1:%d" % self.port
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def _stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.httpd.store.close()
        self.thread.join(timeout=5)

    def tearDown(self):
        self._stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ---------------------------------------------------------------- helpers

    def request(self, method, path, payload=None, raw=None):
        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if raw is not None:
            data = raw
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                return resp.status, resp.read().decode("utf-8"), dict(resp.headers)
        except urllib.error.HTTPError as exc:
            try:
                return exc.code, exc.read().decode("utf-8"), dict(exc.headers)
            finally:
                exc.close()

    def get_json(self, path):
        status, body, _ = self.request("GET", path)
        self.assertEqual(status, 200, body)
        return json.loads(body)

    def post_json(self, path, payload=None):
        status, body, _ = self.request("POST", path, payload if payload is not None else {})
        return status, (json.loads(body) if body else {})


class TestPages(ServerCase):
    def test_index_page_served(self):
        status, body, headers = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["Content-Type"])
        self.assertIn("Daylight", body)
        self.assertIn("把每个今天", body)

    def test_static_assets_served(self):
        for path, ctype in (("/styles.css", "text/css"), ("/app.js", "javascript"),
                            ("/favicon.svg", "svg")):
            status, body, headers = self.request("GET", path)
            self.assertEqual(status, 200, path)
            self.assertIn(ctype, headers["Content-Type"])
            self.assertTrue(body.strip())

    def test_unknown_path_404(self):
        status, body, _ = self.request("GET", "/nope")
        self.assertEqual(status, 404)
        self.assertIn("error", json.loads(body))

    def test_path_traversal_blocked(self):
        for path in ("/../app.py", "/static/../app.py", "/%2e%2e/app.py"):
            status, _, _ = self.request("GET", path)
            self.assertIn(status, (400, 404), path)


class TestHealth(ServerCase):
    def test_health_reports_storage(self):
        h = self.get_json("/api/health")
        self.assertEqual(h["status"], "ok")
        self.assertTrue(os.path.isdir(h["data_dir"]))
        self.assertTrue(os.path.isfile(h["db_path"]))
        self.assertTrue(h["db_path"].endswith("daylight.db"))
        self.assertEqual(h["counts"]["goals"], 0)
        self.assertFalse(h["connector"]["configured"])
        self.assertNotIn("token", json.dumps(h).lower())


class TestGoals(ServerCase):
    def test_create_goal_returns_step(self):
        status, res = self.post_json("/api/goals", {"text": "把周报的开头写出来"})
        self.assertEqual(status, 201)
        self.assertEqual(res["goal"]["text"], "把周报的开头写出来")
        self.assertTrue(res["goal"]["next_step"])
        self.assertEqual(res["state"]["progress"]["total"], 1)

    def test_goal_keyword_step_matches_kind(self):
        status, res = self.post_json("/api/goals", {"text": "写完周报的开头"})
        self.assertEqual(status, 201)
        self.assertIn("先写三行", res["goal"]["next_step"])

    def test_goal_blank_rejected(self):
        status, res = self.post_json("/api/goals", {"text": "   "})
        self.assertEqual(status, 400)
        self.assertIn("error", res)

    def test_goal_too_long_rejected(self):
        status, _ = self.post_json("/api/goals", {"text": "a" * 201})
        self.assertEqual(status, 400)

    def test_goal_wrong_type_rejected(self):
        status, _ = self.post_json("/api/goals", {"text": 123})
        self.assertEqual(status, 400)

    def test_complete_goal_updates_progress(self):
        _, res = self.post_json("/api/goals", {"text": "读一页书"})
        goal_id = res["goal"]["id"]
        status, done = self.post_json("/api/goals/%d/complete" % goal_id)
        self.assertEqual(status, 200)
        self.assertEqual(done["goal"]["done"], 1)
        self.assertEqual(done["state"]["progress"]["percent"], 100)
        self.assertTrue(done["state"]["goals"][0]["done_at"])

    def test_complete_missing_goal_404(self):
        status, res = self.post_json("/api/goals/999999/complete")
        self.assertEqual(status, 404)
        self.assertIn("error", res)

    def test_non_numeric_goal_id_404(self):
        status, _, _ = self.request("POST", "/api/goals/abc/complete", {})
        self.assertEqual(status, 404)

    def test_absurd_goal_id_404(self):
        status, _, _ = self.request("POST", "/api/goals/99999999999999999999/complete", {})
        self.assertEqual(status, 404)

    def test_bad_json_rejected(self):
        status, _, _ = self.request("POST", "/api/goals", raw=b"{not json")
        self.assertEqual(status, 400)


class TestCheckins(ServerCase):
    def test_checkin_appears_in_state(self):
        status, res = self.post_json(
            "/api/checkins", {"did": "写了三段周报", "learned": "先骨架后润色"}
        )
        self.assertEqual(status, 201)
        self.assertEqual(res["checkin"]["did"], "写了三段周报")
        state = self.get_json("/api/state")
        self.assertEqual(len(state["checkins"]), 1)
        self.assertEqual(state["checkins"][0]["learned"], "先骨架后润色")

    def test_checkin_blank_rejected(self):
        status, _ = self.post_json("/api/checkins", {"did": "  "})
        self.assertEqual(status, 400)

    def test_checkin_too_long_rejected(self):
        status, _ = self.post_json("/api/checkins", {"did": "a" * 2001})
        self.assertEqual(status, 400)

    def test_learned_is_optional_and_length_capped(self):
        status, _ = self.post_json("/api/checkins", {"did": "做了一件事", "learned": ""})
        self.assertEqual(status, 201)
        status, _ = self.post_json("/api/checkins", {"did": "又做一件", "learned": "b" * 2001})
        self.assertEqual(status, 400)


class TestReflectAndExport(ServerCase):
    def test_local_card_grounded_in_records(self):
        _, created = self.post_json("/api/goals", {"text": "整理书桌"})
        self.post_json("/api/goals/%d/complete" % created["goal"]["id"])
        self.post_json("/api/checkins", {"did": "清空了桌面", "learned": "十分钟够用"})
        status, res = self.post_json("/api/reflect")
        self.assertEqual(status, 201)
        card = res["card"]
        self.assertEqual(card["mode"], "local")
        self.assertIn("整理书桌", card["body"])
        self.assertIn("清空了桌面", card["body"])
        self.assertIn("十分钟够用", card["body"])
        self.assertIn("连续记录", card["body"])

    def test_card_without_records_claims_nothing(self):
        status, res = self.post_json("/api/reflect")
        self.assertEqual(status, 201)
        self.assertIn("今天还没有写下小目标", res["card"]["body"])

    def test_export_markdown_contains_everything(self):
        _, created = self.post_json("/api/goals", {"text": "给朋友回消息"})
        self.post_json("/api/goals/%d/complete" % created["goal"]["id"])
        self.post_json("/api/checkins", {"did": "回了三条", "learned": "先回最短的"})
        self.post_json("/api/reflect")
        status, body, headers = self.request("GET", "/api/export.md")
        self.assertEqual(status, 200)
        self.assertIn("text/markdown", headers["Content-Type"])
        self.assertIn("attachment", headers["Content-Disposition"])
        self.assertIn("# Daylight · 向阳", body)
        self.assertIn("给朋友回消息", body)
        self.assertIn("回了三条", body)
        self.assertIn("### 经验卡", body)


class TestPersistence(ServerCase):
    def test_data_survives_process_restart(self):
        self.post_json("/api/goals", {"text": "散步 10 分钟"})
        self.post_json("/api/checkins", {"did": "走了 12 分钟"})
        self.post_json("/api/reflect")

        self._stop()
        self._start()

        state = self.get_json("/api/state")
        self.assertEqual(len(state["goals"]), 1)
        self.assertEqual(state["goals"][0]["text"], "散步 10 分钟")
        self.assertEqual(len(state["checkins"]), 1)
        self.assertEqual(len(state["cards"]), 1)
        self.assertEqual(state["streak"], 1)

    def test_health_last_write_advances(self):
        first = self.get_json("/api/health")["last_write"]
        self.post_json("/api/goals", {"text": "写一行字"})
        second = self.get_json("/api/health")["last_write"]
        self.assertTrue(second)
        self.assertGreaterEqual(second, first)


class TestGarden(ServerCase):
    def test_garden_grows_with_activity(self):
        store = Store(self.tmp)
        store.add_goal("一天三件小事", "", day="2026-11-24")
        store.add_checkin("做了一件", day="2026-11-24")
        store.add_checkin("又做一件", day="2026-11-25")
        garden = {entry["day"]: entry for entry in store.garden()}
        self.assertEqual(garden["2026-11-24"]["activity"], 1)
        self.assertEqual(garden["2026-11-25"]["activity"], 1)
        self.assertIn(garden["2026-11-25"]["stage"], PLANT_STAGES)
        store.close()

    def test_streak_counts_consecutive_days(self):
        store = Store(self.tmp)
        for day in ("2026-11-23", "2026-11-24", "2026-11-25"):
            store.add_checkin("留一条", day=day)
        self.assertEqual(store.streak("2026-11-25"), 3)
        self.assertEqual(store.streak("2026-11-27"), 0)
        store.close()


class TestConnector(ServerCase):
    """The connector path is exercised with a fake transport; nothing goes online."""

    def test_connector_rewrites_card(self):
        calls = []

        def transport(method, url, payload, headers, timeout):
            calls.append((method, url, payload, headers))
            body = {"choices": [{"message": {"content": "今天你完成了一个目标，明天继续。"}}]}
            return 200, json.dumps(body)

        self.httpd.connector = coach.Connector(
            "https://gateway.example/v1/chat/completions", "sprite-small",
            transport=transport,
        )
        self.post_json("/api/goals", {"text": "写一段介绍"})
        status, res = self.post_json("/api/reflect")
        self.assertEqual(status, 201)
        self.assertEqual(res["card"]["mode"], "connector")
        self.assertIn("明天继续", res["card"]["body"])
        self.assertEqual(calls[0][0], "POST")
        self.assertNotIn("Authorization", calls[0][3])

    def test_connector_failure_falls_back_to_local(self):
        def transport(method, url, payload, headers, timeout):
            raise coach.ConnectorError("boom")

        self.httpd.connector = coach.Connector(
            "https://gateway.example/v1/chat/completions", "sprite-small",
            transport=transport,
        )
        self.post_json("/api/goals", {"text": "读十页书"})
        status, res = self.post_json("/api/reflect")
        self.assertEqual(status, 201)
        self.assertEqual(res["card"]["mode"], "local")
        self.assertIn("读十页书", res["card"]["body"])

    def test_gateway_list_parses_models(self):
        def transport(method, url, payload, headers, timeout):
            self.assertEqual(method, "GET")
            return 200, json.dumps({"models": [{"id": "sprite-small"}, "sprite-large"]})

        conn = coach.Connector("https://gateway.example/v1/chat/completions",
                               "sprite-small", transport=transport)
        self.assertEqual(conn.list_models(), ["sprite-small", "sprite-large"])

    def test_default_timeout_is_sixty_seconds(self):
        """A slow free model must not be cut off at 8 s and silently fall back."""
        self.assertEqual(coach.DEFAULT_TIMEOUT, 60.0)
        conn = coach.Connector("https://gateway.example/v1/chat/completions",
                               "liquid/lfm-3-1.7b:free")
        self.assertEqual(conn.timeout, 60.0)
        # from_env must keep the same default: start.sh sets no timeout.
        conn = coach.Connector.from_env({
            "SPRITE_CONNECTOR_URL": "https://gateway.example/v1/chat/completions",
            "SPRITE_MODEL": "liquid/lfm-3-1.7b:free",
        })
        self.assertEqual(conn.timeout, 60.0)

    def test_transport_receives_default_timeout(self):
        seen = []

        def transport(method, url, payload, headers, timeout):
            seen.append(timeout)
            body = {"choices": [{"message": {"content": "慢一点也算完成。"}}]}
            return 200, json.dumps(body)

        conn = coach.Connector("https://gateway.example/v1/chat/completions",
                               "liquid/lfm-3-1.7b:free", transport=transport)
        self.assertEqual(conn.complete("写一张卡"), "慢一点也算完成。")
        self.assertEqual(seen, [60.0])

    def test_explicit_timeout_still_wins(self):
        seen = []

        def transport(method, url, payload, headers, timeout):
            seen.append(timeout)
            return 200, json.dumps({"choices": [{"message": {"content": "ok"}}]})

        conn = coach.Connector("https://gateway.example/v1/chat/completions",
                               "m", timeout=5.0, transport=transport)
        conn.complete("x")
        self.assertEqual(seen, [5.0])

    def test_from_env_needs_both_vars(self):
        self.assertFalse(coach.Connector.from_env({}).configured)
        self.assertFalse(coach.Connector.from_env({"SPRITE_CONNECTOR_URL": "x"}).configured)
        conn = coach.Connector.from_env({
            "SPRITE_CONNECTOR_URL": "https://api.sprites.dev/v1/gateway",
            "SPRITE_MODEL": "sprite-small",
        })
        self.assertTrue(conn.configured)
        self.assertEqual(conn.list_url, "https://api.sprites.dev/v1/gateway/list")


class TestKeepAlive(ServerCase):
    """A POST whose body is ignored must not poison the next request on the
    same keep-alive connection (regression: '{}POST /api/reflect' -> 501)."""

    def test_ignored_body_does_not_leak_into_next_request(self):
        import http.client

        _, created = self.post_json("/api/goals", {"text": "先写一行"})
        goal_id = created["goal"]["id"]
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=8)
        try:
            conn.request("POST", "/api/goals/%d/complete" % goal_id, body="{}",
                         headers={"Content-Type": "application/json"})
            first = conn.getresponse()
            first.read()
            self.assertEqual(first.status, 200)

            conn.request("POST", "/api/reflect", body="{}",
                         headers={"Content-Type": "application/json"})
            second = conn.getresponse()
            payload = second.read().decode("utf-8")
            self.assertEqual(second.status, 201, payload)
            self.assertIn("card", json.loads(payload))
        finally:
            conn.close()


class TestCoaching(ServerCase):
    def test_steps_are_deterministic(self):
        a = coach.suggest_next_steps("随便一个目标", 2)
        b = coach.suggest_next_steps("随便一个目标", 2)
        self.assertEqual(a, b)
        self.assertEqual(len(a), 2)

    def test_encouragement_deterministic_per_day(self):
        self.assertEqual(coach.encouragement("2026-11-25"), coach.encouragement("2026-11-25"))
        self.assertIn(coach.encouragement("2026-11-25"), coach.ENCOURAGEMENTS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
