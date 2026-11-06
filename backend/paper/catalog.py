"""Platform instrument identities and illustrative demo contract metadata."""
# Demo contract sizes/prices are illustrative; import validated metadata with a real feed.
INSTRUMENTS = [
    dict(symbol="NIFTY-DEMO-FUT", name="NIFTY Futures", exchange="NFO", group="NSE Futures", kind="FUT", lot=25, tick=0.05, base=25080.0),
    dict(symbol="BANKNIFTY-DEMO-FUT", name="BANK NIFTY Futures", exchange="NFO", group="NSE Futures", kind="FUT", lot=15, tick=0.05, base=53250.0),
    dict(symbol="NIFTY-DEMO-25000CE", name="NIFTY 25000 Call", exchange="NFO", group="NSE Options", kind="CE", lot=25, tick=0.05, base=185.0, strike=25000),
    dict(symbol="NIFTY-DEMO-25000PE", name="NIFTY 25000 Put", exchange="NFO", group="NSE Options", kind="PE", lot=25, tick=0.05, base=142.0, strike=25000),
    dict(symbol="CRUDEOIL-DEMO-FUT", name="Crude Oil Futures", exchange="MCX", group="MCX", kind="FUT", lot=100, tick=1.0, base=6250.0),
    dict(symbol="GOLD-DEMO-FUT", name="Gold Futures", exchange="MCX", group="MCX", kind="FUT", lot=100, tick=1.0, base=81000.0),
    dict(symbol="SILVER-DEMO-FUT", name="Silver Futures", exchange="MCX", group="MCX", kind="FUT", lot=30, tick=1.0, base=95000.0),
    dict(symbol="NATURALGAS-DEMO-FUT", name="Natural Gas Futures", exchange="MCX", group="MCX", kind="FUT", lot=1250, tick=0.1, base=280.0),
    dict(symbol="COPPER-DEMO-FUT", name="Copper Futures", exchange="MCX", group="MCX", kind="FUT", lot=250, tick=0.05, base=900.0),
    dict(symbol="ZINC-DEMO-FUT", name="Zinc Futures", exchange="MCX", group="MCX", kind="FUT", lot=250, tick=0.05, base=280.0),
    dict(symbol="ALUMINIUM-DEMO-FUT", name="Aluminium Futures", exchange="MCX", group="MCX", kind="FUT", lot=250, tick=0.05, base=250.0),
    dict(symbol="LEAD-DEMO-FUT", name="Lead Futures", exchange="MCX", group="MCX", kind="FUT", lot=250, tick=0.05, base=180.0),
    dict(symbol="SENSEX-DEMO-FUT", name="SENSEX Futures", exchange="BFO", group="BSE Futures", kind="FUT", lot=10, tick=0.05, base=82000.0),
    dict(symbol="RELIANCE-DEMO", name="Reliance sample equity", exchange="NSE", group="NSE Equity", kind="EQ", lot=1, tick=0.05, base=1450.0),
    dict(symbol="USDINR-DEMO-FUT", name="USD/INR Futures", exchange="MSE", group="MSE", kind="FUT", lot=1000, tick=0.0025, base=85.0),
    dict(symbol="GIFTNIFTY-DEMO-FUT", name="GIFT NIFTY", exchange="GIFT", group="GIFT NIFTY", kind="FUT", lot=1, tick=0.5, base=25110.0),
    dict(symbol="US500-DEMO-FUT", name="US 500", exchange="GLOBAL", group="Global", kind="FUT", lot=1, tick=0.25, base=5800.0),
]
BY_KEY = {(row["symbol"], row["exchange"]): row for row in INSTRUMENTS}


GROUPS = sorted({row["group"] for row in INSTRUMENTS})
# Gold API documents precious metals per troy ounce; copper uses its own provider unit.
REFERENCE_ASSETS = [
    dict(symbol="XAU", name="Gold", unit="troy oz"),
    dict(symbol="XAG", name="Silver", unit="troy oz"),
    dict(symbol="XPT", name="Platinum", unit="troy oz"),
    dict(symbol="XPD", name="Palladium", unit="troy oz"),
    dict(symbol="HG", name="Copper", unit="provider unit"),
    dict(symbol="BTC", name="Bitcoin", unit="coin"),
    dict(symbol="ETH", name="Ethereum", unit="coin"),
]
REFERENCE_SYMBOLS = {row["symbol"] for row in REFERENCE_ASSETS}


def instrument_key(row: dict) -> str:
    return f'{row["exchange"]}:{row["symbol"]}'
