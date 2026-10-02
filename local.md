##market-analyzer



Paste this into **“Jumpstart your project with Copilot”**:

Build “Market Watcher”, a local application that scans the wider stock market for buying-pressure signals and ranks BUY, WATCH and SELL/AVOID research candidates. It must discover opportunities independently of my existing holdings.

Use Python, pandas, SQLite, Streamlit and Ollama’s local HTTP API. Support Windows 11 and PowerShell. No Claude Code or cloud LLM dependency.

MVP requirements:
- Configurable market universe, starting with S&P 500 stocks and sector ETFs. Provide a small demo universe for quick testing.
- Pluggable market-data providers; start with yfinance for daily historical prices and volume. Handle missing data, stale quotes, rate limits and ticker failures.
- Calculate 20-day relative volume against the preceding 20 sessions, 20/60-day returns, benchmark-relative performance, 50/200-day moving averages, RSI, ATR, OBV and Chaikin Money Flow.
- Rank candidates using transparent, configurable Python rules. Show each score’s contributing factors. Scores are heuristic rankings, not probabilities of profit.
- Clearly label price/volume measures as buying-pressure proxies, not confirmed institutional inflows. Never invent ETF flows, institutional trades or news.
- Provide extension interfaces for actual ETF net flows, SEC disclosures, options flow and news. Mark these unavailable until a provider is connected.
- Call Ollama directly at http://localhost:11434/api/chat using qwen3:8b by default. Make model and endpoint configurable.
- Send only calculated evidence to Ollama for concise strengths, risks and missing-data explanations. Keep ranking independent of the LLM; continue working if Ollama is unavailable.
- Dashboard: sector rankings, top candidates, signal breakdowns, charts, data timestamps and scan history.
- Save scans in SQLite and export CSV/Markdown reports.
- Include a CLI scan command and Windows Task Scheduler instructions.
- No brokerage connection or automatic trading.

Add meaningful tests for calculations, missing/stale data and scoring. Include historical signal evaluation with next-session execution assumptions, fees, slippage and safeguards against look-ahead bias. Disclose survivorship bias when using today’s market constituents.

Deliver a working initial implementation, dependency file, example configuration, demo data and README with exact PowerShell setup/run commands. Distinguish demo results from live results and document data-provider limitations.


Agents:
Implement the first working version of Market Watcher in this repository and open a pull request.

Inspect the existing files first. Build a Python application that scans a configurable stock universe for buying-pressure signals and ranks BUY, WATCH and SELL/AVOID research candidates independently of my holdings.

Use pandas, SQLite, Streamlit and yfinance. Calculate relative volume against preceding sessions, benchmark-relative returns, 50/200-day moving averages, RSI, ATR, OBV and Chaikin Money Flow. Keep scoring transparent and configurable in Python.

Integrate Ollama directly through http://localhost:11434/api/chat, defaulting to qwen3:8b. Use it only to explain calculated evidence, risks and missing information. The scanner must work without Ollama.

Include:
- CLI scan command and dashboard with rankings, charts and data timestamps.
- SQLite scan history and CSV/Markdown export.
- Small offline demo dataset clearly labelled as simulated.
- Missing/stale data handling and provider failure isolation.
- Tests for indicators, scoring and failure handling.
- README with Windows PowerShell installation, run commands and Task Scheduler setup.
- Example configuration and dependency file.

Label price/volume signals as proxies for buying pressure, not verified institutional money flows. Do not fabricate news or flow data. Do not connect to a broker or execute trades.

The background environment cannot access Ollama on my laptop. Mock its HTTP responses for tests and document how I can verify the real connection locally.

Run the available checks, fix failures, and summarize implemented features, test results and remaining limitations in the pull request.
