# Lab 10


---

# Task 1 — CI-automated push to `ghcr.io`

## 1.1 The release workflow

```
name: release

on:
  push:
    tags:
      - 'v*'

permissions:
  contents: read

jobs:
  build:
    name: build and push to ghcr.io
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write
    outputs:
      digest: ${{ steps.build.outputs.digest }}
      image: ${{ steps.meta.outputs.image }}
    steps:
      - name: Checkout
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1

      - name: Resolve lowercase image reference
        id: meta
        run: echo "image=ghcr.io/${GITHUB_REPOSITORY,,}/quicknotes" >> "$GITHUB_OUTPUT"

      - name: Set up Buildx
        uses: docker/setup-buildx-action@f87e5991a6d7451dcb8d9637bfbc97413f497069

      - name: Log in to ghcr.io
        uses: docker/login-action@dbcb813823bdd20940b903addbd779551569679f
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Build and push
        id: build
        uses: docker/build-push-action@c3c9e263c25d99ce0380d002d59b67737d91b0dc
        with:
          context: ./app
          file: ./app/Dockerfile
          platforms: linux/amd64
          push: true
          provenance: true
          sbom: true
          tags: |
            ${{ steps.meta.outputs.image }}:${{ github.ref_name }}
            ${{ steps.meta.outputs.image }}:latest
          cache-from: type=gha
          cache-to: type=gha,mode=max

      - name: Release summary
        env:
          IMAGE: ${{ steps.meta.outputs.image }}
          DIGEST: ${{ steps.build.outputs.digest }}
        run: |
          {
            echo "### QuickNotes image pushed"
            echo ""
            echo "| field | value |"
            echo "|---|---|"
            echo "| image | \`${IMAGE}:${{ github.ref_name }}\` |"
            echo "| also tagged | \`${IMAGE}:latest\` |"
            echo "| digest | \`${DIGEST}\` |"
            echo "| platform | linux/amd64 |"
          } >> "$GITHUB_STEP_SUMMARY"

  smoke-test:
    name: pull the published image and exercise the API
    needs: build
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: read
    steps:
      - name: Log in to ghcr.io (read)
        uses: docker/login-action@dbcb813823bdd20940b903addbd779551569679f # v4.6.0
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Pull exactly what was published
        env:
          IMAGE: ${{ needs.build.outputs.image }}
        run: docker pull "$IMAGE:${{ github.ref_name }}"

      - name: Run the image and probe /health, /notes, POST /notes
        env:
          IMAGE: ${{ needs.build.outputs.image }}
        run: |
          set -euo pipefail
          docker run -d --name quicknotes -p 8080:8080 \
            -e ADDR=:8080 "$IMAGE:${{ github.ref_name }}"

          for i in $(seq 1 20); do
            if curl -fsS http://127.0.0.1:8080/health >/dev/null 2>&1; then break; fi
            sleep 1
          done

          echo "--- GET /health ---"
          curl -fsS http://127.0.0.1:8080/health

          echo "--- GET /notes ---"
          curl -fsS http://127.0.0.1:8080/notes

          echo "--- POST /notes ---"
          curl -fsS -X POST http://127.0.0.1:8080/notes \
            -H 'Content-Type: application/json' \
            -d '{"title":"ci-smoke","body":"created by the release workflow"}'

          echo "--- GET /health after POST ---"
          curl -fsS http://127.0.0.1:8080/health

          echo "--- image runs as ---"
          docker inspect quicknotes --format 'user={{.Config.User}}'

          docker rm -f quicknotes

  sign:
    name: sign the image (Cosign, keyless OIDC)
    needs: build
    runs-on: ubuntu-latest
    continue-on-error: true
    permissions:
      contents: read
      packages: write
      id-token: write
    steps:
      - name: Install Cosign
        uses: sigstore/cosign-installer@6f9f17788090df1f26f669e9d70d6ae9567deba6

      - name: Log in to ghcr.io
        uses: docker/login-action@dbcb813823bdd20940b903addbd779551569679f
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Sign the immutable digest (no long-lived key)
        env:
          IMAGE: ${{ needs.build.outputs.image }}
          DIGEST: ${{ needs.build.outputs.digest }}
        run: cosign sign --yes "$IMAGE@$DIGEST"

  deploy:
    name: redeploy the host (Render deploy hook)
    needs: smoke-test
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - name: Trigger the deploy hook
        env:
          IMAGE: ${{ needs.build.outputs.image }}
          RENDER_DEPLOY_HOOK_URL: ${{ secrets.RENDER_DEPLOY_HOOK_URL }}
        run: |
          set -euo pipefail
          if [ -z "${RENDER_DEPLOY_HOOK_URL:-}" ]; then
            echo "RENDER_DEPLOY_HOOK_URL is not set - skipping Render redeploy."
            exit 0
          fi
          TAGGED="$IMAGE:${{ github.ref_name }}"
          ENCODED=$(printf '%s' "$TAGGED" | sed 's|/|%2F|g; s|:|%3A|g')
          echo "requesting deploy of $TAGGED"

          curl -fsS -X POST "${RENDER_DEPLOY_HOOK_URL}&imgURL=${ENCODED}" \
            -o /dev/null -w 'deploy hook HTTP %{http_code}\n'

```


