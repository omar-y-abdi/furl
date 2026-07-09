# FURL — 3-Agent Validation Report
> Read-only validation across the WHOLE codebase + ALL work cycles. 3 parallel agents (finished-is-finished · loose-ends · lazy-ladder), each verify-before-report with file:line evidence. Synthesized by PM after reading every primary tracking-doc in full + independent HEAD verification.
> HEAD `36187ac2` (= GitHub main `fefd4ab1` for all tracked files); dev-gate: **1716 pytest pass, ruff clean, cargo 0 dead_code, furl doctor OK**.

## NET VERDICT
The codebase is in strong shape. **Everything claimed finished is truly implemented and wired** (0 not-backed of 24 harness claims; FABLE 68/189 + engine-stream + Great Excision confirmed via green gate + reachability). **The tree is lazy-ladder-clean** (every old audit cut already applied; 2 trivial free-deletes remain). The genuine "what's left" is small: a handful of real loose ends (mostly the MCP surface + a silently-dropped B3 spec item + git hygiene), several STALE DOCS that under-report shipped work, and a set of DELIBERATELY-deferred items. No hidden broken work.

---

## CORRECTION TO MY EARLIER SCOPE-MAP (2 items were wrong — caught by validation)
1. **"5 commits ahead of main, UNMERGED" was FALSE** — stale local git ref. `git fetch` → origin/main is `fefd4ab1` (PR #43's merge). `git diff HEAD origin/main -- . ':!harness-plan.md'` is EMPTY. PRs #38/#41/#42/#43 all MERGED (gh confirmed). **All B-work IS on main.** Only local refs were unfetched.
2. **Q10 durable CCR spill is NOT open — it SHIPPED.** CCR-RETENTION.md (my source) is stale. Spill tier is live: `compression_store.py:1729` `FURL_CCR_SPILL` + `:1733` `_create_spill_backend_from_env` + `:1794` wired; `_evict_if_needed → _spill_evicted` before delete; test `tests/test_ccr_spill_tier.py`. Q10 = resolved.

---

## AGENT 1 — FINISHED-IS-FINISHED (`/tmp/verify-finished.md`, Opus)
- **24 VERIFIED · 1 PARTIAL (doc-path only) · 0 NOT-BACKED · 4 deferred-documented.** Dev-gate: 1716 pytest pass (target 1708 exceeded), ruff clean, doctor OK.
- Every harness `[x]`/SHIPPED/COMPLETE claim is implemented AND wired (call-sites confirmed for Q3 envelope, B1 HTML, agent-utility slice-hint). B2 namespace/export/import, B3 redactor(fail-closed)/purge, B4 chat, B5 eval — all real, not stubs.
- 2 non-defect caveats: (a) Q1 doc header points at `tokenizer.py` but the claude→o200k mapping lives at `tokenizers/registry.py:61-104` (feature fully works); (b) Q6/Q7 hook env-vars live in `plugins/furl/hooks/`, not `furl_ctx/` — a search-scope artifact, they ARE wired + tested.
- The 3 doc contradictions (resolved by me + agents): **R6 opaque-scrape** = future-cycle-deferred epic (union-net kept, deliberate); **A1 apply()** = decomp done (content_router.py 1262 LOC / apply() ~105, not the stale 2363/500); **lazy-v4 proxy-plane** = already cut.
- Coverage caveat: this agent scoped to harness-plan.md's claims; the FABLE 68/189 mass is confirmed *indirectly* (green gate + agent-3's Excision reachability sweep), not re-verified finding-by-finding.

