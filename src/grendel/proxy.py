"""The LLM-proxy: a zero-touch OpenAI-compatible endpoint that red-teams a real agent.

The user points their agent's ``base_url`` at ``grendel proxy --serve`` (the only change they
make). For each chat/completions call the agent makes, Grendel injects an attack into the outgoing
prompt, forwards the call to the routed upstream provider carrying the agent's own key, reads the
returned ``tool_calls`` (tool intent) + text, scores the exchange with the existing Scorer, records
an ``AttemptRecord``, and returns the upstream response to the agent unchanged.

Design: pure helpers (``select_route`` / ``inject_attack`` / ``build_upstream_request`` /
``extract_outcome``) + an async ``ProxySession`` (``handle``) that is fully offline-testable with an
injected httpx client. The stdlib server (``make_server`` / ``serve``) runs a SINGLE persistent
asyncio loop in a background thread and dispatches every request onto it via
``run_coroutine_threadsafe`` — so the one httpx client is never used across loops.
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx

from .attacks import Attack, Surface
from .config import GrendelConfig, ProxyConfig
from .errors import ConfigError
from .logging_setup import get_logger
from .records import AttemptRecord, RunRecord, RunStatus, make_run_record
from .scoring import Scorer
from .targets.base import AdapterResponse
from .targets.providers import API_PATHS, ProviderPreset, resolve_provider

log = get_logger("proxy")


# --- pure helpers -----------------------------------------------------------------------------
def select_route(path: str, proxy: ProxyConfig) -> str | None:
    """Return the provider for the longest route path-prefix that ``path`` starts with (or None)."""
    best: str | None = None
    best_len = -1
    for prefix, provider in proxy.routes.items():
        if path.startswith(prefix) and len(prefix) > best_len:
            best, best_len = provider, len(prefix)
    return best


def inject_attack(body: dict, attack: Attack) -> dict:
    """Return a deep copy of ``body`` with the attack payload injected per ``attack.surface``.

    ``prompt`` (and any non-tool-output surface) appends a user message; ``tool-output`` appends a
    synthesized tool message (the indirect-injection vector). The input body is never mutated.
    """
    out = copy.deepcopy(body)
    messages = out.get("messages")
    if not isinstance(messages, list):
        messages = []
        out["messages"] = messages
    if attack.surface == Surface.TOOL_OUTPUT:
        # A bare role="tool" message is invalid to OpenAI unless it follows an assistant
        # message with a matching tool_call — inject the pair so the request stays valid and
        # the payload faithfully arrives as (malicious) tool output (indirect injection).
        messages.append(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "grendel-injected",
                        "type": "function",
                        "function": {"name": "grendel_injected_tool", "arguments": "{}"},
                    }
                ],
            }
        )
        messages.append(
            {"role": "tool", "content": attack.payload, "tool_call_id": "grendel-injected"}
        )
    else:  # prompt / rag / mcp-desc -> appended user turn (documented fallback)
        messages.append({"role": "user", "content": attack.payload})
    return out


def _upstream_headers(preset: ProviderPreset, incoming: dict) -> dict[str, str]:
    """Provider default headers + the agent's own auth headers forwarded verbatim (no Grendel key)."""  # noqa: E501
    headers = dict(preset.default_headers)
    # Case-insensitive lookup of the agent's forwardable auth headers.
    lower = {k.lower(): v for k, v in incoming.items()}
    for name in ("authorization", "x-api-key", "anthropic-version", "openai-organization"):
        if name in lower:
            headers[name] = lower[name]
    return headers


def build_upstream_request(
    preset: ProviderPreset, base_url: str, incoming_headers: dict, body: dict
) -> tuple[str, dict, dict]:
    """Compute (url, headers, body) for the upstream call. Grendel injects no key of its own."""
    suffix = API_PATHS.get(preset.api_style, API_PATHS["openai"])
    url = f"{base_url.rstrip('/')}{suffix}"
    return url, _upstream_headers(preset, incoming_headers), body


def _openai_tool_calls(message: dict) -> list[dict] | None:
    calls = message.get("tool_calls")
    if calls is None:
        return None
    out = []
    for i, call in enumerate(calls):
        fn = (call or {}).get("function") or {}
        raw_args = fn.get("arguments")
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
        except (ValueError, TypeError):
            args = {}
        out.append({"name": fn.get("name", "?"), "args": args, "ordinal": i})
    return out