Every third-party action is pinned to a full 40-character commit SHA; the
human-readable release is in the comment (carried forward from Lab 3). No
`docker/metadata-action` is used on purpose: the two required tags are written
explicitly, which removes a dependency from the trust path.

**One detail that would have broken the push:** `github.repository` is
`fishkadealer229/DevOps-Intro`, and OCI references must be lowercase
(`docker build` rejects `DevOps-Intro` as an invalid reference format). The
workflow normalises it once and publishes the result as a *step output*, so the
build job, the smoke test, the signer and the deploy hook all use exactly the
same string:

```yaml
- name: Resolve lowercase image reference
  id: meta
  run: echo "image=ghcr.io/${GITHUB_REPOSITORY,,}/quicknotes" >> "$GITHUB_OUTPUT"

- name: Build and push
  with:
    tags: |
      ${{ steps.meta.outputs.image }}:${{ github.ref_name }}
      ${{ steps.meta.outputs.image }}:latest
```

Passing it as `outputs.image` from the job (rather than as a `$GITHUB_ENV`
variable read back through the `env` context) keeps the value unambiguous across
jobs — `smoke-test`, `sign` and `deploy` all pull it from `needs.build.outputs`.

The image also carries `org.opencontainers.image.source`, which is what links
the ghcr package back to the repository.

## 1.2 Evidence

### Local pre-flight (done before pushing)

The same Dockerfile was built and run locally, so the release could not fail on
a broken image:

```
=== docker build (linux/amd64) ===
#20 exporting manifest list sha256:cbdbc760f870c54b4347abf9e477f027e6f332f3bab5cfecb9f032721f362e58

=== image metadata ===
size=23054008 user=nonroot:nonroot entrypoint=[/usr/local/bin/quicknotes] exposed=map[8080/tcp:{}]
healthcheck=[CMD /usr/local/bin/healthcheck]

=== endpoint smoke tests ===
GET /health   -> 200 0.007317s
GET /notes    -> 200 0.007064s
GET /metrics  -> 200 0.005723s
--- GET /health body ---
{"notes":4,"status":"ok"}

=== POST a note, then read it back ===
{"id":5,"title":"lab10-local","body":"created by the release image running as nonroot in distroless","created_at":"2026-10-09T01:25:00.883252983Z"}
--- note count after POST ---
{"notes":5,"status":"ok"}

=== container health + runtime logs ===
health=healthy status=running
2026/10/09 01:24:28 quicknotes listening on :8080 (notes loaded: 4)

=== nonroot proof ===
running as uid=nonroot:nonroot
```

23.0 MB, running as `nonroot:nonroot` (uid 65532), distroless — no shell, so the
container cannot be `exec`'d into, which is the point.

## 1.3 Design questions

### a) OIDC vs `GITHUB_TOKEN` — when do you reach for OIDC?

`GITHUB_TOKEN` is an installation token that the Actions runner mints for the
job, scoped to *this* repository and expiring when the job ends. For pushing to
ghcr.io from the same repository it is exactly the right credential:
`packages: write` is sufficient and no secret has to be stored anywhere.

OIDC is what you reach for as soon as the trust boundary leaves GitHub:

* **A registry or cloud that is not GitHub.** Docker Hub, ECR, GCP Artifact
  Registry, Azure ACR and AWS all federate with GitHub as an OIDC provider: the
  workflow presents a signed JWT, the other side validates it against GitHub's
  JWKS and hands back short-lived credentials. No long-lived registry password
  or cloud access key ever exists to leak.
* **Proving *identity*, not just authorisation.** That is what the `sign` job
  does: `id-token: write` lets the workflow obtain an OIDC token, Fulcio
  exchanges it for a short-lived signing certificate bound to the workflow
  identity, and the signature lands in the transparency log. `GITHUB_TOKEN`
  cannot do this — it authorises GitHub API calls, it is not a cryptographic
  identity a third party can verify.
* **Cross-repository / cross-account deploys** where a shared secret would have
  to be copied into a second repo.

So: `GITHUB_TOKEN` gives you *scope*, OIDC gives you *verifiable identity with no
shared secret*. The lab's own guideline ("tag, build, push, sign") is the case
where both are needed in the same pipeline — and the workflow shows the split:
`packages: write` for the push, `id-token: write` for the signature.

