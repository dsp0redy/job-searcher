# Roadmap

This roadmap distinguishes shipped behavior from planned work. Priorities put safe, repeatable scheduled scans ahead of expanding matching features.

## Phase 1 — Reliability and source resilience

- [x] Typed normalized job schema and validation.
- [x] Validated YAML configuration and environment-only secrets.
- [x] SQLite persistence, deduplication, scan history, and AI match cache.
- [x] Bounded request timeouts and retry handling for transient AI-provider failures.
- [x] Bounded retries for Greenhouse/Lever HTTP requests, including numeric/date-form Retry-After handling and retryable HTTP status policy.
- [ ] Apply the same explicit status/retry policy to Workday listing/detail requests and honor Retry-After in AI-provider requests.
- [ ] Add per-host rate limiting and jitter to avoid synchronized retries across career sites.
- [x] Isolate failed sources/sites so other configured sources can still contribute results.
- [ ] Add response-schema fixtures and periodic checks for upstream API drift without making production scans depend on live endpoints.

## Phase 2 — Scheduled workflow and operations

- [x] GitHub Actions scheduled weekday scan and manual dispatch.
- [x] Serialize scheduled scans to reduce duplicate notifications.
- [x] Restrict workflow permissions to repository contents read and Issues write only.
- [x] Upload JSON/CSV/Markdown reports as retained workflow artifacts, including after scan failure.
- [x] CI linting, strict type checking, deterministic tests, property-based fuzzing, and a 100% statement/branch coverage gate.
- [x] CodeQL validation completed on the previous hardening PR.
- [ ] Add dependency vulnerability auditing and a documented dependency update cadence.
- [ ] Add structured scan-health reporting: source success/failure counts, elapsed time, candidate counts, notification failures, and AI failure/defer counts.
- [ ] Alert on consecutive scans with no successful sources or repeated provider/notification failures.
- [ ] Run a controlled live workflow with configured secrets and review the report artifact; mocked tests do not validate current upstream endpoints or account permissions.
- [ ] Document recovery steps for failed runs, rate limits, invalid secrets, and unavailable providers.

## Phase 3 — Matching quality and explainability

- [x] Deterministic title/location/skill scoring before optional AI matching.
- [x] Optional Gemini, Claude, and OpenAI-compatible provider support with response validation.
- [x] AI result cache keyed by job content, resume, provider, endpoint, and model.
- [x] Per-scan AI job cap and configurable batch size to limit cost.
- [x] Reports include match evidence and AI status; AI initialization failure falls back to local scoring and preserves reports.
- [ ] Extract mandatory requirements and years-of-experience constraints into structured evidence.
- [ ] Parse resume text from PDF/text with quality checks and an explicit preview/override path before sending it to an AI provider.
- [ ] Track provider-reported token usage and estimated cost where reliable usage metadata is available.
- [ ] Add configurable freshness policy and explain why a posting was retained or excluded.
- [ ] Add reviewed regression fixtures to evaluate ranking quality and false positives/negatives.

## Phase 4 — Source coverage and user experience

- [x] Workday, Greenhouse, and Lever public-interface adapters.
- [x] Configurable role, location, skill, recency, and source settings.
- [ ] Add more adapters only when stable, permitted public interfaces exist.
- [ ] Add a compact weekly digest grouped by employer and match evidence, linking to original postings.
- [ ] Add an optional review queue/status for saved, applied, rejected, and stale jobs without automatically applying.
- [ ] Add retention controls for old job descriptions, scan history, and local report artifacts.
- [ ] Add documented export/backup and database migration strategy.

## Acceptance criteria for future changes

- Every new branch/path has deterministic tests; external services are mocked in CI.
- CI must pass Ruff, strict mypy, all tests, and 100% statement plus branch coverage.
- Property-based tests should cover parsers, identity normalization, configuration boundaries, and scoring inputs where appropriate.
- Workflow changes must preserve least-privilege permissions, serialized runs, finite job timeout, and artifact upload even after scan failure.
- No secrets, resume text, local database, or personal reports are committed.
- Live validation is separate and controlled; unit tests must not create real GitHub Issues or spend AI tokens.

## Explicit non-goals

- No promise to search every job platform; integrations depend on supported public interfaces.
- No bypassing authentication, CAPTCHAs, paywalls, or anti-bot protections.
- No automatic job applications or fabricated resume claims.
- AI scores are advisory; review the original posting and evidence before applying.
