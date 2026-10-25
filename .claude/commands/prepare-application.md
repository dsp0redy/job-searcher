# Prepare an application

Prepare application materials for one job posting. This command is a drafting assistant, not an auto-apply bot.

## Input

The user should provide a job-posting URL, or identify a posting from a local Job Searcher report. If the user has not provided a URL or unambiguous job identity, ask one concise question and stop.

## Required context

1. Read `.claude/candidate-profile.md` if it exists.
2. If it does not exist, read `docs/candidate-profile.example.md` and ask the user to create their private profile before drafting. Do not treat example placeholders as facts.
3. Fetch the job posting from the supplied URL when accessible. If access is blocked or the page is incomplete, ask the user to paste the job description. Never claim to have read inaccessible content.
4. If available, use the relevant local report entry as discovery context, but treat the employer's posting as the source of truth for responsibilities and requirements.

## Workflow

1. **Capture facts.** Extract employer, role title, location, requisition ID, posting URL, responsibilities, must-have skills, preferred skills, experience range, and application instructions. Mark any unavailable field as unknown.
2. **Evaluate fit.** Compare the posting with the candidate profile. Give a concise fit summary, evidence from the profile, genuine gaps, and questions the user should resolve. Do not infer eligibility from a keyword score alone.
3. **Pause if there is a material issue.** Ask before continuing if the job requires a skill or credential that the profile explicitly lacks, the location/experience is incompatible, or the posting appears suspicious or expired.
4. **Draft a tailored resume.** Reorder and rephrase only facts already supported by the profile. Keep job titles, dates, employers, technologies, project outcomes, and metrics truthful. Never invent experience, certifications, ownership, impact numbers, or ATS keywords unsupported by evidence. Keep the result concise and readable.
5. **Draft a tailored cover letter.** Connect two or three verified candidate examples to the role. Avoid generic praise and unsupported claims. If a company-specific detail cannot be verified, omit it.
6. **Prepare interview notes.** List likely technical/role questions grounded in the posting, candidate examples to revisit, and gaps to study. Clearly separate likely topics from facts about the interview process.
7. **Create a review package** under `applications/<company-slug>/<role-slug>/` with:
   - `job-notes.md`: source URL, capture date, extracted requirements, and fit/gap analysis.
   - `resume-draft.md`: tailored resume content.
   - `cover-letter.md`: tailored cover letter.
   - `interview-prep.md`: grounded interview preparation notes.
   - `review-checklist.md`: items to verify before applying.
8. Show a concise summary of created files and any facts needing confirmation.

## Approval and safety rules

- Never submit an application, click a final submit button, send an email, or represent that an application has been sent. Only the user may perform the final submission.
- Do not invent an application status. Do not mark a job as applied unless the user explicitly confirms that they submitted it.
- Do not include secrets, authentication cookies, personal IDs, or unnecessary sensitive information in generated files.
- Keep personal candidate details and all generated application packages local. The repository ignores `.claude/candidate-profile.md` and `applications/`; verify the ignore rules before adding files to version control.
- Before overwriting an existing package, ask the user or create a clearly named revision rather than silently replacing their edits.
- Respect the job site's terms and access controls. If the posting cannot be retrieved normally, request pasted text instead of bypassing controls.

## Output style

Be specific, evidence-based, and direct. Use the candidate's actual experience and the role's language without keyword stuffing. Explain uncertainty rather than filling gaps with guesses.
