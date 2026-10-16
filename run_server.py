"""Run AI Camera OC Server."""
import os
import subprocess
import sys

env = os.environ.copy()
env.setdefault("ALLOW_INSECURE_LAB", "1")
env.setdefault("MONGO_URI", "mongodb://192.168.96.2:27017/?replicaSet=rs0&directConnection=true")
env.setdefault("MONGO_DATABASE", "camera_lab")
env.setdefault("DEVICE_TOKENS", '{"fixture-device-token":"lab-edge-01"}')
env.setdefault("DASHBOARD_TOKEN", "fixture-dashboard-token")
env.setdefault("REVIEWER_TOKENS", '{"reviewer-1":"fixture-review-token-1","reviewer-2":"fixture-review-token-2"}')
env.setdefault("EVIDENCE_DIR", "/tmp/ai-camera-evidence")

if __name__ == "__main__":
    cmd = [sys.executable, "-m", "uvicorn", "apps.server.main:app", "--host", "0.0.0.0", "--port", "8000"]
    sys.exit(subprocess.run(cmd, env=env).returncode)
