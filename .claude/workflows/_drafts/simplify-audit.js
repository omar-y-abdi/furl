// ---------------------------------------------------------------------------
// simplify-audit  —  lazy-dev over-engineering audit for the Headroom repo
//
// REPORT-ONLY. Every agent is read-only (agentType:'Explore' = no Edit/Write/
// NotebookEdit) and is told never to run git/maturin/write. The synth agent
// RETURNS markdown; the orchestrator does the single additive write of
// lazy-dev-AUDIT.md. Nothing in this workflow mutates the repo.
//
// Shape: pipeline(areas -> audit -> selective adversarial verify) then a synth
// barrier that ranks biggest-SAFE-cut-first. Verify only fires on high-impact
// `delete` claims (the irreversible-if-wrong ones); cheap shrink/stdlib findings
// pass through. Coupling is RE-DERIVED by agents (4 vectors) — the prior scout
// below is a hypothesis to confirm/update, not trusted ground truth.
//
// RUN:    Workflow({ scriptPath: '<this file>', args: { branch, head } })
// SAVE:   wf_lib.py save <this file> --group cleanup
// ---------------------------------------------------------------------------

export const meta = {
  name: 'simplify-audit',
  description: 'Lazy-dev over-engineering audit of the Headroom codebase: per-area reachability + complexity scan, adversarially verify the big delete claims, rank biggest-safe-cut-first. Report-only.',
  whenToUse: 'Re-audit the Headroom repo for simplification: dead/vestigial modules, single-impl abstractions, hand-rolled stdlib, infra cruft. Produces a ranked cut-list; applies nothing.',
  phases: [
    { title: 'Audit', detail: 'one read-only auditor per area' },
    { title: 'Verify', detail: 'independently refute each big delete claim' },
    { title: 'Synthesize', detail: 'dedup + rank biggest-safe-cut-first' },
  ],
}

// --- read-only mandate prepended to every agent prompt -----------------------
const READONLY =
  'You are a READ-ONLY auditor. Use only Read/Grep/Glob and read-only shell ' +
  '(rg, grep, wc, find, sed -n, cat). NEVER run git (no checkout/add/commit/reset/ ' +
  'switch/branch/stash), NEVER run maturin/pip/cargo build, NEVER Edit/Write any ' +
  'file. Exclude these paths from all scans: target/, .venv, .venv-eval, ' +
  '.sccache/, .claude/worktrees/, *.so, *.gif, *.png, node_modules/, .git/. ' +
  'Repo root: /Users/k/dev/headroom (branch verify/phase2-audit-report). ' +
  'Your final output is DATA for a synthesizer, not a human message.'

// --- lazy-dev tag vocabulary -------------------------------------------------
const TAGS =
  'TAGS: delete=dead/vestigial code or speculative feature (replacement: nothing); ' +
  'stdlib=hand-rolled logic the stdlib ships (name the function); ' +
  'native=dependency doing what the platform/an installed dep already does; ' +
  'yagni=abstraction with one impl, factory for one product, config nobody sets, ' +
  'wrapper that only delegates, file exporting one thing; ' +
  'shrink=same behavior, fewer lines. ' +
  'Do NOT flag: the hard invariants (CCR recovery, prompt-cache ordering, Py<->Rust ' +
  'hash parity), tests/asserts that guard real logic, or calibration knobs.'

