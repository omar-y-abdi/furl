# FABLE-RECON-PLAN — Full-tree audit & refactor master plan

> **Provenance:** produced 2026-07-01 against HEAD `bf60ecb` by a 10-lane full-tree sweep
> (every Python and Rust module read in full — no sampling; ~36.6k LOC production +
> ~15.5k LOC tests + benchmarks/verify/docs/packaging). Two decoder defects were
> **empirically reproduced** against a locally built extension before being listed.
> Every finding cites a file:line that was actually read. Items fixed in prior rounds
> (PLAN.md rounds 1–5) are not re-listed. CODEBASE-MAP §6 by-design decisions
> (two CCR stores; Rust-only CCR knobs) are respected and not re-litigated —
> except where new evidence contradicts them, which is called out explicitly.
>
> **Hard invariants this plan never breaks silently:** (1) CCR recovery 100% byte-exact,
> (2) Python↔Rust hash parity, (3) prompt-cache prefix ordering.

---

## 1. Executive summary

**The codebase's real character.** Headroom is a two-brain engine: a genuinely strong,
mutation-tested Rust core (SmartCrusher + compaction + three text compressors) under a
Python orchestration layer that has been hardened through five audit rounds. The
invariant discipline is real — CCR recovery is attacked by six independent test suites,
hash parity is pinned by live cross-language vectors, and the marker grammar is
single-owned. The verify/ harness culture (cold-store subprocesses, strict multiset-SHA
reconstruction, adversarial held-out sweeps) is better than most production codebases.

**But the sweep found the armor has four soft seams:**

1. **Two live, reproducible breaks in the "lossless" tier** — the Python reference
   decoder cannot decode (a) constant columns containing newlines and (b) head-dict
   cells that got CSV-quoted. Both were confirmed by running the real Rust encoder →
   Python decoder round trip: entire tables decode to zero rows. Because the lossless
   tier writes *nothing* to CCR, this is silent, unrecoverable loss on the flagship
   path — the exact class five rounds of work were spent eliminating. Both are
   one-line fixes; the fuzz generator never produces either shape, which is why they
   survived (COR-1, COR-2).

2. **The measurement substrate has rotted underneath the engine.** `python -m verify.run`
   crashes outright on a data file that was never committed; the committed BASELINE is
   a 3-dataset capture at a commit that no longer exists (the shipped engine is ~50pp
   *better* than the README currently proves); the G4 recovery gate is a grep-scrape
   that passes on `"1 failed, 23 passed"`; G5 ignores run_bench's exit code, so a
   crashed bench floor-checks HEAD against HEAD and prints PASS. Every later batch in
   this plan is gate-verified — so the gates get fixed first (TEST-1..4, COR-3).

3. **A large amputated-limb problem.** The learning half of the product was removed in
   prior rounds, but its feeding half survived: ~3,400 LOC of telemetry (TOIN +
   collector + models) and ~613 LOC of compression-feedback run on every request,
   writing data **nothing reads** — with an inverted success signal, a privacy leak
   (raw user queries persisted to `~/.headroom/toin.json` even when the documented
   opt-out is set), and hot-path costs (double full-payload JSON parses, file I/O
   under a global lock). Add the dead CCR tool-injection plane, the unreachable Rust
   HF-tokenizer stack (with its C/C++ supply chain), nine never-raised exported
   exceptions, and 21.6 MB of unreferenced GIFs: **roughly 6–8k LOC and ~25 MB of repo
   weight can be deleted with near-zero behavioral risk** (ARCH-3, SEC-2/3, SIMP-*).

4. **Compression is being left on the table in measurable, named places.** `Bash` sits
   in `DEFAULT_EXCLUDE_TOOLS` while the adjacent comment says it isn't — build/test
   output, the single largest compressible category for coding agents, may never be
   compressed by default. Code content has no strategy at all (0% on 70% of the bench
   corpus tokens). Small arrays (the most common real tool-output size) never offload —
   disk@9 gets 43% where size-90 gets 91%. A proven-lossless 27%-savings render is
   discarded by the 0.30 ratio gate. Kompress — marketed as one of two core engines —
   is exercised by zero benchmarks. And no benchmark feeds raw text to Search/Log/
   Diff/HTML at all: the "search" and "logs" datasets are pre-parsed JSON that routes
   to SmartCrusher (EFF-1..7).

**Top systemic themes** (each recurs across ≥3 modules): docs describing a previous
era of the engine (the map's contract section cites a test file that doesn't exist —
found independently by three lanes); conditional-skip tests that rot to green
(20+ sites guarding the exact regressions their files exist to pin); typed data
flattened to text at the FFI and re-parsed by scraping (the refactor-(b) target, but
also `row_index_markers`, detection metadata, strategy strings); word-counts and
token-counts sharing one name (`compression_ratio` gates in word-units against
tokenizer-derived thresholds); and per-request options defeated by option-blind caches.

**Highest-leverage moves, in order:** fix the two decoder breaks and the gate/harness
holes (days, closes real loss); bound the CCR store flood + escalate typed-miss to
fail-open (closes the last reachable recovery breach); execute the Great Excision
(one decision, −6-8k LOC, kills two highs and a privacy leak); land refactor (b)
(typed CCR refs — retires all six scrape sites and de-risks every future recovery
change); land refactor (a) (ContentRouter decomposition); then the efficacy batch
(Bash, small-array offload, lossless gate, raw-text benchmarks) which is where the
product actually gets better for users.

**Finding counts** (after cross-lane dedup): 3 critical · 26 high · 71 medium ·
57 low/nit = **157 finding IDs** (several bundle multiple sub-findings; full
theme × severity table in §6), including 10 efficacy propositions and the 2
mandated large refactors, planned in full in §4.

---

## 2. Prioritized execution roadmap

Batches are ordered by (invariant risk × leverage), sized to be individually
gateable, and annotated with what must move in lockstep. **Standing rules for every
batch:**

- **Gate:** full `pytest tests/` keyed on exit code + `cargo test --workspace` +
  `gate.sh` G1–G5 (after Phase 0 fixes make the gates honest) + recovery suite +
  floor needle 100%. Behavior-changing batches additionally re-run
  `python -m benchmarks.run_bench` and `python -m verify.run` and diff against the
  re-committed baseline.
- **Rust rule:** after ANY Rust change, `maturin develop` **before** pytest —
  `gate.sh` does not rebuild the extension (a prior round shipped a false-green this
  way; see `.claude/runtime/handoff.md`).
- **Wire-contract rule:** any change to what crosses the PyO3 boundary (new FFI
  fields, config-kwarg deletions, tuple-shape changes) lands Rust + bridge + Python
  consumer + tests in **one commit**.
- **Parity rule:** any change to a dual-implementation behavior (hash inputs, marker
  bytes, detection heuristics with a Python twin — e.g. COR-24 field-scoring,
  COR-23 anchor length) lands both languages in one commit with the parity test
  updated in the same commit.

### Phase 0 — Repair the measurement substrate (≈2 days; everything else depends on it)

| Step | Items | Lockstep / gate |
|---|---|---|
| 0.1 | Fix the two confirmed lossless-decoder breaks: `re.DOTALL` header (COR-1), head-dict `_unq` (COR-2); extend fuzz generator with constant-multiline-string columns, head-dict comma/quote tails, and a uniform-nested-object case | Python-only; new fuzz cases must fail before / pass after |
| 0.2 | Restore or repoint `verify/data/slugify_rg.raw.jsonl` so `verify.run` executes at all (COR-3); fix `DEV_CLAIMS["multiturn@135"]`→`@90` (TEST-26) | run `python -m verify.run` end-to-end once, green |
| 0.3 | Gate honesty: G4 exit-code not grep (TEST-1); G5 checks run_bench exit code + `floor_check.py` rejects unchanged `captured_at` + fails on datasets missing from the floor (TEST-2); portable `cd "$(git rev-parse --show-toplevel)"`; run_bench writes to `--out` or gate trap-restores everything incl. `benchmarks/data/` (TEST-4) | deliberately break a recovery test → G4 must go red |
| 0.4 | Re-baseline: re-run run_bench at HEAD, commit the 6-dataset BASELINE.md + baseline_results.json, update README Proof table (EFF-10 / DOC-5) | after 0.1 so the baseline includes the decoder fixes |
| 0.5 | Anti-vacuity: convert the 20+ conditional-skip sites in the invariant suites to hard asserts / `test_fixture_actually_fires` guards (TEST-5); fix the assertion-free MinTokens fuzz exits (TEST-6) | zero skips in the CCR suites after |

### Phase 1 — Close the remaining invariant gaps (≈1 week)

| Step | Items | Lockstep / gate |
|---|---|---|
| 1.1 | Bound the CCR chunk flood: persist only *dropped* rows + skip granular chunking when `n > capacity/4` (COR-4); fix the `_ccr_rows` chunk-count lie in the same commit (COR-20 — marker byte change → re-pin grammar characterization test) | Rust; proportional-retrieval tests updated to tolerate absent `_ccr_rows` on huge arrays |
| 1.2 | Escalate typed-hash store-miss from debug-skip to `CcrMirrorError` fail-open (COR-5) — the Python-side detector for whatever 1.1 doesn't prevent | extend `test_ccr_mirror_no_silent_loss.py` with a >capacity drop |
| 1.3 | Kompress CCR-store-failure veto→passthrough (COR-6); Kompress `onnx_coreml` fix (COR-11); mid-batch KeyError guard (COR-12) | Python-only |
| 1.4 | Panic containment: `catch_unwind`→`PyRuntimeError` on the hot bridge methods AND `PanicException`-aware fail-open in `compress()` (COR-7); fix the Cargo.toml comment | belt-and-braces, one commit; add a BaseException fail-open test |
| 1.5 | tag_protector: marker-mode stack over-pop (COR-8) + unquoted-attr `/` lookahead (COR-9) | Rust + nested-tag tests |
| 1.6 | Decoder-coverage honesty: gate the crusher's lossless accept to `Compaction::Table` until the decoder covers Buckets/Nested (COR-13, small + safe), decode `json`-tagged cells via `json.loads` (same item), decline compaction on column names containing `:,{}\n=` (COR-15); decide the dotted-flatten contract (COR-14 — owner call: grammar change vs documented value-exact) | bench floor-check (Table-only gating may cost a little compression — measure) |
| 1.7 | Wire the two ccr_store fields into one in DocumentCompactor (COR-19) | Rust, 3 lines + test |

### Phase 2 — Security & privacy batch (≈3 days; independent of Phases 1/3)

`trust_remote_code=False` default (SEC-1); TOIN honors `HEADROOM_TELEMETRY=off`
(SEC-2) and stops persisting raw queries (SEC-3) — both subsumed if Phase 3 deletes
TOIN, so sequence 2 after the Phase-3 decision or fix unconditionally if TOIN stays;
retrieval-log redaction: URL creds, PEM, bare JWT, multi-word quoted values (SEC-4);
jail hardlink error-string + intermediate-symlink documentation or `openat2` (SEC-5);
shared-stats single-lock rewrite (SEC-6); stats paths un-frozen (SEC-7).

### Phase 3 — The Great Excision (≈1 week; requires 4 owner decisions, then mechanical)

**Decisions first (see §5 Open questions):** (a) telemetry/TOIN: delete vs shrink;
(b) compression_feedback: delete vs wire; (c) tool_injection plane: delete vs keep
for upcoming MCP tool work; (d) Rust content_detector 700-LOC mirror: delete vs keep
as oracle. **Then, in dependency order:**

1. collector.py + beacon.py (keep `is_telemetry_enabled`) + collector-only models
   (~1,300 LOC) — 3-line edit at `compression_store.py:1199-1215` (SIMP-1)
2. compression_feedback.py + its store call (SIMP-2 / COR-cross C1)
3. TOIN per decision (delete: −1,600 LOC + 4 call sites; shrink: apply SEC-2/3,
   PERF-9/10, SIMP-4/5 caps and de-federation) (SIMP-3)
4. tool_injection dead plane (~340 LOC; keep `is_valid_ccr_hash` + patterns) (SIMP-6)
5. Rust: HF tokenizer stack + `tokenizers`/`hf-hub` deps (SIMP-7); `tiered.rs`
   (SIMP-8); 3 dead `#[pyfunction]`s (SIMP-9); dead config knobs — **wire-contract
   lockstep**: Rust config fields + PyO3 kwargs + Python dataclass fields in one
   commit with a deprecation shim at the bridge (SIMP-10)
6. Packaging: ast-grep dep (API-6, unless EFF-2a is chosen), httpx extra (API-7),
   nine fictional exceptions + CacheConfig/CacheStrategy exports (API-1), 21.6 MB
   unreferenced media (API-9), `tests/_dotenv.py` + unused markers (TEST-24),
   dead CI prefetch job + torch install (TEST-23), codecov.yml (TEST-25)

Gate: full suite + `cargo deny` + a `maturin sdist` content audit + import-graph
check that no deleted symbol is referenced.

### Phase 4 — Refactor (b): CCR typed dropped-refs across the FFI (≈1.5 weeks)

Full step sequence in §4.2. Depends on Phase 1.1/1.2 (persist shape settles first).
Retires all six text-scrape sites. Wire-contract lockstep throughout.

### Phase 5 — Refactor (a): ContentRouter decomposition (≈1.5 weeks)

Full step sequence in §4.1. Independent of Phase 4 in code, but sequenced after so
the engine extraction moves typed-mirror call sites, not scrape sites. Pure moves;
byte-identical outputs gated per step.

### Phase 6 — Correctness mediums + efficacy levers (≈2 weeks; each item isolated + bench-gated)

Each lands as its own commit with a before/after bench diff:
Bash exclusion decision (COR-10/EFF-1); analysis-intent word-boundary + narrowed
keywords (COR-16); word→token acceptance units (COR-17); option-aware cache keys +
collision guard (COR-18); router-cache atomic pops + sweep (COR-21, PERF-11);
kompress chunk_words vs 512 ceiling (COR-22); log traceback termination (COR-25);
search separator parse (COR-26); diff binary-regex (COR-27); mixed-array persist
skip + compacted decision (COR-28); small-array lossy-recoverable candidate (EFF-3);
lossless gate 0.30→~0.15 experiment (EFF-4); KompressCompressor.apply
frozen_message_count (COR-29).

### Phase 7 — Performance batch (≈1 week; byte-identical, no bench risk)

Token-count/deep-copy dedup in aligner+dedup+router (PERF-1); hoist pin-check +
single detection per message (PERF-2); orchestration memoization (PERF-3); crusher
clone elimination (PERF-4); declined-compaction render skip + classify_string
exposure (PERF-5); simhash MD5→fast-hash (PERF-6, bench-gated exception: k may
shift); log-selection index sets (PERF-7); throwaway-store key-only mode (PERF-8);
context-extraction caps (PERF-12); lazy `__version__` (PERF-13).

### Phase 8 — Test-debt + docs/API honesty close-out (≈1 week)

Remaining TEST items (coverage-theater fixes, boundary triples, tokenizer parity
test TEST-8, Rust integration byte-equality, helpers consolidation); then the full
DOC batch (README/llms.txt/RUST_DEV/SECURITY/NOTICE/DESIGN.md disposition/
CCR-RETENTION quote/beacon string); **CODEBASE-MAP re-anchor last** (crusher.rs
anchors drifted +145..+174 — after all crusher edits have landed); API honesty
(exceptions docs, protect_recent docstring, hooks population, PyPI description).

**Cross-phase dependency graph (the load-bearing edges):**
0.1→0.4 (baseline includes decoder fixes) · 0.3→everything (gates must be honest
before they verify batches) · 1.1↔1.2 (cause+detector, adjacent commits) ·
1.1→§4.2 (persist shape before typed refs) · Phase-3 decisions→2 (TOIN fixes vs
deletion) · §4.2→§4.1 (engine extraction moves typed sites) · all crusher.rs
edits→8 (map re-anchor once).

---

## 3. Findings by theme

Format: **ID · severity · location** — problem / why it matters / exact fix /
effort / risk & blast radius / dependencies. Severities are honest: *critical* =
reachable violation of a hard invariant or a broken deliverable; *high* = real
defect on a live path or a decision-grade gap; *medium* = correct-in-the-common-case
but wrong/costly at edges; *low* = worth fixing, bounded impact.

### 3.1 Correctness & invariant risk (COR)

**COR-1 · critical · `headroom/transforms/csv_schema_decoder.py:72`** — `_HEADER_RE`
lacks `re.DOTALL`, so a lossless render whose constant-column declaration contains a
newline (`[8]{id:int=0+1,note:string="line1\nline2",...}` — a legal, shipped shape:
the Rust formatter CSV-quotes constant declarations, `formatter.rs:530-541,615-617`,
and `stamp_constant_columns` excludes only Null/empty, `compactor.rs:394-397`) fails
the header match → `decode_csv_schema_rows` returns `None` → **0 rows recoverable**.
*Empirically reproduced.* / The lossless tier writes nothing to CCR
(`ccr_roundtrip.rs:112` pins that), so this is silent, unrecoverable loss on the
flagship path; repeated multiline strings (log messages, stack traces)
constant-fold easily; the fuzz generator never produces a constant column. /
**Fix:** add `re.DOTALL` to `_HEADER_RE`; add a fuzz case (all-rows-identical
multiline string column). / trivial / none — `.+` still anchors on the logical
line's final `}` / none.

