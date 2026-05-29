# Production Boundary Guide

EGM is currently an alpha Python library for local, evidence-gated graph memory.
It is not a hosted service, not a distributed database, and not a full agent
platform. This guide defines what is safe to rely on today and what remains
planned engineering work.

## Supported Shape Today

- One EGM workspace is one local directory.
- The workspace contains `egm.db`, `refs/*.md`, and `offload/offload.jsonl`.
- SQLite is the primary store.
- Raw evidence is kept as drill-downable files under `refs/`.
- Audit rows are written for gate checks, fact commits, invalidations, task
  graph mutations, offload records, and long-term memory writes.
- The recommended runtime pattern is a single agent process or one explicit
  writer coordinating access to a workspace.

## Not A Production Platform Yet

Do not treat the current release as:

- a multi-writer shared service;
- a multi-tenant memory platform;
- a compliance archive with retention guarantees;
- a distributed workflow engine;
- a vector database;
- a replacement for external secret management;
- an enforced full-DAG database.

The current graph model is DAG-style. Self-loop and cross-task task edges are
rejected, but multi-node cycle enforcement is planned work.

## SQLite Boundaries

SQLite is the right default for a local library, but it has clear boundaries.

Use it for:

- developer workspaces;
- local agents;
- deterministic tests;
- single-writer prototypes;
- evidence and audit trails that fit on one machine.

Be careful with:

- concurrent writers;
- long-running benchmark jobs that share a workspace;
- network filesystems;
- very large refs or offload files;
- production processes that need zero-downtime schema migration.

EGM enables SQLite WAL mode and a 5000 ms busy timeout on workspace
connections. This improves the local single-writer / many-reader shape, but it
is not a multi-writer guarantee. Coordinate writes at the application layer.
Avoid sharing one writable workspace across unrelated agent processes until the
concurrency test suite is broader.

## Backup And Restore

Back up the whole workspace directory, not only the SQLite file:

- `egm.db`
- `refs/`
- `offload/`

The database points to evidence files by relative paths, so a database-only
backup can preserve fact rows while losing the raw evidence needed for
drill-down and audit.

Recommended minimum backup process:

1. Stop the writer process or pause new writes.
2. Copy the complete workspace directory.
3. Verify that `egm.db`, `refs/`, and `offload/` are present.
4. Run `egm inspect <workspace>` against the restored copy.
5. Export recent audit rows with `egm export-audit <workspace> --format json`.

## Migration Policy

The current code has a versioned migration runner skeleton and a v1 migration
for workspaces created before `Task.current_state`. This is better than a loose
collection of ad hoc column checks, but it is not a mature migration system yet.
Future schema changes still need old-workspace fixtures, rollback notes, and
release-specific migration documentation.

Until that fuller migration discipline lands:

- keep backups before upgrading EGM;
- test upgrades against a copy of the workspace;
- do not run automatic upgrades against the only copy of important data;
- record the EGM package version used to create long-lived workspaces.

## Audit Export

Use the CLI for workspace review:

```powershell
egm inspect .egm
egm audit .egm --limit 20
egm export-audit .egm --format json
egm export-audit .egm --format md --task-id refund-123
egm export-audit .egm --format json --fact-id fact_...
egm export-audit .egm --format json --evidence-id ev_...
```

`export-audit` is intended for handoff, debugging, and review. It is not yet a
retention system or a signed compliance export.

## Secrets

EGM examples and benchmark adapters may call external model providers. Keep API
keys outside the repository:

- shell environment variables;
- local `.env` files ignored by Git;
- CI or cloud secret managers.

Before publishing benchmark or example changes, run:

```powershell
python scripts/scan_secrets.py
```

The repository scanner is a guardrail, not a replacement for GitHub secret
scanning or a dedicated enterprise scanner.

## Schema Review

Treat domain schemas as policy. A schema controls which evidence types, claim
types, source systems, freshness windows, and state gates are trusted.

Before using a schema in a business workflow:

1. List all high-risk claim types.
2. Define required evidence for each claim type.
3. Restrict source systems for high-risk evidence.
4. Set stale and expired windows where time matters.
5. Add state gates for DONE or other irreversible transitions.
6. Run a rejected-path demo and confirm the suggested action is useful.
7. Keep the schema under version control.

## Operational Checklist

- Use one workspace per agent/project boundary.
- Keep raw evidence small enough to inspect.
- Keep API keys out of examples and reports.
- Run tests and deterministic benchmarks before release.
- Run `egm inspect` before and after major workflow changes.
- Export audit rows before deleting or archiving a workspace.
- Do not claim full enterprise concurrency or enforced DAGs until the planned
  hardening work lands.
