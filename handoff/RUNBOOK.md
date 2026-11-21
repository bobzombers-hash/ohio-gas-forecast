# Ohio Gas Price Forecast: RUNBOOK

_Pack written 2026-11-21 (Kyle's local time, UTC-5) by Grok Bot for Kyle Burke. Built from real files, git state and bot transcripts; anything not verified is marked **unknown**. Re-check live state before acting._

```bash
python3 -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python forecast.py --all
python forecast.py --zip 43215 --weeks 8
```
Manual site refresh: GitHub → Actions → "Update forecast and publish site" → Run workflow.
