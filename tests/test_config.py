import json

from hermes_controller import config
from tests.helpers import HomeCase


class ConfigTest(HomeCase):
    def load(self):
        return config.load_settings(self.env, self.config_path)

    def test_reads_routes_and_lists(self):
        s = self.load()
        self.assertEqual(s.allowed_authors, ("tester",))
        self.assertEqual(s.route("testgate").prefix, "/qa")
        self.assertTrue(s.route("testgate").context)
        self.assertEqual(s.route("testgate").timeout, config.DEFAULT_PROJECT_TIMEOUT)
        self.assertEqual(s.requests_dir, self.home / "controller" / "requests")
        self.assertIsNone(s.route("nope"))

    def test_missing_file_is_an_error_not_a_default(self):
        self.config_path.unlink()
        with self.assertRaises(config.ConfigError) as ctx:
            self.load()
        self.assertEqual(ctx.exception.reason, config.CONFIG_MISSING)

    def test_bad_values_are_rejected(self):
        bad = [
            {"allowed_authors": []},
            {"allowed_repo_owners": "acme"},
            {"routes": []},
            {"routes": [{"name": "a b", "prefix": "/qa", "command": ["/bin/true"]}]},
            {"routes": [{"name": "a", "prefix": "qa", "command": ["/bin/true"]}]},
            {"routes": [{"name": "a", "prefix": "/qa", "command": ["true"]}]},
            {"routes": [{"name": "a", "prefix": "/qa", "command": ["/bin/true"]}, {"name": "a", "prefix": "/x", "command": ["/bin/true"]}]},
            {"routes": [{"name": "a", "prefix": "/qa", "command": ["/bin/true"], "timeout_seconds": 0}]},
            {"ced_taker_command": ["relative"]},
            {"github_app_url": "ftp://x"},
            {"github_app_secret_env": "bad name"},
            {"hermes_route": "a/b"},
        ]
        for override in bad:
            self.write_config(**override)
            with self.subTest(override=override), self.assertRaises(config.ConfigError):
                self.load()

    def test_unreadable_json(self):
        self.config_path.write_text("{")
        with self.assertRaises(config.ConfigError) as ctx:
            self.load()
        self.assertEqual(ctx.exception.reason, config.CONFIG_UNREADABLE)

    def test_errors_hold_no_paths(self):
        self.write_config(github_app_url="nope")
        with self.assertRaises(config.ConfigError) as ctx:
            self.load()
        self.assertNotIn(str(self.home), str(ctx.exception))
