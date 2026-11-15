# Persistent backend on Railway

The Vercel frontend stays at `repocortex.vercel.app`. Run two Railway services
in the same project/environment:

- **hydradb**: `deploy/hydradb.Dockerfile`, private networking only, persistent
  volume at `/data`. Set `HYDRADB_AUTH_TOKEN` to a new private random token.
  Do not publish its Bolt, administration, or HTTP ports.
- **api**: `deploy/backend.Dockerfile`, public HTTPS domain targeting `$PORT`.
  Set `HOST=0.0.0.0`, `HYDRADB_BACKEND=bolt`,
  `HYDRADB_BOLT_URI=bolt://hydradb.railway.internal:7687`, and
  `HYDRADB_BOLT_PASSWORD` to the same token. Use the actual private hostname
  supplied by Railway if the database service has another name.

The existing snapshot needs about 535 MiB for HydraDB and 650 MiB for Python
at idle on the recovered host. Plan for at least 1 GiB per service and verify
peak memory under traffic. These are observations, not hosting cost estimates.
The database occupies about 53 MiB; allocate persistent storage with headroom.

## Restore without retraining

Supply only the existing `corpus.json`, `embeddings.npz`, `learned_state.json`,
and `learned_state.npz` to the API's `/app/data` directory using the deployment
staging instructions below. Never include `.env`, worker credentials, local auth
files, or the local database directory in a build context.

For a volume-backed deployment, mount a second volume at `/app/data` on the API
service and use Railway's volume file upload to copy exactly those four files.
Alternatively, build the `with-runtime` target from a private staging directory
containing `runtime/` with those four files. The default `app` image intentionally
contains no runtime. Do not commit the staging directory to Git.

Set the Dockerfile path for each service explicitly. The API health endpoint is
`/health`; the database readiness endpoint is `/readyz` on its internal HTTP port
9090. A fresh database has no corpus, so the API will be unhealthy until restoration
finishes. Run the one-time restore command in the API service container (or a
separate job from the same image with the same private connection variables).

After the private database is ready, run inside the API container:

```sh
python scripts/restore_graph.py --apply
```

This restores the checked-in graph export only into an empty, dedicated
instance. It refuses existing project nodes. It is an explicit one-time action,
not a startup command; do not reset a database to make it pass.

Verify API `/health` reports `mode: live` and `connected: true`, then perform a
sample `/locate` request and inspect its query receipts. Only after these pass,
set Vercel's production `REPOCORTEX_API_URL` to the new API HTTPS origin and
redeploy. Test the public Vercel search before retiring the laptop tunnel.

Provisioning still requires a signed-in hosting account and sufficient plan
resources. Check the account's actual costs/credits before creating services.
