# Self-hosting KVsim v2

This guide runs Krabville as three isolated Docker Compose services on a
64-bit Linux host. ARM64 and x86-64 are supported. Four CPU cores, 4 GB RAM,
and 10 GB of free storage are a comfortable baseline for a live season.

## 1. Prepare the host

Install Docker Engine with the Compose plugin, Git, and curl. Clone the public
repository and create writable runtime directories:

```bash
git clone https://github.com/n30nex/Krabville.git
cd Krabville
cp deploy/.env.example deploy/.env
mkdir -p runtime/data runtime/control deploy/secrets
chmod 700 runtime deploy/secrets
openssl rand -base64 48 > deploy/secrets/voter-secret
chmod 600 deploy/secrets/voter-secret
```

Edit `deploy/.env`:

- Set `KRABVILLE_UID` and `KRABVILLE_GID` from `id -u` and `id -g`.
- Set `KRABVILLE_PUBLIC_ORIGIN` to the exact external origin, without a
  trailing slash.
- Keep `KRABVILLE_BIND_ADDRESS=127.0.0.1` when using a reverse proxy.
- Keep `KRABVILLE_FAKE_PROVIDER=true` until the deterministic smoke test is
  complete.
- Choose model aliases and budgets that your Codex account can use.

Do not commit `deploy/.env`, `deploy/secrets`, `runtime`, reports, databases, or
Codex credentials. They are excluded by Git and the Docker build context.

## 2. Build and smoke-test

The self-host override publishes only the web service to loopback. The engine,
database, control socket, and inference worker remain private.

```bash
docker compose -f compose.yaml -f compose.selfhost.yaml --env-file deploy/.env build --pull
docker compose -f compose.yaml -f compose.selfhost.yaml --env-file deploy/.env run --rm migrate
docker compose -f compose.yaml -f compose.selfhost.yaml --env-file deploy/.env up -d web engine
curl -fsS http://127.0.0.1:18889/healthz
```

Start a disposable fake-provider season before enabling paid or subscription
inference:

```bash
docker compose -f compose.yaml -f compose.selfhost.yaml --env-file deploy/.env run --rm engine krabville-manage start
docker compose -f compose.yaml -f compose.selfhost.yaml --env-file deploy/.env --profile inference up -d inference
docker compose -f compose.yaml -f compose.selfhost.yaml --env-file deploy/.env ps
```

## 3. Add your own Codex login

Install the current Codex CLI on the host using OpenAI's
[standalone installer](https://developers.openai.com/codex/cli):

```bash
curl -fsSL https://chatgpt.com/codex/install.sh | sh
```

The container cannot use a desktop keyring, so follow OpenAI's
[Codex authentication guidance](https://developers.openai.com/codex/auth) and configure file-backed
credentials in `~/.codex/config.toml` before signing in:

```toml
cli_auth_credentials_store = "file"
```

On a headless server, use device-code login and verify it:

```bash
codex login --device-auth
codex login status
```

Set these absolute host paths in `deploy/.env`:

```dotenv
KRABVILLE_CODEX_BIN_HOST=/home/your-user/.codex/bin/codex
KRABVILLE_CODEX_AUTH_HOST=/home/your-user/.codex/auth.json
KRABVILLE_FAKE_PROVIDER=false
```

Resolve the actual binary path with `readlink -f "$(command -v codex)"` if
your installer used a different location. The OAuth file is mounted read-only,
copied into the inference container's private temporary home, and never reaches
the web or engine services. Treat `auth.json` like a password.

Recreate only the inference service:

```bash
docker compose -f compose.yaml -f compose.selfhost.yaml --env-file deploy/.env --profile inference up -d --force-recreate inference
docker compose -f compose.yaml -f compose.selfhost.yaml --env-file deploy/.env logs --tail 100 inference
```

## 4. Put it behind HTTPS

Proxy the configured public hostname to `http://127.0.0.1:18889`. Preserve
streaming for `/api/v3/events/stream`, disable proxy buffering there, and do
not cache `/api/*`. Keep direct host access bound to loopback unless you have a
separate firewall and authentication boundary.

The only public write is the CSRF-protected, rate-limited poll vote endpoint.
The control socket is never published over HTTP.

## 5. Start the real campaign

After the fake-provider smoke test, stop and remove its runtime database if it
is disposable, initialize a clean one, set the intended season limits, and
start Season 1:

```bash
docker compose -f compose.yaml -f compose.selfhost.yaml --env-file deploy/.env down
rm -f runtime/data/krabville.db runtime/data/krabville.db-shm runtime/data/krabville.db-wal
docker compose -f compose.yaml -f compose.selfhost.yaml --env-file deploy/.env run --rm migrate
docker compose -f compose.yaml -f compose.selfhost.yaml --env-file deploy/.env run --rm engine krabville-manage start
docker compose -f compose.yaml -f compose.selfhost.yaml --env-file deploy/.env --profile inference up -d
curl -fsS http://127.0.0.1:18889/healthz
```

Only run the database-removal step for an explicitly disposable test world.
See [OPERATIONS.md](OPERATIONS.md) for upgrades, backups, diagnostics, and
rollback.
