# Setup and operation

## Local setup

1. Install Python 3.11 or newer.
2. Create a virtual environment: `python -m venv .venv`.
3. Activate it and install: `pip install -e '.[dev]'`.
4. Copy `config.example.yml` to `config.yml` and configure source board identifiers and your filters.
5. Validate: `job-searcher --config config.yml --check-config`.
6. Run: `job-searcher --config config.yml --output-dir reports`.

## Sources currently implemented

- **Greenhouse**: public board API; configure board tokens in `sources.greenhouse`.
- **Lever**: public postings API; configure site slugs in `sources.lever`.
- **Workday**: configuration placeholder only; adapter implementation is not yet complete.

The system does not have universal access to every job platform. Prefer public official career endpoints and comply with site terms and rate limits. Source failures are logged independently so a broken board should not prevent scanning other configured boards.

## GitHub Actions

The CI workflow runs lint and tests. The scheduled workflow runs on weekdays at 02:17 UTC and can also be started manually. Ensure `config.yml` is committed without secrets and has valid board identifiers. Reports are uploaded as a short-lived Actions artifact. The current scan workflow does not create GitHub Issues yet; that is a later milestone.

## Privacy and secrets

- Never commit a real resume, `.env`, access tokens, or personal scan reports.
- Add provider secrets only when an AI matcher is implemented and enabled.
- GitHub's built-in `GITHUB_TOKEN` is scoped to the workflow and is not needed for current report generation.

## Scoring

The initial ranker is deterministic and explainable. It scores exact configured title matches, location matches, and skills found in the title/description. It is a relevance heuristic, not a probability of getting an interview. Keep the profile filters accurate and review source postings before applying.

## State and reports

SQLite state is written to `data/jobs.sqlite3`; report files are generated in `reports/`. Both are ignored by Git. CI artifacts expire after 14 days. The database stores source posting data and match cache locally; protect it accordingly.
