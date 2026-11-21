# Ohio Gas Price Forecast: ARCHITECTURE

_Pack written 2026-11-21 (Kyle's local time, UTC-5) by Grok Bot for Kyle Burke. Built from real files, git state and bot transcripts; anything not verified is marked **unknown**. Re-check live state before acting._

- Python 3.12: `gasdata.py` (downloads EIA `.xls` history + AAA state/metro averages), `model.py` (direct multi-horizon ridge regression), `forecast.py` (CLI, `--all`, `--zip`, `--area`, `--weeks`), `dashboard.py` (HTML output), `scheduler.py` (optional local scheduling). `data/` is committed history (for example `aaa_metro_history.csv`).
- GitHub Actions → Pages publishes `output/dashboard.html` as `index.html`.
