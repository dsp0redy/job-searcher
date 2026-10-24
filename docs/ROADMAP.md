# Roadmap

## Phase 1 — Reliable foundation
- [ ] Typed normalized job schema and validation
- [ ] Validated YAML configuration and environment secrets
- [ ] SQLite migrations, deduplication, run history, and cache
- [ ] Structured logging, bounded retries, request timeouts, and rate limiting
- [ ] Unit tests with mocked HTTP; no network dependency in CI

## Phase 2 — Source adapters
- [ ] Greenhouse public job-board API adapter
- [ ] Lever public postings adapter
- [ ] Workday adapter based on supported public career-site endpoints
- [ ] Adapter contract and source health/coverage reporting
- [ ] Respect site terms, robots/access controls, and retry-after responses

## Phase 3 — Matching and delivery
- [ ] Deterministic filters: role, location, seniority, recency, required skills
- [ ] Local relevance scoring before AI
- [ ] Optional AI provider interface with strict JSON validation and cache
- [ ] Markdown/JSON/CSV reports
- [ ] GitHub Issues notifications with idempotency markers

## Phase 4 — Operational quality
- [ ] GitHub Actions schedule and manual dispatch
- [ ] CI: lint, type checks, tests, dependency audit
- [ ] Configuration and secrets documentation
- [ ] Failure isolation: one failed source must not discard other results
- [ ] Metrics for source health, candidates, match rate, cost, and failures

## Explicit non-goals
- No promise to search every job platform; integrations depend on supported public interfaces.
- No bypassing authentication, CAPTCHAs, paywalls, or anti-bot protections.
- No automatic job applications or fabricated resume claims.
