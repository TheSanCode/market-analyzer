from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from html.parser import HTMLParser
from urllib.request import Request, urlopen

import yaml


@dataclass(frozen=True)
class AppConfig:
    values: dict[str, Any]
    path: Path

    @property
    def universe(self) -> dict[str, Any]:
        return self.values.get("universe", {})

    @property
    def scoring(self) -> dict[str, Any]:
        return self.values.get("scoring", {})

    @property
    def data(self) -> dict[str, Any]:
        return self.values.get("data", {})

    @property
    def ollama(self) -> dict[str, Any]:
        return self.values.get("ollama", {})

    @property
    def storage(self) -> dict[str, Any]:
        return self.values.get("storage", {})


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path).expanduser().resolve()
    with config_path.open(encoding="utf-8") as file:
        values = yaml.safe_load(file) or {}
    if not isinstance(values, dict):
        raise ValueError("Configuration must be a YAML mapping.")
    return AppConfig(values=values, path=config_path)


def resolve_universe(config: AppConfig, *, demo: bool = False) -> tuple[list[str], dict[str, str]]:
    universe = config.universe
    if demo:
        tickers = [str(symbol).upper() for symbol in universe.get("demo_tickers", [])]
        sectors = {
            str(symbol).upper(): str(sector)
            for sector, symbols in universe.get("sector_etfs", {}).items()
            for symbol in symbols
        }
        stock_sectors = {
            str(symbol).upper(): str(sector)
            for symbol, sector in universe.get("demo_stock_sectors", {}).items()
        }
        return tickers, {
            **{symbol: stock_sectors.get(symbol, "Stocks") for symbol in tickers if symbol not in sectors},
            **sectors,
        }
    stocks = [str(symbol).upper() for symbol in universe.get("stocks", [])]
    if universe.get("include_sp500", False):
        try:
            request = Request(
                "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
                headers={"User-Agent": "MarketWatcher/0.1 (local market research app)"},
            )
            with urlopen(request, timeout=10) as response:
                parser = _SP500TableParser()
                parser.feed(response.read().decode("utf-8", errors="replace"))
            constituents = parser.constituents()
            stocks.extend(constituents)
            stocks_sectors = {symbol: sector for symbol, sector in constituents.items()}
        except Exception as exc:
            print(f"Warning: could not load current S&P 500 constituents: {exc}")
            stocks_sectors = {}
    else:
        stocks_sectors = {}
    stocks_sectors.update(
        {str(symbol).upper(): str(sector) for symbol, sector in universe.get("stock_sectors", {}).items()}
    )
    etfs = {
        str(symbol).upper(): str(sector)
        for sector, symbols in universe.get("sector_etfs", {}).items()
        for symbol in symbols
    }
    tickers = list(dict.fromkeys([*stocks, *etfs]))
    return tickers, {**{symbol: stocks_sectors.get(symbol, "Stocks") for symbol in stocks}, **etfs}


class _SP500TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._in_table = False
        self._table_depth = 0
        self._in_cell = False
        self._cell: list[str] = []
        self._row: list[str] = []
        self.rows: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            classes = dict(attrs).get("class") or ""
            if not self._in_table and "wikitable" in classes.split():
                self._in_table = True
                self._table_depth = 1
            elif self._in_table:
                self._table_depth += 1
        elif self._in_table and self._table_depth == 1:
            if tag == "tr":
                self._row = []
            elif tag in {"th", "td"}:
                self._cell = []
                self._in_cell = True
            elif tag == "br" and self._in_cell:
                self._cell.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if self._in_table and self._table_depth == 1:
            if tag in {"th", "td"} and self._in_cell:
                self._row.append(" ".join("".join(self._cell).split()))
                self._in_cell = False
            elif tag == "tr" and self._row:
                self.rows.append(self._row)
        if tag == "table" and self._in_table:
            self._table_depth -= 1
            if self._table_depth == 0:
                self._in_table = False

    def handle_data(self, data: str) -> None:
        if self._in_table and self._in_cell:
            self._cell.append(data)

    def constituents(self) -> dict[str, str]:
        import re

        for header_index, row in enumerate(self.rows):
            normalized = [cell.strip().lower() for cell in row]
            try:
                symbol_index = normalized.index("symbol")
                sector_index = normalized.index("gics sector")
            except ValueError:
                continue
            results = {}
            for values in self.rows[header_index + 1 :]:
                if len(values) <= max(symbol_index, sector_index):
                    continue
                symbol = re.sub(r"\[.*?\]", "", values[symbol_index]).strip().upper().replace(".", "-")
                if symbol:
                    results[symbol] = values[sector_index]
            if results:
                return results
        raise ValueError("S&P 500 constituent table was not found.")
