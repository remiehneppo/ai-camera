# CiviWatch (`civi-watch`) — Urban Safety Edge AI Platform

## Project overview

CiviWatch is a Python reference for suspected urban-safety incidents from fixed CCTV, retained evidence and versioned human review. The configured feature modules share perception and snapshot construction while keeping their own temporal state.

The current code baseline is `17d9a32`. It registers US01–US14, but a registered scenario is not proof of camera configuration, quality acceptance or production readiness. The default feature verifiers run offline. Ground-plane templates are not site calibration, and historical benchmark numbers do not establish current target capacity.

Read the [current status and evidence](docs/README.md#trạng-thái-đối-chiếu-tại-17d9a32) before using a report as acceptance evidence. The target ODD is fixed traffic CCTV at 720p–1080p; dashcams and low-resolution streams are outside it.

## Architecture and layout

| Path | Responsibility |
|---|---|
| `domain/` | Event/config/model contracts and scenario registry |
| `apps/edge/pipeline.py` | Shared perception, feature dispatch and candidate verification |
| `apps/edge/snapshot.py` | Validated snapshot construction and evidence-request policy |
| `apps/edge/evidence.py`, `outbox.py`, `recorder.py` | Local persistence, evidence lifecycle and raw retention |
| `apps/server/` | Ingest, review, retrieval and dashboard |
| `tools/` | Replay, diagnostics, dataset preparation and scoped benchmarks |
| `docs/architecture/`, `docs/adr/` | Current implementation descriptions and recorded decisions |

[CONTEXT.md](CONTEXT.md) defines domain terms. [ADR-0005](docs/adr/0005-incident-snapshot-ownership.md) and [ADR-0006](docs/adr/0006-semantic-replay-pipeline-reuse.md) fix snapshot/replay ownership; [ADR-0008](docs/adr/0008-civiwatch-v2-hybrid-vlm-architecture.md) records v2 design intent. [ADR-0007](docs/adr/0007-rtsp-stream-ownership.md) remains proposed. The [current architecture](docs/architecture/system-architecture.md) separates implemented paths from those decisions and open acceptance work.

## Prerequisites and pinned runtimes

- Python 3.12 and the dependencies in `requirements-oracle-test.txt` for the full local check environment
- FFmpeg/ffprobe for recorder and video diagnostics
- Docker Compose for the MongoDB/server/go2rtc lab: MongoDB `7.0.43-jammy`, Python `3.12-slim`, digest-pinned go2rtc `1.9.15`
- Cleared model/video fixtures for the commands that reference them; software smoke on synthetic pixels does not establish ODD acceptance

## Development commands

| Task | Command |
|---|---|
| Run the lab | `docker compose up --build` after setting the required environment |
| Build the server image | `docker compose build server` |
| Check types | `.venv-oracle/bin/python -m mypy domain/ apps/ tools/` |
| Run the full test suite | `.venv-oracle/bin/python -m pytest -q -ra` |
| Inspect evaluator options | `.venv-oracle/bin/python tools/eval_all_scenarios.py --help` |
| Validate the media change spec | `openspec validate fix-civiwatch-media-control-auth --strict` |

There is no configured standalone lint command in the root build/lint configuration. Do not report lint or a target-native build as passing from the Python checks.

## Environment variables

Use [`.env.local.example`](.env.local.example) as a placeholder inventory and inject actual credentials outside source control. Required media credentials have no default.

| Variables | Purpose |
|---|---|
| `DEVICE_TOKENS`, `DASHBOARD_TOKEN` | Device identities and dashboard access |
| `REVIEWER_TOKENS` | Optional reviewer identities; required to enable review decisions |
| `GO2RTC_API_USER`, `GO2RTC_API_PASSWORD` | Native media control authentication and matching edge-adapter credentials |
| `DEVICE_ID`, `DEVICE_TOKEN`, `API_URL` | Synthetic edge sender configuration |
| `ALLOW_INSECURE_LAB` | Explicit loopback HTTP allowance; remove beyond the lab |

An explicitly selected remote `VLMVerifier` can read `CIVIWATCH_VLM_URL` and `CIVIWATCH_VLM_API_KEY`. Default feature verifiers remain offline; setting an endpoint variable alone does not prove that a remote verifier is selected. Remote-image egress requires the applicable data/residency approval.

## Run the lab stack

The MongoDB 7.0.43 service is a one-member replica set with a persistent Docker volume. This is a lab topology, not high availability. MongoDB >= 5.0 is strictly required because the backend event store relies on multi-document ACID transactions and the `$setWindowFields` aggregation operator in `list_current`. MongoDB 8.0.32 refused to start on this host's Linux 6.19 kernel, so the lab is pinned to the supported 7.0 line. Supply separate device and dashboard tokens through the environment; do not put tokens in source files:

```sh
export DEVICE_TOKENS='{"replace-with-device-token":"lab-edge-01"}'
export DASHBOARD_TOKEN='replace-with-dashboard-token'
# Optional: distinct reviewer identities and credentials for event decisions.
export REVIEWER_TOKENS='{"reviewer-1":"replace-with-reviewer-token-1","reviewer-2":"replace-with-reviewer-token-2"}'
# Required: separate go2rtc control credentials, injected through the operator's secret environment.
# Set GO2RTC_API_USER and GO2RTC_API_PASSWORD before starting Compose; no defaults are provided.
docker compose up --build
```

Server evidence now uses the persistent `server-evidence` volume at the existing
`/tmp/civi-watch-evidence` path. Before recreating a server from an older stack,
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

The media control API uses the digest-pinned official `alexxit/go2rtc:1.9.15` image.
Compose rejects missing `GO2RTC_API_USER` or `GO2RTC_API_PASSWORD`; inject both from your
secret environment (placeholder names are in `.env.local.example`). The edge media adapter
uses those same variables for Basic authentication, including loopback requests, and does
not forward credentials across redirects to a different origin. Keep this HTTP API on
loopback or an isolated trusted network; Basic authentication does not encrypt credentials.
Do not broaden the bind address without a separate TLS/network access policy.

`infra/go2rtc.yaml` rejects foreign WebSocket origins and excludes administrative
exit/restart/config routes from its allowlist. Public video fixtures must exist at
`data/benchmark/intersection_traffic_1080p.mp4` and `data/benchmark/shibuya_crossing_1080p.mp4`;
Compose mounts them under `/app/data/benchmark/`. See the
[permission-boundary spec](openspec/changes/fix-civiwatch-media-control-auth/proposal.md)
and [verification log](docs/logs/2026-11-11-review-remediation.md).

Dashboard taxonomy filters use emitted leaf values, not scenario factory names. Clearing
tokens removes both storage copies, event cards, evidence/download URLs and live media;
token query parameters are consumed and removed from the address bar. Missing schedule
state is not presented as inactive.

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

Evidence requests live in the full event payload. Source-event-time policy is pre10/post20; trigger time does not shift it. Ended replay sessions are persisted so recovery terminates incomplete evidence explicitly. Immutable MKV clips/manifests live under the recorder root; `EvidenceLifecycle` coordinates intent, pin, finalize and reconciliation. Actual ranges are keyframe/segment aligned, not exact trims. Transfer receipt state is independent of completeness. Server upload/playback exists separately; see [current readiness](docs/architecture/deployment-readiness.md) for its acceptance limits.

## Concurrent ring ingestion and incremental replay (#51)

`FileRecorder.ingest()` accepts an existing local file or named pipe and publishes each closed segment while ingestion continues. Query `segments()` / `actual_range()` and create pins during the context; post-roll remains `collecting` until coverage arrives. On exit, call `finalize_pin()` after coverage or pass `allow_partial=True` to retain an honest partial receipt. Existing segment data is reconciled after a crash between media rename and sidecar commit. This file-ingest interface rejects remote URLs, including RTSP; the separate `RtspRingRecorder` / `LivePerceptionRunner` path owns live capture and still needs its field acceptance.

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

This diagnostic supplies semantic transport evidence only: it does not establish analytics/domain parity, realtime queue/drop stress, RTSP or hardware acceptance. Delayed-pin regressions use intentionally small lab retention values and real pruned segments; they do not establish approved maximum verification/handoff/recovery budgets. Check the [current readiness](docs/architecture/deployment-readiness.md) and tracker rather than deriving ticket completion from this diagnostic.

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

Both diagnostics remove temporary artifacts after reporting; use small fixtures. Neither establishes live RTSP, bounded queue/drop stress, target/storage sizing, power-cut, production clearance or evidence upload/playback acceptance. The separate upload/review implementation and its remaining acceptance work are tracked in [deployment readiness](docs/architecture/deployment-readiness.md).

## Benchmark dataset and pipeline performance suite

The profiling tool processes the pinned 1080p replay clips `shibuya_crossing_1080p.mp4` and `intersection_traffic_1080p.mp4`. Treat each result according to its recorded model, configuration, hardware and timing scope; it is not a full edge/evidence acceptance run.

1. Download and verify the benchmark dataset (assets pinned by SHA-256 in `data/benchmark/manifest.json`):
```sh
python3 tools/fetch_benchmark_dataset.py
```

2. Run the automated pipeline benchmark (measures Baseline vs Full Pipeline with RTMPose-Tiny):
```sh
.venv-oracle/bin/python tools/run_benchmark.py --max-frames 120 --sample-fps 10.0
```

The [2026-10-21 pipeline profiling report](docs/reports/2026-10-21-pipeline-benchmark-report.md) records historical CPU measurements. The v2 and remediation changes alter model choices, matching and timing/error handling; do not reuse an older FPS table as current capacity evidence. Use [deployment readiness](docs/architecture/deployment-readiness.md) for the measurements and sign-off still required.

`run_benchmark.py` and the other replay tools share the deep `tools/replay_runner.py` module, which unifies video decode validation, source-derived rational timestamps, ephemeral SQLite lifecycle, and fail-fast detection checks across all evaluators. Use its timings as perception-pipeline diagnostic profiling only, not full edge capacity or hardware acceptance.

## Server and edge behavior notes

- `GET /v1/events` is cursor-paginated: `limit` is 1-100 and the response carries `events`, `next_cursor` and `review_enabled`. Pass `next_cursor` back as `cursor` for the next page; a malformed cursor is rejected with 422.
- Evidence upload is streamed to a temporary file with a rolling sha256 and then linked into place; a clip larger than `MAX_EVIDENCE_BYTES` (100 MiB, `apps/server/main.py`) is rejected with 413. Treat this ceiling as provisional until target bitrate sizing is signed off.
- `deliver_pending` retries network errors, HTTP 5xx and 429 with capped exponential backoff and jitter; other 4xx responses fail immediately.
- RTSP loss does not switch the live runner to the fallback permanently: the reconnect loop retries with capped backoff, and the stream session, recorder session and health session stay equal across source changes. A lost frame is reported as a missing observation, never as a synthetic image.
- Tracks start `tentative` and become `active` after `activate_after` consecutive hits (default 2); `person_lying_persistent` anchors on the first stationary observation.
- An unreleased pin is never created for a request refused for storage; released and acknowledged pins have their manifests reclaimed by `cleanup_storage`.

Full change record: `docs/logs/2026-10-15-implement-dispatch-summary.md` and `docs/logs/2026-10-15-code-review-of-implementation.md`.

## Independent module x camera configuration (#03 delta slice)

Edge doctor reads operator configuration for each alert module on each camera and reports
what is actually configured per camera:

```sh
.venv-oracle/bin/python -m apps.edge.doctor --config edge.json --module-config modules.json
```

`modules.json` declares each module's allowlisted `factory` (ADR-0001) plus per-camera
configuration, and an optional `session`. Without `session` a document is only staged and
reported as `not_activated`; with `session` each camera is activated at that boundary and
reported as `enabled`/`disabled`:

```json
{"session": "lab-session-1",
 "modules": [{"module": "person_down", "config_version": "person-down-v1",
              "factory": "person_down",
              "required_fields": ["roi"], "thresholds": ["min_score"],
              "cameras": {"cam-01": {"version": 1, "enabled": true,
                                      "roi": [[[0.1,0.1],[0.9,0.1],[0.9,0.9]]],
                                      "thresholds": {"min_score": 0.4}},
                          "cam-02": {"version": 1, "enabled": false,
                                      "disabled_reason": "capability not cleared for site"}}}]}
```

An enabled module missing a required field, an unknown field, a non-list `required_fields`/
`thresholds`, a non-allowlisted factory, or a field that looks like secret material stops
preflight with exit code 1 and an error naming module/camera/field; the offending value is
never echoed. `capabilities.modules` reports `enabled`/`disabled`/`not_activated` plus reason,
config hash and `perception_groups` — modules that declare the same `perception_profile` on one
camera are reported as one shared decode/inference group instead of two. Registration records
configuration only, not concurrent capacity.

`--start` hands the registry to `EdgeRuntime`: analytics starts only for an activated enabled camera module. Disabled reasons remain visible in status. The live/replay pipeline consumes activated module configuration, including ROI and schedule, through the registry/composition path. [Ticket #57](.scratch/system-build-slices/issues/57-vung-nguy-hiem-module-camera-e2e.md) records the danger-zone carrier implementation and remaining acceptance scope; a registry entry alone does not establish active camera coverage.

## Retained-evidence retrieval (#32)

A reviewer can ask one device to retain a clip; the device receives the request on an
outbound command channel and the requester sees `pending`/`offline`/`expired`/
`completed`/`failed`. The command payload is a closed field set — any `argv`, `shell`,
`script`, `url` or `exec` shaped field is refused, so the channel is never a remote shell.

```sh
# reviewer asks the edge to retain the clip for one evidence request
curl -X POST -H "Authorization: Bearer $REVIEWER_TOKEN" -H 'Content-Type: application/json' \
     -d '{"target": "edge", "ttl_seconds": 300}' \
     "$SERVER/v1/evidence/lab-edge-01/$EVENT/req-001/retrieval"

# the device long-polls its own command channel (device bearer token)
curl -H "Authorization: Bearer $DEVICE_TOKEN" "$SERVER/v1/devices/lab-edge-01/commands?wait=2"

# the requester watches the outcome
curl -H "Authorization: Bearer $REVIEWER_TOKEN" "$SERVER/v1/retrieval/$COMMAND_ID"
```

Semantics enforced by `domain/retrieval_contract.py` and covered by tests:

- `claim` is idempotent while the lease is alive (same lease, no extra attempt) and a
  completed command is never re-issued, so a retried poll cannot duplicate work.
- `metadata` acknowledgement records receipt only: the command stays open and the clip is
  **not** released, deleted or expired. Only an `artifact` acknowledgement (sha256 + size)
  completes it, and repeating the same bytes is idempotent while different bytes conflict.
- A command claimed or acknowledged after `expires_at` cannot complete; a target that the
  server fulfils itself (`target: "server"`) settles from live availability, so retention
  cleanup that removed the clip ends as `failed: evidence_unavailable` and the manifest
  receipt survives.

`apps/edge/retrieval.py` is the device side: `RetrievalWorker` validates each payload,
records the metadata acknowledgement, runs an injected executor (`RecorderClipRetainer` for
an edge clip, idempotent per request id) and closes the command with the artifact or an
allowlisted failure. A device only fulfils what this build implements: a command for another
`target`, or a `retention_scope` other than `clip`, is refused with `unsupported_target` /
`retention_scope_unsupported` instead of running the wrong executor. `retention_scope:
"metadata"` is rejected at issue time (422) until a real metadata-only retention path exists,
so no artifact is ever fabricated for it.

## Inbound storm guard (#41)

A malformed flood must not consume the state reserve, and it must not be silent either.
`domain/storm_guard.py` keeps a rolling window of ingest outcomes, spends a separate
malformed budget, and keeps a **bounded** ring of forensic samples:

- `admit()` turns false once the malformed budget is spent; `POST /v1/events` then answers
  `429` with `Retry-After` and persists nothing.
- `duplicate`, `accepted` and `unavailable` never spend that budget and never create a
  forensic sample, so a retrying edge cannot starve legitimate traffic while a unique storm
  shows up as `truncated` + `degraded`.
- Samples hold only a flat, length-bounded detail (never the payload), and the ring reports
  `dropped_samples` when it rolls over.

```sh
curl -H "Authorization: Bearer $DASHBOARD_TOKEN" "$SERVER/v1/ingest/guard"
# -> counts per outcome, budget_spent/remaining, degraded, truncated, dropped_samples, forensics
curl "$SERVER/healthz"   # -> {"status": "ok"|"degraded", "ingest_guard": {...}}
```

The guard carries a fixed lab budget — 50 malformed attempts per 60s window and 8 forensic
samples — and is not a signed production SLA; changing it is a code change, not a config knob.

## Synthetic probe and operational fault (#40)

A probe walks `decode → inference → journal → delivery` through injected stage callables,
checkpoints each stage in a bounded ledger, and reports a **stall** as an operational fault
carrying its own metric, window, threshold, owner, runbook and recovery:

```python
from apps.edge.probe import SyntheticProbe
from domain.probe_contract import ProbeLedger

report = SyntheticProbe(ProbeLedger(), {
    "decode": decode_once, "inference": infer_once,
    "journal": append_once, "delivery": deliver_once,
}, reporter=health.record_probe_faults).run()
```

```json
{"taxonomy": "operational_fault", "ok": false, "stopped_at": "journal",
 "faults": [{"code": "probe_journal_stalled", "stage": "journal",
             "metric": "probe_journal_age_seconds", "window_seconds": 300.0,
             "threshold_seconds": 120.0, "owner": "edge-ops",
             "runbook": "docs/architecture/contracts.md#operational-fault",
             "recovery": "restart the journal stage, then re-run the synthetic probe",
             "observed": {"last_progress_at": null, "age_seconds": null, "checkpoints": 0}}]}
```

Properties that keep a fault from becoming an incident:

- the probe holds no outbox, incident engine or transport reference (an import-level test
  pins this), and a report is not a valid event at all — `validate_event(report)` refuses it;
- stage names and fault codes are closed enumerations, so metric label cardinality is
  bounded by construction; the failure reason is the exception **type**, never its message;
- `EdgeHealthMonitor.record_probe_faults()` folds the fault codes into
  `operational_faults`, so health degrades and `all_reasons` names the stalled stage;
- `origin=synthetic` stays `ineligible` in the outbox for **every** revision, with a reason
  (`synthetic_or_replay_origin`) that a revision cannot rewrite.

## Datasets and evaluation tools

Which video datasets are worth using (license, verified access, measured results, what each one may and
may not be used to sign) lives in the [dataset register](docs/datasets/video-datasets.md). Media stays
out of git — only paths, sizes and hashes are recorded.

| Tool | Purpose |
|---|---|
| `tools/eval_clip.py` | Run the full edge pipeline over one or more clips and report detections, incident events, pose outcomes and latency |
| `tools/eval_vehicle.py` | Shared pipeline with vehicle-only policy; CLI speed/deceleration defaults 20/150, direct-call defaults 8/50 |
| `tools/eval_all_scenarios.py` | Shared pipeline with Person-down, vehicle, parking and crowd policies; pose enabled unless `--no-pose` |
| `tools/run_benchmark.py` | Throughput/latency benchmark; `--video <clip>` benchmarks a fetched dataset clip without editing the code |
| `tools/a3d_labels.py` | Turn A3D per-frame accident labels into a clip label set (needs the external id mapping; never guesses) |
| `tools/negative_audit_report.py` | Stratified negative audit / Horvitz-Thompson recall report for G2 |
| `tools/oracle_conformance.py` | Detector oracle conformance against golden fixtures |
| `tools/fetch_benchmark_dataset.py`, `tools/fetch_oracle_assets.py` | Download and verify the bundled benchmark clips and oracle artifacts |

All three evaluators call `PerceptionPipeline.process_frame`, create a new replay session and temporary
local recorder/outbox per clip, and never deliver events or media over the network. Reports include
effective tracker/feature/pose configuration. Vehicle and multi-scenario replay retain tracker
thresholds 0.25/0.08/0.3 rather than the pipeline defaults used by `eval_clip`.

```sh
.venv-oracle/bin/python tools/eval_vehicle.py --video /path/to/clip.mp4 --max-frames 30
.venv-oracle/bin/python tools/eval_all_scenarios.py --videos /path/to/clip.mp4 --max-frames 30 --no-pose
.venv-oracle/bin/python tools/eval_clip.py --video /path/to/clip.mp4 --max-frames 30
```

`eval_all_scenarios` preserves CLI/direct frame limits 200/300, vehicle policy 15/120, parking dwell
20 seconds and crowd count/duration 5/3; effective pose processing queue/batch budget remains 30.
`eval_clip` defaults to all sampled frames (`--max-frames 0`) with pose off. Detection statuses outside
`ok`/`ok_empty` fail the run after pipeline status/gap handling; pose degradation remains separate.
Explicit missing paths fail; unavailable auto-selected corpus paths retain existing skip behavior.
Captures and temporary storage are cleaned up on errors as well as success.

Extended evaluation reports US04, US10 and US14 as unconfigured: it does not construct their specialized camera engines/ROI, and the current CLI has no option to enable them. Source-frame timestamps are used by these evaluators and the corrected `tools/compare_models_benchmark.py`; the legacy profiler caveat above is separate. The model comparison measures perception only, excluding continuous recording, evidence packaging and WAN upload. Failed observations cannot produce a completed result or measured performance claim.

`tools/train_civiwatch_detector.py --dry-run` writes separately named blueprint artifacts
and preserves an existing active `manifest.json` and model. Without CUDA, normal training
fails instead of silently generating a deployment. YOLOX COCO preparation regenerates
annotations from current labels and refuses to replace unmanaged destination directories.

Where latency is reported, `latency_scope` identifies `process_frame` **including local snapshot
persistence**, excluding decode, sampling, model startup and network. This scope is not directly
comparable with historical evaluator timings. Zero events means zero emitted snapshots—not a reviewed
negative, complete Evidence, quality gate or target-hardware acceptance. See the
[implementation evidence](docs/logs/2026-10-29-architecture-deepening-review.md#replay-integration-review-corrections-and-cli-smoke).

## Checks

Run static type checking and the entire test suite using the oracle lab environment:
```sh
.venv-oracle/bin/python -m mypy domain/ apps/ tools/
.venv-oracle/bin/python -m pytest -q
```
The [current status index](docs/README.md#trạng-thái-đối-chiếu-tại-17d9a32) links the full-suite, typecheck and smoke evidence for this code baseline. These software-lab checks do not establish camera calibration, target capacity or deployment acceptance.

Run the local contract and SQLite tests with `python -m unittest discover -s tests`. MongoDB transaction, HTTP auth, and browser checks require the Compose lab to be running; they are separate from this unit suite.