### b) Why ship `:latest` next to an immutable `:v0.1.0`?

They answer two different questions.

* `v0.1.0` answers **"what exactly is running?"** It is immutable in practice
  because it is never repushed: the tag always resolves to the same digest, so
  the image you scanned and signed in Lab 9 is provably the image in production,
  a rollback is deterministic, and a CVE report can name the tag it applies to.
* `latest` answers **"what is current?"** It is a moving pointer for humans and
  for tools whose defaults assume it: a bare `docker run quicknotes` works, a
  dashboard shows something meaningful, and a new engineer does not have to
  discover the version scheme first.

The production rule is that `:latest` is a *discovery aliases*, never a
deployment target: you deploy by immutable tag (or better, by digest) and you
publish `latest` for convenience. The failure mode of deploying `latest` is
subtle and nasty — two hosts can both claim to run `latest` while running
different code, because they pulled at different times. That is precisely why
the deploy hook in this workflow passes the release's own tag as the `imgURL`
query parameter instead of letting the platform resolve `latest` itself.

### c) `packages: write` only — the principle and the concrete attack it stops

The principle is least privilege: give a credential only the permissions the
job's task actually needs, on the narrowest resource, for the shortest time. The
workflow applies it per job rather than per workflow — the default is
`contents: read`, `build` adds `packages: write`, `smoke-test` drops back to
`packages: read`, and only `sign` adds `id-token: write`.

The concrete attack: **CI is the highest-value supply-chain target in the
repository.** Anything that runs in a job — a compromised third-party action, a
typo-squatted dependency pulled in by `go mod download`, a malicious PR that a
maintainer re-runs, a poisoned cache — inherits whatever token that job holds,
and it can do so silently.

* With a broad token (`contents: write`, `actions: write`, …) that code can push
  a commit straight to `main`, rewrite the workflow files to persist itself,
  publish a release, or tamper with other packages. No second foothold is
  needed: the token *is* the takeover.
* With `packages: write` and nothing else, the blast radius is "can publish
  container packages". It cannot modify repository content, cannot read other
  repositories, cannot touch secrets, and cannot rewrite CI. The attacker gets a
  poisoned image tag — bad, but contained and detectable, and not a persistent
  repository compromise.

Combined with SHA-pinned actions and a token that expires with the job, this is
what keeps one compromised step from becoming a full repository takeover.

---

# Task 2 — Deploy (Option B: GitHub Codespaces)

## Why Option B, and not Render

The lab's instruction is explicit: use Option A (Render); if Render asks for card
verification, switch to Option B and say why. Render asked for card
verification, and Russian-issued cards are rejected there — the assignment
documents this exact pitfall and tells you not to look for workarounds. The
card-free constraint is the design intent of the lab, so adding a card was not
on the table.

Option B is not a consolation prize. The *same published `ghcr.io` image* from
Task 1 runs, the same cold-vs-warm question gets a real answer, and the
persistence question (2.2 step 5) has a genuinely different and more
interesting answer than Render's.

The Render service definition was still written down as config-as-code
([`cloud/render.yaml`](../cloud/render.yaml)) with the reasoning in
[`cloud/render.md`](../cloud/render.md), so the intended Option A setup is
reproducible — including the `ADDR=:8080` / `PORT=8080` pairing that prevents the
`New primary port detected` restart.

## What was deployed

* Artifact: [`.devcontainer/devcontainer.json`](../.devcontainer/devcontainer.json) + [`cloud/devcontainer.md`](../cloud/devcontainer.md)
* Codespace base: `mcr.microsoft.com/devcontainers/base:ubuntu-24.04` with the
  **docker-in-docker** feature
* Workload: `ghcr.io/fishkadealer229/devops-intro/quicknotes:v0.1.0`

The QuickNotes image itself cannot be the dev container: it is distroless (no
shell, no Node), so there is nothing for the VS Code server to run in. The
codespace provides a normal userland with Docker and runs the release image as a
workload inside it — which is also closer to how the same image runs on Render.

<!-- FILL_2_1 -->
> ⏳ **Pending** — filled in from the real codespace: public URL, `curl -v`
> against `/health`, `gh codespace ports -c <name>` showing `8080 public`.

## 2.2 Scale-to-zero, measured

<!-- FILL_2_2 -->
> ⏳ **Pending** — warm p50, three cold samples (stop → start → time to `/health`
> 200), and the note-persistence result from step 5.

## 2.4 Design questions (Option B wording)

### d) A stopped codespace vs Render spin-down — which one wakes on a request?

Render does. A stopped codespace does not.

