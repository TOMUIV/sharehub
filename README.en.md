<div align="center">

<img src="assets/cover.png" alt="ShareHub" width="100%">

# ShareHub · Self-hosted Resource Sharing Station

**One file to run your self-hosted resource sharing station — admins upload, visitors download without login.**

Python 3 · Zero third-party dependencies · MIT · Docker

[中文](./README.md) · [Deploy](#quick-start) · [Why ShareHub](#why-sharehub) · [Cache & Reservation](#cache--reservation-mechanism)

</div>

---

## What is this

ShareHub is a **lightweight self-hosted resource sharing station**: an admin organizes files and folders into a directory tree from the web UI, and visitors can browse and download **without any account**.

It is not a heavyweight netdisk (no multi-user, no sync clients, no database), nor a one-time share tool (no links that expire and delete). It does exactly one thing: **"admin curates content → visitors download directly"** — perfect for course materials, research assets, team resource libraries, and asset distribution sites.

```
┌──────────────┐        ┌───────────────────┐        ┌──────────────────┐
│  Admin panel  │ ─upload─▶ │   File pool (tree)  │ ─browse─▶ │  Public frontend  │
│  chunk upload │        │  quota/cache/rsv  │        │  no-login download│
└──────────────┘        └───────────────────┘        └──────────────────┘
```

## Why ShareHub

### 🎯 Folder-context upload (exclusive) — upload continuously, never misplaced
Clicking upload inside a folder sends files **only to that folder**. If you switch to another folder while uploads are in progress, **queued files still go to their original folder** — they never leak into the wrong place. You can keep uploading while organizing elsewhere. Many netdisk tools fail at this (switching folders redirects new uploads).

### ⚡ Chunked concurrent upload
Large files are split into **5 MB chunks**, uploaded with **3-way concurrency**, each chunk verified with **SHA-256**. Fast, and never blocked by single-request size limits.

### 🔁 Resumable · stable transfer
After a network drop, tab close, or cancel, re-selecting the same file **re-uploads only the missing chunks**; files ≤64 MB can also be deduplicated by content hash. Combined with folder-context upload, tasks resume reliably even if you navigate away.

### 📂 Folder mechanics
Drag-and-drop or pick entire folders; files are **queued in ascending size order** (small first); duplicate folder names **merge** (same-name files overwrite, new files join the folder); files inside folders always stay in their folder.

### ⚖️ Quota reservation (rare in this category)
Capacity is **reserved at init time based on net delta** (overwriting an old file only reserves the difference) — instead of finding out it doesn't fit after uploading. Reservations are reclaimed three ways: **cancel releases immediately, 2-minute idle auto-releases, tab close releases instantly (sendBeacon)**. Concurrent uploads never overshoot.

### 📊 Real-time visualization
- **Four-segment capacity bar**: used / reserved / cache / available — always sums to the total.
- **Upload status bar**: total / done / uploading / waiting / paused / failed — live stat cards.
- **Pagination**: 12 cards per page, the "go up one level" card occupies one slot; both file and task lists support page jumping.

### 🛡️ Security
HMAC-signed cookies + sliding 7-day renewal + HttpOnly/SameSite; realpath traversal protection; per-chunk hash verification; all admin endpoints require login.

### 🐍 Single file · zero dependencies
The entire app is one `server.py` (~110 KB, Python standard library). No database, no Node, no PHP. Runs anywhere Python 3 exists; containerization is natural.

## Cache & Reservation Mechanism

**Why "cache"?** Uploads are chunked: chunks first land in `.uploads/`, then merge into the final file in the pool. Cancelled or interrupted chunks are **kept as cache** — so re-uploading the same file can **resume**. The cache is auto-cleaned by a 10-minute TTL, and can also be managed manually via "view cache / clear cache" in the admin panel.

**Why "reservation"?** Every file must pass a capacity check at init. To prevent concurrent uploads from each passing the check yet exceeding the quota together, the server **reserves** capacity for each passed file (only the net delta for overwrites). Reservations are released three ways:

| Scenario | Reservation outcome |
|---|---|
| Upload completes | File enters the pool, reservation released |
| Cancel | Released immediately; chunks kept as cache (resumable) |
| Tab closed | Released instantly via sendBeacon |
| Crash / network drop | Auto-released after 2-min idle; chunk cache kept until the 10-min TTL |

"Available space" is therefore always accurate — and you never find out half-way that a file won't fit.

## Comparison

| | **ShareHub** | Netdisk (Nextcloud/Cloudreve) | File manager (FileBrowser) | One-time share (Jirafeau/MicroBin) |
|---|---|---|---|---|
| Focus | admin curates + visitor read-only | personal storage/sync/collab | multi-user file mgmt | upload & get a link |
| Accounts | single admin password | multi-user | multi-user | none |
| Chunked concurrent upload | ✅ 3-way + verify | some | some | few |
| Resume | ✅ + hash dedup | some | some | few |
| Folder-context upload | ✅ **exclusive** | ❌ often misplaced | — | — |
| Quota reservation | ✅ 3-way release | simple reject | none | none |
| Live status bar/capacity | ✅ | some | little | none |
| Deploy | single file/container, zero deps | heavy (PHP/DB) | Go binary | single file |
| Visitor download | ✅ no-login read-only | needs account/link | needs account | one-time link |

## Quick Start

### Option 1: Run directly (zero dependencies)

```bash
# Requires Python 3.8+
python3 server.py --host 0.0.0.0 --port 18888 --prefix ""
```

Then open:
- Frontend (no-login download): `http://your-host:18888/`
- Admin: `http://your-host:18888/admin` (default password `root`, change it after login)

> Routes are absolute paths; `--prefix` only affects links generated by the frontend. Default `--prefix ""` deploys at the root. For a subpath (e.g. `/share`) behind nginx, use `--prefix /share` (see Option 4).

### Option 2: Docker

```bash
docker run -d --name sharehub \
  -p 18888:18888 \
  -v $(pwd)/config.json:/app/config.json \
  -v $(pwd)/data/files:/app/files \
  -v $(pwd)/data/logs:/app/logs \
  sharehub/sharehub:latest
```

Or with docker-compose:

```bash
docker compose up -d
```

### Option 3: systemd (Linux daemon)

```bash
sudo useradd -r -s /usr/sbin/nologin share
sudo mkdir -p /opt/share
sudo cp server.py config.json /opt/share/
sudo cp share.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now share
```

### Option 4: nginx reverse proxy (HTTPS + subpath)

See `nginx.conf.example`. Key point: `proxy_pass http://127.0.0.1:18888/;` (the **trailing slash** strips the `/share` prefix, since backend routes are absolute), and run the container with `--prefix /share`. Chunked uploads use chunked requests, so set `client_max_body_size 0`.

## Configuration

`config.json`:

```json
{
  "admin_password_hash": "4813494d137e1631bba301d5acab6e7bb7aa74ce1185d456565ef51d737677b2",
  "quota": 10737418240
}
```

- `admin_password_hash`: SHA-256 of the admin password. Default password is `root` (matches the hash above).
- `quota`: total pool capacity in bytes. Can be adjusted online via "⚖️ change capacity" (0.5GB ~ 200GB).

## Usage

**Admin** (login required): upload files/folders, create folders, multi-select → ZIP download / delete, view cache, clear cache, view logs, change capacity, change password.

**Frontend** (no login): browse the directory tree, search the current folder, paginated browsing, download single files or ZIP bundles.

## Roadmap

- [ ] Share links (expiry / password / download limit)
- [ ] Multiple admins / roles
- [ ] File preview (images / audio / video / documents)
- [ ] Bilingual UI switching
- [ ] Storage backends (local dir / S3 / object storage)

## License

[MIT](./LICENSE)
