"""One GET request — used as the command hyperfine benchmarks.

Kept as a file so the command line hyperfine runs stays short and its quoting
cannot be blamed for the result.
"""
import sys
import urllib.request

url = sys.argv[1]
req = urllib.request.Request(url, headers={"User-Agent": "lab10-probe"})
with urllib.request.urlopen(req, timeout=60) as resp:
    resp.read()
