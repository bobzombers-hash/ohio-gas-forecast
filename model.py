"""Direct multi-horizon regression forecast of Ohio weekly retail regular gasoline.

For each horizon h (weeks), fit:  y(t+h) - y(t) = b0 + b1*gap_dev(t) + c0*dSpot(t) + c1*dSpot(t-1) + d*dRetail(t)
                                  + e*y_ma4dev(t) + g*dMidwest(t) + seasonal(sin/cos day-of-year)
where gap(t) = retail(t) - wholesale gasoline spot(t) (avg of Gulf Coast & NY Harbor; margin + taxes,
measured vs its 52-week mean; mean-reverts), dSpot = weekly change in wholesale spot (pass-through lags),
y_ma4dev = Ohio price vs its 4-week mean (price-cycle position), dmw0 = Midwest retail weekly change,
plus annual seasonality. All aligned so only
data published by the retail date is used (spot week ending Friday -> retail Monday +3 days).
Ridge-regularised least squares in numpy; trained on a rolling window.
"""
import numpy as np
import pandas as pd

HORIZONS = list(range(1, 9))
TRAIN_YEARS = 10
RIDGE = 1.0

def build_frame(s):
    y = s["ohio"]
    idx = y.index
    def align(x):  # spot dated Friday -> available at next Monday
        x = x.copy(); x.index = x.index + pd.Timedelta(days=3)
        return x.reindex(idx, method="ffill", limit=1)
    spot = align(s["gc_spot"])
    if "nyh_spot" in s:
        spot = 0.5 * spot + 0.5 * align(s["nyh_spot"]).fillna(spot)
    brent = align(s["brent"]) if "brent" in s else align(s["wti"])
    f = pd.DataFrame({"y": y, "spot": spot, "brent": brent})
    f["gap"] = f.y - f.spot
    f["gap_dev"] = f.gap - f.gap.rolling(52, min_periods=26).mean()
    for k in range(4):
        f[f"dspot{k}"] = f.spot.diff().shift(k)
    f["dy0"] = f.y.diff()
    f["dy1"] = f.y.diff().shift(1)
    f["dbrent4"] = (f.brent.diff(4)) / 42.0  # $/bbl -> $/gal (kept for display/experiments)
    f["y_ma4dev"] = f.y - f.y.rolling(4).mean()      # Ohio price-cycle position (spike/trough)
    if "midwest" in s:
        f["dmw0"] = s["midwest"].reindex(idx).diff()  # regional retail momentum
    else:
        f["dmw0"] = 0.0
    w = 2 * np.pi * idx.dayofyear / 365.25
    f["s1"], f["c1"], f["s2"], f["c2"] = np.sin(w), np.cos(w), np.sin(2*w), np.cos(2*w)
    return f

# Feature set chosen by walk-forward backtest (2016-2026) among a handful of candidates.
FEATS = ["gap_dev", "dspot0", "dspot1", "dy0", "y_ma4dev", "dmw0", "s1", "c1"]

def _fit(X, Y, ridge=RIDGE):
    mu, sd = X.mean(0), X.std(0) + 1e-9
    Z = np.c_[np.ones(len(X)), (X - mu) / sd]
    P = ridge * np.eye(Z.shape[1]); P[0, 0] = 0
    beta = np.linalg.solve(Z.T @ Z + P, Z.T @ Y)
    return beta, mu, sd

def _pred(m, X):
    beta, mu, sd = m
    return np.c_[np.ones(len(X)), (X - mu) / sd] @ beta

def targets(f, h):
    return f.y.shift(-h) - f.y

def fit_all(f, end=None, feats=FEATS):
    """Fit one model per horizon on data up to `end` (inclusive origin date, targets must be observed)."""
    models = {}
    for h in HORIZONS:
        d = f.assign(t=targets(f, h)).dropna(subset=feats + ["t"])
        if end is not None:
            d = d[d.index + pd.Timedelta(weeks=h) <= end]   # target must be known at `end`
        d = d[d.index > d.index.max() - pd.DateOffset(years=TRAIN_YEARS)]
        models[h] = _fit(d[feats].values, d["t"].values)
    return models

def backtest(f, start="2016-01-01", refit_every=4, feats=FEATS):
    """Walk-forward: at each origin, refit (every N weeks) using only past data, forecast 1..8 weeks."""
    rows = []
    origins = f.dropna(subset=feats).index
    origins = origins[origins >= start]
    models = None
    for i, t in enumerate(origins):
        if models is None or i % refit_every == 0:
            models = fit_all(f, end=t, feats=feats)
        x = f.loc[[t], feats].values
        for h in HORIZONS:
            ti = f.index.get_loc(t) + h
            if ti >= len(f): continue
            actual = f.y.iloc[ti]
            pred = f.y.loc[t] + _pred(models[h], x)[0]
            rows.append({"origin": t, "h": h, "base": f.y.loc[t], "pred": pred, "naive": f.y.loc[t], "actual": actual})
    bt = pd.DataFrame(rows)
    bt["err"] = bt.actual - bt.pred
    bt["err_naive"] = bt.actual - bt.naive
    return bt

def summarize_backtest(bt):
    g = bt.groupby("h")
    s = pd.DataFrame({
        "n": g.size(),
        "MAE_model": g.err.apply(lambda e: e.abs().mean()),
        "MAE_naive": g.err_naive.apply(lambda e: e.abs().mean()),
        "dir_hit": g.apply(lambda d: (np.sign(d.pred - d.base) == np.sign(d.actual - d.base)).mean(), include_groups=False),
    })
    s["skill_vs_naive_%"] = 100 * (1 - s.MAE_model / s.MAE_naive)
    return s

def interval_quantiles(bt, recent_years=5):
    """Empirical out-of-sample error quantiles per horizon (last N years) -> 80% & 95% intervals."""
    cut = bt.origin.max() - pd.DateOffset(years=recent_years)
    q = bt[bt.origin >= cut].groupby("h").err.quantile([0.025, 0.10, 0.90, 0.975]).unstack()
    q.columns = ["q025", "q10", "q90", "q975"]
    return q

def forecast(f, models, q):
    t = f.dropna(subset=FEATS).index.max()
    x = f.loc[[t], FEATS].values
    base = f.y.loc[t]
    rows = []
    for h in HORIZONS:
        p = base + _pred(models[h], x)[0]
        rows.append({"week_of": (t + pd.Timedelta(weeks=h)).date(), "h": h, "forecast": p,
                     "lo80": p + q.loc[h, "q10"], "hi80": p + q.loc[h, "q90"],
                     "lo95": p + q.loc[h, "q025"], "hi95": p + q.loc[h, "q975"]})
    return t, base, pd.DataFrame(rows)
