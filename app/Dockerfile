# QuickNotes — production image (Lab 10)
#
# Written from scratch for the release pipeline:
#   * multi-stage, static binary, no shell in the runtime image
#   * runs unprivileged (distroless :nonroot, uid 65532)
#   * built for linux/amd64 — Render, Codespaces and Cloudflare all run amd64
#   * seed data is baked in; mutable state lives in the writable /data directory
#
# Port contract (QuickNotes source is never modified):
#   QuickNotes listens on $ADDR (default :8080); platforms like Render inject
#   $PORT and route traffic there. They must agree *by configuration*:
#       ADDR=:8080  PORT=8080
#   See cloud/render.md.

# ---------- stage 1: build ----------
FROM golang:1.24-alpine AS build

WORKDIR /src

# Dependencies first: this layer stays cached across source-only changes.
COPY go.mod ./
RUN go mod download

COPY . .

# Cache mount keeps the Go build cache out of the image layers.
RUN --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 GOOS=linux go build \
        -trimpath \
        -buildvcs=false \
        -ldflags="-s -w" \
        -o /out/quicknotes .

# distroless has no shell and no curl, so HEALTHCHECK needs a real binary.
RUN --mount=type=cache,target=/root/.cache/go-build \
    printf '%s\n' \
      'package main' \
      'import (' \
      '  "net/http"' \
      '  "os"' \
      '  "time"' \
      ')' \
      'func main() {' \
      '  c := http.Client{Timeout: 2 * time.Second}' \
      '  r, err := c.Get("http://127.0.0.1:8080/health")' \
      '  if err != nil {' \
      '    os.Exit(1)' \
      '  }' \
      '  defer r.Body.Close()' \
      '  if r.StatusCode != http.StatusOK {' \
      '    os.Exit(1)' \
      '  }' \
      '}' > /tmp/healthcheck.go \
    && CGO_ENABLED=0 GOOS=linux go build \
        -trimpath -buildvcs=false -ldflags="-s -w" \
        -o /out/healthcheck /tmp/healthcheck.go

# Pre-create the state directory with the nonroot uid/gid (65532) so the
# unprivileged runtime can write notes.json without any shell in the image.
RUN mkdir -p /out/data && chown 65532:65532 /out/data

# ---------- stage 2: runtime ----------
FROM gcr.io/distroless/static:nonroot

# The source label is what links the ghcr.io package to this repository.
LABEL org.opencontainers.image.title="quicknotes" \
      org.opencontainers.image.description="QuickNotes API - DevOps-Intro Lab 10" \
      org.opencontainers.image.source="https://github.com/fishkadealer229/DevOps-Intro" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.base.name="gcr.io/distroless/static:nonroot"

COPY --from=build /out/quicknotes /usr/local/bin/quicknotes
COPY --from=build /out/healthcheck /usr/local/bin/healthcheck

COPY --from=build --chown=nonroot:nonroot /out/data /data

WORKDIR /app
COPY --chown=nonroot:nonroot seed.json /app/seed.json

ENV ADDR=":8080" \
    DATA_PATH="/data/notes.json" \
    SEED_PATH="/app/seed.json"

EXPOSE 8080

USER nonroot:nonroot

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD ["/usr/local/bin/healthcheck"]

ENTRYPOINT ["/usr/local/bin/quicknotes"]
