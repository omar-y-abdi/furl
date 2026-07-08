# Harness Expansion Plan

Implement every **Topp-hävstång** (quick win) and **Big bet** from
`docs/HARNESS-USECASE-EXPANSION.md`. Each item wires or surfaces a capability that
already exists in the code but is gated off, unwired, or unexported.

## Execution model

- **PM/gate:** the orchestrator does **not** implement. Each item is delegated to a
  named subagent. The orchestrator reviews the diff as the harshest critic, and on
  any smell re-initiates the **same** subagent with a continuous-review prompt until
  clean. Only then: commit + push.
- **Quality bar — lazy senior-dev (user, 2026-07-07). "The best code is the code never
  written." The Ladder — stop at the first rung that holds, per item AND per sub-part:**
  1. Does this need to exist at all? Speculative → skip it, say so in one line (YAGNI).
  2. Stdlib does it? Use it. (CLI → `argparse`; HTML → `html.parser`; not a new dep.)
  3. Native/platform feature covers it? Use it.
  4. Already-installed dependency solves it? Use it. Never add a NEW dep for what a few
     lines do. (Reuse `benchmarks/`, `verify/`, `tiktoken` — don't reinvent.)
  5. One line? One line.
  6. Only then: the minimum code that works.
  Deletion over addition. Boring over clever. Fewest files. No unrequested abstractions/
  flags/config. Mark intentional shortcuts with a `lazy:` comment naming the ceiling +
  upgrade path. NOT lazy about: input validation at trust boundaries, data-loss-preventing
  error handling, security, anything explicitly requested.
- **Testing (lazy):** non-trivial logic leaves **ONE runnable check** — the smallest thing
  that fails if the logic breaks (an assert-based self-check or one small test file; no
  frameworks/fixtures). Trivial one-liners need no test. The full suite (`pytest tests/`)
  must stay green regardless.
- **Verify-first:** subagents must confirm each grounding claim against the real code
  before changing anything — the doc's `file:line` are a starting point, not gospel.
- **Green gate (every item):** `uv run ruff check .` + `uv run mypy furl_ctx
  --ignore-missing-imports` + `uv run pytest tests/ -q` (baseline **1583 passed**). Rust
  touch → `uv run maturin develop` first.
- **Compression-contract gate (routing/drop/offload items — Q3, Q5, B1, B2, B4, + any
  touching `content_router`/`content_detector`/`compress`):** ALSO `uv run python -m
  verify.run` → compare `verify/raw_results.json` aggregate ratios vs the committed floor
  (`benchmarks/baseline_results.json` / `BASELINE.md`) — **no regression**; + needle
  recall 100% (`benchmarks/needle_recall.py`). Unit-green is NOT compression-safe.
  `verify/raw_results.json` is generated — **never commit it.**
- **Branches (two PRs):** quick-wins land on `c7/harness-expansion` → green PR → merge →
  big-bets branch off the new main. Isolates CI, compounds on merged code.

## Critic checklist (reject + re-initiate the SAME subagent on ANY hit)

- Ladder skipped — reinvents stdlib / an already-installed dep / a few-lines job, or a
  sub-part that fails rung 1 (YAGNI) → **reject**.
- New dependency (esp. heavy) → **reject**, log as blocker-question instead.
- Speculative param/flag/abstraction/config not in the item spec → reject.
- Stub / TODO / placeholder → reject.
- Tests asserting structure not behavior (coverage theater) → reject (apply test-quality).
- `Any`-typed public signature (RULES no-lie) → reject.
- Mutation of shared/input objects (immutability rule) → reject.
- Ratio or recovery regression vs floor → reject.
- Non-minimal diff — any line not tracing to the item → reject.

## Order (dependency-sorted)

### Quick wins
- [x] **Q1 — Real Claude tokenizer** (#6, S) — `f393fe2a`. claude-* → TiktokenCounter
      o200k_base (was 3.5-cpt estimate); ImportError→estimator fallback. Mirrored in the
      Rust registry so FFI parity is byte-identical (claude asserted == gpt-4o/o200k both
      sides). No new dep; Anthropic-API exact-tokens deferred (blocker-question). Bench pins
      gpt-4o → neutral. 1585 pass, cargo/ruff/mypy green.
- [x] **Q2 — `compress_to(messages, max_tokens=N)`** (#8, M) — `furl_ctx/compress_to.py`.
      Thin bounded greedy orchestrator over compress(): fixed 5-rung kwargs ladder
      (protect_recent→0, compress_user_messages, min_tokens→50, protect_analysis→False),
      first rung that fits wins; unreachable budget → smallest result + warning (never
      raises/loops/over-budget). Measures the real tokenizer per rung, not the fail-open
      `tokens_after`. No engine change → bench-neutral. 1589 pass. *(PM-implemented: 2
      subagent stream-idle-timeouts on big-file reads; ~55-LOC item, sanctioned small edit.)*
- [x] **Q3 — API-envelope unwrap** `{"data":[...],"meta":{}}` (#1, S) — `envelope_ingest.py`.
      Mirrors the CSV path: `sniff_envelope` (shared predicate) unwraps the single common-key
      array → SmartCrusher; meta preserved inline; marker recovers FULL original byte-exact.
      Fail-open on ambiguity/veto/no-savings. Bench-neutral (0/83 bench items sniff as
      envelopes). 1599 pass; byte-exact recovery + veto tested. *(PM-implemented — subagent
      timeout, see blocker.)*
- [x] **Q4 — Retrieval exports** (#4, S) — `retrieve.py`. Exported `retrieve(hash,query=None)`,
      `resolve_markers(messages)` (immutable copy, honest miss), `CompressResult.ccr_hashes`
      (derived property — can't drift). `hash_of_match`/`hashes_in_text` in marker_grammar
      (reuse `marker_patterns`). Bench-neutral. 1603 pass. *(PM-implemented.)*
- [x] **Q5 — CCR spill tier** (#5, S) — **already wired** (PR #30, post-dates the report).
      `get_compression_store()` builds the spill from `FURL_CCR_SPILL` env (`_create_spill_
      backend_from_env`); the MCP server delegates to it. Verified functionally (in-memory
      primary → spill active; sqlite primary → redundant-guard off) + tested
      (`test_ccr_spill_tier.py`). Only gap was docs → added `FURL_CCR_SPILL` to LIBRARY.md.
      `FURL_CCR_SPILL_BACKEND` (configurable spill backend) = speculative YAGNI, skipped.
- [x] **Q6 — Hook wires shipped config** (#2, S) — `FURL_HOOK_EXCLUDE_TOOLS` (via engine
      `is_tool_excluded`, glob-aware; replaces the substring self-guard, fail-open) +
      `FURL_HOOK_MODE=aggressive` (protect_recent=0 + min_tokens=50). Verified end-to-end
      (subprocess: Bash compresses, furl_/excluded pass through). Docs in SKILL/README. 1607
      pass. **Deferred** (need engine levers): per-tool bias (router needs assistant-tool_call
      linkage the single-message hook lacks) + `lossless_only` (no clean pipeline lever;
      FurlConfig has no `lossless_only` field — = separate roadmap #9). *(PM-implemented.)*
- [x] **Q7 — Observability bundle** (#3, S) — `FURL_HOOK_VERBOSE` one-line stderr savings
      summary per compression (hook ran blind before) + `FURL_COST_RATE_USD_PER_MTOK`
      (replaces the hardcoded $3/Mtok in `furl_stats`). Verified (subprocess verbose +
      cost-rate fallback). Docs in SKILL/README/LIBRARY. 1611 pass. **Scoped out** (lazy):
      durable JSONL (`shared_stats_file` already appends cross-process) + `per_message_stats`/
      `timing` on `CompressResult` (speculative surface, no consumer). *(PM-implemented.)*
- [x] **Q8 — `furl` CLI** (#7, M) — `furl_ctx/cli.py` + `[project.scripts]`. Thin stdlib-argparse
      wrapper: `compress [file|-]` (`--model`, `--json`), `retrieve <hash>` (exit 1 + msg on miss),
      `doctor` (import/native `_core`/tiktoken/store health). Installed `furl` console script
      verified end-to-end. Reuses compress()/retrieve(). 1615 pass. **Scoped out** (lazy): `stats`
      (aggregation entangled in the async MCP handler; `furl_stats` covers in-session) +
      `--lossless-only` (no clean engine lever = roadmap #9). *(PM-implemented.)*

### Big bets
- [x] **B1 — HTML main-content extractor** (#9, M) — `html_ingest.py`. Stdlib `html.parser`
      extractor (NO trafilatura dep), wired into the TEXT dispatch arm: strips
      script/style/nav/footer boilerplate, ships extracted article + a marker recovering the
      FULL original HTML byte-exact. Lossy-but-reversible, gated off under lossless_only.
      Bench-neutral (0 HTML bench items). 1619 pass. *(PM-implemented.)*
- [ ] **B2 — CCR durable-retention epic** (#10, L). Eviction *demotes* not deletes;
      session/conversation-scoped lifetime; TTL-extension-on-access; `session_id`/`agent_id`
      namespacing on `compress()`; `ccr_export`/`import`; pin-forever. See `CCR-RETENTION.md`.
      *Extends Q5.*
- [ ] **B3 — Redaction + purge + namespace + audit + encryption** (#11, L).
      `CompressConfig.redactor` (fail-**closed**, outside the fail-open boundary);
      `furl_purge(hash)` MCP tool + `furl purge` CLI; `FURL_CCR_NAMESPACE`; append-only
      `audit.jsonl`; optional at-rest encryption (`FURL_CCR_ENCRYPT_KEY`);
      `FURL_HOOK_SENSITIVE_TOOLS` → memory-only. *After B2.*
- [ ] **B4 — Cross-turn / whole-history wiring** (#12, M). Activate the idle
      `ReadLifecycleManager` (stale/superseded reads) via a conversation-aware path;
      `compress_chat_history()` preset; `compress_with_cache(freeze_up_to_n)` helper.
- [ ] **B5 — Eval / recall harness** (#13, M). `benchmarks/` + `verify/needle_recall.py`
      exist internally; expose `furl eval <corpus> --recall` (the trust gate). *Uses Q4, Q8.*

## HANDOFF — B2–B5 (context limit reached at B1; resume in a fresh session)

Q1–Q8 merged (PR #36, on main). B1 on branch `c7/harness-bigbets` (PR pending). B2–B5
remain — all substantial (L/L/M/M). Baseline **1619 pass**. Gate per item: `uv run ruff
check . && uv run ruff format . && uv run mypy furl_ctx --ignore-missing-imports && uv run
pytest tests/ -q` (+ `cargo fmt --all && cargo test --workspace` if Rust). Routing items →
also confirm bench-neutral (grep bench data for matches) or run `uv run python -m verify.run`.

**Reusable recovery pattern (CSV → envelope → HTML all follow it):** `sniff_x` predicate →
transform → `persist_to_python_ccr(original, candidate, raw_recovery_hash(original), ...)` →
ship `candidate + [N word compressed to 0. Retrieve more: hash=<24hex>]` marker → fail-open
veto (persist fail / no-savings → return None → serve raw, never a dangling marker). Recovery
scans `BRACKET_RETRIEVE_PATTERN`; `retrieve()`/`resolve_markers()`/`ccr_hashes` (Q4) resolve it.

- **B2 — CCR durable-retention epic (L).** Spill tier (Q5) already covers demote-not-delete.
  Remaining, scope to minimal: `session_id`/`agent_id` namespacing on `compress()` +
  `FURL_CCR_NAMESPACE` (shared with B3) for per-tenant store isolation; `ccr_export(path)` /
  `ccr_import(path)` for cross-session checkpointing. Files: `furl_ctx/cache/compression_store.py`
  (`get_compression_store` + `_request_ccr_store` ContextVar at ~:1493 already exists for
  request-scoping — reuse it for namespacing). **Defer** (flag): TTL-on-access promotion,
  pin-forever. Security-adjacent — careful.
- **B3 — Redaction + purge + namespace + audit + encryption (L).** Minimal core: `CompressConfig.
  redactor: Callable[[str],str] | None` applied **fail-CLOSED before** the store write (outside
  compress()'s `except BaseException` fail-open boundary — `compress.py` ~:490-510); `furl_purge`
  MCP tool + `furl purge <hash>` CLI (store has `delete`/`clear` at `sqlite.py:295/327`, unsurfaced);
  `FURL_CCR_NAMESPACE`. **Defer as blocker-questions**: at-rest encryption (needs SQLCipher/crypto
  dep — which?), `audit.jsonl` format (fields/rotation?). `secret_keep_rail` currently guarantees
  secrets reach the store byte-exact — redaction is the fix.
- **B4 — Cross-turn / whole-history wiring (M).** Activate the idle `ReadLifecycleManager`
  (`furl_ctx/transforms/read_lifecycle.py` — needs multi-turn context the single-message hook never
  passes). Add a `compress_chat_history(messages, ...)` preset (= `compress` with
  `compress_user_messages=True`, `protect_recent=2`, retrieval feedback on) + a
  `compress_with_cache(messages, freeze_up_to_n)` prompt-cache-aware helper. Library-only (no hook
  change). Files: `compress.py` / a new small `chat.py`. Bench-neutral (new surface).
- **B5 — Eval / recall harness (M).** Mostly REUSE: `benchmarks/needle_recall.py` +
  `verify/measure.py` exist. Add `furl eval <corpus> --recall` to `furl_ctx/cli.py` (extend the Q8
  argparse) that runs the existing needle-recall over a user corpus and prints ratio + recall%.
  Thin wrapper; no engine change.

## Blocker questions (fill during the run; ask after everything is done)

- **Subagent delegation is broken in this environment** — 3 consecutive `general-purpose`
  Agent subagents (Q2×2, Q3×1) hit reproducible `API Error: Stream idle timeout` at ~10-11
  tool uses / ~6.5 min with 0 output tokens, even with a fully pre-digested, minimal-reading
  spec. Matches a documented prior failure mode in `PLAN.md` ("big-file reads stall bg agents
  regardless of model; run foreground"). Given the "autonomous, don't pause, complete to
  perfection" mandate and the broken delegate path, I am **implementing directly** (as the
  sanctioned rare-small-edit exception, scaled up out of necessity) while gating each item as
  the harsh critic + full green gate. Flagging the deviation from "delegate everything" for
  your awareness — the alternative (halt) would violate the no-pause mandate.

- **B1 HTML extractor** re-introduces functionality the "Great Excision" deliberately
  deleted (`html_extractor.py` + trafilatura, user: "i want it GONE"). User re-authorized
  it here → proceeding with a **minimal stdlib-only** extractor (no trafilatura/readability
  dep). Flagging the re-introduction for confirmation.
- **B3 at-rest encryption** (`FURL_CCR_ENCRYPT_KEY` / SQLCipher) needs a heavy crypto dep →
  building the minimal redaction/purge/namespace/audit core; **encryption deferred as a
  question** (which dep, or skip?). Audit-format (fields/rotation) also a question.

## PERF — #1 PRIORITY (do after B2/B4 land)

**Measured 2026-07-08 — furl-ctx 0.27.0, isolated venv, real 33.8 MB Chrome DevTools trace,
per-stage bounded slices:**

| stage | 1 MB | 4 MB | scaling |
|-------|------|------|---------|
| tiktoken count | 0.15 s | 0.58 s | **O(n)** ~6 MB/s — fine |
| content detector | 0.01 s | 0.03 s | **O(n)** — fine |
| **compress()** | **2.75 s** | **19.6 s** | **4× data → 7.1× time = SUPER-LINEAR** |

4×→7.1× is worse than O(n). Extrapolates to ~10–50 min for 33 MB → matches the observed
15-min hang. **It is the engine (router/crusher), not the harness or the test script** —
tokenizer + detector are linear. Threshold effect: 1 MB routes to `router:mixed` (2.75 s,
70 % saved); 4 MB routes to `router:ccr_offload` (19.6 s, ratio ≈ 1.0, ≈0 useful savings) —
the large-input path is BOTH slow AND ineffective.

**Why #1:** for file/log compression **latency IS the product**. A multi-minute compress is
worse than useless — an agent would rather burn tokens or `grep`/`bash` the file than wait.
Perf beats ratio for this use case.

**Epic:**
1. **Profiled root cause — CORRECTED.** The first profile used *truncated* JSON (`raw[:4MB]`),
   an artifact: on truncated input the top-level `{` never balances, so the mixed splitter falls
   through to per-event extraction → ~9,400 tiny sections. On a **VALID complete trace** the
   splitter yields **1 section** (the whole balanced doc) — the fan-out/size-guard fixes were
   chasing the artifact and are **dropped**. Real bottleneck (valid JSON, 4 MB, 14.8 s cProfile):
   **tokenization = 82 %** — `tiktoken.encode` 12.1 s across 243 `count_text` calls (≈ ~17
   full-content passes at ~0.7 s/pass); the single Rust `crush` is only 1.0 s. The
   router / dispatch / `min_ratio` gate / fallback chain **re-tokenizes the same multi-MB content
   ~17×**. → Fix: tokenize once before + once after; reuse/estimate counts for the ratio gate and
   fallback comparisons instead of re-encoding the full content each time. Contract to preserve:
   the `min_ratio` gate must still read correct token units (COR-17) — don't weaken it, cache it.
2. **Latency budget + early-exit**: hard per-call size/time ceiling. Above a byte threshold,
   short-circuit to a bounded cheap path (structural head/tail keep + CCR-offload the bulk)
   instead of the expensive crusher. Never worse-than-linear; target ≥ 20–50 MB/s end-to-end.
3. **Fix `ccr_offload` accounting**: 4 MB reported `saved=1,508,034` yet `ratio≈0.9997`
   (contradiction) while saving ≈0 useful tokens and costing 19.6 s.
4. **Guard in the eval harness (B5)**: fail if end-to-end MB/s drops below a floor.

Note: Q3 (envelope-unwrap) is a **ratio/routing** fix (detect `traceEvents`, crush the inner
array — the trace detects as PLAIN_TEXT in 0.27.0), **NOT** a perf fix. Perf is its own epic.

**RESULT (2026-07-08) — tokenization memo shipped (commit e8c739e3).** Fixed the confirmed 82 %:
`TiktokenCounter.count_text` now memoizes large strings (bounded by cached bytes, oldest evicted),
so the ~18× re-tokenization of the same multi-MB content collapses. **4 MB: 14.8 s → 5.05 s. Real
33 MB Chrome trace: ~15 min → ~68 s (~13×).** Ratio byte-identical (0.2752), 1633 pytest green,
verify.run gates pass (hash_failures=0, silent_loss=0, byte_exact=True). Accounting-only — no
compression change.

**Residual at 33 MB (~68 s) — deeper, needs a decision (steps 2–4 above superseded):**
- **Rust `crush` = 26 s** (one call, super-linear: 1 s@4 MB → 26 s@33 MB). SmartCrusher is O(>n) on
  huge input → a Rust-side algorithmic fix (harder, contract-risk).
- **`encode` = 34 s** — tiktoken is slow on the base64-heavy trace (sourcemaps); the memo already
  collapsed the repeats, so this is ~one honest tokenization of 33 MB. Reducible only by ESTIMATING
  token counts for huge content (≈ bytes/4) instead of exact tiktoken — a latency-vs-accuracy trade
  on the `min_ratio` gate (the "latency IS the product" stance favors it, but it lowers gate
  precision → needs sign-off).
- **Or a size-guard**: above ~N MB, skip the expensive exact path (estimate + one bounded crush, or
  CCR-offload) → predictable latency, some ratio trade.
13× is banked; the last mile is a trade-off call.
