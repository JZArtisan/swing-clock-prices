#!/usr/bin/env python3
"""Daily price fetch for THE SWING CLOCK (GitHub Actions). Standard library only.

Writes, in the vault's pipe format (identical to the browser snippet of model/fetch_prices.py r3):
  latest/fetch-raw.txt     KEY|YAHOO|CCY|TZ|YYYYMMDD:close,...   + a FETCH|yahoo-v8|<iso>|<rows>|fails:... trailer
  latest/ohlcv-raw.txt     KEY|YAHOO|CCY|TZ|YYYYMMDD:o;h;l;c;v,...  (for the DRUK port — high and volume)
  latest/SHA256            sha256 of each file, for the consumer's integrity check
  data/fetch-raw-<date>.txt, data/ohlcv-raw-<date>.txt   dated copies
Bar dates are stamped in the exchange's own zone, bar by bar (fetch_prices.py r3 / Q46). Closes rounded to 4 dp.
Yahoo first (cookie + crumb handshake, retries with back-off); stooq.com daily CSV as the per-symbol fallback.
"""
import json, sys, time, hashlib, datetime as D, urllib.request, urllib.parse, http.cookiejar, os
from zoneinfo import ZoneInfo

RANGE = os.environ.get("RANGE", "1mo")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
opener.addheaders = [("User-Agent", UA), ("Accept", "*/*")]

def get(url, timeout=30):
    with opener.open(url, timeout=timeout) as r:
        return r.status, r.read()

def crumb():
    try: get("https://fc.yahoo.com/")
    except Exception: pass
    for i in range(4):
        try:
            s, b = get("https://query2.finance.yahoo.com/v1/test/getcrumb")
            t = b.decode().strip()
            if s == 200 and t and "Too Many" not in t: return t
        except Exception as e: pass
        time.sleep(3 * (i + 1))
    return ""

def yahoo(sym, tz, cr):
    for host in ("query2", "query1"):
        for i in range(3):
            try:
                url = "https://%s.finance.yahoo.com/v8/finance/chart/%s?range=%s&interval=1d" % (host, urllib.parse.quote(sym, safe=""), RANGE)
                if cr: url += "&crumb=" + urllib.parse.quote(cr, safe="")
                s, b = get(url)
                j = json.loads(b); q = j["chart"]["result"][0]
                z = q["meta"].get("exchangeTimezoneName") or tz
                ts = q.get("timestamp") or []; qt = q["indicators"]["quote"][0]
                pts, ohlcv = [], []
                for k, t in enumerate(ts):
                    c = (qt.get("close") or [None]*len(ts))[k]
                    if c is None: continue
                    d = D.datetime.fromtimestamp(t, ZoneInfo(z)).strftime("%Y%m%d")
                    pts.append("%s:%s" % (d, fmt(c)))
                    o, h, l, v = [(qt.get(n) or [None]*len(ts))[k] for n in ("open", "high", "low", "volume")]
                    ohlcv.append("%s:%s;%s;%s;%s;%s" % (d, fmt(o), fmt(h), fmt(l), fmt(c), int(v or 0)))
                if not pts: raise ValueError("empty")
                return q["meta"].get("currency"), z, pts, ohlcv, "yahoo"
            except Exception as e:
                last = e; time.sleep(2 * (i + 1))
    raise last

STOOQ_SFX = {".T": ".jp", ".HK": ".hk", ".AX": ".au", ".L": ".uk", ".DE": ".de", ".SI": None, ".KS": None}
def stooq_symbol(sym):
    if "=" in sym or sym.startswith("^") or sym.endswith(".NYB"): return None
    for sfx, s2 in STOOQ_SFX.items():
        if sym.endswith(sfx): return None if s2 is None else sym[:-len(sfx)].lstrip("0") + s2 if sfx == ".HK" else sym[:-len(sfx)] + s2
    return sym.lower() + ".us"

def stooq(sym, tz):
    ss = stooq_symbol(sym)
    if not ss: raise ValueError("no stooq mapping")
    s, b = get("https://stooq.com/q/d/l/?s=%s&i=d" % ss)
    lines = b.decode().strip().splitlines()
    if len(lines) < 2 or not lines[0].startswith("Date"): raise ValueError("stooq empty")
    cutoff = (D.date.today() - D.timedelta(days={"1mo": 35, "3mo": 95, "6mo": 185, "1y": 370, "2y": 740}.get(RANGE, 35))).strftime("%Y-%m-%d")
    pts, ohlcv = [], []
    for l in lines[1:]:
        d, o, h, lo, c, v = (l.split(",") + [""] * 6)[:6]
        if d < cutoff or not c: continue
        dd = d.replace("-", "")
        pts.append("%s:%s" % (dd, fmt(float(c)))); ohlcv.append("%s:%s;%s;%s;%s;%s" % (dd, fmt(float(o or 0)), fmt(float(h or 0)), fmt(float(lo or 0)), fmt(float(c)), int(float(v or 0))))
    return None, tz, pts, ohlcv, "stooq"

def fmt(x):
    if x is None: return "0"
    r = round(float(x) * 10000) / 10000
    return ("%.4f" % r).rstrip("0").rstrip(".") if r != int(r) else str(int(r))

def main():
    m = json.load(open("symbols.json", encoding="utf-8"))
    cr = crumb()
    rows, orows, fails, src = [], [], [], {"yahoo": 0, "stooq": 0}
    for key, (sym, ccy, tz) in m.items():
        try:
            c2, z, pts, ohlcv, s = yahoo(sym, tz, cr)
        except Exception as e1:
            try: c2, z, pts, ohlcv, s = stooq(sym, tz)
            except Exception as e2:
                fails.append("%s:%s/%s" % (key, str(e1)[:30], str(e2)[:30])); continue
        src[s] += 1
        rows.append("|".join([key, sym, c2 or ccy, z, ",".join(pts)]))
        orows.append("|".join([key, sym, c2 or ccy, z, ",".join(ohlcv)]))
        time.sleep(0.4)
    iso = D.datetime.now(D.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    trailer = "FETCH|yahoo-v8|%s|%d|fails:%s" % (iso, len(rows), ";".join(fails) if fails else "none")
    note = "# sources yahoo=%d stooq=%d range=%s" % (src["yahoo"], src["stooq"], RANGE)
    os.makedirs("latest", exist_ok=True); os.makedirs("data", exist_ok=True)
    day = iso[:10]
    f1 = "\n".join(rows + [trailer]) + "\n"; f2 = "\n".join(orows + [trailer.replace("yahoo-v8", "yahoo-v8-ohlcv"), note]) + "\n"
    for p in ("latest/fetch-raw.txt", "data/fetch-raw-%s.txt" % day): open(p, "w", encoding="utf-8").write(f1)
    for p in ("latest/ohlcv-raw.txt", "data/ohlcv-raw-%s.txt" % day): open(p, "w", encoding="utf-8").write(f2)
    sha = lambda s: hashlib.sha256(s.encode("utf-8")).hexdigest()
    open("latest/SHA256", "w").write("%s  fetch-raw.txt\n%s  ohlcv-raw.txt\n" % (sha(f1), sha(f2)))
    print(trailer); print(note)
    if len(rows) < len(m) * 0.9: sys.exit("too many failures: %d of %d" % (len(fails), len(m)))

if __name__ == "__main__": main()
