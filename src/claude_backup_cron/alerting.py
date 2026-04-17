"""Best-effort webhook alerting on backup failure.

Posts a short JSON payload to a URL (Discord/Slack-shape compatible, i.e.
``{"content": "..."}``). Uses the stdlib ``urllib`` so the runtime has
zero third-party deps. Network failures are swallowed — we never want an
unreachable webhook to turn into a second alert.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Final

_LOG = logging.getLogger(__name__)
_TIMEOUT_S: Final = 10


def post(webhook_url: str, message: str) -> bool:
    """Post ``message`` to ``webhook_url`` (Discord/Slack JSON shape).

    Returns True on HTTP 2xx, False otherwise. Never raises — the caller
    is in the middle of handling a different failure and cannot afford a
    cascading exception from a dead webhook.
    """
    if not webhook_url:
        return False
    payload = json.dumps({"content": message[:1900]}).encode("utf-8")
    req = urllib.request.Request(  # noqa: S310 — scheme is documented in config, not user-supplied at runtime.
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:  # noqa: S310
            return bool(200 <= resp.status < 300)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        _LOG.warning("alerting webhook failed: %s", exc)
        return False
