#!/usr/bin/env python3
"""Ohio gas price analyzer + near-term forecaster.

Examples:
  python forecast.py --area "Columbus"
  python forecast.py --zip 43215
  python forecast.py --area "Shaker Heights"
  python forecast.py --all              # every AAA Ohio metro
  python forecast.py --area Dayton --no-refresh   # use cached data

Self-updating:
  python forecast.py --install-schedule [--every daily|weekly]   # register recurring job for this OS
  python forecast.py --status
  python forecast.py --uninstall-schedule
  python forecast.py --scheduled [--force]   # what the job runs: refresh, all metros, dashboard
"""
import argparse, contextlib, json, os, sys, traceback
from datetime import datetime
import numpy as np
import pandas as pd

import gasdata, model

OUT = os.path.join(gasdata.HERE, "output")
os.environ.setdefault("MPLCONFIGDIR", os.path.join(gasdata.HERE, ".mplcache"))
os.environ.setdefault("MPLBACKEND", "Agg")
Z80, Z95 = 1.2816, 1.96

def offset_dynamics(s):
    """Use EIA Cleveland vs Ohio (the only free long metro history) to learn how a metro's
    offset from the state average persists: offset(t+h) - mu = phi_h * (offset(t) - mu) + noise."""
    off = (s["cleveland"] - s["ohio"]).dropna()
    off = off[off.index >= off.index.max() - pd.DateOffset(years=10)]
    res = {}
    for h in model.HORIZONS:
        a, b = off.iloc[:-h].values, off.iloc[h:].values
        mu = off.mean()
        phi = float(np.clip(np.polyfit(a - mu, b - mu, 1)[0], 0, 1))
        resid = (b - mu) - phi * (a - mu)
        res[h] = {"phi": phi, "sd": float(resid.std())}
    return res, float(off.mean()), float(off.std())

def metro_table(aaa):
    st = aaa["state"]
    rows = []
    for name, m in aaa["metros"].items():
        offs = [m[k]["regular"] - st[k]["regular"] for k in ("current", "yesterday", "week ago", "month ago", "year ago")
                if k in m and k in st and m[k]["regular"] and st[k]["regular"]]
        rows.append({"metro": name, "current": m["current"]["regular"], "yesterday": m["yesterday"]["regular"],
                     "week_ago": m["week ago"]["regular"], "month_ago": m["month ago"]["regular"],
                     "year_ago": m["year ago"]["regular"],
                     "offset_now": m["current"]["regular"] - st["current"]["regular"],
                     "offset_typical": float(np.mean(offs))})
    return pd.DataFrame(rows).set_index("metro")

def metro_forecast(fc, mrow, dyn):
    """Statewide forecast + metro offset (current offset decaying toward the metro's typical offset)."""
    out = fc[["week_of", "h"]].copy()
    hw80_s = (fc.hi80 - fc.lo80) / 2; hw95_s = (fc.hi95 - fc.lo95) / 2
    ctr80 = (fc.hi80 + fc.lo80) / 2 - fc.forecast; ctr95 = (fc.hi95 + fc.lo95) / 2 - fc.forecast
    offs = np.array([mrow.offset_typical + dyn[h]["phi"] * (mrow.offset_now - mrow.offset_typical) for h in fc.h])
    sd = np.array([dyn[h]["sd"] for h in fc.h])
    out["offset"] = offs
    out["forecast"] = fc.forecast.values + offs
    hw80 = np.sqrt(hw80_s.values**2 + (Z80 * sd)**2); hw95 = np.sqrt(hw95_s.values**2 + (Z95 * sd)**2)
    out["lo80"] = out.forecast + ctr80.values - hw80; out["hi80"] = out.forecast + ctr80.values + hw80
    out["lo95"] = out.forecast + ctr95.values - hw95; out["hi95"] = out.forecast + ctr95.values + hw95
    return out

