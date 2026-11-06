"""Private fixtures only inside a nonce-marked disposable deployment DB."""
import json
import secrets
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sqlalchemy import select
from backend.models.user import User
from backend.models.auth import ApiKey
from backend.models.audit import ActiveSession
from backend.models.settings import AppSettings
from backend.sandbox._db import session_scope
from backend.security import generate_api_key, hash_api_key, encrypt_value, create_access_token


def main():
    if len(sys.argv)!=2 or len(sys.argv[1])!=32: raise RuntimeError("Owned test nonce required")
    with session_scope() as db:
        if db.scalar(select(AppSettings.value).where(AppSettings.key=="paper_load_test_owner"))!=sys.argv[1]:
            raise RuntimeError("Refusing fixtures in a database not owned by this load run")
        broker=User(username="load_broker",email="load-broker@example.com",role="broker",password_hash="not-a-login-password")
        db.add(broker); db.flush()
        actors=[]
        for index in range(64):
            user=User(username=f"load_user_{index}",email=f"load-{index}@example.com",role="user",broker_id=broker.id,password_hash="not-a-login-password")
            db.add(user); db.flush()
            key=generate_api_key(); token=secrets.token_hex(32)
            db.add(ApiKey(user_id=user.id,api_key_hash=hash_api_key(key),api_key_encrypted=encrypt_value(key)))
            db.add(ActiveSession(user_id=user.id,session_token=token,device_info="isolated load fixture",ip_address="127.0.0.1"))
            actors.append({"id":user.id,"key":key,"cookie":create_access_token({"sub":str(user.id),"username":user.username,"broker":None,"jti":token})})
    # Captured privately by the parent; never print this result to human logs.
    print(json.dumps(actors))


if __name__=="__main__": main()
