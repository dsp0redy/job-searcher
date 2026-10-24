# Roadmap

## Phase 1 — Reliable foundation
- [x] Typed normalized job schema and validation
- [x] Validated YAML configuration and environment secrets
- [x] SQLite persistence, deduplication, run history, and AI match cache
- [x] Request timeouts and bounded retries for transient connection failures
- [ ] Retry-After handling, HTTP status retry policy, and explicit rate limiting
- [x] Unit tests for models, matching, storage, Workday parsing, and AI response validation

## Phase 2 — Source adapters
- [x] Greenhouse public job-board API adapter
- [x] Lever public postings adapter
- [x] Workday adapter based on compatible public career-site endpoints
- [x] Adapter isolation so a failed source does not stop other sources
- [ ] More source-health metrics and live endpoint validation
- [x] Avoid bypassing authentication, CAPTCHAs, or access controls

## Phase 3 — Matching and delivery
- [x] Deterministic title/location/skill scoring before AI
- [x] Optional Gemini and Claude matching with strict result validation
- [x] AI match caching keyed by job, resume text, provider, and model
- [x] Markdown/JSON/CSV reports
- [x] GitHub Issues notifications with stable identity markers and duplicate checks
- [x] Per-scan AI job cap to control cost
- [ ] Mandatory-experience extraction and resume parsing
- [ ] Provider token usage and cost accounting

## Phase 4 — Operational quality
- [x] GitHub Actions schedule and manual dispatch
- [x] CI: lint and tests
- [x] Configuration, secrets, and privacy documentation
- [x] Source-level failure isolation
- [ ] Verify latest CI result and run an end-to-end scan with configured secrets
- [ ] Type checks and dependency/security audit
- [ ] Metrics for source health, candidate volume, match rate, and AI cost

## Explicit non-goals
- No promise to search every job platform; integrations depend on supported public interfaces.
- No bypassing authentication, CAPTCHAs, paywalls, or anti-bot protections.
- No automatic job applications or fabricated resume claims.
- AI scores are advisory; review each posting and its requirements before applying.
