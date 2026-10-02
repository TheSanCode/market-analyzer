# Market Analyzer
AI-based market analyzer using Ollama.

---

## Jumpstart Instructions

Paste this prompt into **GitHub Copilot**:

> Build **"Market Watcher"**, a local application that scans the wider stock market for buying-pressure signals and ranks **BUY**, **WATCH**, and **SELL/AVOID** research candidates. It must discover opportunities independently of my existing holdings.
> 
> Use Python, pandas, SQLite, Streamlit, and Ollama’s local HTTP API. Support Windows 11 and PowerShell. No Claude Code or cloud LLM dependency.

---

## MVP Requirements

### Core Architecture & Tech Stack
* **Universe:** Configurable market universe starting with S&P 500 stocks and sector ETFs. Provide a small demo universe for quick testing.
* **Data Providers:** Pluggable market-data providers; start with `yfinance` for daily historical prices and volume. Handle missing data, stale quotes, rate limits, and ticker failures.
* **Local LLM Integration:** Call Ollama directly at `http://localhost:11434/api/chat` using `qwen3:8b` by default. Make model and endpoint configurable. Send only calculated evidence to Ollama for concise strengths, risks, and missing-data explanations. Keep ranking independent of the LLM; continue working if Ollama is unavailable.

### Technical Indicators & Calculations
* Calculate 20-day relative volume against the preceding 20 sessions.
* Calculate 20/60-day returns and benchmark-relative performance.
* Compute 50/200-day moving averages, RSI, ATR, OBV, and Chaikin Money Flow.

### Scoring & Guardrails
* Rank candidates using transparent, configurable Python rules. Show each score’s contributing factors. Scores are heuristic rankings, not probabilities of profit.
* Clearly label price/volume measures as **buying-pressure proxies**, not confirmed institutional inflows. Never invent ETF flows, institutional trades, or news.
* Provide extension interfaces for actual ETF net flows, SEC disclosures, options flow, and news. Mark these unavailable until a provider is connected.
* No brokerage connection or automatic trading.

### Dashboard & Reporting
* **Dashboard:** Sector rankings, top candidates, signal breakdowns, charts, data timestamps, and scan history.
* **Persistence & Export:** Save scans in SQLite and export CSV/Markdown reports.
* **Automation:** Include a CLI scan command and Windows Task Scheduler instructions.

### Testing & Validation
* Include meaningful tests for calculations, missing/stale data, and scoring. 
* Include historical signal evaluation with next-session execution assumptions, fees, slippage, and safeguards against look-ahead bias. Disclose survivorship bias when using today’s market constituents.

> [!NOTE]
> **Environment Note:** The background environment cannot access Ollama on your local laptop. Mock its HTTP responses for tests and document how you can verify the real connection locally.

---

## Deliverables

* Working initial implementation, dependency file, example configuration, demo data, and README with exact PowerShell setup/run commands.
* Distinction of demo results from live results and documented data-provider limitations.
* A pull request containing implemented features, test results, and remaining limitations after running checks and fixing failures.