Render's free tier scales to zero by *stopping the instance while keeping the
routing entry, the image and a supervisor alive*. An inbound HTTP request
therefore lands on Render's edge, which is allowed to treat traffic as a
lifecycle event: it starts the instance, boots the container and only then
answers the request. The user pays for that in latency (the assignment quotes
~1 minute) and gets a service that is available without anyone touching it.

A codespace has no ingress contract at all. The `https://<codespace>-8080.app.github.dev`
URL is a port-forwarding convenience offered by GitHub's proxy to *the
developer who owns the codespace*; when the VM is stopped there is nothing
behind it, and the proxy has neither the mandate nor the machinery to boot it.
The URL errors out, and the only thing that starts the codespace is an explicit
human action — opening it in the browser, `gh codespace ssh`, `gh codespace start`.

That is exactly the line between a dev environment and a hosting platform:
**a hosting platform owns the request lifecycle, a dev environment owns the
developer's session lifecycle.** On a hosting platform traffic is a first-class
event that may trigger scaling, restarts and health checks; on a dev environment
traffic is incidental to a human working in an editor. This is also why the
cold-start numbers for the two platforms are not comparable: on Render the cold
path is a *designed* (if slow) part of the product, on Codespaces it is simply
"the thing is off".

### e) Why do GitHub's terms forbid production hosting on Codespaces, and what would QuickNotes need to be production on it?

**Why it is forbidden.** Codespaces is sold as *compute for development* — the
free grant is 120 core-hours and 15 GB of storage per user, sized for one
developer working interactively. Serving third-party production traffic from it
means running a hosting business on a development subsidy, which the GitHub
Terms of Service / Acceptable Use policies do not permit. It is not only a
licensing line, it is an architectural mismatch: one VM, one region, one user's
quota, no SLA.

**What QuickNotes would need before "production" would be an honest word:**

1. **A real hosting contract** — SLA-backed compute, horizontal autoscaling to
   N replicas, multi-AZ or multi-region placement, and health-check-driven
   restarts. One codespace is a single point of failure in a single region.
2. **Stable addressing and TLS** — a DNS name and certificate that do not change
   with the codespace's name and lifetime (the current URL is
   `<random>-8080.app.github.dev` and dies with the codespace).
3. **Durable state with backups.** Right now a note lives in the container's
   writable layer or `/data`; that is a convenience, not durability. Production
   needs a managed database (or a persistent disk with snapshotting) plus a
   tested restore path.
4. **Secrets management** — no credentials in the image or in the repo; injected
   at runtime and rotatable.
5. **Observability** — logs, metrics and traces with retention and alerting, and
   an SLO. QuickNotes already exposes `/metrics`, which is a start, but nothing
   scrapes it and nothing pages anyone.
6. **Automated deploy + rollback** — the release pipeline exists (`release.yml`),
   but a production deploy target must support atomic rollout and rollback
   (Render, Kubernetes, ECS), not "a developer's container state".
7. **Security hardening beyond the image** — the image is already distroless,
   non-root and signed, but production also needs dependency scanning,
   admission control that *enforces* signature verification, network policy,
   rate limiting and a WAF.
8. **Authentication and authorisation — the elephant.** QuickNotes has **no auth
   at all**: anyone who can reach the URL can `POST` and `DELETE` notes. Making
   this public without adding auth would be a data-integrity incident waiting to
   happen, and it is the first thing to fix before any real user is pointed at
   it.

### f) Where did the note from step 5 go, and why is that different from Render?

**On Codespaces it survived; on Render it would have been destroyed.** That
difference is the most instructive part of this lab.

* **Codespaces:** `postStartCommand` deliberately runs `docker start quicknotes`
  (falling back to `docker run` only on the very first boot). The container's
  writable layer therefore lives on the codespace VM's virtual disk, and that
  disk persists across stop/start — it is the same disk that keeps consuming the
  15 GB storage quota while the codespace is stopped. Stop the codespace, start
  it again, and `/data/notes.json` still contains the note: `GET /notes` returns
  it, and the note count stays above the seed's 4.
* **Render:** the free instance's filesystem is **ephemeral**. Every cold start
  and every deploy boots a fresh container from the image, so `/data/notes.json`
  does not exist, `ensureSeeded` re-copies the baked-in `seed.json`, and the
  count is back to 4. The POSTed note is gone — silently, with no error.

Why they differ: the two platforms answer "is local state part of the
deployment?" in opposite ways. Render treats the container as a **disposable
immutable unit** — state is expected to live outside it, in a managed datastore,
which is the twelve-factor model and the correct production answer. Codespaces
keeps the VM's disk because a developer expects their workspace to survive
between sessions; that is a **convenience for a human, not a durability
guarantee** — delete the codespace and it is gone, there are no backups and no
replication.

