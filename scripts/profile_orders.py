"""Profile completed order work only in a nonce-marked disposable DB."""
import cProfile
import pstats
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sqlalchemy import select
from backend.sandbox._db import session_scope
from backend.models.settings import AppSettings
from backend.models.user import User
from backend.paper.market import publish_quotes
from backend.services.market_data_cache import get_market_data_cache
from backend.services.sandbox_service import place_order


def main():
    with session_scope() as db:
        if len(sys.argv)!=2 or db.scalar(select(AppSettings.value).where(AppSettings.key=="paper_load_test_owner"))!=sys.argv[1]: raise RuntimeError("Owned load database required")
        ids=list(db.scalars(select(User.id).where(User.username.like("load_user_%")).order_by(User.id)))
    if len(ids)!=64: raise RuntimeError("Expected 64 owned load accounts")
    get_market_data_cache()._redis_enabled=False
    publish_quotes()
    profile=cProfile.Profile(); profile.enable()
    for index in range(150):
        if index%10==0: publish_quotes()
        ok,result,status=place_order(ids[index%64],dict(symbol="NIFTY-DEMO-FUT",exchange="NFO",product="NRML",pricetype="MARKET",quantity=25,action="BUY" if (index//64)%2==0 else "SELL"))
        if not ok: raise RuntimeError("Profile order rejected")
    profile.disable()
    pstats.Stats(profile).strip_dirs().sort_stats("cumulative").print_stats(40)


if __name__=="__main__": main()
