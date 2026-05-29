# Changelog

All notable changes to Evidence-Gated Memory should be recorded here before a
PyPI release. This project follows semantic-versioning intent while it is still
alpha: patch releases may still adjust APIs, but any compatibility risk must be
called out explicitly.

## Unreleased

### Added

- Added PEP 561 package marker support with `py.typed`.
- Added `egm export-audit` for JSON and Markdown audit exports with filters for
  task, claim, fact, and evidence identifiers.
- Added a versioned SQLite migration runner skeleton with v1 migration coverage
  and future-schema rejection.
- Enabled SQLite WAL mode and a 5000 ms busy timeout for local workspaces.
- Added a generic agent-loop integration guide and runnable refund-loop demo.
- Added adapter metadata contract docs and reusable metadata helpers.
- Added long-term memory candidate-gate design documentation.
- Added the first L1 memory candidate gate implementation with source-span
  validation, promote / pending / reject APIs, schema v2 storage, and audit.
- Added `egm candidates` for listing long-term memory candidates in text or
  JSON during review.
- Added explicit TaskEdge multi-node cycle rejection.
- Added TaskNode `parent_id` missing-parent and cross-task rejection.
- Added production-boundary guidance in `docs/production.md`.
- Added release gate guidance in `docs/release-criteria.md`.

### Changed

- Wheel packaging tests now verify both builtin schemas and typed-package
  metadata.

## 0.4.0

### Added

- Published the alpha Python library to PyPI.
- Added evidence-gated facts, freshness handling, derived-fact cascade
  invalidation, TaskGraph primitives, gated node transitions, audit logging,
  long-term memory storage layers, context building, examples, and benchmark
  scaffolding.

### Notes

- This is an alpha library, not a production platform.
- The public DAG story is currently DAG-style. Full multi-node cycle rejection
  is still planned work.
- Long-term memory promotion is currently manual. LLM-generated memory
  candidates must wait for a candidate gate design and implementation.
