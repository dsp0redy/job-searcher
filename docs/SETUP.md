# Setup and operations

## Local setup

1. Install Python 3.11 or newer.
2. Create and activate a virtual environment.
3. Install development dependencies with python -m pip install -e ".[dev]".
4. Review config.yml (or config.example.yml) and update role/location filters and career-site URLs.
5. Validate configuration with job-searcher --config config.yml --check-config.
6. Run a scan with job-searcher --config config.yml --output-dir reports.
7. Run quality checks: ruff check src tests, mypy src/job_searcher, and pytest --cov=job_searcher --cov-report=term-missing.

## Source adapters

- **Workday:** public *.myworkdayjobs.com career sites. The adapter uses public CXS job-search/detail endpoints, limits listing pages, and caps detail requests per site. Employer endpoints can change, so inspect source status and original job links.
- **Greenhouse:** configure public board tokens in sources.greenhouse.
- **Lever:** configure public site slugs in sources.lever.

Source failures are isolated so one failing employer/site does not stop other sources. Greenhouse and Lever requests use bounded retries for transient network failures and retryable HTTP responses (429 and 5xx), respect numeric or HTTP-date Retry-After headers, and cap server-requested waits. Workday has its own listing/detail request path; unified status retry and rate-limit behavior across all adapters remains planned. This is not a universal job crawler and does not bypass authentication, CAPTCHAs, or access controls.

## Matching and filtering

Local matching scores configured title matches, location matches, and skills found in the job title/description. The checked-in configuration defaults to Gemini AI matching, which compares a resume against selected jobs. Add GEMINI_API_KEY and plain-text resume content as RESUME_TEXT in GitHub Actions Secrets. For local runs, RESUME_FILE may point to an ignored PDF or text file instead. To use Claude, set matching.provider to claude and add ANTHROPIC_API_KEY. For an OpenAI-compatible API, set repository variable AI_PROVIDER=openai_compatible, AI_BASE_URL, and AI_MODEL, and store the provider key in AI_API_KEY (a GitHub Actions Secret). Groq uses https://api.groq.com/openai/v1; OpenRouter uses https://openrouter.ai/api/v1. For local-only keyword scoring set matching.provider to none. A score is a relevance estimate, not an interview probability.

AI calls are bounded by matching.max_ai_jobs_per_scan (40 by default) and grouped using matching.max_jobs_per_ai_batch (3 by default). Successful results are cached in SQLite using a key that includes resume text, job content, provider, endpoint, and model. Missing or invalid results are not cached as successful matches, so they can be retried later. If AI initialization or a batch fails, the scan records the AI failure and still produces reports using local evidence; notifications requiring a valid AI result are skipped for that job. Review the run summary and report rather than treating fallback as a successful AI match.

Postings with a known timestamp older than search.posted_within_days are excluded. Greenhouse updated_at and Workday startDate are not treated as original publication dates; if no actual posting date is exposed, the posting is retained. Undated postings are kept because many public career pages omit a parseable date. Workday relative labels such as “Posted 2 Days Ago” are normalized to approximate UTC timestamps.

## GitHub Actions and notifications

CI runs Ruff, strict mypy, tests, and the 100% statement/branch coverage gate on pushes and pull requests. The scheduled workflow runs weekdays at 02:17 UTC and can be run manually from the Actions tab. Scheduled scans are serialized, have a finite job timeout, and upload reports as artifacts even if the scan fails. Artifacts are retained for 14 days.

The checked-in config.yml enables GitHub Issues notifications for postings whose configured match score meets matching.threshold. The workflow provides GITHUB_TOKEN and GITHUB_REPOSITORY automatically and declares only contents: read and issues: write. For local issue creation, provide a token with issue-write permission and the repository in owner/name format through environment variables. Never put tokens in configuration or source control.

The workflow exposes GEMINI_API_KEY, ANTHROPIC_API_KEY, AI_API_KEY, and RESUME_TEXT as repository Actions Secrets. Provider selection uses repository variable AI_PROVIDER (default gemini). For an OpenAI-compatible provider, set AI_PROVIDER=openai_compatible, AI_BASE_URL, and AI_MODEL as repository Variables and AI_API_KEY as a Secret. The Gemini model defaults to gemini-3.5-flash-lite and can be overridden using GEMINI_MODEL; Claude uses CLAUDE_MODEL. If AI mode is selected but its key or resume text is missing, the orchestrator logs the initialization failure and continues with local scoring/reporting; review the run as a partial AI failure, not a full AI match.

Each created issue contains a stable hidden identity marker. Later runs scan existing issues once and reuse the marker cache during the scan to avoid creating duplicates. GitHub's API does not provide an atomic create-if-absent operation, so unrelated concurrent issue creators may still race.

## Privacy and recovery

- Do not commit API tokens, .env, resumes, SQLite databases, or personal generated reports.
- For scheduled AI matching, store extracted resume text in the RESUME_TEXT Actions Secret; do not commit the PDF to a public repository.
- In AI mode, resume text and selected job-description excerpts are sent to the chosen provider. Review the provider's privacy and retention terms before enabling it.
- data/jobs.sqlite3 stores job descriptions and scan state; reports/ may contain job/profile matching evidence.
- Workflow report artifacts are available to repository users with appropriate access until they expire.
- If a run fails, inspect workflow logs and the JSON summary first. Confirm source URLs and credentials, then rerun manually only after considering AI-token cost and whether issue notifications are enabled.
- Unit and property-based tests use mocked provider/network responses and temporary SQLite databases. They do not prove current employer endpoints are available or that live secrets and permissions are correct. A controlled manual scan is still needed.

## Current limitations

- Workday and AI-provider retry policies do not yet share the same Retry-After implementation as Greenhouse/Lever.
- Resume parsing quality checks, mandatory-experience extraction, provider token/billing usage accounting, source-health metrics, and dependency auditing remain planned.
- Workday endpoints and employer career-site URLs may change.
- Listing-page and detail-request caps intentionally trade exhaustive coverage for lower request volume.
