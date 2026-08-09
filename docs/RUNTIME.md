# Runtime — How This Stack Actually Runs

> **Agents: read this before any `podman`, `systemctl`, or “is the DB up?” check.**
> Verified against live units under `/etc/systemd/system/` and live storage under
> `/opt/smart-ring/.local/share/containers/` (2026-07-26).

---

## 1. Dual Podman store (the trap)

Rootless Podman is **per storage root**. Interactive shells and systemd use
**different** roots on this machine:

| Context | `XDG_DATA_HOME` | Graph root | What `podman ps` sees |
|---------|-----------------|------------|------------------------|
| Default interactive shell | unset (falls back to `$HOME`) | `$HOME/.local/share/containers/storage` | **Usually empty for smart-ring** |
| systemd units (`User=` service account) | `/opt/smart-ring/.local/share` | `/opt/smart-ring/.local/share/containers/storage` | `smart-ring-db`, `smart-ring-api` |

**Rule:** every smart-ring `podman` command **must** set:

```bash
export XDG_DATA_HOME=/opt/smart-ring/.local/share
# or prefix one-shot:
XDG_DATA_HOME=/opt/smart-ring/.local/share podman ps -a
```

If bare `podman ps` is empty and `XDG_DATA_HOME=... podman ps` shows the
containers, **the stack is up**. Do not conclude “no containers,” do not create
a second store, do not rewrite units, do not invent startup wrappers.

**Why two stores exist:** code + Podman storage must live **outside** any
encrypted home directory (ecryptfs / home-dir encryption only decrypts on login).
Units set `Environment=XDG_DATA_HOME=/opt/smart-ring/.local/share` so boot-time
services can start without a login session. Default shell Podman still defaults
to `$HOME`.

---

## 2. Canonical layout

| What | Path |
|------|------|
| Code + venv | `/opt/smart-ring/code` |
| Podman rootless storage (production) | `/opt/smart-ring/.local/share/containers` |
| Unit files (canonical — edit only here) | `/etc/systemd/system/smart-ring-*.service` |
| PG data volume | Podman volume `smart-ring-pgdata` (in the **opt** store) |
| Podman network | `smart-ring` bridge (in the **opt** store) |

There are **no** production unit mirrors under `~/.config/systemd/user/`.
There is **no** docker-compose production path. There are **no** Podman
quadlets for this project.

---

## 3. Services (verified)

All three units are **system** units (`WantedBy=multi-user.target`), run as a
non-root service account (`User=` in the unit), and need `sudo systemctl` /
`sudo journalctl` for lifecycle.

### `smart-ring-db.service`

- **Type:** rootless `podman run --replace --name smart-ring-db`
- **Image:** `docker.io/postgres:16-alpine`
- **Network:** `smart-ring`
- **Publish:** `127.0.0.1:5432→5432`
- **Env:** `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` (from unit or
  local secrets — **not** committed), `TZ` matching host civil time
- **Volumes:**
  - `smart-ring-pgdata` → `/var/lib/postgresql/data`
  - `/opt/smart-ring/code/db/init.sql` → `/docker-entrypoint-initdb.d/init.sql:ro`
    (applies **only on first empty data dir**, not on every restart)
- **XDG:** set in unit

### `smart-ring-api.service`

- **Depends:** `Requires=smart-ring-db.service`
- **Image:** `localhost/smart-ring-api:latest`
- **Network:** `smart-ring` (DNS name of DB container: `smart-ring-db`)
- **Publish:** `0.0.0.0:8000→8000` (firewall-gated — see §3.1 below)
- **Env:** `DATABASE_URL` (host `smart-ring-db` on the podman network), `TZ`,
  `RING_ADDRESS` from local secrets/env (**not** committed to git)
- **Bind mounts:**  
  `/opt/smart-ring/code/api` → `/app`  
  `/opt/smart-ring/code/dashboard` → `/dashboard`  
  `/opt/smart-ring/code/collector` → `/collector:ro`
- **XDG:** set in unit  
- Host API/dashboard edits on those mounts are live after process reload; image
  rebuild only needed for Dockerfile / baked deps. Note: the image runs
  **without** `--reload` — a container restart is required to pick up code
  edits (`sudo systemctl restart smart-ring-api`).

### `smart-ring-api-firewall.service` (API network gate)

The API container publishes `0.0.0.0:8000`, so a box-level firewall is the
only thing between the API and everything that isn't the tailnet. That gate is
a dedicated nftables table loaded by a dedicated oneshot unit:

- **Ruleset:** `/etc/nftables.d/smart-ring-api.nft`
- **Table:** `inet smart-ring`, chain `input` at `priority 0` with `policy
  accept` (unrelated traffic untouched). Allows `tcp dport 8000` from:
  - `127.0.0.0/8` — loopback (Tailscale Serve, local tooling)
  - `192.168.1.0/24` — LAN subnet (home devices)
  - `100.64.0.0/10` — Tailscale CGNAT (direct tailnet access)
  Everything else on `:8000` is dropped.
- **Unit:** `smart-ring-api-firewall.service` (Type=oneshot,
  `RemainAfterExit=yes`, `Before=smart-ring-api.service`). A drop-in
  (`/etc/systemd/system/smart-ring-api.service.d/firewall.conf`) wires
  `Wants=` + `After=` so the rules are loaded before the API starts.
- **LAN subnet changes:** edit the `saddr` set in the nft file, then
  `sudo systemctl restart smart-ring-api-firewall`.
- **ufw caveat:** if `sudo ufw enable` is ever run, ufw flushes the whole
  ruleset including this table — re-apply with
  `sudo systemctl restart smart-ring-api-firewall` (or reboot).

**Access model — the network boundary is the auth.** No app-level token.
Intended paths:

