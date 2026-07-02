# QUESTIONS FOR USER — accumulated during autonomous run (2026-07-02)

> User asleep; running autonomously to complete the FABLE-RECON-PLAN. Owner-decisions
> the plan cannot make are logged here (NOT acted on) — the blocked work waits; everything
> else proceeds. On your return, message me and I'll fire these via AskUserQuestion in order.
> Each entry: **what's blocked · the fork · my recommendation.** Append-only.

## A. §5 owner decisions (12) — from FABLE-RECON-PLAN §5

1. **Telemetry/TOIN & compression_feedback — delete vs shrink?** (§5.1; ARCH-3, SIMP-1/2/3)
   Blocks: Phase-3 Great Excision (collector/beacon ~1,300 LOC + feedback plane), SEC-2, SEC-3, PERF-9/10.
   Fork: delete outright (matches excision precedent, kills SEC-2/3 + PERF-9/10 for free) vs shrink TOIN to a minimal recorder (keep only if the learning-loop consumer is genuinely returning).
   **Rec: DELETE** — north star is usage/compression, not telemetry; MCP tool work doesn't need the old TOIN plane. (If kept, SEC-2/3 become mandatory immediately.)

2. **Bash in DEFAULT_EXCLUDE_TOOLS — intentional exclusion or bug?** (§5.2; COR-10/EFF-1)
   Blocks: COR-10, EFF-1 (the single biggest default-savings lever).
   Fork: comment says "Bash is NOT excluded" but the frozenset excludes it + assigns a dead profile. Either compress Bash outputs (delete the 2 entries, bench-gate) or rewrite the comment + delete the dead profile.
   **Rec: COMPRESS** (remove Bash from exclude) — biggest efficacy lever, aligns with "better compression tool"; bench-gate the output change.

3. **Code strategy (EFF-2):** restore AST-outline compressor, invest in line-level near-dup, or accept 0% on code + delete the ast-grep dep + honest-README the matrix?
   Blocks: EFF-2, API-6 (ast-grep dep honesty).
   **Rec: accept 0% + delete ast-grep dep + honest README** (lazy/safe; AST-outline is lossy-risky). Revisit AST if code-compression demand appears.

4. **Kompress standing (EFF-5):** keep-as-core vs demote-to-experimental (measure first via the verify family)? Also GPU/CPU borderline divergence (SIMP-10/COR-11 cluster) — unify or document?
   Blocks: EFF-5 disposition (mostly measurement — I can add the verify family + measure autonomously; the keep/demote call is yours).
   **Rec: keep-as-core** (it's the text compressor); I'll add measurement so the call is data-backed.

5. **Dotted-flatten contract (COR-14):** wire-format change (mark + un-flatten, Rust+Python lockstep) vs documented value-exact-under-dotted-keys?
   Blocks: COR-14.
   **Rec: doc-honesty (b)** — small, safe, no wire-format churn; state value-exact-under-dotted-keys in both docstrings + teach independent_recheck to compare un-flattened.

6. **Rust content_detector mirror (SIMP-6/DOC-13):** delete ~700 LOC or keep as a documented comparison oracle?
   Blocks: Phase-3 excision item 4, DOC-13.
   **Rec: DELETE** — the Python detector is the live path; the Rust mirror is dead weight (excision precedent).

7. **Diff parity-only info losses (DOC-12):** with the Python original retired, keep or lift the `100644`/`Binary files` normalizations?
   Blocks: DOC-12 (minor).
   **Rec: document + keep** (low stakes; lifting risks diff-render churn).

8. **Docs placement (DOC-4, API-13):** archive DESIGN.md / PLAN.md / audits with banners, or keep at root?
   Blocks: DOC-4, API-13 (placement only).
   **Rec: archive the internal-planning docs** (DESIGN.md, audits) with banners; keep README/BENCHMARKS/CONTRIBUTING/SECURITY at root.

9. **`security@headroom.dev` / `conduct@headroom.dev` (DOC-7):** do these mailboxes exist? Unverifiable from the repo.
   Blocks: DOC-7 (SECURITY.md / CODE_OF_CONDUCT accuracy).
   **Rec: you confirm** — if not real, I'll point them at a GitHub issues/security-advisory flow instead.

10. **Durable CCR spill (CCR-RETENTION.md, 5 ranked options):** which option + when? (EFF preamble recommends shipping before "reversible" is marketed harder.)
    Blocks: a FEATURE decision (not a defect fix) — deferring wholesale.
    **Rec: discuss separately** — it's net-new scope, not part of the burn-down.

11. **Exception contract (API-1):** commit to raising 2-3 typed exceptions (behavior change) vs document the fail-open-only reality?
    Blocks: API-1.
    **Rec: document fail-open reality** (no behavior change, honest); the 9 fictional exception exports get deleted regardless (that part isn't blocked).

12. **`compress_unique_entities_when_recoverable` force-enable (lib.rs:539, SIMP-7):** expose on the Python surface or keep the comment-guarded divergence?
    Blocks: the SIMP-7 wire-contract commit's config-exposure part.
    **Rec: keep guarded + document** (safe; exposing is a surface-API change).

## B. New questions arising mid-run

13. **README multiturn number sync (COR-52 contract-fix).** COR-52 fixed dedup to honor `protect_recent` (recent messages no longer wrongly deduped) → multiturn `86.5% → 85.1%` (contract-correct; the old number captured the over-dedup bug). I re-baselined `benchmarks/baseline_results.json` (multiturn 2211) autonomously, but the **README Proof table still says multiturn 87%** — now overstates by ~2pp. **Rec:** sync README multiturn to 85%. Trivial factual update, flagged only because README is outward-facing/you-arbitrated.

14. **PR #5 CCR-offload — the `code 99%` framing (informational, no action unless you disagree).** Merged per your authorization; `code@7` shows 98.9% via CCR-offload (recoverable), but real agent file-reads (Read/Glob) are excluded from offload → stay 0%. README honestly says "identity preview + retrieval marker ships in place of the full files," but a reader could infer "my code compresses 99%." If you want, add one line clarifying the offload targets large non-file-read tool outputs. Left as-is (honest enough); flagging for transparency.

---
### Execution status while these wait
Blocked (deferred): Phase-3 Great Excision (Q1, Q6), COR-10 (Q2), COR-14 (Q5), EFF-1/2, API-6, SEC-2/3 (Q1-dependent), PERF-9/10 (Q1-dependent), DOC-4/7/12/13, API-1 (Q11), SIMP-6 (Q6), the CCR-spill feature (Q10).
Proceeding autonomously: all COR correctness (minus 10/14), COR-7, PERF (minus 9/10), ARCH incl §4.1/§4.2 refactors, TEST, DOC (minus 4/7/12/13), API (minus 1/6), SIMP (minus excision-blocked), SEC unconditional (SEC-1/4/5/6/7), EFF-3.
