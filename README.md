# Market Watcher

Market Watcher is a local research application that scans a configurable stock and sector ETF universe for buying-pressure proxies and ranks candidates as **BUY**, **WATCH**, or **SELL/AVOID**. It operates independently of any brokerage account, places no orders, and executes no trades.

---

## 🚀 Quick Start & Windows 11 / PowerShell Setup

From the repository directory, run the following commands in PowerShell to set up your environment:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

> **Note:** If PowerShell blocks script activation, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` first, then activate the environment again.

---

## 🎮 Try the Demo

The bundled deterministic synthetic dataset covers 280 daily sessions for eight instruments. Demo output is clearly marked and represents **simulated data, not live market data**.

```powershell
python -m market_watcher.cli scan --config config.example.yaml --demo
streamlit run market_watcher/dashboard.py
```

The dashboard opens locally in your browser. Select **Use bundled demo data**, run a scan, and explore sector rankings, score breakdowns, charts, scan history, and CSV/Markdown downloads.

---

## 📊 Scan Live Data

Live daily prices and volume are fetched from Yahoo Finance using `yfinance`. 

```powershell
python -m market_watcher.cli scan --config config.example.yaml
python -m market_watcher.cli scan --config config.example.yaml --explain
python -m market_watcher.cli history --config config.example.yaml
```

### LLM Explanations (Ollama)
Install and start [Ollama](https://ollama.com/) locally to enable optional AI-driven explanations. Pull the default model with `ollama pull qwen3:8b`. 
* Scans and rankings **do not** require Ollama.
* Ollama is called directly over its local HTTP API at `http://localhost:11434/api/chat`. Only calculated indicators, score factors, and missing-factor lists are sent for concise insights. Ollama never affects scoring or rankings.

### Data Handling & Limitations
* **Universe:** The default universe dynamically reads current S&P 500 constituents and sectors from Wikipedia, adding the sector ETFs defined in `config.example.yaml`. Set `include_sp500: false` and edit `stocks` for a fixed list.
* **Resilience:** Batch requests use bounded exponential retries. A limited number of missing tickers receive individual retries (`fallback_ticker_limit`). 
* **Staleness:** Quotes older than the configured `stale_after_days` are excluded from scoring.
* **Disclaimer:** Price and volume measures are **buying-pressure proxies, not confirmed institutional inflows**. No ETF flows, trades, disclosures, or news are fabricated.

---

## ⚙️ Configuration and Outputs

Edit `config.example.yaml` or copy it to a private local configuration file to customize:
* Stocks, S&P 500 inclusion, sector ETFs, and benchmarks.
* Download periods, quote staleness windows, retries, and delays.
* Factor weights, BUY/WATCH thresholds, and minimum indicator coverage.
* Ollama endpoint and model settings.
* SQLite database location and report directories.
* Backtest holding periods, fees, and slippage.

### Persistence & Reports
Each scan is saved in SQLite (`market_watcher.sqlite` by default) and exports CSV and Markdown reports under `reports/`. Optional evidence providers for actual ETF net flows, SEC disclosures, options flow, and news act as extension interfaces and report as unavailable until connected.

---

## 📈 Historical Evaluation & Automation

### Run Historical Backtests
Evaluate historical performance using next-session execution assumptions:
```powershell
python -m market_watcher.cli evaluate --config config.example.yaml --demo
```
This computes signals using data through a session's close, enters at the next session's open, and exits after the configured holding sessions. Results and assumptions are saved to `reports/backtest.json`. 

> [!WARNING]
> * This simple evaluator does not model portfolio sizing, capacity, dividends, taxes, or market impact.
> * Using today's S&P 500 constituents in historical evaluations introduces **survivorship bias**, which is explicitly noted in the report.

### Windows Task Scheduler Setup
To automate scans using Windows Task Scheduler, create a basic task with your desired schedule and configure:
* **Program/script:** Path to your virtual environment's Python executable (e.g., `C:\path\to\market-analyzer\.venv\Scripts\python.exe`)
* **Add arguments:** `-m market_watcher.cli scan --config C:\path\to\market-analyzer\config.example.yaml`
* **Start in:** The repository directory

---

## 📐 Technical Indicators & Scoring

The scanner computes:
* **20-day relative volume** (latest 20 sessions versus preceding 20 sessions)
* **20/60-session returns** and benchmark-relative returns
* **50/200-session moving averages**
* **RSI, ATR, OBV, and Chaikin Money Flow**

Scoring relies on transparent Python rules that expose every factor's raw value, points, weight, and contribution. Missing factors are safely omitted, normalizing the score over available weights. Candidates failing minimum factor coverage are designated **SELL/AVOID**. 

> Scores represent heuristic rankings, **not probabilities of profit or investment advice**.

---

## 🧪 Testing

Run the test suite using pytest:

```powershell
python -m pytest
