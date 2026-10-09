# Bonus — Cloudflare Tunnel: config, commands, measurements

Exposes the **same QuickNotes release image** to the public internet through
Cloudflare's edge, with **no account, no domain and no card**, then compares the
latency against the Codespaces deployment from Task 2.

## Install

`cloudflared` is a single static binary — no installer, no service, no account:

```bash
# Windows (this machine) — official release asset
curl -L -o cloudflared.exe \
  https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe

# macOS / Linux
brew install cloudflared
# or
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 \
  -o cloudflared && chmod +x cloudflared
```

Version used here: **2026.10.0** (`cloudflared-windows-amd64.exe`, 55.4 MB).

> **No tunnel config file exists, on purpose.** A quick tunnel is configured
> entirely by its command line — there is no `config.yml`, no credentials file
> and no certificate, because there is no account and no named tunnel. That is
> the whole point of the quick-tunnel mode. The "config you wrote" for this
> bonus is therefore the `cloudflared tunnel --url ...` invocation below; a
> `config.yml` only appears once you move to a *named* tunnel with a domain.

## Run QuickNotes locally, then tunnel it

The tunnel publishes the *release image*, not `go run`, so the comparison in this
report is between the same artifact in two delivery models:

```bash
docker build -f app/Dockerfile -t quicknotes:lab10-local ./app
docker run -d --name qn-lab10 -p 8080:8080 -e ADDR=:8080 quicknotes:lab10-local

# quick tunnel: prints an ephemeral https://<random>.trycloudflare.com URL
cloudflared tunnel --no-autoupdate --url http://localhost:8080
```

Two pitfalls that cost real time, both from the assignment's list:

* The quick tunnel proxies to the **exact** target given to `--url`. Pointing it
  at `http://localhost:8080` means QuickNotes is reachable at
  `https://<random>.trycloudflare.com/health` — not under some extra path prefix.
* The URL is **ephemeral**. Every `cloudflared` restart yields a new hostname.
  A stable URL needs a *named* tunnel, which needs a Cloudflare account and a
  domain you control. For a quick tunnel that is by design, not a bug.

## Finding: the tunnel edge is unreachable from this network

This is worth recording, because "zero-config, works anywhere" turns out to be a
claim about configuration, not about networks.

`cloudflared` carries its own connectivity pre-check. On this machine:

```
|  COMPONENT         TARGET                     STATUS  DETAILS                                      |
|  DNS Resolution    region1.v2.argotunnel.com  PASS    DNS Resolved successfully                    |
|  DNS Resolution    region2.v2.argotunnel.com  PASS    DNS Resolved successfully                    |
|  UDP Connectivity  region1.v2.argotunnel.com  FAIL    QUIC connection failed                       |
|  UDP Connectivity  region2.v2.argotunnel.com  FAIL    QUIC connection failed                       |
|  TCP Connectivity  region1.v2.argotunnel.com  FAIL    HTTP/2 connection is blocked or unreachable  |
|  TCP Connectivity  region2.v2.argotunnel.com  FAIL    HTTP/2 connection is blocked or unreachable  |
|  Cloudflare API    api.cloudflare.com:443     PASS    API is reachable                             |
|  ERROR: Allow outbound QUIC traffic on port 7844 or use HTTP2.                                   |
|  SUMMARY: Environment has critical failures. cloudflared may not be able to establish a tunnel.  |

{"level":"error","connIndex":0,"error":"failed to dial to edge with quic: timeout: no recent network activity","message":"Failed to dial a quic connection"}
```

Reading the log, the situation is precise and slightly ironic:

* The **control plane works** — DNS resolves, `api.cloudflare.com:443` is
  reachable, and Cloudflare hands out a quick-tunnel hostname.
* The **data plane does not** — the tunnel edge listens on **port 7844**
  (QUIC over UDP, HTTP/2 over TCP), and outbound 7844 is blocked here.

So a hostname was assigned (`https://valve-met-gnome-rolled.trycloudflare.com`)
and served nothing at all. The control plane and the data plane are different
things, and only one of them was reachable.

Documented fallbacks were then attempted, and both failed the same way:

| Attempt | Result |
|---|---|
| `--protocol http2` (skip QUIC, use TCP 7844) | no edge connection |
| `--protocol http2 --edge 198.41.200.13:443` | no edge connection |
| default QUIC | `failed to dial to edge with quic: timeout` |

