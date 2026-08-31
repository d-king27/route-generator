# Weekday walking emails

Emails the first unchecked walk in
`constituency_every_house_walks_m22_4fp.txt` and marks only that entry `[X]`
after Gmail accepts the message. Uses Python's standard library; no packages
need installing. The attached 60-walk schedule is included without changes.

## Setup

1. Put these files on your GitHub repository's `main` branch and make `main`
   the default branch. Scheduled workflows run from the default branch.
2. Enable Google 2-Step Verification and create a
   [Gmail app password](https://support.google.com/accounts/answer/185833?hl=en).
   App passwords may be unavailable for some managed or protected accounts.
3. Under **Settings > Secrets and variables > Actions > Repository secrets**,
   add `SENDER_EMAIL` (Gmail address), `SENDER_PASSWORD` (app password, not your
   normal Google password), and `RECIPIENT_EMAIL` (one destination address).
   To email yourself, set `SENDER_EMAIL` and `RECIPIENT_EMAIL` to the same
   Gmail address.
   Never place credentials in the code or schedule.
4. Enable GitHub Actions. The workflow requests `contents: write` for the
   automatic `GITHUB_TOKEN`; repository/organization policies and `main`
   branch rules must permit its direct commits. This permission does not
   bypass protected-branch or ruleset restrictions.
5. In **Actions > Weekday walk > Run workflow**, select `main` to test.
   **Each manual run sends a real email and advances one walk**, including
   weekends or additional runs on the same day.

The workflow uses maintained
[checkout](https://github.com/actions/checkout) and
[setup-python](https://github.com/actions/setup-python) actions.

## Schedule and behavior

- Runs Monday-Friday at **07:00 UTC**: 07:00 in UK winter, 08:00 during BST.
- GitHub schedules can be delayed or dropped during high load, especially at
  the start of an hour; this is not an exact-time delivery guarantee. Public
  repositories' schedules may be disabled after 60 days without activity.
  See [GitHub scheduled workflow documentation](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).
- One walk is emailed per successful invocation. Overlapping workflow runs
  cannot send simultaneously. Run this automation in only one repository;
  local script invocations are not covered by GitHub's concurrency lock.
- `[X]` means **emailed**, not confirmation that you physically walked the route.
  Summary-tracker checkboxes and all other schedule content remain unchanged.
- Emails and local previews include Google Maps search links for the schedule's
  starting point and each comma-separated target street/area, with Manchester
  added to target queries. If the starting-location header is absent, an area
  map for Northenden is included instead. No Maps API key or extra secret is
  required; see [Google Maps URLs](https://developers.google.com/maps/documentation/urls/get-started).
  These are place searches, not verified walking routes: broad descriptions
  may need refining in Maps, and the written instructions remain in the email.
- Completed entries, divider lines (`===` or `---`), and end-of-file bound the
  email body. Finished schedules exit successfully without requiring secrets,
  sending email, changing the file, or creating a commit.
  The workflow does not disable itself: subsequent scheduled runs simply
  find nothing to send. It does not restart at Walk 01.
- Missing credentials or SMTP errors fail the run without advancing the
  checklist. The prepared update replaces the file atomically after SMTP
  success. No SMTP operation is retried automatically.
- Email and Git cannot form one transaction: if Gmail accepts a message but
  the connection, file update, or subsequent commit/push fails, a later run
  can duplicate it. Check the failed run and mark the sent walk `[X]` on `main`
  before rerunning. Push retries do not resend the email, and never force-push.
  A successful SMTP response confirms acceptance, not inbox delivery.

## Track the walks you actually do

Every email includes its walk number in both the subject and body, for example
`Walk 01: Village Heart & St Hilda's Loop`.

Use [walk_completion_checklist.md](walk_completion_checklist.md) as your personal
record. Change `- [ ]` to `- [x]` only when you have actually walked that route;
you can append a date or notes. Leave missed walks unchecked and catch up in
any order using your numbered emails or the full schedule.

This file starts with all 60 walks unchecked and is never changed by the email
script. Its checkboxes mean **walked**, while those in the original schedule
mean **emailed**. Your completion checklist does not delay, repeat, or reorder
emails. Sending ends after all 60 have been emailed, even if you have walks
left to complete. Commit and push this file too if you want it on GitHub.

## Local preview and verification

From the repository root, with Python 3.11 or later:

```sh
python send_daily_walk.py --dry-run
python -m unittest discover -s tests -v
```

Preview needs no credentials, does not contact Gmail, and does not change the
checklist. Tests use fake SMTP connections and temporary copies of the schedule.
For a real local send, set the three environment variables securely and run
`python send_daily_walk.py`. The schedule is located relative to the script,
so running from a different working directory is supported.
