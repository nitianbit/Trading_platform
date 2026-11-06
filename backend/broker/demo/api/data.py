"""Read-only synthetic market data; no broker account or execution API."""
from backend.paper.market import get_quote


def get_quotes(symbol, exchange, auth_token=None, config=None):
    return get_quote(symbol, exchange)


def get_multi_quotes(symbols, auth_token=None, config=None):
    return [
        {"symbol": item["symbol"], "exchange": item["exchange"],
         **get_quotes(item["symbol"], item["exchange"])}
        for item in symbols
    ]


def get_depth(symbol, exchange, auth_token=None, config=None):
    quote = get_quotes(symbol, exchange)
    return {**quote, "depth": {
        "buy": [{"price": quote["bid"], "quantity": 100}],
        "sell": [{"price": quote["ask"], "quantity": 100}],
    }}

