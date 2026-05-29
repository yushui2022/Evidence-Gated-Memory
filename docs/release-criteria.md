# Release Criteria

This document turns the roadmap in `plan.md` into release checks. If a release
does not meet a gate, either defer the release or describe the missing work
plainly in the release notes.

## Always Required

- `python scripts/scan_secrets.py` passes.
- `python -m pytest` passes.
- Deterministic benchmark snapshot generation passes.
- README install commands and quickstart code match the current package.
- Public benchmark claims include sample size, metric definition, date, and
  limitation.
- README does not claim full enforced DAGs until multi-node cycle rejection is
  implemented.
- README does not claim automatic long-term memory promotion until the
  CandidateAtom gate exists.
- `CHANGELOG.md` has an entry for the release.

## v0.5 Credible Alpha

Required:

- No hardcoded credentials.
- Local deterministic benchmark suite passes.
- Refund, coding, and ticket minimal demos run without API keys.
- Schema-authoring documentation exists.
- Benchmark philosophy and decision protocol exist.
- DAG invariant documentation exists and preserves the DAG-style boundary.
- `egm inspect` reports core workspace counts.
- Known limitations are documented in `plan.md`.

Not required:

- Full tau-bench or tau2-bench A/B results.
- LangChain or LangGraph adapter.
- Versioned migration runner.
- Production guide completion.
- Unaided adoption success. The attempt should be planned, not fabricated.

## v0.7 Adapter Beta

Required:

- Generic agent-loop integration guide.
- Adapter contract covering where to call `record_evidence()`, `assert_fact()`,
  `transition_node()`, and `build_context()`.
- At least one framework example or a documented reason for keeping the generic
  loop as the only supported path.
- Adapter tests for accepted and rejected paths.
- Release notes describe framework API risk.

Not required:

- Hosted service.
- UI.
- Postgres.
- Vector plugin.

## v0.8 Production Hygiene

Required:

- Versioned migration runner.
- Old-workspace migration tests.
- `egm inspect` is complete enough for workspace triage.
- Audit export supports JSON or Markdown and useful filters.
- Production boundary guide exists.
- Workspace concurrency policy is documented.
- Retention/archive policy is documented or explicitly deferred.

Not required:

- Multi-writer enterprise guarantees.
- Signed compliance exports.
- Distributed storage.

## v0.9 Storage And Memory Promotion

Required:

- Normalized storage design is implemented for the first critical dependency
  paths or explicitly scoped.
- L1 CandidateAtom design is complete.
- L1 candidate gate implementation exists.
- Candidate promotion writes audit.
- TaskGraph cycle rejection is implemented.
- Fact lineage cycle enforcement has either landed or is clearly documented as
  remaining work.

Not required:

- Automatic L2/L3 persona promotion.
- Full hosted review UI.

## v1.0 Professional Library

Required:

- Public API is documented and intentionally stable.
- Typed package marker is included in the wheel.
- Packaging extras are defined without bloating the core install.
- Release, deprecation, and changelog policy are active.
- Production guide, release criteria, security guidance, and schema guidance are
  present.
- Migration, audit export, and production-boundary claims match the code.
- At least one unaided external adoption attempt has produced actionable
  feedback, even if the result is negative.
- Reality-check conditions in `plan.md` have been reviewed.

Not required:

- Becoming a general chatbot memory platform.
- Becoming a hosted SaaS product.
- Competing as a vector database.
