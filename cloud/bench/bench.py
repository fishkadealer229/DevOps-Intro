"""Lab 10 latency harness.

Measures warm-path latency for a QuickNotes endpoint two ways:

  * in-process (this script): excludes client process-spawn cost, so it shows
    what the *network path + server* actually costs.
  * via hyperfine (if present): the tool the lab names, which forks curl each
    run and therefore includes Windows process-spawn overhead.

Reporting both is deliberate: the gap between them is exactly the "what is the
slow part of warm latency" question in the report.

Usage:
    python bench.py <base-url> [--runs 50] [--path /health]
"""
import argparse
import json
import statistics
import sys
import time
import urllib.request


def percentile(values, pct):
    """Nearest-rank percentile — same definition hyperfine/wrk lean on."""
    if not values:
        return float("nan")
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, int(round((pct / 100.0) * len(ordered) + 0.5)) - 1))
    return ordered[k]


def measure(url, runs, timeout=60, keepalive=False):
    """Time `runs` requests.

    keepalive=False opens a fresh connection per request (what curl/hyperfine
    do), so every sample also pays DNS + TCP + TLS. keepalive=True reuses one
    connection, which isolates the steady-state network cost from the
    per-request setup cost. The difference between the two is the answer to
    "what dominates warm latency" for a tunnel.
    """
    import http.client
    from urllib.parse import urlsplit

    samples = []
    codes = {}
    parts = urlsplit(url)
    conn = None

    if keepalive:
        cls = http.client.HTTPSConnection if parts.scheme == "https" else http.client.HTTPConnection
        conn = cls(parts.netloc, timeout=timeout)

    for i in range(runs):
        start = time.perf_counter()
        try:
            if keepalive:
                try:
                    conn.request("GET", parts.path or "/",
                                 headers={"User-Agent": "lab10-bench", "Connection": "keep-alive"})
                    resp = conn.getresponse()
                    resp.read()
                    code = resp.status
                except Exception:
                    # Reconnect once: a pooled connection may have been closed.
                    conn.close()
                    cls = http.client.HTTPSConnection if parts.scheme == "https" else http.client.HTTPConnection
                    conn = cls(parts.netloc, timeout=timeout)
                    conn.request("GET", parts.path or "/",
                                 headers={"User-Agent": "lab10-bench", "Connection": "keep-alive"})
                    resp = conn.getresponse()
                    resp.read()
                    code = resp.status
            else:
                req = urllib.request.Request(url, headers={"User-Agent": "lab10-bench"})
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    r.read()
                    code = r.status
        except Exception as exc:  # noqa: BLE001
            code = f"ERR:{type(exc).__name__}"
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        samples.append(elapsed_ms)
        codes[code] = codes.get(code, 0) + 1
        if (i + 1) % 10 == 0:
            print(f"  ... {i + 1}/{runs}", file=sys.stderr)

    if conn is not None:
        conn.close()

    good = [s for s in samples if isinstance(s, float)]
    return {
        "url": url,
        "runs": runs,
        "connection": "keep-alive (one pooled connection)" if keepalive else "fresh connection per request",
        "status_codes": {str(k): v for k, v in codes.items()},
        "min_ms": round(min(good), 2),
        "p50_ms": round(percentile(good, 50), 2),
        "p95_ms": round(percentile(good, 95), 2),
        "mean_ms": round(statistics.fmean(good), 2),
        "max_ms": round(max(good), 2),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base_url")
    ap.add_argument("--runs", type=int, default=50)
    ap.add_argument("--path", default="/health")
    ap.add_argument("--label", default="")
    ap.add_argument("--warmup", type=int, default=5)
    ap.add_argument("--keepalive", action="store_true",
                    help="reuse one connection (isolates TLS/TCP setup from RTT)")
    args = ap.parse_args()

    url = args.base_url.rstrip("/") + args.path
    label = args.label or url
    print(f"# warm-path benchmark: {label}")
    print(f"# target: {url}  runs={args.runs}  warmup={args.warmup}")

    # Warm-up is not optional: first request pays DNS + TLS + any cold path.
    for _ in range(args.warmup):
        try:
            with urllib.request.urlopen(
                urllib.request.Request(url, headers={"User-Agent": "lab10-bench"}),
                timeout=60,
            ) as r:
                r.read()
        except Exception as exc:  # noqa: BLE001
            print(f"# warmup failed: {exc}", file=sys.stderr)

    result = measure(url, args.runs, keepalive=args.keepalive)
    result["label"] = label
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
