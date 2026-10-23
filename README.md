# skills

Claude Code skills for maintaining the `andrewrothstein/ansible-*` roles. This repo is both a plugin and its own marketplace.

## Install

```
/plugin marketplace add andrewrothstein/skills
/plugin install andrewrothstein-skills@andrewrothstein-skills
```

On Claude Code 2.1.275 or later, in one step:

```
/plugin install andrewrothstein-skills --marketplace andrewrothstein/skills
```

From a shell: `claude plugin marketplace add andrewrothstein/skills`, then `claude plugin install andrewrothstein-skills@andrewrothstein-skills --scope user`.

Skills are namespaced by the plugin: `/andrewrothstein-skills:role-upgrade`, and so on.

## Updating

`plugin.json` pins a `version`, so a host only sees changes when that string is bumped. Update with `/plugin marketplace update andrewrothstein-skills`, then `/reload-plugins` (or start a new session).

## Skills

| Skill | What it does |
|---|---|
| `role-outdated` | Read-only: which roles lag the version Homebrew tracks. |
| `role-checksums` | Generate and verify checksum entries for a role, with a stated trust level. |
| `role-upgrade` | Upgrade one role end to end: bump, checksums (with backfill), test, commit, branch + PR, then tag and Galaxy import after merge. |
| `role-backfill` | Backfill and audit historical checksums without bumping the pinned version; branch + PR. |

`skills/role-upgrade/LAYOUT.md` is shared by all four. It says how to find a role, repo, version variable and brew formula without assuming a checkout layout, how to run the dagger test, and how to handle the Galaxy token (never read or print it).

## Conventions the skills follow

- Work on a branch and open a PR. Never merge or push to a default branch.
- Stop and ask before each outward-facing step (push, tag, Galaxy import).
- Checksums fail closed, and the trust level used is always reported.

## Development

`claude plugin validate .` checks the manifests. Validation does not test the skills' behaviour.
