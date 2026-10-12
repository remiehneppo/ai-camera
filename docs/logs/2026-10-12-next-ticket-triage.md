# Next-ticket triage — 2026-10-12

- User asked which ticket can proceed while deferring #08; this is a recommendation, not authorization to implement or change gates.
- Read local ticket execution/dependencies across all 50 system-build-slices issues and acceptance of #11. Individual ticket files are authoritative; #05 is done despite stale PRD row.
- #01/#02/#05 done, #06/#07 partial, #03 blocked. Among not-started tickets, #11 is the dependency-ready candidate: its only blocker #02 is done; #11 is ready-for-agent. #08 need not be completed first.
- Recommend #11 ONNX oracle canonical detections with model/runtime/pre-post/labels/hash provenance, original-coordinate boxes, empty vs invalid distinction, versioned golden fixture hashes/tolerances. Exact artifact and cleared fixture availability must be verified before implementation; no readiness claim about those assets yet.
- #10 still blocked by #03/#06; #12 by #10/#11; #20 by #04/#08; #29 by #11 and target facts. Defer #08 without marking it done, removing dependencies, or claiming downstream readiness.
- No source changes, tests, model downloads, ticket claims, or implementation delegation in this triage.
