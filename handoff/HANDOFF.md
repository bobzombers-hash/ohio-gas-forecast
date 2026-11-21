# Ohio Gas Price Forecast: HANDOFF (start here)

_Pack written 2026-11-21 (Kyle's local time, UTC-5) by Grok Bot for Kyle Burke. Built from real files, git state and bot transcripts; anything not verified is marked **unknown**. Re-check live state before acting._

**What it is:** Forecasts regular gasoline prices across Ohio 1 to 8 weeks ahead, statewide and for 14 AAA metro areas, from public EIA price history and AAA daily averages, using a ridge-regression model with walk-forward backtesting. Publishes a live dashboard.

**Built by / owner bot:** Builder **unknown** (first commit 2026-11-03; probably Primary Bot or a deleted bot).

**Kind:** Python forecaster + daily GitHub Actions + GitHub Pages dashboard (public repo). **Overall state:** Live and updating itself: the daily GitHub Actions run succeeded on Nov 19, 20 and 21, 2026. Dashboard: https://bobzombers-hash.github.io/ohio-gas-forecast/

## Where everything lives
- GitHub (public): https://github.com/bobzombers-hash/ohio-gas-forecast , `main` (Actions commits refreshed `data/` daily, so always pull first).
- Bot box `/workspace/ohio-gas-site/` (clone, clean but behind the daily data commits) and `/workspace/ohio-gas/` (earlier local version).
- Tower `C:\Users\bobzo\ohio-gas\` (local install with `.venv`, `data`, `output`, `logs`; newest file 2026-11-03; not a git clone) and `ohio-gas.zip`.
- Master pack: `C:\Users\bobzo\Handoff\ohio-gas-forecast\` (docs only; the code is on GitHub).

## Reading order
1. `HANDOFF.md`: this file: what the project is, where everything lives, reading order
2. `STATUS.md`: what works, what is broken, what is waiting on Kyle, next steps
3. `ARCHITECTURE.md`: stack, folders, data flow
4. `RUNBOOK.md`: how to install, run, test, build and release
5. `DECISIONS.md`: dated decisions and the reasons, so you do not reopen them
6. `CHAT_SUMMARY.md`: what Kyle asked for, by date, with his words quoted
7. `SECRETS.md`: which secrets exist and where they live (names only, never values)


## First things to do as a new agent
1. Read the project's own README (copied into the master pack `reference/`).
2. Run its tests (see RUNBOOK.md) before changing anything.
3. Ask Kyle what he wants next; this project has no recorded open request.

## Kyle's standing rules (apply to every project)
- Ask Kyle **before**: git pushes, opening/merging PRs that deploy, destructive or production database changes, external posts, anything that costs money (billing, paid signups, paid builds), App Store / Play submissions.
- No paid services or new subscriptions without his explicit OK for that specific purchase. Build paid-vendor features switched off.
- Never print, paste or commit secrets. Ask for them through a secure form or vault, never in chat.
- Verify with evidence before saying something is done (test output, screenshot, log). Plan first on complex work.
- Add a one-line lesson to the project's AGENTS.md / log after every mistake or correction.
- Explain things in plain language. Kyle is a solo builder; do the work end to end and come back with a clear ask.
- An approval is specific: a past "yes" is not permission for the next push/deploy/build.
