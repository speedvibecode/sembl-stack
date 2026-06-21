"""L8 deterministic post-deploy health gate."""
from __future__ import annotations

import json
from urllib.error import URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from .base import Delivery, Verdict


class HttpPostDeployGate:
    def verify(self, delivery: Delivery, *, health_path: str = "/",
               timeout_s: float = 10.0,
               expect_json: dict | None = None) -> Verdict:
        if delivery.status != "deployed" or not delivery.url:
            return Verdict(
                status="BLOCK",
                reasons=["delivery is not deployed or has no URL"],
                raw={"delivery": delivery.to_dict()},
            )

        url = urljoin(delivery.url.rstrip("/") + "/", health_path.lstrip("/"))
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
                reasons=[f"post-deploy health check failed: {exc}"],
                raw={"url": url, "error": repr(exc)},
            )

        if not (200 <= int(code) < 400):
            return Verdict(
                status="BLOCK",
                reasons=[f"post-deploy health check returned HTTP {code}"],
                raw={"url": url, "status_code": int(code), "body": body},
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
                    raw={"url": url, "status_code": int(code), "body": body},
                )
            mismatches = [
                f"{key}={payload.get(key)!r} (want {value!r})"
                for key, value in expect_json.items()
                if payload.get(key) != value
            ]
            if mismatches:
                return Verdict(
                    status="BLOCK",
                    reasons=[f"post-deploy health payload mismatch: {', '.join(mismatches)}"],
                    raw={"url": url, "status_code": int(code), "payload": payload},
                )

        return Verdict(status="PASS", raw={"url": url, "status_code": int(code)})
