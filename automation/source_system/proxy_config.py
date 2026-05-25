"""Centralized Playwright proxy configuration helper.

Provides optional proxy configuration for Playwright browser launches
based on the ``PLAYWRIGHT_PROXY_SERVER`` environment variable.

Usage::

    from automation.source_system.proxy_config import get_playwright_proxy

    proxy = get_playwright_proxy()  # None or {"server": "socks5://..."}
    browser = playwright.chromium.launch(
        **({"proxy": proxy} if proxy else {}),
        args=["--ignore-certificate-errors"],
    )
"""

from __future__ import annotations

import os
from typing import Any


def get_playwright_proxy() -> dict[str, Any] | None:
    """Return Playwright proxy configuration or ``None``.

    Reads ``PLAYWRIGHT_PROXY_SERVER`` from the environment.

    Returns:
        A dict ``{"server": "<value>"}`` when the env var is set and non-empty,
        or ``None`` when the env var is absent or empty.
    """
    raw = os.environ.get("PLAYWRIGHT_PROXY_SERVER", "")
    if not raw:
        return None
    return {"server": raw}
