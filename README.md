# ServiceOwners
![Service Owners Logo](logo.png)

**ServiceOwners** is a tiny, repo-native ownership layer for platform teams:

- A `SERVICEOWNERS` file maps **paths → services**
- An optional `services.yaml` maps **services → owners/contact/docs/runbooks**
- A GitHub Action comments on PRs with **impacted services** and **unmapped files**

It’s designed to be:
- **Boring & predictable** (last match wins, explicit config, easy to review in diffs)
- **Low-friction** (works with just `SERVICEOWNERS`; metadata is optional)
- **CI-first** (PR summaries + “fail on unmapped” enforcement)

---

## The 30-second setup

Create `SERVICEOWNERS` in repo root:

```txt
# pattern            service
apps/api/**          api
apps/web/**          web
infra/**             infra
docs/**              docs
```

Optional: create `services.yaml`:

```yaml
services:
  api:
    owners:
      - team: "@your-org/platform-api"
    contact:
      slack: "#api-help"
    docs: "docs/services/api.md"
    runbook: "docs/runbooks/api.md"
```

Install and run locally:

```bash
python -m pip install serviceowners
sowners lint
sowners impacted --diff origin/main...HEAD --show-files
```

---

## GitHub Action

Create `.github/workflows/serviceowners.yml`:

```yaml
name: serviceowners
on:
  pull_request:

jobs:
  ownership:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - uses: binbandit/serviceowners@v0.1.0
        with:
          token: ${{ github.token }}
          serviceowners_file: SERVICEOWNERS
          services_file: services.yaml
          comment: "true"
          fail_on_unmapped: "true"
          strict_lint: "false"
```

Notes:
- `fetch-depth: 0` is recommended so `git diff base...head` works reliably.
- `services.yaml` is optional; if missing, the action still reports impacted services.

---

## CLI

### `sowners who-owns PATH`

```bash
sowners who-owns apps/api/main.py
sowners who-owns apps/api/main.py --explain
sowners who-owns apps/api/main.py --format json
```

### `sowners impacted`

- Default: uses `git diff HEAD~1...HEAD`
- On PRs: prefer `--diff origin/main...HEAD`

```bash
sowners impacted --diff origin/main...HEAD
sowners impacted --diff origin/main...HEAD --show-files
sowners impacted --stdin < changed_files.txt
sowners impacted --format json
```

Exit codes:
- `0` ok
- `3` unmapped files found and `--fail-on-unmapped`

### `sowners lint`

Fast by default (no expensive repo scan):

```bash
sowners lint
sowners lint --strict
sowners lint --check-matches   # uses git ls-files (can be slow in huge repos)
sowners lint --check-overlaps  # expensive
```

### `sowners init` (bootstrap from CODEOWNERS)

```bash
sowners init --write
```

Looks for `CODEOWNERS` in:
- `CODEOWNERS`
- `.github/CODEOWNERS`
- `docs/CODEOWNERS`

---

## Pattern semantics (SERVICEOWNERS)

This file uses a simple glob syntax:

- `*` matches within a path segment (does **not** cross `/`)
- `**` matches across directories
- trailing `/` means “directory” (shorthand for `/**`)
- leading `/` anchors to repo root (otherwise still treated as repo-root relative)

Examples:
- `docs/*` matches `docs/a.md` but not `docs/a/b.md`
- `docs/**` matches `docs/a/b.md`
- `docs/` is treated as `docs/**`
- `*.md` matches any markdown file anywhere

Last match wins.

---

## Why this exists

`CODEOWNERS` maps files to *people/teams* for review assignment.

Platform teams also need a **service layer**:
- “what services changed in this PR?”
- “who is on call for this code?”
- “where’s the runbook?”

ServiceOwners gives you that layer without needing a portal.

---

## Contributing

```bash
python -m pip install -e ".[dev]"
pytest -q
```

---

## License

MIT.
