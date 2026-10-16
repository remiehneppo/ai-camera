# Server restart

User requested restart of app server. Identified local run_server.py launcher PID 3787172 and apps.server.main:app uvicorn PID 3787181 on port 8000. Unrelated open_webui port 8080 service left untouched. CodeGraph context queried for server health; readiness verified at HTTP root.

Sent SIGTERM to verified app child; it stopped serving but did not exit in 10 seconds. Verified same identity and used SIGKILL for stalled child. Prior process environment was unreadable, so relaunch used existing run_server.py defaults/current environment. First relaunch accidentally resolved venv Python symlink to system Python and failed importing pymongo; corrected to absolute virtualenv executable path without symlink resolution (no dependency install or code change).

Final launcher PID 2975 via /home/tieubaoca/AI/AI-Camera-OC/.venv-oracle/bin/python run_server.py. Readiness: http://127.0.0.1:8000/ returned HTTP 200. Process output: /tmp/ai-camera-server-restart.log. No database readiness claim made.
