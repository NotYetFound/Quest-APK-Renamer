"""Shared HTTPS trust configuration for frozen and source installations."""

from __future__ import annotations

import ssl
from typing import Any
from urllib.request import Request, urlopen

import certifi


def trusted_ssl_context() -> ssl.SSLContext:
    """Use the platform trust store plus the CA bundle shipped with the app."""

    context = ssl.create_default_context()
    context.load_verify_locations(cafile=certifi.where())
    return context


def trusted_urlopen(request: Request, timeout: float) -> Any:
    """Open an HTTPS request with trust that also works in frozen packages."""

    return urlopen(request, timeout=timeout, context=trusted_ssl_context())