**COR-2 · critical · `headroom/transforms/csv_schema_decoder.py:543-549` (+
`formatter.rs:487-490`)** — the head-dict branch passes the raw, still-CSV-quoted
cell to `_decode_head_cell`; a leading `"` fails the digit scan → row skipped.
Cells with commas/quotes/newlines in the tail are quoted by the encoder, and the
Rust stamp-time round-trip proof runs **before** quoting (`compactor.rs:742-762`),
so Rust can't catch it. *Empirically reproduced: `[20]{id:int=0+1,path:string@}`
with `"0/file 0, part.rs"` cells → 0/20 rows.* The affix branch had this exact bug
and was fixed with a comment (`:551-558`); head-dict was missed. Found independently
by two lanes. / Same invariant breach as COR-1, on path-like columns — a common
tool-output shape. / **Fix:** `value = _decode_head_cell(_unq(resolved), hd)`
(ditto-carry keeps the raw cell — it already does); fuzz case with comma-in-tail. /
trivial / none — `_unq` is identity for unquoted cells / none.

**COR-3 · critical · `verify/generators.py:117,131`** — loads
`verify/data/slugify_rg.raw.jsonl`, which was **never committed** (absent from tree
and from all git history; `verify/SOURCES.md:21` still lists it). `verify/run.py`
includes the `search` family (`:61`) and uses `check=True` subprocesses
(`:85-91`), so **`python -m verify.run` crashes** — the adversarial sweep the docs
cite as the engine's independent verification cannot run. / The verification story
is a headline claim; it is currently unexecutable. / **Fix:** re-commit the capture
(pattern exists: `verify/heldout/data/express_rg.raw.jsonl`) or repoint
`_real_paths`/`_real_match_lines` at an existing capture; fix SOURCES.md. / small /
none / do in Phase 0 before anything is "verified".

**COR-4 · high · `crusher.rs:1341-1362` (+ `ccr/mod.rs:58`,
`in_memory.rs:315`)** — `persist_dropped` writes one store entry per **original**
row (kept rows included, per its own comment at `:1315-1322`) + index + blob into a
1000-entry FIFO. Two ~1000-row droppable arrays in one document: the second array's
chunk flood evicts the first array's whole-blob → its surfaced `<<ccr:HASH>>`
dangles and the Python mirror (which reads `ccr_get` after `crush()` returns)
mirrors nothing. A single 1100-row array self-evicts its earliest chunks. /
Reachable breach of the recovery invariant at real workload sizes (the module's own
tests use 1000-row arrays). / **Fix:** persist only *dropped* rows (pass keep
indices into `persist_dropped`) and skip per-row chunking when
`n > capacity / 4` (add `CcrStore::capacity()`; `row_index_marker: None` is an
already-supported shape). / small-medium / low — whole-blob fallback is the tested
contract; `test_ccr_proportional_retrieval.py` must tolerate absent `_ccr_rows` on
huge arrays / pairs with COR-5 (detector) and COR-20 (marker count).

**COR-5 · high · `headroom/transforms/smart_crusher.py:965-975`** — a typed
row-drop hash (`r.ccr_hashes`) missing from the Rust store is logged at *debug* as
"marker leaked from elsewhere" — an excuse valid only for scraped hashes. Combined
with COR-4's self-eviction (`in_memory.rs:31-45` documents it "cannot be fully
eliminated"), this is a silent dangling-marker path, and Python is the last place it
can be caught. / The `CcrMirrorError` fail-open exists precisely for this class. /
**Fix:** for typed hashes only, treat `ccr_get() is None` as `CcrMirrorError`
(→ compress() reverts to originals); keep debug-skip for scraped hashes; `#rows`
index misses stay graceful *iff* the whole-blob resolved. / small / converts rare
silent loss into fail-open passthrough — invariant-correct / after COR-4; extend
`test_ccr_mirror_no_silent_loss.py` with a >capacity drop.

**COR-6 · high · `headroom/transforms/kompress_compressor.py:1354-1384`** —
`_store_in_ccr` swallows every exception and returns `None`; `compress()` then
ships the sub-0.9-ratio result **without a marker** and `apply()`/router applies it
— re-opening the applied-but-unbacked band the gate at `:936-949` exists to close.
Every sibling handles this loss class loudly (smart_crusher raises
`CcrMirrorError`; diff/log/search veto to passthrough, `diff_compressor.py:112-120`). /
Deleted words become unrecoverable with zero log output. / **Fix:** on store
failure, fall back to `self._passthrough(content, n_words)` at both call sites
(`:942-949`, `:1226-1233`), log at error; keep TOIN best-effort separate. / small /
rare store failures become passthrough — correct per invariant / none.

**COR-7 · high · `headroom/compress.py:395-406` + `crates/headroom-py/src/lib.rs:764`
(+ workspace `Cargo.toml:70-72`)** — Rust panics cross the FFI as
`pyo3_runtime.PanicException`, a `BaseException` that escapes `except Exception`;
`compress()`'s fail-open comment claims it catches "a Rust panic" and the workspace
Cargo.toml claims panics are "catchable" — both false. No Python file references
`PanicException`. / The one failure class the fail-open architecture exists for
(engine bug) is the one it cannot catch: a panic crashes the host request. /
**Fix (both ends, one commit):** wrap the hot bridge methods (`crush`,
`crush_array_json`, `smart_crush_content`, `compact_document_json`, the three
`compress`es) in `std::panic::catch_unwind` → `PyRuntimeError`; AND make
`compress()` catch `PanicException` explicitly (import-guarded) or
`BaseException` with immediate re-raise of `KeyboardInterrupt`/`SystemExit`; fix the
Cargo.toml comment; add a BaseException fail-open test. / small-medium / low (panic
paths only) / none.

**COR-8 · high · `crates/headroom-core/src/transforms/tag_protector.rs:571-572`** —
in marker mode (`compress_tagged_content=true`), close-matching runs
`stack.truncate(stack_idx)` **and then** `stack.pop()`, removing the enclosing open
tag. For `<a><b>x</b>y</a>`, `</a>` finds no match → left raw in the cleaned text
while `<a>` became a placeholder; a compressor that strips the raw `</a>` (the
exact failure this module exists to prevent, module doc `:4-12`) yields asymmetric
tags after restore, violating the Hotfix-A9 symmetry invariant (`:666-675`). Block
mode (default) is correct. / Nested workflow tags (`<thinking>`, tool wrappers) are
the normal case for agents. / **Fix:** delete the `pop()` line; add a nested-tags
marker-mode test. / trivial / marker mode only (non-default) / none.

**COR-9 · medium · `tag_protector.rs:374-395`** — in the attribute loop, `/` sets
`self_closing = true` and only whitespace resets it, so an unquoted attribute value
containing `/` (`<citation url=http://x.com>body</citation>`) misclassifies the
open tag as self-closing → body exposed, orphan close, unbalanced restore. /
Unquoted URLs in custom tags are common in LLM traffic. / **Fix:** treat as
self-closing only when `/` is immediately followed by `>` (lookahead); drop the
whitespace reset; test with an unquoted-URL attribute. / trivial / none for
well-formed input / none.

**COR-10 · high · `headroom/config.py:113` vs `:121,128`** — the comment block ends
"Bash is NOT excluded — its outputs (build logs, test output) are ideal compression
targets", but the `DEFAULT_EXCLUDE_TOOLS` frozenset **contains `"Bash"` and
`"bash"`**; `DEFAULT_TOOL_PROFILES` simultaneously assigns Bash a compression
profile (`:189-190`) that can never fire. One of the two is a real defect: either
the single largest compressible category for coding agents is silently never
compressed by default (contradicting the logs benchmark story), or the comment and
profile are lies. / Sits on the default hot path of every `compress()` call; also
the biggest single efficacy lever found (EFF-1). / **Fix:** decide intent; if Bash
should compress, delete the two entries + bench-gate (G1–G5 + needle); if not,
rewrite the comment and delete the dead profile. Add a pinning test for the chosen
routing. / trivial + bench / (a) changes output for Bash-heavy transcripts —
gate it / owner decision; Phase 6.

**COR-11 · medium · `kompress_compressor.py:815,1101,1290`** — `is_onnx = backend
== "onnx"` but the CoreML loader returns `backend="onnx_coreml"` (`:482,516`) →
PyTorch branch → `AttributeError` on `_OnnxModel.parameters` (`:861`); not in
`_MODEL_UNAVAILABLE_ERRORS`, so every request silently falls to the outer fail-open
— compression disabled for anyone using the documented
`HEADROOM_KOMPRESS_BACKEND=coreml`. / A documented knob is broken end-to-end. /
**Fix:** `backend.startswith("onnx")` at all three sites + a stubbed
`_OnnxModel`-under-`"onnx_coreml"` test. / trivial / low / none.

**COR-12 · medium · `kompress_compressor.py:1171` vs `:1186`** — when a batch
forward pass raises a model-unavailable error, affected texts are popped from
`kept_ids_per_text`; a later successful batch containing the same text's remaining
chunks does `kept_ids_per_text[text_idx].add(...)` on the popped key → `KeyError`
propagating as a "bug" for what is the handled-unavailable case. / Transient OSError
during batched GPU/ONNX runs becomes a crash. / **Fix:** membership guard, skip
finalized texts. / trivial / none / none.

**COR-13 · medium · `csv_schema_decoder.py:279-287,397` + `formatter.rs:579-583,611,
261-273`** — the reference decoder proves losslessness only for flat-scalar tables:
(a) `Compaction::Buckets` renders (`__buckets:`) return `None`; (b) `CellValue::
Nested` cells (CSV-quoted IR JSON) decode to plain strings; (c) object/array cells
in `json`-tagged columns decode as strings — the decoder's own comment ("CSV-quoted
cells are ALWAYS strings") is factually wrong for these two producers. Buckets are
reachable from `crush_array` (lossless gates check only `was_compacted() &&
!contains_opaque_ref()`, `crusher.rs:873/925/1191`). / Anything shipped from these
shapes is unverifiable by the very decoder the lossless claim rests on; (c) is a
silent type-fidelity loss. / **Fix:** decode `json`-tagged cells via `json.loads`;
gate the crusher's lossless accept to `matches!(c, Compaction::Table{..})` until the
decoder covers Buckets/Nested (small, fail-closed); extend fuzz with heterogeneous +
nested-object rows. / small (gate) to 1 day (full coverage) / Table-only gating may
cost some compression on heterogeneous arrays — bench floor-check / decide before
§4.2 (changes what "recovered" means).

**COR-14 · medium · `compactor.rs:292-355` + `csv_schema_decoder.py` (whole file)** —
`flatten_uniform_nested` rewrites `{"cfg":{"k":1}}` into a `cfg.k` column; the wire
grammar records nothing, and the decoder has no un-flatten pass → exact
reconstruction is impossible *in principle* for uniform nested objects, while the
module docstring (`:1-9`) promises exact row reconstruction and
`independent_recheck._canonical` counts such rows missing. *Empirically
confirmed.* / The strongest contract in the slice is quietly false for a very
common tool-output shape. / **Fix (owner call):** (a) grammar change — mark
flattened columns (`__flat:cfg=k,m` preamble or quoted literal-dotted names) +
decoder un-flatten, Rust+Python lockstep + fuzz; or (b) doc-honesty — state
value-exact-under-dotted-keys in both docstrings + CODEBASE-MAP and teach
independent_recheck to compare un-flattened. / (b) small, (a) medium / (a) is a
wire-format change — full fuzz net + bench / §5 open question.

**COR-15 · medium · `formatter.rs:311-352` + `csv_schema_decoder.py:294`** — column
names are emitted raw into the `[N]{...}` declaration; `_parse_header_segment`
splits on the FIRST `:`, so a key like `"meta:region"` silently mis-keys every
decoded row (keys with `,{}` at least fail the whole decode). The fuzz docstring's
claim that the formatter quotes special column names is false (only the KV
formatter does, `formatter.rs:820-826`). / Silent key corruption, not fail-closed. /
**Fix:** decline compaction (`Untouched`) when any key contains `:,{}\n=` or
preamble-shaped prefixes (~10 lines, fail-closed like every other gate); fix the
fuzz docstring. / small / rare keys just skip the lossless tier / none.

**COR-16 · medium · `headroom/transforms/content_router.py:2302-2351`** —
`_detect_analysis_intent` substring-matches an extremely broad keyword set
(`fix`, `error`, `bug`, `issue`, `problem`, `wrong`, `improve`…): "fix" matches
*prefix*, "error" matches any mention. In coding-agent traffic virtually every
recent user message trips one, so with defaults `analysis_intent` ≈ always true and
SOURCE_CODE is ≈ never compressed (protection 3, `:1711`) — a savings feature
silently near-disabled, with no log signal distinguishing why. / Conservative
direction, but the knob reads as selective and isn't. / **Fix:** module-level
compiled word-boundary regex; trim to genuine analysis verbs (drop
fix/error/bug/issue/problem/wrong); debug-log which keyword fired. / small / more
code gets compressed — bench-gate / Phase 6.

**COR-17 · medium · `router_dispatch.py:111,148-151,163,176-179,188-190,201` +
`content_router.py:1021,1077,1818,2062` vs `:1531-1536,1674`** — every "token"
inside the compression plane is `len(x.split())` (whitespace words), but the
acceptance gate `compression_ratio < min_ratio` compares that word-ratio against a
threshold derived from **tokenizer-measured** context pressure, while eligibility
uses the real tokenizer. Compaction outputs (CSV, comma-joined) have few spaces, so
word-ratios systematically overstate savings; the two units share the names
"tokens"/"compression_ratio" throughout the result types (the concrete face of the
known C6 name collision). / The core accept/reject decision is made in a different
unit than the one the product is graded on. / **Fix:** thread the real `tokenizer`
(already in `apply()`'s scope) into `compress()`/dispatcher as an optional counter
defaulting to word-split; at minimum rename fields to `words`/`word_ratio` where
that is what they are. / medium / real-token gating changes which messages compress
— isolated, bench-gated change / Phase 6; eases after §4.1's engine extraction.

**COR-18 · medium · `content_router.py:1745,1968-1996,2032`** — the result-cache key
is `hash(content)` alone: (a) per-request options are defeated on hits — a Tier-1
skip-hit serves the original even under `force_kompress=True`; a Tier-2 hit serves a
result computed under a different `target_ratio`/`kompress_model`/`bias`/`context`
(SmartCrusher query-relevance pins depend on `context`, `router_dispatch.py:147`);
`force_kompress` results get served to non-forced callers. All the RouterRuntime
threading is bypassed whenever the same bytes recur within the 30-min TTL. (b) The
64-bit SipHash key is served without any content-equality verification — a
collision substitutes another message's compressed bytes (CrossMessageDeduper got
this right: it verifies `first.content == content`, `cross_message_dedup.py:369-370`). /
(a) silently ignores public per-call API options; (b) is astronomically rare but
catastrophic-silent. / **Fix:** key on `hash((content, runtime, round(bias,3)))`
(+decide `context`); store `len(content)` (or `sha256[:16]`) in the entry and
compare on hit. / small / cache hit-rate drops for option-varying callers (correct);
counter-pinning tests need same-options fixtures / combine both halves; Phase 6.

**COR-19 · medium · `walker.rs:53-90` + `compaction/mod.rs:66`** — two different
`ccr_store` fields: `DocumentCompactor::with_ccr_store` sets a sibling field
consumed only by `walk_string`, leaving `config.ccr_store = None` for the
`compact()` calls in `walk_array`. Masked today (the walker substitutes opaques
before the array compactor sees them) but a loaded Defect-2 trap: any future path
where an opaque string reaches `cell_from_value` under a DocumentCompactor emits a
dangling marker with no stored original. / **Fix:** also set `config.ccr_store`
(idempotent, same hash/bytes) or delete the duplicate field. / trivial / none /
none.

**COR-20 · low · `crusher.rs:1355`** — the `_ccr_rows` marker advertises
`dropped_count` chunks but the index written at `:1342-1354` holds
`original_items.len()` row hashes (kept rows included): "keep 7 of 60" renders
`<<ccr:HASH#rows 53_chunks>>` over a 60-entry index, contradicting the grammar doc
(`ccr/markers.rs:40-42`). / Model-visible lie; harmless to parsing (grammar matches
hash+width). / **Fix:** COR-4's dropped-rows-only persist makes `dropped_count`
correct; otherwise pass `row_hashes.len()`. Marker byte change → re-pin the grammar
characterization test in the same commit. / trivial / byte change to marker text /
land with COR-4.

**COR-21 · medium · `headroom/transforms/router_cache.py:7-10,27-29,65,80`** — the
header claims "all access happens on the main thread … lock-free design … must be
preserved", but the pipeline is a process singleton (`compress.py:75,431-452`) and
the MCP server runs `compress()` on an executor (`mcp_server.py:654`) — concurrent
`apply()` calls share one cache. Two threads hitting the same expired key both pass
the non-None check and both `del` → `KeyError` crash on the hot path (same shape in
`is_skipped`); metric counters race benignly. Separately, "TTL is the natural
bound" is false: eviction is lazy per-key, so unique content (the common case for
tool outputs) leaks forever in a long-lived MCP server. / A crash the docstring
actively forbids fixing, plus a slow memory leak in the target deployment. /
**Fix:** atomic `pop(key, None)` in both lookups; opportunistic sweep on `put()`
every N insertions (or a max-entries FIFO cap, the pattern `InMemoryCcrStore`
already models); rewrite the header note honestly. / small / none — behavior
identical minus the crash / none.

**COR-22 · medium · `kompress_compressor.py:830,846-853`** — `chunk_words=350`
routinely exceeds the model's 512-token `max_length` (≈1.3–1.5 tok/word for prose;
far more for code/URLs); `truncation=True` drops tail tokens, whose words get no
`word_ids` and are therefore **always deleted** regardless of importance —
systematic positional deletion invisible to the threshold and to `target_ratio`
top-k. / Quality: the model never scored the tail; durability mostly saved by the
CCR gate. / **Fix:** lower default `chunk_words` to a measured fit (~250) or detect
truncation (word_ids coverage) and re-chunk the remainder; document the 512 ceiling
in `KompressConfig` (`:713-726`). / small-medium / output changes — bench floor /
Phase 6.

