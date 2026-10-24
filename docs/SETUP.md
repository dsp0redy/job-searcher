# Setup and operations

## Local setup

1. Install Python 3.11 or newer.
2. Create and activate a virtual environment.
3. Install development dependencies with `python -m pip install -e ".[dev]"`.
4. Review `config.yml` (or `config.example.yml`) and verify target cities, role filters, and career-site URLs.
5. Validate configuration without network calls: `job-searcher --config config.yml --check-config`.
6. Preview extracted resume text locally before enabling AI: `job-searcher --config config.yml --preview-resume`. This makes no provider calls and prints the first 1,200 characters plus quality metadata.
7. Safely test current public sources first: `job-searcher --config config.yml --output-dir reports --dry-run`. This fetches live listings and writes reports while disabling AI calls and GitHub Issue creation. Use `job-searcher --config config.yml --output-dir reports` for a full scan only when you intend to run AI matching and notifications.
8. Run quality checks: `ruff check src tests`, `mypy src/job_searcher`, and `pytest --cov=job_searcher --cov-report=term-missing`.

## Location and experience filters

The checked-in profile is intentionally restricted to **Bengaluru/Bangalore and Hyderabad**. These are hard filters, not just scoring bonuses. Country-only locations such as "India", remote-only labels, and postings in unrelated cities are excluded before AI matching and before GitHub Issue publishing. A posting listing multiple cities is eligible if its location field explicitly includes one of the configured target cities. If you want to change the target cities, edit `profile.locations` in both config files and review the location regression fixture and tests.

The local score uses configured role-title and skill evidence. The scanner also extracts explicit experience requirements (for example, "3-5 years" or "8+ years") and excludes roles that cannot overlap the configured candidate range. When a requirement cannot be reliably extracted, it is left unknown and reported as such; the scanner does not guess. This parser is conservative and does not replace reading the original job description.

## Source adapters and resilience

- **Workday:** public `*.myworkdayjobs.com` career sites using public CXS job-search/detail endpoints.
- **Greenhouse:** configure public board tokens in `sources.greenhouse`.
- **Lever:** configure public site slugs in `sources.lever`.

All source adapters share bounded retries for transient network failures and HTTP 429/5xx responses, support numeric and HTTP-date `Retry-After`, cap retry delay, add retry jitter, and pace requests by host within the process. Source failures are isolated so one failing employer/site does not stop other sources. Workday listing and detail requests use the same retry policy. Public endpoints and response schemas can change; the workflow does not bypass authentication, CAPTCHAs, or access controls.

## Matching, resume privacy, and AI cost

Local matching is deterministic. Optional AI matching supports Gemini, Claude, and OpenAI-compatible APIs. Add the provider key and `RESUME_TEXT` as GitHub Actions Secrets. For local runs, `RESUME_FILE` can point to a PDF or text file. Use `--preview-resume` to review extraction quality locally before a run. Empty extraction is rejected; unusually short text produces a warning. AI mode sends resume text and selected job-description fields to the configured provider, so review that provider's privacy and retention terms.

AI calls are bounded by `matching.max_ai_jobs_per_scan` and `matching.max_jobs_per_ai_batch`; successful results are cached using job content, resume, provider, endpoint, and model. The scan records provider-reported input/output token usage when available. It estimates dollar cost only when both `matching.input_cost_usd_per_million_tokens` and `matching.output_cost_usd_per_million_tokens` are explicitly configured. Rates are not guessed because pricing varies by provider and model. If AI initialization or a batch fails, the scan records the failure and still generates reports using local evidence; it skips notifications for jobs without a valid AI result.

Provider configuration:
- Gemini: `GEMINI_API_KEY`, optional `GEMINI_MODEL`.
- Claude: `ANTHROPIC_API_KEY`, optional `CLAUDE_MODEL`, and `matching.provider: claude`.
- OpenAI-compatible: repository variables `AI_PROVIDER=openai_compatible`, `AI_BASE_URL`, and `AI_MODEL`, plus secret `AI_API_KEY`. Groq uses `https://api.groq.com/openai/v1`; OpenRouter uses `https://openrouter.ai/api/v1`.
- Local-only mode: set `matching.provider: none`.

## Freshness and reports

`search.posted_within_days` controls the freshness window. Known older postings are excluded and counted in the scan summary. Undated postings are retained because public boards often omit a reliable publication date; reports label them as `undated`. Greenhouse `updated_at` and Workday `startDate` are not treated as original publication dates.

