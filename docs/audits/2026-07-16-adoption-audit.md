# furl-ctx — Independent Adoption Audit (2026-07-16)

An autonomous due-diligence audit answering one question: **"Should I and my AI agents start using this project?"**

Method: fresh-eyes landing-page review → GitHub/PyPI trust verification → documented-path installation → hands-on functional and edge-case testing (CLI, Python library, MCP server, plugin hooks executed with simulated Claude Code payloads) → full source review (Python + Rust) → security review → comparison with alternatives. Every claim is marked ✅ Verified (directly observed/executed), ⚠ Likely (strong evidence, not fully confirmed), or ❓ Speculation.

Environment: Linux container, Python 3.11.15, uv 0.8.17, furl-ctx 1.2.0 from PyPI, repo at commit `1c909fa`.

---

# Executive Summary

furl-ctx is a genuinely functional, unusually honest, well-engineered **solo experiment** — not yet an adoptable piece of infrastructure. The reversible compress/retrieve core works as advertised (byte-exact round trips verified up to 21 MB, loud misses, ReDoS-guarded retrieval, 0600-permission stores), and the maintainer's self-critical documentation is the best trust signal in the repo. But the flagship promise — automatic, hands-off context compression in Claude Code — **does not deliver today**: the PostToolUse path is inert due to a real, still-open upstream Claude Code bug (#68951), and the fallback PreToolUse pipe is Bash-only, disables itself if you have any Bash permission rule, and adds ~0.5–0.7 s to every Bash call. What works today is the *manual* MCP toolkit, which is solid but demands an agent workflow change. Combine that with a 2.5-week-old repo, bus factor 1, zero external users/issues/reviews, a 24-hour plaintext archive of tool outputs (redaction off by default), and several real bugs found in one afternoon of testing, and the recommendation is: **watch it, experiment with it, don't build on it yet.**

---

# First Impression

*(60-second landing-page read, before any deep inspection)*

**Immediate understanding** — ✅ The tagline ("The context compression layer for AI agents"), the tool list, and the install block communicate the core idea fast: shrink large tool outputs before they hit the context window; originals stay retrievable. An engineer could re-explain the concept after one minute.

**Immediate confusion** —
- Three products in one repo (Claude Code plugin, MCP server, Python library) with different defaults each; unclear at first which one "is" Furl.
- The plugin (1.3.0) and engine (1.2.0) version independently; the README needs a paragraph just to explain how to tell which you have. ✅
- The "Known issue" paragraph reveals mid-page that the headline auto-compression feature currently doesn't deliver tokens savings on the default path. Buried caveat for a landing page. ✅
- TTL rules take two paragraphs and still require cross-referencing LIBRARY.md (four different defaults across surfaces). ✅

**Things that looked suspicious** —
- "By using Furl you'll never need to touch grass again" and "Keep finding yourself waiting on the next usage limit reset?" — meme-marketing tone that undercuts an otherwise engineering-heavy README. ✅
- Headline "0–54% … reaching 95%" is an unusual, honesty-forward construction — but the Proof table still leads with 86–99% numbers. ✅
- Grammar slips ("a on-demand toolkit", "while agent is searching") suggest rushed recent edits. ✅

**Things that inspired confidence** — the "honest read" section that demotes its own benchmark table to "best-case ceilings"; a linked, real upstream bug; committed benchmark inputs; explicit tradeoff documentation ("Furl preserves data availability, not automatic anomaly discovery"). ✅

**Visual presentation / professionalism** — the ASCII logo is visibly broken (rows 5–6 are mis-indented; it does not render "FURL") and wraps a 53 KB SVG inside a `<pre>` block. ✅ Verified broken on the GitHub landing page. Badges are minimal (release + license only — no CI, no PyPI, no downloads badge).

**Marketing clarity: 7/10. Presentation polish: 4/10.**

---

# Discoverability & SEO

**Search visibility** — ⚠ Weak-to-moderate today.
- ✅ The dominant liability is the name: `furl` is a well-known 15-year-old Python URL-manipulation library (PyPI `furl`, latest 2.1.4). `pip install furl` installs the *wrong package*. Searches for "furl python" will be dominated by the URL library. Brand identity splits three ways: "Furl" (brand) / `furl-ctx` (package) / `furl@furl` (plugin).
- ✅ PyPI project URLs still point at the pre-rename repo (`github.com/omar-y-abdi/furl`) — works via redirect, but stale metadata hurts canonical-URL signals.

**AI discoverability** — ✅ Above average for a 2-week-old project: root `llms.txt`, a second (inconsistent) `site/llms.txt`, robots.txt explicitly allowing GPTBot/ClaudeBot/PerplexityBot, sitemap.xml, Google Search Console verification file, og:image, `glama.json` MCP-directory metadata. The infrastructure is there; the content behind it is one page.

