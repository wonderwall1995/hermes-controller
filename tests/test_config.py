"""설정(config.py) 시험. 시험 자료는 모두 가짜다."""

import json
import pathlib
import tempfile
import unittest

from hermes_controller import config
from hermes_controller.config import ConfigError, load_settings


class ConfigCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = pathlib.Path(tmp.name)
        self.path = self.dir / "config.json"
        self.env = {"HERMES_HOME": str(self.dir / "home")}

    def write(self, data):
        self.path.write_text(json.dumps(data), encoding="utf-8")

    def load(self, **kw):
        return load_settings(env=self.env, config_path=kw.get("config_path", self.path))

    def reason(self, data=None, raw=None):
        if raw is not None:
            self.path.write_text(raw, encoding="utf-8")
        else:
            self.write(data)
        with self.assertRaises(ConfigError) as ctx:
            self.load()
        return ctx.exception.reason


class DefaultsTest(ConfigCase):
    def test_no_file_gives_the_defaults_and_makes_no_explanation(self):
        got = self.load()
        home = self.dir / "home"
        self.assertEqual(got.wrapper_command, (str(home / "testgate" / "testgate-run"),))
        self.assertEqual(got.ced_command, ())
        self.assertEqual((got.github_app_url, got.secret_env), (config.DEFAULT_GITHUB_APP_URL, config.DEFAULT_SECRET_ENV))
        self.assertEqual((got.github_timeout, got.ced_timeout), (15, 20))
        self.assertEqual(got.requests_dir, home / "testgate" / "requests")

    def test_an_empty_object_is_the_same_as_no_file(self):
        self.write({})
        self.assertEqual(self.load(), config.fallback_settings(self.env))

    def test_hermes_home_defaults_to_dot_hermes_in_the_home_folder(self):
        self.assertEqual(config.hermes_home({}), pathlib.Path("~/.hermes").expanduser())
        self.assertEqual(config.hermes_home({"HERMES_HOME": "  "}), pathlib.Path("~/.hermes").expanduser())

    def test_log_path_is_under_the_home_logs_folder(self):
        self.assertEqual(config.log_path(self.env), self.dir / "home" / "logs" / "controller.log")

    def test_config_path_can_come_from_the_environment(self):
        self.write({"github_timeout_seconds": 7})
        env = dict(self.env, **{config.ENV_CONFIG: str(self.path)})
        self.assertEqual(load_settings(env=env).github_timeout, 7)


class ValidTest(ConfigCase):
    def test_full_config(self):
        self.write({
            "wrapper_command": ["/opt/tg/run", "--x"], "ced_taker_command": ["/opt/ced/bin/ced-taker", "provide"],
            "github_app_url": "http://localhost:3300/", "github_app_secret_env": "MY_KEY",
            "github_timeout_seconds": 5, "ced_timeout_seconds": 30,
        })
        got = self.load()
        self.assertEqual(got.wrapper_command, ("/opt/tg/run", "--x"))
        self.assertEqual(got.ced_command, ("/opt/ced/bin/ced-taker", "provide"))
        self.assertEqual((got.github_app_url, got.secret_env), ("http://localhost:3300", "MY_KEY"))
        self.assertEqual((got.github_timeout, got.ced_timeout), (5, 30))

    def test_unknown_keys_are_ignored(self):
        self.write({"future": [1], "ced_taker_command": ["/x/ced", "provide"]})
        self.assertEqual(self.load().ced_command, ("/x/ced", "provide"))

    def test_https_url_is_allowed(self):
        self.write({"github_app_url": "https://example.test:8443"})
        self.assertEqual(self.load().github_app_url, "https://example.test:8443")


class InvalidTest(ConfigCase):
    def test_unreadable_files(self):
        for raw in ("", "{", "[]", "5", "null"):
            with self.subTest(raw=raw):
                self.assertEqual(self.reason(raw=raw), config.CONFIG_UNREADABLE)
        self.path.write_bytes(b"\xff\xfe")
        with self.assertRaises(ConfigError) as ctx:
            self.load()
        self.assertEqual(ctx.exception.reason, config.CONFIG_UNREADABLE)

    def test_commands_must_be_a_list_with_an_absolute_first_item(self):
        for key in ("wrapper_command", "ced_taker_command"):
            for bad in ([], "/x/run", ["run"], ["./run"], ["/x/run", ""], ["/x/run", 5], None, {"a": 1}, 5):
                with self.subTest(key=key, bad=bad):
                    self.assertEqual(self.reason({key: bad}), config.CONFIG_INVALID)

    def test_url_must_be_http_or_https_with_a_host(self):
        for bad in ("", "localhost:3200", "ftp://x", "file:///etc/passwd", "http://", "http://a b", "http://h/path", 5, None):
            with self.subTest(bad=bad):
                self.assertEqual(self.reason({"github_app_url": bad}), config.CONFIG_INVALID)

    def test_secret_env_must_be_a_variable_name_never_a_value(self):
        for bad in ("", "has space", "1START", "a-b", "a=b", 5, None):
            with self.subTest(bad=bad):
                self.assertEqual(self.reason({"github_app_secret_env": bad}), config.CONFIG_INVALID)

    def test_timeouts_must_be_positive_integers_within_a_limit(self):
        for key in ("github_timeout_seconds", "ced_timeout_seconds"):
            for bad in (0, -1, 1.5, "5", True, None, config.MAX_TIMEOUT + 1):
                with self.subTest(key=key, bad=bad):
                    self.assertEqual(self.reason({key: bad}), config.CONFIG_INVALID)

    def test_errors_never_contain_paths_or_values(self):
        self.write({"github_app_secret_env": "top secret value"})
        with self.assertRaises(ConfigError) as ctx:
            self.load()
        self.assertNotIn("secret", str(ctx.exception))
        self.assertNotIn(str(self.dir), str(ctx.exception))


class FallbackTest(ConfigCase):
    def test_fallback_runs_the_standard_wrapper_and_makes_no_explanation(self):
        got = config.fallback_settings(self.env)
        self.assertEqual(got.ced_command, ())
        self.assertEqual(got.wrapper_command, config.default_wrapper_command(self.env))


if __name__ == "__main__":
    unittest.main()
