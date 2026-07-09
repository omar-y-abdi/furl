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

**RESULT 2 (2026-07-08) — size-guard shipped (commit 9b4775a7).** Above
`FURL_MAX_COMPRESS_BYTES` (default 8 MB) a content block offloads to CCR immediately
(O(n), head/tail preview + full original byte-exact recoverable) instead of the super-linear
crush. **33 MB trace: 68 s → 24 s; cumulative ~15 min → 24 s (~37×).** Content below the
ceiling is byte-identical (verify.run degradations/hash_failures/silent_loss unchanged);
1636 pytest green.
- **Rust crush now LOW-URGENCY**: huge content bypasses the crush entirely, so SmartCrusher's
  super-linearity only affects mid-size (4–8 MB) content (~5–13 s, tolerable). The deep
  Rust-side fix is deferred unless the 4–8 MB path must be faster.
- **Remaining 24 s residual**: `tokens_before` is one exact tokenization of the 33 MB (~11.7 s,
  memoized). Reducible to ~10 s total by estimating tokens for huge content at the pipeline
  (small change, minor reported-count accuracy trade) — optional last mile.

**Rust crush — scoped for a focused effort (user requested it; needs fresh context — a broken
`.so` from an interrupted `maturin develop` breaks the whole tool, so don't rebuild-loop at
deep context).** Entry: `walk.rs:44 crush` → `smart_crush_content_collecting` → per JSON array
`route.rs:147 crush_array` = walk items → `analyzer.analyze_array` → `planner.create_plan` →
`execute_plan` → compaction (`compactor.rs` / `formatter.rs`). The **analyzer is O(n)** (per-key
stats, keys ≈ const) — ruled out. The super-linear term (1 s@4 MB → 26 s@33 MB, ~O(n^1.4)) is
NOT yet pinpointed; prime suspects: a quadratic op in `planning.rs` (item loops at
:322/:441/:575/:622/:719) or `compactor.rs` (19 item loops). **Method:** instrument the 4 phases
in `crush_array` with `Instant` timing, `maturin develop` once, run a <8 MB subset (the
size-guard offloads >8 MB) at two sizes → the phase whose time scales super-linearly is the
target. Fix MUST keep the crush output byte-identical (grammar + compression-floor contract) +
`cargo test --workspace` + `verify.run` unchanged. Note: LOW real-world urgency — the size-guard
already bounds huge inputs; this only speeds the 4–8 MB path.

**DONE (commit 621509b7, delegated 2-agent pipeline: pinpoint → fix).** The pinpoint
CONTRADICTED the scoping above: the O(n²) was `count_unique_simhash` (`adaptive_sizer.rs:276-298`)
— a greedy simhash-cluster scan inside adaptive k-selection (`compute_optimal_k`), NOT
planning/compactor/formatter (all measured linear-in-bytes). Fix: a 16-bit block index (pigeonhole
LSH — two fps within Hamming t share ≥1 of t+1 equal blocks) → byte-identical cluster count,
**cluster-scan 30.5 s → 0.4 s** at the full trace. Verified by the orchestrator: cargo test 832 +
fmt clean, pytest 1636, verify.run unchanged (degradations=6/hash_failures=0/silent_loss=0 →
byte-identical crush output). Residual: the crush is still slow for guard-disabled large content
(~33 s @ 7.4 MB — other phases sum large), but production offloads >8 MB, so this only affects the
4–8 MB path (lower the guard if that matters). **Lesson: delegated measurement > static scoping —
the pinpoint found the culprit my guess (planning/compactor) missed.**

## AGENT-UTILITY / SIGNAL-COMPLETENESS — user reframe (2026-07-08), now the top bar

**Reframe (user):** furl runs as a post-tool-hook compressor. The real acceptance test is NOT
token ratio and NOT any one signal (DroppedFrame was just an example) — it is: **can the agent
ACT on the compressed output WITHOUT re-reading the source (grep/bash the raw file)?** If it must
re-fetch, the tool is net-negative (added latency+cost, zero gain). "If thats the case, then this
compression tool is useless."