**Google indexing observations** — ✅ A real deployed site exists (https://furl-ctx.vercel.app) with GSC verification (commits a3eaa58/d297a04 specifically fixed the verification file serving 200). ❓ Whether it ranks for anything yet is unverifiable from here; with 2 stars and no backlinks, ranking for "context compression" is unlikely near-term.

**Query coverage** — ✅ "context compression" appears in tagline/description; "token optimization" only as a pyproject keyword; **"prompt compression" — the actual term of art (LLMLingua et al.) — appears nowhere**; "context pruning"/"LLM context memory" absent.

**SEO weaknesses** — name collision; ASCII-art `<pre>` header invisible to crawlers (no real H1 value proposition); one-page site; three different headline numbers across README (95%), site (91.5%), and BASELINE.md (10 datasets, weakest four omitted from README); missing GitHub topics (`context-compression`, `prompt-compression`, `token-optimization`, `ai-agents`).

**SEO improvements (concrete)** —
1. Add "prompt compression" and "reduce LLM token costs" phrasing to the README first paragraph, repo description, and site meta.
2. Fix PyPI `project.urls` to the renamed repo.
3. Add the missing GitHub topics listed above.
4. Add a "furl-ctx is not `furl` (the URL library)" disambiguation line on PyPI and README.
5. Replace the broken ASCII logo with a real heading + image; put the value proposition in crawlable text.
6. Reconcile the 91.5% / 95% / 10-dataset discrepancy into one canonical number, then reuse it everywhere.
7. Expand the site into per-query doc pages ("compress tool outputs in Claude Code", "MCP context compression server") and list them in sitemap.xml; submit to awesome-mcp-servers / PulseMCP / mcp.so.

---

# Trust Assessment

All signals below ✅ Verified via GitHub API, PyPI API, and the local clone unless marked.

| Signal | Observation | Effect on trust |
|---|---|---|
| Repo age | Created **2026-07-01** (~2.5 weeks old); renamed from `omar-y-abdi/furl` ~Jul 13; lineage from a private "Headroom" project (stale `headroom` refs corroborate) | ↓ far too young to have survived real-world contact |
| Contributors | 1 human (the author) + bots (release-please, dependabot, copilot-swe-agent) | ↓ bus factor 1, no second pair of eyes ever |
| Stars / forks / users | 2 stars, 0 forks, **0 issues ever filed** | ↓ no evidence anyone but the author has run it |
| Releases | 9 releases v0.27.0→v1.2.0 in ~9 days; 8 in one 48h window; v1.0.0 nine days after repo creation | ↓ semver signals are noise; ↑ release notes are unusually candid (v1.0.2 admits the hook "was silent no-op live") |
| PRs / review | ~50 PRs, all self-merged, zero reviews; PR #104 merged **over a failing commitlint check** (owner bypass); open PRs include auto-generated agent PRs ("⚡ Bolt", "Lazy Dev Simplification Sweep") | ↓ CONTRIBUTING.md's "one maintainer review" policy has never been exercised |
| CI | 12 workflows: 4-shard pytest, Rust suite, CodeQL, commitlint, release-please, PyPI publish; PR checks green on merged work; deliberately no push-to-main CI (documented quota guard) | ↑ real CI, honestly configured |
| Tests | 172 files, ~1,713 Python + 851 Rust tests; real sqlite/multiprocessing/stdio-MCP e2e tests; captured byte-exact Claude Code hook payloads; fixed-seed fuzz + proptest; **no coverage gate**; Python 3.12-only CI matrix | ↑ substantial and mostly meaningful; ↓ characterization-pin brittleness |
| License / legal | Apache-2.0, NOTICE, SECURITY.md with disclosure process, CODE_OF_CONDUCT | ↑ |
| Security hygiene | CodeQL, dependabot, gitguardian config, deny.toml, SBOM in the wheel, 0600/0700 store perms | ↑ notably above-average for project age |
| Actions pinning | Tag-pinned (`@v7`), not SHA-pinned | → acceptable, not hardened |
| External claims | PyPI package real (9 versions) ✅; upstream bug anthropics/claude-code#68951 real, open, filed by a third party, matches README's description precisely ✅; docs site real ✅ | ↑ the project honestly advertises that its flagship path is currently broken upstream |
| Development style | 54 commits (shallow clone from Jul 9), dense conventional-commit bodies, 125+ internal ticket tags (`COR-44`, `API-8`…) referencing audit documents not in the repo | → clearly heavy AI-agent-assisted development at extreme velocity; unusually traceable, but unreviewable by outsiders |

**Confidence rating: Moderate-High integrity, Low maturity.** The author says true things — every load-bearing external claim checked out — but every property rests on one person's self-attestation, and internal docs are already drifting (CODEBASE-MAP.md contradicts CCR-RETENTION.md on store architecture; three different corpus headline numbers).

---

# Installation Experience

**Commands run** (documented paths, in order):

```
uv run --no-project --with 'furl-ctx[mcp]' furl --help   # README's CLI path
# → 35 packages installed, worked first try; 2.29 s cold (timed)

uv venv venv && uv pip install 'furl-ctx[mcp]'           # library path
venv/bin/furl doctor
# → [OK] furl_ctx import: 1.2.0 / [OK] native _core: _core.abi3.so
#   [OK] tiktoken / [OK] CCR store: SqliteBackend
```

- **Time to first successful execution: ~2.3 seconds.** ✅ Fastest install of any tool in its class I'm aware of; the Rust extension ships pre-built in the wheel (abi3), no compiler needed. The wheel even bundles a CycloneDX SBOM. ✅
- **Manual interventions: 0.** Warnings: 0. Guesses required for library/CLI: 0.
- `furl doctor` is a genuinely good touch — verifies import, native core, tokenizer, and store in one command. ✅
- **Friction points**: the primary documented install (`/plugin marketplace add omar-y-abdi/furl-ctx` inside Claude Code) could not be exercised end-to-end in this environment; instead I executed every hook script directly with byte-accurate simulated Claude Code payloads (results below). ⚠ The full plugin-manager flow is therefore unverified here. Also: `pip install furl` (the natural guess from the brand name "Furl") silently installs an unrelated URL library — the README never warns about this.
- **Unexpected issue**: none at install time. The often-fatal step for Python+Rust hybrids (building the extension) simply doesn't exist for wheel platforms.

---

# Functional Testing

All tests run against furl-ctx 1.2.0 from PyPI. ✅ = observed.

**Verified functionality**
- ✅ **Byte-exact reversibility** (the core promise): 190 KB log file and 21 KB CSV both compressed, retrieved via `furl retrieve <hash>`, and `cmp`-identical to the originals. Content-addressed hashes are idempotent across runs (same input → same hash).
- ✅ **Anomaly surfacing at small scale**: in 2,000 repetitive log lines, the single injected FATAL line **was preserved in the 5-line compressed view** — better than the README promises (it warns anomalies won't surface).
- ✅ **Sliceable retrieval on a 21 MB payload**: compress took 9.0 s; `furl retrieve <hash> --pattern "ERROR" --context-lines 1` found the needle among 400k lines in 0.8 s; `--line-range` equally precise.
- ✅ **ReDoS guard**: `--pattern "(a+)+$"` rejected with a clear message ("nested unbounded quantifier (catastrophic-backtracking risk)") — actively screened, not just timed out.
- ✅ **Loud misses everywhere**: retrieve after purge / bogus hash → exit 1 with backend, store path, and the three possible causes named. Bad `FURL_CCR_TTL_SECONDS` values (`banana`, `-5`) warn and fall back rather than crash.
- ✅ **MCP server**: all six tools (`furl_compress/retrieve/search/list/stats/purge`) work over raw stdio JSON-RPC; structured JSON results; hash format validated; `furl_search` found "row 4321" inside a stored 5,000-row payload; pattern retrieval returned exactly the matching line with line numbers.
- ✅ **PreToolUse pipe semantics**: executed the actual rewritten script — exit code 42 preserved, stderr passed through untouched, stdout replaced by the compressed view (190 KB → 599 B). The rewrite never `eval`s tool output; failure of the compressor falls back to `cat` of the original (fail-open confirmed by design and in execution).
- ✅ **PostToolUse hook**: fed a captured-format Claude Code payload; returned well-formed `hookSpecificOutput.updatedToolOutput` JSON and printed an honest stderr note that current Claude Code may ignore it (upstream #68951).
- ✅ **Python library**: the README snippet runs as documented; `CompressResult` carries tokens_before/after, ccr_hashes, warnings, error.

**Failed / broken functionality**
- ✅ **Binary input crashes the CLI with a raw `UnicodeDecodeError` traceback** (`cli.py:38 _read_input`) — no friendly error, no fail-open (the library's fail-open contract doesn't cover the CLI's read step).
- ✅ **CSV summary is actively misleading**: 1,000 *distinct* rows (`id` 0–999, distinct salaries) compressed to `[{"id":1,…,"_dup_count":1000}]` — the visible summary tells the model one row repeats 1,000×, which is false. Data remains retrievable, but an agent trusting the summary draws wrong conclusions. Footer even reads "1000 rows compressed to 0."
- ✅ **`furl purge` does not cascade**: purging the outer hash left the nested `<<ccr:…>>` dropped-rows blob independently retrievable. A user purging sensitive data would believe it gone while a copy survives under another hash.
- ✅ **Large-payload summaries lose the advertised structure for plain text**: the README advertises "schema, per-field value histograms, example rows" for a 33 MB trace; my 21 MB *text log* got plain head/tail + omission marker, and the ERROR needle vanished from view (only findable if the agent already knows to search). The structured-summary claim appears to hold only for structured (JSON/CSV) inputs — not stated in the docs.

**Edge cases & surprises**
- ✅ Empty input: clean no-op, exit 0.
- ✅ Unknown model name: silently accepted (falls back to default tokenizer) — no warning.
- ✅ `resolve_markers()` on a plain string dies with `AttributeError: 'str' object has no attribute 'get'` — documented signature is a message list, but a `TypeError` with guidance would be appropriate for a public API.
- ✅ **Metric semantics surprise**: `furl compress --json` on 80 KB of `/dev/urandom`-grade random strings reports `compression_ratio: 0.98`. That "98%" is *visibility reduction* (984 of 1,000 lines offloaded to the store), not compression. The same word — "reduction" — means honest lossless shrinkage in BENCHMARKS.md's 0–54% band and means "hidden but retrievable" in CLI/MCP stats (`furl_stats` reported 99.6% savings and `estimated_cost_saved_usd` of unclear provenance). Two incompatible definitions share one vocabulary; agents and humans will over-trust the big number.
- ✅ Same input, different surface, wildly different behavior: 3,000 near-identical lines → CLI ~99% visible reduction (CCR offload on), library `compress()` 50,006 → 29,029 tokens (42%, no CCR marker minted). Defaults differ silently across surfaces.
- ✅ Hook overhead (warm uv cache, measured): pretool gate ~0.24 s + pipe compressor ~0.32–0.44 s per Bash call, plus the PostToolUse spawn; first-run cold ~2.9 s (and potentially tens of seconds on cold uv caches, against a 30 s hook timeout).
- ✅ Store housekeeping: `~/.furl` is 0700, `ccr.sqlite3` 0600; secrets in tool output are stored **plaintext** and retrievable byte-exact for the TTL (24 h under plugin/CLI defaults); redaction exists (`FURL_REDACT_PATTERNS`) but is off by default.

---

# Source Code Review

*(full pass over `furl_ctx/` ~27.4k lines Python, `crates/` ~40k lines Rust, plugin hooks, and tests)*

**Architecture** — ✅ A Python orchestration shell around a **load-bearing Rust core** (SmartCrusher, log/diff/search/text compressors, tokenizer, BM25 — all PyO3; "no Python fallback" is explicit in `smart_crusher.py:17`). Three delivery surfaces (plugin hooks, MCP server, library) over one engine. Every lossy drop mints a `<<ccr:HASH>>` marker whose original is persisted to a sqlite/memory store; a mirror layer re-persists Rust-side drops into the Python-readable store, and mirror failure *vetoes* the compression (serves the original). The design is coherent and the fail-open/veto/loud-miss invariants genuinely hold in code and in my black-box tests.

Standing structural tensions: (a) **two parallel language implementations** (tokenizer fully duplicated Python/Rust with no FFI, pinned only by frozen golden vectors — silent divergence possible on unpinned inputs); (b) a two-store recovery plane bridged by mirror/veto machinery, including mixed hash algorithms (Rust MD5[:24] vs Python SHA-256[:24] vs 12-hex row hashes) held together by characterization tests; (c) an architecture partially shaped by **test-monkeypatch preservation** — `router_engine.py:24-45` late-binds globals explicitly "so the test suite's monkeypatches keep biting."

**Maintainability** — ⚠ High risk for anyone but the author. ~40% of Python lines are comments/docstrings, much of it changelog-sediment referencing 125+ internal ticket tags (`COR-44`, `API-8`, `TEST-32b`) whose source documents are not in the repo. `content_router.py` is a 1,272-line facade of delegation boilerplate over 10 extracted `router_*` modules. Unusual decision traceability; poor outside readability.

**Code quality** — ✅ Individually disciplined: no bare `except: pass` on load-bearing paths; `catch_unwind` on the FFI boundary with a `BaseException` backstop in `compress.py`; parameterized SQL throughout; monotonic clocks for TTLs; a genuinely careful `openat`/`O_NOFOLLOW` path jail in the opt-in `furl_read`; careful env parsing (mostly warn-and-fallback). Zero `unsafe` in Rust.

Concrete defects found (all ✅ verified in code):
1. `chat.py:149,156` — `compress_with_cache` can emit empty text blocks, which the Anthropic API rejects with a 400 (the engine elsewhere guards this exact case).
2. `compression_store.py:643-674` — hash-collision path returns before the `require_durable` check, silently breaking the durable-write veto contract in that (rare) branch.
3. `content_router.py:201-221` — result cache keyed by `(hash, len, bias)` never compares content; the comment claims collision-safety the code doesn't implement.
4. `router_engine.py:462`, `mcp_server.py:1774` — chars-vs-bytes confusion in size ceilings (up to ~4× off on multibyte content).
5. `pipeline.py:370-390` — `simulate()` claims to be side-effect-free but durably writes CCR entries and mutates the global cache.
6. `router_split.py:101-113` — markdown checklists (`[x] done`) misclassified as JSON sections.
7. `_ccr_offload` stores whitespace word counts as `original_tokens` — stats mix tokenizer counts with word counts.
8. CLI binary-input crash (verified at runtime, above).
9. `furl eval --recall` is a *required* `store_true` flag — mandatory flag conveying no choice.

**Dead code / unfinished ideas** — ✅ `csv_schema_decoder.py` (726 lines) shipped but consumed only by benchmarks; `FurlError` exported but never raised; `SmartCrusher(relevance_config=…)` raises `NotImplementedError`; hooks.py docstring references a nonexistent "Furl SaaS"; three default-off subsystems (code-aware compressor 1,592 lines, retrieval feedback, net-mutation gate) carried in every wheel; ghost documentation of excised subsystems throughout.

**Performance observations** — ✅ Engine throughput is fine (21 MB in 9 s; retrieval sub-second). The real cost is process architecture: every hook event spawns `sh -lc` → `uv run` → fresh Python → imports; one Bash call with the pipe on pays up to **three process spawns** (~0.5–0.7 s warm, measured; documented ~0.2 s is a floor). No daemon/warm server for hooks. `compress_chat_history` rebuilds its pipeline per call, discarding caches. The MCP server's `_file_cache` never evicts.

**Security observations** — rating **MODERATE — adopt only with configuration changes** (details from the dedicated review):
- High: all large Bash/WebFetch/Task outputs persist **plaintext to disk for 24 h by default, redaction off** (`redaction.py:43-44`; `.mcp.json`); given the upstream bug, the PostToolUse hook currently provides *storage cost with zero token benefit*. Same-user-only exposure (0600/0700 verified), no off-machine transmission — **zero network calls anywhere in the package** (grepped; SessionStart banner is a static printf).
- High (by design, well-mitigated): the default-on PreToolUse pipe rewrites every Bash command. Verified: exit codes preserved, stderr untouched, nothing from output is evaluated, rewrite is transcript-visible, and a total permission guard disables it if *any* Bash rule or unreadable settings file exists. Residual: buffered stdout, lost stdout/stderr interleaving, unguarded interaction with persistent-shell harnesses (❓ untested against every harness).
- Medium: supply chain — hooks fetch `furl-ctx[mcp]==1.2.0` from PyPI at first use: version-pinned but not hash-pinned, `--no-project` bypasses the lockfile, transitive deps float.
- Medium: marker forgery — any tool output can inject `<<ccr:HASH>>` (grammar validates only hex/width); `resolve_markers()` will splice stored content for any resolvable marker, and the MCP legend urges the model to retrieve markers it sees — a workable prompt-injection amplifier for pulling other recent same-project payloads into context (mechanism ✅ verified; real-world exploitation ❓).
- Verified at runtime: purge non-cascade (above) undermines the "purge = gone" mental model.
- Positives: 0600/0700 perms, ReDoS screens on retrieval patterns and redaction, parameterized SQL, TOCTOU-hardened file jail, honest SECURITY.md, CodeQL + dependabot + SBOM.

**Testing strategy** — ✅ Stronger than typical: ~2,500 tests across both languages, low mocking, real sqlite/multiprocessing/stdio e2e, byte-exact captured hook payloads, fixed-seed fuzz, proptest, and an adversarial `verify/` harness that documents silent-loss bugs it caught. Weaknesses: no coverage measurement in CI, brittle characterization pins (exact call counts, byte-for-byte log lines), 3.12-only matrix, MCP tests silently skip without the extra.

---

# Comparison With Alternatives

**vs. doing nothing (Claude Code's own mitigations)** — Claude Code already truncates giant tool outputs to files, supports subagents (fan out reading, return conclusions), and auto-compacts conversations. Those are free and maintained; they are *lossy* in different ways (truncation loses middles; compaction loses fidelity). Furl's genuine differentiator is **reversibility**: nothing is lost, everything is retrievable by hash/pattern/range. ✅ Verified working. But the integration reality inverts the pitch: Furl's automatic path is currently inert in the very harness it targets, while the manual MCP tools duplicate what an agent can approximate with `grep`/`head` at zero install cost when the data is in files.

**vs. LLMLingua / prompt-compression research tools** — those compress *prompts* lossily via a small model; heavier, GPU-hungry, irreversible, not agent-integrated. Furl is lighter, deterministic, reversible, and tool-output-focused. They solve different problems; Furl never mentions them or the term "prompt compression," to its SEO detriment. (⚠ comparison from general knowledge, not fresh benchmarks.)

**vs. RAG / memory layers (e.g. vector stores, mem0-style)** — those persist knowledge across sessions with semantic search; Furl is a short-TTL (30 min–24 h) byte-exact spill buffer with substring/regex search only (BM25 exists internally but no embeddings). Complementary, not competitive.

**Unique value** — content-addressed, byte-exact, TTL'd offload of oversized tool outputs with sliceable retrieval (`--pattern`, `--line-range`, field selects) exposed as MCP tools; honest token accounting via real tokenizers; genuinely good failure-mode engineering (fail-open, loud miss, veto).

**Missing features** — a daemon to kill per-call spawn latency; semantic retrieval; cascade purge; structured summaries for large *text* payloads; cross-surface consistent defaults; a second maintainer; and the one that matters most — a working automatic path in Claude Code (blocked upstream, not by Furl).

---

# User Experience

**Documentation** — comprehensive to a fault: README + LIBRARY.md (30 KB) + BENCHMARKS.md (39 KB) + CCR-RETENTION.md + plugin README + CODEBASE-MAP.md. The honesty is exemplary; the *organization* is not. The TTL story needs four documents to reconcile (library 30 min / bare MCP 1 h / CLI & plugin 24 h — and my `furl mcp` session showed 24 h, the CLI default, adding a fifth nuance ✅). Internal contradictions verified: CODEBASE-MAP vs CCR-RETENTION on store architecture; SKILL.md contradicting itself on the store path (`~/.furl/ccr.sqlite3` vs per-project); stale `/plugin marketplace add /path/to/headroom` instruction; root llms.txt describing a 3-tool server vs the actual 6(+1).

**Onboarding** — two slash commands (if you have uv), or one pip install. Truly easy. But the first thing a new user should be told — "the automatic compression you installed this for doesn't currently reach the model; here's what does work" — is mid-README fine print.

**Learning curve** — for humans: moderate (marker grammar, hash retrieval, TTL matrix, ~32 `FURL_*` env vars). For AI agents: the MCP tool descriptions + SKILL.md are well-written and my raw JSON-RPC session required zero guessing (✅); agents would use `furl_compress`/`furl_retrieve`/`furl_search` reliably. The risk for agents is semantic, not mechanical: trusting misleading summaries (`_dup_count` bug) and inflated "savings" stats.

**Developer ergonomics** — `furl doctor`, loud error messages naming store paths and causes, `--json` stats, and idempotent hashes are all excellent. The CLI lacks `list`/`search`/`stats` subcommands (MCP-only), inconsistently validates hashes vs the MCP server, and crashes on binary input.

**Where users get stuck** — ⚠ (projected from observed behavior): wondering why token usage didn't drop (upstream bug + pipe silently disabled by their Bash allow-rules + Read/Grep bypass by design); reconciling plugin vs engine versions; finding data "gone" (TTL expiry is silent until a loud miss); assuming purge removed everything.

---

# Strengths

*(each ✅ verified)*
1. Reversibility promise holds: byte-exact round trips, content-addressed idempotent hashes, loud misses.
2. Frictionless install: prebuilt abi3 wheel, 2.3 s to first run, `furl doctor`, SBOM in the wheel.
3. Retrieval quality: sub-second pattern/range slicing over 21 MB; ReDoS screening; field-level selects.
4. Small-scale anomaly surfacing beats its own documentation (FATAL line kept among 5 survivors of 2,000).
5. Fail-open discipline end-to-end — hook failure never breaks a tool call (executed and confirmed).
6. Exit-code and stderr preservation through the Bash pipe rewrite (executed and confirmed).
7. Security fundamentals: 0700/0600 stores, no network calls at all, parameterized SQL, permission-rule guard that disables the pipe, transcript-visible rewrites.
8. Unusually honest documentation culture: "honest read" bands, disclosed upstream breakage, disclosed secret-at-rest risk, committed benchmark inputs, adversarial self-verification harness.
9. Serious test corpus (~2,500 tests, both languages, low mocking, real e2e).
10. Real CI with CodeQL, dependabot, release automation, conventional commits.

# Weaknesses

1. ✅ Flagship automatic compression currently delivers no token savings in Claude Code (upstream #68951); the fallback pipe is Bash-only and disables itself if any Bash permission rule exists.
2. ✅ Bus factor 1; 2.5 weeks old; zero external users, issues, reviews; self-merged PRs including one over a failing check.
3. ✅ Privacy default: 24 h plaintext archive of tool outputs, redaction opt-in, purge non-cascading.
4. ✅ Latency tax: up to 3 process spawns per Bash call (~0.5–0.7 s warm, seconds cold); no daemon.
5. ✅ Metric vocabulary conflates visibility-reduction with compression (98% "ratio" on random noise); `furl_stats` savings and USD figures will mislead.
6. ✅ Misleading compressed views possible (`_dup_count` on distinct rows).
7. ✅ Config sprawl: ~32 env vars, four+ TTL defaults, divergent CLI/library/MCP behaviors.
8. ✅ Maintainability: comment sediment keyed to unresolvable ticket tags, duplicated Python/Rust stacks pinned by golden vectors, facade layers preserving monkeypatch seams.
9. ✅ Docs drift already present (CODEBASE-MAP vs CCR-RETENTION; SKILL.md self-contradiction; stale headroom paths; 3-tool llms.txt).
10. ✅ Brand/SEO liability: name collision with the established `furl` PyPI package; stale PyPI URLs; no "prompt compression" keyword coverage.
11. ✅ Supply chain: hooks pull from PyPI at first use without hash pinning or lockfile; Actions tag-pinned only.
12. ✅ Marker forgery is structurally possible (prompt-injection amplifier; scope-limited to same-project stored data).

# Bugs Found

*(all reproduced or code-verified this audit)*
1. CLI crashes with raw `UnicodeDecodeError` traceback on binary input (`cli.py:38`).
2. CSV/JSON summary can label 1,000 distinct rows `"_dup_count": 1000` — factually wrong visible summary; footer says "1000 rows compressed to 0."
3. `furl purge` leaves nested dropped-row blobs retrievable (non-cascading delete).
4. Large plain-text payloads get head/tail truncation, not the advertised structured summary; error lines vanish from view at scale (21 MB test).
5. `compress_with_cache` can emit empty text blocks → Anthropic API 400 (`chat.py:149,156`).
6. Durable-write veto bypassed on hash-collision path (`compression_store.py:643-674`).
7. Result-cache collision comment claims a safety property the `(hash, len, bias)` key doesn't provide (`content_router.py:201-221`).
8. Chars-vs-bytes limit confusion (`router_engine.py:462`, `mcp_server.py:1774`).
9. `simulate()` has durable side effects despite claiming none (`pipeline.py:370-390`).
10. Markdown checklists misrouted as JSON sections (`router_split.py:101-113`).
11. Offload stats record word counts as token counts (`router_engine.py` `_ccr_offload`).
12. `resolve_markers` raises bare `AttributeError` on non-list input (missing type guard).
13. `furl eval --recall` is a required boolean flag.
14. WebSearch is hook-matched but structurally never compressed (`compress_tool_output.py:154-158`).
15. Hardcoded version quadruplication (SessionStart banner, plugin.json, pins, `_FURL_CTX_PIN`) — banner can silently lie.
16. Repo hygiene: `.gitignore:264` ignores the entire `/docs/` directory, yet `docs/audits/DESIGN.md` is force-tracked over the ignore — new documentation added under `docs/` silently disappears from `git add` (this audit hit it).

# Improvement Opportunities

**Critical** *(adoption blockers; benefit: every prospective user)*
1. Ship a truthful "what works today" banner at the top of the README: automatic path pending upstream fix; pipe = Bash-only, off under permission rules; Read/Grep bypassed by design. Effort: hours. (The information exists; it's the placement that misleads.)
2. Separate the two meanings of "compression": report `visible-token reduction` and `lossless compression` as distinct numbers in CLI/MCP stats and benchmarks. Effort: days. Prevents agents/users from over-trusting 98%-on-noise figures.
3. Fix the `_dup_count`-on-distinct-rows summary bug — misleading a model is worse than not compressing. Effort: days.
4. Redaction on by default (built-in credential patterns) for stored originals, or first-run consent + `furl purge --all`; make purge cascade. Effort: days. Benefit: anyone whose agents touch secrets.

**High Priority**
5. A resident daemon (or the MCP server doing hook work) to eliminate per-Bash-call spawn latency. Effort: 1–2 weeks. Benefit: every plugin user, every call.
6. Hash-pin or lockfile-pin the hook's PyPI fetch. Effort: hours-days. Benefit: supply-chain posture.
7. Graceful binary/undecodable input handling in the CLI. Effort: hours.
8. Unify defaults (TTL, backend, offload aggressiveness) across CLI/library/MCP, or print the active profile on every run. Effort: days.
9. Reconcile drifted docs (CODEBASE-MAP, SKILL.md store path, headroom remnants, llms.txt tool count, README/site/BASELINE headline numbers). Effort: days.

**Medium Priority**
10. Structured summaries (or at least error-line preservation) for large plain-text payloads. Effort: ~week.
11. CLI parity: `furl list/search/stats`; consistent hash validation with the MCP server. Effort: days.
12. Coverage measurement + gate in CI; widen the Python matrix beyond 3.12. Effort: days.
13. Rename/disambiguate vs the `furl` URL library on PyPI/README; fix PyPI project URLs. Effort: hours.
14. Marker-grammar hardening: only resolve markers the store actually minted for that session/namespace (verify provenance, not just format). Effort: days.

**Nice to Have**
15. Prune dead weight (`csv_schema_decoder`, `FurlError`, NotImplementedError params, ghost docs); translate ticket-tag comments into human rationale or link the archive. Effort: ongoing.
16. SEO: real H1, "prompt compression" coverage, GitHub topics, MCP directory listings, per-query doc pages. Effort: days.
17. SHA-pin GitHub Actions. Effort: hours.

# Final Verdict

## Probably Not — *today, for production agent workflows.* Re-evaluate when the upstream hook bug is fixed and a second party is maintaining or at least reviewing.

Why not "No": everything the project claims to do reversibly, it verifiably does — round trips are byte-exact, misses are loud, failure modes are engineered with unusual care, security fundamentals are present, and the documentation is more honest about its own limits than most mature projects. Tinkerers who want the *manual* MCP toolkit (compress/search/slice-retrieve giant tool outputs on demand) get real, working value right now, and the two-command install makes trying it nearly free.

Why not "Yes, with caveats": the reason most people would install it — automatic, hands-off context compression in Claude Code — currently cannot deliver on its default path due to an open upstream bug, and its stopgap (rewriting every Bash command) is narrow, latency-taxed, and disabled by common configurations. The project is 2.5 weeks old with a bus factor of 1, zero external users or reviewers, defaults that persist plaintext tool output (including any secrets) for 24 hours with a non-cascading purge, stats that overstate savings by conflating offload with compression, and at least one summary-fidelity bug that would feed a model false information. For an *AI agent workflow* — where the agent trusts summaries and stats implicitly — those last two items are disqualifying until fixed.

**If you do adopt now**: use the MCP tools only (skip the pipe: `FURL_PRETOOL_PIPE=0`), set `FURL_REDACT_PATTERNS`, lower `FURL_CCR_TTL_SECONDS`, and treat every "savings" number as visible-context reduction, not compression.

# Research Diary

- **Landing page**: understood the pitch in under a minute — good sign. Noticed the broken ASCII logo, the "touch grass" joke, and that the "Known issue" paragraph quietly concedes the flagship feature is inert. First hypothesis: marketing-heavy vaporware. This turned out **wrong** — the engineering is real.
- **Structure survey**: 27k lines Python + Rust crates + 172 test files for a 2-week-old repo. New hypothesis: heavy AI-assisted development. (Later corroborated: 125+ internal ticket tags, 8 releases in 48 h, agent-generated PRs.)
- **Install**: braced for a maturin/Rust build fight; got a prebuilt abi3 wheel and a 2.3 s cold start with zero interventions. Genuinely impressed. `furl doctor` exists — someone thought about failure modes.
- **First compressions**: logs 190 KB→599 B *with the injected FATAL line surfaced* — better than the README promises (it warns anomalies won't surface). Briefly suspected the README undersells; later corrected: at 21 MB the same class of needle vanished from view. The honesty holds at scale, the pleasant surprise only at small scale.
- **Entropy test**: 98% "compression" of random noise stopped me cold — impossible information-theoretically. Realized "reduction" here means offload-to-store, not compression. This became one of my main findings: the vocabulary conflation will mislead exactly the audience (agents) the tool targets.
- **CSV test**: found the `_dup_count: 1000` on distinct rows. First outright fidelity bug — the compressed view *lies* while the store tells the truth.
- **Purge test**: nested blob survived purge of the outer hash. Second real bug, this one with privacy implications. Pattern emerging: the happy path is polished; the corner cases weren't all found yet.
- **ReDoS probe**: expected a hang; got an intelligent rejection message naming catastrophic backtracking. Revised upward my estimate of the author's security literacy — later confirmed by the 0600 stores, the permission guard, and zero network calls.
- **Pipe rewrite execution**: expected broken exit codes; got exit 42 and stderr faithfully preserved. The rewrite is more careful than I assumed — but measured ~0.5–0.7 s warm overhead per Bash call, which the docs' "~0.2 s" undersells.
- **Agent reports landed**: source review confirmed the Rust core is load-bearing (not résumé decoration), found the collision/veto and empty-text-block bugs, and quantified the comment sediment. Trust review verified PyPI and the upstream bug are real, found the repo is 2.5 weeks old with zero external fingerprints, and caught the three inconsistent headline numbers. Security review rated it MODERATE with the plaintext-24h default as the top finding.
- **Mind change log**: started at "probably vaporware" → mid-audit "surprisingly excellent, maybe Yes-with-caveats" → final "Probably Not (today)" once I weighed that the *automatic* value prop is currently undeliverable upstream, the working surface is manual-only, and the two fidelity/metric bugs directly poison agent trust. The project's honesty is its best asset; its age, bus factor, and defaults are its blockers. I'd genuinely revisit in a quarter.