// --- coupling vectors the reachability auditors MUST check (advisor #3) -------
const COUPLING =
  'To call a module dead/vestigial you MUST check ALL FOUR coupling vectors and ' +
  'report what you found for each: (1) static `import X` / `from X import`; ' +
  '(2) lazy/deferred imports INSIDE functions; (3) dynamic imports ' +
  '(importlib.import_module, __import__, string module names) and headroom/__init__.py ' +
  '+ headroom/transforms,cache,models,providers __init__ lazy re-export tables; ' +
  '(4) pyproject.toml entry_points / console_scripts / [project.scripts] / deps. ' +
  'Then classify reachability from the PUBLIC API `compress()` (entry: ' +
  'headroom/compress.py -> headroom/pipeline.py loads transforms via entry_points): ' +
  'LIVE = exercised by a normal compress() call; VESTIGIAL = import exists but only ' +
  'in a dead/guarded branch never hit by compress() (e.g. proxy interceptor only ' +
  'loads if a proxy is configured); DEAD = no referrer at all. ' +
  'A VESTIGIAL/DEAD dir is cuttable but name the exact untangle (which keep-set ' +
  'lazy-import to drop first). A LIVE dir is NOT a safe cut.'

// --- PRIOR SCOUT (hypothesis — confirm or correct it; may be stale) ----------
const SCOUT =
  'PRIOR SCOUT (orchestrator grep, verify independently): keep-set imports the ' +
  'supposedly-amputated bloat, so naive "rm dead dir" is WRONG. Findings to confirm: ' +
  'proxy(3894 LOC) <- transforms/pipeline.py (lazy, line ~115), transforms/' +
  'compression_policy.py, ccr/mcp_server.py, ccr/response_handler.py. ' +
  'tokenizers(1816) <- transforms/pipeline.py (lazy, line ~160). ' +
  'models(596) <- config.py, cache/*. providers(172) <- tokenizer.py. ' +
  'storage <- cache/backends. hooks.py <- compress.py. binaries.py <- proxy only. ' +
  'relevance(1017) & shared_context: 0 static refs but LAZILY re-exported by ' +
  'headroom/__init__.py. observability/telemetry(4001)/integrations/onnx_runtime/' +
  'component_tracker: appear unreferenced (telemetry only referenced by proxy/models ' +
  'internally) — the cleanest cut candidates IF proxy itself is vestigial.'

const FINDINGS = {
  type: 'object',
  properties: { findings: { type: 'array', items: {
    type: 'object',
    properties: {
      tag: { type: 'string', enum: ['delete', 'stdlib', 'native', 'yagni', 'shrink'] },
      title: { type: 'string' },
      paths: { type: 'string', description: 'file(s)/dir/glob, comma-separated' },
      est_loc_cut: { type: 'number' },
      replacement: { type: 'string', description: '"nothing" for delete; else the leaner form' },
      reachability: { type: 'string', enum: ['live', 'vestigial', 'dead', 'na'] },
      safe_to_cut_now: { type: 'boolean' },
      untangle_needed: { type: 'string', description: 'what must change first if not safe now; "" if safe' },
      confidence: { type: 'number' },
    },
    required: ['tag', 'title', 'paths', 'est_loc_cut', 'replacement', 'reachability', 'safe_to_cut_now'],
  } } },
  required: ['findings'],
}

const VERDICT = {
  type: 'object',
  properties: {
    verdict: { type: 'string', enum: ['confirmed', 'refuted', 'uncertain'] },
    blockers: { type: 'string', description: 'coupling/usage that blocks the cut, or "" if none' },
    reasoning: { type: 'string' },
    confidence: { type: 'number' },
  },
  required: ['verdict', 'reasoning'],
}

