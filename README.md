# Market Watcher (market-analyzer)

Market Watcher scans a stock universe you configure for **price/volume proxies of buying
or selling pressure**. It ranks research candidates as **BUY**, **WATCH** or **SELL/AVOID**
using a transparent, rules-based score. A local Ollama model can optionally explain the
calculated evidence in plain language.

> **Important**
> - Signals are price/volume **proxies** for buying pressure. They are **not** verified
>   institutional money flows. The app has no news, fund-flow or order-book data and does not make any up.
> - Labels are research candidates **independent of your holdings**. The app never reads a portfolio.
> - There is **no broker connection** and **no trade execution**. Nothing here is investment advice.
> - Live data comes from Yahoo Finance through the unofficial `yfinance` library. This data may be delayed, incomplete or rate-limited.

## Features

- **Indicators** (`market_watcher/indicators.py`):
  - relative volume against the mean of the *preceding* N sessions (the current session is excluded)
  - 20- and 63-session returns relative to a benchmark (aligned on common dates)
  - SMA50/SMA200
  - Wilder RSI and ATR
  - OBV, plus a normalised OBV trend
  - Chaikin Money Flow
- **Scoring** (`market_watcher/scoring.py`):
  - Six weighted components, each with a sub-score from -1 to 1 and a written reason.
  - The final score runs from -100 to 100. An ATR volatility penalty applies.
  - A BUY is capped at WATCH when the data is stale or too many inputs are missing.
  - All weights and thresholds live in the `ScoringConfig` dataclass. You can override them in TOML.
- **Data handling** (`market_watcher/data.py`):
  - Tickers are fetched one at a time with retries, so one failure never stops the scan.
  - Duplicate rows, time zones, missing closes, volume, high or low values and negative volume are cleaned up and reported as warnings.
  - Data is flagged as stale after `max_stale_days`. Short histories are labelled `INSUFFICIENT DATA`.
  - If the benchmark is missing, only the relative-strength component is skipped.
- **Offline demo**:
  - `market_watcher/demo_data/simulated_ohlcv.csv` holds a **SIMULATED** dataset. All tickers are named `DEMO-*`.
  - Scenarios: accumulation, distribution, range-bound, spike, short history, stale feed, gappy feed, plus a missing ticker.
  - Regenerate it with `python -m market_watcher.demo`. Every output is labelled as simulated.
- **SQLite history** (`data/market_watcher.db`) and **CSV/Markdown export** (`exports/`).
- **CLI**:
  - `scan`: run a scan
  - `history`: list saved scans, or one ticker's history
  - `export`: export a saved scan
  - `check-ollama`: test the local Ollama connection
- **Streamlit dashboard** (`app.py`):
  - rankings with label filters
  - scan, benchmark and per-ticker data timestamps
  - price with SMAs, volume, relative volume, RSI, CMF and OBV charts
  - evidence, risks, missing info and score history
  - on-demand Ollama explanations
  - CSV/Markdown downloads
- **Optional Ollama explanations** (`market_watcher/llm.py`):
  - Calls `POST http://localhost:11434/api/chat` with `qwen3:8b` by default.
  - The model only receives the calculated JSON evidence and is told not to invent news or flows.
  - It never influences scores. If Ollama is down or the model is missing, the scan continues without explanations.

## Install (Windows PowerShell)

You need Python 3.11 or newer from python.org (tick "Add python.exe to PATH") and Git.

```powershell
cd $HOME\source
git clone https://github.com/TheSanCode/market-analyzer.git
cd market-analyzer

py -3.12 -m venv .venv
# If activation is blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

Copy-Item config.example.toml config.toml   # then edit universe, benchmark, weights...
```

## Run

```powershell
# Offline demo with SIMULATED data (no internet or Ollama needed)
python -m market_watcher scan --demo --no-llm --export

# Live scan using config.toml (yfinance; Ollama explanations if reachable)
python -m market_watcher -c config.toml scan --export

# Other commands
python -m market_watcher -c config.toml scan --no-llm      # skip the LLM
python -m market_watcher -c config.toml history             # saved scans
python -m market_watcher -c config.toml history --ticker MSFT
python -m market_watcher -c config.toml export --scan-id 3  # latest if omitted
python -m market_watcher -c config.toml check-ollama --chat

# Dashboard (opens http://localhost:8501)
python -m streamlit run app.py
```

