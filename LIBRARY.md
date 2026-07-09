# Furl as a Python library

Furl is primarily a Claude Code plugin (see the [root README](README.md)), but
the same engine is a plain Python library you can drop into any app or MCP host.

## Install

Prebuilt wheels ship on [PyPI](https://pypi.org/project/furl-ctx/) — **no Rust
toolchain**, and pip auto-selects your platform's wheel (macOS arm64/x86_64,
Linux arm64/x86_64):

```bash
pip install "furl-ctx[all]"
```

Granular extras: `[mcp]` (MCP server), `[code]` (tree-sitter AST-verified code
compression, ~50 MB, opt-in), `[dev]`. Requires **Python 3.10+**.

Using `pipx`? `pipx install --python python3.13 "furl-ctx[all]"`.

## Use it

```python
# Compress inline in any Python app
from furl_ctx import compress

result = compress(messages, model="claude-sonnet-4")
# result.messages  → compressed; CCR keeps originals retrievable
```

```bash
# Or run the MCP server for Claude Code / Cursor / any MCP host
python3 -m furl_ctx.ccr.mcp_server      # exposes furl_compress / _retrieve / _stats
```

| Your setup     | Hook in with                                  |
|----------------|-----------------------------------------------|
| Any Python app | `compress(messages, model=…)`                 |
| MCP clients    | `python3 -m furl_ctx.ccr.mcp_server`          |

## Retrieve — full or sliced

`compress()` offloads large, low-redundancy content to the CCR store and leaves a
`<<ccr:HASH>>` marker. `retrieve(hash)` turns a marker's hash back into content.
With **no filter argument it is byte-identical to the full stored original** (or
`None` if the hash has left the store window — a loud, explicit miss). Passing a
filter narrows what comes back **without dumping the whole original**, so an agent
can drill into a huge offloaded array cheaply:

```python
from furl_ctx import retrieve

# Full original, byte-exact (unchanged behavior):
original = retrieve(hash)

# ROW-SELECT — keep only the rows of a JSON array of objects (or a JSON object
# with one dominant inner array, e.g. a Chrome trace {"metadata":…, "traceEvents":[…]})
# whose field matches a value:
dropped = retrieve(hash, select_field="name", select_equals="DroppedFrame")

# …or a numeric range window (inclusive; open-ended if a bound is omitted):
window = retrieve(hash, select_field="ts", select_min=404733, select_max=404999)

# Project only some columns of the selected rows, and cap the result:
cols = retrieve(hash, select_field="name", select_equals="Paint",
                fields=["name", "ts"], limit=200)

# TEXT filters over the original as lines (regex + context, or a line window):
lines = retrieve(hash, pattern=r"ERROR", context_lines=2)
head  = retrieve(hash, line_range=[1, 50])

# FIELDS projection over a top-level JSON array of objects:
ids = retrieve(hash, fields=["id", "status"])
```

Rules (they mirror the `furl_retrieve` MCP tool and share one validated spec):

- A **row-select** needs `select_field` plus **either** `select_equals` (equality)
  **or** `select_min`/`select_max` (a numeric range) — never both. A row whose
  field is missing or non-numeric is skipped from a range (never an error). It
  composes with `fields` (project the selected rows) but not with
  `pattern`/`line_range`. The result is always bounded by `limit` (default 1000);
  when more rows match, a `{"_truncated": …}` marker row is appended so a
  truncated slice is never mistaken for the full set.
- `select`/`fields` need a JSON array (or a dominant-array object for select). On
  any other shape they raise `ValueError` — never a silent empty result.
- `pattern`/`line_range` operate on the original as text lines and return matching
  lines prefixed with 1-based line numbers.
- Bad usage (an incompatible filter mix, an invalid regex/range, a filter on the
  wrong shape, or `query` together with a filter) raises `ValueError`. A store
  miss returns `None` on every path.

`resolve_markers(messages)` expands **every** resolvable marker in a message list
back to its original inline (bulk recovery), leaving unresolvable markers in place.

## How it works

```
  tool output · logs · diffs · JSON · RAG chunks
                      │
                      ▼
               ┌─────────────┐
               │    Furl     │
               └──────┬──────┘
                      │
            ┌─────────┴─────────┐
            ▼                   ▼
     compressed context    CCR store (byte-exact originals)
            │                    ▲
            ▼                    │
          LLM  ──► needs detail? ┘
```

