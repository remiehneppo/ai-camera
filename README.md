# AI Camera lab slice

Implemented software-lab slices: synthetic event/dashboard (#01), lab facts/protocol (#02), versioned review with audit trail and re-review triggers (#04), retry/revision delivery (#05), file recorder/replay (#06), durable pinned evidence (#07), server evidence upload/playback (#08), process crash recovery (#09), pinned ONNX detector oracle (#11), Python ByteTracker with time/session semantics (#13), end-to-end perception pipeline baseline (#14), live runner (#15 partial), startup/shutdown (#16), truthful health monitor with operational fault surfacing (#17), storage quota protection (#18), dataset feedback lineage (#20), ODD image quality assessment and freeze detection (#21 partial), RTMPose-Tiny pose estimation (#22), track gap and clock jump handling (#23 partial), pose scheduling and degradation (#24), person fall detection (#25), and persistent lying (#26). Full Python test suite (445 tests) passes across edge, health, quota, pose, review API, and contracts. Native C++ acceleration (#10/#12), camera hardware RTSP field validation, and production target deployment acceptance (G3–G5) remain open as tracked in the [tracker](.scratch/system-build-slices/PRD.md).

## Run the lab stack

The MongoDB 7.0.43 service is a one-member replica set with a persistent Docker volume. This is a lab topology, not high availability. MongoDB >= 5.0 is strictly required because the backend event store relies on multi-document ACID transactions and the `$setWindowFields` aggregation operator in `list_current`. MongoDB 8.0.32 refused to start on this host's Linux 6.19 kernel, so the lab is pinned to the supported 7.0 line. Supply separate device and dashboard tokens through the environment; do not put tokens in source files:

```sh
export DEVICE_TOKENS='{"replace-with-device-token":"lab-edge-01"}'
export DASHBOARD_TOKEN='replace-with-dashboard-token'
# Optional: distinct reviewer identities and credentials for event decisions.
export REVIEWER_TOKENS='{"reviewer-1":"replace-with-reviewer-token-1","reviewer-2":"replace-with-reviewer-token-2"}'
docker compose up --build
```

Server evidence now uses the persistent `server-evidence` volume at the existing
`/tmp/ai-camera-evidence` path. Before recreating a server from an older stack,
copy its existing clips into that volume; adding a volume does not migrate the
old container's writable layer. Keep the original device/event directories so
stored MongoDB file paths remain valid. The image initializes the directory for
its non-root UID 10001. Python 3.12 matches the pinned NumPy/OpenCV lab runtime.

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

## Concurrent ring ingestion and incremental replay (#51)

`FileRecorder.ingest()` accepts an existing local file or named pipe and publishes each closed segment while ingestion continues. Query `segments()` / `actual_range()` and create pins during the context; post-roll remains `collecting` until coverage arrives. On exit, call `finalize_pin()` after coverage or pass `allow_partial=True` to retain an honest partial receipt. Existing segment data is reconciled after a crash between media rename and sidecar commit. Remote URLs, including RTSP, are intentionally rejected here so credentials cannot reach ffmpeg argv; no live camera integration is implemented.

`replay()` streams ffprobe frame timestamps as CSV with synchronous callback backpressure and advances watermark only after each successful callback. It does not retain a Python frame list. Synthetic 320×180 H.264 measurements at 10–10,000 seconds delivered the first callback before ffprobe EOF in all 12 runs; sampled Python and ffprobe RSS did not grow proportionally with duration in that envelope. This is evidence for incremental replay, not a process-wide memory guarantee. Closed-segment metadata probing separately materializes JSON per segment. Replay remains file-based, not a reconnecting camera session or live analytics pipeline.

`FileRecorder(..., probe_timeout_seconds=30)` sets a configurable operational safety budget: metadata probes have a wall-time limit; replay waits for subprocess output have an inactivity limit that excludes callback work and realtime pacing. Timeout/system/unknown probe failures preserve unclassified media for retry. Only recognized premature-EOF or malformed-header diagnostics permit removal; unpublished preserved parts are not queryable ring data. Publisher shutdown waits are bounded after producer exit, but a stuck filesystem operation may leave a daemon publisher running. These limits are not production SLOs; see [hardening evidence](docs/logs/2026-10-13-ticket-51-hardening.md).

The #51 regression tests use a synthetic Matroska FIFO to hold the producer open while querying/pinning, then exercise kill, crash-window reconciliation and consumer failure. These software tests do not establish camera session limits, RTSP ownership, timestamp uncertainty, reconnect/codec-change behavior, target performance, or G1 acceptance. See [ticket #51](.scratch/system-build-slices/issues/51-live-ring-publish-segments-during-ingest.md) and [implementation evidence](docs/logs/2026-10-12-ticket-51.md).

## Software replay lab (#06/#07 follow-up)

Measure a small cleared video through fast, paced realtime and slow-callback replay:

```sh
python3 -m apps.edge.replay_lab /tmp/camera-fixture.mp4 \
  --sample-fps 5 --slow-callback-seconds 0.25 > /tmp/replay-lab-report.json
```

The JSON compares PTS/time-base/event-time traces, reports delivered counts, elapsed time and callback-completion lag, and queries raw coverage during every callback. Lag is relative to the first callback, excluding initial probing; last consumer event time is observed progress, not a queried recorder watermark. Raw is fully recorded before replay, not ingested concurrently. Temporary recorder artifacts are removed after the report. Replay timestamp metadata is streamed; this diagnostic accumulates output traces, so use small fixtures.

This is **semantic transport evidence only**: no analytics/domain parity, realtime queue/drop stress, RTSP or hardware acceptance. Delayed-pin regressions use intentionally small lab retention values and real pruned segments; they do not establish approved maximum verification/handoff/recovery budgets. Tickets #06/#07 remain partial and #08 remains blocked.

## ONNX detector oracle lab (#11)

Use a separate optional CPU runtime (Python 3.12 was tested):

```sh
python3 -m venv .venv-oracle
.venv-oracle/bin/pip install -r requirements-oracle.txt
.venv-oracle/bin/python -m tools.fetch_oracle_assets
.venv-oracle/bin/python -m tools.oracle_conformance
```

The fetch command verifies exact model/photo SHA-256 and byte counts from versioned manifests; large artifacts stay under ignored `data/oracle/`. YOLOX-Tiny uses the approved `0.1.1rc0` ONNX binary, but measured preprocessing is **raw BGR 0–255**, not the old release tag's RGB/ImageNet normalization. Pixel replay yields RGB; the detector converts to BGR once. Preprocessing source and the old per-class NMS source are pinned separately in the manifest/attribution. Candidate scores are `>0.1`, final scores `>=0.30`, and inclusive-pixel per-class NMS uses `0.45`.

Create a short cleared clip, then run metadata-only output from actual decoded pixels:

```sh
ffmpeg -loop 1 -i data/oracle/shibuya_people.jpg -t 0.6 -r 5 \
  -c:v ffv1 /tmp/oracle-fixture.mkv
.venv-oracle/bin/python -m apps.edge.oracle_replay \
  --video /tmp/oracle-fixture.mkv \
  --manifest models/yolox-tiny/manifest.json \
  --model data/oracle/yolox_tiny.onnx --sample-fps 5 \
  > /tmp/oracle-report.json
```

Reports carry source/model/config/runtime identity, original-coordinate detections, transforms, PTS/event-time and stage timings. Valid empty output is `ok_empty`; invalid input/output or inference is `failed`, never a negative detection. Fast and paced replay share source-time sampling. Decoder/probe waits are bounded; timestamp inventory is disk-spooled, while JSON observations accumulate in memory, so use small lab clips. Source/artifact mutation during a run is rejected by before/after fingerprint checks; this is not filesystem snapshot isolation.

Golden fixtures are generated by an independent attributed reference, not production preprocessing/postprocessing. Comparisons require exact identity/status/labels/counts and absolute bbox/score tolerances `1e-3` pixels / `1e-6`. `--record` explicitly replaces golden evidence and is not needed for normal verification. Numeric tests use a separate synthetic identity and explicitly pinned generated ONNX bytes; the lab path accepts only the approved real model.

**Lab authorization is not production clearance.** Source Apache-2.0 attribution is retained; exact released-weight/training-data rights and privacy/personality clearance remain unresolved. See `models/yolox-tiny/ATTRIBUTION.md`. This detector-stage oracle does not implement native/RKNN, tracking/pose, a full application `PerceptionPipeline`, notifications, or target/field quality acceptance.

## Detector–recorder and pin-budget diagnostic reports (#06/#07)

Compare real ONNX detections and raw coverage across fast/paced replay using the small oracle fixture above:

```sh
.venv-oracle/bin/python -m apps.edge.oracle_recorder_lab \
  --video /tmp/oracle-fixture.mkv --manifest models/yolox-tiny/manifest.json \
  --model data/oracle/yolox_tiny.onnx --sample-fps 5 > /tmp/detector-recorder-report.json
```

The synchronous observation callback completes before consumer progress advances. Reports compare detector identity/status/provenance and bbox/score tolerances, keep inference failure distinct from valid empty output, and query copied raw coverage after consumption. Raw is pre-recorded; this is not domain/event parity or concurrent ingestion isolation.

Exercise a caller-supplied source-time delay scenario with the 40-second camera fixture:

```sh
python3 -m apps.edge.pin_budget_lab /tmp/camera-fixture.mp4 \
  --ring-seconds 40 --anchor-time 12 --verification-seconds 15 \
  --handoff-seconds 5 --recovery-seconds 5 --margin-seconds 1 \
  > /tmp/pin-budget-report.json
```

This scenario persists an intent, prunes before first pin, restarts the recorder/outbox, then reconciles at explicit EOF. Theoretical requirement is caller delay + pre10 + caller margin, separate from actual keyframe-aligned coverage. These values are **scenarios, not approved or measured verification/handoff/recovery maxima or RTO**. Ring8 in this example produces partial pre-roll; anchor0 with verification15/handoff10/recovery12 and ring8 produces known `missing` request coverage with a failed build and `unknown` artifact completeness (there is no artifact).

Both diagnostics remove temporary artifacts after reporting; use small fixtures. Neither establishes live RTSP, bounded queue/drop stress, target/storage sizing, power-cut, production clearance or evidence upload/playback acceptance. #06/#07 remain partial; #08 remains blocked.

## Benchmark dataset and pipeline performance suite

An automated benchmark suite profiles the complete edge perception pipeline against real 1080p surveillance video footage (`shibuya_crossing_1080p.mp4` for pedestrian flow and `intersection_traffic_1080p.mp4` for vehicle traffic, under CC BY-SA 4.0).

1. Download and verify the benchmark dataset (assets pinned by SHA-256 in `data/benchmark/manifest.json`):
```sh
python3 tools/fetch_benchmark_dataset.py
```

2. Run the automated pipeline benchmark (measures Baseline vs Full Pipeline with RTMPose-Tiny):
```sh
.venv-oracle/bin/python tools/run_benchmark.py --max-frames 120 --sample-fps 10.0
```

### Measured performance summary (Intel Core i5-12400F, ONNX Runtime CPU):

| Scenario (1080p) | Configuration | Throughput (FPS) | Median Latency (P50) | Peak RAM (RSS) |
| :--- | :--- | :---: | :---: | :---: |
| **Shibuya Crossing** | **Baseline (YOLOX + ByteTrack)** | **20.10 FPS** | **44.79 ms** | **266.7 MB** |
| **Shibuya Crossing** | **Full Pipeline + RTMPose** | **8.84 FPS** | **89.50 ms** | **519.8 MB** (Pose: 3.73 ms/person) |
| **Intersection Traffic** | **Baseline (YOLOX + ByteTrack)** | **16.35 FPS** | **56.25 ms** | **334.9 MB** |
| **Intersection Traffic** | **Full Pipeline + RTMPose** | **10.56 FPS** | **83.77 ms** | **530.4 MB** (Pose: 3.84 ms/person) |

Detailed breakdown of per-stage latencies (decode, preprocess, inference, NMS, tracking, pose) is recorded in [Pipeline Benchmark Report](docs/reports/2026-10-21-pipeline-benchmark-report.md).

## Server and edge behavior notes

- `GET /api/events` is cursor-paginated: `limit` is 1-100 and the response carries `events`, `next_cursor` and `review_enabled`. Pass `next_cursor` back as `cursor` for the next page; a malformed cursor is rejected with 422.
- Evidence upload is streamed to a temporary file with a rolling sha256 and then linked into place; a clip larger than `MAX_EVIDENCE_BYTES` (100 MiB, `apps/server/main.py`) is rejected with 413. Treat this ceiling as provisional until target bitrate sizing is signed off.
- `deliver_pending` retries network errors, HTTP 5xx and 429 with capped exponential backoff and jitter; other 4xx responses fail immediately.
- RTSP loss does not switch the live runner to the fallback permanently: the reconnect loop retries with capped backoff, and the stream session, recorder session and health session stay equal across source changes. A lost frame is reported as a missing observation, never as a synthetic image.
- Tracks start `tentative` and become `active` after `activate_after` consecutive hits (default 2); `person_lying_persistent` anchors on the first stationary observation.
- An unreleased pin is never created for a request refused for storage; released and acknowledged pins have their manifests reclaimed by `cleanup_storage`.

Full change record: `docs/logs/2026-10-15-implement-dispatch-summary.md` and `docs/logs/2026-10-15-code-review-of-implementation.md`.

## Checks

Run the entire test suite with pytest using the oracle lab environment:
```sh
.venv-oracle/bin/python -m pytest -q
```
All **445 tests** across edge perception, tracking, fall incident engine, RTMPose estimation, ODD quality assessment, health monitoring, storage quota, server review API, and event contracts pass.

Run the local contract and SQLite tests with `python -m unittest discover -s tests`. MongoDB transaction, HTTP auth, and browser checks require the Compose lab to be running; they are separate from this unit suite.
