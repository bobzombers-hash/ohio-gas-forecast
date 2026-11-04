"""Self-contained dashboard (output/dashboard.html, published as index.html) (charts embedded as base64 PNG, no network needed)."""
import base64, html, io, os
from datetime import datetime
import pandas as pd

import gasdata

def _png_b64(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110)
    return base64.b64encode(buf.getvalue()).decode()

def metro_history_chart(path_csv):
    """Chart of locally logged AAA metro prices (grows with each scheduled run)."""
    if not os.path.exists(path_csv):
        return None, 0
    h = pd.read_csv(path_csv)
    n_dates = h.date.nunique()
    if n_dates < 2:
        return None, n_dates
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    h["date"] = pd.to_datetime(h.date)
    piv = h.pivot_table(index="date", columns="area", values="regular")
    fig, ax = plt.subplots(figsize=(11, 4.5))
    main = ["Ohio (state)", "Columbus", "Cleveland-Lorain-Elyria", "Cincinnati (OH only)", "Dayton", "Toledo", "Akron", "Youngstown-Warren"]
    for c in piv.columns:
        if c in main:
            ax.plot(piv.index, piv[c], marker="o", ms=3, lw=2.2 if c == "Ohio (state)" else 1.2,
                    color="black" if c == "Ohio (state)" else None, label=c)
    ax.set_ylabel("$ per gallon, regular"); ax.grid(alpha=0.25); ax.legend(fontsize=8, ncol=4)
    ax.set_title(f"AAA metro averages logged by the daily job ({n_dates} days)")
    fig.autofmt_xdate(); fig.tight_layout()
    b = _png_b64(fig); plt.close(fig)
    return b, n_dates

