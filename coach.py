"""Coaching layer: next-step hints, the daily card, and the optional connector.

Everything here works offline. The connector is a runtime-only add-on: when
SPRITE_CONNECTOR_URL and SPRITE_MODEL are set, Daylight asks a sprite-hosted
model to rewrite the card in warmer language. It never invents achievements —
the numbers and quotes in the card always come from SQLite. When the connector
is missing or fails, the local template is used and the UI says 本地模式.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
import zlib

STEP_RULES = [
    (("写", "文案", "文章", "文档", "报告", "write", "draft"),
     "先写三行，不求完整：只回答「第一句是什么」。"),
    (("学", "读", "课程", "教程", "study", "learn", "read"),
     "定一个 20 分钟的时段，只啃一个小节，学完立刻用自己的话写一句。"),
    (("联系", "发消息", "问", "预约", "邮件", "call", "email", "ask"),
     "先把开场那句话打出来，发出去，然后去做别的事等回复。"),
    (("整理", "清理", "归档", "收纳", "tidy", "clean"),
     "只清一个抽屉或一个文件夹，10 分钟计时，到点就停。"),
    (("跑", "走", "运动", "锻炼", "拉伸", "walk", "run", "exercise"),
     "先出门走 10 分钟，不计距离和速度，回来再决定要不要加量。"),
    (("代码", "修", "调试", "上线", "code", "fix", "bug", "build"),
     "先写一个能失败的最小用例，跑红它，再动实现。"),
    (("画", "设计", "草图", "design", "sketch"),
     "先画三个 5 分钟的粗糙版本，选一个再细化。"),
    (("存款", "预算", "账", "钱", "budget", "save"),
     "先记下今天的一笔真实支出，再看一个能立刻改的小项。"),
]

DEFAULT_STEPS = [
    "把它拆成 10 分钟内能完成的第一步，现在就做那一步。",
    "先做最小可用的版本，完成比完美先到。",
    "设一个 25 分钟专注段，只做这一件事，结束后写一句结果。",
    "把「今天要做到哪一步」写成一句话，越具体越好。",
]

ENCOURAGEMENTS = [
    "你今天留下的每个字，明天都会替你说话。",
    "慢一点没关系，方向对就行。",
    "完成的那个小动作，比计划里的十件大事更有分量。",
    "你已经比昨天多知道了一点自己。",
    "记录本身就是行动，今天没有白过。",
    "把今天收好，明天从这里接着长。",
    "你不需要一次长成大树，先长一片叶子。",
    "真实的一小步，胜过想象里的一大步。",
]


def suggest_next_steps(text: str, limit: int = 2) -> list:
    """Concrete first steps for a goal, matched by keyword; never invents results."""
    lowered = text.lower()
    hits = []
    for keys, step in STEP_RULES:
        if any((k in text) or (k in lowered) for k in keys):
            hits.append(step)
        if len(hits) >= limit:
            break
    if not hits:
        start = zlib.crc32(text.encode("utf-8")) % len(DEFAULT_STEPS)
        for i in range(limit):
            hits.append(DEFAULT_STEPS[(start + i) % len(DEFAULT_STEPS)])
    return hits[:limit]


def encouragement(day: str) -> str:
    return ENCOURAGEMENTS[zlib.crc32(day.encode("utf-8")) % len(ENCOURAGEMENTS)]


def build_card(day: str, goals: list, checkins: list, streak: int) -> str:
    """Daily card built strictly from stored records."""
    total = len(goals)
    done = [g for g in goals if g["done"]]
    open_goals = [g for g in goals if not g["done"]]

    lines = [f"{day} · 今日经验卡", ""]

    if total:
        lines.append(f"今天你写下 {total} 个小目标，完成了 {len(done)} 个。")
        for g in done:
            lines.append(f"· 完成：{g['text']}")
        for g in open_goals:
            lines.append(f"· 仍在进行：{g['text']}")
    else:
        lines.append("今天还没有写下小目标。空着也是一种信息。")

    lines.append("")
    if checkins:
        lines.append(f"行动记录 {len(checkins)} 条：")
        for i, c in enumerate(checkins, 1):
            lines.append(f"{i}. 我做了什么：{c['did']}")
            if c["learned"]:
                lines.append(f"   我学到：{c['learned']}")
    else:
        lines.append("行动记录还是空的 —— 写一句「我做了什么」，今天就有了落脚点。")

    lines.append("")
    if total:
        lines.append(f"今天的完成率：{round(len(done) / total * 100)}%。")
    lines.append(f"连续记录：第 {streak} 天。" if streak else "从今天开始，连续记录第 1 天。")

    if open_goals:
        nxt = open_goals[0].get("next_step") or suggest_next_steps(open_goals[0]["text"], 1)[0]
        lines.append(f"明天的一小步：{nxt}")
    elif checkins:
        lines.append("明天的一小步：给今天这条记录补一句「它为什么重要」。")
    else:
        lines.append("明天的一小步：写下一个小目标，只写一句。")

    lines.append(f"给自己的话：{encouragement(day)}")
    return "\n".join(lines)


class ConnectorError(RuntimeError):
    pass


# Free hosted models are queued behind other traffic and routinely need more
# than 8 seconds to answer a card. Measured on sprite daylight with
# liquid/lfm-3-1.7b:free: an 8 s ceiling cut the call short and the card fell
# back to the local template, so the connector looked "not configured".
DEFAULT_TIMEOUT = 60.0


class Connector:
    """Optional sprite connector gateway client (OpenAI-compatible chat call).

    No token is embedded: the caller passes one at construction time from the
    runtime environment, and this class never writes it anywhere. The gateway
    connector used in production needs no token at all.
    """

    def __init__(self, chat_url, model, list_url=None, token=None,
                 timeout=DEFAULT_TIMEOUT, transport=None):
        self.chat_url = chat_url or ""
        self.model = model or ""
        if not list_url and self.chat_url:
            # the documented discovery endpoint lives beside the configured base
            base = self.chat_url.split("/v1/")[0].rstrip("/")
            list_url = base + "/v1/gateway/list"
        self.list_url = list_url or ""
        self._token = token or ""
        self.timeout = timeout
        self._transport = transport or self._http_transport

    # ------------------------------------------------------------- factories

    @classmethod
    def from_env(cls, env=None, transport=None):
        env = os.environ if env is None else env
        chat_url = (env.get("SPRITE_CONNECTOR_URL") or "").strip()
        model = (env.get("SPRITE_MODEL") or "").strip()
        list_url = (env.get("SPRITE_GATEWAY_LIST_URL") or "").strip()
        token = (env.get("SPRITE_CONNECTOR_TOKEN") or "").strip()  # never logged
        if not chat_url or not model:
            return cls("", "", "", "", transport=transport)
        return cls(chat_url, model, list_url, token, transport=transport)

    @property
    def configured(self) -> bool:
        return bool(self.chat_url and self.model)

    def describe(self) -> dict:
        """Safe-to-show status: never includes the token."""
        return {
            "configured": self.configured,
            "model": self.model,
            "chat_url": self.chat_url,
            "list_url": self.list_url,
        }

    # ------------------------------------------------------------- transport

    def _http_transport(self, method, url, payload, headers, timeout):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, method=method)
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read(1 << 20).decode("utf-8", "replace")
                return resp.status, body
        except urllib.error.HTTPError as exc:  # surface status, not a stack trace
            return exc.code, exc.read(1 << 20).decode("utf-8", "replace")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ConnectorError(f"connector unreachable: {type(exc).__name__}") from exc

    def _headers(self):
        h = {"Accept": "application/json"}
        if self._token:
            h["Authorization"] = "Bearer " + self._token
        return h

    # ------------------------------------------------------------- gateway

    def list_models(self) -> list:
        if not self.list_url:
            raise ConnectorError("gateway list url not configured")
        status, body = self._transport(
            "GET", self.list_url, None, self._headers(), self.timeout
        )
        if status != 200:
            raise ConnectorError(f"gateway list HTTP {status}")
        try:
            data = json.loads(body)
        except ValueError as exc:
            raise ConnectorError("gateway list is not JSON") from exc
        raw = data.get("models") or data.get("data") or []
        out = []
        for item in raw:
            if isinstance(item, str):
                out.append(item)
            elif isinstance(item, dict):
                name = item.get("id") or item.get("name")
                if name:
                    out.append(str(name))
        return out

    def complete(self, prompt: str, system: str | None = None) -> str:
        if not self.configured:
            raise ConnectorError("connector not configured")
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        status, body = self._transport(
            "POST",
            self.chat_url,
            {"model": self.model, "messages": messages, "temperature": 0.4},
            self._headers(),
            self.timeout,
        )
        if status != 200:
            raise ConnectorError(f"connector HTTP {status}")
        try:
            data = json.loads(body)
            return str(data["choices"][0]["message"]["content"]).strip()
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ConnectorError("unexpected connector payload") from exc


SYSTEM_PROMPT = (
    "你是 Daylight（向阳）的温和教练。只根据用户提供的真实记录写一张当日经验卡，"
    "中文，120 字以内，四行：今天做了什么、学到什么、明天一小步、一句鼓励。"
    "不得添加记录里没有的成绩，不得编造数据，不评判，不空喊口号。"
)


def card_with_connector(connector, day, goals, checkins, streak):
    """Return (body, mode). Falls back to the local template on any failure."""
    local = build_card(day, goals, checkins, streak)
    if not connector.configured:
        return local, "local"
    facts = [
        f"日期：{day}",
        f"连续记录天数：{streak}",
        "小目标：" + ("；".join(
            f"{g['text']}（{'已完成' if g['done'] else '进行中'}）" for g in goals
        ) or "无"),
        "行动记录：" + ("；".join(
            f"{c['did']}" + (f" / 学到：{c['learned']}" if c["learned"] else "")
            for c in checkins
        ) or "无"),
    ]
    prompt = "以下是用户今天的真实记录，请写今日经验卡：\n" + "\n".join(facts)
    try:
        text = connector.complete(prompt, SYSTEM_PROMPT)
    except ConnectorError:
        return local, "local"
    if not text:
        return local, "local"
    return text, "connector"
