# Ohio Gas Price Forecast

Live dashboard: **https://bobzombers-hash.github.io/ohio-gas-forecast/**

A small Python program that forecasts regular gasoline prices across Ohio 1–8 weeks ahead,
statewide and for 14 AAA metro areas (Cleveland, Columbus, Cincinnati, Toledo, Akron, Dayton, …).

## How it works
- **Data:** U.S. EIA weekly retail prices (Ohio, Cleveland, Midwest), Gulf Coast / NY Harbor wholesale
  gasoline and WTI / Brent crude (public `.xls` history files, no API key), plus today's AAA
  Ohio state and metro averages from gasprices.aaa.com.
- **Model:** direct multi-horizon ridge regression on wholesale-to-retail gap, spot momentum, recent
  retail trend and seasonality; 10-year rolling training window. Walk-forward backtest since 2016:
  MAE ≈ $0.10 at 1 week, $0.17 at 4 weeks, $0.23 at 8 weeks (10–15% better than "no change").
  80% ranges come from empirical backtest errors.
- **Metros:** statewide forecast + each metro's AAA offset, decaying toward its typical offset.

## How the site updates
`.github/workflows/update.yml` runs daily at 14:17 UTC (~10 AM Eastern) and on demand
(Actions → *Update forecast and publish site* → *Run workflow*). It:
1. installs Python 3.12 + `requirements.txt`;
2. runs `python forecast.py --all` (refresh EIA + AAA, forecast all metros, build `output/dashboard.html`);
3. commits refreshed files in `data/` back to the repo, so `data/aaa_metro_history.csv` grows daily
   (skipped when nothing changed);
4. publishes the dashboard as `index.html` to GitHub Pages.

If a source can't be reached, the last committed copy is used and the dashboard shows a
yellow "stale data" warning. Times are shown in Eastern time.

## Run locally
```bash
python3 -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python forecast.py --all                 # all metros + output/dashboard.html
python forecast.py --zip 43215 --weeks 8 # one ZIP or city (--area "Dayton")
```
`scheduler.py` / `forecast.py --install-schedule` can also schedule it on your own Mac/Linux/Windows
machine; not needed for the GitHub version.

## Caveats
Forecasts are weekly averages; Ohio prices cycle sharply, so single-day pump prices can fall outside
the ranges. Neighborhood-level history isn't free, so "local" = statewide model + metro offset.
Not financial advice. Data © EIA (public domain) and AAA.

## License
MIT
