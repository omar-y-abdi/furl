# Furl — Claude Code plugin

Bundles Furl's context compression into Claude Code as a single plugin:

- **MCP server** (`furl`) → the `furl_compress`, `furl_retrieve`, `furl_stats` tools.
- **PostToolUse hook** → automatically compresses large tool outputs before they
  enter context (fail-open; never breaks a tool call).
- **Skill** (`furl`) → explains how it works, the `<<ccr:HASH>>` retrieval flow, and
  how to tune or disable it.

## Install (2 commands)

**1 — Install Furl** into the same Python that Claude Code will run. Prebuilt
wheels ship on the GitHub Release, so this needs **no Rust toolchain** and picks
the right wheel for your platform automatically (macOS arm64/x86_64, Linux
arm64/x86_64):

```bash
pip install "furl-ctx[mcp]" --only-binary furl-ctx \
  --find-links https://github.com/omar-y-abdi/furl/releases/expanded_assets/v0.27.0
```

**2 — Add the plugin** from this repo (its root ships the marketplace manifest at
`.claude-plugin/marketplace.json`):

```
/plugin marketplace add /path/to/headroom
/plugin install furl@furl
```

Run those two `/plugin …` lines inside Claude Code (they are slash commands, not
shell commands). The first registers the repo root as a marketplace named `furl`
(which points at `./plugins/furl`); the second installs the `furl` plugin from it.
Restart the session (or re-enable the plugin) so the MCP server and hook load.

> **Installing from GitHub instead of a local clone:** once this repo's default
> branch carries the manifest, `/plugin marketplace add omar-y-abdi/furl` (the
> GitHub `owner/repo` shorthand) works directly — it reads
> `.claude-plugin/marketplace.json` from the default branch. Before that merge,
> use the local-path form above against your clone. Once Furl is on PyPI, step 1
> shortens to `pip install "furl-ctx[mcp]"`.

**Verify** it loaded: run `/plugin` (the `furl` plugin should be enabled) and ask
Claude to call `furl_stats` — it should return session stats from the `furl` MCP
server.

### Prerequisite detail (be honest about this)

Both the MCP server and the hook invoke **`python3` on your PATH** (they run
`python3 -m furl_ctx.ccr.mcp_server` and `import furl_ctx`). That interpreter must
be the one where you installed Furl in step 1. If you use a virtualenv or `pyenv`,
make sure the active `python3` resolves to it, or the MCP server won't start and the
hook will silently fail-open (do nothing) rather than error. Verify with `/mcp`
(the `furl` server should be listed) after the plugin loads.

## What each piece does

### MCP server (`.mcp.json`)

Registers one server, keyed `furl` (short on purpose — keeps generated tool names
like `mcp__furl__furl_compress` well under Claude Code's 64-char limit):

```json
{ "mcpServers": { "furl": {
  "command": "python3",
  "args": ["-m", "furl_ctx.ccr.mcp_server"],
  "env": { "FURL_CCR_BACKEND": "sqlite", "FURL_CCR_TTL_SECONDS": "86400" }
}}}
```

`FURL_CCR_BACKEND=sqlite` makes the CCR store durable at `~/.furl/ccr.sqlite3`, so
originals survive across processes and can be retrieved later.

### Compression hook (`hooks/hooks.json` + `hooks/compress_tool_output.py`)

A `PostToolUse` hook on external-output tools (`Bash`, `WebFetch`, `WebSearch`,
`Task`). Your own `Read`/`Grep`/`Glob` file access is deliberately left untouched by
default, so a later `Edit` still sees exact file bytes. For each result it:

1. Skips Furl's own tools and anything already carrying `<<ccr:` markers.
2. Skips outputs below `FURL_HOOK_MIN_CHARS` (default 2000).
3. Compresses the rest via `furl_ctx.compress(...)` and replaces the tool output
   **only if the result is genuinely smaller**.

It pins the **same** `FURL_CCR_BACKEND=sqlite` as the server, so markers it creates
are retrievable through `furl_retrieve`. It is **fail-open**: any error passes the
original output through unchanged (exit 0, no output), so a compression problem can
never break your tool call.

**Tuning / disabling** (env vars):

| Variable | Default | Effect |
|----------|---------|--------|
| `FURL_HOOK_ENABLED` | on | `0`/`false`/`off` disables the hook (MCP tools stay). |
| `FURL_HOOK_MIN_CHARS` | `2000` | Size threshold before compressing. |
| `FURL_HOOK_MODEL` | `claude-sonnet-4-5-20250929` | Model name for token counting. |

The full `FURL_*` reference is in the repo's top-level `README.md` → "Configuration".

### Skill (`skills/furl/SKILL.md`)

Auto-activates when you ask what Furl is doing, why output looks compressed, how to
retrieve originals, or how to tune/disable it.

## Structure

```
.claude-plugin/
└── marketplace.json         # repo-root marketplace → source ./plugins/furl
plugins/furl/
├── .claude-plugin/
│   └── plugin.json          # plugin manifest (name, version, skills)
├── .mcp.json                # registers the `furl` MCP server
├── hooks/
│   ├── hooks.json           # PostToolUse registration (auto-loaded)
│   └── compress_tool_output.py   # the fail-open compression hook
├── skills/
│   └── furl/
│       └── SKILL.md         # how-it-works skill
└── README.md
```