**COR-23 · low · `crates/headroom-core/src/transforms/smart_crusher/anchors.rs:100`**
— quoted-anchor length check uses UTF-8 **byte** length (`.len() >= 2`) where the
Python twin counts characters: `'é'`/`'日'` accepted as anchors in Rust, rejected in
Python — a real keep-pinning divergence on unicode queries. / **Fix:**
`.chars().count() >= 2`. / trivial / none / parity rule: land noting the Python
behavior it now matches.

**COR-24 · low · `smart_crusher/field_detect.rs:179`** — ties count as "descending"
(`w[0] >= w[1]`): a constant bounded column (e.g. `progress: 0.5` ×30) scores 0.7 →
score-field → `search_results` pattern → TopN sorts on a constant → degrades to
keep-first-K, silently positional. A rank signal requires variation. / **Fix:**
require `unique_count > 1` (or variance > 0) before the descending bonus, or count
only strict decreases. Python lockstep (parity fixtures pin the behavior). / small /
parity-visible — both languages one commit / parity rule.

**COR-25 · medium · `log_compressor.rs:509-525`** — Python-traceback termination
returns `!starts_with(uppercase)` for non-indented lines, so after a traceback every
following uppercase-starting line (`INFO …`, `Build succeeded`) continues the trace
until a lowercase/digit line or the 20-line cap — inflating `is_stack_trace` scoring
(+0.3, `:983`) and stack-trace selection (`:806-811`) with unrelated noise. /
**Fix:** small state extension (`Continue | IncludeAndEnd | End`): include the
single exception-message line, then terminate. / small / selection changes for logs
with tracebacks — bench floor-check / Phase 6.

**COR-26 · medium · `search_compressor.rs:570-621`** — the leftmost
`<sep><digits><sep>` scan misparses filenames containing `-<digits>-`
(`utils-v2-final.py:42:content` → file `utils-v`, line 2), and the two separators
may disagree (`file.py:42-text` parses) — silent mis-grouping invisible in stats. /
**Fix:** prefer the colon-only `:N:` form first (grep match lines are always
`path:N:…`); the dash fallback requires both dashes (rg context lines); keep the
Windows-drive skip. Test: `foo-2-bar.py:42:x` parses as file `foo-2-bar.py`. /
small / changes only previously-wrong parses / Phase 6.

**COR-27 · medium · `diff_compressor.rs:665-668,750-753`** — `^Binary files .+
differ$` cannot match the compressor's **own output** `Binary files differ`
(requires ≥1 char between "files " and " differ") — recompression silently drops
the line (the guard at `:383` is dead) — and CRLF input (`differ\r`) fails `$`,
losing the binary marker entirely. / **Fix:** `^Binary files (.+ )?differ\r?$`;
output stays byte-identical for currently-matched inputs. / trivial / none /
Phase 6.

**COR-28 · medium · `crusher.rs:1461-1475`** — `crush_mixed_array`'s dict arm
destructures only `items` from the inner `crush_array` call, discarding two side
effects: (a) the inner lossy path already wrote blob + n chunks + index into the
store under a hash **no surfaced marker names** — store pollution feeding COR-4's
eviction pressure; (b) an inner lossless `compacted` win is thrown away — the dict
subgroup ships entirely uncompressed while `strategy_parts` reports `dict:25->25`. /
Wasted CPU + capacity burn + a real compression gap on "tabular dicts inside a
mixed array". / **Fix:** internal `crush_array_inner(items, …, persist: bool)` for
the mixed arm (persist-skip half is behavior-invisible); separately decide whether
to substitute the subgroup's `compacted` (changes output bytes — bench-gate) or
document it ignored. / medium / persist-skip safe; compacted half bench-gated /
after COR-4.

**COR-29 · medium · `kompress_compressor.py:1314-1352`** —
`KompressCompressor.apply()` silently discards `frozen_message_count` (the pipeline
forwards it, `pipeline.py:286`) and would compress messages inside the frozen
prefix — breaking prompt-cache prefix ordering for any pipeline that includes it.
Latent (production routes via ContentRouter), but it is a public `Transform`;
`SmartCrusher.apply` honors the kwarg (`smart_crusher.py:1162,1174-1175`). Also
`tokens_before` stringifies block-list content (`:1321`). / **Fix:** honor
`kwargs.get("frozen_message_count", 0)` in the loop; count str content only. /
small / none / none.

**COR-30 · low · `content_router.py:1032-1048` + `router_split.py:149-159`** —
mixed reassembly is not byte-faithful even when every section passes through
(`"\n\n"` join, whitespace-only sections dropped, fences re-synthesized), so direct
`compress()` callers get mutated bytes at ~zero savings with
`strategy_used=MIXED`; fence markers are also re-added *after* `compressed_tokens`
is counted, undercounting fenced sections. The apply() path is saved only by the
ratio gate. / **Fix:** if no section changed, return the original string verbatim
as PASSTHROUGH; count fence-wrapped content after wrapping. / small / direct-caller
outputs improve / none.

**COR-31 · low · `content_router.py:1721-1725,2223-2230,2263-2271`** —
already-compressed pinning keys on the human phrase (`"Retrieve more: hash="`)
only; with `ccr_inject_marker=False`, crushed output carries `<<ccr:` sentinels but
no phrase, so after result-cache expiry the message is re-compressed and the
sentinel row rides through a second crush whose survival is not contractual. /
**Fix:** add `or "<<ccr:" in content` to all three pin checks. / trivial / slightly
more pinning (correct direction) / none.

**COR-32 · low · `headroom/ccr/marker_grammar.py:88-101` + `mcp_server.py:677` +
`compression_store.py:405`** — `is_valid_ccr_hash` lowercases before checking, so an
uppercase hash passes the format guard, then **misses** in the store (keys are
stored lowercase) — a confusing "evicted/never stored" miss instead of a format
rejection or a hit. / **Fix:** normalize at ingress (`hash_key = hash_key.lower()`
in `_handle_retrieve`) — friendlier to models that title-case. / trivial / none /
none.

**COR-33 · low · `crusher.rs:1153-1156,1638-1652`** — `_dup_count` is stamped even
when the plan dropped nothing, and on **every** visible copy of a duplicate family
(N rows each claiming N duplicates) — token inflation on a no-drop path. / **Fix:**
gate annotation on `dropped_count > 0` or stamp only the family representative. /
small / narrow edge; add a pin test / none.

**COR-34 · low · `analyzer.rs:398-406`** — the temporal-field branch's comment
claims a `mn != 0` mirror-check that does not exist, and `max_val` is bound then
ignored: min=1.5e9 with max=9e17 still classifies temporal → `time_series` flip. /
**Fix:** verify the Python twin, then either check both ends or fix the comment. /
trivial / behavior change only if tightened — parity-check first / parity rule.

**COR-35 · low · `planning.rs:235,319-356,432,494`** — `keep_existing_only` is
`false` at all three call sites (dead branch); `plan_top_n` re-implements
query-signal logic inline and never runs `prioritize_indices`/dedup — its keep set
is unbounded above `max_items` via anchor adds, so the CCR-backed halved budget is
ignored on the TopN strategy. / **Fix:** drop the dead bool; document or fix
(Python-lockstep) TopN's budget exemption. / small–medium / TopN budget change is
parity-visible / parity rule.

**COR-36 · low · `headroom/ccr/mcp_server.py:344-391,933,964` (+ `:257`)** —
`_compress_content` ignores `result.error`: a fail-open compress (tokens_after=0)
is stored and booked as `savings_percent=100`; `_handle_read` cache hits book
fictional savings into the same totals; `original_tokens` is a word count. /
Stats surface lies to the operator. / **Fix:** branch on `result.error` (return
error-shaped payload, skip record); separate `cache_hits`/`cache_tokens_avoided`
counters; use the tokenizer. / small / additive stats-shape change / none.