// --- the audit areas (weighted where cuts actually live; Rust core = light) --
const AREAS = [
  { key: 'entangle-proxy', focus:
    'REACHABILITY of headroom/proxy/ (3894 LOC) and headroom/binaries.py. Is proxy ' +
    'reached by a normal compress() call, or only via guarded/lazy imports in ' +
    'transforms/pipeline.py + compression_policy.py + ccr/*? Trace each referrer. ' +
    'If vestigial, the cut frees ~4k LOC + binaries.py — name the untangle.' },
  { key: 'entangle-telemetry', focus:
    'REACHABILITY of headroom/telemetry/(4001) + observability/ + integrations/ + ' +
    'onnx_runtime.py + component_tracker.py. These look unreferenced except from ' +
    'proxy/models internals. Confirm: are they dead, or kept alive only by other ' +
    'bloat? The cleanest large cut if proxy/models also go.' },
  { key: 'entangle-models-tok', focus:
    'REACHABILITY of headroom/models/(596) + providers/(172) + tokenizers/(1816) + ' +
    'relevance/(1017) + storage/ + shared_context.py. These are coupled to keep-set ' +
    '(config.py, tokenizer.py, cache/, transforms/pipeline.py) AND lazily re-exported. ' +
    'For each: live, vestigial, or a dead public-API export? Name the untangle.' },
  { key: 'python-core', focus:
    'OVER-ENGINEERING inside the keep-set: headroom/transforms/*.py, compress.py, ' +
    'pipeline.py, parser.py, tokenizer.py, config.py, exceptions.py, utils.py, paths.py. ' +
    'Hunt: single-impl interfaces/ABCs, factories for one product, wrappers that only ' +
    'delegate, hand-rolled stdlib, dead config flags, files exporting one thing. NOT the ' +
    'dead-dir question (other agents own that).' },
  { key: 'ccr-cache', focus:
    'TRIM headroom/ccr/ + headroom/cache/ (handoff flagged "4k LOC feels heavy"). ' +
    'Internal over-engineering and orchestration cruft ONLY — do NOT touch the CCR ' +
    'recovery invariant or hash-parity logic. Look for dead backends, unused cache ' +
    'layers, speculative config, delegating wrappers.' },
  { key: 'rust-core', focus:
    'LIGHT pass on crates/headroom-core + crates/headroom-py. This is the hardened ' +
    'valuable core with hard invariants — do NOT shrink-nitpick it. Report ONLY: ' +
    'genuinely-dead features, unused feature-flag code paths (magika/embeddings/redis ' +
    'if never enabled), unreferenced modules/fns, dead legacy enums (e.g. LosslessFirst ' +
    'if unused). High bar; few findings expected.' },
  { key: 'tests', focus:
    'tests/ (12.8k LOC, 42 files): tests for DELETED/dead modules (proxy/telemetry/etc.), ' +
    'duplicate/overlapping suites, and scaffolding for features that no longer exist. ' +
    'Keep every test that guards a live invariant.' },
  { key: 'bench-verify', focus:
    'benchmarks/ vs verify/: two separate benchmarking systems (run_bench.py + verify/' +
    'run.py + measure.py). Quantify overlap/duplication and whether one subsumes the ' +
    'other. Also claude_analysis_ttl.py at repo root — stray?' },
  { key: 'toplevel', focus:
    'Repo-root cruft + manifests: docker/, Dockerfile, docker-compose.yml, docker-bake.hcl, ' +
    'mkdocs.yml, wiki/, sql/, *.gif, *.png, ENTERPRISE.md, TESTING-copilot-subscription.md, ' +
    'REALIGNMENT, PR.md, codecov.yml, deny.toml, Makefile, llms.txt, and marketing docs. ' +
    'Also pyproject.toml + Cargo.toml: deps/extras/entry_points for amputated modules. ' +
    'What is dead weight for a lean compression library vs load-bearing?' },
]

const auditPrompt = (a) =>
  `${READONLY}\n\n${TAGS}\n\n${COUPLING}\n\n${SCOUT}\n\n` +
  `YOUR AREA: ${a.focus}\n\n` +
  `Read the actual files (don't guess). Return findings. For module-deletion findings, ` +
  `reachability + safe_to_cut_now + untangle_needed are REQUIRED and must reflect the ` +
  `four-vector check. est_loc_cut = lines actually removed. Be a senior dev: real cuts ` +
  `only, no nitpicks, no false "safe to delete".`

