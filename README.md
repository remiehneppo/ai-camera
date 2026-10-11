# AI Camera lab slice

This repository currently implements tracker ticket [#01](.scratch/system-build-slices/issues/01-event-synthetic-xuat-hien-tren-dashboard.md): persist one synthetic event and its delivery intent on edge, commit its full snapshot on the server, then display metadata from the API.

## Run the lab stack

The MongoDB 7.0.43 service is a one-member replica set with a persistent Docker volume. This is a lab topology, not high availability. MongoDB 8.0.32 refused to start on this host's Linux 6.19 kernel, so the lab is pinned to the supported 7.0 line. Supply separate device and dashboard tokens through the environment; do not put tokens in source files:

```sh
export DEVICE_TOKENS='{"replace-with-device-token":"lab-edge-01"}'
export DASHBOARD_TOKEN='replace-with-dashboard-token'
docker compose up --build
```

The server binds to loopback on port 8000. Open `http://127.0.0.1:8000`, choose **Set dashboard token**, and enter `DASHBOARD_TOKEN`.

In another shell, use the same device token and ID:

```sh
export DEVICE_ID='lab-edge-01'
export DEVICE_TOKEN='replace-with-device-token'
export API_URL='http://127.0.0.1:8000'
export ALLOW_INSECURE_LAB=1
python -m apps.edge.send_synthetic
```

The edge SQLite database defaults to `data/edge-events.sqlite3`. Event and outbox rows commit in one SQLite transaction with WAL and full synchronous durability. A delivery failure leaves the same message pending; rerun the command to retry pending entries without creating another event. A successful run with no pending work creates one fresh fixture. Remove `ALLOW_INSECURE_LAB` and use an HTTPS ingress before sending beyond loopback. MongoDB is not published to the host.

The server authenticates each device token to one `device_id`, rejects mismatches, enforces a 256 KiB event body limit, validates the versioned snapshot, and commits the immutable revision, higher-only current projection, and ineligible downstream decision in one majority-journaled Mongo transaction. Identical retries return the stored receipt; the same identity with different content returns conflict. Synthetic and replay events never become notification work.

## Checks

Run the local contract and SQLite tests with `python -m unittest discover -s tests`. MongoDB transaction, HTTP auth, and browser checks require the Compose lab to be running; they are separate from this unit suite.
