"""Qwen-Image model client (阿里 通义万相 / Qwen-Image).

A thin, bring-your-own-key client over Alibaba DashScope's text-to-image
endpoint. Like every CoverLock model it honours the
:class:`~coverlock.models.base.ImageModel` contract: prompt in → raw bytes of a
**text-free main visual** out, with zero knowledge of platform rules or titles.

DashScope's image generation is asynchronous: you POST a task and then poll a
task-status endpoint until it succeeds, at which point it returns an image URL to
download. This client encapsulates that flow behind one blocking ``generate``.

Config (from the environment, never hard-coded):

* ``DASHSCOPE_API_KEY`` (or ``QWEN_API_KEY``) — required; your DashScope key.
* ``QWEN_MODEL`` — override the model id (default ``wanx2.1-t2i-turbo``).
* ``QWEN_BASE_URL`` — override the API base (default the DashScope endpoint).

Any missing key, transport error, task failure, timeout, or unparseable payload
surfaces as :class:`ModelError` — never a bare provider exception.
"""

from __future__ import annotations

import os
import time
from typing import Any, Optional

import httpx

from .base import ImageModel, ImageRequest, ModelError

__all__ = ["QwenImageModel"]

_DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/api/v1"
_DEFAULT_MODEL = "wanx2.1-t2i-turbo"


def _nearest_size(width: int, height: int) -> str:
    """Map a requested pixel size to a DashScope-accepted ``W*H`` size string."""
    candidates = ["1024*1024", "768*1152", "1152*768", "720*1280", "1280*720"]
    target = width / height if height else 1.0
    best = candidates[0]
    best_err = float("inf")
    for c in candidates:
        cw, ch = (int(v) for v in c.split("*"))
        err = abs((cw / ch) - target)
        if err < best_err:
            best_err, best = err, c
    return best


class QwenImageModel:
    """A :class:`ImageModel` backed by DashScope's Qwen/Wanx text-to-image."""

    name = "qwen-image"

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 60.0,
        poll_interval: float = 2.0,
        max_poll_seconds: float = 120.0,
    ) -> None:
        self.api_key = api_key or os.environ.get("DASHSCOPE_API_KEY") or os.environ.get("QWEN_API_KEY")
        self.model = model or os.environ.get("QWEN_MODEL", _DEFAULT_MODEL)
        self.base_url = (base_url or os.environ.get("QWEN_BASE_URL", _DEFAULT_BASE_URL)).rstrip("/")
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.max_poll_seconds = max_poll_seconds

    def _require_key(self) -> str:
        if not self.api_key:
            raise ModelError(
                "Qwen-Image needs an API key. Set DASHSCOPE_API_KEY (or QWEN_API_KEY) "
                "to your Alibaba DashScope key, or run with --model mock to work offline."
            )
        return self.api_key

    def generate(self, request: ImageRequest) -> bytes:
        key = self._require_key()
        task_id = self._submit_task(key, request)
        image_url = self._await_result(key, task_id)
        return self._download(image_url)

    # -- steps -------------------------------------------------------------- #
    def _submit_task(self, key: str, request: ImageRequest) -> str:
        url = f"{self.base_url}/services/aigc/text2image/image-synthesis"
        input_block: dict[str, Any] = {"prompt": request.prompt}
        params: dict[str, Any] = {"size": _nearest_size(request.width, request.height), "n": 1}
        if request.seed is not None:
            params["seed"] = int(request.seed)
        payload = {"model": self.model, "input": input_block, "parameters": params}
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "X-DashScope-Async": "enable",
        }
        try:
            resp = httpx.post(url, json=payload, headers=headers, timeout=self.timeout)
        except httpx.HTTPError as exc:
            raise ModelError(f"Qwen-Image task submission failed: {exc}") from exc
        if resp.status_code != 200:
            raise ModelError(f"Qwen-Image submit returned HTTP {resp.status_code}: {resp.text[:300]}")
        try:
            data = resp.json()
        except ValueError as exc:
            raise ModelError(f"Qwen-Image submit returned non-JSON body: {exc}") from exc
        task_id = (data.get("output") or {}).get("task_id")
        if not task_id:
            raise ModelError(f"Qwen-Image submit returned no task_id: {str(data)[:300]}")
        return str(task_id)

    def _await_result(self, key: str, task_id: str) -> str:
        url = f"{self.base_url}/tasks/{task_id}"
        headers = {"Authorization": f"Bearer {key}"}
        deadline = time.monotonic() + self.max_poll_seconds
        while True:
            try:
                resp = httpx.get(url, headers=headers, timeout=self.timeout)
            except httpx.HTTPError as exc:
                raise ModelError(f"Qwen-Image task poll failed: {exc}") from exc
            if resp.status_code != 200:
                raise ModelError(f"Qwen-Image poll returned HTTP {resp.status_code}: {resp.text[:300]}")
            try:
                data = resp.json()
            except ValueError as exc:
                raise ModelError(f"Qwen-Image poll returned non-JSON body: {exc}") from exc

            output = data.get("output") or {}
            status = str(output.get("task_status", "")).upper()
            if status == "SUCCEEDED":
                return _first_image_url(output)
            if status in {"FAILED", "CANCELED", "UNKNOWN"}:
                raise ModelError(
                    f"Qwen-Image task {task_id} ended {status}: {str(output)[:300]}"
                )
            if time.monotonic() >= deadline:
                raise ModelError(
                    f"Qwen-Image task {task_id} did not finish within {self.max_poll_seconds:.0f}s"
                )
            time.sleep(self.poll_interval)

    def _download(self, image_url: str) -> bytes:
        try:
            resp = httpx.get(image_url, timeout=self.timeout)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise ModelError(f"Qwen-Image download failed: {exc}") from exc
        return resp.content


def _first_image_url(output: Any) -> str:
    if not isinstance(output, dict):
        raise ModelError("Qwen-Image output was not an object")
    results = output.get("results")
    if not isinstance(results, list) or not results:
        raise ModelError(f"Qwen-Image succeeded but returned no results: {str(output)[:300]}")
    first = results[0]
    url = first.get("url") if isinstance(first, dict) else None
    if not url:
        raise ModelError(f"Qwen-Image result had no image url: {str(first)[:300]}")
    return str(url)


# Static type-check aid: assert the client satisfies the protocol structurally.
_PROTOCOL_CHECK: ImageModel = QwenImageModel(api_key="placeholder")  # noqa: F841