def make_chart(s, fc_state, area_label, fc_area, aaa, path):
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(11, 5.5), dpi=130)
    start = s["ohio"].index.max() - pd.DateOffset(years=3)
    oh = s["ohio"][s["ohio"].index >= start]; cl = s["cleveland"][s["cleveland"].index >= start]
    ax.plot(oh.index, oh.values, color="#1f5fbf", lw=1.6, label="Ohio avg, regular (EIA weekly)")
    ax.plot(cl.index, cl.values, color="#999999", lw=1.0, alpha=0.8, label="Cleveland (EIA weekly)")
    d = pd.to_datetime(fc_area.week_of)
    ax.fill_between(d, fc_area.lo95, fc_area.hi95, color="#e8a317", alpha=0.18, label="95% interval")
    ax.fill_between(d, fc_area.lo80, fc_area.hi80, color="#e8a317", alpha=0.35, label="80% interval")
    ax.plot(d, fc_area.forecast, color="#c77800", lw=2, marker="o", ms=3, label=f"Forecast: {area_label}")
    if fc_area is not fc_state:
        ax.plot(pd.to_datetime(fc_state.week_of), fc_state.forecast, color="#1f5fbf", lw=1.2, ls="--", label="Forecast: Ohio avg")
    if aaa:
        ax.scatter([pd.Timestamp(aaa["asof"])], [aaa["state"]["current"]["regular"]], color="black", zorder=5, s=18,
                   label=f"AAA Ohio avg {aaa['asof']}")
    ax.set_ylabel("$ per gallon, regular"); ax.grid(alpha=0.25)
    ax.set_title(f"Ohio gasoline: 3-year history and 8-week forecast ({area_label})")
    ax.legend(loc="upper left", fontsize=8, ncol=2)
    fig.tight_layout(); fig.savefig(path); plt.close(fig)

