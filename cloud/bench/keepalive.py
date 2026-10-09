"""Keep a free-tunnel session alive.

localhost.run disconnects idle tunnels with
    "Received disconnect ... tunnel activity timeout"
so a background pinger keeps a request flowing. This is also the clearest
possible evidence for why a free tunnel is not a production hosting option:
an idle production service must keep serving, and this one hangs up.
"""
import sys
import time
import urllib.request

url = sys.argv[1].rstrip("/") + "/health"
interval = int(sys.argv[2]) if len(sys.argv) > 2 else 45

pk = 0
while True:
    pk += 1
    try:
        with urllib.request.urlopen(
            urllib.request.Request(url, headers={"User-Agent": "lab10-keepalive"}),
            timeout=45,
        ) as r:
            body = r.read().decode().strip()
        print(f"{time.strftime('%H:%M:%S')} ping {pk}: {r.status} {body}", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"{time.strftime('%H:%M:%S')} ping {pk}: ERR {type(exc).__name__} {str(exc)[:60]}", flush=True)
    time.sleep(interval)
