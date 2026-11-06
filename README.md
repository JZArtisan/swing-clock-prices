# swing-clock-prices
Daily closes (and OHLCV) for THE SWING CLOCK's roster, fetched by GitHub Actions at 05:15 UTC (13:15 SGT) from Yahoo's v8 chart
endpoint (stooq fallback). `latest/fetch-raw.txt` is in the vault's pipe format and is consumed unchanged by
`model/fetch_prices.py save`; `latest/SHA256` carries the integrity hashes. `symbols.json` is the roster's symbol map
(key → Yahoo symbol, currency, exchange zone) — edit it only through a Swing Clock strategy round. No secrets, no third-party
actions beyond `actions/checkout`; the workflow has `contents: write` on this repository only.
