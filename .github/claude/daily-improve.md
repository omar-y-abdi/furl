# Daily Improvement Routine

You are running the scheduled daily improvement session for furl-ctx. Your job
today: find ONE genuinely new improvement, prove it is real, implement it,
verify it end to end, and open a pull request with evidence. A human reviews
and merges every PR. You never merge.

## Mission

One focused, evidence-backed improvement per day, anywhere in the repo. Code,
performance, compression quality, test rigor, API ergonomics, docs accuracy,
build tooling. Small and real beats big and speculative.

## Hard rules

- NEVER merge, enable auto-merge, or approve your own PR. Open it and stop.
- NEVER weaken a test, baseline, threshold, or assertion to get green. If a
  metric legitimately improves, update the pinned expectation in the same PR
  and explain why in the PR body.
- NEVER touch the required-check structure in `.github/workflows/ci.yml`.
  `tests/test_ci_required_checks_guard.py` enforces this; keep it green.
- NEVER add a dependency without a strong written justification in the PR body.
- NEVER delete code you merely suspect is dead. Prove it: no references, no
  dynamic lookups, no plugin or MCP surface, tests still pass.
- NEVER force-push to main or rewrite history on any branch you did not create
  today.
- One PR per session. If you find a second problem, note it in the ledger's
  candidate list instead of expanding scope.
- Follow the type-driven style of the codebase: total functions, explicit
  domain errors, effects at the edges, no stringly-typed states.

## Step 0: anti-repeat, before choosing anything

1. Read `docs/audits/IMPROVEMENT-LEDGER.md`. Every prior automated PR is
   listed there with its area and files.
2. Run: `gh pr list --state merged --limit 40 --json title,files,mergedAt`
   and skim which modules recent PRs already touched.
3. Build your exclusion list: any area in the ledger from the last 30 days,
   plus any module a merged PR touched in the last 14 days.
4. Your chosen target must NOT be in the exclusion list. Always look for what
   nobody has touched yet: the coldest corners, not the warmest.

## Step 1: pick exactly one target

Rotate across dimensions day by day; pick the highest-value target outside the
exclusion list. Priority order when in doubt:

1. Correctness or silent-loss risk in the compression or CCR recovery path.
2. Compression quality: better token reduction with retention held at 100%.
3. Performance: speed or memory in `crates/furl-core` or the Python layer.
4. Test rigor: a live module whose tests would survive a deliberate bug.
   Boundary coverage, red-proof quality, property tests.
5. API and DX: sharper types, clearer errors, dead-simple entry points.
6. Docs truth: README, CONTRIBUTING or docs claims that drifted from code.

If everything looks covered, go one level deeper on an old area instead of
repeating it: property-based tests where only example tests exist, fuzzing a
parser, extending the benchmark corpus with a new real-world dataset, tightening
mypy or clippy strictness one notch. List 3 candidates in your notes, pick one,
and record the other two in the ledger's candidate list.

## Step 2: prove the problem before fixing it

Produce a failing artifact FIRST: a failing test, a benchmark number, a
reproducible measurement, or a concrete broken example. If you cannot
demonstrate the problem, it is not a problem; pick another target. Save the
before-numbers; the PR body needs them.

## Step 3: implement

- Branch off current main: `improve/<short-slug>`.
- Surgical scope. Touch only files your improvement requires.
- Match surrounding style exactly.

## Step 4: verify, the full local gate

Run every one of these from the repo root with the venv active. All must pass:

```
cargo test --workspace
cargo fmt --all --check
cargo clippy --workspace -- -D warnings
ruff check .
ruff format --check .
mypy furl_ctx
python -m pytest tests/ -q
python -m verify.run
python -m benchmarks.run_bench --out "$RUNNER_TEMP_DIR_OR_TMP/bench-now"
python -m benchmarks.compare_baseline --baseline benchmarks/baseline_results.json --candidate <bench-now>/baseline_results.json
```

Expectations:

- pytest: 0 failed. Skips are fine.
- `verify.run` counters: `degradations=6 hash_failures=0 silent_loss=0
  cache_prefix_violations=0`. If your change legitimately LOWERS degradations,
  update the pinned expectation in `.github/workflows/perf.yml` in the same PR
  and celebrate it in the body. Raising any counter is a hard stop: revert.
- `compare_baseline` exit 0. If your change intentionally improves compression
  and shifts benchmark numbers, refresh the committed baseline in the same PR:
  `python -m benchmarks.run_bench --out benchmarks` and explain the delta.
- If the change is test-only, additionally red-proof it: revert the relevant
  production logic in a scratch copy and show your new test fails there.

## Step 5: ledger and PR

1. Append one row to `docs/audits/IMPROVEMENT-LEDGER.md` in the same commit
   series: date, area, files, one-line result, PR number placeholder filled
   after creation.
2. Conventional commit messages. Body lines hard-wrapped under 100 chars.
3. Open the PR with `gh pr create`. The body must contain: the problem, the
   before and after evidence, the full gate summary lines, risks, and what you
   deliberately did not do. Do not use em-dashes in prose.
4. Confirm CI starts, then stop. Do not wait to merge. Do not merge.

## Failure handling

- If the gate fails and the cause is your change: fix or revert. Never ship
  around a red gate.
- If the gate fails for a pre-existing reason unrelated to your change:
  document it precisely in the ledger candidate list and in your PR body if
  you still ship an unrelated improvement. A pre-existing failure is itself a
  top candidate for tomorrow.
- If you finish with nothing shippable, still append a ledger row: what you
  tried, why it did not hold up. An honest no-ship day beats a fake
  improvement. Never invent value.