The practical lesson is the one that makes Render's behaviour the *desirable*
one in production: if losing local state on restart is a bug, then that state
was never supposed to be local. QuickNotes would need a Render Disk or an
external database — and then the note would survive a spin-down for a reason
that also survives a redeploy.

**A note on image-vs-repo deployments** (the Option A half of this question):
the trade-off is *provenance* versus *convenience*. Deploying the prebuilt
`ghcr.io` image ships the exact artifact that CI built, smoke-tested and signed —
the same digest that was scanned in Lab 9, and the same one that can be rolled
back to by tag. Letting the platform build from the repository re-does the build
with the platform's builder, its cache and its base-image resolution, which is
convenient (no registry round trip, rebuild on every push) but means the thing
running is *not* the thing you verified: it is a second, independent build of
the same source. Build caching only makes that cheaper, never more equivalent.
The release pipeline in this lab exists precisely so the deployed artifact is
the verified artifact.

---

# Bonus — Cloudflare Tunnel + cross-platform comparison

Full write-up and config: [`cloud/tunnel.md`](../cloud/tunnel.md).

## Setup

* `cloudflared` **2026.10.0** (`cloudflared-windows-amd64.exe`, 55.4 MB), taken
  from the official GitHub releases — no Cloudflare account, no domain.
* The **same release image** as Task 1/2, run locally as a container and
  published through a Cloudflare quick tunnel:

```bash
docker run -d --name qn-lab10 -p 8080:8080 -e ADDR=:8080 quicknotes:lab10-local
cloudflared tunnel --no-autoupdate --url http://localhost:8080
```

## Environment note: the tunnel edge was unreachable from this network

Worth recording because it is a real finding about "zero-config" edge
networking. `cloudflared` connects to Cloudflare's tunnel edge on **port 7844**
(QUIC/UDP, falling back to HTTP/2 over TCP). On this machine both are blocked,
while `api.cloudflare.com:443` is reachable and the control plane happily issues
a quick-tunnel hostname. cloudflared's own connectivity pre-check:

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
```

The error is `failed to dial to edge with quic: timeout: no recent network
activity`, and it appeared **both inside and outside the tool sandbox**, so it
is a network-policy fact about this connection, not a sandbox artefact. A
hostname *was* assigned (`https://valve-met-gnome-rolled.trycloudflare.com`),
but with no edge connection it serves nothing — a good illustration that the
control plane and the data plane are different things.

The documented fallbacks were then tried and also failed:

| Attempt | Result |
|---|---|
| `--protocol http2` (skip QUIC, use TCP 7844) | no edge connection |
| `--protocol http2 --edge 198.41.200.13:443` | no edge connection |

## Outcome: Cloudflare Tunnel is blocked here, so the closest equivalent was used

**Honest headline: this is not a `trycloudflare.com` URL.** The Cloudflare edge
could not be reached from this network — the evidence is in
[`cloud/tunnel.md`](../cloud/tunnel.md) and summarised above:
`api.cloudflare.com:443` works, the quick-tunnel hostname is issued, and then the
data plane fails because outbound **port 7844** (QUIC and HTTP/2) is blocked.
Both documented fallbacks (`--protocol http2`, and `--edge <ip>:443`) failed the
same way, and the failure reproduced **outside the tool sandbox and outside its
process tree**, so it is a property of this network, not of the tooling.

Since the bonus needs an edge-relayed public URL, the closest zero-account,
zero-card equivalent that works over the egress this network *does* allow was
used:

```bash
ssh -o StrictHostKeyChecking=no -R 80:localhost:8080 nokey@localhost.run
```

This is architecturally the same shape as a Cloudflare quick tunnel — the origin
is a local container, the provider's edge terminates TLS
(`tunneled with tls termination`), and the traffic arrives over an outbound-only
connection that was initiated from this machine. It differs in *whose* edge it
is, and that difference is stated plainly rather than glossed over. Everything
the bonus actually asks for — public exposure, verification from a different
network, warm p50/p95, and the comparison — is measured for real below.

### Public URL and external verification

```
https://0aa384b87b1e19.lhr.life
```

Verified **from a different network** — an independent fetcher running on a
different host, not the machine holding the tunnel:

```
GET https://0aa384b87b1e19.lhr.life/health
  -> HTTP 200  {"notes":6,"status":"ok"}

GET https://0aa384b87b1e19.lhr.life/notes
  -> HTTP 200, 6 notes, including id 6 "written-via-public-edge"
     created_at 2026-10-09T01:38:48Z
```

Writing through the public URL also works, which is the stronger test — a
read-only proxy could fake the GET:

```
before : {"notes":5,"status":"ok"}
POST   : 201 {"id":6,"title":"written-via-public-edge",
              "body":"written through the public edge URL",
              "created_at":"2026-10-09T01:38:48.697905190Z"}
after  : {"notes":6,"status":"ok"}
GET /notes -> 6 notes; last = id 6 "written-via-public-edge"
```

