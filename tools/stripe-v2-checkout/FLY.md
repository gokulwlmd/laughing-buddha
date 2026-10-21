# Fly.io deployment

The private campaign/SKU checkout is deployed at `https://wlmd-stripe-test-0f89b1bb.fly.dev`. Use `/checkout/{campaign_id}/{url_encoded_sku}` with the existing owner invitation/cookie. The app is in organization `personal`, region `iad`, with one machine `84e117f290dd38` and encrypted 1 GB volume `vol_40o3gdk37mo7zy24` (`checkout_data`). Both Sticky application secrets are deployed and verified. Do not recreate these resources for an update.

The original $2 checkout's durable receipt is order 505015. Its subsequent Sticky read-back reported status 6; see README.md for the evidence and limits. The migration retains this receipt. Campaign/SKU URLs can start another purchase through an explicit button after completion; the old receipt remains stored and each new attempt has its own state. Preserve the purchase_successors table as well as purchase/checkouts. Current deployment digest and validation are recorded in `deployment.json` (public metadata only).

## Image and persistent state

`Dockerfile` copies only the application, static files, runtime requirements and entrypoint. `.dockerignore` excludes local state, credentials, tests and unrelated project files. The entrypoint prepares `/data`, then drops to UID/GID 10001 before running Uvicorn. Source ownership is set explicitly so private workspace file modes do not prevent the service from reading its code.

The SQLite record and invitation live on a persistent `checkout_data` volume. Use one machine and one Uvicorn worker; do not scale horizontally. Keep the machine running during the payment test because stopping discards the in-memory client secret. Preserve its volume through updates and reconcile an open payment after a restart rather than starting another payment.

Local verification passed: the image starts as UID 10001, `/health` returns running, unauthenticated page access returns 401, and the private page serves the Stripe form. The invitation and a SQLite marker both survive a container restart with the same mounted volume. The build trust bundle and proxy variables are absent at runtime. This check used no Sticky/Fly application credentials and made no payment requests. The disposable smoke-test container and volume were removed afterward.

Build locally from this directory:

```sh
python3 build_image.py
```

The helper uses the environment's existing HTTP proxy and resolves its hostname for the container build. The public trust bundle is mounted as a BuildKit secret during installation; it is not retained in the image. TLS verification stays enabled. No application credentials are build arguments or image contents. Normal builders without a proxy can use `docker build -t wlmd-stripe-checkout:fly-test .`.

## Fly authentication and application secrets

Fly CLI 0.4.120 is installed at `/workspace/scratch/flyctl/flyctl`. Its official release archive was verified against the release SHA-256 checksum `ef9b938ff3af2b28fad961a676e5ac2295124ad0b892ffb1c5f16a03bd4ee378`.

Set `FLY_CONFIG_DIR=/workspace/scratch/fly-config` and `DOCKER_CONFIG=/workspace/scratch/docker-config` when invoking the tools from this environment. Reuse a provided `FLY_API_TOKEN`; never put its value in source, command arguments, reports or chat. First verify `flyctl auth whoami` and inspect available organizations before selecting the deployment organization. A token that can only deploy an existing app cannot provision a new app/volume.

The hosted app separately needs these **Fly app secrets**:

- `STICKY_API_USERNAME`
- `STICKY_API_PASSWORD`

The owner supplied both through their authenticated local CLI, and hosted API read-back verified they work. Do not request them again during normal updates. Manage rotations through Fly's secure secret controls. The cloud Sticky bindings remain scoped to HTTPS requests to `whitelabelmd.sticky.io`; do not copy proxy placeholders to Fly or extract their underlying values. No Stripe private key is required for this Sticky-managed flow.

## Provision and deploy after authentication

Initial provisioning is complete. The following records the provisioning commands; do not repeat them for this app. Run future management commands from this directory using the installed `flyctl` path (or add that directory to PATH).

```sh
flyctl apps create wlmd-stripe-test-0f89b1bb --org personal
flyctl volumes create checkout_data --app wlmd-stripe-test-0f89b1bb --region iad --size 1 --yes
flyctl config validate --config fly.toml
```

For an authorized future update, inspect both the legacy purchase and all checkouts states first. Do not restart a payment that is awaiting card confirmation or capture. Build using `build_image.py`, then upload through this workspace's HTTPS proxy:

```sh
python3 build_image.py
python3 push_image.py
flyctl deploy --config fly.toml --image registry.fly.io/wlmd-stripe-test-0f89b1bb:checkout-2usd --ha=false --strategy immediate --yes
```

`push_image.py` exports the tested local image, verifies its layer digests, and uses standard registry chunked HTTPS uploads with the bound Fly token. Ordinary Docker push failed because its authentication context did not survive this environment's credential proxy; large single-request uploads also failed. Chunked requests worked, and the uploaded manifest was read back and verified. The helper never prints the token or embeds credentials in the image. The first deployment used the verified digest above; prefer the helper's returned immutable digest when updating.

Fly's authenticated config validation passed, one machine and its persistent mount were confirmed, the health check passed, and public HTTPS plus authenticated fixture read-back worked. Fly CLI emitted a UDP DNS-check warning because direct DNS is unavailable in this cloud environment; HTTPS verification through the supported proxy succeeded. This was not an application readiness failure.

Verify the deployed `/health`, unauthenticated page rejection, the retained legacy receipt, and authenticated read-only `/api/config?campaign_id=ID&sku=SKU` after opening that checkout page. An optional `/api/quote` only calculates and stores a quote; it must never be followed by automated authorization/capture as a health check. Obtain and deliver that invitation through an owner-only channel without logging it. Do not make an automated real-card request or capture as a health check. The owner completed the original browser flow; the generalized campaign/SKU changes have offline and read-only verification, without another live charge.
