import json
import unittest

from apps.server.config import load_server_config


def valid_environment() -> dict[str, str]:
    return {
        "DEVICE_TOKENS": '{"device-secret":"lab-edge-01"}',
        "DASHBOARD_TOKEN": "dashboard-secret",
        "MONGO_URI": "mongodb://mongo:27017/?replicaSet=rs0",
        "MONGO_DATABASE": "camera_lab",
    }


class ServerConfigTests(unittest.TestCase):
    def test_config_is_immutable_and_fingerprint_omits_secret_values(self) -> None:
        first = load_server_config(valid_environment())
        env = valid_environment()
        env["DEVICE_TOKENS"] = json.dumps({"rotated-secret": "lab-edge-01"})
        env["DASHBOARD_TOKEN"] = "rotated-dashboard-secret"
        second = load_server_config(env)

        self.assertEqual(first.config_hash, second.config_hash)
        self.assertEqual(len(first.config_hash), 64)
        with self.assertRaises(TypeError):
            first.device_tokens["new-secret"] = "other-device"

    def test_invalid_required_field_fails_without_echoing_secret(self) -> None:
        env = valid_environment()
        env["DEVICE_TOKENS"] = '{"do-not-leak":""}'

        with self.assertRaisesRegex(ValueError, "DEVICE_TOKENS") as error:
            load_server_config(env)
        self.assertNotIn("do-not-leak", str(error.exception))

    def test_invalid_json_fails_with_field_name(self) -> None:
        env = valid_environment()
        env["DEVICE_TOKENS"] = "not-json"

        with self.assertRaisesRegex(ValueError, "DEVICE_TOKENS"):
            load_server_config(env)

    def test_connection_options_change_the_fingerprint(self) -> None:
        env = valid_environment()
        env["MONGO_URI"] = "mongodb://mongo:27017/?replicaSet=other"

        self.assertNotEqual(load_server_config(valid_environment()).config_hash, load_server_config(env).config_hash)

    def test_invalid_mongo_uri_error_does_not_echo_credentials(self) -> None:
        env = valid_environment()
        env["MONGO_URI"] = "mongodb://user:top-secret@mongo:27017/#fragment"

        with self.assertRaisesRegex(ValueError, "MONGO_URI") as error:
            load_server_config(env)
        self.assertNotIn("top-secret", str(error.exception))

    def test_reviewer_id_affects_hash_but_reviewer_secret_does_not(self) -> None:
        env = valid_environment()
        env["REVIEWER_TOKENS"] = '{"alice":"review-secret"}'
        first = load_server_config(env)
        env["REVIEWER_TOKENS"] = '{"alice":"rotated-secret"}'
        second = load_server_config(env)
        env["REVIEWER_TOKENS"] = '{"bob":"rotated-secret"}'
        third = load_server_config(env)

        self.assertEqual(first.config_hash, second.config_hash)
        self.assertNotEqual(second.config_hash, third.config_hash)
        with self.assertRaises(TypeError):
            first.reviewer_tokens["bob"] = "another-secret"

    def test_invalid_reviewer_tokens_fail_without_echoing_secret(self) -> None:
        env = valid_environment()
        env["REVIEWER_TOKENS"] = '{"alice":"do-not-leak","":""}'
        with self.assertRaisesRegex(ValueError, "REVIEWER_TOKENS") as error:
            load_server_config(env)
        self.assertNotIn("do-not-leak", str(error.exception))

    def test_reviewer_secret_cannot_reuse_device_credential(self) -> None:
        env = valid_environment()
        env["REVIEWER_TOKENS"] = '{"alice":"device-secret"}'
        with self.assertRaisesRegex(ValueError, "REVIEWER_TOKENS"):
            load_server_config(env)


if __name__ == "__main__":
    unittest.main()
