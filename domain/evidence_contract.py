"""Source-event-time evidence policy shared by journal and recorder worker."""

import math


def validate_storage_id(value):
    if (not isinstance(value, str) or not value or len(value) > 128
            or value in {".", ".."} or any(char in value for char in ("/", "\\", "\x00"))):
        raise ValueError("invalid evidence storage ID")
    return value


def make_evidence_request(request_id, session_id, anchor_kind, anchor_time, *,
                          mapping_uncertainty=0, supersedes_request_id=None):
    request = {
        "request_id": request_id, "session_id": session_id,
        "evidence_anchor_kind": anchor_kind, "evidence_anchor_time": anchor_time,
        "requested_start": anchor_time - 10, "requested_end": anchor_time + 20,
        "mapping_uncertainty": mapping_uncertainty, "policy_version": "lab-pre10-post20-v1",
        "supersedes_request_id": supersedes_request_id,
    }
    return validate_evidence_request(request)


def validate_evidence_request(request):
    if not isinstance(request, dict):
        raise ValueError("evidence request must be an object")
    fields = {"request_id", "session_id", "evidence_anchor_kind", "evidence_anchor_time",
              "requested_start", "requested_end", "mapping_uncertainty", "policy_version", "supersedes_request_id"}
    if request.keys() != fields:
        raise ValueError("invalid evidence request fields")
    for field in ("request_id", "session_id"):
        if not isinstance(request[field], str) or not request[field] or len(request[field]) > 128:
            raise ValueError(f"invalid {field}")
    if request["evidence_anchor_kind"] not in ("onset", "first_qualifying_observation", "synthetic"):
        raise ValueError("invalid evidence anchor kind")
    for field in ("evidence_anchor_time", "requested_start", "requested_end", "mapping_uncertainty"):
        value = request[field]
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError(f"invalid {field}")
    anchor = request["evidence_anchor_time"]
    if request["policy_version"] != "lab-pre10-post20-v1" or request["requested_start"] != anchor - 10 or request["requested_end"] != anchor + 20 or request["mapping_uncertainty"] < 0:
        raise ValueError("invalid evidence policy interval")
    supersedes = request["supersedes_request_id"]
    if supersedes is not None and (not isinstance(supersedes, str) or not supersedes or len(supersedes) > 128 or supersedes == request["request_id"]):
        raise ValueError("invalid supersedes_request_id")
    return dict(request)
