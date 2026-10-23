# Locating the role and tools (layout-independent)

Shared by role-outdated, role-checksums, role-upgrade, role-backfill. **Never assume a checkout layout.** Resolve everything from facts, and say what you resolved.

## Names: repo, role, var prefix, brew formula are four different things
Do not derive one from another by string surgery. Repos were named `ansible-<x>`; Ansible later required role names to be valid Python module names (no `-`), so the role name was changed in `meta/main.yml` while the repo kept its name, and some repos were named differently from the start. Known shapes: `ansible-act` -> role `act`; `ansible-docker_binaries` (repo has `_` too); `ansible-unarchivedeps` (dash dropped entirely); `ansible_restic` (repo prefix is `ansible_`, not `ansible-`; matches the `infix` var in the user's task files). Repos may also be quoted/`.git`-suffixed in remotes.

| Thing | Source of truth |
|---|---|
| repo (dir/remote) | `git remote get-url origin`, strip `.git` and path; the dir name is only a hint |
| role name (galaxy name, `andrewrothstein.<role>` in requirements) | `galaxy_info.role_name` in `meta/main.yml` (strip quotes); if absent, ask |
| var prefix / version var | the actual keys in `defaults/main.yml` (`grep -E '^[a-z0-9_]+_ver:'`); usually `<role>_ver` but not always (`kafka_scala_ver`, roles with several or none). Pick the one used in the role's download URL in `vars/main.yml`; if ambiguous or none, stop and ask |
| brew formula | `.brew-name` in the role dir, else the role name with `_` -> `-`, else the upstream project name; verify with `brew info`. Never assume it equals the role or repo name |
| upstream repo | role's mirror var / script `MIRROR=`, not the role name |
| galaxy import | `<owner> <repo>` from the remote (repo, not role) and `--role-name <role>` from meta |

Optional per-role override file `.role-map.yml` in the role dir (only create it when asked): `role_name`, `ver_var`, `brew`, `upstream`. If present it wins over inference.

## Role dir (first match wins)
1. An explicit path argument (a repo dir, or `<owner>/<repo>`).
2. The cwd's repo, if `git rev-parse --show-toplevel` succeeds and it looks like a role (has `meta/main.yml` with `galaxy_info` and `tasks/main.yml`). Use the top-level, not the cwd (it may be a subdirectory or a worktree).
3. A name given as `<name>`: look under `$ROLES_DIR` (and siblings of the cwd's repo) for a repo whose **role name** (meta) or **repo name** equals it, trying `ansible-<name>`, `ansible_<name>`, `ansible-<name with _ as ->`, then a scan of `meta/main.yml` role_names. Exactly one match -> use it; several or none -> list candidates and ask. If it exists on GitHub but is not cloned, offer to `git clone` it (ask first); the user's task `ansible-test-role:clone` takes `infix`.
4. Otherwise ask. Do not guess a path or `cd` somewhere you were not pointed at.

Sweeps: a role repo = any git repo under `$ROLES_DIR` (or the parent of the cwd's repo when it holds several) whose `meta/main.yml` has `galaxy_info`, regardless of prefix. Non-role repos (e.g. a bare `ansible` repo) lack that and are skipped. Report which clones were skipped and which GitHub repos are not cloned (`gh repo list <owner> --json name`).

Run commands with `git -C <role dir>` / subshell `cd`; do not rely on a persistent cwd (it can be reset between calls).

## Facts to derive, not hard-code
- **owner**: remote owner (also normally `galaxy_info.namespace`; if they differ, stop and ask).
- **default branch**: `git symbolic-ref --short refs/remotes/origin/HEAD` (fall back to `gh repo view --json defaultBranchRef`).
- **scripts**: whichever of `dl-checksum.sh|dl-checksums.sh|update-checksums.sh|dl-checksums.go` exist in the role dir.

## Tests
The contract is the dagger call, not the task file:
`dagger call --mod github.com/andrewrothstein/docker-ansible@develop test-role --os=<OS> --os-ver=<OS_VER> --role-dir=<role dir> --platforms=<PLATFORMS>` (defaults debian / bookworm / linux/amd64).
Prefer the user's Taskfile (`ansible-test-role.yml`) only if it is found: `$TASKS_DIR`, else a sibling `tasks/` repo next to the role dir; run with `ROLE_DIR=<role dir>`. If not found, run `dagger` directly. Same command either way. Needs `dagger` + a container runtime. Locally and in CI use the same call; in CI the role's own workflow (`.github/workflows/build.yml` -> docker-ansible `dagger-ansible-test-role.yml`) is the test, so do not duplicate it.

## Galaxy
Prefer the user's task: `task ansible-galaxy:role-import name=<role> branch=<tag>` (from the tasks repo: `$TASKS_DIR`, or a sibling `tasks/`). Its `Taskfile.yml` loads `.env` and `.env.local` (`dotenv`), and the task's `test-secrets` dep fails fast if `ANSIBLE_GALAXY_TOKEN` is empty. Without the tasks repo: `ansible-galaxy role import --branch <tag> <owner> <repo> --role-name <role>` with the token from the environment.

**Secrets are the user's to supply; do not assume how.** The tasks repo works with either a user-managed `.env` file or a secrets manager (the user's is Doppler, mounted as an ephemeral `.env`: `doppler run --mount .env -- task <task>`; documented in the tasks repo `CLAUDE.md`). So:
- Run the task as-is first; if `test-secrets` fails, tell the user the token is missing and offer the wrapper that fits what they use (`doppler run --mount .env -- ...` if `doppler` is installed and the user says that is their setup; otherwise ask them to put it in their `.env` / environment).
- Never read, print, echo, `cat` or `grep -v`-print `.env`, `.env.local`, or the token; redact `--token` in any shown output (the task passes it as an argument, so it is briefly visible to `ps`).
- Never write the token to a file, commit message, PR body, or the conversation, and never create or edit `.env` for the user.
- A user's approval to run the import covers that import only.

## Environment
Do not depend on `~/Downloads`, `$HOME` layout, or the user's cwd. Temp files go in `mktemp -d`. If a required tool (`brew`, `gh`, `dagger`, `ansible-galaxy`, `yamllint`) is missing, say which step is skipped; never silently skip.
