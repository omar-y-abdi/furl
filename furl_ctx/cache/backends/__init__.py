"""Storage backends for CompressionStore.

This module provides pluggable storage backends for CCR (Compress-Cache-Retrieve).
The default is in-memory storage; a durable SQLite backend ships for deployments
that need entries to survive process restarts and to be retrievable across
processes (the MCP server defaults to it). Custom backends can be implemented
for anything else (Redis, MongoDB, distributed caches, ...).

Usage:
    from furl_ctx.cache.backends import InMemoryBackend, CompressionStoreBackend
    from furl_ctx.cache.backends.sqlite import SqliteBackend
    from furl_ctx.cache.compression_store import CompressionStore

    # Use default in-memory backend
    store = CompressionStore()

    # Use the durable SQLite backend
    store = CompressionStore(backend=SqliteBackend())

    # Use custom backend
    class MyBackend:
        # Implement CompressionStoreBackend protocol
        ...
    store = CompressionStore(backend=MyBackend())
"""

from .base import CompressionStoreBackend
from .memory import InMemoryBackend
from .sqlite import SqliteBackend

__all__ = [
    "CompressionStoreBackend",
    "InMemoryBackend",
    "SqliteBackend",
]
