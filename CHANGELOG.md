# Changelog

All notable changes to Furl will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Nothing yet.

## [0.26.0] - 2026-07-02

### Rename and history note

This is the first release under the **Furl** name. The project was previously
named Headroom; the PyPI package is now `furl-ctx` and the Python import is
`furl_ctx`. The git history was squashed on 2026-07-02 — all pre-rename commits
were collapsed into a single root commit ("Initial commit (inherited Headroom SDK
base)"). The pre-rename release log no longer maps to this repository's commits
and has been retired.

### What ships today

**Public API** (`from furl_ctx import compress, CompressConfig, CompressResult`)

- `compress(messages, model=..., config=...)` — single entry point for context compression
- `CompressConfig` — typed configuration for compression behaviour
- `CompressResult` — typed result carrying compressed messages and stats

**Pipeline transforms**

- `CacheAligner` — aligns content to prompt-cache prefix boundaries
- `CrossMessageDeduper` — cross-message deduplication with byte-verified CCR
  pointer replacement
- `ContentRouter` — strategy-based routing of content to compressors

**Compressors**

- `SmartCrusher` — Rust-backed (pyo3) compressor: JSON-array crushing and
  lossless column-encoding compaction suite
- `SearchCompressor` — optimised for tool-output search result blocks
- `LogCompressor` — log and trace output compressor
- `DiffCompressor` — diff and patch output compressor

**CCR (Compressed-Content Recovery)**

- Byte-exact recovery of compressed content via `<<ccr:HASH>>` inline markers
- In-memory CCR store; no external persistence required

**MCP server**

- Entrypoint: `python -m furl_ctx.ccr.mcp_server`
- Tools: `furl_compress`, `furl_retrieve`, `furl_stats`
- Opt-in: `furl_read` (behind a feature flag)

**Tokenization**

- tiktoken only (cl100k_base / o200k_base)

**Rust extension**

- `furl_ctx._core` built with maturin; crates `furl-core` / `furl-py`
- Distributed as a single wheel — no separate Rust toolchain required at
  install time

### Removed from the pre-rename codebase

The following capabilities were excised before this release and do not ship:

- Reverse proxy and upstream routing (Vertex AI, OAuth2, multi-provider)
- Web dashboard and CLI
- ML-based compressor (Kompress)
- HTML extraction
- Telemetry and usage reporting
- Non-tiktoken tokenizer backends (Hugging Face, Mistral)

Furl is now a focused context-compression engine and MCP server for Claude Code
tool-output compression, with no network-facing proxy surface.
