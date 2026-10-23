---
name: role-backfill
description: Backfill and audit historical checksums for an andrewrothstein/ansible-* role without changing its pinned version: add older/missing upstream versions to `<name>_checksums`, and re-verify existing entries against upstream. Use for "backfill act", "fill in missing versions", "audit checksums for X", or sweeping many roles. Opens a branch + PR; never bumps `<name>_ver`.
---

# role-backfill `<name>|--all [--since <ver|date>] [--last <N>] [--audit-only]`

Companion to `role-upgrade` (which already backfills holes between the oldest tracked version and the target). This skill goes further: older history and verification of what is already there. It follows the trust rules, script hardening and validation in `role-checksums`; read that first.

Resolve paths and facts per `${CLAUDE_PLUGIN_ROOT}/skills/role-upgrade/LAYOUT.md` (layout-independent; read it first). Same publish policy as `role-upgrade`: **branch + PR only, never merge or push to the default branch, never force-push.** Stop and ask before pushing/opening the PR; approval does not carry from one role to the next.
`<name>`, `<name>_ver` and `<name>_checksums` below are shorthand: use the role's real version/checksum var names from `defaults/main.yml` (see `LAYOUT.md`), which need not match the repo or role name.

## Modes

1. **Fill** (default): add entries for upstream stable versions missing from `<name>_checksums`.
   - Range: holes inside the tracked range always; versions older than the oldest tracked only when asked (`--since <ver|date>` or `--last <N>` newest N releases). With no bound given, ask once before going below the oldest tracked version, suggesting a bound (the role's `meta/main.yml` and the repo's tag history show how far back it was ever supported).
   - Skip prereleases/RCs/drafts, and versions whose assets use a different naming/layout the role cannot construct (report them as skipped, do not invent mappings). Platforms the role cannot select (`<name>_arch_map`, `vars/main.yml`) are left out and listed.
2. **Audit** (always runs on existing entries, alone with `--audit-only`): re-derive each existing version's values from upstream the same way (trust order in `role-checksums`) and compare.
   - Classify each entry: `ok`, `mismatch` (value differs from upstream), `invalid` (empty, not `^[0-9a-f]{64}$`, duplicate key), `unverifiable` (release/assets deleted, no checksum source), `tofu-only`.
   - **A `mismatch` is a security signal, not a typo.** Do not overwrite it. Report it prominently (role, version, platform, old vs upstream value, whether the upstream release was re-uploaded/edited after publish via `gh api repos/<o>/<r>/releases/tags/<tag> --jq '{published_at,updated_at:.assets[].updated_at}'`) and leave the decision to the user. `invalid` entries may be regenerated and flagged.

## Steps (per role)

1. Preflight as in `role-upgrade` (clean tree, default branch, `git pull --ff-only`), then `git checkout -b <name>-backfill`.
2. Build the version list: upstream stable releases (`gh release list -R <o>/<r> --exclude-pre-releases --limit 500 --json tagName,publishedAt`) minus tracked versions, bounded as above. Show the list and count before generating.
3. Generate each missing version with the role's hardened script (one run per version, `dl_ver <ver>`; never edit the script's default version arg in a backfill commit unless it is empty), validate (64-hex, platform set vs the neighbouring versions and explain differences, URLs 200, one independent download spot-check per version, cross-check source). Rate-limit and back off on GitHub 403/429; prefer one `gh api` call per release over one per asset.
4. Insert entries in `sort -V` order within the existing structure and comment style; do not reorder or reformat existing entries. Check the file still parses (`python3 -c 'import yaml'` if available, else `ansible-inventory`/`yamllint`; say so if no linter exists).
5. Run the audit pass and include its table in the PR body.
6. Test per the Tests section of `LAYOUT.md`. A backfill changes no active version, so one default OS/arch is enough; add one of the newly backfilled versions as `<name>_ver` override only if the user asks to prove an old version still installs.
7. Commit: `<name>: backfill checksums <lowest>..<highest>` (one commit for fills, a separate commit for any regenerated `invalid` entries), with the session's Co-Authored-By trailer. Review `git diff --stat`; changes outside the checksum files mean stop.
8. **Gate -> publish**: push branch, `gh pr create`. PR body: versions added, versions skipped + why, platforms left out + why, trust level per version, audit table (esp. mismatches), test result.
9. No tag or Galaxy import: nothing user-visible changed unless the user asks for a release, in which case follow `role-upgrade` step 10 after merge.

## Sweep (`--all` or a list of roles)

Roles are independent: process sequentially, one fully through step 7 before the next, and collect all publish gates into one approval list. First pass = audit + dry count only (`role-outdated`-style table: role | tracked range | missing versions | invalid | mismatches | unverifiable) so the user can pick which roles to fill. A failure or `mismatch` in one role is reported and does not block the others. Roles without a checksum script or without a recognisable upstream are listed as unmapped, not guessed at.

## Never

- Overwrite a mismatching checksum, hand-edit a value, or "fix" one by trusting the new download blindly.
- Touch `<name>_ver`, tasks, vars or meta in a backfill PR.
- Use `curl -k` or cached downloads (see `role-checksums`).
- Merge, force-push, or delete tags/branches you did not create.
