from __future__ import annotations

import argparse
import json
from pathlib import Path

from market_watcher.backtest import evaluate_signals
from market_watcher.config import load_config, resolve_universe
from market_watcher.ollama import explain_with_ollama
from market_watcher.providers import DemoProvider, YFinanceProvider
from market_watcher.reports import candidates_csv, markdown_report
from market_watcher.scanner import scan_market
from market_watcher.storage import list_scans, save_scan


def main() -> None:
    parser = argparse.ArgumentParser(description="Market Watcher local market research scanner.")
    commands = parser.add_subparsers(dest="command", required=True)
    scan_parser = commands.add_parser("scan", help="Scan the configured stock and ETF universe.")
    scan_parser.add_argument("--config", default="config.example.yaml")
    scan_parser.add_argument("--demo", action="store_true", help="Use the bundled synthetic demo data.")
    scan_parser.add_argument("--explain", action="store_true", help="Ask local Ollama to explain top candidates.")
    scan_parser.add_argument("--export-dir", default=None)
    history_parser = commands.add_parser("history", help="List saved scans.")
    history_parser.add_argument("--config", default="config.example.yaml")
    history_parser.add_argument("--limit", type=int, default=20)
    evaluate_parser = commands.add_parser("evaluate", help="Evaluate historical signals with next-session entries.")
    evaluate_parser.add_argument("--config", default="config.example.yaml")
    evaluate_parser.add_argument("--demo", action="store_true")
    evaluate_parser.add_argument("--output", default="reports/backtest.json")
    args = parser.parse_args()

    config = load_config(args.config)
    database = _database_path(config)
    if args.command == "history":
        print(json.dumps(list_scans(database, args.limit), indent=2))
        return
    if args.command == "scan":
        provider = _provider(args.demo, config)
        result = scan_market(config, provider, demo=args.demo)
        scan_id = save_scan(database, result)
        export_dir = Path(args.export_dir or config.values.get("reports", {}).get("directory", "reports"))
        export_dir.mkdir(parents=True, exist_ok=True)
        (export_dir / f"market-watch-scan-{scan_id}.csv").write_text(
            candidates_csv(result), encoding="utf-8-sig"
        )
        (export_dir / f"market-watch-scan-{scan_id}.md").write_text(
            markdown_report(result), encoding="utf-8"
        )
        if args.explain:
            eligible = [row for row in result["candidates"] if row.get("status") == "ok"][:3]
            for candidate in eligible:
                candidate["ollama_explanation"] = explain_with_ollama(candidate, config.ollama)
        counts = {}
        for candidate in result["candidates"]:
            counts[candidate["signal"]] = counts.get(candidate["signal"], 0) + 1
        print(f"Saved scan {scan_id} ({result['data_source']}) with {len(result['candidates'])} candidates.")
        print(json.dumps(counts, indent=2))
        print(f"Reports: {export_dir.resolve()}")
        if args.explain:
            for candidate in eligible:
                explanation = candidate["ollama_explanation"]
                print(f"\n{candidate['ticker']} ({explanation['status']}): {explanation['text']}")
        return

    provider = _provider(args.demo, config)
    universe, _ = resolve_universe(config, demo=args.demo)
    benchmark = str(config.universe.get("benchmark", "SPY")).upper()
    histories = provider.fetch_history(list(dict.fromkeys([*universe, benchmark])), str(config.data.get("period", "2y")))
    result = evaluate_signals(
        histories,
        benchmark,
        config.scoring,
        holding_sessions=int(config.values.get("backtest", {}).get("holding_sessions", 20)),
        fee_bps=float(config.values.get("backtest", {}).get("fee_bps", 5)),
        slippage_bps=float(config.values.get("backtest", {}).get("slippage_bps", 5)),
    )
    result["data_source"] = "demo" if args.demo else "live"
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
    print(f"Evaluated {len(result['trades'])} historical trades. Results: {output.resolve()}")


def _provider(demo: bool, config: object) -> DemoProvider | YFinanceProvider:
    if demo:
        return DemoProvider()
    data_settings = config.data
    return YFinanceProvider(
        attempts=int(data_settings.get("retries", 3)),
        retry_delay=float(data_settings.get("retry_delay_seconds", 1)),
        fallback_ticker_limit=int(data_settings.get("fallback_ticker_limit", 20)),
    )


def _database_path(config: object) -> Path:
    configured = Path(config.storage.get("database", "market_watcher.sqlite"))
    return configured if configured.is_absolute() else config.path.parent / configured


if __name__ == "__main__":
    main()
