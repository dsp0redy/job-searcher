# Setup and operations

## Local setup

1. Install Python 3.11 or newer.
2. Create a virtual environment: `python -m venv .venv`.
3. Activate it and install the project: `python -m pip install -e ".[dev]"`.
4. Review `config.yml` (or copy `config.example.yml`) and update the role/location filters and career-site URLs.
5. Validate the configuration: `job-searcher --config config.yml --check-config`.
6. Run a scan: `job-searcher --config config.yml --output-dir reports`.
7. Run tests and lint: `pytest` and `ruff check src tests`.

## Source adapters

- **Workday:** public `*.myworkdayjobs.com` career sites. The adapter uses public CXS job-search/detail endpoints, limits listing pages, and caps detail requests per site. Employer endpoints can change, so inspect source status and original job links.
- **Greenhouse:** configure public board tokens in `sources.greenhouse`.
- **Lever:** configure public site slugs in `sources.lever`.

Source failures are logged independently. This is not a universal job crawler and does not bypass authentication, CAPTCHAs, or access controls.

## Matching and filtering

Local matching scores configured title matches, location matches, and skills found in the job title/description. The checked-in configuration defaults to Gemini AI matching, which compares a resume against selected jobs. Add `GEMINI_API_KEY` and plain-text resume content as `RESUME_TEXT` in GitHub Actions Secrets. For local runs, `RESUME_FILE` may point to an ignored PDF or text file instead. To use Claude instead, set `matching.provider: claude` and add `ANTHROPIC_API_KEY`; for local-only scoring set `matching.provider: none`. A score is a relevance estimate, not an interview probability.

AI calls are bounded by `matching.max_ai_jobs_per_scan` (40 by default) and grouped using `matching.max_jobs_per_ai_batch` (8 by default). Successful results are cached in SQLite using a key that includes the resume text, job content, provider, and model. Missing or invalid results are not cached as successful matches, so they can be retried later.

Postings with a known timestamp older than `search.posted_within_days` are excluded. Undated postings are kept because many public career pages omit a parseable date. Workday's relative labels such as “Posted 2 Days Ago” are normalized to approximate UTC timestamps.

## GitHub Actions and notifications

The CI workflow runs Ruff and pytest on pushes and pull requests. The scheduled workflow runs weekdays at 02:17 UTC and can be run manually from the Actions tab. Reports are uploaded as artifacts and retained for 14 days.

The checked-in `config.yml` enables GitHub Issues notifications for postings whose configured match score meets `matching.threshold`. The workflow provides `GITHUB_TOKEN` and `GITHUB_REPOSITORY` automatically and declares `issues: write`. For local issue creation, provide a token with issue-write permission and the repository in `owner/name` format through environment variables. Never put tokens in configuration or source control.

The workflow also exposes the optional AI credentials as `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, and `RESUME_TEXT` from repository Actions Secrets. The model names can be overridden using repository variables `GEMINI_MODEL` and `CLAUDE_MODEL`. If AI mode is selected but its key or resume text is missing, the run fails early with a clear configuration error.

Each created issue contains a stable hidden identity marker. Later runs scan existing issues once and reuse the marker cache during the scan to avoid creating duplicates. GitHub's API does not provide an atomic create-if-absent operation, so unrelated concurrent issue creators may still race.

## Privacy

- Do not commit API tokens, `.env`, resumes, or personal generated reports.
- For scheduled AI matching, store the resume's extracted text in the `RESUME_TEXT` Actions Secret; do not commit the PDF to a public repository.
- In AI mode, the resume text and selected job-description excerpts are sent to the chosen provider. Review the provider's privacy and retention terms before enabling it.
- `data/jobs.sqlite3` stores job descriptions and scan state; `reports/` may contain job/profile matching evidence.
- Workflow report artifacts are available to repository users with appropriate access until they expire.

## Current limitations

- Resume parsing, mandatory-experience extraction, and provider token/billing usage accounting are not implemented yet. AI fit scores are advisory and should be reviewed against the original job description.
- Workday endpoints and employer career-site URLs may change.
- Listing-page and detail-request caps intentionally trade exhaustive coverage for lower request volume.
