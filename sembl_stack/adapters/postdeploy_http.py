"""L8 deterministic post-deploy health gate."""
from __future__ import annotations

from urllib.error import URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from .base import Delivery, Verdict


class HttpPostDeployGate:
    def verify(self, delivery: Delivery, *, health_path: str = "/",
               timeout_s: float = 10.0) -> Verdict:
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
                body = resp.read(512).decode("utf-8", "replace")
        except (OSError, URLError) as exc:
            return Verdict(
                status="BLOCK",
                reasons=[f"post-deploy health check failed: {exc}"],
                raw={"url": url, "error": repr(exc)},
            )

        if 200 <= int(code) < 400:
            return Verdict(status="PASS", raw={"url": url, "status_code": int(code)})
        return Verdict(
            status="BLOCK",
            reasons=[f"post-deploy health check returned HTTP {code}"],
            raw={"url": url, "status_code": int(code), "body": body},
        )
