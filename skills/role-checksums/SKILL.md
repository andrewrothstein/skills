---
name: role-checksums
description: Securely generate or update the checksum YAML for an ansible-* role (the dl-checksum.sh / dl-checksums.sh / update-checksums.sh scripts and the `<name>_checksums` block in defaults/main.yml) for a new upstream version. Use when adding a version's checksums to a role or writing a checksum script for a role that lacks one.
---

# role-checksums

Produce the `<name>_checksums` entry for one new version of one role, with provenance, and fail closed.
Resolve paths and facts per `${CLAUDE_PLUGIN_ROOT}/skills/role-upgrade/LAYOUT.md` (layout-independent; read it first). Work in the role dir. Existing script names in use: `dl-checksum.sh` (upstream checksum file, preferred), `dl-checksums.sh` (hash downloaded artifacts), `update-checksums.sh` (per-asset `.sha256` files). Repo task `update-checksums` in `tasks/ansible-test-role.yml` runs whichever exist; scripts that print YAML are appended to `defaults/main.yml`, those with an inline `>>` write their own file under `defaults/main/`.
`<name>`, `<name>_ver` and `<name>_checksums` below are shorthand: use the role's real version/checksum var names from `defaults/main.yml` (see `LAYOUT.md`), which need not match the repo or role name.

## Trust order (use the highest available, say which one was used)

1. Upstream-published checksum file **whose signature you verified** (cosign/minisign/gpg/sigstore attestation, `gh attestation verify`).
2. Upstream-published checksum file over HTTPS, **cross-checked** against a second independent source: the GitHub release asset `digest` field (`gh api repos/<o>/<r>/releases/tags/<tag> --jq '.assets[]|{name,digest}'`) or `brew`'s formula sha256 for the same asset when it is the same file.
3. Hash of artifacts you downloaded yourself (trust-on-first-use). Allowed, but flag it clearly in the summary and PR body as TOFU. Download **fresh** every time.

## Script conventions (match the existing scripts)

- Shebang `#!/usr/bin/env sh` (or bash if already bash), `set -e`; default version arg `dl_ver ${1:-X.Y.Z}`; bump that default on each upgrade.
- Emit YAML to stdout in this shape, one `# url` comment above each value:
  ```
    # <checksum-file-url>
    'X.Y.Z':
      # <asset-url>
      <platform>: sha256:<64 hex>
  ```
- Platform list = what the role's `vars/main.yml` / `tasks/` can actually construct (`<name>_platform`, `_arch_map`). Add new upstream platforms only if the role can use them; drop none silently.

## Required hardening (fix these in any script you touch)

- Never trust a cached file: write downloads into `mktemp -d` (trap cleanup), not `~/Downloads`, or delete the cached file first.
- `curl -fsSL --proto '=https' --tlsv1.2`. Never `-k`.
- Quote every variable. Match the filename exactly (`grep -F -- " $file$"`-style, not a loose substring that can match `.sig`, `.sbom`, or a longer name).
- Fail if a lookup yields empty or not `^[0-9a-f]{64}$` (a missing grep must abort, not print `sha256:`). No stray unset variables (an old argo script tests `$csums` but sets `$lsums`).
- Do not execute or `source` anything downloaded.

## Backfill every missing version (always)

Never add only the target version. Before generating, list upstream stable releases (`gh release list -R <owner>/<repo> --exclude-pre-releases --limit 200 --json tagName`, or the project's own release feed) and diff against the versions already keyed in `<name>_checksums` (`grep -oE "^  '?[0-9][^':]*'?:"`). Every upstream stable version from the oldest tracked one up to the target that lacks an entry (the target itself, versions skipped between the old pin and the target, and older holes) gets an entry. Run the script once per missing version, validate each exactly as below, and insert entries in version order (`sort -V`), not just appended. Ignore prereleases/RCs. Versions older than the oldest tracked one are not backfilled unless the user asks. Report the list of backfilled versions; if a release lacks the expected assets or checksum file, report it as skipped and why. Only the target is written to `<name>_ver`; backfilled versions just get checksums.

Also treat an existing entry as missing if it is invalid: empty `sha256:`, not 64 hex, or duplicate platform keys; regenerate and flag it.

## Steps

1. Identify the role's `<name>_ver` and mirror URL from `defaults/main.yml` and `vars/main.yml`; read the existing script, if any, and the latest existing entry in `<name>_checksums`.
2. Locate the upstream release assets and the highest-trust verification available (see above). If the role has no script, create `dl-checksum.sh` (if upstream has a checksum file) or `dl-checksums.sh` (otherwise), `chmod +x`.
3. Bump the script's default version to the target, run it, and capture stdout to a temp file. Do not append yet.
4. **Validate** the output: every platform line has 64-hex, no duplicate platforms, platform set equals the previous version's set (explain any difference), every URL returns 200 (`curl -sIfL`). Spot-check at least one platform by independently downloading the asset and running `sha256sum`/`shasum -a 256`.
5. Insert the entry into `defaults/main.yml` under `<name>_checksums` (newest version appended after the existing ones, preserving the file's style), or into the specific `defaults/main/*_checksums.yml`. Run `yamllint .` if `.yamllint.yaml` exists.
6. Report: trust level used, cross-check result, platforms added/missing. Anything at level 3 or any mismatch must be called out, not buried.

Never commit or push from this skill; the `role-upgrade` skill owns that.
