"""POST a note and read the collection back — proves writes work publicly.

curl.exe on this host cannot do HTTPS (schannel credential failure), so the
public API is exercised with Python's OpenSSL-backed client instead.
"""
import json
import sys
import urllib.request

base = sys.argv[1].rstrip("/")
title = sys.argv[2] if len(sys.argv) > 2 else "public-write-test"


def call(method, path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        base + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json", "User-Agent": "lab10-post"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = resp.read().decode()
        return resp.status, body


print("before :", call("GET", "/health")[1].strip())
status, body = call("POST", "/notes", {"title": title,
                                       "body": "written through the public edge URL"})
print(f"POST   : {status} {body.strip()}")
print("after  :", call("GET", "/health")[1].strip())
notes = json.loads(call("GET", "/notes")[1])
print(f"GET /notes -> {len(notes)} notes; last = {notes[-1]}")
