"""
NetBox inventory plugin.

This is a minimal NetBox shaped http client approach with no third party deps.

Design
NetBox schemas vary. This plugin expects a simplified endpoint that returns
a compatible json payload with the same schema as the static plugin.

That keeps normalization identical while still demonstrating a realistic plugin.

You can adapt parse logic later to match real NetBox endpoints.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.request import Request, urlopen

from datacenter_orchestrator.inventory.plugins.base import InventoryPlugin
from datacenter_orchestrator.inventory.plugins.static import StaticInventoryPlugin
from datacenter_orchestrator.inventory.store import InventoryStore


class HttpClient(Protocol):
    """Simple http client interface for testability."""

    def get_json(self, url: str, headers: dict[str, str]) -> dict[str, Any]:
        """Return parsed json for the given url."""


@dataclass
class UrllibHttpClient(HttpClient):
    """Default http client using urllib."""

    timeout_seconds: int = 10

    def get_json(self, url: str, headers: dict[str, str]) -> dict[str, Any]:
        req = Request(url, headers=headers, method="GET")
        with urlopen(req, timeout=self.timeout_seconds) as resp:
            body = resp.read().decode("utf-8")
        return json.loads(body)


@dataclass(frozen=True)
class NetBoxInventoryPlugin(InventoryPlugin):
    """
    Load inventory from a NetBox shaped endpoint.

    inventory_url should return the same schema used by StaticInventoryPlugin.
    token is optional. If provided, it is sent as an Authorization header.

    For real NetBox, you would usually call api dcim devices and then transform.
    This plugin keeps a stable minimal contract for now.
    """

    inventory_url: str
    token: str | None = None
    http: HttpClient = UrllibHttpClient()

    def load(self) -> InventoryStore:
        headers: dict[str, str] = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Token {self.token}"

        data = self.http.get_json(self.inventory_url, headers=headers)

        temp_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".json",
                delete=False,
                encoding="utf-8",
            ) as f:
                f.write(json.dumps(data))
                temp_path = f.name

            return StaticInventoryPlugin(path=Path(temp_path)).load()
        finally:
            if temp_path:
                try:
                    Path(temp_path).unlink()
                except OSError:
                    pass