def run(a):
    """Refresh data, fit, forecast. Returns (results, chart_png, fresh) where fresh = core sources refreshed live."""
    os.makedirs(OUT, exist_ok=True)

    print("== Refreshing data ==")
    s, status = gasdata.fetch_eia(refresh=not a.no_refresh)
    for k, v in status.items():
        print(f"  EIA {k:10s} {v}")
    if "ohio" not in s or "gc_spot" not in s:
        sys.exit("Required EIA series unavailable; cannot forecast.")
    aaa, aaa_note = None, None
    try:
        if a.no_refresh:
            raise RuntimeError("--no-refresh")
        aaa = gasdata.fetch_aaa()
        gasdata.save_aaa_snapshot(aaa)
        print(f"  AAA Ohio   ok; as of {aaa['asof']}, state avg ${aaa['state']['current']['regular']:.3f}, {len(aaa['metros'])} metros")
    except Exception as e:
        cached = os.path.join(gasdata.DATA, "aaa_latest.json")
        if os.path.exists(cached):
            aaa = json.load(open(cached)); print(f"  AAA Ohio   not refreshed ({e}); using cached snapshot from {aaa['asof']}")
            aaa_note = f"AAA: not refreshed ({e}); using snapshot from {aaa['asof']}"
        else:
            print(f"  AAA Ohio   FAILED ({e}); metro offsets unavailable, statewide forecast only")

    print("\n== Fitting model + walk-forward backtest (2016-present) ==")
    f = model.build_frame(s)
    bt = model.backtest(f)
    summ = model.summarize_backtest(bt)
    q = model.interval_quantiles(bt)
    models = model.fit_all(f)
    t0, base, fc = model.forecast(f, models, q)
    fc = fc[fc.h <= a.weeks].reset_index(drop=True)
    # interval coverage check over last 5y
    cut = bt.origin.max() - pd.DateOffset(years=5)
    rb = bt[bt.origin >= cut].merge(q, left_on="h", right_index=True)
    cov80 = ((rb.err >= rb.q10) & (rb.err <= rb.q90)).mean()
    print(summ.round(3).to_string())
    print(f"(MAE in $/gal; naive = 'price stays where it is'; dir_hit = share of correct up/down calls)")

    print(f"\n== Latest data ==")
    print(f"  EIA Ohio avg week of {t0.date()}: ${base:.3f}   (Cleveland ${s['cleveland'].iloc[-1]:.3f}, Midwest ${s['midwest'].iloc[-1]:.3f})")
    print(f"  WTI ${s['wti'].iloc[-1]:.2f}/bbl, Brent ${s['brent'].iloc[-1]:.2f}/bbl, Gulf Coast gasoline spot ${s['gc_spot'].iloc[-1]:.3f}/gal (week ending {s['wti'].index[-1].date()})")

    daily = gasdata.fetch_daily_spot() if not a.no_refresh else {}
    if isinstance(daily.get("gc_spot"), list) and daily["gc_spot"]:
        g = daily["gc_spot"]; w = daily.get("wti") if isinstance(daily.get("wti"), list) else None
        print(f"  Latest daily: Gulf Coast gasoline ${g[-1][1]:.3f}/gal on {g[-1][0]} (vs ${g[0][1]:.3f} on {g[0][0]})"
              + (f", WTI ${w[-1][1]:.2f} on {w[-1][0]}" if w else ""))
    mt = metro_table(aaa) if aaa else None
    dyn, off_mu, off_sd = offset_dynamics(s)

    targets = []
    if a.all and mt is not None:
        targets = [(m, m, 0.0, "AAA metro") for m in mt.index]
    elif a.area or a.zip:
        metro, label, dist, how = gasdata.resolve_area(a.area, a.zip, list(mt.index) if mt is not None else None)
        targets = [(metro, label, dist, how)]

    print("\n== Ohio statewide forecast (EIA basis) ==")
    print(fc.round(3).to_string(index=False))

    results = {"generated": datetime.now().isoformat(timespec="seconds"), "eia_last_week": str(t0.date()),
               "eia_ohio_last": base, "status": status, "daily_spot": daily, "aaa": aaa, "aaa_note": aaa_note,
               "backtest": summ.reset_index().to_dict("records"), "coverage80_last5y": cov80,
               "state_forecast": json.loads(fc.to_json(orient="records", date_format="iso")), "areas": []}
    area_fc_for_chart, chart_label = fc, "Ohio avg"
    for metro, label, dist, how in targets:
        if mt is None:
            print(f"\n(No AAA metro data; '{label}' gets the statewide forecast.)"); break
        r = mt.loc[metro]
        mf = metro_forecast(fc, r, dyn)
        print(f"\n== {label} -> AAA metro '{metro}' ({how}{', %.0f mi' % dist if dist else ''}) ==")
        print(f"  AAA {aaa['asof']}: ${r.current:.3f} now | yesterday ${r.yesterday:.3f} | week ago ${r.week_ago:.3f} | month ago ${r.month_ago:.3f} | year ago ${r.year_ago:.3f}")
        print(f"  Offset vs Ohio avg: now {r.offset_now:+.3f}, typical {r.offset_typical:+.3f}")
        print(mf.round(3).to_string(index=False))
        results["areas"].append({"label": label, "metro": metro, "how": how, "distance_mi": dist,
                                 "aaa": r.to_dict(), "forecast": json.loads(mf.to_json(orient="records", date_format="iso"))})
        area_fc_for_chart, chart_label = mf, label

    slug = "".join(c if c.isalnum() else "_" for c in (chart_label if len(targets) <= 1 else "all_metros"))
    png = os.path.join(OUT, f"forecast_{slug}.png")
    make_chart(s, fc, chart_label if len(targets) <= 1 else "Ohio avg", area_fc_for_chart if len(targets) <= 1 else fc, aaa, png)
    results["chart"] = png
    json.dump(results, open(a.json, "w"), indent=1, default=str)
    print(f"\nChart saved: {png}\nResults JSON: {a.json}")
    print(f"80% interval empirical coverage (last 5y backtest): {cov80:.0%}")
    print("\nCaveats: per-neighborhood history isn't free; local = statewide model + AAA metro offset. "
          "Ohio prices cycle sharply (jumps of 20-40c in a day are common), so single-day prices can sit outside these weekly-average bands. "
          "Not financial advice.")
    fresh = (not a.no_refresh) and status.get("ohio", "").startswith("ok") and aaa_note is None and aaa is not None
    return results, png, fresh


class _Tee:
    def __init__(self, *streams): self.streams = streams
    def write(self, x):
        for s in self.streams: s.write(x)
    def flush(self):
        for s in self.streams: s.flush()