## AGENT 2 — LOOSE-ENDS (`/tmp/verify-loose-ends.md`, Sonnet)
**REAL (worth acting on):**
- **MCP surface gaps** (deferred per north-star, but flagged): `furl_retrieve` inputSchema never advertises `select_field/select_equals/select_min/select_max/limit` though `RetrieveFilters.parse()` reads them → unreachable via MCP. **No `furl_purge` MCP tool at all** (library+CLI only) — B3's purge is a security primitive the one live model-facing surface can't invoke.
- **`FURL_HOOK_SENSITIVE_TOOLS`** (memory-only compression for sensitive tools) — was in the original B3 spec, never implemented, and unlike encryption/audit.jsonl (explicit SKIP) it silently vanished from the B3 summary. Zero mentions anywhere. Decide: implement or explicit-SKIP.
- **Git hygiene**: harness-plan.md has 1 uncommitted edit (PLAN-COMPLETE paragraph, at loss-risk); `verify/raw_results.json` documented "never commit" but missing from `.gitignore` (guardrail gap); `benchmarks/agent_utility_baseline.json` never committed though its sibling baseline is the enforced regression convention.
- **PERF-16**: MCP `_retrieve_content` runs store/BM25 sync on the event loop (unlike `_compress_content`'s `run_in_executor`).
**STALE DOCS (under-report shipped work):** CCR-RETENTION.md (Q10 spill — shipped, see correction); RUST_DEV.md + signals/README.md (describe `Tiered<T>` as live/future — deleted SIMP-5b).
**DELIBERATE (not loose ends, verified as-documented):** opaque-scrape union-net, COR-17 word-count fallback, ARCH-7 private-method reach, `enable_ccr_marker`→`advertise_retrieval_tool` deprecation alias, 4 doc-parked items.
**Clean:** TODO/FIXME/stub grep = 0 hits; 7 test skips all legit platform/env conditionals (no rot-to-green).
**Cosmetic:** 9 stale local branch caches (GitHub-deleted), 117 worktree-wf_* Workflow-tool leftovers.

## AGENT 3 — LAZY-LADDER, ALL CODE (`/tmp/verify-lazy.md`, Sonnet)
- **VERDICT: tree lazy-ladder-clean.** Every v4 Tier-1/2/3/Decision-Gate item already GONE at HEAD (verified file-existence + caller-grep, not trusting stale v4). cargo 0 warnings/0 dead_code, ruff clean, vulture clean.
- **2 trivial free-deletes only:** (1) Rust `detect_diff()` (`unidiff_detector.rs:88` + re-export `mod.rs:43`) — 0 non-test callers, `detect()` duplicates via `is_diff()` inline. ~11 LOC. (2) `numpy>=1.24.0` in pyproject `dev` extras — orphan from deleted kompress_compressor.py, 0 imports.
- Informational (packaging-honesty, not lazy): `PIL` used try/except-guarded in `tokenizers/base.py`, undeclared in pyproject.
- Adversarial-verify: csv_schema_decoder.py trap CONFIRMED (726 LOC, guards byte-exact recovery, do-not-touch); `_create_default_ccr_backend` REFUTED-dead (now has live SqliteBackend branch).
- B-work (B3 redactor/purge, signal-aware `_ccr_summary`, sliceable retrieve + CLI) all ladder-compliant — minimal, wired, no speculative knobs.
- Coverage caveat: leaned on cargo/ruff/vulture + manual v4-lead + B-work verification; did not byte-audit all 44k LOC line-by-line.

---

## CONSOLIDATED "WHAT'S LEFT" (ranked)
| # | Item | What it is / does | Why not finished | Severity |
|---|------|-------------------|------------------|----------|
| 1 | MCP `furl_purge` tool absent | B3 purge (delete a stored CCR blob) reachable only via library+CLI, not the model-facing MCP surface | Deferred per north-star ("MCP waits until codebase beyond-perfect") — but it's a SECURITY primitive the model can't invoke | Med (deferred) |
| 2 | MCP `furl_retrieve` select_* not advertised | Slice params parsed by handler but absent from inputSchema → model can't use narrow-slice retrieval | Task #8, deferred per north-star; 1-block schema add | Med (deferred) |
| 3 | `FURL_HOOK_SENSITIVE_TOOLS` dropped | Original B3 spec item (memory-only compress for sensitive tools) | Silently vanished from B3 summary — no implement/SKIP decision recorded | Med |
| 4 | Git hygiene | harness-plan.md uncommitted edit; verify/raw_results.json not in .gitignore; agent_utility_baseline.json uncommitted (no regression floor) | Housekeeping never done | Low (real) |
| 5 | PERF-16 MCP event-loop | retrieve/BM25 sync on asyncio loop | Known low-prio, never batched | Low |
| 6 | Rust `detect_diff()` + numpy dev-orphan | dead ~11 LOC + orphan dep | trivial free-deletes | Low |
| 7 | Stale docs (CCR-RETENTION, RUST_DEV, signals/README) | describe shipped/deleted things as open/live | doc-drift after work landed | Low (doc) |

## DELIBERATELY DEFERRED (working-as-intended — NOT gaps)
Opaque-scrape elimination epic (union-net safety kept), at-rest encryption + audit.jsonl (YAGNI SKIP), Engine-P2 backlog (LogTemplate/tabular/secret-mask/token-calibration), A1 further apply() shrink (already 105 lines), Q14 README cosmetic line.

## RECOMMENDED NEXT STEPS (small, ordered)
1. Git hygiene (5 min): commit harness-plan.md; add `verify/raw_results.json` to .gitignore; commit `benchmarks/agent_utility_baseline.json`.
2. Decide `FURL_HOOK_SENSITIVE_TOOLS`: implement (small) or record explicit SKIP like encryption/audit.
3. Trivial lazy cuts: delete Rust `detect_diff()` + re-export; drop `numpy` dev-extra.
4. Doc-drift fix: correct CCR-RETENTION.md (Q10 shipped) + RUST_DEV/signals README (Tiered deleted).
5. MCP surface (only when north-star says MCP-time): add `furl_purge` tool + advertise `select_*`.
