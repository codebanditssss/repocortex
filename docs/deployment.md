# Running the recovered demo

The complete demo uses Next.js, the Python ranker, and the already-restored
HydraDB on one host. Next proxies `/api/locate` and `/api/status` to Python;
Python connects to HydraDB. Only the Next web port needs public routing.

## Existing local instance

The recovered container is named `repocortex-recovered`, with Bolt bound to
`127.0.0.1:17687`. Keep it running and use its existing credentials. Configure
`HYDRADB_BACKEND=bolt` and `HYDRADB_BOLT_URI=bolt://127.0.0.1:17687` in the
repository's ignored `.env` or process environment, together with the matching
`HYDRADB_BOLT_PASSWORD`. Do not replace its token, rerun restoration, or start
the original compose stack over its data directory.

From the repository root, check the current Python and Next services:

```sh
.venv/bin/python scripts/serve_demo.py --check
```

The default ports are Python `8765` and Next `3101`. The check prints only
connection mode and connected state. `mode: live` and `connected: true` confirm
the graph check; replay mode is still usable but is not live graph scoring.

## Restarting the application services

Required artifacts are `data/corpus.json`, `data/embeddings.npz`,
`data/learned_state.json`, and `data/learned_state.npz`. Recover these artifacts
as described in [recovery.md](recovery.md); no retraining is needed. The Python
environment needs the project dependencies, and the embedding model must be
available in its existing cache or downloadable on initial startup.

Use Node.js 20.9 or newer. If dependencies or the production build are missing,
prepare them before starting services, in the `web` directory:

```sh
npm ci
npm run build
```

Do not rebuild into the same `.next` directory while a production Next server
is running from it. Build in a separate release checkout, or stop that server
first. Once the application's ports are free, run from the repository root:

```sh
.venv/bin/python scripts/serve_demo.py
```

The supervisor refuses occupied ports, waits for Python health, and starts
Next with `REPOCORTEX_API_URL` set to the chosen local Python port. Both bind
to loopback. Ctrl-C stops only its child services; HydraDB remains running.
Use `--api-port` and `--web-port` for alternative ports, and pass the same
options with `--check`. Launch with the project's virtualenv Python.

## Short-lived public demonstration

`cloudflared` is installed on the recovered host. A Quick Tunnel provides
a temporary demonstration URL:

```sh
cloudflared tunnel --url http://127.0.0.1:3101
```

Use the generated HTTPS URL and its `/app/locate` path. Keep the host awake and
the tunnel process running. Quick Tunnel URLs change on restart; this is not
durable hosting. Verify `/api/status`, submit one sample report, and open its
database query receipts before sharing the link.

The public endpoint accepts inference requests. For sustained public traffic,
put access controls or rate limiting in front of it; do not expose Bolt, the
Python port, or MCP learning endpoints. A durable deployment can use a single
VM/container host with persistent runtime files and HydraDB storage, plus an
HTTPS reverse proxy to Next. A frontend-only Vercel deployment cannot reach
this host's loopback Python service; it requires a separately reachable backend.

`ngrok`, `vercel`, and `railway` clients are also installed. Account access and
project targets have not been verified.

## Current Vercel frontend

The production website is https://repocortex.vercel.app. Its server-side
`REPOCORTEX_API_URL` points to the persistent Railway Python service. That
service connects to HydraDB over Railway private networking; the browser never
receives a Bolt URL or database credential. Fresh searches use the live graph,
while saved benchmark evidence remains available if the API is unavailable.
Verify `/api/status` reports `mode: live` and `connected: true` after every
deployment.
