"""Doubao Seedream image-model client (豆包 Seedream).

A thin, user-key-bring-your-own client over ByteDance's Volcengine Ark image
generation endpoint. It honours the :class:`~coverlock.models.base.ImageModel`
contract: take a fully-composed prompt, return the raw bytes of a **text-free
main visual**. It never sees the platform rules, safe-zone, or title.

Config comes from the environment (never hard-coded):

* ``DOUBAO_API_KEY`` (or ``ARK_API_KEY``) — required; your Volcengine Ark key.
* ``DOUBAO_MODEL`` — override the model id (default ``doubao-seedream-3-0-t2i``).
* ``DOUBAO_BASE_URL`` — override the API base (default the Ark v3 endpoint).

Any missing key, transport error, non-2xx response, or unparseable payload is
surfaced as :class:`ModelError` — never a bare httpx/JSON exception — so the
offline core (and ``--model mock``) is never affected by a provider hiccup.
"""

from __future__ import annotations

import base64
import os
from typing import Any, Optional

import httpx

from .base import ImageModel, ImageRequest, ModelError

__all__ = ["DoubaoSeedreamModel"]

_DEFAULT_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
_DEFAULT_MODEL = "doubao-seedream-3-0-t2i"


def _nearest_size(width: int, height: int) -> str:
    """Map a requested pixel size to Seedream's accepted ``WxH`` size string.

    Seedream accepts a small set of sizes; we pick the closest portrait one so the
    aspect is preserved as well as possible. compose.py then enforces the exact
    compliant dimensions regardless, so this only needs to be *close*.
    """
    candidates = ["1024x1024", "864x1152", "1152x864", "1280x720", "720x1280"]
    target = width / height if height else 1.0
    best = candidates[0]
    best_err = float("inf")
    for c in candidates:
        cw, ch = (int(v) for v in c.split("x"))
        err = abs((cw / ch) - target)
        if err < best_err:
            best_err, best = err, c
    return best


class DoubaoSeedreamModel:
    """A :class:`ImageModel` backed by Volcengine Ark's Seedream text-to-image."""

    name = "doubao-seedream"

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 60.0,
    ) -> None:
        self.api_key = api_key or os.environ.get("DOUBAO_API_KEY") or os.environ.get("ARK_API_KEY")
        self.model = model or os.environ.get("DOUBAO_MODEL", _DEFAULT_MODEL)
        self.base_url = (base_url or os.environ.get("DOUBAO_BASE_URL", _DEFAULT_BASE_URL)).rstrip("/")
        self.timeout = timeout

    def _require_key(self) -> str:
        if not self.api_key:
            raise ModelError(
                "Doubao Seedream needs an API key. Set DOUBAO_API_KEY (or ARK_API_KEY) "
                "to your Volcengine Ark key, or run with --model mock to work offline."
            )
        return self.api_key

    def generate(self, request: ImageRequest) -> bytes:
        key = self._require_key()
        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": request.prompt,
            "size": _nearest_size(request.width, request.height),
            "response_format": "b64_json",
            "n": 1,
        }
        if request.seed is not None:
            payload["seed"] = int(request.seed)
        guidance = request.params.get("guidance")
        if guidance is not None:
            payload["guidance_scale"] = guidance

        url = f"{self.base_url}/images/generations"
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        try:
            resp = httpx.post(url, json=payload, headers=headers, timeout=self.timeout)
        except httpx.HTTPError as exc:
            raise ModelError(f"Doubao Seedream request failed: {exc}") from exc

        if resp.status_code != 200:
            raise ModelError(
                f"Doubao Seedream returned HTTP {resp.status_code}: {resp.text[:300]}"
            )
        try:
            data = resp.json()
        except ValueError as exc:
            raise ModelError(f"Doubao Seedream returned non-JSON body: {exc}") from exc

        return _extract_image_bytes(data)


def _extract_image_bytes(data: Any) -> bytes:
    """Pull image bytes from an Ark images response (b64_json or url)."""
    if not isinstance(data, dict):
        raise ModelError(f"Doubao Seedream response was not an object: {type(data).__name__}")

    items = data.get("data")
    if not isinstance(items, list) or not items:
        raise ModelError(f"Doubao Seedream response had no image data: {str(data)[:300]}")
    first = items[0]
    if not isinstance(first, dict):
        raise ModelError("Doubao Seedream response item was not an object")

    b64 = first.get("b64_json")
    if isinstance(b64, str) and b64:
        try:
            return base64.b64decode(b64)
        except (ValueError, TypeError) as exc:
            raise ModelError(f"Doubao Seedream b64 payload was not decodable: {exc}") from exc

    url = first.get("url")
    if isinstance(url, str) and url:
        try:
            img = httpx.get(url, timeout=60.0)
            img.raise_for_status()
            return img.content
        except httpx.HTTPError as exc:
            raise ModelError(f"Doubao Seedream image URL fetch failed: {exc}") from exc

    raise ModelError("Doubao Seedream response contained neither b64_json nor url")


# Static type-check aid: assert the client satisfies the protocol structurally.
_PROTOCOL_CHECK: ImageModel = DoubaoSeedreamModel(api_key="placeholder")  # noqa: F841