def extract_outcome(api_style: str, upstream_json: dict) -> tuple[str, list[dict] | None]:
    """Return (text, normalized tool_calls) from an upstream response.

    ``tool_calls`` is None when the response exposes no tool-calls key at all (tri-state, matching
    ``AdapterResponse.tool_calls``): [] means the model declined; a list is the observed intent.
    """
    if api_style == "anthropic":
        blocks = upstream_json.get("content")
        if not isinstance(blocks, list):
            return "", None
        text = ""
        tool_calls: list[dict] = []
        for block in blocks:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text" and not text:
                text = block.get("text") or ""
            elif btype == "tool_use":
                tool_calls.append(
                    {
                        "name": block.get("name", "?"),
                        "args": block.get("input") or {},
                        "ordinal": len(tool_calls),
                    }
                )
        has_tools = any(isinstance(b, dict) and b.get("type") == "tool_use" for b in blocks)
        return text, (tool_calls if has_tools else None)

    if api_style == "ollama":
        message = upstream_json.get("message") or {}
        return message.get("content") or "", _openai_tool_calls(message)

    # openai (and openai-compatible / openrouter)
    choice = (upstream_json.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    return message.get("content") or "", _openai_tool_calls(message)


def _error_body(message: str) -> bytes:
    return json.dumps({"error": {"message": message, "type": "grendel_proxy_error"}}).encode(
        "utf-8"
    )


# --- the async session ------------------------------------------------------------------------
class ProxySession:
    """Holds the run state for a serving proxy: config, attacks, scorer, client, and the record."""

    def __init__(
        self,
        config: GrendelConfig,
        attacks: list[Attack],
        *,
        client: httpx.AsyncClient,
        scorer: Scorer | None = None,
        record: RunRecord | None = None,
        record_path: Path | None = None,
    ) -> None:
        if not attacks:
            raise ValueError("ProxySession requires at least one attack to inject")
        self.config = config
        self.attacks = attacks
        self._client = client
        self.scorer = scorer or Scorer()
        provider = next(iter(config.proxy.routes.values()), "proxy")
        self.record = record or make_run_record(
            target_name="proxy",
            provider=provider,
            model="(proxied)",
            config=config,
            pack_ids=[a.id for a in attacks],
        )
        self.record.status = RunStatus.RUNNING
        self._i = 0
        self._lock = threading.Lock()
        # Incremental persistence: if set, the record is written after EVERY attempt, so an
        # ungraceful stop (kill / crash) never loses data. Guarded by the same lock.
        self._record_path = Path(record_path) if record_path is not None else None

    def enable_persistence(self, path) -> None:
        """Write the record after every attempt to ``path`` (crash-safe; set post-construction)."""
        self._record_path = Path(path)

    def _persist(self) -> None:
        if self._record_path is None:
            return
        with self._lock:
            self._record_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._record_path.with_suffix(self._record_path.suffix + ".tmp")
            tmp.write_text(self.record.to_json(), encoding="utf-8")
            os.replace(tmp, self._record_path)

    def _next_attack(self) -> Attack:
        with self._lock:
            attack = self.attacks[self._i % len(self.attacks)]
            self._i += 1
        return attack

    async def aclose(self) -> None:
        await self._client.aclose()

    async def handle(self, path: str, headers: dict, body_bytes: bytes) -> tuple[int, dict, bytes]:
        json_headers = {"Content-Type": "application/json"}
        provider = select_route(path, self.config.proxy)
        if provider is None:
            return 404, json_headers, _error_body(f"no route matches path {path!r}")
        try:
            body = json.loads(body_bytes) if body_bytes else {}
        except ValueError as exc:
            return 400, json_headers, _error_body(f"invalid JSON body: {exc}")
        if not isinstance(body, dict) or not isinstance(body.get("messages"), list):
            return 400, json_headers, _error_body("expected an OpenAI chat request with 'messages'")

        attack = self._next_attack()
        try:
            preset = resolve_provider(provider, self.config)
            base_url = preset.base_url
            if not base_url:
                raise ConfigError(
                    f"route provider {provider!r} has no base_url; configure a custom provider "
                    f"base_url for it"
                )
        except ConfigError as exc:
            self._append_error(attack, str(exc))
            return 502, json_headers, _error_body(str(exc))

        injected = inject_attack(body, attack)
        url, up_headers, up_body = build_upstream_request(preset, base_url, headers, injected)

        start = time.perf_counter()
        try:
            resp = await self._client.post(url, json=up_body, headers=up_headers)
        except httpx.HTTPError as exc:
            self._append_error(attack, f"upstream request failed: {exc}")
            return 502, json_headers, _error_body(f"upstream request failed: {exc}")
        latency_ms = (time.perf_counter() - start) * 1000.0

        if not (200 <= resp.status_code < 300):
            self._append_error(attack, f"upstream HTTP {resp.status_code}: {resp.text[:200]}")
            return resp.status_code, dict(resp.headers), resp.content

        try:
            upstream_json = resp.json()
        except ValueError as exc:
            self._append_error(attack, f"upstream returned non-JSON: {exc}")
            return 502, json_headers, _error_body(f"upstream returned non-JSON: {exc}")

        text, tool_calls = extract_outcome(preset.api_style, upstream_json)
        adapter_resp = AdapterResponse(
            text=text,
            raw=upstream_json,
            model=up_body.get("model", "") or "",
            provider=preset.name,
            tool_calls=tool_calls,
            latency_ms=latency_ms,
        )
        result = await self.scorer.score_async(attack, response_text=text, response=adapter_resp)
        self.record.attempts.append(
            AttemptRecord(
                attack_id=attack.id,
                category=attack.category,
                owasp=attack.owasp,
                atlas=attack.atlas,
                prompt=attack.payload,
                response_text=text,
                tool_calls=list(tool_calls) if tool_calls is not None else [],
                tool_observed=tool_calls is not None,
                verdict=result.verdict,
                score_tier=result.detail.tier if result.detail else None,
                score_detail=result.detail,
                latency_ms=latency_ms,
            )
        )
        self._persist()
        # Pass the upstream reply back to the agent UNCHANGED (zero-touch).
        return resp.status_code, dict(resp.headers), resp.content

    def _append_error(self, attack: Attack, message: str) -> None:
        from .records import Verdict

        self.record.attempts.append(
            AttemptRecord(
                attack_id=attack.id,
                category=attack.category,
                owasp=attack.owasp,
                atlas=attack.atlas,
                prompt=attack.payload,
                verdict=Verdict.ERROR,
                error=message,
            )
        )
        self._persist()


def startup_banner(session: ProxySession, host: str, port: int) -> str:
    """Deterministic startup banner (bound address, routes, attack count, agent base_url hint)."""
    routes = session.config.proxy.routes
    lines = [
        f"grendel proxy serving on http://{host}:{port}",
        f"  attacks: {len(session.attacks)} injected in rotation",
        "  routes:",
    ]
    for prefix in sorted(routes):
        lines.append(
            f"    point your agent base_url at http://{host}:{port}{prefix} -> {routes[prefix]}"
        )
    lines.append("  (Ctrl-C to stop; the run record is written on shutdown)")
    return "\n".join(lines)


# --- the stdlib server (single persistent loop) -----------------------------------------------
def _make_handler(session: ProxySession, loop: asyncio.AbstractEventLoop):
    class _ProxyHandler(BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:  # noqa: D401 — silence default stderr logging
            log.debug("proxy request", extra={"args": args})

        def _write(self, status: int, headers: dict, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", headers.get("Content-Type", "application/json"))
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler API
            try:
                raw_len = self.headers.get("Content-Length") or "0"
                try:
                    length = int(raw_len)
                except ValueError:
                    self._write(400, {}, _error_body(f"invalid Content-Length header {raw_len!r}"))
                    return
                body = self.rfile.read(length) if length > 0 else b""
                fut = asyncio.run_coroutine_threadsafe(
                    session.handle(self.path, dict(self.headers), body), loop
                )
                status, headers, out = fut.result(timeout=120)
            except Exception as exc:  # noqa: BLE001 — never let an exception escape the handler
                status, headers, out = (
                    500,
                    {"Content-Type": "application/json"},
                    _error_body(str(exc)),
                )
            self._write(status, headers, out)

        def _method_not_allowed(self) -> None:
            # Drain any request body first so the client isn't reset mid-send (ReadError).
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length > 0:
                    self.rfile.read(length)
            except (ValueError, OSError):
                pass
            self._write(405, {}, _error_body("method not allowed; POST chat/completions only"))

        # Every non-POST verb → 405 (not the stdlib default 501).
        do_GET = _method_not_allowed  # noqa: N815
        do_PUT = _method_not_allowed  # noqa: N815
        do_DELETE = _method_not_allowed  # noqa: N815
        do_PATCH = _method_not_allowed  # noqa: N815
        do_HEAD = _method_not_allowed  # noqa: N815
        do_OPTIONS = _method_not_allowed  # noqa: N815

    return _ProxyHandler


def make_server(session: ProxySession, host: str, port: int) -> ThreadingHTTPServer:
    """Bind a threaded server backed by a single persistent asyncio loop in a daemon thread.

    All ``session.handle`` coroutines run on this one loop, so the session's single httpx client is
    never used across loops.
    """
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    httpd = ThreadingHTTPServer((host, port), _make_handler(session, loop))
    httpd._grendel_loop = loop  # type: ignore[attr-defined]
    httpd._grendel_thread = thread  # type: ignore[attr-defined]
    httpd._grendel_session = session  # type: ignore[attr-defined]
    return httpd


def stop_server(httpd: ThreadingHTTPServer) -> None:
    """Shut the server down, close the session client on its loop, then stop the loop."""
    loop = httpd._grendel_loop  # type: ignore[attr-defined]
    session = httpd._grendel_session  # type: ignore[attr-defined]
    httpd.shutdown()
    try:
        asyncio.run_coroutine_threadsafe(session.aclose(), loop).result(timeout=5)
    except Exception:  # noqa: BLE001 — best-effort client close
        log.debug("proxy client close failed; ignoring")
    loop.call_soon_threadsafe(loop.stop)
    httpd._grendel_thread.join(timeout=5)  # type: ignore[attr-defined]


def serve(session: ProxySession, host: str, port: int) -> RunRecord:
    """Serve until interrupted (Ctrl-C), then shut down and return the recorded run."""
    httpd = make_server(session, host, port)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop_server(httpd)
    session.record.status = RunStatus.COMPLETED
    return session.record
