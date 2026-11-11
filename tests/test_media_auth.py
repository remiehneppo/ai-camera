"""Behavioral tests for Go2RtcMediaEngine authentication, credential isolation, and redirect safety.

Verifies:
1. Basic Auth credentials sent via HTTP Authorization header to protected endpoints without URL embedding.
2. Cross-origin (including cross-port) redirects do not forward Authorization credentials.
3. Explicit username/password produce credential-free endpoints and repr.
4. Embedded userinfo in base_url is rejected with a generic ValueError without leaking secrets.
5. Environment variable fallback (GO2RTC_API_USER, GO2RTC_API_PASSWORD) authenticates requests.
"""
from __future__ import annotations

import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import threading
import unittest
from urllib.error import HTTPError

from apps.edge.media_engine import Go2RtcMediaEngine


class _TestHttpServer:
    def __init__(self, handler_cls: type[BaseHTTPRequestHandler]) -> None:
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
        self.port = self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def shutdown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2.0)


def _make_auth_handler(expected_user: str, expected_pass: str) -> type[BaseHTTPRequestHandler]:
    expected_token = base64.b64encode(f"{expected_user}:{expected_pass}".encode("utf-8")).decode("ascii")

    class ProtectedHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            auth = self.headers.get("Authorization", "")
            if auth != f"Basic {expected_token}":
                self.send_response(401)
                self.send_header("WWW-Authenticate", 'Basic realm="go2rtc"')
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"Unauthorized")
                return

            if self.path == "/api/streams":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"cam1": {"producers": []}}).encode("utf-8"))
            elif self.path.startswith("/api/frame.jpeg"):
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.end_headers()
                self.wfile.write(b"\xff\xd8\xff\xe0valid-jpeg")
            elif self.path.startswith("/api/stream.mp4"):
                self.send_response(200)
                self.send_header("Content-Type", "video/mp4")
                self.end_headers()
                self.wfile.write(b"\x00\x00\x00\x18ftypmp42")
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            pass

    return ProtectedHandler


class MediaAuthBehavioralTests(unittest.TestCase):
    def test_basic_auth_sent_to_protected_endpoints(self) -> None:
        srv = _TestHttpServer(_make_auth_handler("testuser", "testpass"))
        srv.start()
        try:
            engine = Go2RtcMediaEngine(
                base_url=f"http://127.0.0.1:{srv.port}",
                username="testuser",
                password="testpass",
            )
            probe = engine.probe_streams()
            self.assertEqual(probe["status"], "available")
            self.assertEqual(probe["stream_count"], 1)

            jpeg = engine.fetch_snapshot_jpeg("cam1")
            self.assertEqual(jpeg, b"\xff\xd8\xff\xe0valid-jpeg")

            clip = engine.extract_evidence_clip(
                "cam1",
                request_id="req-auth-1",
                session_id="sess-auth-1",
                start_seconds=0.0,
                end_seconds=5.0,
            )
            self.assertEqual(clip["status"], "complete")
            self.assertEqual(clip["provider"], "go2rtc")

            engine_bad = Go2RtcMediaEngine(
                base_url=f"http://127.0.0.1:{srv.port}",
                username="testuser",
                password="wrong-password",
            )
            probe_bad = engine_bad.probe_streams()
            self.assertEqual(probe_bad["status"], "standalone_fallback")
            self.assertEqual(probe_bad["reason"], "HTTPError")
        finally:
            srv.shutdown()

    def test_authorization_header_not_forwarded_on_cross_origin_redirect(self) -> None:
        """Credentials must not be forwarded across cross-origin (including cross-port) redirects."""
        server_b_auth_headers: list[str | None] = []

        class TargetServerB(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                server_b_auth_headers.append(self.headers.get("Authorization"))
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.end_headers()
                self.wfile.write(b"\xff\xd8\xff\xe0redirected-jpeg")

            def log_message(self, format: str, *args: object) -> None:
                pass

        srv_b = _TestHttpServer(TargetServerB)
        srv_b.start()

        class OriginServerA(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                auth = self.headers.get("Authorization", "")
                if not auth.startswith("Basic "):
                    self.send_response(401)
                    self.end_headers()
                    return
                self.send_response(302)
                self.send_header("Location", f"http://127.0.0.1:{srv_b.port}/sink/frame.jpeg")
                self.end_headers()

            def log_message(self, format: str, *args: object) -> None:
                pass

        srv_a = _TestHttpServer(OriginServerA)
        srv_a.start()

        try:
            engine = Go2RtcMediaEngine(
                base_url=f"http://127.0.0.1:{srv_a.port}",
                username="secretuser",
                password="secretpassword",
            )
            try:
                data = engine.fetch_snapshot_jpeg("cam1")
                self.assertEqual(data, b"\xff\xd8\xff\xe0redirected-jpeg")
                self.assertEqual(len(server_b_auth_headers), 1)
                self.assertIsNone(server_b_auth_headers[0])
            except HTTPError:
                self.assertEqual(len(server_b_auth_headers), 0)
        finally:
            srv_a.shutdown()
            srv_b.shutdown()

    def test_credentials_not_embedded_in_urls_or_repr(self) -> None:
        """Explicit credentials must never appear in StreamEndpointInfo URLs or engine repr."""
        user = "explicit-user"
        secret = "very-confidential-secret"
        engine = Go2RtcMediaEngine(
            base_url="http://127.0.0.1:1984",
            username=user,
            password=secret,
        )
        info = engine.endpoints_for_camera("cam-01")
        all_urls = [
            info.webrtc_url,
            info.mjpeg_url,
            info.mp4_clip_url,
            info.snapshot_url,
            info.rtsp_relay_url,
        ]
        for url in all_urls:
            self.assertNotIn(user, url)
            self.assertNotIn(secret, url)
            _, _, rest = url.partition("://")
            host_and_path = rest.split("/")[0]
            self.assertNotIn("@", host_and_path)

        repr_str = repr(engine)
        self.assertNotIn(user, repr_str)
        self.assertNotIn(secret, repr_str)

    def test_userinfo_in_base_url_rejected_without_secret_leak(self) -> None:
        """Passing credentials via base_url must fail with a generic ValueError without echoing secrets."""
        secret = "embedded-secret-password"
        with self.assertRaises(ValueError) as ctx:
            Go2RtcMediaEngine(base_url=f"http://admin:{secret}@127.0.0.1:1984")
        self.assertNotIn(secret, str(ctx.exception))
        self.assertNotIn("admin", str(ctx.exception))

    def test_env_var_credential_fallback_authenticates_requests(self) -> None:
        srv = _TestHttpServer(_make_auth_handler("env_user", "env_pass"))
        srv.start()
        old_u = os.environ.get("GO2RTC_API_USER")
        old_p = os.environ.get("GO2RTC_API_PASSWORD")
        os.environ["GO2RTC_API_USER"] = "env_user"
        os.environ["GO2RTC_API_PASSWORD"] = "env_pass"
        try:
            engine = Go2RtcMediaEngine(base_url=f"http://127.0.0.1:{srv.port}")
            probe = engine.probe_streams()
            self.assertEqual(probe["status"], "available")
            self.assertEqual(probe["stream_count"], 1)
        finally:
            srv.shutdown()
            if old_u is not None:
                os.environ["GO2RTC_API_USER"] = old_u
            else:
                os.environ.pop("GO2RTC_API_USER", None)
            if old_p is not None:
                os.environ["GO2RTC_API_PASSWORD"] = old_p
            else:
                os.environ.pop("GO2RTC_API_PASSWORD", None)


if __name__ == "__main__":
    unittest.main()
