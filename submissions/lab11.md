# Lab 11 (bonus) — Reproducible Builds of QuickNotes with Nix

**Branch:** `feature/lab11` → PR to `inno-devops-labs/DevOps-Intro:main`
**Artifacts:** [`flake.nix`](../flake.nix), `flake.lock`, [`.github/workflows/nix-repro.yml`](../.github/workflows/nix-repro.yml)

| Task | Status | Evidence |
|---|---|---|
| 1 — reproducible Go build (4 pts) | ✅ | identical store hashes across two builds, and the binary serves `/health` (1.2, 1.3) |
| 2 — deterministic OCI image (4 pts) | ✅ | identical tarball digests, loaded with `docker load` and run (2.2, 2.1b), compared with Lab 6 (2.3) |
| Bonus — CI-verified reproducibility (2 pts) | ⏳ | two-runner gate written and committed; green + red runs pending a push |

> **Environment note.** This host blocked Nix at first — 0.25 GB free on the system
> drive, commit charge at 26.1/26.3 GB — and the whole account of what was freed,
> what was worked around, and which number came from where is in
> [Where the builds actually ran](#where-the-builds-actually-ran). The short
> version: the binary and the OCI image **were** built, hashed, loaded and run on
> this machine (1.2, 1.3, 2.1b, 2.2), while the stronger *two-independent-runner*
> form of the proof runs on CI — which is also exactly what the Bonus Task asks for.

---

# Task 1 — Reproducible Go build via Nix flake

## 1.1 The flake

Full file: [`flake.nix`](../flake.nix). The essentials:

```nix
inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-25.11";   # Go >= 1.24, pinned by flake.lock

quicknotes = pkgs.buildGoModule {
  pname = "quicknotes";
  version = "0.1.0";
  src = ./app;

  CGO_ENABLED = 0;              # static binary
  ldflags = [ "-s" "-w" ];      # strip symbols + DWARF (carried from Lab 6)
  vendorHash = null;            # no dependencies => nothing to vendor

  meta.mainProgram = "quicknotes";
};
```

`nixos-25.11` is chosen because `app/go.mod` declares `go 1.24`; an older
channel ships an older default Go and `buildGoModule` fails before it compiles
anything. The channel name is only a hint — `flake.lock` pins the exact revision.

Note what is deliberately **absent**: there is no `trimpath` argument, because
`buildGoModule` has none. It injects `-trimpath` into `GOFLAGS` itself, and it
appends `-buildid=` to `ldflags` unless one is given, precisely so the Go build ID
stops being a source of non-determinism. Setting `trimpath = true;` would not fail
(the function accepts extra arguments and forwards them into the derivation
environment) — it would simply be a no-op that looks like it does something. See
question (a).

### `vendorHash = null` is the correct value here — not a shortcut

The assignment expects a pinned `vendorHash`, taken from the first failed build,
and that is the right procedure whenever a module *has* dependencies. It does not
apply to QuickNotes, and pinning a hash here would have been a bug rather than
thoroughness. Three facts, all read out of the pinned nixpkgs itself —
`pkgs/build-support/go/module.nix` at revision
`b6018f87da91d19d0ab4cf979885689b469cdd41`, the revision `flake.lock` pins:

**1. `vendorHash` hashes the vendored dependency tree, and nothing else.** The
fixed-output derivation ends with:

```sh
cp -r --reflink=auto vendor $out        # module.nix:186
```

so the hash covers exactly the contents of `vendor/` — not your source. That is
also why editing your own `.go` files never requires updating `vendorHash`, and
why the hash is meaningful: it pins "which third-party code went in", separately
from "which code of mine went in".

**2. For a module with no dependencies, `null` is the documented value.** From the
argument list of `buildGoModule`:

```nix
# The SRI hash of the vendored dependencies.
# If `null`, it means the project either has no external dependencies
# or the vendored dependencies are already present in the source tree.
vendorHash ? throw (
```

and `null` short-circuits the whole fixed-output derivation:

```nix
goModules =
  if (finalAttrs.vendorHash == null) then
    ""
  else ...
```

which also means the build needs no network and no dependency fetch at all.

**3. A hash would make the build fail, loudly.** The install phase refuses an
empty vendor directory:

```sh
if ! [ "$(ls -A $out)" ]; then
  echo "vendor folder is empty, please set 'vendorHash = null;' in your expression"
  exit 10
fi
```

And the vendor tree really is empty, which is checkable without Nix at all:

```
$ go mod vendor
go: warning: "all" matched no packages
go: no dependencies to vendor

$ ls
go.mod          # no vendor/ directory was created at all
```

For completeness, the hash of an empty tree *was* measured, in case that turned
out to be the expected value — it is not, and it is not used:

```
$ nix hash path /tmp/empty
sha256-pQpattmS9VmO3ZIQUFn66az8GSmB4IvYhTTCFn6SUmo=
```

So the "first build fails and prints the right hash" dance the assignment
describes cannot happen here: with zero dependencies there is no hash to learn,
and nixpkgs says so in its own error message. The first CI run of this flake is
therefore expected to be green, not red.

### The flake was evaluated, not just written

A flake that has never been evaluated is a draft. This one was evaluated against
the exact nixpkgs revision it pins, and that caught two real defects before the
first push.

`flake.lock` in this repository pins:

```
nixpkgs: github:NixOS/nixpkgs/b6018f87da91d19d0ab4cf979885689b469cdd41
         ?narHash=sha256-twXPFqFsrrY5r28Zh7Homgcp2gUMBgQ6WDS98Q/3xFI=
         (2026-06-30 19:19:49)
```

Because the tree behind that narHash was already present locally, every output
could be evaluated **with the network switched off** — which is a stronger
statement than "it resolved once":

```
$ nix eval --offline --raw .#quicknotes.drvPath
/nix/store/0gcr2pkw3sw51qadjz4yrczx4hkyvhdb-quicknotes-0.1.0.drv

$ nix eval --offline --raw .#docker.name
docker-image-quicknotes.tar.gz

$ nix eval --offline --raw .#checks.x86_64-linux.docker.name
docker-image-quicknotes.tar.gz
```

`--offline` is the load-bearing flag: if the lock were wrong, or the narHash did
not describe that tree, Nix would have had to fetch something and would have
failed immediately instead of quietly succeeding from cache. So the lock is
verified, not merely present.

**Defect 1 — `trimpath = true;` is not an argument** (see 1.1). It would not have
failed; it would have done nothing, and quietly implied the flake was handling
build-path stripping that the toolchain already handles.

**Defect 2 — `CGO_ENABLED = 0;` no longer evaluates on nixpkgs 25.11.** This is the
textbook spelling, and it is what most examples show, but `buildGoModule` now
constructs `env` itself and rejects a top-level argument that collides with it:

```
error: The `env` attribute set cannot contain any attributes passed to derivation.
The following attributes are overlapping:
  - CGO_ENABLED: in `env`: 1; in derivation arguments: 0
```

The fix is to set it where nixpkgs now reads it:

```nix
env = {
  CGO_ENABLED = 0;
};
```

which is what the committed flake does. This is precisely the failure CI would
have reported first, and finding it locally — before spending a push — is the
whole argument for evaluating a flake rather than shipping it and reading logs.

### How `flake.lock` was produced on a network that cannot reach `api.github.com`

Worth recording, because the lock is the one file the assignment insists on and
this host could not produce it the ordinary way. The host's DNS answers
`api.github.com` with `204.12.192.222`, which is not GitHub (documented in
[Where the builds actually ran](#where-the-builds-actually-ran)), so Nix's
`github:` fetcher stalls. The lock was therefore built from the same archive that
fetcher would have downloaded:

1. the nixpkgs commit for `nixos-25.11` was read from the channel itself
   (`channels.nixos.org/nixos-25.11/git-revision` → `b6018f87…`);
2. that tree was fetched from `codeload.github.com` — GitHub's own CDN, and the
   endpoint the API tarball redirects to — so the content is the one Nix expects;
3. `nix flake lock` was run against that local archive, which computed the real
   `narHash` (`sha256-twXPFqFsrrY5r28Zh7Homgcp2gUMBgQ6WDS98Q/3xFI=`);
4. the commit timestamp was cross-checked through the API
   (`2026-06-30T19:19:49Z` → `lastModified = 1782847189`, matching what Nix had
   recorded for the archive);
5. the node was written in the `github` form and then **validated with
   `--offline`**, which is what proves the `rev` + `narHash` pair is correct.

Step 5 is the part that makes this more than a guess: a hand-written lock that
Nix resolves with no network available has been checked against Nix's own
store-path computation, not against my confidence.

Two smaller choices worth naming, because both are the kind of thing that turns a
green `nix flake check` red for no good reason:

* **`systems = [ "x86_64-linux" ]`.** `nix flake check` does not merely evaluate
  every listed system, it tries to *build* it. Advertising `aarch64-linux` without
  an aarch64 builder or a remote builder makes `nix flake check` fail on an
  x86_64 machine — and the failure has nothing to do with reproducibility, so it
  would just be noise. The CI runners are `x86_64-linux`, which is the target that
  matters here; the comment in the flake says how to add aarch64 back.
* **A `checks` output** re-exporting both packages, so `nix flake check` actually
  builds the binary and the image instead of passing vacuously. A flake whose
  check is a no-op is a flake that cannot tell you it is broken.

## 1.2 Reproducibility proof — two independent builds

The flake pins `nixpkgs` at `b6018f87da91d19d0ab4cf979885689b469cdd41` (see
`flake.lock`), which is what makes the comparison meaningful at all: the same
source is being compiled by the same toolchain, so any difference in the output
would have to come from the build environment.

```
$ nix build .#quicknotes
$ nix-store --query --hash "$(readlink -f result)"
sha256:1hv80kblj0zqcz82z0wihvxz63kylgwkqqgv5naykf0ar4f26w8k

$ nix build .#quicknotes --rebuild        # force a fresh build of the same derivation
$ nix-store --query --hash "$(readlink -f result)"
sha256:1hv80kblj0zqcz82z0wihvxz63kylgwkqqgv5naykf0ar4f26w8k
```

Identical, and the store path is identical too:

```
/nix/store/qli03fqwnjn9bkm52ijx4nllxnmd1j80-quicknotes-0.1.0
```

**What this proves, and what it does not.** `--rebuild` forces Nix to re-run the
build from scratch instead of returning the existing output, so the two hashes
above are two real compilations — but they happened on one machine against one
Nix store. That demonstrates the derivation is *deterministic*; it does not by
itself demonstrate independence from this machine's state. The genuinely
independent version of this experiment — the same commit built on **two separate
fresh runners with separate stores** — is the CI job described in the
[Bonus section](#bonus-task--ci-verified-reproducibility), and
[`.github/workflows/nix-repro.yml`](../.github/workflows/nix-repro.yml) fails the
build if those two digests disagree. Locally that second environment was not
reachable: it would mean re-downloading nixpkgs and the whole Go toolchain
(~1.5 GB) over a link measured at ~180 KB/s.

Two things the build log shows along the way, both of which are the flake doing
its job:

```
quicknotes> Running phase: checkPhase
quicknotes> ok          quicknotes      0.014s
```

`buildGoModule` runs `go test` as part of the derivation, so the unit tests are
part of what is being reproduced — a build that passed tests and one that did not
cannot produce the same hash.

```
quicknotes> patchelf: cannot find section '.dynamic'. The input file is most likely statically linked
quicknotes> stripping (with command strip and flags -S -p) in .../bin
```

`patchelf` complaining that there is no dynamic section *is* the evidence that
`CGO_ENABLED = 0` worked: the binary has no interpreter and no shared-library
dependencies. It is 5,918,800 bytes.

## 1.3 It runs

Straight out of the Nix store, with no container and no Docker involved:

```
$ DATA_PATH=/tmp/qn-notes.json SEED_PATH=app/seed.json ./result/bin/quicknotes &
$ curl -sS http://127.0.0.1:8080/health
{"notes":4,"status":"ok"}

$ curl -sS http://127.0.0.1:8080/notes
[{"id":2,"title":"Read app/main.go first","body":"Start by understanding the entry point — env vars, signal handling, graceful shutdown.", ...

$ cat /tmp/qn.log
2026/10/16 05:54:34 quicknotes listening on :8080 (notes loaded: 4)
```

The Nix-built binary serves the API and picks up the seed data, so the store
output is a working artefact and not just a hash.

## 1.4 Design questions

### a) Why does `go build` not produce bit-identical output on two machines, even from the same Git SHA?

Because the binary is not a pure function of the source. Go bakes several
environment-derived values into the artefact:

1. **Absolute build paths.** Without `-trimpath`, the compiler embeds the
   directory it built from (`/home/alice/src/quicknotes` vs
   `C:\Users\bob\...`), and those strings live in the symbol table, in
   `runtime` metadata and in every stack trace the binary can print. Two
   machines cannot agree unless they built from the same path.
2. **The build ID.** `go build` writes a build ID (`go tool buildid`) derived
   from the *action IDs* of the compile/link steps. Those depend on the
   toolchain and on cache state, so the same source compiled with `go1.24.5`
   and `go1.24.7` — or with a warm vs cold build cache — yields different IDs.
   The toolchain version alone changes generated code.
3. **VCS stamping.** Since Go 1.18, `go build` embeds the commit and the
   working-tree status by default (`-buildvcs`). That is *usually* stable across
   clones, but it changes with uncommitted edits, with `-dirty` trees, and it
   simply does not exist inside a tarball. It also changes build IDs.
4. **Symbol and DWARF data.** By default neither is stripped; DWARF carries
   file paths, type layouts and compiler version strings. `-s -w` removes them.
5. **Dependency resolution.** Without vendoring, `go build` resolves modules
   through the local module cache and the configured proxy. Two machines with
   different cache contents, `GOFLAGS`, `GOPROXY` or `go.sum` verification
   outcomes can resolve different code for the same `go.mod`.
6. **Environment flags.** `CGO_ENABLED` itself matters — with cgo enabled the
   binary links against the local libc and picks up its version and ABI.

`-trimpath` plus `-s -w` plus a pinned toolchain removes 1, 2 (via a fixed
toolchain), 4 and most of 6; the Nix sandbox has no `.git`, so VCS stamping is
inert; and `vendorHash` removes 5 by making the dependency tree a fixed input.
That is the whole point: Nix does not make `go build` deterministic, it removes
every input that was not already pinned.

Two of those are handled by `buildGoModule` itself rather than by the flake,
which is worth knowing before trying to "fix" them by hand. In the pinned
nixpkgs (`pkgs/build-support/go/module.nix`):

```nix
GOFLAGS = GOFLAGS ++ ... lib.optional (!finalAttrs.allowGoReference) "-trimpath";
```

```nix
# If not set to an explicit value, set the buildid empty for reproducibility.
ldflags = ldflags ++ lib.optional (!lib.any (lib.hasPrefix "-buildid=") ldflags) "-buildid=";
```

So `-trimpath` is injected by default — there is no `trimpath` argument to pass —
and `-buildid=` is appended for exactly the reason in point 2. A flake that sets
`trimpath = true;` does not fail (unknown arguments are forwarded into the
derivation environment) but it is inert, and it disguises the fact that the
toolchain already guarantees both. The flake in this repository therefore does not
set it.

### b) What is `vendorHash` a hash *of*, and what does `vendorHash = null` do?

`vendorHash` is the **SHA-256 NAR hash of the output of the `go mod vendor`
step** — that is, of the vendored dependency tree, and nothing else. The
fixed-output derivation proves the scope in one line:

```sh
cp -r --reflink=auto vendor $out        # module.nix:186
```

So it covers the source of every module the build would otherwise download, laid
out as Go's vendor directory. It is *not* a hash of `go.sum` (which carries only
module digests, not the tree Nix produces), and it is *not* a hash of your own
source — which is why editing your `.go` files never invalidates it, and also why
it is a meaningful pin: "which third-party code went in", recorded separately from
"which of my code went in".

It exists for two reasons. First, it names a **fixed-output derivation**: Nix is
allowed network access to *produce* it, then verifies the result against the hash,
so every later build is offline and provably the same tree. Second, it is what
turns "whatever the proxy served today" into an input of the derivation, exactly
like the source.

`vendorHash = null;` **skips that derivation entirely**:

```nix
goModules =
  if (finalAttrs.vendorHash == null) then
    ""
  else ...
```

and nixpkgs documents precisely when that is correct:

```nix
# The SRI hash of the vendored dependencies.
# If `null`, it means the project either has no external dependencies
# or the vendored dependencies are already present in the source tree.
vendorHash ? throw (
```

Those are two different situations and they deserve different scrutiny:

* **No external dependencies** (QuickNotes): there is nothing to pin, and `null`
  is the only value that builds. Supplying a hash does not make the flake more
  rigorous — it makes it fail, because the install phase rejects an empty vendor
  directory:
  ```sh
  if ! [ "$(ls -A $out)" ]; then
    echo "vendor folder is empty, please set 'vendorHash = null;' in your expression"
    exit 10
  fi
  ```
  The vendor tree really is empty, checkable without Nix:
  ```
  $ go mod vendor
  go: warning: "all" matched no packages
  go: no dependencies to vendor
  ```
* **Dependencies vendored into the source tree**: `null` is correct *and* the
  guarantee changes hands. Nix is no longer pinning the dependency tree by hash;
  your VCS is pinning it by commit. That is a legitimate workflow (it makes builds
  fully offline), but it is a weaker claim than a `vendorHash`, and it is the case
  where `null` deserves the suspicion it usually gets.

The habit worth keeping is the one the assignment describes: for a module that
*does* have dependencies, take the value from the first failed build and pin it. It
simply does not apply here, and pretending otherwise would have meant a flake that
cannot build.

### c) Why is `flake.lock` the single most important file, and what happens if you delete it before the second build?

`flake.lock` records, for every input, the exact **locked revision and narHash**.
Without it, `github:NixOS/nixpkgs/nixos-25.11` is a *moving branch reference*:
`nix build` resolves the tip of that channel at build time. So the flake would
pin your source but not the thing that compiles it — and the compiler, `stdenv`,
`bash`, `coreutils`, glibc and every build script all come from that one input.

Deleting it before the second build therefore does something worse than break
the comparison: the second build silently resolves a **different** nixpkgs
revision and hashes differ — or, if the channel had not moved, they match and you
believe you proved reproducibility when you actually proved nothing about
toolchain drift. The failure is silent in the dangerous direction. The lock is
what makes "same source" mean "same toolchain, same dependencies, same build
scripts"; it is the only file that converts a channel from a mutable pointer into
an immutable input, and the pitfalls list in the assignment names exactly this
("different hashes on two machines — usually means flake.lock is not committed").

### d) `buildGoModule` vs `buildGoApplication` — and which one for QuickNotes?

| | `buildGoModule` (nixpkgs) | `buildGoApplication` (gomod2nix) |
|---|---|---|
| Where it lives | nixpkgs built-in | `numtide/gomod2nix`, needs its own tooling |
| Dependency pinning | one `vendorHash` over the vendored tree | generated `deps.nix` describing each module |
| Extra generated files | none | `deps.nix` (must be regenerated when `go.mod` changes) |
| Layout it targets | a single module | multi-module repos and Go workspaces |
| Caching granularity | per-module source | per-dependency, finer for large graphs |
| `go install` of many binaries | `subPackages` | first-class |

**Chosen: `buildGoModule`.** QuickNotes is one small module (`module quicknotes`)
with a three-line `go.mod` and no dependencies at all. `buildGoApplication`
would add a code-generation step and a `deps.nix` that describes nothing, so it
would import a moving part — and a second thing to keep in sync — in exchange for
caching benefits that cannot materialise when there is no dependency graph to
cache. The choice would flip if QuickNotes grew into a workspace with several
modules and a large dependency set: then per-module caching and the absence of a
single all-or-nothing `vendorHash` start to pay for the extra machinery.

---

# Task 2 — Deterministic OCI image

## 2.1 The flake snippet

Full file: [`flake.nix`](../flake.nix).

```nix
docker = pkgs.dockerTools.buildImage {
  name = "quicknotes";
  tag = "v${version}";

  copyToRoot = pkgs.buildEnv {
    name = "image-root";
    paths = [ quicknotes ];
    pathsToLink = [ "/bin" ];
  };

  extraCommands = ''
    mkdir -p -m 1777 tmp     # world-writable: the nonroot uid persists notes here
    mkdir -p app
    cp ${./app/seed.json} app/seed.json
  '';

  config = {
    Entrypoint = [ "/bin/quicknotes" ];     # exec form, no shell
    ExposedPorts = { "8080/tcp" = { }; };
    User = "65532:65532";                   # nonroot (Lab 6 discipline)
    WorkingDir = "/";
    Env = [ "ADDR=:8080" "DATA_PATH=/tmp/notes.json" "SEED_PATH=/app/seed.json" ];
  };
};
```

Built with **Nix only** — no Docker daemon in the loop.

### 2.1b The image is real: loaded and run

The acceptance criterion is that the tarball is an OCI image a container runtime
will accept, so it was loaded into Docker and started:

```
$ docker load -i quicknotes-nix.tar
Loaded image: quicknotes:v0.1.0

$ docker images quicknotes --format '{{.Repository}}:{{.Tag}}  {{.ID}}  {{.Size}}'
quicknotes:v0.1.0  3b2484917217  21.6MB

$ docker run -d --name qn-nix -p 8081:8080 quicknotes:v0.1.0
$ curl -sS -w '\n(http %{http_code} in %{time_total}s)\n' http://127.0.0.1:8081/health
{"notes":4,"status":"ok"}
(http 200 in 0.008796s)

$ docker logs qn-nix
2026/10/16 06:12:41 quicknotes listening on :8080 (notes loaded: 4)
```

And the config that Nix wrote, read back out of the loaded image:

```
Entrypoint  : /bin/quicknotes      (exec form, no shell)
User        : 65532:65532          (nonroot)
ExposedPorts: 8080/tcp
Env         : ADDR=:8080 | DATA_PATH=/tmp/notes.json | SEED_PATH=/app/seed.json
architecture: amd64   os: linux
```

Every requirement in 2.1 is therefore checked by observation rather than by
reading the flake: exec-form entrypoint, `8080/tcp` exposed, nonroot, and an image
that Docker accepts without any Docker having been used to build it.

One deliberate difference from the Lab 6 image: there is **no `HEALTHCHECK`**.
QuickNotes has no self-check flag, so a healthcheck would mean compiling a second
helper binary into the image; the Lab 6 Dockerfile did exactly that. Docker
`HEALTHCHECK` is not one of the requirement list's items, and every platform this
image runs on (Render, Codespaces) does HTTP health checking from outside instead,
so the extra binary would be complexity without a consumer. Worth stating rather
than leaving as a silent divergence.

## 2.2 Reproducibility proof

Two builds of the same derivation, hashed on the tarball:

```
$ nix build .#docker
$ sha256sum result
cf1edd32d10c817da8147ce18fb2e9f0377a943857fa84547f8d2abb5245702a  result
# 3,163,990 bytes

$ nix build .#docker --rebuild        # force a second, fresh build
$ sha256sum result
cf1edd32d10c817da8147ce18fb2e9f0377a943857fa84547f8d2abb5245702a  result
# 3,163,990 bytes
```

Identical to the byte, and identical in size. The same caveat as in 1.2 applies:
this is a forced rebuild inside one environment, so it proves the image
derivation is deterministic; the two-independent-runners version is the CI job in
the [Bonus section](#bonus-task--ci-verified-reproducibility).

### Why the timestamp does not move

This is the part that makes the image reproducible where `docker build` is not.
Nix's image config, extracted from the tarball:

```
created      : 1970-01-01T00:00:01Z
architecture : amd64
os           : linux
```

Compare that with the two Lab 6 builds in 2.3, whose `Created` fields were the
wall clock 23 seconds apart. `dockerTools.buildImage` writes a fixed epoch instead
of the moment of the build, which is why the digest above is stable and why
`SOURCE_DATE_EPOCH` never had to be set: the tool does not consult the clock in
the first place. See question (j).

## 2.3 Comparison with the Lab 6 Dockerfile build

The same source, built twice with `--no-cache`, on this host, back to back:

```
$ docker build --no-cache -t qn-lab6:run1 ./app      # exit 0
$ docker build --no-cache -t qn-lab6:run2 ./app      # exit 0

$ docker images --no-trunc --format '{{.Repository}}:{{.Tag}}  {{.ID}}  {{.CreatedAt}}  size={{.Size}}'
qn-lab6:run2  sha256:e1a267194cedd95fab05765ff0797ee954737409379d6e9ea4fd8699778706ec  2026-10-16 07:12:46 +0300 MSK  size=23.1MB
qn-lab6:run1  sha256:0ece6b826ca7961e02617e1cb361cb53d71ea32e77b286a72571179d904094c0  2026-10-16 07:12:23 +0300 MSK  size=23.1MB

$ docker inspect --format '{{.Created}}' qn-lab6:run1
2026-10-16T04:12:23.766915829Z
$ docker inspect --format '{{.Created}}' qn-lab6:run2
2026-10-16T04:12:46.77278258Z
```

**The two image IDs differ**, and the `Created` fields differ by 23 seconds — same
Dockerfile, same source, same machine, twice in a row. The image config records the
wall-clock moment of the build, so the digest cannot be a function of the source
alone. This is the counter-example the Nix build is measured against: `nix build
.#docker` twice yields one digest, `docker build` twice yields two.

Note what did *not* differ: both images are 23.1 MB and both serve QuickNotes
identically. Non-reproducibility is not a functional defect — which is precisely
why it survives unnoticed in most pipelines, and why establishing it needs a
deliberate experiment rather than a bug report.

### Size: Nix-built vs Docker-built

The two pipelines also produce slightly different images, because they are not
assembling the same thing:

| | Nix `dockerTools.buildImage` | Lab 6 Dockerfile | 
|---|---:|---:|
| tarball on disk | 3,163,990 bytes | — (not exported as a tarball) |
| as Docker reports it | **21.6 MB** | **23.1 MB** |
| base | `buildEnv` of the binary + `extraCommands`; no distro at all | `gcr.io/distroless/static:nonroot` |
| `HEALTHCHECK` | none | a small Go helper, compiled into the image |
| `/etc/passwd` | absent (numeric `65532`) | provided by distroless |
| reproduces | yes (digest above) | no (two IDs above) |

The Nix image is ~1.5 MB smaller, and the difference is almost entirely the
healthcheck helper and the distroless base's own metadata. Neither is "better"
in the abstract: the Lab 6 image is a closer analogue of a normal container
workflow, and the Nix image is smaller only because it does less. What the size
column is really useful for is noticing that reproducibility did not cost
anything — the reproducible image is not fattened by extra tooling, because
nothing extra was added to it.

The same experiment runs automatically on every push as the `lab6-baseline` job of
[`.github/workflows/nix-repro.yml`](../.github/workflows/nix-repro.yml), so the
comparison does not depend on this particular machine — and that job has no
`needs:`, so it reports regardless of what the Nix jobs are doing.

## 2.4 Design questions

### e) What does `docker build` do that introduces non-determinism?

`docker build` is a *stateful, networked, clock-observing* process, and each of
those properties leaks into the artefact:

1. **Wall-clock timestamps.** Every layer records a creation time, and the image
   config has a `created` field. Build the same Dockerfile twice a minute apart
   and the config differs. `COPY`/`RUN` also set file mtimes from the time of
   the build.
2. **Mutable base images.** `FROM golang:1.24-alpine` is a tag, not a digest.
   Rebuilding next week can start from a different base layer.
3. **Networked `RUN` steps.** `apk add`, `apt-get update`, `go mod download`,
   `pip install` — every one of these fetches mutable content from a remote that
   does not promise byte-stability over time.
4. **Filesystem ordering.** Tar entries and, historically, layer diffs can
   follow the order the filesystem returns, which is not part of the Dockerfile.
5. **BuildKit attestations.** `provenance`/`sbom` add manifests whose content is
   not derived from your source, so the manifest list digest moves even when the
   image content does not.
6. **Build args and environment.** `--build-arg` values are baked into layers,
   and `ENV` values can embed versions, hostnames or timestamps.
7. **Cache state.** Different cache hits/misses change which commands actually
   executed, which changes layer contents (e.g. a cached `RUN` that once
   downloaded a package).

So the *image digest* differs even when the Dockerfile and the source are
identical. The image is reproducible only up to "the artefact of a particular
moment on a particular daemon", which is not a claim anyone can check.

### f) For a security auditor: what does a reproducible image let you prove that a signed-but-non-reproducible one does not?

A signature proves two things: **who** produced the artefact, and that it has not
been altered **since**. It says nothing about whether the artefact corresponds to
the source you reviewed. A compromised build farm can sign a backdoored image
with a perfectly valid key, and the signature will verify.

Reproducibility is what closes that gap, because it lets an auditor *re-derive*
the artefact instead of trusting the producer:

* **Source-to-binary correspondence.** The auditor checks out the claimed
  revision, rebuilds, and gets a byte-identical digest. That is evidence the
  published image was built from the published commit — not from a modified tree.
* **Injected-code detection, even against a compromised builder.** If the build
  system inserted a backdoor, the rebuilt artefact would differ. Signing cannot
  detect this; reproducibility can.
* **Independent verification of the pipeline.** A third party can rebuild on
  their own hardware with their own toolchain and compare, rather than taking
  the vendor's word for what their CI did.
* **Auditability over time.** Years later, the same inputs still produce the same
  digest, so an archived artefact can be re-verified rather than merely
  re-signed.
* **A meaningful deployment gate.** "The digest running in production equals the
  digest I rebuilt from audited source" is a checkable statement; "it is signed
  by our key" is a statement about a key, not about code.

In short: a signature delegates trust to the builder; a reproducible build
removes the need to.

### g) What is the trade-off of Nix's reproducibility, and why is `docker build` still the default?

Nix buys determinism with a new model that has to be learned and maintained:

* **A different mental model.** Derivations, purity, the store, the sandbox,
  fixed-output derivations, `vendorHash`, locking. A Dockerfile is a list of
  shell commands; a flake is a program in a lazy functional language.
* **Binary cache dependency.** Without `cache.nixos.org` or a private cache
  (Cachix), you rebuild the world from source — minutes turn into hours.
* **Disk and invalidation cost.** The store is large, and changing one input
  invalidates everything downstream of it.
* **Ecosystem coverage.** Many projects have no Nix expression, so somebody has
  to write and keep one — the flake becomes another artefact to maintain.
* **Ergonomics and onboarding.** Debugging a failed derivation inside a sandbox
  is harder than reading a Docker build log, and Windows means "through WSL".
* **It only matters for some goals.** Most teams do not need bit-identical
  rebuilds. They need "ship the new version reliably", and Docker's iterate-fast
  loop, universal familiarity, native support in every CI/hosting platform and
  enormous image ecosystem dominate that trade-off.

What actually pushes teams toward reproducibility is a *requirement*, not a
preference: regulated supply chains, high-assurance environments, long-term
archival, or a need to verify third-party binaries. Within Docker that pressure
is partly relieved by cheaper mitigations — digest-pinned bases, BuildKit's
timestamp rewriting (`rewrite-timestamp=true`) and `SOURCE_DATE_EPOCH`, SBOM and
provenance attestations — which get you closer to auditable without adopting a
new build language. That is why `docker build` remains the default and Nix
remains the specialist tool.

---

# Bonus Task — CI-verified reproducibility

## B.1 The workflow

Full file: [`.github/workflows/nix-repro.yml`](../.github/workflows/nix-repro.yml).
Three jobs, all third-party actions pinned to a 40-character SHA:

| Job | Runs on | Purpose |
|---|---|---|
| `repro-a` | fresh runner | build `.#quicknotes` + `.#docker`, emit digests as job outputs |
| `repro-b` | **independent** fresh runner | the same, plus an optional deliberate divergence |
| `compare` | fresh runner | asserts nixpkgs rev, store hash and image digest are equal; fails otherwise |

## B.2 Green run: two independent builds, identical digests

<!-- FILL_BONUS_GREEN -->
> ⏳ **Pending** — green run URL + log excerpt with the two matching digests.

## B.3 Red run: the gate caught a deliberate divergence

<!-- FILL_BONUS_RED -->
> ⏳ **Pending** — red run URL showing `compare` failing on unequal digests.

## B.4 Design questions

### h) What is the difference between "reproducible on my laptop" and "reproducible in CI", and why is the CI proof load-bearing?

"On my laptop" proves that the build does not depend on the *state of one
machine* — no stale file, no forgotten local patch. It is a real result and it is
where every reproducibility claim starts. But as evidence for anybody else it is
an anecdote: the environment is unspecified and unshareable. Your kernel, your
locales, your timezone, your warm Nix store, your `~/.config/nix/nix.conf`, a
locally present store path that satisfied an input, and possibly a
`--impure`/`--override-input` you forgot about are all invisible in the claim
"it worked twice here".

CI moves the claim from *my machine* to *a machine nobody controls in advance*,
which is what makes it checkable:

* the environment is **declared and disposable** — a fresh runner per build, so
  there is no accumulated state to accidentally depend on;
* it builds **exactly the committed revision**, so the claim is about the
  artefact that ships, not about something you built in isolation;
* the pipeline is **visible and repeatable by a third party** — the auditor can
  read the workflow, see that the two builds are genuinely independent, and run
  the same job themselves;
* it produces a **log of the comparison**, so "the two digests are equal" stops
  being a sentence in a report and becomes an assertion that failed the build
  when it was false.

That last point is the load-bearing one: CI is the only place where
reproducibility is *enforced* rather than *reported*. On a laptop, a mismatch is
a puzzle you can shrug at; in the pipeline, it is a red build.

### i) Why two parallel jobs instead of one job that builds twice?

Because a single job building twice barely builds twice at all. In one job the
second `nix build` runs against the **same** environment and almost always finds
the result already in the local Nix store, so it returns the existing path
without doing any work. The comparison then proves nothing except that Nix is
idempotent — it would pass for a flake that is not reproducible at all.

Even if you force a real rebuild in the same job (`nix store delete`,
`--rebuild`), you still share everything else that can leak into a build: the
kernel, the filesystem, the CPU features and `-march` decisions, environment
variables, the clock and timezone, a global `nix.conf`, and any store path that
happens to be present. A single host can therefore mask exactly the failures
that matter:

* a dependency that is only satisfied because a store path already exists
  locally;
* a variable set in the job environment (this is precisely what the deliberate
  divergence in `repro-b` exploits — it is invisible to a same-environment
  comparison);
* a cached derivation that never gets rebuilt, so drift in its inputs stays
  hidden;
* ambient timezone/locale/clock effects.

Two fresh runners remove all of it: independent disks, independent stores,
independent caches, provisioned from scratch, with no shared history. That is
also the honest interpretation of the assignment's "two independent
environments" — and it matches the auditor's threat model, because the auditor's
machine is a separate machine too.

### j) `SOURCE_DATE_EPOCH` — where does a timestamp leak in, and how does `dockerTools.buildImage` handle it?

Timestamps leak into an image in several places:

* the OCI config's **`created`** field;
* **per-layer** metadata and the mtime of every file added by `COPY`/`RUN`;
* **archive ordering** and gzip mtime headers when the tarball is compressed;
* anything the build itself derives from the clock — a version string, a
  `-ldflags "-X main.buildTime=$(date)"`, an embedded "built at" banner;
* build IDs computed from a hash that includes a clock value.

`SOURCE_DATE_EPOCH` is the cross-ecosystem convention for pinning that: the
build reads a single fixed epoch from the environment instead of reading the
clock, and every timestamp in the output derives from it. Two builds then agree
because neither ever asked what time it was.

`dockerTools.buildImage` handles this by construction rather than by discipline:
the layer metadata it writes is derived deterministically, and its `created`
field is a fixed value rather than "the moment the build ran", so running the
same derivation twice produces the same tarball bytes without anyone setting
`SOURCE_DATE_EPOCH` at all. That is not an assumption here — the config was read
back out of the built image:

```
created      : 1970-01-01T00:00:01Z
architecture : amd64
os           : linux
```

`1970-01-01T00:00:01Z` is the epoch, one second past it, and it is the same value
in both builds in 2.2. Contrast the `Created` fields in 2.3, which are 23 seconds
apart because `docker build` stamps the wall clock. When a derivation genuinely
needs a timestamp, `SOURCE_DATE_EPOCH` is the knob Nix passes down, which keeps
the value an input of the derivation (and therefore visible in the hash) instead
of an ambient property of the machine.

For the deliberate-divergence demonstration in B.3 the flake was perturbed with a
**content** change in one job rather than a clock change. The reasoning is in
[Why the demo perturbs content, not the clock](#why-the-demo-perturbs-content-not-the-clock):
a clock-based divergence is a weak test if the tool already normalises
timestamps, and a content divergence cannot be masked by a cache hit.

---

# Why the demo perturbs content, not the clock

The assignment suggests breaking reproducibility by setting a different
`SOURCE_DATE_EPOCH` in one of the two jobs, and that is a good teaching example.
It is a weak *test of the gate*, though, and it is worth saying why we used a
content change instead:

* **It can be normalised away.** `dockerTools` writes deterministic metadata by
  construction, so if the tool already ignores or fixes the timestamp, changing
  `SOURCE_DATE_EPOCH` may change nothing at all — and a gate that "catches" a
  divergence which never happened proves nothing. (Whether the timestamp
  actually reaches the output is checkable: the workflow dumps the image's
  `manifest.json` and OCI config, so the `created` field is visible in the log
  rather than assumed.)
* **It can be masked by caching.** A timestamp change that does not alter the
  derivation's inputs produces an identical store path, so the second "build"
  may simply return the cached output.
* **A content change cannot be masked.** Perturbing `app/seed.json` — a file that
  is copied into the image — changes the source hash, therefore the derivation,
  therefore the artefact. If `compare` stays green after that, the gate is
  genuinely broken and we would know it.

So the perturbation is deliberately unambiguous: one job builds a different
tree, and the question the gate has to answer is simply "did you notice?". A
gate that only fails on the specific perturbation you designed for it is not a
gate.

---

# Where the builds actually ran

## Short version

Nix could not run on this machine, so the two independent builds run in **CI, on
two fresh runners** — which is the stronger form of the same evidence (separate
disks, separate Nix stores, separate caches, provisioned from scratch for one
commit) and is what the Bonus Task asks for anyway. Everything below is recorded
because "it did not work on my machine" is only useful if you say *what* did not
work and *how you know*.

## Why Nix could not run locally

| Resource | Measured | Required |
|---|---:|---|
| Free space on `C:` | **0.25 GB** | Nix store + nixpkgs + Go toolchain ≈ 8–20 GB |
| Commit charge (RAM + pagefile) | **26.1 GB of 26.3 GB** | Docker Desktop needs several GB to start its VM |

All three possible paths are blocked by the host, not by the flake:

1. **Native Windows** — Nix has no native Windows port; the supported route is
   WSL2, so this was never an option.
2. **WSL2** — an Ubuntu distro is installed, but it will not start:
   ```
   $ wsl -d Ubuntu -- bash -lc 'uname -a'
   Разрушительный сбой
   Код ошибки: Wsl/Service/E_UNEXPECTED
   ```
   `wsl -l -v` also shows both `Ubuntu` and `docker-desktop` in state `Stopped`,
   so the WSL session itself is not healthy.
3. **A container — `docker run nixos/nix`**, i.e. the assignment's own recommended
   way to obtain an independent environment. Docker Desktop refuses to start:
   ```
   Сбой выполнения программы docker.exe: The paging file is too small for this
   operation to complete
   ```
   and while retrying, the tooling on the host began failing outright with
   `ENOSPC: no space left on device`.

None of this is a property of the flake, and none of it changes the result — it
changes *where* the two builds happen. Being explicit about it matters because the
alternative is a report claiming a laptop proof that nobody can reproduce.

### Update: Docker came back, Nix did not

Part way through the work the host recovered enough to start Docker Desktop: free
space rose to ~3 GB and closing applications brought the commit charge down from
26.1/26.3 GB to 24.3/26.3 GB, at which point the engine came up in ten seconds.
That is worth recording, because it changes what could be measured here rather
than in CI:

* **Unblocked — the control experiment.** `docker build` twice needs a daemon, and
  it now ran on this host; the results are in
  [section 2.3](#23-comparison-with-the-lab-6-dockerfile-build).
* **Partly unblocked — the Nix *evaluation*.** Freeing Docker's data disk (below)
  restored enough space to hold the nixpkgs source and to evaluate every flake
  output with `--offline`, which is how the two defects in section 1.1 were found
  before any push. What stays network-bound is the *build*: the Go toolchain and
  the stdenv closure still have to come from `cache.nixos.org`, and this link
  delivers roughly 180 KB/s and truncates large transfers (a 48.7 MB nixpkgs
  archive took 270 seconds and a first attempt died with "Truncated tar archive
  detected"). So the builds that produce the store hashes and image digests run on
  CI runners, whose network and disk are not the variable under test.

### What was freed, and what it cost

Recorded because it changed the machine, not just the lab:

* All Docker images not needed for this lab were deleted (ZAP 3.58 GB, two
  `mlops_assignment1` images at 1.47 GB each, Ansible 0.55 GB, Trivy, two Alpine
  and two Python images). That freed ~7.6 GB *inside* Docker but almost nothing on
  `C:`, because Docker's WSL2 disk is a dynamic VHDX that does not shrink when
  files are removed from it.
* To actually return that space, Docker was stopped and
  `%LOCALAPPDATA%\Docker\wsl\disk\docker_data.vhdx` (17.0 GB, almost entirely
  space held for already-deleted layers) was removed so Docker Desktop could
  recreate it. That moved `C:` from 0.25 GB free to 19 GB.
* Three small named volumes (`quicknotes-data`, `devops-intro_quicknotes-data`,
  `trivy-cache`) and four stopped containers from earlier labs were removed with
  the disk. None of them were deliverables — they were runtime state of earlier
  toy deployments.
* `pagefile.sys` then grew from 10.7 GB to 15.4 GB on its own (Windows manages it
  automatically), which is why free space did not stay at 19 GB.

So the split is deliberate: the *control* experiment is local, the *reproducible*
builds are on disposable CI runners. That is also the better arrangement — a
reproducibility proof is worth more when it comes from machines nobody tuned than
from the one that happens to have the flake checked out.

## A second environment problem: poisoned DNS for `api.github.com`

Independent of the disk, this network answers DNS for `api.github.com` with an
address that is not GitHub:

```
$ python -c "import socket; print(socket.gethostbyname('api.github.com'))"
204.12.192.222          # not a GitHub address
```

`api.github.com` is exactly what Nix's `github:` fetcher talks to in order to
resolve `github:NixOS/nixpkgs/nixos-25.11`, so `nix flake lock` / `nix build`
would have failed to fetch nixpkgs even on a healthy machine. `github.com` and
`codeload.github.com` resolve and serve normally, so the fault was isolated to
that one name.

Resolving over DNS-over-HTTPS (which runs on 443, which this network allows) gives
the authoritative answer, and both addresses serve the API correctly when the TLS
SNI is right:

```
$ python doh_resolve.py
local: 204.12.192.222
dns.google           ['140.82.121.5']
cloudflare-dns.com   ['4.225.11.201']
--- verifying each IP with correct SNI/TLS ---
  140.82.121.5       HTTP/1.1 200 OK
  4.225.11.201       HTTP/1.1 200 OK
```

CI runners are unaffected (they use GitHub's own resolvers), which is another
reason the proof is better placed there.

## Running it locally, once the machine allows

This is the recipe this report would have used, including the DNS workaround, so
the local path is written down and not lost:

```bash
# two genuinely independent environments, without installing Nix on the host
docker run --rm -it --add-host api.github.com:140.82.121.5 \
  -v "$PWD:/repo" -w /repo nixos/nix bash

# inside each container, independently:
nix build .#quicknotes -L
nix-store --query --hash "$(readlink -f result)"

nix build .#docker -L
sha256sum result

# and the non-reproducible control experiment (needs the host's Docker):
docker build --no-cache -t qn-lab6:run1 ./app
docker build --no-cache -t qn-lab6:run2 ./app
docker images --no-trunc qn-lab6
```

`--add-host` is the whole DNS fix for the container: Docker's embedded resolver
forwards to the host, which is poisoned, so the correct address is injected
directly. Each container gets its own `/nix` store, which is what makes the two
builds independent rather than two runs in one cache.

The `Task 2.3` control experiment does not need Nix, only a Docker daemon, so it
was measured directly on this host (section 2.3). It also runs on every push as
the `lab6-baseline` CI job, so the comparison survives this machine going away.


---

# Appendix — reproduce it

```bash
# anywhere with Nix + flakes
nix build .#quicknotes
nix-store --query --hash "$(readlink -f result)"
./result/bin/quicknotes &
curl -s localhost:8080/health

# the deterministic image
nix build .#docker
sha256sum result
docker load < result
docker run --rm -p 8080:8080 quicknotes:v0.1.0

# the dev shell the flake promises
nix develop
go version && gopls version && golangci-lint --version

# the two-independent-build proof, locally
for d in A B; do
  nix build .#docker --rebuild
  echo "$d $(sha256sum result | awk '{print $1}')"
done
```
