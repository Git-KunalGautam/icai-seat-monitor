# ICAI seat monitor

A Python 3.12 program that checks ICAI's public batch list once, alerts through Telegram when seats open, and exits. GitHub Actions runs it approximately every 15 minutes. No browser, database, paid API, registration automation, or always-on computer is needed.

Default filters: **Central / JAIPUR / Advanced (ICITSS) MCS Course**.

## Verification status

The implemented scraper successfully fetched the live Jaipur MCS list on **4 November 2026, 10:30 Asia/Kolkata**, returning **six batches, all with zero seats**. A dry run and two successive observation-only checks passed. This is a dated observation; availability can change. `python -m src.main --dry-run` prints a fresh result without sending notifications or accessing state.

The live page uses ASP.NET WebForms, with a region postback that populates the POU list. Requests can submit full forms even though an ASP.NET AJAX UpdatePanel is present; JavaScript execution and Playwright are unnecessary.

| Purpose | Verified control / behavior |
| --- | --- |
| Form | `form1`, relative action `./launchbatchdetail.aspx` |
| Region | `ddl_reg`, `__EVENTTARGET=ddl_reg` postback |
| POU | `ddlPou`, populated by the region response |
| Course | `ddl_course` |
| Submit | `btn_getlist=Get List` |
| Results | `upd_grid` containing `GridView1` |
| Hidden state | Fresh hidden fields, including `__VIEWSTATE`, `__VIEWSTATEGENERATOR`, `__EVENTVALIDATION`, preserved for every request |

Option values are resolved by visible labels on every run. During verification, Central was `5`, JAIPUR was `170`, and MCS was `45`; these values are **not hardcoded in the scraper**. A browser user-agent is required for ASP.NET to render the region's postback handler. POSTing to the non-`www` host returns a 301 that discards form data, so the scraper consistently uses the verified `https://www.icaionlineregistration.org/launchbatchdetail.aspx` endpoint.

Sanitized live form/table captures are in `tests/fixtures/`. Hidden values have been replaced and cookies were not saved. Pagination and explicit empty-result wording are covered with constructed tests, but neither occurred in the verified Jaipur result. Missing tables, empty panels, header-only tables, unexpected selections, and invalid seat values are errors. An explicit recognized empty message is handled separately. Unrecognized wording fails safely and requires inspection.

Telegram sending and GitHub state writes are covered by mocks, **not live credentialed integration tests**. No notification was sent during development. The project has not been published from this workspace; GitHub CLI is installed but not authenticated.

## Run on Windows

Install Python 3.12 and Git. From PowerShell in this project:

```powershell
Set-Location D:\self\automate\course
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m src.main --dry-run
```

These commands use the virtual environment directly; PowerShell activation is optional. In a clone elsewhere, change `Set-Location` to that folder. Run commands from the repository root. A production install only needs `requirements.txt`.

If this managed environment blocks pytest's temporary directories, use an execution environment with access to its temporary directory. Development verification used `python -m pytest --basetemp .test-tmp-final -p no:cacheprovider --tb=short` with that access enabled: **71 tests passed**. The test suite blocks all actual network requests and never uses real Telegram credentials.

For a local check that saves observations but does not send alerts:

```powershell
$env:TELEGRAM_NOTIFICATIONS_ENABLED = 'false'
.\.venv\Scripts\python.exe -m src.main
Remove-Item Env:TELEGRAM_NOTIFICATIONS_ENABLED
```

Local runs use ignored `data/local_state.json`, keeping development history separate from deployed `data/seat_state.json`. Do not run concurrent local writers or a second alerting deployment against the same chat/state.

## Set up Telegram

