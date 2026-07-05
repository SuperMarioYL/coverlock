"""Pluggable image-model registry.

Models are looked up by name (``"mock"``, ``"doubao-seedream"``,
``"qwen-image"``). The offline :class:`~coverlock.models.mock.MockModel` is always
available so the pipeline runs with no key. Real provider clients register lazily
— they are only imported when actually requested — so a missing optional client
(or an import-time issue in a provider module) never breaks the offline core.

Public API::

    from coverlock.models import get_model, available_models
    model = get_model("mock")
    png_bytes = model.generate(request)
"""

from __future__ import annotations

from typing import Callable

from .base import ImageModel, ImageRequest, ModelError
from .mock import MockModel

__all__ = [
    "ImageModel",
    "ImageRequest",
    "ModelError",
    "MockModel",
    "get_model",
    "available_models",
    "register_model",
]

# Factories for models that are always safe to construct (no key, no network).
_EAGER: dict[str, Callable[[], ImageModel]] = {
    "mock": MockModel,
}

# Aliases → canonical names, so both the pack target and CLI flag resolve.
_ALIASES: dict[str, str] = {
    "doubao": "doubao-seedream",
    "seedream": "doubao-seedream",
    "qwen": "qwen-image",
    "qwen-image": "qwen-image",
}

# Lazily-imported provider clients: name -> (module, class). Imported only on
# first request so an absent/broken optional client can't break `--model mock`.
_LAZY: dict[str, tuple[str, str]] = {
    "doubao-seedream": ("coverlock.models.doubao", "DoubaoSeedreamModel"),
    "qwen-image": ("coverlock.models.qwen", "QwenImageModel"),
}


def register_model(name: str, factory: Callable[[], ImageModel]) -> None:
    """Register (or override) an eagerly-available model factory by name."""
    _EAGER[name] = factory


def _canonical(name: str) -> str:
    key = name.strip().lower()
    return _ALIASES.get(key, key)


def get_model(name: str) -> ImageModel:
    """Resolve a model by name (aliases accepted) and return an instance.

    Raises:
        ModelError: if the name is unknown, or a provider client can't be imported.
    """
    canonical = _canonical(name)

    if canonical in _EAGER:
        return _EAGER[canonical]()

    if canonical in _LAZY:
        module_path, cls_name = _LAZY[canonical]
        try:
            import importlib

            module = importlib.import_module(module_path)
            cls = getattr(module, cls_name)
        except Exception as exc:  # provider client missing or broken
            raise ModelError(
                f"model {name!r} is not available: {exc}. "
                f"Use --model mock to run offline."
            ) from exc
        return cls()

    raise ModelError(
        f"unknown model {name!r}; available: {available_models()}"
    )


def available_models() -> list[str]:
    """List every model name that can be requested (eager + lazy providers)."""
    names = set(_EAGER) | set(_LAZY)
    return sorted(names)
