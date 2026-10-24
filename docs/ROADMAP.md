# Roadmap

This roadmap tracks implementation separately from validation that requires live credentials or external services. The current priority is reliable scheduled discovery with strict Bengaluru/Hyderabad filtering, safe notifications, and actionable operations.

## Phase 1 — Reliability and source resilience

- [x] Typed normalized job schema and validated configuration.
- [x] SQLite persistence, deduplication, scan history, AI match cache, review statuses, schema version tracking, and online backup.
- [x] Bounded retries for source and AI HTTP requests, including retryable 429/5xx statuses, numeric/date-form Retry-After, exponential backoff, and jitter.
- [x] Per-host request pacing shared by source adapters and AI requests within the process.
- [x] Workday listing/detail requests use the same retry and pacing policy as Greenhouse/Lever.
- [x] Isolate failed sources/sites so other configured sources can still contribute results.
- [x] Add checked-in response-schema fixtures for Greenhouse, Lever, and Workday plus a scheduled non-blocking smoke check of configured public endpoints.
- [x] Add fuzz/property tests for identity normalization, matching boundaries, Workday date parsing, and reviewed location regression cases.

## Phase 2 — Scheduled workflow and operations

- [x] GitHub Actions scheduled weekday scan and manual dispatch, with serialized runs, finite timeout, least-privilege permissions, and report upload after failure.
- [x] CI linting, strict type checking, deterministic tests, property-based fuzzing, and a 100% statement/branch coverage gate.
- [x] Scheduled dependency vulnerability auditing and weekly Dependabot updates for Python packages and GitHub Actions.
- [x] Structured scan-health reporting: elapsed time, source success/failure/skipped counts, candidate counts, location/freshness/experience exclusions, AI failures/deferred jobs, notification outcomes, and configured token-cost estimates.
- [x] Open/update a single scan-health alert when a scan fails; close it after a successful run.
- [x] Document recovery steps for failed runs, rate limits, invalid secrets, provider outages, and issue permissions.
- [x] Add a manual live-source dry-run that uses current public endpoints, writes reports/artifacts, and disables both AI calls and job Issue creation by default.
- [ ] Verify the real scheduled workflow's secret configuration and `issues: write` permission in a controlled non-dry-run after reviewing the dry-run artifact; this can create real GitHub Issues and may incur AI-provider cost, so it requires explicit operator approval.

## Phase 3 — Matching quality and explainability

- [x] Deterministic title/skill scoring with a hard location allowlist before AI matching or issue creation.
- [x] Configured target cities are Bengaluru/Bangalore and Hyderabad; country-only, remote-only, and unrelated-city postings do not pass the city filter.
- [x] Extract explicit experience ranges and exclude postings whose stated range is incompatible with the configured experience range. Unknown requirements are retained and reported as unknown rather than guessed.
- [x] Reports include local evidence, freshness status, experience evidence, AI status, and exclusion counts in the run summary.
- [x] Optional Gemini, Claude, and OpenAI-compatible provider support with response validation and cached results.
- [x] Preview extracted resume text locally before an AI run; warn when extracted text is unusually short and reject empty extraction.
- [x] Capture provider-reported token counts; estimated cost is shown only when explicit per-million input/output rates are configured.
- [x] Configurable posting-age filter; old postings are counted as excluded and undated postings are labeled rather than silently assumed fresh.
- [x] Reviewed location regression fixtures prevent out-of-area postings from re-entering the candidate/notification path.
- [x] Add a manually reviewed relevance fixture with precision/recall checks for target-city roles, unrelated cities, wrong roles, and incompatible experience requirements.

## Phase 4 — Source coverage and user experience

- [x] Workday, Greenhouse, and Lever public-interface adapters. These cover configured public interfaces, not every job board.
- [x] Generate an employer-grouped digest for each scan with original links, scores, and evidence.
- [x] Aggregate a seven-day employer-grouped digest across recent scan snapshots, deduplicated by stable job identity.
- [x] Local review queue supports saved, applied, rejected, and stale statuses with private local notes; no automatic applications are made.
- [x] Retention controls prune old database jobs, match-cache entries, scan history, and local scan report files.
- [x] SQLite online backup and schema-version guard are available; existing schemas are upgraded additively during initialization.
- [x] Evaluate further adapters; defer adding another source until a stable, permitted public interface is selected. Avoid unsupported scraping and untested integrations.

## Acceptance criteria

- Every new branch/path has deterministic tests; external services are mocked in CI.
- CI must pass Ruff, strict mypy, all tests, and 100% statement plus branch coverage.
- Property-based tests cover parsers, identity normalization, configuration boundaries, and scoring inputs where appropriate.
- Workflow changes preserve least-privilege permissions, serialized runs, finite job timeout, and artifact upload even after scan failure.
- No secrets, resume text, local database, or personal reports are committed.
- Live validation remains a separate controlled step; unit tests must not create real GitHub Issues or spend AI tokens.

## Explicit non-goals

- No promise to search every job platform; integrations depend on supported public interfaces.
- No bypassing authentication, CAPTCHAs, paywalls, or anti-bot protections.
- No automatic job applications or fabricated resume claims.
- AI scores are advisory; review the original posting and requirements before applying.
