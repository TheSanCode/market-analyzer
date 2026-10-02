# Market Watcher

Market Watcher is a local research application that scans a configurable stock and sector ETF universe for buying-pressure proxies and ranks candidates as **BUY**, **WATCH**, or **SELL/AVOID**. It does not read or depend on brokerage accounts, place orders, or make trades.

## Windows 11 / PowerShell setup

From the repository directory, run:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If PowerShell blocks activation, use `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, then activate the environment again.

## Try the demo

The bundled deterministic synthetic dataset covers 280 daily sessions for eight instruments. Demo output is clearly marked and is **not live market data**.

```powershell
python -m market_watcher.cli scan --config config.example.yaml --demo
streamlit run market_watcher/dashboard.py
```

The dashboard opens locally. Select **Use bundled demo data**, run a scan, and explore the sector rankings, score breakdown, chart, history, and CSV/Markdown downloads.

## Scan live data

Install and start [Ollama](https://ollama.com/) locally if you want optional explanations. Pull the default model with `ollama pull qwen3:8b`; scans and rankings do not require Ollama.

```powershell
python -m market_watcher.cli scan --config config.example.yaml
python -m market_watcher.cli scan --config config.example.yaml --explain
python -m market_watcher.cli history --config config.example.yaml
```

Live daily prices and volume are fetched from Yahoo Finance using `yfinance`. The default universe dynamically reads current S&P 500 constituents and sectors from Wikipedia and adds the sector ETFs in `config.example.yaml`. To use a fixed list instead, set `include_sp500: false` and edit `stocks` (optional `stock_sectors` map). The configurable benchmark defaults to SPY. Data retrieval depends on third-party availability and may be delayed, incomplete, rate-limited, or revised. Batch requests use bounded exponential retries; a limited number of missing tickers receive individual retries (`fallback_ticker_limit`). Missing tickers are reported; quotes older than the configured `stale_after_days` are excluded from scoring.

The local Streamlit dashboard defaults to the demo toggle. The CLI defaults to live mode unless `--demo` is passed. The `data_source` field, dashboard banner, and report distinguish demo from live scans.

## Configuration and outputs

Edit `config.example.yaml` or copy it to a private local config file to change:

- Stocks, current S&P 500 inclusion, sector ETFs, and benchmark.
- Download period, quote staleness window, retries, and delay.
- Factor weights, BUY/WATCH thresholds, and minimum indicator coverage.
- Ollama endpoint and model (defaults to `http://localhost:11434` and `qwen3:8b`).
- SQLite database and report locations.
- Backtest holding period, fees, and slippage.

Each scan is stored in SQLite (`market_watcher.sqlite` by default) and exports a CSV and Markdown report under `reports/`. Optional evidence providers for actual ETF net flows, SEC disclosures, options flow, and news are extension interfaces only; they explicitly report unavailable until connected. Price and volume measures are **buying-pressure proxies, not confirmed institutional inflows**. No ETF flows, trades, disclosures, or news are invented.

Ollama is called directly over its local HTTP API at `/api/chat`. Only a candidate's calculated indicators, score factors, and missing-factor list are sent for a concise explanation. Ollama explanations never affect rankings. If Ollama is unavailable, the scan and dashboard continue without explanations.

## CLI and historical evaluation

Run a historical evaluation with next-session execution assumptions:

```powershell
python -m market_watcher.cli evaluate --config config.example.yaml --demo
```

The evaluator computes each signal using data through that session's close, enters at the next session's open, and exits after the configured number of holding sessions. It applies configured round-trip fees and slippage and writes trade details and assumptions to `reports/backtest.json`. Future prices are used only for trade outcomes, not signal calculations. This simple evaluator does not model portfolio sizing, capacity, dividends, taxes, or market impact. Using today's S&P 500 constituents in historical evaluation introduces survivorship bias; the report calls this out.

For Windows Task Scheduler, create a basic task with the desired schedule and set:

- **Program/script:** the virtual environment's `python.exe` (for example, `C:\path\to\market-analyzer\.venv\Scripts\python.exe`)
- **Add arguments:** `-m market_watcher.cli scan --config C:\path\to\market-analyzer\config.example.yaml`
- **Start in:** the repository directory

This runs a live scan. Add `--demo` only for a synthetic-data test task. Keep the computer awake and ensure network access for Yahoo Finance; Ollama is only needed if `--explain` is specified.

## Indicators and scoring

The scanner calculates 20-day relative volume (latest 20 sessions versus the preceding 20 sessions), 20/60-session returns and benchmark-relative returns, 50/200-session moving averages, RSI, ATR, OBV, and Chaikin Money Flow. A configurable Python rule score exposes every factor's raw value, points, weight, and contribution. Missing factors are omitted and the score is normalized over available factor weights; candidates below the minimum factor coverage are SELL/AVOID. Scores are **heuristic rankings, not probabilities of profit or investment advice**.

## Tests

```powershell
python -m pytest
```