def build(results, chart_png_path, out_path):
    e = html.escape
    st = results["status"]
    aaa = results.get("aaa") or {}
    fc = pd.DataFrame(results["state_forecast"])
    chart = base64.b64encode(open(chart_png_path, "rb").read()).decode() if chart_png_path and os.path.exists(chart_png_path) else None
    mh, mh_n = metro_history_chart(os.path.join(gasdata.DATA, "aaa_metro_history.csv"))
    warn = [f"{k}: {v}" for k, v in st.items() if not v.startswith("ok")]
    if results.get("aaa_note"):
        warn.append(results["aaa_note"])
    from datetime import datetime, timezone, date
    from zoneinfo import ZoneInfo
    now_et = datetime.now(timezone.utc).astimezone(ZoneInfo("America/New_York"))
    updated = now_et.strftime("%b %d, %Y %I:%M %p %Z").replace(" 0", " ")
    try:
        age = (now_et.date() - date.fromisoformat(str(results["eia_last_week"])[:10])).days
        if age > 13:
            warn.append(f"EIA weekly data is {age} days old (normally <= 7)")
    except Exception:
        pass
    try:
        aage = (now_et.date() - date.fromisoformat(str(aaa.get("asof"))[:10])).days
        if aage > 2:
            warn.append(f"AAA prices are {aage} days old")
    except Exception:
        pass

    def money(v):
        return f"${v:.3f}" if v is not None else "–"

    def cents(v):
        return f"{'+' if v >= 0 else '−'}{abs(v) * 100:.1f}¢"

    state_rows = "".join(
        f"<tr><td>{str(r.week_of)[:10]}</td><td>{r.h}</td><td><b>{money(r.forecast)}</b></td>"
        f"<td>{money(r.lo80)} – {money(r.hi80)}</td><td>{money(r.lo95)} – {money(r.hi95)}</td></tr>" for r in fc.itertuples())
    metro_rows = ""
    for a in sorted(results.get("areas", []), key=lambda a: -a["aaa"]["current"]):
        f = a["forecast"]; m = a["aaa"]
        cells = "".join(f"<td><b>{money(f[i]['forecast'])}</b><br><span class=s>{money(f[i]['lo80'])}–{money(f[i]['hi80'])}</span></td>"
                        for i in (0, 3, 7) if i < len(f))
        metro_rows += (f"<tr><td>{e(a['metro'])}</td><td>{money(m['current'])}</td><td>{cents(m['current'] - m['week_ago'])}</td>"
                       f"<td>{cents(m['offset_now'])}</td>{cells}</tr>")
    hdr = "".join(f"<th>{str(f[i]['week_of'])[:10]}<br><span class=s>{i + 1} wk, 80% range</span></th>"
                  for i in (0, 3, 7) for f in [results['state_forecast']] if i < len(f))
    bt_rows = "".join(f"<tr><td>{b['h']} wk</td><td>${b['MAE_model']:.3f}</td><td>${b['MAE_naive']:.3f}</td>"
                      f"<td>{b['skill_vs_naive_%']:.0f}%</td><td>{b['dir_hit'] * 100:.0f}%</td></tr>" for b in results["backtest"])
    ds = results.get("daily_spot") or {}
    gc = ds.get("gc_spot") if isinstance(ds.get("gc_spot"), list) else None
    wti = ds.get("wti") if isinstance(ds.get("wti"), list) else None
    spot_line = ""
    if gc:
        spot_line += f"Gulf Coast wholesale gasoline {money(gc[-1][1])}/gal on {gc[-1][0]}. "
    if wti:
        spot_line += f"WTI crude ${wti[-1][1]:.2f}/bbl on {wti[-1][0]}."
    state_now = aaa.get("state", {}).get("current", {}).get("regular") if aaa else None
    state_wk = aaa.get("state", {}).get("week ago", {}).get("regular") if aaa else None

    doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Ohio Gas Price Forecast</title>
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;max-width:1100px;margin:24px auto;padding:0 16px;color:#1d1d1f;background:#fff}}
@media (prefers-color-scheme: dark){{body{{background:#161618;color:#e8e8ea}} table td,table th{{border-color:#333!important}} .card{{border-color:#333!important}} img{{background:#fff}}}}
h1{{margin-bottom:4px}} .muted,.s{{color:#888;font-size:12px}} .card{{border:1px solid #ddd;border-radius:12px;padding:14px 18px;margin:16px 0}}
.kpis{{display:flex;flex-wrap:wrap;gap:12px}} .kpi{{flex:1 1 200px;border:1px solid #ddd;border-radius:12px;padding:12px}} .kpi b{{font-size:26px;display:block}}
table{{border-collapse:collapse;width:100%;font-size:14px}} td,th{{border-bottom:1px solid #eee;padding:6px 8px;text-align:right;vertical-align:top}} td:first-child,th:first-child{{text-align:left}}
img{{max-width:100%;border-radius:8px}} .warn{{background:#fff4e5;color:#7a4b00;border-radius:8px;padding:8px 12px}} .scroll{{overflow-x:auto}}
</style></head><body>
<h1>Ohio Gas Price Forecast</h1>
<div class="muted">Last updated {e(updated)} · EIA data through week of {e(results['eia_last_week'])} · AAA prices as of {e(str(aaa.get('asof', 'n/a')))}</div>
{('<p class="warn">Some sources could not be refreshed this run; last good copies were used: ' + e('; '.join(warn)) + '</p>') if warn else ''}
<div class="kpis card" style="border:none;padding:0">
 <div class="kpi"><span class="s">AAA Ohio avg, {e(str(aaa.get('asof', '')))}</span><b>{money(state_now)}</b><span class="s">{cents(state_now - state_wk) + ' vs week ago' if state_now and state_wk else ''}</span></div>
 <div class="kpi"><span class="s">EIA Ohio avg, week of {e(results['eia_last_week'])}</span><b>{money(results['eia_ohio_last'])}</b></div>
 <div class="kpi"><span class="s">Forecast, {str(fc.week_of.iloc[min(3, len(fc) - 1)])[:10]}</span><b>{money(fc.forecast.iloc[min(3, len(fc) - 1)])}</b><span class="s">80%: {money(fc.lo80.iloc[min(3, len(fc) - 1)])} – {money(fc.hi80.iloc[min(3, len(fc) - 1)])}</span></div>
 <div class="kpi"><span class="s">Forecast, {str(fc.week_of.iloc[-1])[:10]}</span><b>{money(fc.forecast.iloc[-1])}</b><span class="s">80%: {money(fc.lo80.iloc[-1])} – {money(fc.hi80.iloc[-1])}</span></div>
</div>
<p class="muted">{e(spot_line)}</p>
{f'<div class="card"><img alt="history and forecast" src="data:image/png;base64,{chart}"></div>' if chart else ''}
<div class="card scroll"><h3>Forecast by metro (weekly average, regular)</h3>
<table><tr><th>Metro</th><th>AAA now</th><th>Week chg</th><th>vs Ohio</th>{hdr}</tr>{metro_rows}</table>
<p class="s">Neighborhood/ZIP lookups use the nearest metro: <code>.venv/bin/python forecast.py --zip 43215</code></p></div>
<div class="card scroll"><h3>Ohio statewide forecast (EIA basis)</h3>
<table><tr><th>Week of</th><th>Weeks ahead</th><th>Forecast</th><th>80% range</th><th>95% range</th></tr>{state_rows}</table></div>
{f'<div class="card"><img alt="metro history" src="data:image/png;base64,{mh}"></div>' if mh else f'<p class="muted">Local metro history: {mh_n} day(s) logged so far; a chart appears after 2+ days of scheduled runs.</p>'}
<div class="card scroll"><h3>Backtest accuracy (walk-forward 2016 – present)</h3>
<table><tr><th>Horizon</th><th>Model MAE</th><th>No-change MAE</th><th>Skill</th><th>Direction right</th></tr>{bt_rows}</table>
<p class="s">MAE = mean absolute error, $/gal. 80% band empirical coverage over the last 5 years: {results['coverage80_last5y'] * 100:.0f}%.</p></div>
<div class="card"><h3>Caveats</h3><ul>
<li>Forecasts are weekly averages; Ohio stations swing 20–40¢ in a day on price cycles.</li>
<li>Per-neighborhood history isn't free: areas use the nearest AAA metro's offset from the state average.</li>
<li>Shocks (refinery outages, storms, crude spikes) can't be foreseen from these inputs. Not financial advice.</li></ul></div>
<div class="card"><h3>Data sources</h3><ul>
{''.join(f'<li>EIA {e(k)}: {e(v)} — <span class="s">{e(gasdata.eia_url(gasdata.EIA_SERIES[k][0]))}</span></li>' for k, v in st.items())}
<li>AAA Ohio metro averages — <span class="s">{e(gasdata.AAA_URL)}</span></li></ul></div>
</body></html>"""
    tmp = out_path + ".tmp"
    open(tmp, "w", encoding="utf-8").write(doc)
    os.replace(tmp, out_path)
    return out_path
