# Job Searcher

A modular, low-token job discovery and matching platform. The initial repository is empty; this commit establishes the product direction and architecture. The implementation will use source adapters, deterministic filtering, normalized job records, persistent deduplication, optional AI ranking, and GitHub-based reporting.

## Design principles
- Source adapters are isolated and independently testable.
- Prefer official public career-site APIs/feeds; do not bypass logins, CAPTCHAs, or access controls.
- Normalize all postings into one schema and deduplicate by source + requisition/URL.
- Apply cheap local filters before any optional AI calls.
- Persist state in SQLite; keep credentials in environment variables/GitHub Secrets.
- Treat coverage as adapter-based, not a promise to crawl every job site.

## Architecture
```mermaid
flowchart TD
  A[CLI / GitHub Actions schedule] --> B[Search Orchestrator]
  B --> C[Source Adapter Registry]
  C --> D[Workday Adapter]
  C --> E[Greenhouse Adapter]
  C --> F[Lever Adapter]
  D & E & F --> G[Normalize and Validate]
  G --> H[Deduplicate: SQLite]
  H --> I[Local Eligibility Filters]
  I --> J[Optional AI Match Ranker]
  J --> K[Report / GitHub Issues]
  K --> L[Persist run state and cache]
```

## Sequence
```mermaid
sequenceDiagram
  participant S as Scheduler/CLI
  participant O as Orchestrator
  participant A as Adapters
  participant D as SQLite
  participant M as Matcher
  participant R as Reporter
  S->>O: start scan(config)
  O->>A: fetch configured sources
  A-->>O: normalized job candidates
  O->>D: check and upsert identities
  D-->>O: unseen candidates
  O->>O: local filters and ranking
  opt AI enabled and candidate qualifies
    O->>M: compact resume + selected JD fields
    M-->>O: validated score and rationale
  end
  O->>R: publish summary and artifacts
  O->>D: persist run results/cache
  R-->>S: run outcome
```

## Planned structure
```text
src/job_searcher/
  cli.py                 CLI entry point
  config.py              Validated configuration
  models.py              Normalized Job model
  orchestrator.py        Pipeline coordination
  storage/sqlite.py      Persistence and deduplication
  adapters/base.py       Adapter contract
  adapters/greenhouse.py Greenhouse public job boards
  adapters/lever.py      Lever public postings
  adapters/workday.py    Workday career sites
  matching/local.py      Token-efficient local relevance score
  reporting/markdown.py  Reports
 tests/                  Unit and adapter tests
 docs/                   Architecture and operations
 .github/workflows/      Scheduled scans and CI
```

## Status
Bootstrap only. See `docs/ROADMAP.md` for the phased implementation plan. Never commit resume files, API keys, or generated personal reports.
