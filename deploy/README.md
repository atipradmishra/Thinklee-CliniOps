# Deploying CliniOps — cliniops.cloudhubs.nl

Fixes uploads failing on the hosted instance, and moves the app off the
Werkzeug development server.

## Two separate bugs

Both were confirmed against the live host, not inferred.

### 1. Every authenticated API call returns 422

```
POST /api/data/upload-file        → 422   {"msg": "Not enough segments"}
GET  /api/data/get-data-sources   → 422
GET  /api/dashboard/list          → 401   ← different, and the clue
```

The app holds the JWT in two places that can drift apart:

- **Page routes** read it from the **Flask session cookie** — which is why
  pages render 200 and the UI looks signed in.
- **Every `fetch()`** reads it from **localStorage** — which was empty.

`data_management.html` builds its header unconditionally:

```js
Authorization: `Bearer ${localStorage.getItem("token")}`
```

With nothing in storage that interpolates to the literal string
`Bearer null`, which `flask_jwt_extended` rejects with **422 "Not enough
segments"**. Reproduced exactly:

| Header sent | Response |
|---|---|
| `Authorization: Bearer null` | **422** `Not enough segments` |
| no Authorization header | **401** |

`/api/dashboard/list` returned 401 rather than 422 because the sidebar is the
one caller that omits the header when there is no token. That split is what
identified the cause.

> **Note on an earlier theory.** I first attributed the empty localStorage to
> the app being served on both `http://` and `https://` — localStorage is
> scoped to the origin, the session cookie to the domain. That was wrong:
> `http://cliniops.cloudhubs.nl` already returns a 301 to https. The exact
> history that left storage empty (cleared site data, a different browser
> profile, a session cookie outliving the token) can't be recovered from here
> — and no longer matters, because the fix makes it self-healing.

### 2. nginx rejects any upload over 1 MB

```
POST /api/data/upload-file  (2 MB body)  →  413, uploaded=0 bytes
```

`client_max_body_size` is unset, so nginx caps request bodies at its 1 MB
default and rejects real documents before Flask ever sees them. This would
have become the visible failure the moment bug 1 was fixed.

## Fixes

| Change | Where |
|---|---|
| Write the session's token to localStorage on every page render | `app/templates/base.html` |
| Raise `client_max_body_size` to 100 MB | `deploy/nginx-minimal-patch.conf` |
| Run gunicorn instead of `python run.py` | `deploy/cliniops.service` |
| Bind to `127.0.0.1` instead of `0.0.0.0` | `deploy/cliniops.service` |
| 300 s request timeouts | both |

The `base.html` change makes the server session the single source of truth:
every page render rewrites the token, and clears it when there is no session
so callers send no header (401) rather than a malformed one (422).

## Install

```bash
cd ~/Thinklee-CliniOps && git pull && source venv/bin/activate && pip install -r requirements.txt
```

### 1. nginx — add four directives

Do **not** replace your nginx config. Your TLS and your `:80 → :443` redirect
already work. Open your existing site file:

```bash
sudo nano /etc/nginx/sites-available/cliniops
```

Paste the four directives from `deploy/nginx-minimal-patch.conf` inside the
existing `server { listen 443 ssl; ... }` block, then:

```bash
sudo nginx -t
```

Only if that passes:

```bash
sudo systemctl reload nginx
```

`deploy/nginx-cliniops.conf` is a full reference config if you ever want to
rebuild the file from scratch, but the patch above is the lower-risk path.

### 2. systemd — switch to gunicorn

Set `OMP_NUM_THREADS` in the unit to your core count (`nproc`) first.

```bash
sudo cp deploy/cliniops.service /etc/systemd/system/cliniops.service && sudo systemctl daemon-reload && sudo systemctl restart cliniops
```

```bash
sudo systemctl status cliniops --no-pager
```

The model takes 20–40 s to load, so the first request after a restart is slow.

### 3. Close port 5000

The app was listening on `0.0.0.0:5000` with `debug=True`, which exposes the
Werkzeug debugger — an unauthenticated remote shell for anyone who can reach
that port. The new unit binds to localhost; remove any inbound rule for 5000
from the security group as well. Only 80 and 443 need to be open.

## Verify

```bash
curl -s -o /dev/null -w '%{http_code}\n' -X POST https://cliniops.cloudhubs.nl/api/data/upload-file
```

Expect **401** — no token, correctly rejected. The old behaviour was 422.

```bash
head -c 2000000 /dev/urandom > /tmp/big.bin && curl -s -o /dev/null -w '%{http_code}\n' -X POST -F "files=@/tmp/big.bin" https://cliniops.cloudhubs.nl/api/data/upload-file; rm /tmp/big.bin
```

Expect **401**, not 413. A 413 means the nginx change has not taken effect.

Then in the browser: sign out, sign in, upload. DevTools → Application → Local
Storage should show a `token` key.

## Still outstanding

**Uploads are synchronous and slow.** Measured on this codebase, embedding runs
at about 1.1 s per 1000-character chunk on CPU:

| Document | Time |
|---|---|
| ~10 pages | ~56 s |
| ~40 pages | ~3.8 min |
| ~150 pages | ~14 min |

The 300 s timeouts cover most single files, but a batch will still exceed them,
and one upload occupies a thread for minutes. Moving ingestion to a background
job — accept the file, return `202` with a job id, poll for status — is the
durable fix. The ingestion loop is already per-file with a results list, so it
is a contained change.

**`app/config.py` hardcodes SQLite.** `SQLALCHEMY_DATABASE_URI =
"sqlite:///thinkly.db"` ignores the environment entirely. Survivable with one
gunicorn worker; `database is locked` as soon as there are two.

**Memory is tight.** The embedding model is ~1.3 GB resident per worker on a
3.7 GB host. Your current setup runs the Werkzeug reloader, so there are two
copies loaded. One gunicorn worker with threads fits; two workers will not.
