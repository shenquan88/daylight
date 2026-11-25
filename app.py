#!/usr/bin/env python3
"""Daylight · 向阳 — a persistent personal agent for positive daily progress.

Python standard library only: http.server + sqlite3 + urllib. No pip installs.

    python app.py                 # http://0.0.0.0:8080
    python app.py --port 8099 --data-dir ./data

Facts live in SQLite on a persistent disk (Sprite disk at /home/sprite/daylight-data,
./data when developing locally). Process memory is never the source of truth.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import coach
from store import Store

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

MAX_BODY = 64 * 1024
LIMIT_GOAL = 200
LIMIT_STEP = 240
LIMIT_DID = 2000
LIMIT_LEARNED = 2000
ID_MAX = 10 ** 12

STATIC_ROUTES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "application/javascript; charset=utf-8"),
    "/favicon.svg": ("favicon.svg", "image/svg+xml"),
}

GOAL_COMPLETE_RE = re.compile(r"^/api/goals/(\d{1,13})/complete$")


class BadRequest(Exception):
    pass


class NotFound(Exception):
    pass


def clean_text(value, field, limit, required=True):
    """Validate one user string: type, length, control characters."""
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise BadRequest(f"{field} 需要是文本")
    value = value.replace("\r\n", "\n").strip()
    if required and not value:
        raise BadRequest(f"{field} 不能为空")
    if len(value) > limit:
        raise BadRequest(f"{field} 最多 {limit} 个字符")
    for ch in value:
        if ch in "\n\t":
            continue
        if ord(ch) < 32 or ord(ch) == 127:
            raise BadRequest(f"{field} 含有不可见字符")
    return value


class DaylightHandler(BaseHTTPRequestHandler):
    server_version = "Daylight/1.0"
    protocol_version = "HTTP/1.1"

    # ---------------------------------------------------------------- plumbing

    def log_message(self, fmt, *args):
        if getattr(self.server, "quiet", False):
            return
        sys.stderr.write(
            "%s %s\n" % (self.address_string(), fmt % args)
        )

    def _send(self, status, body=b"", content_type="application/json; charset=utf-8",
              extra_headers=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status, payload):
        self._send(status, json.dumps(payload, ensure_ascii=False))

    def _error(self, status, message):
        self._json(status, {"error": message})

    def _read_body_bytes(self) -> bytes:
        """Consume the whole request body, always.

        A handler that ignores the body anyway must still drain it: on a
        keep-alive connection the unread bytes would become the next request
        line (the classic "{}POST /api/..." 501).
        """
        length = self.headers.get("Content-Length")
        if not length:
            return b""
        try:
            size = int(length)
        except ValueError:
            raise BadRequest("Content-Length 非法")
        if size <= 0:
            return b""
        if size > MAX_BODY:
            raise BadRequest("请求体过大")
        return self.rfile.read(size)

    def _read_json(self):
        raw = getattr(self, "_body", b"")
        if not raw:
            raise BadRequest("请求体为空")
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise BadRequest("请求体需要是 JSON")
        if not isinstance(data, dict):
            raise BadRequest("请求体需要是 JSON 对象")
        return data

    # ---------------------------------------------------------------- GET

    def do_GET(self):
        try:
            self._route_get()
        except BadRequest as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))
        except NotFound as exc:
            self._error(HTTPStatus.NOT_FOUND, str(exc))
        except Exception as exc:  # keep the process alive, report honestly
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, f"服务端错误：{type(exc).__name__}")

    def _route_get(self):
        path = urlparse(self.path).path
        if path == "/api/health":
            health = self.server.store.health()
            health["connector"] = self.server.connector.describe()
            return self._json(HTTPStatus.OK, health)
        if path == "/api/state":
            state = self.server.store.state(self.server.connector.configured)
            state["connector"] = self.server.connector.describe()
            return self._json(HTTPStatus.OK, state)
        if path == "/api/export.md":
            md = self.server.store.export_markdown()
            return self._send(
                HTTPStatus.OK,
                md,
                "text/markdown; charset=utf-8",
                {"Content-Disposition": 'attachment; filename="daylight-export.md"'},
            )
        if path in STATIC_ROUTES:
            name, ctype = STATIC_ROUTES[path]
            full = os.path.join(STATIC_DIR, name)
            if not os.path.isfile(full):
                raise NotFound("页面资源缺失")
            with open(full, "rb") as fh:
                body = fh.read()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
            return
        raise NotFound("没有这个页面")

    # ---------------------------------------------------------------- POST

    def do_POST(self):
        self._body = b""
        try:
            self._body = self._read_body_bytes()
            self._route_post()
        except BadRequest as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))
            self.close_connection = True
        except NotFound as exc:
            self._error(HTTPStatus.NOT_FOUND, str(exc))
        except Exception as exc:
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, f"服务端错误：{type(exc).__name__}")
            self.close_connection = True

    def _route_post(self):
        path = urlparse(self.path).path
        store = self.server.store

        if path == "/api/goals":
            data = self._read_json()
            text = clean_text(data.get("text"), "目标", LIMIT_GOAL)
            steps = coach.suggest_next_steps(text, 2)
            next_step = clean_text(data.get("next_step") or steps[0], "下一步", LIMIT_STEP)
            goal_id = store.add_goal(text, next_step)
            goal = store.goal_by_id(goal_id)
            return self._json(HTTPStatus.CREATED, {
                "goal": goal,
                "suggestions": steps,
                "state": store.state(self.server.connector.configured),
            })

        match = GOAL_COMPLETE_RE.match(path)
        if match:
            goal_id = int(match.group(1))
            if goal_id > ID_MAX:
                raise NotFound("目标不存在")
            if store.goal_by_id(goal_id) is None:
                raise NotFound("目标不存在")
            changed = store.complete_goal(goal_id)
            return self._json(HTTPStatus.OK, {
                "goal": store.goal_by_id(goal_id),
                "changed": changed,
                "state": store.state(self.server.connector.configured),
            })

        if path == "/api/checkins":
            data = self._read_json()
            did = clean_text(data.get("did"), "我做了什么", LIMIT_DID)
            learned = clean_text(data.get("learned"), "我学到", LIMIT_LEARNED, required=False)
            checkin_id = store.add_checkin(did, learned)
            state = store.state(self.server.connector.configured)
            return self._json(HTTPStatus.CREATED, {
                "checkin": {
                    "id": checkin_id, "day": store.today(),
                    "did": did, "learned": learned,
                },
                "state": state,
            })

        if path == "/api/reflect":
            data = self._read_json() if self._body else {}
            day = clean_text(data.get("day"), "日期", 10, required=False) or store.today()
            goals = store.goals_for(day)
            checkins = store.checkins_for(day)
            streak = store.streak(day)
            body, mode = coach.card_with_connector(
                self.server.connector, day, goals, checkins, streak
            )
            card_id = store.add_card(body, mode, day)
            return self._json(HTTPStatus.CREATED, {
                "card": {"id": card_id, "day": day, "body": body, "mode": mode},
                "state": store.state(self.server.connector.configured),
            })

        raise NotFound("没有这个接口")

    def do_HEAD(self):
        self.do_GET()


def default_data_dir() -> str:
    if os.path.isdir("/home/sprite"):
        return "/home/sprite/daylight-data"
    return os.path.join(BASE_DIR, "data")


def make_server(host="0.0.0.0", port=8080, data_dir=None, quiet=False,
                connector=None, store=None):
    store = store or Store(data_dir or default_data_dir())
    httpd = ThreadingHTTPServer((host, port), DaylightHandler)
    httpd.daemon_threads = True
    httpd.store = store
    httpd.connector = connector or coach.Connector.from_env()
    httpd.quiet = quiet
    return httpd


def main(argv=None):
    parser = argparse.ArgumentParser(description="Daylight · 向阳 — local-first daily agent")
    parser.add_argument("--host", default=os.environ.get("DAYLIGHT_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("DAYLIGHT_PORT", "8080")))
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    httpd = make_server(args.host, args.port, args.data_dir, args.quiet)
    store = httpd.store
    conn = httpd.connector
    mode = "connector" if conn.configured else "local"
    print(f"Daylight · 向阳  http://{args.host}:{httpd.server_address[1]}")
    print(f"data dir : {store.data_dir}")
    print(f"database : {store.db_path}")
    print(f"mode     : {mode}" + (f"  model={conn.model}" if conn.configured else "  (本地模板)"))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstop")
    finally:
        httpd.server_close()
        store.close()


if __name__ == "__main__":
    main()