Each scan produces JSON, CSV, Markdown, and an employer-grouped seven-day digest with links and match evidence. Reports include stable job identities for the local review queue. Spreadsheet formula-like CSV cells are escaped. Local report files older than `search.report_retention_days` are pruned. The scheduled workflow restores/saves recent report snapshots through the Actions cache so later weekly digests can aggregate prior scans; cache availability is best-effort and snapshots are still subject to the configured retention. Workflow artifacts are retained for 14 days.

## Review queue, retention, and backups

Use the `identity` field in a JSON report to set or inspect local review status:

```bash
job-searcher --config config.yml --job-identity YOUR_JOB_IDENTITY --review-status saved --review-notes "Review role requirements"
job-searcher --config config.yml --job-identity YOUR_JOB_IDENTITY
```

Supported statuses are `saved`, `applied`, `rejected`, and `stale`. Notes remain local in SQLite and are not sent to GitHub. The tool does not apply to jobs automatically.

Create a consistent online SQLite backup and prune retained state with:

```bash
job-searcher --config config.yml --backup-db backups/jobs.sqlite3
job-searcher --config config.yml --prune-now
```

Database retention is controlled by `storage.retention_days`; local report retention is controlled by `search.report_retention_days`. SQLite records a schema version and rejects a database created by a newer unsupported schema. Back up before changing application versions. Schema changes should be additive or include an explicit migration before increasing the schema version.

## GitHub Actions, notifications, and alerts

The scheduled workflow runs weekdays at 02:17 UTC and can be started manually from **Actions → Scheduled job scan → Run workflow**. Manual dispatch defaults to `dry_run: true`, which checks live public source data and uploads reports without AI calls or job Issue creation. Set `dry_run: false` only when intentionally authorizing a full scan, which can spend AI tokens and create real Issues. Scheduled weekday runs continue to use the configured AI and notification settings. The workflow is serialized, has a 30-minute timeout, installs runtime dependencies, validates config, uploads reports even after scan failure, and uses only `contents: read` and `issues: write` permissions. If all sources fail or AI matching is incomplete, the CLI exits nonzero after preserving reports. The workflow opens or updates one scan-health alert issue and closes it after a successful run.

The checked-in config enables job Issue notifications when the final score reaches `matching.threshold`. The workflow provides `GITHUB_TOKEN` and `GITHUB_REPOSITORY` automatically. Existing job issues use a stable hidden marker, but GitHub does not offer atomic create-if-absent semantics, so independent concurrent creators can still race.

CI runs Ruff, strict mypy, tests, and the 100% statement/branch coverage gate. A weekly dependency-audit workflow runs `pip-audit`; Dependabot proposes weekly updates for Python dependencies and GitHub Actions.

## Recovery checklist

1. Open the failed Actions run and inspect the JSON summary and source-specific status.
2. If no source succeeded, verify career-site URLs and check whether the public endpoint or rate limit changed.
3. If AI failed, verify provider selection, secret names, resume extraction, endpoint/model variables, and provider quota. Review partial-failure status before rerunning because AI calls can incur cost.
4. If issue creation failed, verify repository name and `issues: write` permission. Reports remain available even if notification creation fails.
5. Use uploaded artifacts to inspect candidate locations and original job URLs. Do not broaden the city allowlist just to increase result count without reviewing false positives.

Unit/property tests use mocked network responses and temporary databases. They do not validate live employer endpoints, real credentials, actual GitHub permissions, or AI-provider billing. A controlled manual scan is still required for final production verification.


## Operational notes

- **Scheduled workflows pause after 60 days without repository activity** on public repos.
  If scans stop, re-enable the workflow in the Actions tab (or push any commit).
- **Review queue:** `job-searcher --job-identity <id> --review-status rejected|applied|saved|stale`.
  `rejected` and `applied` jobs are excluded from later reports and issues. Reviewed jobs are
  never pruned by retention.
- **Workday coverage:** `search.workday_search_terms` narrows the otherwise-unfiltered listing
  (use your target cities); `search.workday_detail_limit` controls how many postings per site get
  a full description, which drives skill and experience scoring.
- **Seniority filter:** `profile.exclude_title_keywords` skips titles such as "Principal" or "Director".
- **Issue de-duplication** reads up to 5,000 existing issues. Beyond that it refuses to publish
  (reported as a notification failure) rather than risk duplicates.