**Known gap:** huge content (>8 MB) hits the size-guard → CCR offload → agent sees only a hash +
head/tail preview (user: "~30% of the info"). Crush IS signal-complete but too slow (~33 s @ 7.4 MB
even post-fix). Current design forces a bad binary: fast+info-poor (offload) vs complete+slow (crush).

**Direction (advisor-gated, 2026-07-08):**
1. **Eval FIRST, fix SECOND.** Do NOT pre-commit an implementation (e.g. rare-value/outlier
   salience). Build an agent-utility eval, baseline the CURRENT system on real corpora, let the
   failing queries dictate the mechanism. (Same lesson as the Rust-perf pinpoint: measurement >
   static scoping.) BLOCKING: no output-changing implementation until the eval justifies it.
2. **Eval must be DISCRIMINATING** (else confirmation bias). String-presence ("is X in the output")
   is a weak proxy = the ts-survival test the user told us to generalize past. Grade by a SUBAGENT
   answering from ONLY the compressed blob vs ground truth from full source, across three query
   archetypes that stress different failure modes:
   - **anomaly** ("find the unusual events") — salience/rare-keep wins
   - **locality** ("what happened around T / line N?") — needs NEIGHBORS, salience loses
   - **aggregate** ("how many X / distribution of Y?") — needs counts/schema, not kept rows
   Corpora: Chrome trace, app logs, source file, JSON API dump, stacktrace.
3. **Check RETRIEVAL before building any salience engine.** Q4's `retrieve(hash, query=None)`: if
   retrieval can already return a SLICE (predicate/range/query), the offload path isn't useless —
   the cheap fix is "make the preview tell the agent what to query." If retrieve is all-or-nothing
   (dumps 33 MB back → blows context), THAT is the real gap. The eval must distinguish these.
   **RETRIEVAL CHECK RESULT (2026-07-08):** plain `retrieve(hash, query)` is **ALL-OR-NOTHING** —
   `query` is metadata only (record_access/logging), returns the full stored `original_content`
   byte-for-byte (retrieve.py:17-25, compression_store.py:575-661). So in the post-hook + library
   path the agent gets the marker → `retrieve(hash)` → the whole 33 MB back → blows context =
   **confirms the user's "useless" fear for huge content.** BUT slice capability EXISTS and is
   under-surfaced: `RetrieveFilters` (regex `pattern`, `line_range`, `fields` projection on JSON
   arrays) + BM25 `store.search()` return SUBSETS — but they materialize the full blob first
   (context-cheap, not memory-cheap) and are wired ONLY into the MCP handler (mcp_server.py:868-870,
   :912), not the plain `retrieve()`. The offload preview is **head-8 + tail-2 truncated rows, no
   schema, no type-counts, no ranges, no anomalies** (router_engine.py:652-722, consts :103-112) —
   "almost entirely uninformative" for a 140 k heterogeneous-event trace. → Fix space (quantify via
   eval, don't pre-commit): (a) richer preview (schema + per-key/type counts + ranges +
   representative anomalies) → answers AGGREGATE/ANOMALY inline; (b) surface the EXISTING slice
   filters → answers LOCALITY/specific slices context-cheaply — mostly REUSE, cheaper than a Rust
   salience engine. Caveat vs the 'MCP waits' north-star: slice filters currently need the MCP tool;
   pure library/hook `retrieve()` is all-or-nothing.
4. **Prototype any salience in PYTHON inside the eval harness**, prove across all 3 archetypes, port
   to Rust ONCE if ever (Rust byte-identical contract + maturin rebuild loops = deep-context hazard).
   Caveat: "rare value" is only meaningful on low-cardinality categorical fields; on all-unique
   fields (ts, frameSeqId) everything is "rare" → needs per-field cardinality/type awareness.
5. **Crush-perf is DISSOLVED by the reframe.** Signal-complete ≠ complete. We don't owe the agent all
   140 k events fast — we owe it the signal + a navigable summary (schema + counts + ranges + kept
   anomalies + representative sample). A single O(n) pass is cheaper than the full crusher AND more
   useful. Stop optimizing crush latency for huge input.
