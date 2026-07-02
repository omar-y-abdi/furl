"""Transform modules for Headroom SDK."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Expose concrete types to static analysis while keeping runtime imports lazy.
    from headroom.transforms.base import Transform  # noqa: F401
    from headroom.transforms.cache_aligner import CacheAligner  # noqa: F401
    from headroom.transforms.content_detector import (  # noqa: F401
        ContentType,
        DetectionResult,
        detect_content_type,
    )
    from headroom.transforms.content_router import (  # noqa: F401
        CompressionStrategy,
        ContentRouter,
        ContentRouterConfig,
        RouterCompressionResult,
    )
    from headroom.transforms.cross_message_dedup import CrossMessageDeduper  # noqa: F401
    from headroom.transforms.diff_compressor import (  # noqa: F401
        DiffCompressionResult,
        DiffCompressor,
        DiffCompressorConfig,
    )
    from headroom.transforms.log_compressor import (  # noqa: F401
        LogCompressionResult,
        LogCompressor,
        LogCompressorConfig,
    )
    from headroom.transforms.pipeline import TransformPipeline  # noqa: F401
    from headroom.transforms.search_compressor import (  # noqa: F401
        SearchCompressionResult,
        SearchCompressor,
        SearchCompressorConfig,
    )
    from headroom.transforms.smart_crusher import SmartCrusher, SmartCrusherConfig  # noqa: F401

__all__ = [
    # Base
    "Transform",
    "TransformPipeline",
    # JSON compression
    "SmartCrusher",
    "SmartCrusherConfig",
    # Text compression (coding tasks)
    "ContentType",
    "DetectionResult",
    "detect_content_type",
    "SearchCompressor",
    "SearchCompressorConfig",
    "SearchCompressionResult",
    "LogCompressor",
    "LogCompressorConfig",
    "LogCompressionResult",
    "DiffCompressor",
    "DiffCompressorConfig",
    "DiffCompressionResult",
    # Content routing
    "ContentRouter",
    "ContentRouterConfig",
    "RouterCompressionResult",
    "CompressionStrategy",
    # Other transforms
    "CacheAligner",
    "CrossMessageDeduper",
]

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    # Base
    "Transform": ("headroom.transforms.base", "Transform"),
    "TransformPipeline": ("headroom.transforms.pipeline", "TransformPipeline"),
    # Anchor selection
    # JSON compression
    "SmartCrusher": ("headroom.transforms.smart_crusher", "SmartCrusher"),
    "SmartCrusherConfig": ("headroom.transforms.smart_crusher", "SmartCrusherConfig"),
    # Text compression (coding tasks)
    "ContentType": ("headroom.transforms.content_detector", "ContentType"),
    "DetectionResult": ("headroom.transforms.content_detector", "DetectionResult"),
    "detect_content_type": ("headroom.transforms.content_detector", "detect_content_type"),
    "SearchCompressor": ("headroom.transforms.search_compressor", "SearchCompressor"),
    "SearchCompressorConfig": (
        "headroom.transforms.search_compressor",
        "SearchCompressorConfig",
    ),
    "SearchCompressionResult": (
        "headroom.transforms.search_compressor",
        "SearchCompressionResult",
    ),
    "LogCompressor": ("headroom.transforms.log_compressor", "LogCompressor"),
    "LogCompressorConfig": ("headroom.transforms.log_compressor", "LogCompressorConfig"),
    "LogCompressionResult": ("headroom.transforms.log_compressor", "LogCompressionResult"),
    "DiffCompressor": ("headroom.transforms.diff_compressor", "DiffCompressor"),
    "DiffCompressorConfig": ("headroom.transforms.diff_compressor", "DiffCompressorConfig"),
    "DiffCompressionResult": (
        "headroom.transforms.diff_compressor",
        "DiffCompressionResult",
    ),
    # Content routing
    "ContentRouter": ("headroom.transforms.content_router", "ContentRouter"),
    "ContentRouterConfig": ("headroom.transforms.content_router", "ContentRouterConfig"),
    "RouterCompressionResult": (
        "headroom.transforms.content_router",
        "RouterCompressionResult",
    ),
    "CompressionStrategy": ("headroom.transforms.content_router", "CompressionStrategy"),
    # Other transforms
    "CacheAligner": ("headroom.transforms.cache_aligner", "CacheAligner"),
    "CrossMessageDeduper": (
        "headroom.transforms.cross_message_dedup",
        "CrossMessageDeduper",
    ),
}


def __getattr__(name: str) -> object:
    if name == "__path__":
        raise AttributeError(name)

    try:
        module_name, attr_name = _LAZY_EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc

    module = import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
