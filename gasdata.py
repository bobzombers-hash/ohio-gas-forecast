"""Data access: EIA weekly history (no API key) + AAA current Ohio metro averages."""
import io, json, math, os, re, time, urllib.request, urllib.parse
from datetime import datetime
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"

EIA_SERIES = {
    # key: (EIA series id, description, url)
    "ohio":      ("EMM_EPMR_PTE_SOH_DPG", "Ohio regular retail gasoline, weekly ($/gal)"),
    "cleveland": ("EMM_EPMR_PTE_YCLE_DPG", "Cleveland regular retail gasoline, weekly ($/gal)"),
    "midwest":   ("EMM_EPMR_PTE_R20_DPG", "Midwest (PADD 2) regular retail gasoline, weekly ($/gal)"),
    "gc_spot":   ("EER_EPMRU_PF4_RGC_DPG", "U.S. Gulf Coast conventional gasoline spot, weekly ($/gal)"),
    "nyh_spot":  ("EER_EPMRU_PF4_Y35NY_DPG", "NY Harbor conventional gasoline spot, weekly ($/gal)"),
    "wti":       ("RWTC", "WTI Cushing crude spot, weekly ($/bbl)"),
    "brent":     ("RBRTE", "Brent crude spot, weekly ($/bbl)"),
}

def eia_url(sid):
    return f"https://www.eia.gov/dnav/pet/hist_xls/{sid}w.xls"

def _get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()

def fetch_eia(refresh=True, log=print):
    os.makedirs(DATA, exist_ok=True)
    out, status = {}, {}
    for key, (sid, desc) in EIA_SERIES.items():
        path = os.path.join(DATA, f"{sid}.xls")
        err = None
        if refresh:
            try:
                b = _get(eia_url(sid))
                if len(b) < 1000:
                    raise ValueError(f"empty response ({len(b)} bytes)")
                tmp = path + ".tmp"
                open(tmp, "wb").write(b)
                pd.read_excel(tmp, sheet_name="Data 1", skiprows=2)  # validate before replacing last good copy
                os.replace(tmp, path)
            except Exception as e:
                err = str(e)
                if os.path.exists(path + ".tmp"):
                    os.remove(path + ".tmp")
        if not os.path.exists(path):
            status[key] = f"FAILED: {err}"
            continue
        df = pd.read_excel(path, sheet_name="Data 1", skiprows=2)
        s = pd.Series(df.iloc[:, 1].values, index=pd.to_datetime(df.iloc[:, 0]), name=key).dropna().astype(float)
        out[key] = s
        status[key] = ("cached copy (refresh failed: %s)" % err) if err else "ok"
        status[key] += f"; {s.index[0].date()} to {s.index[-1].date()}, last={s.iloc[-1]:.3f}"
    return out, status

# ---------------- AAA current metro averages ----------------
AAA_URL = "https://gasprices.aaa.com/?state=OH"

def _money(x):
    return float(x.replace("$", "").replace(",", "")) if x and "$" in x else None