- Tailnet: `https://<tailscale-hostname>` (Tailscale Serve → `127.0.0.1:8000`)
- LAN: `http://<box-lan-ip>:8000`

Anything else (internet/WAN, guest networks, VM bridges) is refused at the
firewall.

### `smart-ring-poller.service`

- **Not a container.** Bare metal:
  `/opt/smart-ring/code/venv/bin/python3 …/collector/sync_request_poller.py --loop --interval 30`
- **WorkingDirectory:** `/opt/smart-ring/code`
- **No** `XDG_DATA_HOME` (does not use Podman)
- Talks to Postgres on `localhost:5432` (published by db unit)

### Collector (BLE)

- Invoked by poller jobs or manually:  
  `venv/bin/python3 -m collector.sync_ring --forget`  
- Bare metal only (BlueZ/DBus). Never containerize.

---

## 4. Commands that work

From a shell owned by the same uid as the unit `User=` (so rootless Podman can
open the opt store). Prefer once per session:

```bash
export XDG_DATA_HOME=/opt/smart-ring/.local/share
cd /opt/smart-ring/code
```

### See the real containers

```bash
podman ps -a
# Expect: smart-ring-db, smart-ring-api (both Up when healthy)
```

### Lifecycle (systemd owns start/stop)

```bash
sudo systemctl status smart-ring-db smart-ring-api smart-ring-poller
sudo systemctl restart smart-ring-api smart-ring-poller
sudo systemctl restart smart-ring-db smart-ring-api smart-ring-poller   # full bounce
sudo journalctl -u smart-ring-db -u smart-ring-api -u smart-ring-poller -n 80 --no-pager
```

After editing a unit file:

```bash
sudo systemctl daemon-reload
sudo systemctl restart smart-ring-db smart-ring-api smart-ring-poller
```

### psql into production DB

```bash
export XDG_DATA_HOME=/opt/smart-ring/.local/share
podman exec -it smart-ring-db psql -U smart_ring -d smart_ring
```

Host TCP also works (DB is published on loopback via `127.0.0.1:5432`).

### Apply new SQL (existing volume)

`init.sql` is **not** re-run on restart. For additive schema on a living DB:

```bash
export XDG_DATA_HOME=/opt/smart-ring/.local/share
podman exec -i smart-ring-db psql -U smart_ring -d smart_ring < /opt/smart-ring/code/db/init.sql
# or paste the CREATE TABLE / ALTER block only
```

Also keep `db/init.sql` in git so new empty volumes get full schema.

### Rebuild API image (when Dockerfile / non-mounted deps change)

```bash
export XDG_DATA_HOME=/opt/smart-ring/.local/share
cd /opt/smart-ring/code
podman build --format docker -t localhost/smart-ring-api:latest api/
sudo systemctl restart smart-ring-api
```

Note: use `--format docker`, not the OCI default — the image carries a
`HEALTHCHECK` (urllib to `/health`) and OCI format drops it.

### Stack alive check (acceptance)

A review or session that cannot run this has not verified runtime:

```bash
# A — wrong store (often empty):
podman ps -a
# B — production store (must show smart-ring-db + smart-ring-api when up):
XDG_DATA_HOME=/opt/smart-ring/.local/share podman ps -a
# C — HTTP:
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/health
# D — firewall gate loaded:
sudo nft list table inet smart-ring
```

If A is empty and B is not → docs/commands were wrong; stack is not “down.”

---

## 5. Hard do-nots

| Do not | Why |
|--------|-----|
| Bare `podman …` without XDG for smart-ring | Wrong graph root; false empty / wrong volumes |
| `systemctl --user` for smart-ring | Units are **system** under `/etc/systemd/system/` |
| `docker compose` / compose files for production | Not how this stack runs |
| Move code or Podman storage into an encrypted home | Encrypted home → boot autostart dies |
| Create wrapper “startup” units | Fix real dependencies; see unit `After=`/`Requires=` |
| Assume empty `podman ps` means stack is down | Run check §4 with XDG first |
| Re-run only `init.sql` and expect ALTER on existing DB | First-init only; apply DDL explicitly |
| Commit `.env`, unit-embedded secrets, or BLE address | Local env / unit files only |

---

## 6. pytest vs production

- Regression tests open `DATABASE_URL` (from env / `.env.example` shape) and
  create ephemeral DBs named `smart_ring_test_<pid>`, then drop them on session end.
- That hits the **published** Postgres port; it is not a second production stack
  and must not replace verifying containers via Podman+XDG.
- Use `venv/bin/python3 -m pytest` (venv shebangs may still point at old paths).

---

## 7. Timezone

- Postgres: server `TimeZone` set to host civil time (this deployment uses
  `America/Vancouver`).
- Both containers: matching `TZ=` in the system units.
- Collector `set_time_local`: local BCD to the ring.

---

## 8. Autostart verification

Proven only by **cold reboot, no login, then boot logs**
(`journalctl -b -u smart-ring-db -u smart-ring-api -u smart-ring-poller`).
“It is running now while I am logged in” does not prove boot.

Units use `After=user@UID.service network-online.target` and
`WantedBy=multi-user.target` (UID = service account from the unit file — read
the unit; do not assume another host’s number).

---

## 9. Secrets / privacy (public remotes)

**Never commit:**

- `.env` (gitignored) — real `RING_ADDRESS`, DB passwords, live `DATABASE_URL`
- BLE MAC, Tailscale hostnames, personal emails/phones
- Copies of `/etc/systemd/system/smart-ring-*.service` if they embed secrets
  (live units on disk may; the repo must not mirror them)

**OK to commit:** paths under `/opt/smart-ring`, public unit *names*, published
ports, architecture prose, placeholder-only values in `.env.example`.
