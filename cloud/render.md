# Task 2 — deployment target: **Option B, GitHub Codespaces**

## Which option, and why

The lab says: use Option A (Render); if Render asks for card verification,
switch to Option B (Codespaces) and say so in the report.

Render was attempted first. The signup flow required card verification, and
Russian-issued cards are rejected there (the lab calls this out explicitly in
*Why these platforms?* and in the pitfalls). Two things follow from that:

1. Card-free is a hard constraint of this lab — adding a card is "off the
   rails" by the assignment's own wording.
2. Option B is not a downgrade: the same published `ghcr.io` image from Task 1
   is run, the same cold-vs-warm question is answered, and the question is
   arguably sharper, because a codespace's storage is *persistent* while
   Render's is ephemeral.

So Task 2 runs the **image built by Task 1** inside a codespace, with port 8080
exposed publicly. See `cloud/devcontainer.md` for the artifact and the commands.

## What was prepared for Option A (kept for reproducibility)

Even though Render was not used, the service definition is written down as
config-as-code in [`cloud/render.yaml`](render.yaml) so the intent is
reproducible the moment an account works. The settings that matter:

| Setting | Value | Why |
|---|---|---|
| Source | **Existing image** `ghcr.io/fishkadealer229/devops-intro/quicknotes:v0.1.0` | The image is the artifact Task 1 produced and the one that was smoke-tested in CI. Render building from the repo would produce a *different*, independently built image. |
| Instance type | **Free** | The create form pre-selects a paid instance; Free must be chosen explicitly before Deploy. |
| Region | **Frankfurt** | Closest region to Innopolis. |
| Health check path | `/health` | QuickNotes answers `{"status":"ok","notes":N}`. |
| `ADDR` | `:8080` | QuickNotes' listen address. |
| `PORT` | `8080` | Pins Render's routing port to the same value as `ADDR`, so the platform never detects a "new primary port" and restarts the deploy. |
| `DATA_PATH` | `/data/notes.json` | Writable location in the image; the rest of the root filesystem is read-only in spirit (distroless, nonroot). |
| `SEED_PATH` | `/app/seed.json` | Seed data baked into the image. |
| Auto-deploy | **off** | Deploys are triggered by the release workflow's deploy hook, so the deployed tag always matches the released tag. |

### Deploy hook

`.github/workflows/release.yml` has a `deploy` job that runs after the smoke
test and calls the service's deploy hook, passing the freshly built tag as
`imgURL` (URL-encoded `%2F` / `%3A`, since only the tag may differ from the
image the service was created with):

```
curl -fsS -X POST "${RENDER_DEPLOY_HOOK_URL}&imgURL=${ENCODED}"
```

The hook URL embeds an authorising key, so it is stored **only** as the GitHub
Actions secret `RENDER_DEPLOY_HOOK_URL` — never in the repository. When the
secret is absent the step logs `RENDER_DEPLOY_HOOK_URL is not set — skipping
Render redeploy.` and exits 0, which is what keeps the release green for the
Codespaces-only setup used here.