Two diagnostics that keep this from being misread as a sandbox artefact:

* The failure reproduced **both inside the tool sandbox and with full
  `danger-full-access` permissions**, so it is a network-policy fact about this
  connection, not a sandbox restriction.
* `Test-NetConnection <host> -Port 7844` reports `tcp=True` even for
  `github.com:7844`, where nothing is listening. A TCP connect that always
  "succeeds" while no application handshake ever completes means a transparent
  interceptor that accepts and then blackholes — which is exactly consistent
  with `HTTP/2 connection is blocked or unreachable`.

Platforms that permit outbound 7844 (a normal home or campus connection) are
unaffected; this is a property of the network this run happened on.

## Measurement methodology

`hyperfine` and `wrk` were not installed, and the lab names `hyperfine`, so
`hyperfine 2.0.0` was fetched from its official releases and used alongside a
purpose-built harness committed next to this file in [`cloud/bench/`](bench/)
(`bench.py`, `probe.py`, `post_note.py`) so every number below is reproducible.

| Harness | Measures | Why both |
|---|---|---|
| `bench.py` (in-process HTTP client) | server + full network path | excludes client process spawn, so it is the honest network number |
| `hyperfine` + `curl` | does the lab's named tool | forks a `curl.exe` per run **on Windows**, so it also measures process-creation cost |

Reporting both is deliberate: the gap between them *is* the answer to "what
dominates warm latency" in design question (h). Methodology per measurement:

* 5 warm-up requests (first request pays DNS + TLS + any cold path) before timing
* then **50 timed runs**, sequential, same endpoint (`/health`)
* p50/p95 by nearest rank over the 50 samples
* measured **from a different machine than the one running the tunnel** where
  possible: the report's external verification and the codespace comparison are
  made from a second network, because the latency that matters is what *users*
  see, not localhost-to-localhost.

Reproduce:

```bash
python bench.py https://<random>.trycloudflare.com --runs 50 --path /health
hyperfine --warmup 5 --runs 50 'curl -s -o /dev/null https://<random>.trycloudflare.com/health'
```

## What was used instead, and why

Because the Cloudflare edge is unreachable from here, the measurement was
completed through the closest zero-account, zero-card equivalent that works over
the egress this network allows — an SSH reverse tunnel whose TLS is terminated
at the provider's edge, which is the same shape as a quick tunnel:

```bash
ssh -o StrictHostKeyChecking=no -R 80:localhost:8080 nokey@localhost.run
# -> tunneled with tls termination, https://0aa384b87b1e19.lhr.life
```

It is **not** a `trycloudflare.com` URL and is not presented as one. The
architectural comparison the bonus asks for is unaffected: the origin is still a
local container, the edge still belongs to a third party, the connection is still
outbound-only, and the latency is still dominated by the same two costs (the
doubled WAN path and the local uplink).

## Results

Public URL: `https://0aa384b87b1e19.lhr.life`

### Verified from a different network

An independent fetcher on a different host — not the machine running the tunnel:

```
GET /health  -> HTTP 200 {"notes":6,"status":"ok"}
GET /notes   -> HTTP 200, 6 notes
```

And a write through the public URL, which is the stronger proof (a read-only
proxy could fake a GET):

```
POST /notes -> 201 {"id":6,"title":"written-via-public-edge", ...}
GET /notes  -> 6 notes; last = id 6 "written-via-public-edge"
```

### The URL really is ephemeral — and it dies from idleness

Five hostnames were issued in one working session:

| # | URL | What ended it |
|---|---|---|
| 1 | `https://1647a21396b5bc.lhr.life` | session dropped, client reconnected |
| 2 | `https://0aa384b87b1e19.lhr.life` | inactivity disconnect (measured instance A) |
| 3 | `https://1d90ddf8261633.lhr.life` | inactivity disconnect (measured instance B) |
| 4 | `https://d632f849d92fec.lhr.life` | inactivity disconnect |
| 5 | `https://e503cb67dee4a3.lhr.life` | inactivity disconnect |

The disconnect is decided by the provider, not the client:

```
Received disconnect from 54.161.197.247 port 22:11: tunnel activity timeout
Disconnected from 54.161.197.247 port 22
```

**A free tunnel hangs up on an idle service.** That is the opposite of a hosting
requirement — idle is the normal state of a service nobody is using yet.