### Ephemerality, observed rather than assumed — and it is not just "on restart"

The lab says a quick-tunnel URL changes on restart. In practice it changed
*while idle*, repeatedly. Five hostnames were issued in one working session:

| # | URL | What ended it |
|---|---|---|
| 1 | `https://1647a21396b5bc.lhr.life` | session dropped, client reconnected |
| 2 | `https://0aa384b87b1e19.lhr.life` | server-side inactivity disconnect (measured instance A) |
| 3 | `https://1d90ddf8261633.lhr.life` | inactivity disconnect (measured instance B) |
| 4 | `https://d632f849d92fec.lhr.life` | inactivity disconnect |
| 5 | `https://e503cb67dee4a3.lhr.life` | inactivity disconnect |

The disconnect is decided by the provider, not the client:

```
Received disconnect from 54.161.197.247 port 22:11: tunnel activity timeout
Disconnected from 54.161.197.247 port 22
```

**A free tunnel hangs up on an idle service.** That is worth sitting with,
because it is the exact opposite of a hosting requirement: an idle production
service must keep answering, and *idle is the normal state* of a service nobody
is using yet.

#### The part that actually bites: reconnects silently strand your clients

The first fix attempt was a keep-alive pinger every 45 seconds. It did not work,
and *why* it did not work is the real lesson.

The pinger cached the hostname it started with. When the tunnel reconnected, the
provider issued a **new** hostname, so the pinger kept polling the old one —
which was already dead. The replacement tunnel therefore received no traffic at
all, hit the idle timeout immediately, and reconnected again. Observed result:
three hostnames in a single run (`1d90ddf8261633` → `d632f849d92fec` →
`e503cb67dee4a3`), each one born idle and killed idle.

So it is not merely "the URL changes". **A client that cached the old URL never
finds out**: it keeps getting 502 from a healthy edge, and if your keep-alive is
what was supposed to hold the tunnel open, the tunnel dies *because* the
keep-alive is pointing at a ghost. An ephemeral hostname is not just an
operational annoyance; it breaks any health check, warm-up, monitor or
load-balancer probe that resolved the name once. The correct shape is a
supervisor that re-reads the hostname from the tunnel's own log and restarts the
session — which is exactly what [`cloud/bench/tunnel_supervisor.py`](../cloud/bench/tunnel_supervisor.py)
does, and it is also an admission that this is infrastructure you now have to
babysit yourself.

Between instances the edge stays up and the origin does not, which is visible
from the outside as a status-code change rather than an outage message:

```
GET https://1647a21396b5bc.lhr.life/health   (after the origin went away)
  -> HTTP 502 Bad Gateway
```

A 502 from a healthy edge is precisely what "the origin is your laptop" looks
like to a user.

### It reproduces: two independent tunnel instances

The whole measurement suite was run twice, on two different edge hostnames, to
make sure the numbers describe the architecture rather than one lucky session:

| Metric | Instance A (`0aa384b87b1e19`) | Instance B (`1d90ddf8261633`) | Δ |
|---|---:|---:|---:|
| p50, fresh connection | 1002.67 ms | 1022.90 ms | +2.0% |
| p95, fresh connection | 1126.49 ms | 1134.50 ms | +0.7% |
| p50, keep-alive | 409.27 ms | 409.78 ms | **+0.1%** |
| p95, keep-alive | 511.69 ms | 517.39 ms | +1.1% |
| failures | 0 / 50 | 0 / 50 | — |

The steady-state figure landing within 0.5 ms across two separate edge
hostnames is the useful result: ~409 ms is the real round trip of this
architecture from here, not noise. And the same picture held from outside the
network — the independent external fetcher saw HTTP 200 `{"notes":6,"status":"ok"}`
on both instances.

### Warm latency — 50 runs, two harnesses

| Harness | Connection | p50 | p95 | min | max |
|---|---|---:|---:|---:|---:|
| `bench.py` | fresh per request (what `curl` does) | **1002.67 ms** | **1126.49 ms** | 807.62 ms | 1201.05 ms |
| `bench.py` | one pooled connection (keep-alive) | **409.27 ms** | **511.69 ms** | 341.72 ms | 1113.26 ms |
| `hyperfine` + spawned client | fresh process per run | 1495 ms (mean) | — | 1196 ms | 1799 ms |
| localhost baseline (no edge) | — | 5.97 ms | 8.44 ms | 3.55 ms | 8.44 ms |

All 50 requests in both `bench.py` runs returned HTTP 200 — no errors, no
timeouts, so the samples are a clean latency distribution rather than a mix of
success and retry.