1. Open the official [@BotFather](https://t.me/BotFather), issue `/newbot`, and follow the prompts. Store the token in `TELEGRAM_BOT_TOKEN` in your local `.env`. See Telegram's [bot creation guide](https://core.telegram.org/bots/features#botfather).
2. For a private chat, open your new bot and send `/start`. Bots cannot initiate private conversations before you contact them.
3. Run the following helper. It reads recent updates and prints only chat types and IDs; it sends no messages and does not print your token.

```powershell
.\.venv\Scripts\python.exe -m src.chat_id
```

Set `TELEGRAM_CHAT_ID` to the returned private ID. For a channel, add the bot as an administrator with permission to post messages, publish a new channel message yourself, then run the helper and use the returned channel ID (usually negative). A public channel's `@channelusername` also works as `TELEGRAM_CHAT_ID`. Do not use the bot's own ID as your destination.

Use a dedicated bot. `getUpdates` cannot be used while a webhook is configured, and another consumer can consume updates. Recent updates may expire; send another message if none are found. The helper never deletes webhooks or advances an update offset. See the official [getUpdates](https://core.telegram.org/bots/api#getupdates) and [sendMessage](https://core.telegram.org/bots/api#sendmessage) APIs.

Once `.env` has both values, a normal run enables real alerts:

```powershell
.\.venv\Scripts\python.exe -m src.main
```

A normal run sends only when a qualifying available batch is observed. Zero seats produce no Telegram message, so silence does not prove that Telegram credentials work. The first actual positive alert validates end-to-end delivery. Never paste a token into a browser URL, commit it, or include it in screenshots/logs. `.env` is ignored.

## Deploy to GitHub Actions

Create a repository with these files on its default branch. Standard GitHub-hosted runners are free for public repositories under GitHub's current [Actions billing policy](https://docs.github.com/en/billing/concepts/product-billing/github-actions). A public repository exposes the public batch state and configured target labels, but the state contains no bot token, chat ID, cookies, or personal details.

The commands below require [GitHub CLI](https://cli.github.com/). Use a new repository name if `icai-seat-monitor` already exists:

```powershell
gh auth login
git init -b main
git add .
git commit -m "Add ICAI seat monitoring automation"
gh repo create icai-seat-monitor --public --source . --remote origin --push
gh secret set TELEGRAM_BOT_TOKEN
gh secret set TELEGRAM_CHAT_ID
gh workflow enable check-seats.yml
gh workflow run check-seats.yml -f dry_run=true
gh run list --workflow check-seats.yml --limit 5
```

The two `gh secret set` commands securely prompt for values. Do not put credential literals into commands. Alternatively create an empty repository on GitHub, push these files using its instructions, then add the same secrets under **Settings → Secrets and variables → Actions → Secrets**.

Under **Settings → Actions → General**, ensure Actions and the workflow's requested `contents: write` permission are permitted by repository/organization policy. The monitoring job needs that permission to commit **only** `data/seat_state.json` using the temporary `GITHUB_TOKEN`; you do not create a personal access token. Other permissions are not requested. Required reviews or branch rules that reject bot commits must be resolved for the intended state branch before enabling alerts. No force-push or protection bypass is attempted.

In **Actions → Check ICAI seats → Run workflow**, select the default branch. Run once with `dry_run` checked, inspect the six/current batch records, then run with it unchecked to enable normal monitoring. CLI equivalent:

```powershell
gh workflow run check-seats.yml -f dry_run=false
gh run list --workflow check-seats.yml --limit 5
# Replace RUN_ID with an ID from the list:
gh run view RUN_ID --log
```

The workflow file must be on the default branch for scheduling. Manual execution on another branch is deliberately skipped to prevent separate state histories. For a fork, enable Actions and the scheduled workflow explicitly. Pushes/PRs also run offline unit tests through `.github/workflows/tests.yml` with no secrets.

Scheduling is enabled by the committed workflow and runs without your computer. Logs and success/failure status appear under **Actions**. The script exits `0` on successful checks, including valid zero availability or an explicit empty result; scraping, delivery, and persistence failures exit `1`. Watch failed-run emails or GitHub notifications so monitoring failures are noticed independently of Telegram.

## Checking interval and limitations

Edit `.github/workflows/check-seats.yml`:

| Approximate interval | UTC cron |
| --- | --- |
| 15 minutes (default) | `7,22,37,52 * * * *` |
| 30 minutes | `7,37 * * * *` |
| 60 minutes | `7 * * * *` |

GitHub schedules are **best-effort**: runs can be delayed or dropped during high load. They do not provide exact execution times or instant detection. Seats that open and close between checks can be missed. Jobs share one concurrency group with `cancel-in-progress: false` and have a 12-minute timeout; GitHub may replace older pending jobs when several accumulate. See [scheduled event behavior](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).

Public scheduled workflows may be disabled after 60 days without repository activity. Inspect Actions regularly and re-enable if needed; unchanged-state runs intentionally do not make keepalive commits. Private repositories consume the account's included compute allowance, shared with other workloads. At 15-minute intervals this is approximately 2,880 job starts per 30 days, so private-repository use can exhaust the free allowance. Check the current billing page and your usage rather than assuming that every deployment is free. Use 30/60-minute checks if appropriate. The application requires no paid services.

## Configuration

`.env` is for local execution. GitHub Actions uses its workflow environment, repository secrets, and optional repository variables. Changing your local `.env` does not change the deployed workflow.

| Variable | Default / use |
| --- | --- |
| `ICAI_URL` | Official HTTPS launch batch URL; only the verified official hosts/path are accepted |
| `DEFAULT_REGION` | `Central` |
| `DEFAULT_POU` | `JAIPUR` |
| `DEFAULT_COURSE` | `Advanced (ICITSS) MCS Course` |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Required for enabled alerts; GitHub Actions Secrets |
| `TELEGRAM_NOTIFICATIONS_ENABLED` | `true`; `false` saves observations/pending alerts without sending |
| `NOTIFY_ON_SEAT_INCREASE` | `true`; controls positive-to-higher-positive alerts |
| `TIMEZONE` | `Asia/Kolkata`; extraction timestamps; alert timestamps always use Asia/Kolkata |
| `LOG_LEVEL` | `INFO`; structured JSON logs |
| `REQUEST_TIMEOUT` | `30` seconds read, up to 10 seconds connect; permitted range 1–120 |
| `MAX_RETRIES` | `3` additional tries, permitted range 0–5 |
| `HTTP_TRUST_ENV` | `true`; honors machine proxy/certificate configuration |
| `STATE_BACKEND` | `local` for development; workflow sets `github` |
| `STATE_PATH` | `data/local_state.json`; local backend only |
| `STATE_BRANCH` | `main` locally; workflow sets repository default branch |
| `GITHUB_REPOSITORY`, `GITHUB_TOKEN` | Automatically supplied in Actions; required for GitHub backend |

Booleans accept `true` or `false`, ignoring case. Repository **Variables** for `DEFAULT_REGION`, `DEFAULT_POU`, `DEFAULT_COURSE`, `TELEGRAM_NOTIFICATIONS_ENABLED`, and `NOTIFY_ON_SEAT_INCREASE` are wired into the workflow. To override another setting in Actions, add it to the workflow's `env` block. Keep credentials in Secrets.

Additional targets are additive to the default. Edit `config.json` using exact current visible labels; do not enter guessed numeric option values:

```json
{
  "targets": [
    {
      "region": "Central",
      "pou": "JAIPUR",
      "course": "AICITSS - Advanced Information Technology"
    }
  ]
}
```

That course label was verified in the live dropdown; the example's batch availability was not checked. Duplicate combinations are normalized and deduplicated. Unknown labels fail with a selection error. Run `--dry-run` before committing configuration changes. Targets are checked sequentially, three HTTP requests each before pagination, using cookies and fresh hidden fields within one session. Keep the target count small enough for the job timeout and respectful use of the public site.

## Monitoring and state behavior

The parser extracts every displayed batch's number, integer seat count, start/end dates, timing, POU, course, open-for value, region, and check timestamp. `--dry-run` prints the full records. Table order is irrelevant. WebForms numeric pager links, if present, are discovered and followed, with a safety limit and checks against repeated/skipped pages.

| Previous seats | Current seats | Outcome |
| --- | --- | --- |
| Unseen / 0 | 0 | Save observation, no alert |
| Unseen / 0 | Positive | Alert |
| Positive | Same | Skip confirmed duplicate |
| 2 | 5 | Alert if increase notifications enabled |
| 5 | 2 | Save decrease, no new alert |
| Positive | 0 | Reset; a subsequent opening alerts again |
| Failed pending alert | Still positive | Retry with current seat count |
| Failed pending alert | 0 | Cancel stale alert |

With notifications disabled, eligible alerts remain pending; re-enabling sends them only if the batch is still observed with seats. Absent rows, explicit empty results, and failed scrapes do not imply that previously seen batches have zero seats. A pending alert is only sent for a fresh positive batch in the current response.

Each key is a JSON composite of normalized region/POU/course and the preserved batch identifier. State stores one small record per batch: latest seats, pending flag, last confirmed notification seat count, end date, and state-change timestamp. It does not retain snapshots, secrets, or cookies. Unobserved batches are pruned 30 days after completion.

On GitHub Actions, the [Contents API](https://docs.github.com/en/rest/repos/contents#create-or-update-file-contents) reads `data/seat_state.json` from the **current branch tip**, independent of the workflow checkout. It commits only real changes, using the file SHA to detect stale writers. No git merge, force-push, or arbitrary conflict resolution is used. A transient branch conflict is retried only if the state file is unchanged. A changed remote state fails safely for review/rerun. Uncertain write results are read back before retrying, avoiding duplicate commits when the first write succeeded.

Pending observations are committed before any alert. Each Telegram-confirmed delivery is committed before the next message. Partial delivery failures retain pending flags and return failure status while preserving successful deliveries. An initial discovery/opening can require one pending-state commit plus one confirmation commit per sent message; unchanged 15-minute polls create no commits. `last_checked_at` is freshly extracted on every check, but is not rewritten into persistent state merely to update the clock. Local state uses an atomic replace with file flushing.

Missing local state initializes a new history with a warning. Missing/inaccessible GitHub state and corrupted state **stop alerts** rather than silently resetting deduplication. Restore the last valid state from repository history. For an intentional fresh deployment, the tracked starter file is `{"version": 1, "batches": {}}`; resetting history may alert again for all currently positive batches.

There is no atomic transaction between Telegram and GitHub: a crash or lost network response after Telegram accepts a message but before its confirmation is saved can cause a duplicate on a later check. The Bot API offers no idempotency key for `sendMessage`. This system suppresses normal repeated notifications and minimizes the delivery gap, but cannot guarantee exactly-once delivery across those two services. Do not run independent copies concurrently against the same destination.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| No alerts, job succeeds | Inspect `--dry-run` results; zero seats are expected to be silent; unchanged positive seats may already be notified |
| No scheduled runs | Confirm default-branch workflow, Actions enabled, 60-day inactivity rule, billing allowance, and GitHub scheduling delays |
| Network connection refused on this managed Windows host | Its machine proxy was unusable during development. For an environment that permits direct access, set `$env:HTTP_TRUST_ENV='false'` for that shell and retry; do not disable TLS verification |
| TLS certificate failure | Fix the trusted CA/proxy certificate configuration; never use `verify=False` |
| HTTP 403, CAPTCHA, login page, changed controls | Stop and inspect the public page manually; no protection bypass or automatic login is attempted |
| POU/course selection error | Check exact live dropdown labels, region relationship, and user-agent rendering; use `--dry-run` |
| Missing results / malformed seats | Inspect website availability and changes; the script preserves state and exits failure |
| Telegram HTTP 401/403/400 | Check token, chat ID, private `/start`, channel admin posting permission, and bot removal/blocking |
| Telegram rate limiting / timeouts | Bounded exponential backoff honors short retry delays; long waits defer to a later run; delivery stays pending |
| No chat IDs from helper | Send a fresh private/channel message; ensure another consumer/webhook is not using the bot |
| GitHub state 404 | Check tracked state file, default branch, repository identity, and token contents permission; no silent reinitialization |
| State write denied / 409 / 422 | Check repository rules and permissions; inspect concurrent edits, then rerun; no stale state is overwritten |
| Corrupt state | Restore the previous valid JSON from history before enabling alerts; keep a copy if investigating |
| Job timeout | Reduce targets, inspect downtime/retries, and adjust the timeout deliberately if needed |

Requests have bounded retries with exponential backoff for transient faults. HTTP 429 `Retry-After` is respected; long requests to wait are not retried early. Telegram read/connection failures with ambiguous delivery are left pending instead of blindly resending within the same run. A later scheduled run rechecks current availability. Logs omit raw network exceptions and response bodies to prevent token leakage.

## Optional migration to an existing VPS

Disable the GitHub schedule first. Copy the **latest remote** `data/seat_state.json` to the VPS as `data/local_state.json`, install Python 3.12 and `requirements.txt`, set `STATE_BACKEND=local`, and store Telegram settings in a restricted `.env` (`chmod 600 .env`). Keep only one scheduler active. The program remains a one-shot job; no application server is needed.

Example Linux crontab after installing the project and virtual environment at `/opt/icai-seat-monitor`:

```cron
7,22,37,52 * * * * cd /opt/icai-seat-monitor && /usr/bin/flock -n /opt/icai-seat-monitor/monitor.lock /opt/icai-seat-monitor/.venv/bin/python -m src.main >> /opt/icai-seat-monitor/monitor.log 2>&1
```

Back up the local state, configure log rotation, and monitor cron failures. VPS hosting is outside the default free GitHub Actions deployment.
