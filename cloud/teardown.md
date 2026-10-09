# Tear-down (Lab 10)

Both deploy targets in this lab are free, so nothing here costs money if left
running. It is still documented, and it *does* matter for quota hygiene.

## Codespaces (Option B — the one actually used)

A **stopped** codespace still consumes the storage quota (15 GB free), and it
keeps consuming it until it is deleted or auto-expires. Compute hours only tick
while it runs, but storage is the trap.

```bash
# list codespaces and their state
gh codespace list

# stop it (frees compute, keeps storage)
gh codespace stop -c <codespace-name>

# delete it (frees compute *and* storage) — do this when the lab is graded
gh codespace delete -c <codespace-name>
```

Web equivalent: <https://github.com/codespaces> → the codespace → **Stop** or
**Delete**.

Codespaces also auto-delete after a default 30-day retention period of
inactivity; that is not a substitute for deleting it deliberately.

## Render (Option A — prepared, not activated)

If a Render service had been created:

1. Dashboard → the `quicknotes` service → **Settings**.
2. **Suspend** the service (keeps config, stops the container), or
3. **Delete** the service at the bottom of Settings.
4. Free instances cost nothing while suspended; a *paid* instance type bills by
   the hour, which is why the create form must not be left on the default plan.

## Local resources (Bonus)

The Cloudflare quick tunnel is ephemeral and holds no account state, but the
local processes should still be cleaned up:

```bash
# stop the tunnel (Ctrl-C in its terminal), then
docker rm -f qn-lab10                 # the local QuickNotes container
docker image rm quicknotes:lab10-local  # the locally built image
```

The quick tunnel URL dies with the `cloudflared` process — nothing to delete on
Cloudflare's side, which is one of the nicer properties of quick tunnels.
