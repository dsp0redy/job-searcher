# Application preparation workflow

Job Searcher already discovers, filters, ranks, deduplicates, and reports job postings. This optional layer helps prepare human-reviewed application materials for an individual posting. It is designed to run locally with Claude Code; it is not part of the scheduled GitHub Actions scan.

## What it does

- Reads a user-provided posting URL and the private candidate profile.
- Summarizes role requirements and explains fit, evidence, and gaps.
- Drafts a tailored resume and cover letter without inventing qualifications.
- Prepares role-specific interview notes and a pre-submission checklist.
- Keeps the output as local review files for the user to edit.
- Consumes the scanner's `reports/application-queue.json` handoff, which contains only jobs at or above the configured match threshold (70/100 by default).

It does **not** submit application forms, email recruiters, log in to job portals, or automatically mark jobs as applied.

## Setup

1. Install and configure [Claude Code](https://docs.anthropic.com/en/docs/claude-code/overview) in your local checkout. This feature is optional; the existing Python scanner works without it.
2. Copy `docs/candidate-profile.example.md` to `.claude/candidate-profile.md`.
3. Replace every placeholder with verified details from your actual resume. Remove any section that does not apply.
4. Keep the private profile and generated application packages out of Git. The repository's `.gitignore` excludes `.claude/candidate-profile.md` and `applications/`.
5. Run the scanner first; it writes `reports/application-queue.json` with eligible jobs scoring at least the configured threshold (70/100 by default). Review that shortlist, then from Claude Code run `/prepare-application` and ask it to process `reports/application-queue.json`, or pass a specific posting URL.

If the job site blocks automated page access, paste the full job description when prompted. Do not provide passwords, cookies, or other login secrets.

## Handoff and score semantics

The queue JSON is included in the existing `reports/` artifact from GitHub Actions. Download that artifact and place `application-queue.json` in the local Job Searcher checkout before running the assistant. The public upstream `ai-job-search-dev/ai-job-search` repository is not writable by this project; this handoff is a file contract rather than a direct repository-to-repository push.

A score of 70/100 is a relevance threshold, **not an actual employer ATS score or probability of interview**. If AI matching is enabled but failed or deferred for a posting, that posting is excluded from the handoff. Local-only matches are labeled `local_heuristic`.

## Output

For each posting, the command creates a review package under:

```text
applications/
  <company-slug>/
    <role-slug>/
      job-notes.md
      resume-draft.md
      cover-letter.md
      interview-prep.md
      review-checklist.md
```

Review all facts, dates, metrics, links, formatting, and employer instructions. Export the final resume to the format requested by the employer only after reviewing the draft. If a PDF is needed, compile it locally with a tool you trust and inspect the resulting PDF before submitting.

## Suggested review checklist

- [ ] The posting is genuine, current, and at the correct employer domain.
- [ ] The role, location, experience range, and eligibility match your situation.
- [ ] Every resume statement is supported by your actual experience.
- [ ] Dates, project details, metrics, skills, and certifications are accurate.
- [ ] The resume and cover letter are tailored but do not exaggerate fit.
- [ ] The generated files contain no secrets or unnecessary personal data.
- [ ] The final resume file opens correctly and is readable.
- [ ] You personally reviewed the complete application before submission.
- [ ] Update Job Searcher's local review status only after you decide what to do; use `applied` only after you actually submit.

## Privacy and costs

Claude Code may send the content you provide to the configured AI service. Do not use this workflow until you have reviewed the applicable service's privacy, retention, and billing terms. Avoid putting personal candidate data in public issues, pull requests, workflow logs, or committed files.

## Relationship to the upstream project

This is a small, approval-first integration inspired by the public [ai-job-search](https://github.com/ai-job-search-dev/ai-job-search) project. It keeps Job Searcher's existing Python scanner and database as the discovery layer rather than copying the upstream repository wholesale. The upstream project is MIT-licensed; consult its repository for its license and current instructions if you choose to use it directly.