def _online():
    import urllib.request
    try:
        urllib.request.urlopen(urllib.request.Request(gasdata.eia_url("EMM_EPMR_PTE_SOH_DPG"), method="HEAD",
                                                      headers={"User-Agent": gasdata.UA}), timeout=15)
        return True
    except Exception:
        return False


def scheduled(force=False):
    """Entry point for the OS scheduler: guard, lock, log, refresh, forecast all metros, rebuild dashboard."""
    import scheduler, dashboard
    os.makedirs(scheduler.LOGS, exist_ok=True)
    logp = os.path.join(scheduler.LOGS, "run.log")
    if os.path.exists(logp) and os.path.getsize(logp) > 2_000_000:   # simple rotation
        os.replace(logp, logp + ".1")
    with open(logp, "a", encoding="utf-8", errors="replace") as log:
        stamp = datetime.now().isoformat(timespec="seconds")
        ok, why = scheduler.due(force)
        if not ok:
            log.write(f"[{stamp}] skip: {why}\n"); return 0
        lock = os.path.join(gasdata.DATA, ".run.lock")
        if os.path.exists(lock) and (datetime.now().timestamp() - os.path.getmtime(lock)) < 3600:
            log.write(f"[{stamp}] skip: another run in progress\n"); return 0
        if not _online():
            log.write(f"[{stamp}] skip: offline (EIA unreachable); keeping last good data, will retry next hour\n")
            scheduler.record(False, "offline"); return 0
        open(lock, "w").write(str(os.getpid()))
        try:
            log.write(f"\n[{stamp}] ===== scheduled run ({why}) =====\n"); log.flush()
            ns = argparse.Namespace(area=None, zip=None, all=True, no_refresh=False, weeks=8,
                                    json=os.path.join(OUT, "results.json"))
            with contextlib.redirect_stdout(_Tee(log)):
                results, png, fresh = run(ns)
            dash = dashboard.build(results, png, os.path.join(OUT, "dashboard.html"))
            scheduler.record(fresh, "" if fresh else "some sources stale; used cached copies")
            log.write(f"[{datetime.now().isoformat(timespec='seconds')}] done: dashboard={dash} fresh={fresh}\n")
            print(f"Dashboard updated: {dash}")
            return 0
        except Exception as e:
            log.write(f"[{datetime.now().isoformat(timespec='seconds')}] ERROR: {e}\n{traceback.format_exc()}\n")
            scheduler.record(False, str(e)); return 1
        finally:
            if os.path.exists(lock): os.remove(lock)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--area", help="Ohio city, neighborhood, or AAA metro name")
    ap.add_argument("--zip", help="Ohio ZIP code")
    ap.add_argument("--all", action="store_true", help="forecast every AAA Ohio metro (also rebuilds dashboard.html)")
    ap.add_argument("--no-refresh", action="store_true", help="use cached data, skip downloads")
    ap.add_argument("--weeks", type=int, default=8, help="horizon in weeks (1-8)")
    ap.add_argument("--json", default=os.path.join(OUT, "results.json"), help="where to save machine-readable results")
    ap.add_argument("--install-schedule", action="store_true", help="register the recurring self-update job for this OS")
    ap.add_argument("--uninstall-schedule", action="store_true", help="remove the recurring job")
    ap.add_argument("--status", action="store_true", help="show schedule + last run status")
    ap.add_argument("--every", choices=["daily", "weekly"], default="daily", help="refresh frequency for --install-schedule")
    ap.add_argument("--scheduled", action="store_true", help="run as the scheduler does (guarded, logged, all metros, dashboard)")
    ap.add_argument("--force", action="store_true", help="with --scheduled: ignore the freshness guard")
    a = ap.parse_args()
    if a.install_schedule or a.uninstall_schedule or a.status:
        import scheduler
        if a.install_schedule: scheduler.install(a.every)
        if a.uninstall_schedule: scheduler.uninstall()
        if a.status: scheduler.status()
        return
    if a.scheduled:
        sys.exit(scheduled(a.force))
    results, png, _ = run(a)
    if a.all:
        import dashboard
        print("Dashboard:", dashboard.build(results, png, os.path.join(OUT, "dashboard.html")))

if __name__ == "__main__":
    main()