- **ContentRouter** — detects content type, selects the right compressor.
- **SmartCrusher** — universal JSON: arrays of dicts, nested objects, mixed types.
- **SearchCompressor / LogCompressor / DiffCompressor** — search results, build logs, diffs.
- **CrossMessageDeduper** — deduplicates repeated content across conversation turns.
- **CacheAligner** — stabilizes prefixes so Anthropic/OpenAI KV caches actually hit.
- **CCR** — reversible compression; the LLM retrieves originals on demand. Large
  distinct content no compressor can shrink (e.g. source files) takes the
  reversible CCR offload: an identity preview plus a retrieval marker.

### Pipeline internals

`compress()` emits three compression lifecycle stages:

`Input Received` → `Input Routed` → `Input Compressed`

- **Transforms** do the work: CacheAligner, CrossMessageDeduper, ContentRouter, SmartCrusher.
- **Pipeline extensions** observe or customize these stages via `on_pipeline_event(...)`; `compress()` passes your `hooks` object as the extension.
- **Compression hooks** sit alongside the lifecycle as an additional extension seam.

### Prompt caching (`cache_control`) — the frozen-prefix contract

Furl never modifies messages up to and including the highest Anthropic
`cache_control` marker (the **frozen prefix**), so provider prompt caches keep
hitting. Two rules keep caching and compression compatible:

- **Mark the breakpoint before the live zone.** `cache_control` on the *last*
  message freezes the whole conversation — every transform skips everything and
  0 tokens are saved (`error` stays `None`). `compress()` flags this in
  `result.warnings` and logs at WARNING. Either mark the breakpoint before the
  turns you want compressed, or compress before marking.
- **Pass back what Furl shipped.** The provider cached the bytes Furl
  *returned* last turn, not your originals. On multi-turn conversations, feed
  the previous `result.messages` back in — or don't move the marker forward
  past turns that already shipped compressed. Re-sending original history with
  a forward-moved marker guarantees a prefix-cache miss at the previously
  compressed message and pins it uncompressed forever (it is frozen). A
  best-effort detector (CCR registry hit inside the frozen prefix) surfaces
  this in `result.warnings`.

## CLI

`pip install furl-ctx` also installs a `furl` command — shell-native access to the
same engine (pipelines, CI log reduction, offline eval, no LLM harness):

```bash
psql -c 'table events' | furl compress        # FILE, or stdin, -> compressed stdout
furl compress big.json --json                 # compressed text + token stats as JSON
furl retrieve <hash>                          # original content for a <<ccr:HASH>> marker
furl doctor                                   # check the install: native core, tokenizer, store
```

## Configuration (environment variables)

Every live `FURL_*` knob. All are optional — the defaults are the shipped behavior.

