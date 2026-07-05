"""L8 deterministic post-deploy health gate."""
from __future__ import annotations

import json
from urllib.error import URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

from ._redact import summarize
from .base import Delivery, Verdict


class HttpPostDeployGate:
    def __init__(self, health_path: str = "/", expect_json: dict | None = None):
        # Defaults come from config `options.postdeploy` (threaded by the registry) so the
        # spine can enforce a real health contract — e.g. {ok, supabaseConfigured} — by config
        # alone. A CLI flag overrides per-call; None means "use the configured default".
        self.health_path = health_path
        self.expect_json = expect_json

    def verify(self, delivery: Delivery, *, health_path: str | None = None,
               timeout_s: float = 10.0,
               expect_json: dict | None = None) -> Verdict:
        health_path = health_path if health_path is not None else self.health_path
        expect_json = expect_json if expect_json is not None else self.expect_json
        if delivery.status != "deployed" or not delivery.url:
            return Verdict(
                status="BLOCK",
                reasons=["delivery is not deployed or has no URL"],
                raw={"delivery": delivery.to_dict()},
            )

        url = urljoin(delivery.url.rstrip("/") + "/", health_path.lstrip("/"))
        # A Delivery artifact can arrive via `--delivery <file>` — untrusted input,
        # not necessarily freshly produced by this run's own deploy step. Restrict
        # to http(s): `urlopen` also honors `file://`, which would read local files
        # into the verdict body instead of checking a deployed app (codex review
        # finding).
        if urlsplit(url).scheme not in ("http", "https"):
            return Verdict(
                status="BLOCK",
                reasons=[f"delivery URL scheme is not http(s): {delivery.url!r}"],
                raw={"url": url},
            )
        try:
            req = Request(url, headers={"User-Agent": "sembl-stack-postdeploy"})
            with urlopen(req, timeout=timeout_s) as resp:
                code = getattr(resp, "status", None)
                if code is None:
                    code = resp.getcode()
                body = resp.read(2048).decode("utf-8", "replace")
        except (OSError, URLError) as exc:
            return Verdict(
                status="BLOCK",
                reasons=[f"post-deploy health check failed: {type(exc).__name__}"],
                raw={"url": url, "error": type(exc).__name__},
            )

        if not (200 <= int(code) < 400):
            return Verdict(
                status="BLOCK",
                reasons=[f"post-deploy health check returned HTTP {code}"],
                raw={"url": url, "status_code": int(code), "body": summarize(body)},
            )

        # A 2xx/3xx is necessary but not sufficient: a misconfigured app can return
        # 200 with a useless body. When the caller declares an expected payload, assert
        # the health JSON actually reports the app healthy (matches the app's own
        # postdeploy-health.mjs check, instead of status-only).
        if expect_json:
            try:
                payload = json.loads(body)
            except (ValueError, TypeError):
                return Verdict(
                    status="BLOCK",
                    reasons=["post-deploy health payload is not valid JSON"],
                    raw={"url": url, "status_code": int(code), "body": summarize(body)},
                )
            # Only the allowlisted expected keys are surfaced (health booleans the caller
            # declared) — never the full third-party payload, which may carry env-shaped values.
            mismatches = [
                f"{key}={payload.get(key)!r} (want {value!r})"
                for key, value in expect_json.items()
                if payload.get(key) != value
            ]
            if mismatches:
                return Verdict(
                    status="BLOCK",
                    reasons=[f"post-deploy health payload mismatch: {', '.join(mismatches)}"],
                    raw={"url": url, "status_code": int(code), "body": summarize(body)},
                )

        return Verdict(status="PASS", raw={"url": url, "status_code": int(code)})
