---
name: role-upgrade
description: End-to-end upgrade of one andrewrothstein/ansible-* role to a new upstream version (bump version, securely regenerate checksums, test, commit, PR/push, tag, ansible-galaxy import). Use for "upgrade ansible-X", "bump X to the brew version", "update role X". Pass the role name and optionally a target version.
---

# role-upgrade `<name> [version]`

Resolve paths and facts per `${CLAUDE_PLUGIN_ROOT}/skills/role-upgrade/LAYOUT.md` (layout-independent; read it first).
`<name>`, `<name>_ver` and `<name>_checksums` below are shorthand: use the role's real version/checksum var names from `defaults/main.yml` (see `LAYOUT.md`), which need not match the repo or role name.
Companion skills: `role-outdated` (discovery), `role-checksums` (checksum generation, security rules live there).

## Confirmation gates

Do the local steps freely. **Stop and ask before each outward-facing step**: `git push`, tag push, `ansible-galaxy role import`, opening a PR. Approval for one role/step does not carry to the next. If the user has said "go ahead through galaxy import" for this run, proceed, but still never force-push. **Always use a branch and a PR; never merge to, or push to, the default branch**, and never merge the PR (the user merges). Pushing the feature branch and `gh pr create` are the only publish actions.

## Steps

1. **Preflight**: `git status` clean, on default branch, `git pull --ff-only`. If dirty or diverged, stop and report.
2. **Target version**: given arg, else `brew info --json=v2 <formula>` stable (honour `.brew-name`). Compare with `<name>_ver` in `defaults/main.yml`; if not newer, stop. Read upstream release notes (`gh release view v<ver> -R <owner>/<repo>`) for asset renames, dropped platforms, or changed archive layout/checksum file names; these break `vars/main.yml` and the script.
3. **Branch**: `git checkout -b <name>-<ver>`.
4. **Bump** `<name>_ver` in `defaults/main.yml` (and `<name>_ver` anywhere else it is pinned, e.g. README example, `platform-matrix`/`vars`). Fix url/asset-name templates in `vars/main.yml` if upstream changed naming.
5. **Checksums**: follow `role-checksums` exactly, **including its backfill of every upstream stable version missing from `<name>_checksums` (e.g. a role going 0.2.87 -> 0.2.89 also gets 0.2.88)**, including the trust level and independent spot-check. Do not continue past a failed or unexplained mismatch.
6. **Housekeeping if needed**: `meta/requirements.yml` dependency versions (e.g. `andrewrothstein.unarchivedeps`) only when the user asks or a test fails; do not opportunistically refactor.
7. **Test** per the Tests section of `LAYOUT.md`: the `dagger ... test-role` call (via the user's Taskfile default task only if found), against the working tree, before committing. Also try other `OS`/`OS_VER`/`PLATFORMS` combos that `meta/main.yml` or `platform-matrix-v1.json` claim to support, at least one arm64 or non-debian one when the upgrade touched platform handling. If `dagger`/a container runtime is missing, stop and say so instead of skipping. Run `yamllint .` and `ansible-lint` if configured. If tests fail, fix or stop and report with output; never commit a failing upgrade as success.
8. **Commit**: message exactly `<name>:<ver>` (existing convention), stage only the files changed, add the Co-Authored-By trailer from the session's attribution reminder. Review `git diff --stat` first; unexpected files mean stop.
9. **Publish**: `git push -u origin <name>-<ver>` and `gh pr create --base <default branch>`; leave the local checkout on the feature branch. PR body: old -> new version, checksum trust level + cross-check result, test result, any platform changes, and the list of backfilled versions.
10. **Gate -> release** (only after the user confirms the PR is merged and CI is green; `git checkout <default> && git pull --ff-only` first, tag the merge commit): next tag = latest numeric tag with patch+1 (`git tag --sort=-v:refname | head`; tags look like `0.0.13`, `0.1.0`; compare with `sort -V`, and ask if the scheme looks different). Push the tag, then
    `ansible-galaxy role import --branch <tag> <owner> <repo> --role-name <role>` (see Galaxy in `LAYOUT.md`: prefer the `ansible-galaxy:role-import` task; the user supplies the token via `.env` or their secrets manager, never handle it yourself).
11. **Summary**: one line per step done/skipped, trust level, PR/tag URLs, anything needing the user.

## Batch mode

For several roles (e.g. from `role-outdated`), process **sequentially**, one role fully through step 8 before the next; collect all publish/release gates and present them together for a single approval list. A failed role is reported and skipped, never blocks the rest.

## Never

- Skip checksum verification, use `curl -k`, or pin a checksum you did not independently confirm.
- Merge a PR or push to the default branch.
- Rewrite history, force-push, or delete tags.
- Hand-edit a checksum value.