const verifyPrompt = (a, f) =>
  `${READONLY}\n\nYou are an adversarial verifier. A prior auditor claims this is SAFE ` +
  `to DELETE NOW. Try to REFUTE it by finding ANY live coupling, re-checking ALL FOUR ` +
  `vectors yourself:\n${COUPLING}\n\n` +
  `CLAIM (${a.key}): ${f.title}\nPaths: ${f.paths}\nClaimed reachability: ${f.reachability}\n` +
  `Claimed est_loc_cut: ${f.est_loc_cut}\nUntangle named: ${f.untangle_needed || '(none)'}\n\n` +
  `Find a real referrer/usage -> verdict=refuted with the blocker. Conclusively unused ` +
  `via all four vectors -> confirmed. Can't tell -> uncertain. Default to uncertain over ` +
  `a confident wrong "confirmed".`

phase('Audit')
const reviewed = await pipeline(
  AREAS,
  (a) => agent(auditPrompt(a), { label: `audit:${a.key}`, phase: 'Audit', schema: FINDINGS, agentType: 'Explore' }),
  (review, a) => parallel(
    (((review && review.findings) || [])).map(f => () => {
      const needsVerify = f.tag === 'delete' && (f.est_loc_cut || 0) >= 300 && f.safe_to_cut_now === true
      if (!needsVerify) return Promise.resolve({ area: a.key, ...f, verdict: 'not_verified', reasoning: '' })
      return agent(verifyPrompt(a, f), { label: `verify:${a.key}`, phase: 'Verify', schema: VERDICT, agentType: 'Explore' })
        .then(v => ({ area: a.key, ...f, ...v }))
    })
  )
)

const all = reviewed.filter(Boolean).flat().filter(Boolean)
const refuted = all.filter(v => v.verdict === 'refuted')
const verifiedSafe = all.filter(v => v.tag === 'delete' && v.safe_to_cut_now === true && v.verdict !== 'refuted')
log(`Audit: ${all.length} findings across ${AREAS.length} areas. ` +
    `${verifiedSafe.length} delete-claims survived verification, ${refuted.length} refuted.`)

phase('Synthesize')
const synthPrompt =
  `${READONLY}\n\nYou are a lazy senior dev writing the simplification audit. Below are ` +
  `${all.length} findings (JSON) from ${AREAS.length} parallel auditors; big delete-claims ` +
  `carry an adversarial verdict (refuted/confirmed/uncertain/not_verified) with blockers.\n\n` +
  `Write lazy-dev-AUDIT.md as MARKDOWN. Rules:\n` +
  `- DROP any finding whose verdict is "refuted" (coupling proved it live) — note them in a ` +
  `short "Refuted / not safe" appendix so we don't re-litigate.\n` +
  `- Dedup overlapping findings across areas.\n` +
  `- RANK biggest-cut-first by est_loc_cut, but group into 3 tiers:\n` +
  `  TIER 1 — SAFE TO CUT NOW (dead/vestigial, verified, no untangle): a table ` +
  `[rank | what | paths | ~LOC | tag | evidence].\n` +
  `  TIER 2 — CUT AFTER UNTANGLE (vestigial but a keep-set lazy-import must drop first): ` +
  `table + the exact untangle step per row.\n` +
  `  TIER 3 — INTERNAL SHRINK (yagni/stdlib/native/shrink inside the keep-set): table.\n` +
  `- Top of file: a 4-line executive summary with total ~LOC cuttable now (Tier 1) vs ` +
  `after-untangle (Tier 2), and the single biggest lever.\n` +
  `- Honest: if the "amputated" bloat is still load-bearing, say so plainly.\n` +
  `- This is REPORT-ONLY. End with a one-line note that applying is a separate gated step.\n\n` +
  `FINDINGS JSON:\n${JSON.stringify(all)}`

const report = await agent(synthPrompt, { label: 'synthesize', phase: 'Synthesize', agentType: 'Explore' })

return {
  branch: 'verify/phase2-audit-report',
  areaCount: AREAS.length,
  findingCount: all.length,
  verifiedSafeCount: verifiedSafe.length,
  refutedCount: refuted.length,
  report,
  findings: all,
}