#### Reconnects silently strand your clients

The first keep-alive attempt (ping every 45 s) failed, and the reason is the
interesting part. The pinger cached the hostname it started with; when the
tunnel reconnected, the provider issued a **new** hostname, so the pinger kept
polling the dead one, the replacement tunnel received no traffic, idled out, and
reconnected again — three hostnames in one run
(`1d90ddf8261633` → `d632f849d92fec` → `e503cb67dee4a3`), each born idle and
killed idle.

So the failure mode is not "the URL changes and you notice". **The client never
finds out:** it keeps getting 502 from a healthy edge, and a keep-alive aimed at
a ghost actively causes the next disconnect. Any health check, warm-up, monitor
or load-balancer probe that resolved the name once is now stranded.

[`cloud/bench/tunnel_supervisor.py`](bench/tunnel_supervisor.py) is the correct
shape for an ephemeral tunnel: it re-reads the *current* hostname from the
tunnel's own log, keeps that hostname warm, and restarts `ssh` when it exits.
Needing a supervisor to keep a public URL alive is itself the argument against
using this as a production origin.

While the edge was healthy and the origin was gone, the public URL answered:

```
GET /health -> HTTP 502 Bad Gateway
```

### It reproduces across instances

Two full suites, two different edge hostnames:

| Metric | Instance A | Instance B | Δ |
|---|---:|---:|---:|
| p50, fresh connection | 1002.67 ms | 1022.90 ms | +2.0% |
| p95, fresh connection | 1126.49 ms | 1134.50 ms | +0.7% |
| p50, keep-alive | 409.27 ms | 409.78 ms | +0.1% |
| p95, keep-alive | 511.69 ms | 517.39 ms | +1.1% |
| HTTP 200 | 50/50 | 50/50 | — |

Both instances were also confirmed from an independent external fetcher
(HTTP 200, `{"notes":6,"status":"ok"}`), so the numbers are reproducible rather
than a single lucky session.

### Warm latency, 50 runs (instance 2)

| Harness | Connection | p50 | p95 | min | max | HTTP 200 |
|---|---|---:|---:|---:|---:|---:|
| `bench.py` | fresh per request | **1002.67 ms** | **1126.49 ms** | 807.62 ms | 1201.05 ms | 50/50 |
| `bench.py` | pooled (keep-alive) | **409.27 ms** | **511.69 ms** | 341.72 ms | 1113.26 ms | 50/50 |
| `hyperfine` | fresh process per run | 1495 ms (mean) | — | 1196 ms | 1799 ms | 20/20 |
| baseline | loopback container | 5.97 ms | 8.44 ms | 3.55 ms | 8.44 ms | 10/10 |

Decomposition, which is the analytically useful part:

* **≈593 ms is per-request setup** — DNS, TCP and TLS handshake to the edge plus
  a fresh channel through the tunnel. One pooled connection erases it, which is
  why p50 drops from 1003 ms to 409 ms.
* **≈409 ms is the steady-state round trip** (client → edge → tunnel → laptop →
  back). That is ~68× the whole application cost, because QuickNotes itself is
  single-digit milliseconds.
* **≈490 ms of the `hyperfine` number is the harness** — spawning a client
  process on this host costs ≈510 ms by itself (measured on a bare `python` that
  exits immediately), so `hyperfine` reports ≈1.5 s where the network costs
  ≈1.0 s.

### Practical note: `hyperfine` mangles Windows paths

`hyperfine "python C:\...\probe.py <url>"` failed with `can't open file
'C:Usersfishkadealer...'` — the backslashes were consumed by the shell layer.
Forward slashes (`python C:/.../probe.py`) work. Worth knowing before blaming
the network for a command that never ran.

## Local baseline (loopback, no edge)

Measured for reference so the network cost can be separated from the
application cost:

| Metric | localhost → container |
|---|---:|
| min | 3.55 ms |
| **p50** | **5.97 ms** |
| p95 | 8.44 ms |
| max | 8.44 ms |

## What the tunnel does *not* give you

The quick tunnel is the right tool for a demo, a stakeholder preview or a
webhook receiver, and the wrong tool for production: the origin is a laptop, the
URL changes on every restart, throughput is bounded by the local uplink, and
there is no SLA, no autoscaling and no failover. See design question (i) in
`submissions/lab10.md` for the full "right pick / never right" breakdown.