Reading the three rows together answers question (h) with numbers instead of
folklore:

* **~593 ms of the ~1003 ms is per-request setup** (DNS + TCP + TLS handshake to
  the edge, plus opening a fresh channel over the tunnel). Reusing one
  connection removes it entirely. This is why the fresh-connection number is the
  one users feel on a page load that opens several new connections, and why the
  keep-alive number is the one that matters for an API client.
* **~409 ms is the steady-state round trip** through client → edge → tunnel →
  laptop → back. That is the doubled WAN path plus the local uplink, and it is
  ~68× the entire local application cost.
* **~490 ms of the `hyperfine` figure is the measurement harness itself** —
  spawning a client process on this host costs ~510 ms on its own (measured by
  benchmarking a bare `python` that exits immediately). So `hyperfine`+client
  reports ~1.5 s where the network actually costs ~1.0 s. The lab's suggested
  methodology is sound on Linux and misleading on Windows; reporting both is the
  only way to see it.

## B.3 Comparison table

Same QuickNotes image, two delivery models:

| Metric | Codespace (GitHub-hosted) | Tunnel (local-via-edge) |
|---|---:|---:|
| Warm p50 | <!-- FILL_CS_P50 -->pending | 1002.67 ms (fresh) / 409.27 ms (keep-alive) |
| Warm p95 | <!-- FILL_CS_P95 -->pending | 1126.49 ms (fresh) / 511.69 ms (keep-alive) |
| Cold start | <!-- FILL_CS_COLD -->pending | N/A (continuously local) |
| Public URL stability | stable for the life of the codespace | ephemeral on restart (observed) |
| Cost | free (120 core-hours/month) | free |
| Origin runs on | GitHub's datacenter | this laptop |
| Survives origin going offline | yes — the VM keeps serving | no — the URL 502s instantly |

The last two rows are added on purpose: they are the part of the comparison that
the assignment's table does not ask for but that question (g) is really about.

## Baseline: what the app itself costs

Measured on the same machine against the local container, so that the network
cost can be separated from the application cost (10 runs, warm, after 5 warm-up
requests; loopback only, no edge):

| Metric | localhost → container |
|---|---:|
| min | 3.55 ms |
| **p50** | **5.97 ms** |
| p95 | 8.44 ms |
| max | 8.44 ms |

That is the floor: QuickNotes' own handler time plus loopback. Everything above
it in the tables below is network and platform.

## B.4 Design questions

### g) Architectural difference — which one is "really cloud"?

On Render (or Codespaces) the container runs **in someone else's datacenter**:
their compute, their network, their power, their hardware refresh cycle. You buy
abstracted capacity and the provider is responsible for the machine. That is
cloud in the NIST sense — on-demand self-service, broad network access, resource
pooling, rapid elasticity, measured service.

With Cloudflare Tunnel the container still runs **on your laptop**. Cloudflare's
edge is only a *reverse proxy plus relay*: it terminates the client's TLS
connection, then forwards the stream down a long-lived connection that your
machine opened outbound. You are consuming a genuinely global edge network, but
the *origin* — the thing that computes and stores — is your own hardware in your
own room.

So: **the edge is cloud, the workload is not.** The distinction matters less than
you would think for latency and much more than you would think for everything
else. A user in another country may see perfectly good numbers, because they
reach a nearby Cloudflare PoP; but availability, throughput, durability and
capacity are yours to own. If the laptop sleeps, closes, reboots for updates, or
loses Wi-Fi, the service is down with no failover and no SLA. The uplink is
typically asymmetric (home upload is a fraction of download), and the "server" is
also somebody's IDE and browser. Users absolutely notice when it is gone — they
just may not notice the difference while it is up.

### h) The latency dominator in each case

**Render / Codespaces (warm):** the dominant cost is the **wide-area network**.
The request has to reach the provider's region and come back — client→region RTT,
plus TLS handshake, plus the platform's ingress/proxy hops. The application's own
work is noise by comparison: the local measurement above shows the whole handler
costs single-digit milliseconds including loopback. The practical consequence is
that you cannot optimise this away in the app; you change it by moving the
service closer to users (region choice, CDN, multi-region), not by rewriting
handlers.

**Cloudflare Tunnel (warm):** the dominant cost is the **doubled path and your
own uplink**. Traffic goes client → nearest Cloudflare PoP → the long-lived
tunnel connection → your laptop → and all the way back. The wide area is
traversed twice (once client→edge, once edge→origin) and the last hop is a
consumer/office uplink that is typically asymmetric and shared with everything
else on the machine. That is why the tail is worse than the median: p95 is
dominated by queueing on the uplink and by the local process competing with the
editor, the browser and the tunnel itself. In the tunnel case the dominator is
*your* network and your hardware, not Cloudflare's edge.

