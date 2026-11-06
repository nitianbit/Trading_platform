"""Public API verification using owned QA accounts retained for browser QA."""
from pathlib import Path
import json
import secrets
import os
import time
from concurrent.futures import ThreadPoolExecutor
import httpx
from urllib.parse import urlsplit, parse_qs

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT))
from backend.config import get_settings
record = Path(os.environ.get("DHK_QA_RECORD", str(ROOT / ".local" / "qa.json")))
record.parent.mkdir(exist_ok=True)
host = os.environ.get("DHK_QA_URL", "http://127.0.0.1:8083")
saved = json.loads(record.read_text()) if record.exists() else {"customers": []}


def checked(response, expected=200):
    assert response.status_code == expected, f"{response.request.url.path}: {response.status_code} {response.text[:500]}"
    return response.json()


def login(client, account):
    checked(client.post("/auth/login", json={"username": account["username"], "password": account["password"]}))


def keep_record():
    record.write_text(json.dumps(saved))
    record.chmod(0o600)


with httpx.Client(base_url=host, timeout=20) as admin:
    checked(admin.get("/web/paper/admin"), 401)
    setup = checked(admin.get("/auth/check-setup"))
    if setup["needs_setup"]:
        suffix = secrets.token_hex(4)
        saved["admin"] = dict(username=f"qa_admin_{suffix}", email=f"qa-admin-{suffix}@example.com", password=secrets.token_urlsafe(20))
        checked(admin.post("/auth/setup", json=saved["admin"]), 403)
        candidate = {**saved["admin"], "username": saved["admin"]["username"] + "_second", "email": f"qa-admin-second-{suffix}@example.com"}
        def claim(account):
            response = httpx.post(host + "/auth/setup", json={**account, "setup_token": get_settings().setup_token}, timeout=20)
            return response.status_code, account
        with ThreadPoolExecutor(max_workers=2) as pool:
            claims = list(pool.map(claim, [saved["admin"], candidate]))
        assert sorted(code for code, _ in claims) == [200, 403], [code for code, _ in claims]
        saved["admin"] = next(account for code, account in claims if code == 200)
        keep_record()
        print("PASS: operator-token setup and concurrent first-admin claim")
    elif "admin" not in saved:
        raise SystemExit("User-owned setup detected. QA will not modify it.")
    login(admin, saved["admin"])
    me = checked(admin.get("/auth/me"))
    assert me["paper_only"] and me["is_admin"] and not me["broker_authenticated"]
    assert checked(admin.get("/web/trading-mode"))["mode"] == "sandbox"
    checked(admin.post("/web/trading-mode", json={"mode": "live"}), 400)
    checked(admin.get("/broker/config"), 404)
    print("PASS: platform authentication and enforced paper-only mode")
    def identity(account):
        return {key: account[key] for key in ("username", "email")}

    def activate(invitation, account):
        token = parse_qs(urlsplit(invitation["invitation_url"]).fragment)["token"][0]
        checked(httpx.post(host + "/auth/invite/preview", json={"token": token}, timeout=20))
        checked(httpx.post(host + "/auth/invite/accept", json={"token": token, "password": account["password"]}, timeout=20))
        return token

    broker_accounts, broker_clients, broker_ids = [], [], []
    for label in ("a", "b"):
        suffix = secrets.token_hex(4)
        account = dict(username="qa_broker_" + label + "_" + suffix, email=f"broker-{label}-{suffix}@example.com", password=secrets.token_urlsafe(20))
        invitation = checked(admin.post("/web/paper/brokers", json=identity(account)), 201)
        assert invitation["role"] == "broker" and not invitation["password_set"]
        with httpx.Client(base_url=host, timeout=20) as unactivated:
            checked(unactivated.post("/auth/login", json={"username": account["username"], "password": account["password"]}), 401)
        token = activate(invitation, account)
        if label == "a":
            checked(httpx.post(host + "/auth/invite/accept", json={"token": token, "password": account["password"]}, timeout=20), 400)
        client = httpx.Client(base_url=host, timeout=20)
        login(client, account)
        saved.setdefault("brokers", []).append(account)
        keep_record()
        broker_accounts.append(account)
        broker_clients.append(client)
        broker_ids.append(invitation["id"])
    broker_a, broker_b = broker_clients
    checked(broker_a.get("/web/paper/settings"), 403)
    checked(broker_a.get("/web/paper/brokers"), 403)
    checked(admin.post("/web/paper/users", json={"username": "qa_direct", "email": "direct@example.com"}), 403)
    checked(broker_a.post("/web/paper/brokers", json={"username": "qa_elevate", "email": "elevate@example.com"}), 403)
    accounts = []
    for label in ("a", "b"):
        suffix = secrets.token_hex(4)
        account = dict(username=f"qa_customer_{label}_{suffix}", email=f"qa-{label}-{suffix}@example.com", password=secrets.token_urlsafe(20))
        invitation = checked(broker_a.post("/web/paper/users", json=identity(account)), 201)
        assert invitation["broker_id"] == broker_ids[0] and not invitation["password_set"]
        activate(invitation, account)
        info = invitation
        assert info["is_admin"] is False
        saved["customers"].append(account)
        accounts.append(account)
        keep_record()
    checked(broker_a.post("/web/paper/users", json=identity(accounts[0])), 409)
    user_rows = checked(broker_a.get("/web/paper/users"))
    assert len(user_rows) == 2 and all(row["broker_id"] == broker_ids[0] for row in user_rows)
    assert checked(broker_b.get("/web/paper/users")) == []
    assert checked(broker_b.get("/web/paper/admin"))["accounts"] == []
    uid = user_rows[0]["id"]
    checked(broker_b.patch(f"/web/paper/accounts/{uid}", json={"is_active": False}), 404)
    checked(broker_b.post(f"/web/paper/accounts/{uid}/invitation"), 404)
    checked(broker_a.post("/web/paper/users", json={"username": "qa_forged", "email": "forged@example.com", "broker_id": broker_ids[1]}), 422)
    checked(broker_a.patch(f"/web/paper/accounts/{uid}", json={"is_active": True, "broker_id": broker_ids[1]}), 422)
    checked(admin.post(f"/web/paper/users/{uid}/assign-broker", json={"broker_id": broker_ids[1]}), 409)
    print("PASS: invitation-only broker hierarchy, single-use activation and cross-broker isolation")
    print("PASS: customer creation and duplicate-account validation")
    checked(broker_a.patch(f"/web/paper/brokers/{broker_ids[0]}/limit", json={"max_users": 999}), 403)
    for invalid in (-1, True, 1.5):
        checked(admin.patch(f"/web/paper/brokers/{broker_ids[0]}/limit", json={"max_users": invalid}), 422)
    checked(admin.patch(f"/web/paper/brokers/{broker_ids[0]}/limit", json={"max_users": 0}))
    assert checked(broker_a.get("/web/paper/broker-capacity")) == {"users": 2, "max_users": 0}
    blocked_account = dict(username="qa_quota_blocked_"+secrets.token_hex(4), email="quota-blocked-"+secrets.token_hex(4)+"@example.com")
    checked(broker_a.post("/web/paper/users", json=blocked_account), 409)
    checked(admin.patch(f"/web/paper/brokers/{broker_ids[0]}/limit", json={"max_users": 3}))
    quota_candidates = [dict(username="qa_quota_"+secrets.token_hex(5), email="quota-"+secrets.token_hex(5)+"@example.com", password=secrets.token_urlsafe(20)) for _ in range(2)]
    def quota_create(account):
        return httpx.post(host + "/web/paper/users", headers={"Cookie": "access_token="+broker_a.cookies.get("access_token")}, json=identity(account), timeout=20)
    with ThreadPoolExecutor(max_workers=2) as pool:
        quota_results = list(pool.map(quota_create, quota_candidates))
    assert sorted(response.status_code for response in quota_results) == [201, 409], [response.text for response in quota_results]
    saved["customers"].extend(account for account, response in zip(quota_candidates, quota_results) if response.status_code == 201)
    keep_record()
    assert checked(broker_a.get("/web/paper/broker-capacity")) == {"users": 3, "max_users": 3}
    checked(admin.patch(f"/web/paper/brokers/{broker_ids[0]}/limit", json={"max_users": None}))
    print("PASS: per-broker quota validation, zero/unlimited capacity and concurrent admission")

    with httpx.Client(base_url=host, timeout=20) as first, httpx.Client(base_url=host, timeout=20) as second:
        login(first, accounts[0])
        login(second, accounts[1])
        checked(second.get("/web/paper/admin"), 403)
        checked(second.post("/web/sandbox/reconcile-margin"), 403)
        checked(second.post("/web/sandbox/reset"), 403)
        checked(second.get("/web/sandbox/summary"), 403)
        checked(second.get("/web/paper/users"), 403)
        checked(second.post("/web/paper/users", json=accounts[0]), 403)
        market = checked(first.get("/web/paper/market"))
        assert market["data_source"] == "synthetic_demo" and len(market["instruments"]) == 17
        assert {row["group"] for row in market["instruments"]} == {"NSE Futures", "NSE Options", "MCX", "GIFT NIFTY", "Global", "BSE Futures", "NSE Equity", "MSE"}
        settings = checked(admin.get("/web/paper/settings"))
        original_policy = settings["policy"]
        checked(second.get("/web/paper/settings"), 403)
        checked(second.put("/web/paper/settings", json=original_policy), 403)
        checked(admin.put("/web/paper/settings", json={**original_policy, "max_customers": -1}), 422)
        checked(admin.put("/web/paper/settings", json={**original_policy, "disabled_groups": ["unknown"]}), 422)
        policy = {**original_policy, "public_feed_enabled": False, "max_customers": settings["customer_count"] + 1}
        checked(admin.put("/web/paper/settings", json={**policy, "revision": checked(admin.get("/web/paper/settings"))["revision"]}))
        stale = {**original_policy, "revision": settings["revision"]}
        checked(admin.put("/web/paper/settings", json=stale), 409)
        for incomplete in ({}, {"max_customers": 0}, {"revision": settings["revision"]}):
            checked(admin.put("/web/paper/settings", json=incomplete), 422)
        assert checked(admin.get("/web/paper/settings"))["policy"] == policy
        candidates = [dict(username="qa_capacity_" + secrets.token_hex(5), email="capacity-" + secrets.token_hex(5) + "@example.com", password=secrets.token_urlsafe(20)) for _ in range(2)]
        cookie_headers = {"Cookie": "access_token=" + broker_a.cookies.get("access_token")}
        def create_candidate(account):
            return httpx.post(host + "/web/paper/users", headers=cookie_headers, json=identity(account), timeout=20)
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(create_candidate, candidates))
        assert sorted(response.status_code for response in responses) == [201, 409], [response.text for response in responses]
        for account, response in zip(candidates, responses):
            if response.status_code == 201:
                # Replacing an unused invitation invalidates the original immediately.
                invitation = response.json()
                old_token = parse_qs(urlsplit(invitation["invitation_url"]).fragment)["token"][0]
                replacement = checked(broker_a.post(f"/web/paper/accounts/{invitation['id']}/invitation"))
                checked(httpx.post(host + "/auth/invite/preview", json={"token": old_token}, timeout=20), 400)
                new_token = parse_qs(urlsplit(replacement["invitation_url"]).fragment)["token"][0]
                def accept_once(_):
                    return httpx.post(host + "/auth/invite/accept", json={"token": new_token, "password": account["password"]}, timeout=20)
                with ThreadPoolExecutor(max_workers=2) as pool:
                    accepted = list(pool.map(accept_once, range(2)))
                assert sorted(result.status_code for result in accepted) == [200, 400], [result.text for result in accepted]
                saved["customers"].append(account)
        keep_record()
        assert checked(admin.get("/web/paper/settings"))["customer_count"] == policy["max_customers"]
        policy.update(max_customers=0, disabled_groups=["MCX"], disabled_instruments=["NFO:NIFTY-DEMO-FUT"])
        checked(admin.put("/web/paper/settings", json={**policy, "revision": checked(admin.get("/web/paper/settings"))["revision"]}))
        filtered = checked(first.get("/web/paper/market"))["instruments"]
        assert all(row["group"] != "MCX" and row["symbol"] != "NIFTY-DEMO-FUT" for row in filtered)
        checked(first.get("/web/paper/chart", params={"symbol": "GOLD-DEMO-FUT", "exchange": "MCX"}), 404)
        assert not checked(first.get("/web/paper/reference-prices"))["enabled"]
        checked(first.get("/auth/me"))  # Lowering capacity preserves existing-account access.
        checked(admin.put("/web/paper/settings", json={**original_policy, "revision": checked(admin.get("/web/paper/settings"))["revision"]}))
        print("PASS: admin policy validation, concurrent customer cap, market filtering and reference-feed switch")
        key_a = checked(first.get("/web/apikey"))["api_key"]
        key_b = checked(second.get("/web/apikey"))["api_key"]
        assert key_a != key_b
        from websockets.sync.client import connect
        import json
        with connect("ws://127.0.0.1:" + os.environ.get("WEBSOCKET_PORT", "8783"), open_timeout=5) as ws:
            ws.send(json.dumps({"action":"authenticate", "api_key":key_a}))
            assert json.loads(ws.recv(timeout=5))["status"] == "success"
            for invalid in ([{"symbol":"NOPE-DEMO", "exchange":"NFO"}], ["not-an-object"]):
                ws.send(json.dumps({"action":"subscribe", "symbols":invalid, "mode":"Quote"}))
                assert json.loads(ws.recv(timeout=5))["status"] == "error"
            ws.send(json.dumps({"action":"subscribe", "symbols":[{"symbol":"NIFTY-DEMO-FUT", "exchange":"NFO"}], "mode":"Depth"}))
            assert json.loads(ws.recv(timeout=5))["status"] == "error"
            ws.send(json.dumps({"action":"subscribe", "symbols":[{"symbol":"NIFTY-DEMO-FUT", "exchange":"NFO"}], "mode":"LTP"}))
            assert json.loads(ws.recv(timeout=5))["status"] == "success"
            tick = json.loads(ws.recv(timeout=5))
            assert tick["type"] == "market_data" and tick["data"]["data_source"] == "synthetic_demo" and tick["data"]["ltp"] > 0
            ws.send(json.dumps({"action":"unsubscribe", "symbols":[{"symbol":"NIFTY-DEMO-FUT", "exchange":"NFO"}], "mode":"LTP"}))
            assert json.loads(ws.recv(timeout=5))["status"] == "success"
            ws.send(json.dumps({"action":"subscribe", "symbols":[{"symbol":"NIFTY-DEMO-FUT", "exchange":"NFO"}], "mode":"Quote"}))
            assert json.loads(ws.recv(timeout=5))["status"] == "success"
            quote = json.loads(ws.recv(timeout=5))["data"]
            assert quote["bid"] < quote["ltp"] < quote["ask"]


        quotes = checked(first.post("/api/v1/multiquotes", json={
            "apikey": key_a, "symbols": [{"symbol": "NIFTY-DEMO-FUT", "exchange": "NFO"}]
        }))
        assert quotes["results"][0]["ltp"] > 0

        def order(**overrides):
            payload = dict(apikey=key_a, symbol="NIFTY-DEMO-25000CE", exchange="NFO",
                           action="BUY", quantity=25, pricetype="MARKET", product="NRML")
            return {**payload, **overrides}

        baseline = checked(admin.get("/web/paper/admin"))
        before = checked(first.get("/web/dashboard"))["data"]
        assert before["utiliseddebits"] == 0
        checked(first.post("/api/v1/placeorder", json=order()))
        positions = checked(first.get("/web/positions"))["data"]
        assert any(row["symbol"] == "NIFTY-DEMO-25000CE" and row["quantity"] == 25 for row in positions), positions
        assert checked(second.get("/web/orderbook"))["data"]["orders"] == []
        assert checked(second.get("/web/positions"))["data"] == []
        after = checked(first.get("/web/dashboard"))["data"]
        assert after["utiliseddebits"] > 0 and after["availablecash"] < before["availablecash"]
        overview = checked(admin.get("/web/paper/admin"))
        account = next(row for row in overview["accounts"] if row["username"] == accounts[0]["username"])
        assert overview["customers"] == baseline["customers"] and overview["open_positions"] == baseline["open_positions"] + 1
        assert account["open_positions"] == 1 and account["fills"] == 1 and account["used_margin"] > 0
        print("PASS: admin access control and account activity overview")
        print("PASS: fill, position, margin and isolated customer books")
        managed = checked(broker_a.get("/web/paper/trades"))
        assert len(managed["trades"]) == 1 and managed["trades"][0]["username"] == accounts[0]["username"]
        assert checked(broker_b.get("/web/paper/trades"))["trades"] == []
        checked(broker_b.get("/web/paper/trades", params={"user_id": managed["trades"][0]["user_id"]}), 404)
        checked(first.get("/web/paper/trades"), 403)
        checked(admin.get("/web/paper/trades", params={"limit": 101}), 422)
        assert len(checked(admin.get("/web/paper/trades"))["trades"]) == 1

        checked(first.post("/api/v1/placeorder", json=order(action="SELL")))
        assert all(row["quantity"] == 0 for row in checked(first.get("/web/positions"))["data"])
        fills = checked(first.get("/web/tradebook"))["data"]
        assert len(fills) == 2, fills
        buy = next(row for row in fills if row["action"] == "BUY")
        sell = next(row for row in fills if row["action"] == "SELL")
        cash = checked(first.get("/web/dashboard"))["data"]
        expected = round((sell["average_price"] - buy["average_price"]) * 25, 2)
        total_fees = sum(fill["brokerage"] for fill in fills)
        assert abs(cash["brokerage_paid"] - total_fees) <= 0.01
        assert abs(cash["m2mrealized"] - (expected - total_fees)) <= 0.01, (cash, expected)
        assert abs(cash["gross_realized_pnl"] - expected) <= 0.01
        assert abs(checked(broker_a.get("/web/paper/earnings"))["balance"] - sum(fill["broker_credit"] for fill in fills)) <= 0.01
        assert abs(checked(admin.get("/web/paper/earnings"))["balance"] - sum(fill["admin_credit"] for fill in fills)) <= 0.01
        checked(first.get("/web/paper/earnings"), 403)
        print("PASS: user brokerage deductions, 3% broker/1% admin earnings and net P&L")
        assert cash["utiliseddebits"] == 0, cash
        assert cash["m2munrealized"] == 0, cash
        print("PASS: position close, margin release and realized P&L")
        page_one = checked(broker_a.get("/web/paper/trades", params={"limit": 1}))
        assert len(page_one["trades"]) == 1 and page_one["next_before_id"] is not None
        page_two = checked(broker_a.get("/web/paper/trades", params={"limit": 1, "before_id": page_one["next_before_id"]}))
        assert len(page_two["trades"]) == 1 and page_two["next_before_id"] is None
        assert page_one["trades"][0]["id"] != page_two["trades"][0]["id"]
        assert len(checked(admin.get("/web/paper/trades", params={"user_id": page_one["trades"][0]["user_id"]}))["trades"]) == 2

        pending = checked(first.post("/api/v1/placeorder", json=order(pricetype="LIMIT", price=1)))
        pending_id = pending["orderid"]
        overview = checked(admin.get("/web/paper/admin"))
        account = next(row for row in overview["accounts"] if row["username"] == accounts[0]["username"])
        assert account["pending_orders"] == 1 and account["open_positions"] == 0 and account["unrealized_pnl"] == 0
        assert account["fills"] == 2
        checked(second.post("/api/v1/cancelorder", json={"apikey": key_b, "orderid": pending_id}), 404)
        checked(first.post("/api/v1/cancelorder", json={"apikey": key_a, "orderid": pending_id}))
        assert checked(first.get("/web/dashboard"))["data"]["utiliseddebits"] == 0
        checked(first.post("/api/v1/placeorder", json=order(quantity=1)), 400)
        checked(first.post("/api/v1/placeorder", json=order(quantity=2500000)), 400)
        print("PASS: cancel, foreign-order denial, lot and insufficient-funds checks")

        # Exercise modification through the public route, including omitted fields.
        editable = checked(first.post("/api/v1/placeorder", json=order(pricetype="LIMIT", price=1)))["orderid"]
        time.sleep(1.05)
        checked(first.post("/api/v1/modifyorder", json={"apikey": key_a, "orderid": editable, "quantity": 50}))
        changed = next(row for row in checked(first.get("/web/orderbook"))["data"]["orders"] if row["orderid"] == editable)
        assert changed["price"] == 1 and changed["quantity"] == 50
        for invalid in ({"quantity": -25}, {"price": 1.03}, {"pricetype": "BOGUS"}, {"quantity": 2500000, "price": 400}):
            checked(first.post("/api/v1/modifyorder", json={"apikey": key_a, "orderid": editable, **invalid}), 400)
        checked(first.post("/api/v1/cancelorder", json={"apikey": key_a, "orderid": editable}))
        assert checked(first.get("/web/dashboard"))["data"]["utiliseddebits"] == 0
        print("PASS: HTTP modification preserves omitted price and rejects invalid or unfunded changes")

        time.sleep(1.05)  # Respect the configured per-account order admission window.
        for symbol, exchange, qty in [
            ("CRUDEOIL-DEMO-FUT", "MCX", 100),
            ("SILVER-DEMO-FUT", "MCX", 30),
            ("NATURALGAS-DEMO-FUT", "MCX", 1250),
            ("SENSEX-DEMO-FUT", "BFO", 10),
            ("USDINR-DEMO-FUT", "MSE", 1000),
            ("GIFTNIFTY-DEMO-FUT", "GIFT", 1),
            ("US500-DEMO-FUT", "GLOBAL", 1),
        ]:
            checked(first.post("/api/v1/placeorder", json=order(symbol=symbol, exchange=exchange, quantity=qty)))
            checked(first.post("/api/v1/placeorder", json=order(symbol=symbol, exchange=exchange, quantity=qty, action="SELL")))
            time.sleep(1.05)
        print("PASS: crude, silver, gas, BSE, MSE, GIFT and global demo round trips")

    other_account = dict(username="qa_customer_other_"+secrets.token_hex(5), email="other-"+secrets.token_hex(5)+"@example.com", password=secrets.token_urlsafe(20))
    other_invitation = checked(broker_b.post("/web/paper/users", json=identity(other_account)), 201)
    activate(other_invitation, other_account)
    saved["customers"].append(other_account)
    keep_record()
    with httpx.Client(base_url=host, timeout=20) as other_client:
        login(other_client, other_account)
        other_key = checked(other_client.get("/web/apikey"))["api_key"]
        for side in ("BUY", "SELL"):
            checked(other_client.post("/api/v1/placeorder", json={"apikey": other_key, "symbol": "NIFTY-DEMO-25000CE", "exchange": "NFO", "quantity": 25, "product": "NRML", "pricetype": "MARKET", "action": side}))
    own = checked(broker_b.get("/web/paper/trades"))["trades"]
    assert len(own) == 2 and all(row["user_id"] == other_invitation["id"] for row in own)
    assert all(row["user_id"] != other_invitation["id"] for row in checked(broker_a.get("/web/paper/trades"))["trades"])
    assert {row["username"] for row in checked(admin.get("/web/paper/trades"))["trades"]} == {accounts[0]["username"], other_account["username"]}
    print("PASS: manager trade history, user filters, pagination and two-broker isolation")

    # Broker disablement blocks existing browser sessions and API keys for all children.
    with httpx.Client(base_url=host, timeout=20) as blocked:
        login(blocked, accounts[0])
        checked(admin.patch(f"/web/paper/accounts/{broker_ids[0]}", json={"is_active": False}))
        checked(blocked.get("/auth/me"), 401)
        checked(broker_a.get("/auth/me"), 401)
        checked(blocked.post("/api/v1/quotes", json={"apikey": key_a, "symbol": "NIFTY-DEMO-FUT", "exchange": "NFO"}), 401)
        checked(admin.patch(f"/web/paper/accounts/{broker_ids[0]}", json={"is_active": True}))
        checked(blocked.get("/auth/me"), 401)  # Re-enabling must not resurrect revoked sessions.
        login(blocked, accounts[0])
        checked(blocked.get("/auth/me"))
    for client in broker_clients:
        client.close()
    print("PASS: broker disablement blocks children and re-enabling requires a fresh browser login")

    # Authentication boundary probes use only the temporary customer and keys.
    with httpx.Client(base_url=host, timeout=20) as security_client:
        login(security_client, accounts[1])
        old_key = checked(security_client.get("/web/apikey"))["api_key"]
        new_key = checked(security_client.post("/web/apikey"))["api_key"]
        assert old_key != new_key
        checked(security_client.post("/api/v1/quotes", json={"apikey": old_key, "symbol": "NIFTY-DEMO-FUT", "exchange": "NFO"}), 401)
        checked(security_client.post("/api/v1/quotes", json={"apikey": new_key, "symbol": "NIFTY-DEMO-FUT", "exchange": "NFO"}))
        checked(security_client.post("/api/v1/quotes", json={"apikey": ["invalid"]}), 401)
        for index in range(6):
            checked(security_client.post("/auth/login", json={"username": "qa_nonexistent_one", "password": "wrong-password"}), 401 if index < 5 else 429)
        checked(security_client.post("/auth/login", json={"username": "qa_nonexistent_two", "password": "wrong-password"}), 401)
        print("PASS: immediate key rotation, malformed-key rejection and separate login limits")
    async def flood_invalid_keys():
        import asyncio
        async with httpx.AsyncClient(base_url=host, timeout=20) as client:
            responses = await asyncio.gather(*[client.post("/api/v1/quotes", json={"apikey": "not-a-valid-key"}) for _ in range(65)])
            assert 429 in [response.status_code for response in responses]
            assert all(response.status_code in (401, 429) for response in responses)
    import asyncio
    asyncio.run(flood_invalid_keys())
    print("PASS: API admission limit rejects an invalid-key flood")

    cookie = admin.cookies.get("access_token")
    checked(admin.post("/auth/logout"))
    checked(admin.get("/auth/me", headers={"Cookie": f"access_token={cookie}"}), 401)
    print("PASS: server-side session revocation")
print("API checks complete. Disposable accounts and cache keys will be removed by the isolated runner." if os.environ.get("DHK_TEST_DB_NAME") else "API checks complete. QA accounts retained; cleanup must use the same explicitly selected QA target.")

