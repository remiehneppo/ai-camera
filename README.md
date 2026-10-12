# AI Camera lab slice

This repository implements tracker ticket [#01](.scratch/system-build-slices/issues/01-event-synthetic-xuat-hien-tren-dashboard.md) and has a partial implementation of [#03](.scratch/system-build-slices/issues/03-doctor-va-config-fail-fast-qua-duong-chay-lab.md): persist and display a synthetic event, validate server configuration, and inspect lab server reachability. Analytics/model and recorder runtimes are not implemented.

## Run the lab stack

The MongoDB 7.0.43 service is a one-member replica set with a persistent Docker volume. This is a lab topology, not high availability. MongoDB 8.0.32 refused to start on this host's Linux 6.19 kernel, so the lab is pinned to the supported 7.0 line. Supply separate device and dashboard tokens through the environment; do not put tokens in source files:

```sh
export DEVICE_TOKENS='{"replace-with-device-token":"lab-edge-01"}'
export DASHBOARD_TOKEN='replace-with-dashboard-token'
# Optional: distinct reviewer identities and credentials for event decisions.
export REVIEWER_TOKENS='{"reviewer-1":"replace-with-reviewer-token-1","reviewer-2":"replace-with-reviewer-token-2"}'
docker compose up --build
```

After the server starts, validate the effective server configuration and probe MongoDB from inside the server container:

```sh
docker compose exec server python -m apps.server.doctor
```

The doctor prints a redacted config fingerprint that excludes credential values; rotating secrets alone does not change it. It reports analytics as disabled and recorder as unavailable until those runtimes exist.
The review API is disabled until `REVIEWER_TOKENS` is configured. Reviewer IDs are audit identities; bearer values are never returned or included in the config fingerprint.

The chosen perception baseline is ONNX Runtime CPU on x86 with file replay. Future RKNN support uses its own target artifact and the same `PerceptionPipeline` semantics; RTSP replaces the video source configuration without changing event contracts. These future paths still require their target conformance checks.

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

## Synthetic recorder evidence (#07)

Generate a cleared fixture, persist event/outbox/evidence intent atomically, and stream-copy a pinned clip:

```sh
ffmpeg -f lavfi -i testsrc=size=64x64:rate=10 -t 40 -c:v mpeg4 -g 10 /tmp/camera-fixture.mp4
DEVICE_ID=lab-edge-01 python -m apps.edge.send_synthetic --no-send \
  --record-file /tmp/camera-fixture.mp4 --anchor-time 10
```

Evidence requests live in the full event payload. Source-event-time anchor policy is pre10/post20; trigger time does not shift it. Ended replay sessions are persisted so recovery terminates incomplete evidence explicitly. Independent immutable MKV clips and manifests live under the recorder root; `EventOutbox.reconcile_evidence` retries durable intents and records per-request operational failures. Actual ranges are keyframe/segment aligned, not exact trims. Transfer receipt state is independent of completeness; actual server upload/playback is ticket #08.

## Software replay lab (#06/#07 follow-up)

Measure a small cleared video through fast, paced realtime and slow-callback replay:

```sh
python3 -m apps.edge.replay_lab /tmp/camera-fixture.mp4 \
  --sample-fps 5 --slow-callback-seconds 0.25 > /tmp/replay-lab-report.json
```

The JSON compares PTS/time-base/event-time traces, reports delivered counts, elapsed time and callback-completion lag, and queries raw coverage during every callback. Lag is relative to the first callback, excluding initial probing; last consumer event time is observed progress, not a queried recorder watermark. Raw is fully recorded before replay, not ingested concurrently. Temporary recorder artifacts are removed after the report. Input metadata and output traces are materialized, so use small fixtures.

This is **semantic transport evidence only**: no analytics/domain parity, realtime queue/drop stress, RTSP or hardware acceptance. Delayed-pin regressions use intentionally small lab retention values and real pruned segments; they do not establish approved maximum verification/handoff/recovery budgets. Tickets #06/#07 remain partial and #08 remains blocked.

## Checks

Run the local contract and SQLite tests with `python -m unittest discover -s tests`. MongoDB transaction, HTTP auth, and browser checks require the Compose lab to be running; they are separate from this unit suite.
