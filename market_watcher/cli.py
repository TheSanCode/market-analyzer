"""Command-line interface: ``python -m market_watcher <command>``."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from . import storage
from .config import AppConfig, ConfigError, load_config
from .data import make_provider
from .demo import DEMO_BENCHMARK
from .export import export_scan
from .llm import OllamaClient
from .scanner import SIGNAL_DISCLAIMER, ScanResult, run_scan

DEMO_UNIVERSE = [
    "DEMO-ACCUM",
    "DEMO-DISTRIB",
    "DEMO-RANGE",
    "DEMO-SPIKE",
    "DEMO-YOUNG",
    "DEMO-STALE",
    "DEMO-GAPPY",
    "DEMO-MISSING",
]


def _load(args: argparse.Namespace) -> AppConfig:
    cfg = load_config(args.config)
    if getattr(args, "db", None):
        cfg.database_path = args.db
    return cfg


def apply_demo(cfg: AppConfig) -> AppConfig:
    """Switch a config to the offline simulated dataset."""
    cfg.data.provider = "demo"
    cfg.universe = list(DEMO_UNIVERSE)
    cfg.benchmark = DEMO_BENCHMARK
    return cfg


def _print_scan(scan: ScanResult) -> None:
    if scan.simulated:
        print("*** SIMULATED DEMO DATA - not real market prices ***")
    print(SIGNAL_DISCLAIMER)
    print(
        f"scan {scan.scan_id} | started {scan.started_at} UTC | provider {scan.provider} "
        f"| benchmark {scan.benchmark} (last bar {scan.benchmark_last_bar or 'n/a'})"
    )
    print(f"{'rank':>4}  {'ticker':<14}{'label':<18}{'score':>7}  {'last bar':<11} flags")
    for r in scan.results:
        if r.status != "ok":
            print(f"{'-':>4}  {r.ticker:<14}{'ERROR':<18}{'':>7}  {'':<11} {r.error}")
            continue
        flags = []
        if r.stale:
            flags.append("STALE")
        if r.missing:
            flags.append(f"{len(r.missing)} missing")
        if r.warnings:
            flags.append(f"{len(r.warnings)} data warnings")
        score = f"{r.score:7.1f}" if r.score is not None else f"{'n/a':>7}"
        print(
            f"{r.rank or '-':>4}  {r.ticker:<14}{r.label:<18}{score}  "
            f"{r.last_bar or 'n/a':<11} {', '.join(flags)}"
        )
    for n in scan.notes:
        print(f"note: {n}")
    explained = [r for r in scan.results if r.explanation]
    for r in explained:
        print(f"\n--- {r.ticker} (LLM explanation of calculated evidence) ---\n{r.explanation}")


def cmd_scan(args: argparse.Namespace) -> int:
    cfg = _load(args)
    if args.demo:
        apply_demo(cfg)
    if args.no_llm:
        cfg.ollama.enabled = False
    provider = make_provider(cfg.data.provider, cfg.data.demo_path)

    explainer = None
    if cfg.ollama.enabled:
        client = OllamaClient(cfg.ollama)
        ok, msg = client.check()
        if ok:
            explainer = client
        else:
            print(f"LLM explanations disabled for this scan: {msg}", file=sys.stderr)

    scan = run_scan(
        cfg,
        provider,
        explainer,
        progress=(lambda m: print(m, file=sys.stderr)) if args.verbose else None,
    )
    if not args.no_save:
        storage.save_scan(cfg.database_path, scan)
    _print_scan(scan)
    if args.export or args.export_dir:
        csv_path, md_path = export_scan(scan, args.export_dir or cfg.export_dir)
        print(f"exported {csv_path} and {md_path}")
    if not scan.ok:
        print("no tickers could be analysed", file=sys.stderr)
        return 2
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    cfg = _load(args)
    if args.ticker:
        rows = storage.ticker_history(cfg.database_path, args.ticker.upper(), args.limit)
        if not rows:
            print("no history")
            return 0
        for r in rows:
            sim = " SIMULATED" if r["simulated"] else ""
            score = "n/a" if r["score"] is None else f"{r['score']:.1f}"
            print(
                f"scan {r['scan_id']:>4} {r['started_at']}  {r['label']:<18} "
                f"{score:>7}  last bar {r['last_bar']}{sim}"
            )
        return 0
    scans = storage.list_scans(cfg.database_path, args.limit)
    if not scans:
        print(f"no scans in {cfg.database_path}")
        return 0
    for s in scans:
        sim = " SIMULATED" if s["simulated"] else ""
        print(
            f"scan {s['id']:>4} {s['started_at']}  {s['provider']:<18} "
            f"ok={s['n_ok']} failed={s['n_failed']}{sim}"
        )
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    cfg = _load(args)
    scan = storage.load_scan(cfg.database_path, args.scan_id)
    if scan is None:
        print("scan not found", file=sys.stderr)
        return 1
    csv_path, md_path = export_scan(scan, args.out or cfg.export_dir)
    print(f"exported {csv_path} and {md_path}")
    return 0


def cmd_check_ollama(args: argparse.Namespace) -> int:
    cfg = _load(args)
    client = OllamaClient(cfg.ollama)
    ok, msg = client.check()
    print(msg)
    if not ok:
        return 1
    if args.chat:
        reply = client.chat(
            [{"role": "user", "content": "Reply with exactly: Market Watcher connection OK"}]
        )
        print(f"model replied: {reply}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="market-watcher",
        description="Scan a stock universe for price/volume buying-pressure proxies.",
    )
    p.add_argument("-c", "--config", type=Path, help="TOML config file (default: built-in)")
    p.add_argument("--db", help="override SQLite database path")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("scan", help="run a scan, save it to SQLite and print rankings")
    s.add_argument("--demo", action="store_true", help="use the offline SIMULATED dataset")
    s.add_argument("--no-llm", action="store_true", help="skip Ollama explanations")
    s.add_argument("--no-save", action="store_true", help="do not write to SQLite")
    s.add_argument("--export", action="store_true", help="write CSV + Markdown to export_dir")
    s.add_argument("--export-dir", help="write CSV + Markdown to this directory")
    s.add_argument("-v", "--verbose", action="store_true")
    s.set_defaults(func=cmd_scan)

    h = sub.add_parser("history", help="list saved scans, or one ticker's history")
    h.add_argument("--ticker")
    h.add_argument("--limit", type=int, default=20)
    h.set_defaults(func=cmd_history)

    e = sub.add_parser("export", help="export a saved scan (latest by default)")
    e.add_argument("--scan-id", type=int)
    e.add_argument("--out", help="output directory")
    e.set_defaults(func=cmd_export)

    o = sub.add_parser("check-ollama", help="verify the local Ollama connection")
    o.add_argument("--chat", action="store_true", help="also send a tiny test chat")
    o.set_defaults(func=cmd_check_ollama)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if getattr(args, "verbose", False) else logging.ERROR,
        format="%(levelname)s %(name)s: %(message)s",
    )
    try:
        return int(args.func(args))
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
