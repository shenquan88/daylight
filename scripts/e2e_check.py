"""End-to-end check against a real server process.

Starts `app.py` on a real port, drives it with real HTTP requests, kills the
process, starts it again, and proves the data came back from disk.
Every step prints its request, status code and the field it proved.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8099
BASE = "http://127.0.0.1:%d" % PORT
DATA_DIR = os.path.join(ROOT, "data")

failures = []


def call(method, path, payload=None):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, exc.read().decode("utf-8")
        finally:
            exc.close()


def check(label, ok, detail=""):
    mark = "PASS" if ok else "FAIL"
    print("[%s] %s%s" % (mark, label, ("  ->  " + detail) if detail else ""))
    if not ok:
        failures.append(label)


def wait_healthy(timeout=25.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            status, body = call("GET", "/api/health")
            if status == 200:
                return json.loads(body)
        except Exception:
            pass
        time.sleep(0.25)
    return None


def start():
    proc = subprocess.Popen(
        [sys.executable, "app.py", "--port", str(PORT), "--data-dir", DATA_DIR, "--quiet"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
    )
    health = wait_healthy()
    if health is None:
        out = proc.stdout.read() if proc.stdout else ""
        print("server did not become healthy. output:\n" + out)
        proc.kill()
        raise SystemExit(1)
    return proc, health


def stop(proc):
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    print("    server stopped (exit code %s)" % proc.returncode)


def reset_data_dir():
    """Start from an empty database so the counts below are meaningful."""
    os.makedirs(DATA_DIR, exist_ok=True)
    for name in os.listdir(DATA_DIR):
        if name.startswith("daylight.db"):
            os.remove(os.path.join(DATA_DIR, name))


def main():
    reset_data_dir()
    print("=== Daylight end-to-end check ===")
    print("python:", sys.version.split()[0])
    print("data dir:", DATA_DIR)

    print("\n-- run 1: fresh process --")
    proc, health = start()
    print("    /api/health -> 200  db=%s  bytes=%d" % (health["db_path"], health["db_bytes"]))
    check("health reports a real sqlite file", os.path.isfile(health["db_path"]))

    status, body = call("GET", "/")
    check("GET / -> 200 html", status == 200 and "Daylight" in body, "status=%d" % status)

    status, body = call("POST", "/api/goals", {"text": "把周报的开头写出来"})
    goal_a = json.loads(body)["goal"]
    check("POST /api/goals -> 201", status == 201,
          "id=%s next_step=%s" % (goal_a["id"], goal_a["next_step"]))

    status, body = call("POST", "/api/goals", {"text": "散步 15 分钟"})
    goal_b = json.loads(body)["goal"]
    check("POST /api/goals (2nd) -> 201", status == 201, "id=%s" % goal_b["id"])

    status, body = call("POST", "/api/goals/%d/complete" % goal_a["id"])
    done = json.loads(body)
    check("POST /api/goals/%d/complete -> 200" % goal_a["id"], status == 200,
          "done=%s percent=%s" % (done["goal"]["done"], done["state"]["progress"]["percent"]))

    status, body = call("POST", "/api/checkins",
                        {"did": "写完了周报前三段", "learned": "先写骨架比先润色快"})
    check("POST /api/checkins -> 201", status == 201)

    status, body = call("POST", "/api/checkins",
                        {"did": "出门走了 12 分钟", "learned": "走起来就不想停"})
    check("POST /api/checkins (2nd) -> 201", status == 201)

    status, body = call("POST", "/api/reflect", {})
    card = json.loads(body)["card"]
    grounded = ("把周报的开头写出来" in card["body"] and "写完了周报前三段" in card["body"])
    check("POST /api/reflect -> 201", status == 201, "mode=%s" % card["mode"])
    check("card is grounded in real records", grounded)
    check("card has no invented achievement", "已完成 3" not in card["body"])

    status, body = call("GET", "/api/state")
    state = json.loads(body)
    check("GET /api/state -> 200", status == 200,
          "goals=%d checkins=%d cards=%d streak=%d" % (
              len(state["goals"]), len(state["checkins"]), len(state["cards"]), state["streak"]))

    status, body = call("GET", "/api/export.md")
    ok_export = (status == 200 and "把周报的开头写出来" in body
                 and "写完了周报前三段" in body and "### 经验卡" in body)
    check("GET /api/export.md -> 200 markdown", ok_export, "%d bytes" % len(body))

    status, _ = call("GET", "/api/health")
    check("GET /api/health after writes -> 200", status == 200)

    status, _ = call("POST", "/api/goals", {"text": ""})
    check("empty goal rejected -> 400", status == 400)
    status, _ = call("POST", "/api/goals", {"text": "x" * 500})
    check("over-long goal rejected -> 400", status == 400)
    status, _ = call("POST", "/api/goals/999999/complete")
    check("missing goal -> 404", status == 404)

    stop(proc)

    print("\n-- run 2: restart, same data dir --")
    proc, health = start()
    print("    /api/health -> 200  db=%s  bytes=%d  last_write=%s"
          % (health["db_path"], health["db_bytes"], health["last_write"]))
    status, body = call("GET", "/api/state")
    state = json.loads(body)
    check("goals survived restart", len(state["goals"]) == 2, "goals=%d" % len(state["goals"]))
    check("checkins survived restart", len(state["checkins"]) == 2,
          "checkins=%d" % len(state["checkins"]))
    check("cards survived restart", len(state["cards"]) == 1, "cards=%d" % len(state["cards"]))
    check("completion flag survived restart",
          any(g["done"] for g in state["goals"]))
    check("streak survived restart", state["streak"] >= 1, "streak=%d" % state["streak"])
    check("counts in health match", health["counts"]["goals"] == 2
          and health["counts"]["checkins"] == 2, json.dumps(health["counts"]))

    stop(proc)

    print("\n=== %d failure(s) ===" % len(failures))
    for f in failures:
        print("  - " + f)
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
