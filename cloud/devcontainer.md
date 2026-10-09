# Task 2, Option B — GitHub Codespaces

Artifact: [`.devcontainer/devcontainer.json`](../.devcontainer/devcontainer.json)
(run `cat .devcontainer/devcontainer.json` for the full file — it is reproduced
below as well).

## What it does

A codespace is created from `mcr.microsoft.com/devcontainers/base:ubuntu-24.04`
with the **docker-in-docker** feature, and on every start it runs the image that
Task 1 published:

```
ghcr.io/fishkadealer229/devops-intro/quicknotes:v0.1.0
```

Port `8080` is forwarded, and Codespaces maps it to
`https://<codespace-name>-8080.app.github.dev`.

### Why not point `image` straight at the QuickNotes image?

That was the first instinct, and it does not work. The QuickNotes image is
**distroless**: no shell, no package manager, no Node — nothing for the VS Code
server to run inside it. A dev container needs a userland. So the codespace
provides a normal Ubuntu userland with Docker, and the distroless image is
*run as a workload* inside it — which is also closer to how it runs on Render.

### Why `docker start` instead of a fresh `docker run` on each start

The `postStartCommand` is:

```bash
docker start quicknotes 2>/dev/null || docker run -d --name quicknotes \
  -p 8080:8080 -e ADDR=:8080 \
  -e DATA_PATH=/data/notes.json -e SEED_PATH=/app/seed.json \
  ghcr.io/fishkadealer229/devops-intro/quicknotes:v0.1.0
```

Reusing the existing container means its writable layer survives a codespace
stop/start. That is deliberate: it makes Task 2.2 step 5 measurable, and it is
the honest difference from Render, whose filesystem is wiped on every spin-down.
It also makes the command idempotent — on the very first start there is no
container to start, so the `||` branch creates it.

## Commands used

```bash
# one-time: the codespace scope is not in the default gh token
gh auth refresh -h github.com -s codespace

# create the codespace for this repo/branch
gh codespace create -R fishkadealer229/DevOps-Intro -b feature/lab10

# list them, with state
gh codespace list

# port 8080 must be public — this CANNOT be set from devcontainer.json
gh codespace ports visibility 8080:public -c <codespace-name>

# confirm it
gh codespace ports -c <codespace-name>

# open a shell inside (also what wakes a stopped codespace)
gh codespace ssh -c <codespace-name>

# teardown
gh codespace stop   -c <codespace-name>
gh codespace delete -c <codespace-name>
```

Web equivalent for port visibility: the codespace → **Ports** tab → right-click
the `8080` row → **Port Visibility** → **Public**.

## Port visibility gotcha

Port visibility is **per codespace and per lifetime**, not part of the repo
config. After every codespace restart (or after creating a new one) the URL
redirects to a GitHub login page until `8080` is made public again. If the URL
shows "Sign in to GitHub", the port is still private — that is the diagnostic,
not a broken app.

Output captured in this run:

```
$ gh codespace ports -c <codespace-name>
# (filled in from the actual run — see submissions/lab10.md)
```