`scan` exits with code 0 when at least one ticker was analysed. It exits with 2 when every ticker failed and with 1 on a configuration error.
The dashboard reads `config.toml` by default. To use another file, set `$env:MARKET_WATCHER_CONFIG`.

## Configuration

See `config.example.toml`. Any setting you leave out falls back to the Python defaults in
`market_watcher/config.py` and `market_watcher/scoring.py`. Unknown keys and wrongly typed values are rejected.

How the score works:

- Each component maps one metric to a sub-score from -1 to 1. Its points are `weight × sub-score`.
- Score = 100 × sum(points) / sum(weights of components that had data). An ATR penalty applies when volatility is high.
- Labels:
  - score ≥ `buy_threshold`: BUY
  - score ≤ `avoid_threshold`: SELL/AVOID
  - otherwise: WATCH
- A BUY drops to WATCH when the data is stale or the weight coverage is below `min_weight_coverage`.
- Each component and its reason are stored with every result and shown in exports and the dashboard.

## Verify the Ollama connection locally

The automated tests mock every Ollama HTTP response. To check the real connection on your laptop:

```powershell
ollama pull qwen3:8b
ollama list                                   # qwen3:8b should be listed
# Ollama normally runs as a background app; otherwise start it with:  ollama serve

# 1) Raw API check
$body = @{ model = "qwen3:8b"; stream = $false; think = $false;
           messages = @(@{ role = "user"; content = "Reply with OK" }) } | ConvertTo-Json -Depth 5
Invoke-RestMethod -Uri http://localhost:11434/api/chat -Method Post -Body $body -ContentType "application/json"

# 2) Market Watcher check (/api/tags + a tiny chat)
python -m market_watcher check-ollama --chat

# 3) End-to-end: explanations on simulated data
python -m market_watcher scan --demo --export
```

If the check fails, the scan prints `LLM explanations disabled for this scan: ...` and carries on.
You can change the URL, model, timeout and `explain_top_n` in the `[ollama]` section.
qwen3 "thinking" output is turned off (`"think": false`) and any `<think>` blocks are removed.

## Schedule daily scans (Windows Task Scheduler)

`scripts\run_scan.ps1` runs a scan with `config.toml` and `--export`, and writes a log to `logs\`.

```powershell
$Repo = (Resolve-Path .).Path
$Action = New-ScheduledTaskAction -Execute "powershell.exe" `
  -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$Repo\scripts\run_scan.ps1`"" `
  -WorkingDirectory $Repo
# Weekdays, after the US close (22:30 local time here; adjust to your time zone)
$Trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 22:30
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1)
Register-ScheduledTask -TaskName "MarketWatcherScan" -Action $Action -Trigger $Trigger -Settings $Settings `
  -Description "Market Watcher daily scan (research only, no trading)"

Start-ScheduledTask -TaskName "MarketWatcherScan"     # test run now
Get-ScheduledTaskInfo -TaskName "MarketWatcherScan"   # LastTaskResult 0 = success
# Unregister-ScheduledTask -TaskName "MarketWatcherScan" -Confirm:$false
```

You can also set it up in the GUI: Task Scheduler → Create Task → Actions → Start a program.
Use `powershell.exe` with the same arguments and set "Start in" to the repository folder.

## Tests and checks

```powershell
python -m pip install pytest ruff
python -m pytest -q
ruff check .
```

The tests cover:

- indicator maths, including a reference Wilder RSI loop
- scoring rules and configuration
- provider failures, malformed, empty, stale and short data
- missing benchmark data
- SQLite round-trips and exports
- the CLI
- mocked Ollama success and failure paths

They need no network access, no Ollama and no Yahoo access.

## Limitations

- Yahoo Finance data through `yfinance` is unofficial, may be delayed and can break or be rate-limited. A failed ticker is recorded and skipped.
- Daily bars only. Relative volume compares the latest *completed* bar, so a scan during market hours sees a partial session.
- Staleness is measured in calendar days and ignores exchange holidays.
- Signals are heuristic proxies. There is no backtest, and the default weights are untuned starting points.
- The dashboard charts re-fetch current data, which can be newer than the data used in the scan you select. The caption shows both timestamps.

## License

Apache-2.0 (see `LICENSE`).