**COR-37 · low · `compression_store.py:434-437,856-858,1051-1061`** — the
feedback-before-lock comment is wrong (eviction events are processed on the *next*
call); `search()` bumps `entry.retrieval_count` even for zero-result queries
(contradicting `mcp_server.py:415-418`'s rationale); `_clean_expired` never records
the eviction-success signal capacity-eviction does. / **Fix:** fix comment; move
`record_access` after results known; align reaping — all moot in part if SIMP-2
excises the consumer. / small / none / after Phase-3 decision.

**COR-38 · low · `headroom/transforms/html_extractor.py:154-182,160,38`** —
`trafilatura.extract` returning `None` is coerced to `extracted=""` with ratio ≈ 0
("best compression ever"); safe only via the router's empty-output guard — direct
callers get silent total loss with no CCR backing; empty input yields ratio 0.0
where every sibling passthrough is 1.0; the module also mutes the global
trafilatura logger at import. / **Fix:** explicit failure signal (`success: bool`
or `extracted=None`), ratio 1.0 on empty/failed, logger suppression into
`__init__`; touch the dispatcher's `.extracted` read (`router_dispatch.py:198-202`). /
small / low / none.

**COR-39 · low · `content_router.py:1495,1842-1844`** — `tokens_before/after` run
`tokenizer.count_text(str(content))` on block-list content — tokenizing the Python
`repr`. Deltas are roughly meaningful; absolute numbers (and the derived
`context_pressure` at `:1532`, which drives `min_ratio`) are inflated fictions for
block-format conversations. / **Fix:** a `_message_text(m)` that concatenates
text/tool_result payloads for list content; use in both counts. / small / reported
metrics shift (more accurate) / none.

**COR-40 · low · `headroom/tokenizers/` (4 items)** —
(a) `tiktoken_counter.py:194-206`: the `count_messages` override stringifies every
part type it doesn't special-case — Anthropic `image/source` base64, `tool_result`,
Strands parts — re-introducing on the **default gpt-4o path** the base64-as-text
explosion `base.py:140-232` exists to prevent (1 MB image ≈ 330K fake tokens);
fix: delegate unknown parts to the inherited `_count_content_parts` (small; counts
change for multimodal — they were wrong before). (b) `registry.py:141,154` +
`tiktoken_counter.py:96-117`: case split — "GPT-4o" silently gets `cl100k_base`;
fix: lowercase once in `__init__` (1 line). (c) `registry.py:157-164` +
`huggingface.py:106-125`: one transient network failure caches the estimation
fallback for process lifetime; fix: don't cache failures / TTL negative-cache.
(d) `mistral.py:65-79`: every v3 model gets the *tekken* tokenizer, but
mistral-large/small are SentencePiece-v3 → systematically wrong counts for the
flagship models; `v2` branch unreachable; fix: split the map, verify against
mistral-common. / (a) is the weightiest — medium on its own. / small each / (a)
changes multimodal counts / none.

**COR-41 · low · misc single-line correctness nits** — `router_dispatch.py:311-319`:
TOIN receives the *requested* strategy, so fallback-Kompress wins are never recorded
(pass `actual_strategy`). `smart_crusher.py:407-414` vs `:434`: TOIN is recorded
*before* the mirror can raise `CcrMirrorError` → learning records for compressions
that never shipped (reorder). `cross_message_dedup.py:44-48`: the "elided row
remains visible in message N" claim is invalidated when the router later crushes
message N (soften wording; hash backing keeps it safe).
`in_memory.rs:283`/`with_capacity_and_ttl(0,…)`: `len()` counts expired entries vs
the trait doc; capacity-0 holds one entry (assert `capacity >= 1`).
`log_compressor.rs:708-721`: a trace longer than the cap re-opens as a "new" trace
per 20-line chunk (track `ended_by_cap`). `search_compressor.rs:466-510`:
per-file-cap stat double-counts global-cap truncations. / trivial each / none /
none.

### 3.2 Security & privacy (SEC)

**SEC-1 · high · `headroom/tokenizers/huggingface.py:119-122,148-149`** —
`AutoTokenizer.from_pretrained(tokenizer_name, trust_remote_code=True)`, with the
fallback "assume the model name is the tokenizer name": `compress(messages,
model=…)` routes `llama*/qwen*/deepseek*/phi-/yi-/falcon/...` prefixes here
(`pipeline.py:142-144` → registry), so any caller-influenced model string
downloads **and executes** repo code from the HF Hub when `transformers` is
installed. None of the mapped tokenizers requires remote code. / Remote-code
execution reachable from the public API surface. / **Fix:** default
`trust_remote_code=False`; opt-in env var for the rare legacy tokenizer; degradation
is the already-designed estimation fallback. / trivial / legacy `Qwen/Qwen-7B` load
may fail → estimation / none.

**SEC-2 · high · `headroom/telemetry/toin.py:1564-1596,388` vs `llms.txt:41`** —
`get_toin()` never consults `HEADROOM_TELEMETRY`; only the dead collector honors it
(`collector.py:753-761`), and none of the 4 recording call sites gate on it. Users
who set the documented opt-out keep getting `~/.headroom/toin.json` written. / The
exact over-claim class round-3 M6 supposedly fixed. / **Fix:** `get_toin()` returns
a disabled instance when `not is_telemetry_enabled()`. Subsumed by SIMP-3 deletion. /
trivial / tests relying on TOIN recording must set the env / Phase-3 decision.

**SEC-3 · high · `toin.py:1045-1064` vs `telemetry/__init__.py:12-15`, `toin.py:29-33`**
— `_anonymize_query_pattern` masks only `field:value` tokens; free-text queries
("find payments for john.smith@example.com", URLs, error strings) are stored
**verbatim** in `common_query_patterns` and written to `~/.headroom/toin.json` —
while the package docstring promises "What we DON'T collect: … Queries or search
terms". Query text flows in from `content_router.py:744`, `smart_crusher.py:688`,
`compression_store.py:1251`. / A written privacy contract is false; the file can be
synced/backed up/committed. / **Fix:** drop query-pattern collection entirely
(nothing consumes it) or hash the patterns. Subsumed by SIMP-3. / small / none —
write-only data / Phase-3 decision.

**SEC-4 · medium · `headroom/cache/compression_store.py:83-96,160-181,677-680`** —
the INFO-level retrieval log previews 4096 chars of the retrieved ORIGINAL; the
round-5-hardened redaction misses (live-probed): URL-embedded credentials
(`postgres://admin:pass@host`), PEM private-key blocks, bare JWTs (`eyJ…` without
`Bearer`), and multi-word quoted secrets (the value class `[^\"'\s,}]+` stops at
the first space, leaking the tail). / Retrieved originals routinely carry env dumps
and config files — these four shapes are the most common real secret carriers. /
**Fix:** four additional patterns (`://user:[REDACTED]@`, BEGIN/END PRIVATE KEY
block, `\beyJ[A-Za-z0-9_-]{10,}\.…`, quote-terminated value match when the opening
quote was captured); extend the round-5 test suite. / small / over-redaction of the
log preview only — declared safe at `:165` / none.

**SEC-5 · low · `headroom/ccr/mcp_server.py:764-796,847`** — the (off-by-default)
`headroom_read` jail is textbook fd-pinned TOCTOU hardening with two residuals:
`O_NOFOLLOW` guards only the final component (a directory component swapped to a
symlink between `resolve()` and `open()` escapes — fully closing needs a dir_fd
walk or `openat2(RESOLVE_BENEATH)`), and `st_nlink > 1` rejects legitimately
hardlinked files with a misleading "path outside workspace" message. / **Fix:**
distinguish the hardlink error string (10 min); either implement the
`openat2`/dir_fd walk or document the residual threat model. / small–medium / low;
feature off by default / none.

**SEC-6 · low · `mcp_server.py:190-228`** — `_read_shared_events` reads under
`LOCK_SH`, releases, then rewrites under a separate `LOCK_EX` open — an event
appended by another MCP process between the two is lost (the file exists for
multi-process aggregation). / **Fix:** one `open(..., "r+")` handle under a single
`LOCK_EX`: read, filter, `seek(0)`, `truncate()`, write. / trivial / none / none.

**SEC-7 · low · `mcp_server.py:169-170` vs `paths.py:22-23`** — `SHARED_STATS_DIR`/
`SHARED_STATS_FILE` are frozen at import, contradicting paths.py's explicit
no-caching contract; the jail re-reads env, the stats don't — they can disagree
about the workspace. / **Fix:** make them functions, call at the five use sites. /
trivial / none / none.

### 3.3 Architecture & coupling (ARCH)

**ARCH-1 · high (mandated) · `headroom/transforms/content_router.py` (2,363 LOC;
`apply()` ~507 LOC)** — the remaining god-object. Six seams were already extracted
(router_cache/split/policy/dispatch/ccr_mirror + compressor_registry), but the
orchestrator still owns four separable planes: a content-level compression engine,
a message-level policy walker, the Anthropic block walker, and the cache gate —
plus ~90 LOC of delegator shims and the module-level debug helpers. Full
decomposition plan in **§4.1**. / large / gated per step / after §4.2.

**ARCH-2 · high (mandated) · CCR opaque-path typing** — opaque
`<<ccr:HASH,KIND,SIZE>>` markers (and, on the live `SmartCrusher.apply()` path,
even row-drop markers) are recovered by re-parsing rendered text at six Python
scrape sites, instead of via typed FFI fields like the `crush()` row-drop path.
The typed carrier already exists but is private and lossy-flattened
(`DroppedRef`, `crusher.rs:187-195` → two unpaired `Vec<String>`s,
`types.rs:214-222`), and `row_index_markers` is typed-in-name-only (full marker
text that Python re-parses, `smart_crusher.py:473-489`). Full plan in **§4.2**. /
large / wire-contract lockstep / after COR-4/5.

**ARCH-3 · high · `headroom/telemetry/` (~3,400 LOC) + `headroom/cache/
compression_feedback.py` (613 LOC)** — the learning loop's consuming half was
amputated; the feeding half survived and runs on every request. Evidence:
`ToolIntelligenceNetwork.get_pattern/iter_patterns/get_stats/export_patterns` have
zero callers; the documented consumer is retired (`toin.py:5-9` claims "the Rust
core loads that TOML" — no loader exists; `crusher.rs:23` says TOIN never
overrides); `TelemetryCollector.record_compression` and every getter: zero
callers; `CompressionFeedback.record_compression`: zero callers, so
`get_compression_hints` can never pass its MIN_SAMPLES gate — and *it* has zero
callers too (`use_feedback_hints` is an inert flag, `config.py:241`,
`smart_crusher.py:203`); the one live signal is **inverted** — capacity-eviction
"successes" are booked as retrievals (`compression_store.py:1081-1115,1204`,
live-probed: 4 evictions → `total_retrievals=4`). / ~4,000 LOC of scaffolding
that cannot learn, is consulted by nobody, costs hot-path CPU/locks/IO, and
carries two highs (SEC-2, SEC-3). / **Fix:** Phase-3 decisions — delete
collector+beacon+feedback (near-zero risk; 3-line edit at the store call sites);
TOIN: delete (−1,600 LOC, 4 call sites, 4 test files) or shrink to a ~200-LOC flat
recorder with SEC-2/3 + caps applied. / medium-large / behavior-neutral for
compression output (all call sites already best-effort) / owner decision, §5.

**ARCH-4 · medium · `crates/headroom-core/src/transforms/smart_crusher/crusher.rs`
(3,513 LOC, ~49% tests)** — the Rust-side monolith. Natural 4-module split with no
behavior change: `walk.rs` (~480: crush/smart_crush_content/process_value*/
crush_mixed_array), `route.rs` (~430: crush_array/crush_array_lossy/floors/
budget), `persist.rs` (~330: persist_dropped/DroppedRef/sentinels/hash_canonical —
the invariant-bearing module, auditable in one screen), `crusher.rs` (~250:
struct/constructors/execute_plan); tests co-located per module. Only coupling to
break: `crush_array_lossy → persist_dropped` (moves via
`&Option<Arc<dyn CcrStore>>`). / Do §4.2's `DroppedRef` promotion first so the
split doesn't reshuffle it. / large / pure moves, byte-identical / after §4.2.

**ARCH-5 · medium · `diff_compressor.rs:471-505` + `log_compressor.rs:654-674` +
`search_compressor.rs:293-315` (Rust) and `diff_compressor.py:133-164` +
`log_compressor.py:220-248` + `search_compressor.py:198-233` (Python)** — the
marker+persist+ratio-veto tail is triplicated in both languages: `md5_hex_24` is
byte-duplicated three times in Rust (`diff:1141-1151`, `log:1143-1153`,
`search:633-643`), `hash_opaque` twice (`compactor.rs:1016-1024`,
`walker.rs:176-183`), and `_persist_to_python_ccr` is three verbatim 30-line
Python copies. / Three copies is how the next hash/threshold change misses one —
the map's change-index already has to enumerate all three. / **Fix:** Rust: one
shared `ccr/persist.rs` helper (`persist_and_mark(...)`) + single
`md5_hex_24`/`sha6_hex12`; Python: one `transforms/_ccr_persist.py`. Keys/markers
stay byte-identical (pinned by existing round-trip tests). / medium / low /
natural precursor to §4.2 — one seam to type instead of three.

**ARCH-6 · medium · `headroom/tokenizers/registry.py:25-65` vs
`crates/headroom-core/src/tokenizer/registry.rs:40-61`** — the Rust registry claims
to "mirror MODEL_PATTERNS" but only the OpenAI/tiktoken families agree: Python
routes mistral→mistral-common, llama/qwen/…→HF, gemini/cohere→calibrated
estimation; Rust sends all of those to chars/4 estimation (nothing in-repo calls
`register_hf`). The same model is counted differently on the two sides of the FFI,
so ratio/threshold decisions disagree — and nothing tests the two counts against
each other (TEST-8). / **Fix (tiered):** minimum — correct both docstrings to
state the divergence; add the TEST-8 parity test for the families that *should*
agree; ideal — single owner (route Python counting through the Rust registry, or
trim Python MODEL_PATTERNS to what Rust supports). / doc small; unification
large / doc none / TEST-8 first.

**ARCH-7 · low · `headroom/transforms/router_ccr_mirror.py:106,151-153`** — the
invariant-guarding CcrMirror calls SmartCrusher's **private**
`_mirror_ccr_to_python_store`/`_collect_ccr_hashes` across modules; a rename inside
smart_crusher.py silently breaks the CCR guard (the `except Exception` at `:112`
softens the break to a recompute). / **Fix:** promote the two methods to public
names with the old names as aliases; note the consumer in smart_crusher.py.
§4.2 retires the scrape half anyway. / small / none / with §4.2.

**ARCH-8 · low · `anchor_selector.rs:397-595`** — the Python-JSON-parity
serializers (`python_json_dumps*`, `write_python_json_*` — used for **canonical
hashing** by crusher/orchestration) live inside the anchor-selection module; two
unrelated load-bearing concerns share a file. / **Fix:** mechanical move to
`util/pyjson.rs`. / small / none / none.

**ARCH-9 · low · `headroom/transforms/read_lifecycle.py:241,259-283`** —
`_build_file_operation_index` re-scans all messages per tool call
(O(reads×messages)) although the index is known during `_build_tool_metadata`'s
single pass; `FileOperation.content_size`/`ReadClassification.content_size`
(`:51,:347`) are never populated; and this is the *third* independent dual-format
tool-call scanner (with `content_router._build_tool_name_map`, `:1364`, and
dedup's block walk). / **Fix:** record `msg_index` in the single pass; delete the
dead fields; longer-term one shared `iter_tool_calls(messages)`. / small / none /
none.

**ARCH-10 · low · `headroom/cache/backends/base.py:99,26` + `backends/memory.py:38`**
— the backend Protocol requires `keys()` and `exists()` that no code calls, and
`InMemoryBackend` carries its own lock although every production call site already
holds `CompressionStore._lock` (double-locking on every hot-path op) while the
Protocol doc says thread-safety is the implementation's responsibility — two
contradictory stories. / **Fix:** narrow the Protocol; pick one thread-safety
story and document it. / small / hypothetical third-party backends only / none.

**ARCH-11 · low · `crates/headroom-py/src/lib.rs:948-976,1004-1014`** — the
`PyDetectionResult.metadata` number-coercion ladder (u64→i64→f64→None, arrays→JSON
strings) is dead: the only constructor always passes an empty map and
confidence 1.0; the getter docstring describes values that cannot occur. /
**Fix:** collapse to `PyDict::new(py)` + comment, or drop the synthetic fields and
return the bare content-type string (aligned with §4.2's typing direction). /
small / Python reads only `.content_type`/`.confidence` (verified) / none.

**ARCH-12 · low · `crusher.rs:648-649` + `config.rs:129-146` + `lib.rs:613`** —
`enable_ccr_marker` is read by **zero** headroom-core code paths (FFI getter only,
for the router's retrieval-tool decision), yet lives on `SmartCrusherConfig` — and
the trap already sprang: the comment at `crusher.rs:648-649` claims the non-dict
sentinel "is gated by `enable_ccr_marker`" while the test at `:3028` pins the
opposite. / **Fix:** correct the comment now (trivial); consider renaming to
`advertise_retrieval_tool` / moving to the FFI config layer (medium — touches
Python kwargs). / trivial+medium / rename touches `lib.rs:480/502` kwargs / SIMP-10.

### 3.4 Types (TYPE)

**TYPE-1 · medium · `crusher.rs:1718-1723` ↔ `analyzer.rs:604-635,666,676,691` +
`FieldStats.field_type`** — three stringly-typed cross-module contracts: the
entropy-floor override gate matches crushability **reason strings** produced 900
lines away; `detected_pattern` is a free String matched in analyzer routing;
`field_type` (`"numeric"`/`"string"`/…) is compared in ≥8 places. A producer typo
silently changes routing (the reason gate is at least documented fail-closed;
the others are not). / **Fix:** `enum SkipReason` + reuse the existing
`DataPattern` enum + an internal `FieldType` enum — each with byte-identical
`as_str()` (parity fixtures pin the strings). Order: reason/pattern first
(internal-only), field_type last (FFI-mirrored shape). / medium / low-medium /
parity rule.

**TYPE-2 · medium · `types.rs:214-222` + `crusher.rs:187-195,412-419`** — the FFI
flattens the private, correctly-paired `DroppedRef { hash, row_index_marker }`
into two unpaired `Vec<String>`s ("may be shorter … never longer"), and the opaque
path has no typed representation at all. This is the enabling type for §4.2 —
promote to a public enum (`RowDrop { hash, row_index_key } | Opaque { hash, kind,
byte_size }`) with derived back-compat getters. / medium / low — side-output only,
bytes pinned by grammar/floor tests / §4.2 step R1.

**TYPE-3 · low-medium · the extracted router seams re-erase their types** —
`ContentRouter.__init__(observer: Any)` (`content_router.py:627`),
`CompressorRegistry(config: Any)` (`compressor_registry.py:43`),
`StrategyDispatcher(config: Any)` (`router_dispatch.py:61`), `router_policy`
functions take `config: Any` (`router_policy.py:41,71`), getters return `Any`,
callable aliases are "documentation, not enforcement" (`router_dispatch.py:38-41`).
mypy verifies nothing about e.g. `config.min_ratio_relaxed` existing. / **Fix:**
type `config: ContentRouterConfig` (TYPE_CHECKING import or a narrow Protocol of
the fields each seam reads); define a `CompressionObserver` Protocol
(`record_compression`, optional `record_router_route_counts`). / small-medium /
type-only / do immediately before §4.1 (these are the interfaces the decomposition
multiplies).

**TYPE-4 · low · `content_router.py:1554-1563,2186,2252,2027`** — `route_counts` is
a stringly counter with three seeding conventions (pre-seed + `setdefault` + bare
`+=` that would `KeyError` on an unseeded dict), plus a near-dead second `bump`
closure in `_compress_content_block`. / **Fix:** `collections.Counter[str]` (makes
every `+=` total); delete the local bump. / small / observer receives a dict
subclass — compatible / fold into §4.1 S3.

**TYPE-5 · low · naming-as-typing** — `KompressResult.original_tokens/
compressed_tokens` are word counts fed to TOIN/store as tokens
(`kompress_compressor.py:927-934,1361-1370`); `markers.rs:68` takes `unit: &str`
(`"lines"`/`"matches"`) where a two-variant enum makes invalid units
unrepresentable; `mcp_server.py:964` books word counts as `original_tokens`. /
**Fix:** rename or re-type each; COR-17 is the systemic version. / trivial each /
none / with COR-17.

### 3.5 Performance (PERF)

**PERF-1 · medium · `pipeline.py:237,258,346` + `cache_aligner.py:274,278,344` +
`cross_message_dedup.py:254-255` + `content_router.py:1495,1842`** — one request
pays up to **eight** full-conversation token counts and two deep copies: the
aligner counts the same unmutated list twice and deep-copies on top of the
pipeline's copy; dedup counts before/after; the router counts before/after; the
pipeline counts at entry and exit. On a 100k-token conversation with tiktoken this
is the dominant fixed overhead — on exactly the large-context requests the product
exists for. / **Fix:** aligner: count once, `tokens_after = tokens_before`, return
the input list (keep the copy in the public `align_for_cache` wrapper); dedup:
count once at entry; router reuse is optional/larger. Removes 3 counts + 1 deep
copy with two small edits. / small / aligner aliasing for direct callers — keep
the public-wrapper copy / none.

**PERF-2 · medium · `content_router.py:1699` vs `:953-968,1721,1746`** — content
detection (a Rust FFI round-trip + on-PLAIN_TEXT the full Python regex cascade)
runs **twice** per compressed message — once in `apply()` for the `is_code`
protections, again inside `compress()` — and runs even for messages about to be
pinned or served from cache. / **Fix:** (a) hoist the pin check above detection;
(b) skip detection when both code-protections are inert; (c) full dedup: let
`compress()` accept a precomputed `DetectionResult`. / small for a+b / (a)/(b)
behavior-identical by construction / (c) folds into §4.1 S5.

**PERF-3 · medium · `orchestration.rs:220-228,67,104,131,456` +
`analyzer.rs:465` + `planning.rs:86-95`** — the over-budget prioritizer
re-serializes and re-detects work already done: `detect_error_items_for_
preservation` runs with `None` (fresh serialize + keyword scan of every item)
though the caller computed `item_strings` precisely to avoid this;
`detect_structural_outliers` runs up to 3× per crush; `item_content_hash`
(md5+serialize) is recomputed 3-4× per item across dedup/fill/novelty. / **Fix:**
thread `item_strings` into `PrioritizeParams`; compute the per-index hash vector
once and share. Byte-identical outputs. / medium / low / none.

**PERF-4 · medium · `crusher.rs:898-906,935-943,1125-1133,1260`** — full-array
deep clones on the passthrough and skip paths (immediately re-wrapped by the
caller), into the lossless candidate even when MinTokens discards it, and again in
`render_result_string` for token counting. / **Fix:** internal
`Routed::Passthrough` vs `Routed::Result` enum (or `Cow`), defer building the
candidate's `items` until the route decision picks it. / medium / internal-only if
done via the enum / with ARCH-4.

**PERF-5 · medium · `compaction/mod.rs:120-124` + `compactor.rs:131-137` +
`walker.rs:142` + `crusher.rs:811`** — declined compactions still pay full
render (the CSV formatter serializes the **entire original array** for
`Untouched`, discarded immediately) and a full clone into
`Untouched(items.to_vec())`; every string is cloned just to classify because
`classify_string` is private. / **Fix:** check `was_compacted()` before
formatting; unit-variant or `Cow` for `Untouched`; expose
`classify_string(&str)`. / small-medium / `Untouched(Value)` used by JsonFormatter
tests — adjust / none.

**PERF-6 · medium · `adaptive_sizer.rs:158-178,192-232` + `log_compressor.rs:749-751`
+ `search_compressor.rs:428-438`** — one full **MD5 digest per 4-char window**
(a 10k-line log ≈ 770k MD5 calls inside `compute_optimal_k`), per-bigram
`(String,String)` allocations, and `select_matches` materializing every match as a
fresh `format!` string just to feed it. The MD5 choice was Python-parity; the
Python original is retired — nothing pins it. / **Fix:** fast 64-bit hash (xxhash/
FxHash) for grams, `(u64,u64)` bigrams, `&str` slices. / medium / k values may
shift slightly → gate on ratio non-regression, not byte equality / after the
parity-retirement doc decision (DOC-13).

**PERF-7 · low · `log_compressor.rs:761-849`** — selection clones every categorized
`LogLine` 2-3× though identity is `line_number`-only. / **Fix:** run
categories/selection on `BTreeSet<usize>`, clone once at output. / small /
behavior-identical / none.

**PERF-8 · medium · `crates/headroom-py/src/lib.rs:1281-1294,1468-1479`** —
`PySearchCompressor.compress`/`PyLogCompressor.compress` allocate a throwaway
1000-cap `InMemoryCcrStore` per call and have the core write the **full original
payload** into it, dropped on return — its only purpose is making the core emit
`cache_key`. Also an untested-contract hazard: no pytest pins that these bridges'
`cache_key` resolves in the Python store (TEST-9). / **Fix:** key-only mode in
`compress_with_store` (compute the key when criteria are met, no store), pinned by
a byte-equality test on `cache_key`. / small-medium / low / with TEST-9.

**PERF-9 · medium · `smart_crusher.py:643,672` + `toin.py:582`** — every modified
crush re-parses the **full original and full compressed payloads** with
`json.loads` purely for TOIN, then serializes all threads through one global
RLock. / **Fix:** free via ARCH-3 deletion; else pass the already-parsed items
down. / small / none / Phase-3 decision.

**PERF-10 · medium · `toin.py:1488-1507` vs `:1439-1450`** — `_maybe_auto_save`
calls `save()` **inside** the lock, defeating save()'s own
serialize-under-lock/write-outside-lock design: every 10 minutes a request thread
does a full-DB `json.dumps` + mkstemp/write/rename while blocking all recorders.
Plus no shutdown flush at all (`:393,1504-1507`) — short-lived CLI/MCP runs never
persist. / **Fix:** check/update timestamp under lock, save after release; atexit
dirty-flush. Moot under deletion. / trivial / benign double-save race at worst /
Phase-3 decision.

**PERF-11 · medium · `router_cache.py:27-29`** — the unbounded-growth half of
COR-21 (lazy per-key eviction only). Fix there. / — / — / COR-21.

**PERF-12 · low · `smart_crusher.py:1085-1121`** — `_extract_context_from_messages`
caps user messages at 5 but appends `tool_calls[].function.arguments` for **every**
assistant message in history: a 200-turn session pushes hundreds of KB of query
context into Rust BM25 on every crushed message. / **Fix:** same 5-message window
for the assistant scan + a total-chars cap. / trivial / slight relevance-signal
change — bench-check / none.

**PERF-13 · low · `headroom/_version.py:47-61` + `release_version.py:220-256` +
`__init__.py:50`** — `import headroom` spawns `git tag` + `git log` subprocesses
(~92 ms) in any checkout; non-hermetic imports; every test collection pays it. /
**Fix:** PEP 562 lazy `__getattr__`; move out of the eager import; see API-8 for
the placement question. / small / anything reading `__version__` still works /
none.

**PERF-14 · low · `tokenizers/estimator.py:104-116,133-140`** — auto-mode
`count_text` fully `json.loads`-parses a multi-MB valid-JSON string just to pick
3.2 vs 4.0 chars/token, plus three full-text regex scans — per call. / **Fix:**
detect on a 4 KB prefix sample. / small / unknown-model estimation path only /
none.

**PERF-15 · low · `tag_protector.rs:694-711`** — `restore_tags` is O(blocks×text)
with a full-string realloc per block, and `str::replace` substitutes **all**
occurrences of a placeholder (a compressor that duplicates a placeholder gets the
original injected twice). / **Fix:** single left-to-right scan matching each
placeholder once. / small / none / none.

### 3.6 Tests, benchmarks & verification (TEST)

**TEST-1 · high · `.claude/runtime/gate.sh:41,44`** — G4 (the recovery-invariant
gate) is `pytest … | grep -q '23 passed'`: the output `"1 failed, 23 passed"`
**matches** → PASS with a failing recovery test; adding a test spuriously fails;
the failure message still says "21-green". This contradicts the file's own G2
lesson ("exit code can't lie", `:11-15`). / **Fix:** key on exit code; pin counts
via `--co -q | wc -l` if wanted. Prove by breaking a recovery test → red. /
trivial / none / Phase 0.

**TEST-2 · high · `gate.sh:49,56,7` + `.claude/runtime/floor_check.py:16-56`** —
G5 discards run_bench's exit code (`set -uo` without `-e`); on a crash the
working-tree baseline equals HEAD's → floor_check compares HEAD to HEAD →
**guaranteed PASS with zero fresh measurement**. floor_check also iterates *floor*
datasets only, so repeated_logs/disk/multiturn are never floor-checked; the gate's
restore line omits `benchmarks/data/`; and `gate.sh:7` hardcodes
`cd /Users/k/dev/headroom`. / **Fix:** check the exit code; reject
`cur.captured_at == floor.captured_at`; fail on `current − floor` dataset
difference; `cd "$(git rev-parse --show-toplevel)"`; trap-restore everything (or
run_bench `--out`). / small / none / Phase 0.

**TEST-3 · high · `benchmarks/BASELINE.md:3-4` + `baseline_results.json`** — the
committed baseline is a 2026-06-12, 3-dataset capture at commit `0795e63e`, which
**does not exist** in the (squashed) history; current code produces six datasets
(`datasets.py:623-632`); the shipped engine measures ~93% on logs/search
(`BENCHMARKS.md:159-166`) vs the tabled 84.5%/40%; and the provenance commands are
no longer re-derivable (`git log -n 300` vs a 50-commit history). / The ratchet is
anchored to an unverifiable snapshot and half the suite is ungated. / **Fix:**
re-run at HEAD, commit the 6-dataset baseline, correct the provenance text to
"committed snapshot; capture command historical". / small / re-baselining resets
the ratchet — confirm no regression first / Phase 0.4, after COR-1/2.

**TEST-4 · medium · `benchmarks/run_bench.py:314-328` + `run_final.py:33,105-123`**
— run_bench unconditionally overwrites the committed baseline files and silently
re-captures `data/*.raw.json` when any snapshot is missing; run_final writes a
never-committed `final_results.json`, silently refresh-alls six datasets on one
missing file, and mis-scores multiturn (uses `measure_case`, not
`measure_conversation_case` as run_bench correctly does). (The "pytest dirties the
tree" claim in handoff.md is **disproven** — a full pytest run leaves the tree
byte-clean; the dirtying path is gate.sh.) / **Fix:** run_bench `--out` dir or
explicit `--write-baseline`; run_final: fail loudly on missing snapshots, fix the
multiturn scorer or move to archive/ with a header. / small / floor_check's
CUR_PATH updates in the same change / Phase 0.

**TEST-5 · high · 20+ conditional-skip sites in the invariant suites** — census
(all verified): `test_smart_crusher_toin_attachment.py:79,111,133,194,214,246,283`
(the whole TOIN-regression suite can go vacuous; `:200-219` can run **zero**
assertions), `test_diff_compressor_sidecar_persist.py:129,153,220,232`,
`test_result_cache_ccr_divergence.py:203,271,360,416` (the P0 divergence suite),
`test_ccr_marker_grammar_characterization.py:729,820`,
`test_ccr_persist_failure_vetoes.py:164`, `test_ccr_eviction_loud_miss.py:132,141`.
Today zero fire (verified: 50/50 pass) — but one benign threshold bump flips them
to skip-forever with green CI; these files pin silent-data-loss fixes. / **Fix:**
hard-assert preconditions where a sibling proves the fixture fires; else one
`test_fixture_actually_fires` per file; optional gate check that skip-count == 0
for the CCR suites. / small / may expose fixture drift (the point) / Phase 0.5.

**TEST-6 · high · `tests/test_csv_schema_decoder_roundtrip_fuzz.py:538-628`** —
the **default-policy** "zero silent loss" fuzz test never checks for loss: the
string/`None` branch falls through with a comment and zero assertions
(`:583-593`); the sentinel branch never resolves dropped rows (`:597-616`); the
sentinel-key loop is a tautology (`:604-605`). The lossless-policy sibling
(`:529-535`) does it right. / A regression dropping half the adversarial rows on
MinTokens passes. / **Fix:** compute `missing = expected − (kept ∪ decoded ∪
CCR-recovered)` (machinery exists in `test_ccr_recovery_invariant.
_recover_from_output`) and assert empty; `pytest.fail` on the fall-through
branch. / small / may expose a real gap / Phase 0.5.

**TEST-7 · medium · `tests/test_compress_frozen_prefix.py:14-16,200-240`** — the
"parity" class claims values "taken verbatim from
`crates/headroom-core/tests/cache_control.rs`" — **no file in crates/ mentions
`compute_frozen_count` or `cache_control`** (the Rust half of the frozen-prefix
parity lock is fictitious); and two "system/tools markers don't bump" tests
contain no system message and no cache_control at all — byte-identical to the
no-marker test, they cannot fail. / **Fix:** honest docstring ("characterization
of the Python owner"), delete or realize the two vacuous tests, drop the stale TDD
header + unused imports (`:8-10,23-25`). / small / none / none.

**TEST-8 · medium · missing Python↔Rust tokenizer-count parity** — the engine
makes keep/drop and ratio decisions with the Rust tiktoken port
(`tokenizer/tiktoken_impl.rs`) while all measurement counts with Python tiktoken;
`test_tokenizers.py` is `count > 0` smoke throughout (`:59-77` etc.),
`tokenizer_proptest.rs` tests Rust against itself. Drift silently skews every
threshold and every reported ratio. / **Fix:** one parametrized corpus test
(ASCII, CJK, emoji, code, 100 KB blob): `TiktokenCounter("gpt-4o").count_text(s)
== _core count`. / small / may reveal real drift / none.

**TEST-9 · medium · no pytest pins the search/log bridge `cache_key`-resolves
contract** — the throwaway-store bridges (PERF-8) emit `[… Retrieve more:
hash=…]` markers whose only backing is the Python shim's re-persist; `headroom-py`
has `test = false` (`Cargo.toml:19-27`) so Rust cannot test it, and no Python test
asserts the marker's hash resolves after `compress()`. / **Fix:** pytest per
bridge: compress → extract cache_key → `store.retrieve(key)` returns the
original. / small / none / with PERF-8.

**TEST-10 · medium · `crates/headroom-core/tests/ccr_roundtrip.rs`** — roundtrip
assertions are parsed-`Value` equality, not byte equality (`:52-54,69,91,178,204`
— key-order/number-form changes pass); `without_compaction_also_stores_dropped_
rows` (`:57-72`) and `lossless_win_does_not_write_to_store` (`:112-132`) are
conditionally vacuous (`if let`/`if` gates); `full_crush_pipeline_roundtrips_
through_store` (`:274-291`) asserts only `store_len > 0` — it roundtrips
nothing. / **Fix:** add string-compare vs canonical serialization; assert the
preconditions; use the existing `extract_hash_from_marker` (`:434`) and assert
`store.get(hash) == canonical`. / small / second test's fixture may prove
off-path / none.

**TEST-11 · medium · coverage-theater census (Python)** — the sweep's verified
list, each with the concrete fix in place: `test_tokenizers.py:62-398` pervasive
`count > 0` (assert relative/pinned counts); `test_ccr.py:378-391`
`isinstance(list)` only (pin the contract); `test_text_compressors.py:388-399`
passes on a no-op (assert an actual drop); `test_search_compressor.py:470-503,
370-392,221-234` can't detect the named behaviors (counterfactual compares);
`test_log_compressor.py:191-206` asserts `max_total_lines` after setting
`max_errors=5` (count ERROR lines); `test_compress_api.py:36-50` "should be
compressed" allows passthrough (`tokens_saved > 0`);
`test_transforms_log_compressor.py:22-28` npm case never asserts `cache_key`
round-trip; `test_read_lifecycle_phantom_hash.py:219-227,258-263` OR-shaped
asserts pass when the feature never fires; `test_result_cache_ccr_divergence.py:
250-259,394-400` asserts "backed", not byte-equal (reuse the recovery-invariant
subset check); `test_crush_typed_hash_parity.py:171-174` compares
`ccr_get(h) == ccr_get(h)` — a literal self-comparison;
`test_csv_schema_affix_multiline.py:86-93` silent `return` + conditional assert
lets full-row-drop pass. / **Fix:** one hardening batch, each item ~trivial. /
small aggregate / none / Phase 8.

**TEST-12 · medium · boundary gaps** — the 256-byte opaque floor is tested at
255/256/257 in Rust (`crusher.rs:1931-1935`) but Python fixtures only use 600-byte
blobs (`test_ccr_recovery_invariant.py:236-241`); kompress's `ratio < 0.9` CCR
gate has no ≥ 0.9 case (`keep_k=18`); min_tokens floor has no sub-50 raw-path
case; read_lifecycle 200-byte floor, dedup `MIN_DEDUP_CHARS ==`, search
`min_matches_for_ccr` activate-side, log `min_lines` at N — all one-sided. /
**Fix:** one at/below/above triple per threshold (the standard
`test_kompress_hardening.py:41-67,323-344` already sets). / small / none /
Phase 8.

**TEST-13 · medium · `tests/conftest.py:25-39`** — a suite-wide hookwrapper turns
**any** `httpx.ReadTimeout` failure into a skip; the network suites it served no
longer exist, so today it can only mask a genuine bug. / **Fix:** delete or scope
to a `live` marker. / trivial / none / with TEST-24.

**TEST-14 · medium · `.github/workflows/ci.yml:105-131,134,158-173`** — a
`prefetch-model` job downloads `sentence-transformers/all-MiniLM-L6-v2` (with
retries and an HF_TOKEN secret) that **nothing imports**; the test matrix `needs:`
it; the test job installs CPU torch though kompress is ONNX-only
(`pyproject.toml:57-62`); `grep -rl "import torch"` over the repo is empty. /
**Fix:** delete the job, the edge, the cache-restore, the torch install. / small /
validate one green CI run / none.

**TEST-15 · medium · `verify/REPORT.md:91,105,108-109` +
`independent_recheck.py:1-11` + `heldout/REPORT.md:211`** — the reports cite a
`_present_in_text` fallback and line numbers that no longer exist (the code is now
*stricter* than the report says), and both REPORTs claim numbers "byte-identical
to the committed `raw_results.json`" — which is **not committed** in either tree.
/ The headline replication claim is unverifiable from the repo. / **Fix:** commit
the raw results (or delete the claims); regenerate/stamp REPORT.md against the
commit it audited; two-line recheck docstring update. / small / none / Phase 0–8.

**TEST-16 · low · benchmark honesty residue** — `benchmarks/metrics.py:246-249,
282-284` still has the lenient scalar-substring presence fallback verify removed
(port the strict ladder); `needle_recall.py:90` names the needle **in the query**
(best-case recall by construction — add a non-naming control arm);
`metrics.measure_case` never resets stores → warm-state numbers vs verify's cold
(reset per case); `verify/measure.py:273-275` "byte-exact" is a canonical
multiset (rename or add an ordering check); `imp2_ab.py:117-145` mirrored
exclude-set unvalidated + corroboration printed not asserted. / **Fix:** as
listed. / small each / needle numbers will drop (honest) / Phase 8.

**TEST-17 · low · Rust in-module near-vacuous tests** —
`encodings.rs:735-749` civil-math loop can't fail on valid dates
(continue-without-assert; only 4 spot anchors bite); `planning.rs:998-1028`
asserts only non-empty where the name promises a ±2 window;
`orchestration.rs:771-790` asserts only `len <= 10` where the name promises
first-3/last-2; `crusher.rs:2344-2355` conditionally vacuous. / **Fix:** real
membership/round-trip asserts. / small / none / Phase 8.

**TEST-18 · low · PyO3 boundary error paths untested** — `crush_array_json`
ValueError (`lib.rs:824-833`), routing-policy parse (`:507-512`),
`with_compaction_format` (`:746-752`), `compact_document_json` (`:873-888`);
plus `CompactionStage::from_format_name`/`SUPPORTED_FORMAT_NAMES` keep-in-sync
pair has zero tests anywhere (`compaction/mod.rs:102-115`). / **Fix:** one pytest
of the four error shapes + a 6-line Rust test over the names. / trivial / none /
none.

**TEST-19 · low · duplicated load-bearing fixtures** — `_log_shaped_rows`/
`_log_rows` + vocabulary tables copied verbatim between
`test_ccr_recovery_invariant.py:293-338` and
`test_result_cache_ccr_divergence.py:80-114` (the fixture is delicately tuned to
stay lossy — divergence rots to skip if re-tuned in one file); kompress stubs
quadruplicated across 4 files; `_make_large_diff`/`_FailingStore`/aligner
helpers/MCP stubs ×2–3; **cross-test-file import**
`test_lossless_column_encodings.py:26` imports from
`tests.test_ccr_recovery_invariant`. / **Fix:** `tests/_fixtures.py` +
`tests/_kompress_stubs.py` with an `assert_fixture_drops()` self-check; kill the
cross-import. / small-medium / none / with TEST-5.

**TEST-20 · low · slow tests unmarked** — `pyproject.toml:199-203` registers
`slow/real_llm/live`; zero users. Heaviest offenders:
`test_runtime_options_thread_safety.py` (16 threads ×2 + 32 full compress runs),
`test_ccr.py:86,349` (real `sleep(1.1)` ×2 ≈ 22% of suite wall-time — inject a
`now_fn`), `test_ccr_proportional_retrieval.py`. / **Fix:** fake clock + mark or
delete the markers (TEST-24). / small / none / none.

**TEST-21 · low · `test_transforms_content_router.py:24-55`** — exhaustible
`time.time` iterator (`StopIteration` on any refactor that adds a call). /
**Fix:** `itertools.chain(times, repeat(112.0))` or a clock object. / trivial /
none / do before §4.1.

**TEST-22 · low · `test_mcp_server_handlers.py:75-88`** — closure-cell
introspection of the MCP SDK's private wrapper (breaks on any `mcp` bump). /
**Fix:** expose the routing handler as a named attribute on `HeadroomMCPServer`
and call it directly. / small / none / none.

**TEST-23 · low · dead CI/coverage config** — `codecov.yml` with no coverage
upload anywhere (`ci.yml:12` admits it); `[tool.coverage.*]` unexercised;
ci.yml tests only 3.11 while classifiers promise 3.10–3.14
(`pyproject.toml:38-42`). / **Fix:** delete or wire; align classifiers or add the
matrix. / trivial-small / none / none.

**TEST-24 · low · dead test-support code** — `tests/_dotenv.py` (106 LOC, serves
suites that no longer exist, no importer), the three unused markers, dead helpers
`_has_ccr_sentinel`/`_compress_to_csv_text`
(`test_csv_schema_decoder_roundtrip_fuzz.py:99-116`). / **Fix:** delete. /
trivial / none / none.

**TEST-25 · low · zero-coverage live plumbing** — `telemetry/collector.py` (775),
`telemetry/models.py` (880), `cache/compression_feedback.py` (613): zero test
references yet invoked on the production retrieval path
(`compression_store.py:1159-1199`) — a bug there fires exactly when a user
retrieves dropped data. Also uncovered: `tag_protector.py` (Python side),
`error_detection.py`, `cache/backends/*`, `release_version.py`,
`headroom/pipeline.py`. / **Fix:** mostly mooted by Phase-3 deletion; if kept, one
fail-open test (a raising collector must not break `store.retrieve`) + smoke
round-trips. / small-medium / none / Phase-3 decision.

**TEST-26 · low · `verify/run.py:53,284-301`** — `DEV_CLAIMS` keys
`"multiturn@135"` but generated ids are `multiturn@90/900`, so the documented
−15.8pp multiturn shortfall is never auto-flagged (REPORT admits it; code
unfixed); the "compare the MEDIUM tier" comment doesn't match the code. /
**Fix:** `DEV_CLAIMS["multiturn@90"] = 0.708`; fix the comment. / trivial / none /
Phase 0.

### 3.7 Docs & comments (DOC)

**DOC-1 · high · `README.md:187-193`** — the corporate-SSL troubleshooting section
documents a `cdn.pyke.io` ONNX-Runtime download and `ORT_STRATEGY`/
`ORT_LIB_LOCATION` env vars for the Rust core — which is explicitly ML-free
(`crates/headroom-core/Cargo.toml:64-67`); the vars have zero consumers. The
audience most likely to follow instructions literally will allowlist a CDN and set
env vars that do nothing. / **Fix:** delete the bullet; keep the (real)
huggingface.co one. / trivial / none / none.

**DOC-2 · high · `CODEBASE-MAP.md:100`** — the CONTRACT-ENFORCEMENT row for hash
parity cites `tests/ccr_backends.rs:116` (`backend_swap_byte_equal_keys`) as "the
surviving cross-backend byte-equal-keys check" — the file and test exist
**nowhere** (found independently by three lanes). A maintainer changing hashing
would trust a phantom net. / **Fix:** repoint to the real pins
(`tests/test_ccr_hash_parity_vectors.py` + `crusher.rs::hash_canonical_pinned_
vectors`, `crusher.rs:2992-3025`); decide whether to resurrect a cross-backend
test (moot with one backend). / trivial / none / none.

**DOC-3 · medium · `CODEBASE-MAP.md` anchor drift + one behavioral lie** —
crusher.rs anchors drifted +145..+174 lines (map promises ±15): `crush_array`
695→840, `crush_array_lossy` 892→1037, `persist_dropped` 1147→1290,
`ccr_backed_keep_budget` 1554→1728, `hash_canonical` 1607→1781, formatter
`write_table` 258→288, `format_ccr_marker` 561→593. And `:99` claims CacheAligner
"tracks `_previous_prefix_hash` (cache_aligner.py:229)" — the aligner was made
stateless in round 1; the attribute exists only in archive/; the real mechanism is
the caller-threaded `previous_prefix_hash` kwarg (`cache_aligner.py:268-269,333`).
This is the map's prompt-cache-invariant row. / **Fix:** re-anchor (mechanical) +
rewrite `:99` — **after** all crusher.rs edits in this plan land (Phase 8). /
small / none / last.

**DOC-4 · medium · `DESIGN.md`** — presented as "how the engine drops data
**today** (the audited reality)" while its core claims are now false:
`enable_ccr_marker=false` ⇒ "no store + no marker = silent, unrecoverable" (`:21`
— fixed long ago; the pointer is unconditional), lossless-first routing (`:10-11`
— default is MinTokens), anchors two eras stale. A reader concludes the engine
still silently loses data — the exact opposite of the locked invariant. / **Fix:**
move to `docs/audits/` with a dated "historical Phase-2 design — superseded"
banner (15 min), or rewrite as current (1 day). / trivial / none / owner
preference, §5.

**DOC-5 · medium · `README.md:98-108`** — the "Proof" table is the stale
3-dataset capture (TEST-3): it under-reports the shipped engine by ~50pp on two of
three rows, and the documented repro command overwrites it with contradicting
numbers. / **Fix:** with Phase 0.4's re-baseline, update the table (keep the
deletion-vs-lossless footnote discipline; logs becomes a MinTokens LOSSY row). /
small / none / Phase 0.4.

**DOC-6 · medium · `llms.txt:3,19-37,27,30`** — the agent-facing doc contradicts
the honesty work done on README: "originals never deleted" (false — 1000-entry
FIFO / 300 s TTL, `CCR-RETENTION.md:3-8`); "60–95%" unscoped (README was scoped to
"redundant workloads" in round 4); "70–90%" without the tier caveat; and a
12-entry "doc index" whose entries link to nothing (docs/ contains only audits/). /
**Fix:** three wording edits + link or delete the phantom index entries. / small /
none / none.

**DOC-7 · medium · `SECURITY.md:5-8,41-42`** — the supported-versions table says
"0.2.x ✅ / 0.1.x ❌" for a project at 0.25.0, and "Budget Limits: set budget
limits…" names a feature that does not exist anywhere (proxy-era residue). /
**Fix:** "latest 0.x"; delete the bullet; verify the `security@`/`conduct@`
mailboxes exist (unverifiable from the repo). / trivial / none / none.

**DOC-8 · medium · `RUST_DEV.md:70-72,157,133,§Phase-3g`** — four stale claims in
the primary Rust onboarding doc: CI builds "macos-x86_64" (rust.yml has exactly
two targets and an explicit NOT-in-matrix comment, `:66-80`); the CCR store is
"capacity-**LRU**" (it is generation-counter **FIFO**, `in_memory.rs:12` — this
misdescribes a data-loss-window contract); a cited
`memory/project_lossless_first_pipeline.md` doesn't exist; the "Phase 3g (queued)"
sections describe traits that were built then **deleted**. / **Fix:** four edits +
fence historical sections. / small / none / none.

**DOC-9 · medium · `crusher.rs:14-34,450-452,507-510` + `:648-649`** — the module
header describes the dead everything-disabled stub world ("CCR: enabled=false;
result has ccr_hash=None", "no markers in this stage") — the **opposite** of the
unconditional-persist invariant this file owns; and the `:648-649` comment claims
the non-dict sentinel is gated by `enable_ccr_marker` (test `:3028` pins the
opposite; the flag gates nothing in core — ARCH-12). / **Fix:** rewrite the header
around lossless/lossy routing + unconditional persist; delete the three stub
claims and the false gate comment. / small / none / none.

**DOC-10 · medium · `smart_crusher.py` doc-rot batch** — `/v1/retrieve` cited 12×
(`:79,:511,:553,:610,:702,:716,:952,:981,:1012,:1049…`) — no such HTTP endpoint
exists; the production reader is MCP `headroom_retrieve`. `compress.py:386` cited
3× (the boundary is `:395`). `content_router.py:1043/:1118` cites drifted.
`tests/parity/fixtures/smart_crusher/` (17 fixtures) cited in the module docstring
— the directory doesn't exist. Same sweep should hit `compression_store.py:358,
382` and `router_ccr_mirror.py:67,116`. / **Fix:** one mechanical sweep;
prefer function-name anchors (the map's own convention). / small / none / none.

**DOC-11 · medium · telemetry doc-lies (survive rounds 3–5)** — `beacon.py:53`
renders the phantom `--no-telemetry` flag in the code-emitted notice (round-3 M6
fixed llms.txt but not the code string); `collector.py:748` cites the deleted
Supabase beacon; `telemetry/__init__.py:24-30`'s usage example raises `TypeError`
(kwargs don't exist — actual signature `collector.py:101-121`); `toin.py:56-58` +
`telemetry/__init__.py:50-51` claim "the Rust core loads that TOML at startup" —
no loader exists. / **Fix:** four edits; mooted where Phase 3 deletes. / trivial /
none / Phase-3 decision.

**DOC-12 · medium · dead-constraint parity docs (Rust transforms)** —
`diff_compressor.rs:17-18` + `transforms/mod.rs:5-9`: "the 20 fixtures in
`tests/parity/fixtures/diff_compressor/` are the spec" — the directory is gone,
and the "parity-bound, we MUST drop everything Python drops" principle constrains
nothing (the Python originals now *wrap this Rust code*). Several information
losses are preserved solely on the dead constraint (the `100644`/`Binary files`
normalizations, `diff_compressor.rs:1076-1084`). / **Fix:** rewrite both blocks
("Rust is canonical; recovery tests are the spec"); file the keep-or-lift decision
for the parity-only losses (§5). / small / none / precedes PERF-6.

**DOC-13 · medium · `content_detector.rs:19-24`** — module doc says "this detector
is the primary path"; reality is inverted: the PyO3 binding routes through
`detection::detect` (unidiff→PlainText), the Python-side fallback is Python's
*own* regex detector, and the 700-LOC Rust regex cascade has zero production
callers (its one live entry, `is_json_array_of_dicts`, has no Python caller
either — SIMP-9). / **Fix:** fix the doc + short-circuit `is_json_array_of_dicts`
to `try_detect_json`; deletion decision in §5. / small + decision / none / none.

**DOC-14 · low · assorted Rust doc/comment drift** — `ccr/mod.rs:48-50` (Redis
backend deleted); `relevance/hybrid.rs:18,33` (cites a `hybrid.py` that doesn't
exist); `signals/mod.rs:22-25` + `signals/README.md:43` (tree-sitter and the
excised bge embedder); `lib.rs:9` (wrong module path); `lib.rs:72,1047,1077,1103`
("pyo3 0.22" workaround comments — the workspace pins 0.24.2; re-verify the
workarounds); `build.rs:10-16,46-53` (glibc-shim rationale cites absent ort/ONNX —
re-run the `nm` symbol audit and rewrite or delete); workspace `Cargo.toml:34-42`
(cites a nonexistent REALIGNMENT doc); `deny.toml:1-2` (dead "Phase 0" language,
never-tightened allows); `builder.rs:27-31` ("no silent fallback" builder silently
defaults scorer+tokenizer — reword) + `constraints.rs:23-24` (names a nonexistent
`with_default_constraints`); `compactor.rs:73` (doc default 0.5 vs code 0.6);
`config.rs:72-74` ("no metadata keys" — stale vs `_ccr_dropped`/`_dup_count`);
`classifier.rs:55` (">64" vs `>= 64`); `formatter.rs:543-557` (doc comment stacked
on the wrong fn). / **Fix:** one doc-sweep batch. / small aggregate / none /
Phase 8.

**DOC-15 · low · `CCR-RETENTION.md:94-99`** — quotes the current miss message as
ending "…or configure a durable CCR backend (Sqlite/Redis)…"; the live message
(`compression_store.py:153-156`) ends "Recompute the source content." / **Fix:**
update the quote. / trivial / none / none.

**DOC-16 · low · `compress.py:295-297` + `:169-171`** — the sole owner of the
frozen-prefix invariant carries a comment "Mirrors Rust compute_frozen_count
(cache_control.rs:109)" citing a file its own docstring says was deleted. /
**Fix:** delete the ghost citation. / trivial / none / none.

**DOC-17 · low · misc Python doc drift** — `headroom/__init__.py:9` "BM25 /
embedding relevance scoring" (embeddings excised); `content_router.py:445`
`prefer_code_aware_for_code=False # let code pass through unmangled` is false
(False routes code to KOMPRESS, `router_policy.py:65-66`); `ContentRouterConfig`
docstring lists a phantom `skip_recent_messages` (`:433`);
`relevance/base.py:63-77` abstractmethod docstring claims a default impl that
exists only in the Rust twin; `search_compressor.py:126-131` +
`log_compressor.py:151-155` claim "preserved internal helpers" that don't exist;
`cross_message_dedup.py:44-48` (COR-41); CONTRIBUTING.md:16 broken table cell. /
**Fix:** batch edit. / small / none / Phase 8.

### 3.8 API & packaging (API)

**API-1 · medium · `headroom/exceptions.py:24-192` + `headroom/__init__.py:33-42`
+ `cache/base.py:67-79`** — the advertised error contract is fiction: none of the
**nine** exported exception classes is raised anywhere in the package; the package
docstring teaches `except ConfigurationError as e: print(e.details)` — a pattern
that can never fire; `exceptions.py:8` tells users to import a `HeadroomClient`
that no longer exists; `compress()` raises only `TypeError`. `CacheConfig`/
`CacheStrategy` are likewise exported with **zero** internal consumers, and
CacheConfig's docstring advertises excised spaCy/embedding tiers. Net: 11 of 39
`__all__` exports are decorative. / **Fix:** rewrite the docstring to the real
contract (`result.error` on fail-open; `TypeError` on bad kwargs); prune `__all__`
to `HeadroomError` + classes you commit to raising (raising `ConfigurationError`
from the unknown-kwarg branch is a candidate behavior change); delete
CacheConfig/CacheStrategy or re-home them honestly. / small-medium / removing
exports is API-breaking — do in a minor bump / owner call on the exception story.

**API-2 · medium · `headroom/hooks.py:41-52,67,131-138` + `compress.py:272-276,
290,372`** — `CompressContext` promises `user_query/turn_number/tool_calls/
provider`; `compress()` constructs it as `CompressContext(model=model)` only —
and the user query IS computed, **after** both hook invocations, so bias hooks
following the module's own examples get an empty query forever.
`CompressEvent.ccr_hashes` is never populated. `post_compress` is skipped on
zero savings, inflation-guard reverts, and fail-open — so the documented
A/B-testing and anomaly use-cases can't see the negative class. / **Fix:** hoist
`_extract_user_query` above the hooks and pass it; call `post_compress`
unconditionally on the success path + inflation return; populate `ccr_hashes`
from `markers_inserted` or delete the field; fix docstrings. / small / subclasses
assuming savings>0 now see zero-events — changelog note / none.

**API-3 · medium · `compress.py:113-115,223` vs `content_router.py:1704`** — the
top-3-most-read knob `protect_recent` is documented as "don't compress the last N
messages"; it actually gates **code only** (`protect_recent_code`). A user setting
it to protect recent tool outputs still sees them compressed. / **Fix:** honest
docstring (likely correct, given min_tokens + CCR reversibility) or extend the
guard to all types (bench-gated behavior change). / trivial (doc) / doc route
zero / owner call.

**API-4 · medium · `content_router.py:553-584` + `cache_aligner.py:333` +
`pipeline.py:201,286`** — the pipeline broadcasts the same `**kwargs` to every
transform, and CacheAligner's documented `previous_prefix_hash` kwarg is not in
`_APPLY_ALLOWED_KWARGS` → any caller using the documented turn-to-turn tracking
via the pipeline gets a `TypeError` from ContentRouter; `record_metrics` is a
stale allowlist entry (the pipeline pops it before broadcast). Structural
fragility: the allowlist must track every sibling's kwargs forever. / **Fix:**
add the entry + drop the stale one now; longer-term the pipeline owns the union
(transforms declare `accepted_kwargs`). / trivial now / none / none.

**API-5 · medium · `compression_store.py:1288-1318`** — the env-selected CCR
backend loader calls any entry-point factory with hardcoded Redis-shaped kwargs
(`url=HEADROOM_REDIS_URL, tenant_prefix=…`); any signature mismatch →
blanket-except → **silent downgrade to InMemoryBackend** for an operator who
explicitly requested durability; `HEADROOM_REDIS_URL` is residue naming. /
**Fix:** kwargs via `HEADROOM_CCR_BACKEND_OPTS` (JSON) or zero-arg factory; on
explicit-backend failure, raise instead of downgrading; rename the env var. /
small / raising changes startup for misconfigured deployments — that's the point /
none.

**API-6 · high · `pyproject.toml:50`** — `ast-grep-cli>=0.30.0` is a **core**
dependency justified by "(CodeCompressor)" — retired
(`router_dispatch.py:122-124`); the only in-package reference is
`headroom/tools.json:94-99`, which nothing reads and whose comment names a
nonexistent `headroom tools doctor` CLI. Every `pip install headroom-ai` pulls a
multi-MB binary wheel for a feature that no longer exists. Flagged in two prior
audits, never resolved. / **Fix:** delete the dep + the tools.json entry (or move
tools.json to archive/ — it ships in the wheel via `python-source="."`). Held
only by the EFF-2(a) decision (restoring the AST outliner would make it honest). /
trivial / low / §5 decision first.

**API-7 · medium · `headroom/ccr/mcp_server.py:11-16` + `pyproject.toml:64-67`** —
the server docstring instructs `headroom mcp serve` / `headroom mcp install`;
there is **no** `[project.scripts]` — no `headroom` CLI exists (the README's
`python -m headroom.ccr.mcp_server` is correct); and the `mcp` extra pins `httpx`
which nothing imports. / **Fix:** rewrite the docstring; drop httpx; optionally
add a real `headroom-mcp` script shim. / trivial / none / none.

**API-8 · medium · version machinery** — `headroom/release_version.py` (310 LOC of
CI release tooling) ships inside the user wheel and `_version.py:47-61` executes
it (git subprocesses) on import in checkouts (PERF-13); two version systems
coexist (release-please manifest 0.25.0 + the git-computed runtime version —
the skew itself is documented by-design). / **Fix:** move release_version.py to
`scripts/` (release.yml adjusts one path); `_version.py` falls back to
`importlib.metadata` with a lazy `__getattr__`. / small-medium / release.yml path
+ any tests importing it / none.

**API-9 · medium · repo weight** — 26.7 MB of tracked media; 21.6 MB referenced
nowhere (`headroom_learn.gif` 15 MB, `Headroom-2.gif` 5.4 MB,
`headroom-savings.png` 1.2 MB); pack ≈ 27 MiB, i.e. media ≈ 99% of clone weight;
`HeadroomDemo-Fast.gif` (4.5 MB) is the one README uses. / **Fix:** `git rm` the
three; host the demo gif as a release asset / user-images URL; history rewrite
only if ever re-published. / trivial / README image must keep rendering on
GitHub+PyPI (relative paths already break on PyPI) / none.

**API-10 · medium · `pyproject.toml:8`** — PyPI `description` still says "Cut
costs by 50-90%" — unscoped, different range from the deliberately-scoped README
headline; it is the single most-seen claim. / **Fix:** "…60-95% fewer tokens on
redundant workloads, reversible via CCR". / trivial / none / none.

**API-11 · medium · `NOTICE:17-43`** — attributes Pydantic, sentence-transformers,
FastAPI (none is a dependency; zero imports) and omits shipped third-party code
(the extras' transformers/onnxruntime/trafilatura and every Rust crate statically
compiled into `_core.so`). NOTICE ships in the sdist. / **Fix:** regenerate (keep
tiktoken+NumPy; add extras + a `cargo license` section). / small / none / after
API-6/SIMP-7 settle the dep set.

**API-12 · low · `headroom/transforms/__init__.py:80,84-92,131,139-143`** —
optional-HTML names raise `ImportError` from `__getattr__` instead of
`AttributeError` when trafilatura is absent; the private-named
`_HTML_EXTRACTOR_AVAILABLE` is exported in `__all__`; `CompressionStrategy`
lazy-binds to the 2,363-line content_router instead of the 115-line
`router_policy` that owns it (touching the enum imports the whole router + Rust
chain). / **Fix:** repoint the enum; catch ImportError → AttributeError with an
install hint; rename or unexport the flag. / trivial / import-order only / none.

**API-13 · low · session scaffolding in the public tree** — `PLAN.md` (live PM
log with user mandates and quotes), stale `DESIGN.md` (DOC-4), `docs/audits/*`
sit at/near the root of a public repo; PLAN.md:126 itself classifies them as
session-scaffolding-not-under-review. archive/ (2.8 MB incl. a full shadow
package) is defensible and does not enter the sdist — verify once with
`maturin sdist && tar -tf` given the unusual `python-source="."`. / **Fix:** move
PLAN.md → `.claude/runtime/`; DESIGN.md → docs/audits/ + banner; one-time sdist
audit. / small / the critique-workflow ORIENT excludes reference these paths —
update them / owner call, §5.

### 3.9 Simplicity, dead code & over-engineering (SIMP)

**SIMP-1 · high · `headroom/telemetry/collector.py` (775) + `beacon.py` (54) +
collector-only halves of `models.py` (~470)** — delete (evidence in ARCH-3; keep
`is_telemetry_enabled`, ~15 LOC). Internal defects recorded for completeness if
kept: non-atomic save under lock (`collector.py:440`), unbounded
`_retrieval_stats` (`:225-244`), the double-checked-locking pattern toin.py
explicitly avoids (`:744-746`), a 10k-event ring never read (`:185-187`). /
−1,300 LOC; 3-line edit at `compression_store.py:1199-1215`. / small / near-zero /
Phase-3 decision (a).

**SIMP-2 · high · `headroom/cache/compression_feedback.py` (613)** — delete (the
write-only, inverted-signal loop; evidence in ARCH-3 / live probe) + the
`feedback.record_retrieval` call and `use_feedback_hints`/doc claims
(`config.py:285-290`). Keep `RetrievalEvent` if tests use it. / small / low /
Phase-3 decision (b).

**SIMP-3 · high · `headroom/telemetry/toin.py` (1,606) + `models.py` remainder** —
delete (−1,600 LOC, 4 call sites, 4 test files, `paths.toin_path`) **or** shrink
to a ~200-LOC flat recorder. If kept, the internal fix list: SEC-2, SEC-3,
PERF-9/10, plus: unbounded pattern store with keys designed never to aggregate
(content-prefix sha in `_create_content_signature`, `content_router.py:310-318`;
`uuid4` for empty items, `models.py:219-230`) → global LRU cap + stable keys;
the inert `(auth_mode, model_family)` tuple-key machinery (always
`("unknown","unknown",hash)`, `toin.py:106-149,190-197`) and
`DEFAULT_MIN_OBSERVATIONS_TO_PUBLISH` exported for a removed CLI
(`telemetry/__init__.py:72-74`); ~150 LOC of user-count federation that can only
ever count 1 (`toin.py:264-277,639-657,1391-1423`); the plugin
architecture-for-one-backend (Protocol + entry-point loader + 3 env vars,
`toin.py:1524-1561`); the deprecated `get_recommendation` stub + warn-dedup
(`:427-432,956-987`); `total_*` fields that are truncating rolling averages
(`models.py:543-547`); multi-process last-writer-wins (docstring caveat). /
medium-large / behavior-neutral / Phase-3 decision (a).

**SIMP-4 · medium · `headroom/ccr/tool_injection.py:178-459` +
`ccr/__init__.py:7`** — the injection plane (`CCRToolInjector`,
`create_ccr_tool_definition`, `create_system_instructions`, `parse_tool_call`,
`session_has_done_ccr`) has zero production callers post proxy-removal (~340
LOC); docstrings cite archived infrastructure; the class usage example calls
bool **fields** as methods (`injector.inject_tool(tools)` → `TypeError`);
`ccr/__init__.py:7` claims a hook that doesn't exist. / **Fix:** excise (keep
`CCR_TOOL_NAME`, `is_valid_ccr_hash`, the marker patterns; repoint tests at
marker_grammar) — unless the upcoming MCP tool work will consume it, in which
case fix the docs instead. / medium / low (no callers) / Phase-3 decision (c).

**SIMP-5 · medium · Rust dead surface** — (a) the **entire HF tokenizer path**:
`register_hf`/`try_register_hf`/`HfTokenizer` have zero callers outside their own
tests and are not FFI-exported — nothing can populate the registry — while
`tokenizers = "0.22"` (vendored onig_sys/esaxx C/C++) and `hf-hub`
(+ureq+rustls+ring) exist solely for it: build time, supply-chain surface, wheel
bytes in a project that documents PyPI's 10 GB ceiling
(`tokenizer/registry.rs:113,146`, `hf_impl.rs`; also `hf_impl.rs:151-158` returns
0 tokens on encode error, violating the trait convention — moot on deletion);
(b) `signals/tiered.rs` — zero production constructions (the ML tier it composes
was excised); (c) three dead `#[pyfunction]`s: `parse_search_lines` (constructs a
full compressor per call), `detect_log_format`, `is_json_array_of_dicts`
(`lib.rs:1301,1483,1018`, registrations `:1561,1569,1575`) — zero Python callers
incl. tests. / **Fix:** delete (a) + the two deps, (b) + re-export, (c) + regs;
re-grep for dynamic getattr first. / small-medium / low / Phase 3.

**SIMP-6 · medium · `content_detector.rs` (~700 LOC)** — a Rust mirror of a
Python module that is itself the live fallback (DOC-13). / **Fix:** decision (§5):
delete down to `ContentType` + `try_detect_json`, or keep as a documented
comparison oracle with an honest header. / medium / check no external `_core`
consumer expects regex semantics / Phase-3 decision (d).

**SIMP-7 · medium · dead config knobs (wire-contract)** — `config.rs:77-104`: six
knobs read by zero core paths (`enabled`, `uniqueness_threshold`,
`similarity_threshold`, `toin_confidence_threshold`, `use_feedback_hints`,
`include_summaries`); `min_tokens_to_crush` is consulted only by `crush_object`
(`crushers.rs:397`) — arrays ignore it, its doc over-promises. Note
`lib.rs:539` force-enables `crush_unique_entities_when_recoverable` without
constructor exposure (comment-guarded divergence from the Python dataclass). /
**Fix:** delete the dead knobs Rust+FFI+Python-dataclass in one commit with a
bridge deprecation shim; reword min_tokens_to_crush; expose or document the
forced flag. / medium / API break for kwargs users — deprecate at bridge /
Phase 3, wire-contract rule.

**SIMP-8 · low · trait-surface prose** — `traits.rs`/`observer.rs`/
`constraints.rs`: ~460 LOC of extension plumbing serving 2 one-line Constraint
impls + 1 tracing Observer; the docs sell SOC2/HIPAA AuditObserver and
loop-trained scorers that exist nowhere. The seams are cheap and defensible —
keep the traits, trim the hypothetical-customer prose to one line each. / trivial
/ none / none.

**SIMP-9 · low · mechanical dead-code sweep** — `diff_compressor.rs:685` dead
immutable `parse_warnings` with two doc comments promising it fires
(`:595-599,202-204` — wire or delete both); `diff_compressor.rs:888-890`
unreachable empty-check, `:941` `let _ = n;`; `log_compressor.rs:786`
`let _ = ();`; `orchestration.rs:356-358` identity `singleton_pin_cap`;
`analyzer.rs:183-187` unreachable guard; `keyword_detector.rs:263-269`
find→`any()`; `planning.rs` dead `keep_existing_only` (COR-35);
`content_router.py:1606/1703` duplicate `messages_from_end`;
`_process_content_blocks` defaults duplicating config defaults
(`content_router.py:2090-2094` — make required); `content_router.py:1855`
hardcoded "(<50 words)" label while the floor is 250; `tokenizer.py:45-48` dead
`available` property; `pipeline.py:42-48,71,81-83` proxy-era PipelineEvent fields
never set + dead `enabled`; `compression_store.py:541` `get_metadata` zero
callers; `parser.py:19` BASE64_PATTERN false-positives on 50+-char alnum runs +
`:351-352` never-set WasteSignals fields; headroom-core `serde` direct dep unused
(transitive suffices); `.gitignore` dead negations; `pyproject.toml:183-185` mlx
mypy override. / **Fix:** one sweep batch. / small aggregate / none / Phase 3/8.

**SIMP-10 · low · `kompress_compressor.py` internal duplication (the 1,384-LOC
verdict: mostly earning its keep)** — removable ~200–250 LOC: the chunk→score→
reduce→CCR logic duplicated between `compress()` (`:830-964`) and
`compress_batch` (`:1103-1235`) (extract a shared per-text helper, or delegate
single→batch once COR-11/the borderline divergence at `:818-828` vs `:1029-1037`
is resolved — on GPU the documented PyTorch borderline behavior is currently
unreachable and CPU/GPU results differ for identical config);
`_default_max_concurrent` (`:178-187`) — three branches that all return 1 feeding
a keyed semaphore registry (`:194-202`). / **Fix:** after COR-11; characterize
first. / medium / behavior-neutral with characterization tests / COR-11 first.

**SIMP-11 · low · `tokenizers/registry.py:88-118`** — a singleton-of-classmethods
with mixed class/instance state and no lock; module-level dicts + functions
express the same thing with ~60 fewer lines (public `TokenizerRegistry.get/
register` preserved). Also stale `# type: ignore[arg-type]` at
`pipeline.py:141-144` and `cache_aligner.py:386` from before the Protocol unify —
try removing. / small / low / none.

### 3.10 Compression efficacy (EFF) — where compression is left on the table

*Architecture verdict first (the mandated question): lossy-by-deletion + CCR is
the **right** architecture for structured/redundant content, and the in-repo
evidence is decisive — byte-exact recovery held under two adversarial
out-of-sample harnesses and an independent strict recheck; granular per-row
chunks turned retrieval economics from −7.5% to +62–69% effective savings at 25%
retrieval (BENCHMARKS.md:89-101); semantic dedup was tried and measured a
structural no-op (dup-heavy data routes lossless; residual lossy cases are
all-distinct — BENCHMARKS.md:424-429); summarization is structurally incompatible
with the byte-exact + hash-parity invariants. The honest limits: genuine-entropy
lossless sits at 0–54%, and "reversible" means a 1000-entry/300 s window — the
durable/spill backend (CCR-RETENTION.md:107-126) should ship before "reversible"
is marketed harder.*

**EFF-1 · high · Bash exclusion (= COR-10)** — if the frozenset entry is the bug,
this is the single largest default-path savings unlock in the tree: build/test
output for coding agents. Decide + bench.

**EFF-2 · high · code content has no strategy — 0% on 70% of bench-corpus tokens**
(`BASELINE.md:26`; constant across phases). Three compounding causes:
the bench wraps files as a JSON array (routes to SmartCrusher, whose opaque gate
deliberately refuses file contents); CODE_AWARE is a stub-to-Kompress
(`router_dispatch.py:122-134`); Kompress needs [ml] + a 261 MB model. The only
measured code win is 66% on byte-identical re-reads (verify/REPORT.md:58). /
**Proposals:** (a) restore the AST-outline compressor from
`archive/headroom/interceptors/astgrep.py` as a CCR-backed strategy — outline
visible, full source under `<<ccr:HASH>>`; information-complete, and the binary
dep already ships (API-6). 1-2 weeks incl. recovery-invariant + needle tests;
medium risk (byte-exact CCR + language edges). (b) extend cross-message dedup to
line-level near-dups so a re-read of an edited file ships only changed lines +
pointer (the counterfactual-gate lesson from BENCHMARKS.md:263-271 applies).
(c) cheapest: a raw-source-string dataset so "code" in the bench actually routes
as code. / §5 decision.

**EFF-3 · high · small arrays never offload** — disk@9 lands 40-43% vs 91-95% at
size 90, explicitly "no offload at size 9" (BENCHMARKS.md:46-47,63-65): arrays ≤
adaptive_k take the lossless-only tier (`crusher.rs:864-884`) and never produce a
lossy-recoverable candidate — despite MinTokens being able to arbitrate and every
drop being CCR-backed; the keep-budget floor is already 5 (`crusher.rs:1728`).
Small arrays are the most common real tool-output size, and multiturn realistic
entropy (28-39%) shares the root cause per-message (BENCHMARKS.md:48,66-69). /
**Fix:** let small arrays emit a lossy candidate (respect query-pin/critical-row
guarantees); MinTokens picks. / medium / tier-1 boundary is a documented contract
(CODEBASE-MAP:27) — full needle + recovery re-verification / after Phase 1.

**EFF-4 · medium · the lossless ratio gate strands proven savings** — Phase 3
measured a logs lossless render at 26.97% savings, round-trip-proven, discarded
under the 0.30 gate (`BENCHMARKS.md:479-481`; `config.rs:205`); the 256-byte
absolute floor already guards noise (`crusher.rs:1661`). / **Fix:** experiment:
`lossless_min_savings_ratio` 0.30 → ~0.15 for the small-array path; one constant
+ bench re-run. / small / low / Phase 6.

**EFF-5 · medium · Kompress is unmeasured** — zero benchmark or verify references;
the only quality numbers are the model's own eval-split stats in a code comment
(keep_rate 0.8097 ≈ 19% word reduction, `kompress_compressor.py:46-51`) — an
order of magnitude below the structured paths, never compared to heuristics.
Costs are real and in code: 261 MB download, [ml] dep set, a dedicated ≥1000 ms
slow-path log (`:910-919`), CPU batching measured at 0.7–0.9× (`:988-989`),
word-deletion unsafe for code. / **Fix:** add a `kompress` family to
`verify/run.py` (prose/markdown/code, [ml] installed) measuring tokens, latency,
and CCR round-trip vs a passthrough control — **before** continuing to market it
as one of two core engines; demote to experimental if it can't beat
passthrough+CCR net of latency. / small-medium / none / §5.

**EFF-6 · medium · no benchmark exercises Search/Log/Diff/HTML/Kompress at all** —
`search@90`/`logs@90` are *parsed JSON arrays* routed to SmartCrusher
(`datasets.py:263-312,217-252`); README markets five compressors with zero
in-repo benchmark evidence. With a plain `pip install` (no extras), prose,
markdown (no such ContentType — it's PLAIN_TEXT), code, and HTML all pass
through; README:32 says Headroom "compresses everything your AI agent reads". /
**Fix:** raw-text datasets (real CI log text → LogCompressor; raw `rg` output →
SearchCompressor; a real diff; an HTML page; a markdown README) — ~30 lines each
in datasets.py; plus a default-install coverage matrix in the README. / small /
none / Phase 6/8.

**EFF-7 · medium · retrieval-plane polish** — needle recall is measured only with
queries that *name* the needle (TEST-16); logs' visible-only recall is 44.4%
(BASELINE) — fine given CCR, but the retrieval cost model deserves the non-naming
control before "100% recall" is quoted. / with TEST-16.

**EFF-8 · low · exact-size loss in opaque markers** — `humanize_bytes`
(markers.rs:78-89) is the only lossy step between typed IR and wire text
(`4.5KB` vs exact size); §4.2's typed refs carry `byte_size: usize` exactly, so
retrieval UIs can show precise costs. / free with §4.2.

**EFF-9 · low · mixed-array dict subgroups ship uncompressed** (= COR-28b) — the
discarded inner lossless win is a real compression gap on "tabular dicts inside a
mixed array". / with COR-28.

**EFF-10 · low · the proof surface under-sells the engine by ~50pp** (= TEST-3 /
DOC-5) — zero-engine-work win: re-baseline and update the README table. /
Phase 0.4.

---

## 4. The two mandated large refactors — full step sequences

### 4.1 Refactor (a): ContentRouter decomposition

**Current anatomy** (from a full read of `content_router.py`, 2,363 LOC; line
anchors verified at HEAD):

*Module level (~590 LOC):* `RouterRuntime` (93-134) · the `CacheDisposition` ADT
(137-170) · debug helpers `_router_debug_dumps/_log_router_debug/_json_shape/
_mixed_indicators/_section_debug` (173-223) · `_detect_content` Rust-primary/
regex-backstop (226-279) · `_create_content_signature` (282-328) ·
`RoutingDecision`/`RouterCompressionResult` (331-417) · `ContentRouterConfig`
(420-533) · `_APPLY_ALLOWED_KWARGS` (553-584).

*Class methods, by cluster:*

| Cluster | Methods (lines · ≈LOC) |
|---|---|
| **CONTENT ENGINE** (compress one string) | `compress` 777-931 (155) · `_determine_strategy` 953-968 · `_compress_mixed` 977-1053 (77) · `_compress_pure` 1055-1096 (42) · `_apply_strategy_to_content` 1098-1168 (71, delegator binding closures) · `_try_kompress` 1170-1242 (73) · `_observe` 933-951 · `_timed_compress` 758-775 · `_get_kompress` 1322-1360 (39, per-request model_id) · `_record_to_toin` 686-756 (71) |
| **MESSAGE WALKER** | `apply` 1403-1909 (**507**: kwargs gate 1429-1433 · lifecycle pre-pass 1435-1453 · option resolution 1455-1493 · tool map/exclusions 1499-1510 · adaptive params 1512-1546 · Pass-1 classify loop 1594-1762 · Pass-2 parallel 1764-1806 · Pass-3 merge 1808-1837 · summary log 1846-1885 · observer 1892-1898) |
| **BLOCK WALKER** | `_process_content_blocks` 2080-2300 (221) · `_compress_content_block` 1998-2078 (81) |
| **CACHE GATE** | `_lookup_cached_disposition` 1932-1996 (65 — already the exemplary single seam) + the **duplicated store-half** at apply:1818-1837 and block:2062-2077 |
| **MESSAGE POLICY** | `_build_tool_name_map` 1364-1394 · `_get_tool_bias` 1911-1930 · `_detect_analysis_intent` 2302-2351 · `should_apply` 2353-2363 |
| **Delegator shims** (~90 LOC, monkeypatch back-compat) | `_strategy_from_detection(_type)` · `_content_type_from_strategy` · `_adaptive_min_ratio` · 5 `_get_*` registry getters · `_ensure_ccr_backed` · `_extract_ccr_hashes` |

State held: `config`, `_observer`, `_registry`, `_dispatcher`, `_ccr_mirror`,
`_kompress`, `_toin`, `_cache` — shared across all concurrent requests via the
`compress.py:75` singleton pipeline.

**Target end-state (5 modules + a ~450-LOC facade):**

- `router_debug.py` — the five debug helpers (pure functions; imported back into
  `content_router` as module globals so existing `monkeypatch.setattr(
  content_router_module, …)` targets keep biting).
- `router_engine.py` — `ContentCompressionEngine`: owns `_registry`,
  `_dispatcher`, kompress lifecycle, TOIN recorder; API
  `compress(content, context, question, bias, runtime) -> RouterCompressionResult`.
  Zero message/dict knowledge; stateless per call. Absorbs `compress`,
  `_determine_strategy`, `_compress_mixed`, `_compress_pure`,
  `_apply_strategy_to_content`, `_try_kompress`, `_observe`, `_timed_compress`,
  `_get_kompress`, `_record_to_toin`.
- `router_message_policy.py` — a pure classification layer: a
  `MessageDisposition` ADT (`Frozen | ProtectedMsg(reason) | Small | NonString |
  ContentBlocks | AlreadyCompressed | Compressible(bias, content_key)`) and
  `classify_message(...) -> MessageDisposition` extracted from the Pass-1 gate
  chain (1594-1762, minus the cache lookup); plus `_build_tool_name_map`,
  `_get_tool_bias`, `_detect_analysis_intent` as pure functions. Every
  route-counter bump becomes a single disposition→counter mapping.
- `router_blocks.py` — `ContentBlockWalker`: `_process_content_blocks` +
  `_compress_content_block`, with `lookup_disposition`, `store_disposition` and
  `compress_fn` injected per call (the same per-call-resolution idiom
  StrategyDispatcher already uses, so monkeypatching router methods keeps
  working).
- **Cache gate completed in place** — `_lookup_cached_disposition` stays on the
  facade (it needs the SmartCrusher getter for CCR re-mirror); its missing twin
  `_store_disposition(content_key, result, min_ratio, …)` is extracted from the
  two duplicated put/mark_skip blocks.
- `content_router.py` (facade, ~450 LOC) — config, `_APPLY_ALLOWED_KWARGS`,
  `RouterRuntime`, the ADTs, `__init__` wiring, `apply()` orchestration
  (classify → dispatch on disposition → Pass-2/3 executor → summary), the cache
  gate, and thin delegators for every public/monkeypatched name.

**Step sequence (each step is a separate commit; gate per step = full pytest +
`gate.sh` G1–G5 + the router pin suites `test_content_router_cache_lookup_paths` /
`test_result_cache_ccr_divergence` / strategy-chain / worker-options /
apply-kwargs; behavior must be byte-identical — any bench diff fails the step):**

- **S0 — characterization top-up (test-only).** Pins that don't exist yet: the
  routing summary log line shape; the empty-output guard's routing_log rewrite;
  the mixed path end-to-end; `force_kompress` through apply(); a frozen +
  content-blocks + excluded-tool matrix asserting `route_counts` whole-dict
  equality (the existing suites cover the cache lookups). Also fix TEST-21's
  exhaustible clock now (it will break under any refactor).
- **S1 — `router_debug.py`** (pure move + re-import as module globals). Lowest
  risk; proves the re-export/monkeypatch pattern once more.
- **S2 — cache-gate completion (in place).** Extract `_store_disposition` from
  apply:1818-1837 + block:2062-2077 (delete both copies); land COR-18's
  option-aware key + length guard here if Phase 6 hasn't already (one seam, one
  review). `_lookup_cached_disposition` untouched.
- **S3 — `router_message_policy.py`.** Introduce `MessageDisposition`; rewrite
  Pass-1 as `match classify_message(...)`. The gate chain moves verbatim —
  ordering of protections is behavior (excluded-tool window before user-skip
  before size before error before detection-based) and must be preserved
  exactly; the S0 matrix pins it. Counters map in one place (fold TYPE-4's
  `Counter` here).
- **S4 — `router_blocks.py`.** Move the block walker; `_process_content_blocks`
  defaults become required kwargs (SIMP-9's drift item). Facade keeps
  one-line delegators.
- **S5 — `router_engine.py`.** Move the content engine; `ContentRouter.compress`
  becomes a delegator (public API unchanged). This is the step that unlocks
  PERF-2(c) (pass a precomputed detection into the engine) and COR-17 (thread a
  real tokenizer) — both as **follow-up** commits, not part of the move.
- **S6 — Pass-2/3 executor extraction.** `_compress_pending(pending, runtime,
  …)` on the facade (or `router_engine`): the ThreadPoolExecutor block
  1764-1837 verbatim, env-var parse hoisted to one place.
- **S7 — facade cleanup + docs.** Delete now-dead locals, update the module
  docstring (it still lists KompressCompressor's retired framing), re-anchor
  CODEBASE-MAP's router rows (DOC-3 does the rest later).

**Invariant guards throughout:** the tests monkeypatch
`content_router_module.is_mixed_content` / `split_into_sections` / `time` — every
moved symbol must remain rebindable as a `content_router` module global;
`_ensure_ccr_backed` stays reachable via the facade (the CCR-backing guard's
callers are pinned); no step changes `transforms_applied` string formats
(`router:{strategy}:{ratio}` flat vs `router:{label}:{strategy}` threaded — the
documented divergence stays in the callers).

**Sizing:** S0 ~½ day; S1-S2 ~½ day; S3 ~1.5 days (the risky one); S4 ~1 day;
S5 ~1.5 days; S6-S7 ~1 day. ≈ 6 working days with gates.

### 4.2 Refactor (b): typed CCR dropped-refs across the FFI (finish the two-store mirror)

**Current state (verified firsthand + three lanes):**

- *Typed today:* `CrushResult.ccr_hashes` (bare row-drop hashes) +
  `row_index_markers` — but the latter carries **full rendered marker text** that
  Python re-parses with the grammar walker (`smart_crusher.py:473-489`), and the
  hash↔index pairing is destroyed by the flatten (`crusher.rs:412-419` from the
  private `DroppedRef`, `crusher.rs:187-195`; "may be shorter … never longer",
  `types.rs:219-222`).
- *Scrape-only:* opaque refs everywhere; and on the live `SmartCrusher.apply()`
  path (`smart_crush_content`, a bare `(str, bool, str)` tuple) **even row-drop
  recovery is scrape-only** (`smart_crusher.py:608-616`).
- *Python scrape sites to retire (6):* `smart_crusher.py:460-465`
  (crush→opaque-only walker), `:473-489` (`_row_index_keys` re-parsing typed
  markers), `:522-529` (crush_array_json items — which also double-mirrors the
  typed hash), `:530-537` (compacted), `:551-561` (compact_document_json — 100%
  scrape), `:608-616` (`_smart_crush_content` — 100% scrape, live path).
  (`router_ccr_mirror.extract_ccr_hashes` is a *different plane* — it re-parses
  cached prompt text, not fresh FFI output — and stays.)
- *Rust emission sites (all already have `{hash, kind, exact byte_size}` in
  scope):* the compaction IR is **already typed** — `CellValue::OpaqueRef` /
  `Compaction::OpaqueRef` (`formatter.rs:152-161,192-201,275-280,585-595,
  712-717,769-773`) flattened only at render via `marker_for_opaque`
  (`markers.rs:53`); the document walker computes the hash inline and discards it
  (`walker.rs:171-188` returns only the marker String); the crusher's string case
  likewise (`crusher.rs:807-815`). `CompactionStage::run` already returns
  `(Compaction, String)` (`compaction/mod.rs:120-124`) — the IR reaches the
  crusher.

**Design principle:** the wire **bytes never change** — hashes are computed at
the same sites, markers render identically; the refactor only *additionally
carries* what is already computed. Hash parity and recovery bytes are therefore
structurally safe; every step is additive until the final deletion.

**Step sequence (each step a commit; Rust steps: `maturin develop` before pytest;
R3+R4 are the wire-contract lockstep and land together):**

- **R1 — Rust: promote the typed carrier.** In `types.rs`:
  ```rust
  pub enum DroppedRef {
      RowDrop { hash: String, row_index_key: Option<String> },  // bare "HASH#rows"
      Opaque  { hash: String, kind: String, byte_size: usize },
  }
  ```
  Replace the private struct (`crusher.rs:187-195`); `CrushResult` gains
  `dropped: Vec<DroppedRef>`; `ccr_hashes()`/`row_index_markers()` become derived
  getters (back-compat, byte-identical output). Unit tests: derived getters equal
  the old fields on the existing corpus. *(This is also the pre-step ARCH-4's
  split wants.)*
- **R2 — Rust: collect opaque refs.**
  (i) `fn collect_opaque_refs(c: &Compaction, sink: &mut Vec<DroppedRef>)` —
  a pure IR walk (Table cells, `Compaction::OpaqueRef`, Buckets, Nested) run on
  `CompactionStage::run`'s existing return value;
  (ii) `emit_opaque_ccr_marker` returns `(String, DroppedRef)`; thread a
  `&mut Vec<DroppedRef>` sink through `walk/walk_string/walk_array`
  (`DocumentCompactor` grows a collecting variant) and through
  `process_string_collecting`. Property test: for every fixture, the collected
  set == the scraped set of the rendered text (this is the adversarial proof the
  scrape can then be retired against). Include fixtures whose **payload
  contains literal `<<ccr:…>>` text** — the false-positive class the scrape has
  and the typed path doesn't.
- **R3 + R4 (one commit) — FFI carries the refs.**
  `PyCrushResult` gains `dropped_refs -> list[tuple[str, str, str, int]]`
  (`(kind_tag, hash, opaque_kind_or_index_key, byte_size)`) or a small pyclass;
  `crush_array_json`'s dict gains `"dropped_refs"` + `"row_index_key"` (bare
  key, not marker text); new `compact_document_json_typed(doc) -> (str, list)`
  (old method delegates, deprecated); new `smart_crush_content_typed(...) ->
  (crushed, was_modified, info, dropped_refs)` (old 3-tuple delegates,
  deprecated). Extend `tests/test_crush_typed_hash_parity.py` — and fix its
  self-comparison tautology (TEST-11) so the typed-vs-scraped **payload**
  equality is actually asserted.
- **R5 — Python: consume typed, keep the scrape as a one-release safety net.**
  All six mirror sites switch to typed refs; `_row_index_keys` deleted (bare keys
  arrive); `_smart_crush_content` moves to the typed sibling (its 16 tuple-shape
  consumers keep the 3-tuple via the wrapper). For one release, mirror the
  **union** (typed ∪ scraped) and `logger.error` + a counter on any scrape-only
  hash — it must never fire; a firing is a typed-path bug caught before it
  becomes silent loss. COR-5's typed-miss `CcrMirrorError` escalation lands here
  if Phase 1 hasn't already.
- **R6 — delete the scrape.** Remove `_mirror_opaque_ccr_markers_in_text`,
  `_collect_opaque_ccr_hashes{,_from_string}`, `_mirror_ccr_markers_in_text`'s
  tree-walk, the union net, and the deprecated FFI shims. `marker_grammar`
  consumers (tool_injection/recovery walkers/router_ccr_mirror) are untouched —
  they parse *prompt* text, a different plane. Gate: the full recovery matrix
  (`test_ccr_recovery_invariant` all 23+, proportional retrieval, parity
  vectors, marker-grammar characterization) + one full `verify/run.py` cold
  sweep + bench floor.

**Interactions:** COR-4 (persist only dropped rows) changes what `row_index_key`
counts — land Phase 1 first so R1's semantics are final. COR-13's decision
(Table-only lossless gate) slightly changes which renders carry opaque refs —
decide before R2's property test is written. ARCH-5 (shared persist helper) is a
natural R1 companion on the diff/log/search side but is not required.

**Sizing:** R1 ~1 day; R2 ~2 days (walker threading + property tests); R3/R4
~1.5 days; R5 ~1.5 days; R6 + full verification ~1 day. ≈ 7 working days.

---

## 5. Open questions (owner decisions the plan cannot make)

1. **Telemetry/TOIN & feedback (ARCH-3, SIMP-1/2/3):** delete outright, or shrink
   TOIN to a minimal recorder? Deletion matches the repo's excision precedent and
   kills SEC-2/3 + PERF-9/10 for free; keep only if the learning loop's consumer
   is genuinely coming back. (If kept, SEC-2/SEC-3 are mandatory immediately.)
2. **Bash in DEFAULT_EXCLUDE_TOOLS (COR-10/EFF-1):** was the exclusion
   intentional (comment is the lie) or accidental (frozenset is the bug)? The
   answer decides the single biggest default-savings lever.
3. **Code strategy (EFF-2):** restore the AST-outline compressor (makes API-6's
   dep honest), invest in line-level near-dup, or accept 0% on code and delete
   the ast-grep dep + honest-README the coverage matrix?
4. **Kompress's standing (EFF-5):** measure first (add the verify family), then
   keep-as-core vs demote-to-experimental. Also whether the GPU/CPU borderline
   divergence (SIMP-10/COR-11 cluster) is worth unifying or documenting.
5. **Dotted-flatten contract (COR-14):** wire-format change (mark + un-flatten)
   or documented value-exact-under-dotted-keys?
6. **Rust content_detector mirror (SIMP-6/DOC-13):** delete ~700 LOC or keep as a
   documented comparison oracle?
7. **Parity-only information losses in diff (DOC-12):** with the Python original
   retired, keep or lift the `100644`/`Binary files` normalizations?
8. **DESIGN.md / PLAN.md / audits placement (DOC-4, API-13):** archive with
   banners, or keep at root?
9. **`security@headroom.dev` / `conduct@headroom.dev` (DOC-7):** do these
   mailboxes exist? Unverifiable from the repo.
10. **Durable CCR spill (CCR-RETENTION.md options):** the efficacy verdict
    (EFF preamble) recommends shipping it before "reversible" is marketed
    harder — which of the five ranked options, and when?
11. **Exception contract (API-1):** commit to raising 2-3 typed exceptions
    (behavior change) or document the fail-open-only reality?
12. **`compress_unique_entities_when_recoverable` force-enable
    (`lib.rs:539`, SIMP-7):** expose on the Python surface or keep the
    comment-guarded divergence?

## 6. Method & coverage appendix

**Coverage:** 10 audit lanes, every lane reading its slice in full: Python
orchestration (content_router + 6 seams + pipeline/aligner/dedup/lifecycle/
detection) · Python compressor wrappers + decoders (incl. building the extension
and reproducing the decoder bugs) · Python public API + CCR plane + stores (with
live probes of eviction/redaction/feedback accounting) · telemetry/tokenizers/
relevance · Rust SmartCrusher core (21 files) · Rust compaction + transforms ·
Rust infra + FFI (workspace/benches/clippy clean-checked) · test suite (66 files,
751 tests, all assertions read) · verify/benchmarks harnesses (claims re-executed)
· docs/packaging/efficacy (every factual claim grepped against code). Findings
were cross-deduplicated; three independent lanes converged on the same phantom
map citation and two on each empirically-confirmed decoder bug, which is the
main confidence signal for the sweep's completeness.

**Counts by theme × severity (156 IDs; several bundle multiple sub-findings):**

| Theme | crit | high | med | low | total |
|---|---|---|---|---|---|
| Correctness (COR) | 3 | 6 | 17 | 15 | 41 |
| Security (SEC) | – | 3 | 1 | 3 | 7 |
| Architecture (ARCH) | – | 3 | 3 | 6 | 12 |
| Types (TYPE) | – | – | 2 | 3 | 5 |
| Performance (PERF) | – | – | 9 | 6 | 15 |
| Tests/harness (TEST) | – | 5 | 10 | 11 | 26 |
| Docs (DOC) | – | 2 | 11 | 4 | 17 |
| API/packaging (API) | – | 1 | 10 | 2 | 13 |
| Simplicity (SIMP) | – | 3 | 4 | 4 | 11 |
| Efficacy (EFF) | – | 3 | 4 | 3 | 10 |
| **Total** | **3** | **26** | **71** | **57** | **157** |

**Genuinely good — keep and defend (one line each):** the
`CacheDisposition`/`_lookup_cached_disposition` seam; `RouterRuntime` frozen
threading; the `CcrMirrorError` fail-open design; unconditional-persist marker
emission and its six-angle test coverage; `hash_canonical_pinned_vectors` (a real
cross-language lock); the marker-grammar single-owner + byte-identity tests; the
in-memory store's generation-FIFO with per-fix regression tests; encodings.rs
(stamp-time round-trip proofs as gates); the compactor's shipped-bytes stamp
gates; tag_protector's proptest symmetry invariants; the fd-pinned MCP read jail;
cause-honest retrieval misses; verify/'s cold-subprocess isolation and strict
reconstruction; BENCHMARKS.md's tiered honesty and preserved negative results;
FFI GIL discipline and ValueError-not-panic boundaries; `compress()`'s kwargs
allowlist and never-mutate-config semantics.