def fetch_aaa(log=print):
    """Return dict with state + metro averages (regular/mid/premium/diesel, current/yesterday/week/month/year)."""
    html = _get(AAA_URL).decode("utf-8", "replace")
    asof = re.search(r"Price as of\s*([0-9/]+)", html)
    asof = datetime.strptime(asof.group(1), "%m/%d/%y").date().isoformat() if asof else None

    def parse_table(chunk):
        rows = {}
        for tr in re.findall(r"<tr>(.*?)</tr>", chunk, re.S):
            tds = [re.sub(r"<[^>]+>", "", t).strip() for t in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
            if len(tds) >= 5 and tds[0].endswith("Avg."):
                rows[tds[0].replace(" Avg.", "").lower()] = {
                    "regular": _money(tds[1]), "mid": _money(tds[2]),
                    "premium": _money(tds[3]), "diesel": _money(tds[4])}
        return rows

    # statewide table = first table after the "Ohio average gas prices" header
    i = html.find("average gas prices")
    state = parse_table(html[i:html.find("</table>", i)])
    metros = {}
    for m in re.finditer(r'<h3 data-cost="[^"]*" data-title>([^<]+)</h3>(.*?)</table>', html, re.S):
        metros[m.group(1).strip()] = parse_table(m.group(2))
    if not state.get("current") or len(metros) < 5:
        raise ValueError("AAA page layout changed or incomplete (could not parse state/metro tables)")
    return {"asof": asof, "source": AAA_URL, "state": state, "metros": metros}

def save_aaa_snapshot(aaa):
    """Append today's AAA metro regular prices to a local CSV so local history builds up over time."""
    path = os.path.join(DATA, "aaa_metro_history.csv")
    rows = [{"date": aaa["asof"], "area": "Ohio (state)", "regular": aaa["state"]["current"]["regular"]}]
    rows += [{"date": aaa["asof"], "area": k, "regular": v["current"]["regular"]} for k, v in aaa["metros"].items()]
    new = pd.DataFrame(rows)
    if os.path.exists(path):
        old = pd.read_csv(path)
        new = pd.concat([old[old.date != aaa["asof"]], new])
    new.to_csv(path, index=False)
    tmp = os.path.join(DATA, "aaa_latest.json.tmp")
    json.dump(aaa, open(tmp, "w"), indent=1)
    os.replace(tmp, os.path.join(DATA, "aaa_latest.json"))
    return path

# ---------------- area -> AAA metro ----------------
# Approximate centroids of the AAA Ohio metro areas (lat, lon)
METRO_COORDS = {
    "Akron": (41.081, -81.519), "Canton-Massillon": (40.799, -81.379),
    "Cleveland-Lorain-Elyria": (41.499, -81.694), "Columbus": (39.961, -82.999),
    "Dayton": (39.759, -84.192), "Toledo": (41.654, -83.536),
    "Youngstown-Warren": (41.100, -80.650), "Cincinnati (OH only)": (39.103, -84.512),
    "Belmont County": (40.030, -80.990), "Lawerence County": (38.600, -82.550),
    "Lima": (40.743, -84.105), "Mansfield": (40.759, -82.516),
    "Springfield": (39.924, -83.809), "Steubenville-Weirton (OH only)": (40.370, -80.634),
}
ALIASES = {"cleveland": "Cleveland-Lorain-Elyria", "lorain": "Cleveland-Lorain-Elyria", "elyria": "Cleveland-Lorain-Elyria",
           "cincinnati": "Cincinnati (OH only)", "youngstown": "Youngstown-Warren", "warren": "Youngstown-Warren",
           "canton": "Canton-Massillon", "massillon": "Canton-Massillon", "steubenville": "Steubenville-Weirton (OH only)",
           "lawrence county": "Lawerence County", "ironton": "Lawerence County", "belmont": "Belmont County"}

def _hav(a, b):
    R = 3958.8
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = math.sin((la2-la1)/2)**2 + math.cos(la1)*math.cos(la2)*math.sin((lo2-lo1)/2)**2
    return 2*R*math.asin(math.sqrt(h))

def resolve_area(area=None, zipcode=None, metros=None):
    """Return (metro_name, label, distance_miles, how)."""
    names = list(metros) if metros else list(METRO_COORDS)
    if area and not zipcode:
        a = area.strip().lower()
        for n in names:
            if a == n.lower() or a == n.lower().split(" (")[0]:
                return n, area, 0.0, "exact AAA metro match"
        if a in ALIASES and ALIASES[a] in names:
            return ALIASES[a], area, 0.0, "alias of AAA metro"
    # geocode
    try:
        if zipcode:
            j = json.loads(_get(f"https://api.zippopotam.us/us/{zipcode}"))
            p = j["places"][0]
            if p["state abbreviation"] != "OH":
                raise SystemExit(f"ZIP {zipcode} is in {p['state']}, not Ohio.")
            pt, label = (float(p["latitude"]), float(p["longitude"])), f"{zipcode} ({p['place name']}, OH)"
        else:
            q = urllib.parse.urlencode({"q": f"{area}, Ohio", "format": "json", "limit": 1, "countrycodes": "us"})
            req = urllib.request.Request(f"https://nominatim.openstreetmap.org/search?{q}",
                                         headers={"User-Agent": "ohio-gas-forecast/1.0 (personal use)"})
            j = json.loads(urllib.request.urlopen(req, timeout=20).read())
            if not j or "Ohio" not in j[0]["display_name"]:
                raise SystemExit(f"Could not locate '{area}' in Ohio.")
            pt, label = (float(j[0]["lat"]), float(j[0]["lon"])), j[0]["display_name"].split(", United States")[0]
    except SystemExit:
        raise
    except Exception as e:
        raise SystemExit(f"Geocoding failed ({e}). Try one of: {', '.join(names)}")
    best = min(names, key=lambda n: _hav(pt, METRO_COORDS[n]))
    return best, label, _hav(pt, METRO_COORDS[best]), "nearest AAA metro by distance"

def fetch_daily_spot():
    """Latest daily wholesale prices (display only; the model uses weekly data)."""
    out = {}
    for key, sid in {"gc_spot": "EER_EPMRU_PF4_RGC_DPG", "nyh_spot": "EER_EPMRU_PF4_Y35NY_DPG",
                     "wti": "RWTC", "brent": "RBRTE"}.items():
        try:
            b = _get(f"https://www.eia.gov/dnav/pet/hist_xls/{sid}d.xls")
            df = pd.read_excel(io.BytesIO(b), sheet_name="Data 1", skiprows=2).dropna()
            df = df[pd.to_datetime(df.iloc[:, 0]) >= pd.Timestamp.now() - pd.Timedelta(days=21)]
            out[key] = [(str(pd.Timestamp(d).date()), float(v)) for d, v in zip(df.iloc[:, 0], df.iloc[:, 1])]
        except Exception as e:
            out[key] = f"FAILED: {e}"
    return out
