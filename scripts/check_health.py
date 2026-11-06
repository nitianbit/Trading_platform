"""Exit nonzero when public readiness is degraded; suitable for a host timer."""
import json
import os
import sys
from urllib.request import urlopen

url = sys.argv[1] if len(sys.argv) > 1 else "https://" + os.environ["APP_DOMAIN"] + "/health"
try:
    with urlopen(url, timeout=5) as response:
        body = json.load(response)
        healthy = response.status == 200 and body.get("status") == "ok" and all(body.get("checks", {}).get(key) is True for key in ("database", "redis", "feed"))
except Exception:
    healthy = False
print("DHK readiness: " + ("ok" if healthy else "degraded"))
raise SystemExit(0 if healthy else 1)
