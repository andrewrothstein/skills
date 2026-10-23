---
name: role-outdated
description: Find which andrewrothstein/ansible-* roles are behind the upstream version Homebrew tracks. Use when asked "what roles are out of date", "which roles need upgrading", or before batch-upgrading roles. Read-only.
---

# role-outdated

Report roles whose pinned version lags Homebrew. **Read-only: never edits, commits, or pushes.**

Resolve paths and facts per `${CLAUDE_PLUGIN_ROOT}/skills/role-upgrade/LAYOUT.md` (layout-independent; read it first). Roles = the role repos found per that file (repo name, role name, var prefix and brew formula can all differ).

## Steps

1. `brew update` (once), then get the current stable versions:
   `brew info --json=v2 <formula...>` -> `.formulae[].versions.stable` (also check `.casks[]` when no formula matches).
2. For each role dir (or the ones the user named):
   - Identify role, repo, version var and brew formula per `LAYOUT.md` (names differ; honour `.brew-name`, do not assume formula == role name). Skip roles with no resolvable formula as "unmapped".
   - Current version: first match of `^<name>_ver:` in `defaults/main.yml` (fall back to `grep -E '^[a-z0-9_]+_ver:'`; if there are several, e.g. bazel/docker_binaries, report all).
   - Skip roles with no brew formula and list them separately as "unmapped" so the user can add `.brew-name` or handle them by another source (GitHub releases via `gh api repos/<o>/<r>/releases/latest`).
3. Compare with `sort -V`. Brew may be ahead of or behind upstream; if brew's version looks stale vs the latest GitHub release, say so.
4. Output a table: role | pinned | brew | status (behind / current / unmapped / ahead). Sort behind roles first. Also note roles with uncommitted changes or not on the default branch (`git status --porcelain`, `git branch --show-current`).

Offer to run the `role-upgrade` skill (`<name>`) for the behind roles. Do not start upgrading without being asked.