6. **Checkpoint before implementing.** Proceed autonomously on the EVAL (measurement can't be wrong).
   Before ANY output-changing implementation, show the user REAL before/after output on their actual
   trace (they've asked twice to see output, not plans). Note their earlier "crush huge = complete"
   choice predates crush-perf proving crush can't be fast enough — premise changed, re-surface w/ data.

**CI (2026-07-08):** required checks (build-wheel/lint/test 1-4) all green; `audit` + `commitlint` are
NON-required. audit = crossbeam-epoch RUSTSEC-2026-0204 → dep bump 0.9.18→0.9.20 (delegated). commitlint
= one 126-char header on 621509b7 → DISSOLVED by squash-merge (intermediate commit never lands on main);
NO force-push (rewrites shared history + hook-blocked).

**BASELINE RESULT (2026-07-08, `benchmarks/agent_utility_eval.py` @ commit 6dec22f6, clean release .so):**
5-corpus run (chrome_trace_slice EXCLUDED — 4MB crush hangs >7min even release, below the 8MB guard =
a SECOND perf pathology, documented). GT-present cols are a NOISY substring proxy (LLM grading pending);
the objective evidence is the blob content.

| corpus | bytes | transform | agent-sees | off? | anom | loc | agg |
|--------|-------|-----------|-----------|------|------|-----|-----|
| chrome_trace_full | 33.8M | ccr_offload | 1,670 ch | Y | NO | NO | NO |
| app_log | 341K | mixed (offload) | 903 ch | Y | ~ | NO | ~ |
| source_file | 37K | protected:recent_code | 36,880 ch | N | Y | Y | ~ |
| json_api | 78K | smart_crusher (offload) | 4,843 ch | Y | ~ | NO | ~ |
| stacktrace | 2K | protected:error_output | 1,980 ch | N | Y | Y | Y |

**Findings:**
- **Large content fails.** 33MB trace = TOTAL failure — the 1,670-char blob is 8 head rows of
  `__metadata`/`thread_name` (ts=0, useless) + gap + 2 tail InputLatency rows. Zero DroppedFrames, no
  schema, no counts. Head/tail sampling is BLIND to signal.
- **Locality is unanswerable from ANY compressed blob** (NO on all 3 offloaded corpora) — sampling never
  keeps "the neighbors of position T". (Advisor predicted this.)
- **Small content is fine** — source_file (37K) + stacktrace (2K) PASS THROUGH untouched
  (router:protected) → agent has everything. furl correctly leaves small/protected content alone.
- So furl is signal-incomplete EXACTLY where compression matters → agent must re-grep → the user's
  "useless" is real, and MEASURED.
- **~~Second perf pathology~~ CORRECTED (2026-07-08):** the "4MB slice hangs >7min" was **CPU
  starvation** from the concurrent `wqvokspr6` crush-perf workflow (ran 111 min at 99% CPU during the
  harness runs). Verified once it finished: the slice compresses in **5.0s** (router:mixed, 4MB→2.8MB).
  NOT a furl pathology — my claim was wrong (harsh-review self-correction). The crush path (<8MB) is
  fine (~5s@4MB, ~22.9s@33MB guard-disabled per wqvokspr6). **THE sole target is the OFFLOAD path
  (>8MB → 1,670ch boilerplate)** = `router_engine.py._build_offload_preview`. wqvokspr6 also found: no
  super-linear crush term remains (621509b7 confirmed, cluster_index 98ms); the ~13s tokens_before
  tokenization is the floor, ~2x reducible by moving to the Rust tiktoken path — parked (the
  signal-aware summary sidesteps full-content tokenization anyway).

**Fix (proposed, checkpoint pending):** replace the head/tail offload preview with a SIGNAL-AWARE O(n)
summary — schema (keys+types) + per-key cardinality/top-values + numeric ranges + per-`name` histogram +
K representative + K RARE rows — AND surface the EXISTING slice filters (`line_range`/`pattern`/`fields`,
mcp_server.py:868) in the marker so the agent pulls locality/specific slices context-cheap. Prototype in
Python first (prove across all 3 archetypes), port to the offload path once proven. Answers
aggregate+anomaly inline + locality via a cheap slice, AND sidesteps the crush entirely (O(n) summary, no
super-linear crush) → fixes the latency pathology too. Rare-value salience needs per-field
cardinality/type awareness (all-unique fields like ts/frameSeqId → everything "rare") — handle in the
Python prototype.

**FIX SHIPPED + WIRED END-TO-END (2026-07-08/09) — the agent-utility epic is DONE.**
- **#38** `feat(router): signal-aware CCR offload preview` — `_build_offload_preview` now emits `_ccr_summary`
  (schema + per-field value histograms + numeric ranges + per-primary-categorical-value `examples` + sample),
  fail-open to the old head/tail. The builder caught + fixed my picker spec (COVERAGE-first, not most-distinct →
  picks `name` over sparse `tdur`/`id`, surfacing DroppedFrame with its ts). Trace: anomaly NO→YES, aggregate NO→YES.
- **#41** `feat(ccr): sliceable retrieve` — new ROW-SELECT filter (`select_field` + `select_equals` | `select_min`/
  `select_max`, `limit`) over a JSON array OR a dominant-array object; library `retrieve()` surfaces every filter
  (byte-identical no-filter path); the offload summary carries a domain-agnostic `retrieve` slice-hint; +43 tests.
- **#42** `feat(cli): furl retrieve slice flags` — `furl retrieve HASH --select-field/--select-equals/...` matches
  the library (SUPPRESS-defaulted; no-flag byte-identical); +7 tests.
- **Verified independently on the 33MB trace:** `retrieve(name==DroppedFrame)` = 310KB/1000 rows, `retrieve(ts∈window)`
  = 21KB/66 events, full retrieve byte-exact. All 3 archetypes servable without re-grep or 33MB dump (anomaly+aggregate
  inline; locality via a cheap slice). verify.run byte_exact / hash_failures=0 / silent_loss=0; 1708 tests; CI green on all 3.
- **Deferred (task #8):** advertising `select_*` in the `furl_retrieve` MCP tool schema — the handler already parses it
  (works if passed); parked at the "MCP waits" north-star, a 1-block add when the freeze lifts.

## REMAINING — B3 core (redaction + purge; needs NO Q3) — IN PROGRESS
- `CompressConfig.redactor: Callable[[str], str] | None` applied **FAIL-CLOSED before the store write** (outside
  compress()'s fail-open boundary), so a redactor error never leaks unredacted content into the CCR store.
- `purge(hash) -> bool` library + `furl purge <hash>` CLI — surface the store's `delete` (sqlite.py:295, memory, base).
- Namespace **already done** (`FURL_CCR_NAMESPACE_ENV`, compression_store.py:1525-1544, from B2).
- **Q3 RESOLVED (user, 2026-07-09): SKIP both** — at-rest encryption + `audit.jsonl` are out of scope (YAGNI;
  redactor + namespace + purge cover the threat, no new dep). **B3 COMPLETE (#43).**
- **`FURL_HOOK_SENSITIVE_TOOLS` — SKIP (user, 2026-07-09, YAGNI):** memory-only compression for named sensitive
  tools was in the original B3 spec but is redundant with the fail-closed redactor, which already redacts BEFORE
  every store write. Deliberately not built (no new surface). Recorded explicitly so it is a decision, not a silent
  drop; revisit only if a real per-tool memory-only requirement appears.
- **North-star-deferred (not pending work):** `furl_purge` MCP tool + advertising `select_*` in the `furl_retrieve`
  MCP schema (#8) — parked at the "MCP waits" freeze-line. PERF tokenization→Rust also parked (summary sidesteps it).

## PLAN COMPLETE (2026-07-09)
Every harness item shipped to main: **Q1–Q8, B1, B2, B3, B4, B5, PERF**, and the **agent-utility / signal-completeness
epic** (#38 signal-aware summary, #41 sliceable retrieve, #42 CLI slice flags). The tool went from useless on a 33MB
trace (1,670ch of metadata boilerplate) to a full **compress → signal-aware summarize → cheap slice-retrieve** loop
(anomaly+aggregate inline, locality via a 21KB slice), plus a **fail-closed redactor + purge** security core. Byte-exact
recovery intact throughout; CI green on all PRs. Only the MCP-surface items remain, deliberately parked at your north-star.
