"""Supervise an ephemeral localhost.run tunnel.

The free tier disconnects an *idle* tunnel, and every reconnect issues a NEW
hostname. A naive pinger that caches the first URL then keeps hammering a dead
host, so the replacement tunnel is idle too and dies immediately -- an endless
reconnect loop. Observed hostnames in a single run:

    https://1d90ddf8261633.lhr.life
    https://d632f849d92fec.lhr.life
    https://e503cb67dee4a3.lhr.life

This supervisor watches the tunnel log, discovers the CURRENT hostname, keeps
that hostname warm, and restarts ssh when it exits. It is the correct shape for
an ephemeral tunnel -- and also the reason nobody would build production on one.

Usage: python tunnel_supervisor.py
"""
import os
import re
import signal
import subprocess
import sys
import time
import urllib.request

DIR = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(DIR, "tunnel_supervisor.log")
URL_RE = re.compile(r"tunneled with tls termination, (https://[a-z0-9]+\.lhr\.life)")
PING_INTERVAL = 20  # seconds; must stay well under the provider's idle timeout

ssh_proc = None
current_url = None


def start_ssh():
    global ssh_proc
    log = open(LOG, "a", encoding="utf-8", errors="replace")
    log.write(f"\n=== {time.strftime('%H:%M:%S')} starting ssh tunnel ===\n")
    log.flush()
    ssh_proc = subprocess.Popen(
        ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=NUL",
         "-o", "ServerAliveInterval=30",
         "-R", "80:localhost:8080", "nokey@localhost.run"],
        stdout=log, stderr=subprocess.STDOUT,
    )
    return ssh_proc


def latest_url():
    """Newest hostname mentioned in the log."""
    try:
        with open(LOG, encoding="utf-8", errors="replace") as fh:
            matches = URL_RE.findall(fh.read())
        return matches[-1] if matches else None
    except FileNotFoundError:
        return None


def ping(url):
    req = urllib.request.Request(url + "/health", headers={"User-Agent": "lab10-supervisor"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status, r.read().decode().strip()


def shutdown(*_):
    if ssh_proc and ssh_proc.poll() is None:
        ssh_proc.terminate()
    print("supervisor stopped", flush=True)
    sys.exit(0)


signal.signal(signal.SIGINT, shutdown)
signal.signal(signal.SIGTERM, shutdown)

start_ssh()
while True:
    time.sleep(PING_INTERVAL)

    if ssh_proc.poll() is not None:
        rc = ssh_proc.returncode
        print(f"{time.strftime('%H:%M:%S')} ssh exited rc={rc}; restarting", flush=True)
        current_url = None
        start_ssh()
        time.sleep(12)  # let the new hostname appear
        continue

    found = latest_url()
    if found != current_url:
        current_url = found
        print(f"{time.strftime('%H:%M:%S')} current hostname: {current_url}", flush=True)

    if not current_url:
        continue

    try:
        status, body = ping(current_url)
        print(f"{time.strftime('%H:%M:%S')} ping {current_url}: {status} {body}", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"{time.strftime('%H:%M:%S')} ping {current_url}: ERR {type(exc).__name__}", flush=True)
