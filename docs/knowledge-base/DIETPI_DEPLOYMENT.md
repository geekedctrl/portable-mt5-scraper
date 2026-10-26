# DietPi dev deployment

The portable images target Linux/amd64 and can run on the x86_64 Debian-based
DietPi VM. Transfer the exported `mt5scraper-image.tar` plus `compose.yaml`,
`.env.example`, and the optional `compose.slate-local.yaml` from the release
directory. The export contains images and public configuration only; it excludes
credentials, database volumes, and persisted MT5 terminal state.

## Load and configure

```sh
mkdir -p ~/mt5scraper-deploy
cd ~/mt5scraper-deploy
docker load -i mt5scraper-image.tar
cp .env.example .env
chmod 600 .env
nano .env
```

Set `MT5_LOGIN`, `MT5_PASSWORD`, and the exact `MT5_SERVER` in the private `.env`.
For the current dev performance test, set `LIVE_POLL_SECONDS=0.5`. The public
template retains the more conservative 1 second default. Leave resource limits
at core 4 CPU/4 GiB and dashboard 0.25 CPU/256 MiB unless deliberately changed.

## Connect to Slate's Docker network

The current VM network is `slate-dev_internal`. Set
`SLATE_DOCKER_NETWORK=slate-dev_internal` in `.env`, and verify the network exists:

```sh
docker network inspect slate-dev_internal
```

Validate Compose quietly and start Gateway with the optional network overlay:

```sh
docker compose --project-directory . -p mt5scraper-portable -f compose.yaml -f compose.slate-local.yaml config --quiet
docker compose --project-directory . -p mt5scraper-portable -f compose.yaml -f compose.slate-local.yaml up -d
```

This gives the dashboard/API the internal DNS alias
`mt5-market-provider:8080`. It does not configure Slate's application to consume
the API; that requires the separate Slate provider integration. To run Gateway
without the Slate network, omit `-f compose.slate-local.yaml` from both commands.

## Verify

```sh
docker compose --project-directory . -p mt5scraper-portable -f compose.yaml ps
curl http://127.0.0.1:8080/provider/v1/status
```

The status should report `ready: true` and a collector quote interval of `0.5`.
The dashboard and MT5 desktop ports bind to VM loopback; use an SSH tunnel for
browser access. The dashboard port can also be reached by containers on
`slate-dev_internal`. The provider API is read-only and supports status,
instrument discovery, batch quotes, and stored candle history.

Volumes are created by Docker Compose and are not part of the image archive.
Do not use `docker compose down -v` during upgrades; it removes market history
and saved MT5 state.