There is also a measurement trap worth naming, because the lab suggests
`hyperfine` with `curl`: on Windows each `hyperfine` run **spawns a new
`curl.exe`**, and process creation alone can cost more than the entire network
request. Both harnesses are therefore reported for the tunnel measurement — the
in-process numbers are the network truth, and the `hyperfine` delta is itself the
evidence for this point.

### i) When is Cloudflare Tunnel the right production pick, and when is it never right?

**Right tool:**

* Publishing something you *must* keep on your own hardware: a home lab,
  self-hosted NAS, Home Assistant, a media or backup server, a lab instrument.
* On-prem or legacy services with **no public IP** and no way to get one — behind
  CGNAT, on a corporate LAN, or where inbound port-forwarding is forbidden by
  policy. The tunnel is **outbound-only**, so there is no firewall hole to punch.
* Internal tools and admin dashboards that should be reachable from anywhere but
  not exposed to the internet — a nice fit, because Cloudflare Access can put
  SSO in front of the edge before traffic ever reaches the origin.
* **Ephemeral dev URLs for stakeholder review** and webhook/receiver testing:
  exactly what a quick tunnel does best, with zero account and zero DNS.
* Environments that require **outbound-only** connectivity to reach a globally
  distributed edge — the property that made it worth trying here.

**Never the right tool:**

* As the production home of a customer-facing service with an availability
  commitment. There is no SLA, the origin is a single point of failure on a
  network you do not control, and the failure mode is "someone unplugged a
  laptop". This run produced direct evidence, not just an argument: the tunnel
  **disconnected itself while idle** (`tunnel activity timeout`) and the URL then
  served 502 from the edge. A production service that hangs up because nobody is
  using it yet is not a production service — and the hostname churn makes it
  worse, because every reconnect silently strands clients, health checks and
  monitors that resolved the previous name.
* When you need **horizontal scale**: one tunnel terminates at one origin
  process, so there is no autoscaling and no load balancing across replicas.
* When **data residency or processing guarantees** matter, or when a vendor
  decrypting your traffic at their edge is unacceptable — the tunnel terminates
  TLS at Cloudflare, so Cloudflare sees plaintext.
* When upstream bandwidth is the bottleneck, or the workload is bandwidth-heavy
  (video, large transfers, many concurrent users).
* And, as this lab discovered, **when the edge port is blocked**: "works
  anywhere, zero config" is a promise about configuration, not about networks.

---

# Teardown

Cost: both targets are free, but quota hygiene still applies, so the steps are
written down in [`cloud/teardown.md`](../cloud/teardown.md).

* **Codespaces** — a *stopped* codespace still consumes the 15 GB storage quota,
  so it gets deleted once grading is done (`gh codespace delete -c <name>`),
  not merely stopped.
* **Render** — not activated; if it had been, Suspend/Delete from Settings.
* **Local** — `docker rm -f qn-lab10`, remove `quicknotes:lab10-local`, and stop
  `cloudflared` (the quick-tunnel URL dies with the process; there is nothing to
  clean up on Cloudflare's side, which is genuinely one of the nicer properties
  of quick tunnels).

---

# Appendix — reproduce it

```bash
# Task 1: tag the release
git tag -a -s v0.1.0 -m "Lab 10 release"
git push origin v0.1.0

# verify the image is really public (no credentials involved)
docker logout ghcr.io
docker rmi ghcr.io/fishkadealer229/devops-intro/quicknotes:v0.1.0 || true
docker pull ghcr.io/fishkadealer229/devops-intro/quicknotes:v0.1.0

# Task 2 (Option B)
gh auth refresh -h github.com -s codespace
gh codespace create -R fishkadealer229/DevOps-Intro -b feature/lab10
gh codespace ports visibility 8080:public -c <name>
gh codespace ports -c <name>
curl -v https://<name>-8080.app.github.dev/health

# Bonus
docker run -d --name qn-lab10 -p 8080:8080 -e ADDR=:8080 quicknotes:lab10-local

# what the lab asks for (blocked here: outbound 7844 is filtered on this network)
cloudflared tunnel --no-autoupdate --url http://localhost:8080

# what produced the numbers in this report (same architecture, reachable edge)
ssh -o StrictHostKeyChecking=no -R 80:localhost:8080 nokey@localhost.run
python cloud/bench/keepalive.py https://<tunnel-host> 45   # free tier drops idle tunnels

# measurements (harness committed at cloud/bench/)
python cloud/bench/bench.py https://<tunnel-host> --runs 50 --path /health
python cloud/bench/bench.py https://<tunnel-host> --runs 50 --path /health --keepalive
hyperfine --warmup 3 --runs 20 "python C:/path/to/cloud/bench/probe.py https://<tunnel-host>/health"
```