| Variable | Default | What it does |
|----------|---------|--------------|
| `FURL_WORKSPACE_DIR` | `~/.furl` | Workspace root: home of the durable CCR SQLite store and the shared session-stats file. Also the **security boundary for `furl_read`** — file reads are jailed to it (the jail alone defaults to the server's working directory when unset). |
| `FURL_CCR_TTL_SECONDS` | `1800` | CCR retention window in seconds — how long "reversible" lasts before an entry expires (an expired/evicted retrieval is a loud miss, never silent). Positive integer; invalid values warn and fall back. |
| `FURL_CCR_BACKEND` | unset (in-memory; the MCP server defaults to `sqlite`) | CCR store backend: `memory`, `sqlite`, or the name of a third-party `furl_ctx.ccr_backend` entry point. Explicitly selecting a backend that cannot be loaded **raises at startup** — no silent downgrade to memory. |
| `FURL_CCR_BACKEND_OPTS` | unset (`{}`) | JSON object of keyword arguments passed to a third-party backend factory, e.g. `{"url": "..."}`. |
| `FURL_CCR_SQLITE_PATH` | `<workspace>/ccr.sqlite3` | File path of the durable SQLite CCR store. |
| `FURL_CCR_SQLITE_MAX_ROWS` | `10000` | Row cap for the SQLite store (oldest-created evicted first). |
| `FURL_CCR_SPILL` | `off` | Q10 retention. When truthy (`1`/`true`/`yes`/`on`), an **in-memory** primary demotes evicted entries to a durable SQLite **spill** tier instead of deleting them, so a `retrieve()` past the in-memory cap still recovers (byte-identical, read-only — no promotion back). Ignored when the primary is already `sqlite` (`FURL_CCR_BACKEND=sqlite`, the MCP server's default): a durable primary has nothing to spill to. |
| `FURL_MCP_READ` | `off` | Enables the `furl_read` MCP tool (`on`/`true`/`1`/`yes`/`enabled`). Reads are jailed to `FURL_WORKSPACE_DIR`. |
| `FURL_COMPRESS_WORKERS` | `4` | Worker threads for the router's parallel per-message compression. |
| `FURL_PIPELINE_BREAKER_THRESHOLD` | `3` | Consecutive pipeline failures before the circuit breaker opens and messages pass through **uncompressed** for the cooldown window. `<= 0` disables the breaker. |
| `FURL_PIPELINE_BREAKER_COOLDOWN_S` | `60` | Seconds an open circuit breaker keeps passing messages through untouched before retrying. |
| `FURL_COMPACTION_FORMAT` | `csv-schema` | Lossless render format for SmartCrusher compaction: `csv-schema`, `json`, or `markdown-kv`. Unknown values raise. |
| `FURL_COST_RATE_USD_PER_MTOK` | `3.0` | Blended $/1M-token rate for the MCP `furl_stats` cost-saved estimate. Invalid/negative values fall back to the default. |

The Claude Code plugin's own hook/MCP knobs (`FURL_HOOK_*`) are documented in
[`plugins/furl/README.md`](plugins/furl/README.md).

## Compared to

Furl runs **locally**, covers **every** content type, and is **reversible**.

|                                                                              | Scope                                          | Deploy                             | Local | Reversible |
|------------------------------------------------------------------------------|------------------------------------------------|------------------------------------|:-----:|:----------:|
| **Furl**                                                                 | All context — tools, RAG, logs, files, history | library · MCP                      | Yes   | Yes        |
| [RTK](https://github.com/rtk-ai/rtk)                                        | CLI command outputs                            | CLI wrapper                        | Yes   | No         |
| [lean-ctx](https://github.com/yvgude/lean-ctx)                               | CLI commands, MCP tools, editor rules          | CLI wrapper · MCP                  | Yes   | No         |
| [Compresr](https://compresr.ai), [Token Co.](https://thetokencompany.ai)    | Text sent to their API                         | Hosted API call                    | No    | No         |
| OpenAI Compaction                                                            | Conversation history                           | Provider-native                    | No    | No         |

> **RTK** ([rtk-ai/rtk](https://github.com/rtk-ai/rtk)) is a complementary CLI-output rewriter — a peer in the table above, **not** bundled with or a dependency of Furl. If you already use it for shell-output rewriting, Furl compresses everything downstream; the two compose cleanly. Credit to the RTK team for a great tool.

## Corporate / SSL-inspection environments

The prebuilt-wheel install needs no Rust and avoids this entirely. It only
applies if you force a **source build** (`--no-binary`, `git+…`, or an unsupported
platform) and `pip` fails with `CERTIFICATE_VERIFY_FAILED`
(`unable to get local issuer certificate`): your network uses **SSL inspection** — a MITM
proxy presenting a company-issued CA. The build backend (`maturin`) downloads `rustup` over a
connection your TLS stack doesn't trust. **Install Rust first** so the build doesn't fetch it:

```bash
# macOS / Linux
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh && rustup default stable
# Windows
winget install Rustlang.Rustup && rustup default stable
```

Restart your shell, then re-run the install. Simplest of all: install the prebuilt
wheel from PyPI (`pip install "furl-ctx[all]"`), which skips the Rust build — and this
whole issue — entirely.

One runtime asset is fetched over TLS; if it is blocked, trust your corporate CA via
`REQUESTS_CA_BUNDLE` / `SSL_CERT_FILE` / `CURL_CA_BUNDLE`:

- **`openaipublic.blob.core.windows.net`** — tiktoken's BPE encoding files, downloaded once on
  first use and cached locally. Pre-populate the cache and point `TIKTOKEN_CACHE_DIR` at it to
  run fully offline.

## Contributing

```bash
git clone <your-fork-url> && cd <repo-dir>
pip install -e ".[dev]" && pytest
```

A devcontainer ships in `.devcontainer/`. See [CONTRIBUTING.md](CONTRIBUTING.md).
