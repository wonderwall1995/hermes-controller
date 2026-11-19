"""파이프라인(pipeline.py)과 명령(cli.py) 시험.

github-app, ced-taker, testgate 래퍼는 모두 가짜이다. 실제 문서와 실제 키는 쓰지 않는다.
시험 자료에는 "기록에 나오면 안 되는 표식"을 심어서, 내용이 기록에 새지 않는지 확인한다.
"""

import json
import logging
import os
import pathlib
import stat
import subprocess
import sys
import tempfile
import time
import unittest

from hermes_controller import cli, config, contextfile, pipeline
from hermes_controller.cedtaker import CedTakerError
from tests.test_githubapp import SECRET, Fake, ServerCase

ROOT = pathlib.Path(__file__).resolve().parent.parent
QA_SENTINEL = "SENTINEL_QA_9f3a"
TITLE_SENTINEL = "SENTINEL_TITLE_9f3a"
DIFF_SENTINEL = "SENTINEL_DIFF_9f3a"
DOC_SENTINEL = "SENTINEL_DOC_9f3a"
EXC_SENTINEL = "SENTINEL_EXC_9f3a"
SECRET_ENV = "UNIT_TEST_APP_KEY"

CED_SCRIPT = r'''
import json, sys
request = json.loads(sys.stdin.read())
record, mode = sys.argv[1], sys.argv[2]
open(record, "w").write(json.dumps(request))
if mode == "ok":
    print(json.dumps({"version": 1, "docs": [{"id": "ced:amount", "title": "CED 해설: amount", "text": "SENTINEL_DOC_9f3a 금액의 뜻"}], "notices": ["안내 하나"]}))
elif mode == "empty":
    print(json.dumps({"version": 1, "docs": [], "notices": []}))
elif mode == "exit":
    sys.stderr.write("공급자의 오류 문장"); sys.exit(3)
elif mode == "huge":
    print(json.dumps({"version": 1, "docs": [{"id": "a", "title": "t", "text": "가" * 600000}, {"id": "b", "title": "t", "text": "가" * 600000}], "notices": []}))
'''

REQUEST = {"deliveryId": "d-1", "repo": "acme/shop", "pr": 7, "commit": None, "text": QA_SENTINEL, "truncated": False,
           "free": False, "unsupported": None, "author": "alice", "receivedAt": 1700000000}


class PipelineCase(ServerCase):
    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = pathlib.Path(tmp.name)
        self.home = self.dir / "home"
        self.requests = self.home / "testgate" / "requests"
        self.requests.mkdir(parents=True)
        self.script = self.dir / "ced.py"
        self.script.write_text(CED_SCRIPT, encoding="utf-8")
        self.ced_record = self.dir / "ced-record.json"
        self.env = {"HERMES_HOME": str(self.home), SECRET_ENV: SECRET, "PATH": os.environ.get("PATH", "")}
        self.config = self.dir / "config.json"
        self.write_config("ok")
        self.launched = []
        Fake.behavior = {"payload": {"title": TITLE_SENTINEL, "body": "설명", "diff": f"diff --git a/x b/x\n+{DIFF_SENTINEL}\n"}}

    def write_config(self, mode, **extra):
        data = {"ced_taker_command": [sys.executable, str(self.script), str(self.ced_record), mode],
                "github_app_url": self.url, "github_app_secret_env": SECRET_ENV, **extra}
        self.config.write_text(json.dumps(data), encoding="utf-8")

    def spool(self, delivery_id="d-1", **overrides):
        (self.requests / f"{delivery_id}.json").write_text(json.dumps(dict(REQUEST, deliveryId=delivery_id, **overrides)), encoding="utf-8")

    def launcher(self, command, delivery_id):
        """실제로 래퍼를 띄우는 대신, 시작되는 순간 해설 파일이 이미 있었는지 기록한다."""
        path = self.requests / f"{delivery_id}.context.json"
        self.launched.append({"command": list(command), "id": delivery_id, "context": json.loads(path.read_bytes()) if path.exists() else None})

    def run_pipeline(self, delivery_id="d-1", **kw):
        kw.setdefault("launcher", self.launcher)
        return pipeline.run(delivery_id, env=self.env, config_path=self.config, **kw)

    def context(self, delivery_id="d-1"):
        path = self.requests / f"{delivery_id}.context.json"
        return json.loads(path.read_bytes()) if path.exists() else None

    def failure_notice(self, reason):
        return f"참고 문서 공급자가 응답하지 않아 해설 없이 분석함 ({reason})."


class SuccessTest(PipelineCase):
    def test_the_explanation_is_written_before_the_wrapper_starts(self):
        self.spool()
        summary = self.run_pipeline()
        self.assertEqual(summary, {"explanation": "attached:1", "wrapper": "started"})
        (call,) = self.launched
        self.assertEqual(call["id"], "d-1")
        self.assertEqual(call["context"]["docs"][0]["id"], "ced:amount")  # 래퍼가 시작될 때 파일이 이미 있었다

    def test_the_default_wrapper_location_is_used_without_a_config(self):
        self.spool()
        self.config.unlink()
        self.run_pipeline()
        self.assertEqual(self.launched[0]["command"], [str(self.home / "testgate" / "testgate-run")])

    def test_the_configured_wrapper_is_used(self):
        self.spool()
        self.write_config("ok", wrapper_command=["/opt/tg/run", "--x"])
        self.run_pipeline()
        self.assertEqual(self.launched[0]["command"], ["/opt/tg/run", "--x"])

    def test_the_pr_information_goes_to_ced_taker_and_the_commit_is_passed_on(self):
        self.spool(commit="abc1234", pr=9)
        self.run_pipeline()
        self.assertEqual(json.loads(Fake.log[-1]["body"]), {"repo": "acme/shop", "pr": 9, "commit": "abc1234"})
        sent = json.loads(self.ced_record.read_text(encoding="utf-8"))
        self.assertEqual((sent["repo"], sent["title"], sent["description"]), ("acme/shop", TITLE_SENTINEL, "설명"))
        self.assertIn(DIFF_SENTINEL, sent["diff"])

    def test_the_request_is_signed_with_the_key_from_the_configured_variable(self):
        self.spool()
        self.run_pipeline()
        call = Fake.log[-1]
        from hermes_controller import githubapp
        self.assertEqual(call["headers"]["x-hermes-signature"],
                         githubapp.sign(SECRET, call["headers"]["x-hermes-timestamp"], call["body"]))

    def test_the_qa_text_is_never_sent_anywhere(self):
        self.spool()
        self.run_pipeline()
        self.assertNotIn(QA_SENTINEL, Fake.log[-1]["body"].decode())
        self.assertNotIn(QA_SENTINEL, self.ced_record.read_text(encoding="utf-8"))

    def test_an_answer_without_documents(self):
        self.spool()
        self.write_config("empty")
        self.assertEqual(self.run_pipeline()["explanation"], "empty")
        self.assertEqual(self.context(), {"version": 1, "docs": [], "notices": []})

    def test_the_context_file_is_private(self):
        self.spool()
        self.run_pipeline()
        self.assertEqual(stat.S_IMODE((self.requests / "d-1.context.json").stat().st_mode), 0o600)

    def test_the_wrapper_is_started_exactly_once(self):
        self.spool()
        self.run_pipeline()
        self.assertEqual(len(self.launched), 1)


class SkipTest(PipelineCase):
    def test_free_conversation_and_notice_only_requests_skip_the_explanation(self):
        for overrides, kind in (({"free": True}, "free"), ({"unsupported": "issue"}, "unsupported"), ({"free": True, "unsupported": "issue"}, "free")):
            with self.subTest(kind=kind):
                Fake.log = []
                self.launched = []
                self.spool(**overrides)
                self.assertEqual(self.run_pipeline(), {"explanation": f"skipped:{kind}", "wrapper": "started"})
                self.assertEqual(Fake.log, [])  # github-app을 부르지 않는다
                self.assertIsNone(self.context())  # 해설 파일도 없다
                self.assertEqual(len(self.launched), 1)  # 래퍼는 실행한다

    def test_a_missing_or_broken_request_still_starts_the_wrapper(self):
        for raw in (None, "{", json.dumps({"repo": "../x", "pr": 1})):
            with self.subTest(raw=raw):
                self.launched = []
                (self.requests / "d-1.json").unlink(missing_ok=True)
                if raw is not None:
                    (self.requests / "d-1.json").write_text(raw)
                summary = self.run_pipeline()
                self.assertEqual(summary["wrapper"], "started")
                self.assertTrue(summary["explanation"].startswith("request:"))
                self.assertIsNone(self.context())
                self.assertEqual(len(self.launched), 1)


class FailureTest(PipelineCase):
    """해설을 못 만들어도 분석은 일어나고, 해설 파일에 사유가 남는다."""

    def assert_failed_but_analyzed(self, reason):
        self.assertEqual(len(self.launched), 1)
        self.assertEqual(self.context(), {"version": 1, "docs": [], "notices": [self.failure_notice(reason)]})
        self.assertEqual(self.launched[0]["context"]["notices"], [self.failure_notice(reason)])  # 래퍼 시작 전에 이미 있었다

    def test_github_app_error(self):
        self.spool()
        Fake.behavior = {"mode": "status", "status": 401}
        self.assertEqual(self.run_pipeline(), {"explanation": "failed:github_http_401", "wrapper": "started"})
        self.assert_failed_but_analyzed("github_http_401")

    def test_missing_signing_key(self):
        self.spool()
        del self.env[SECRET_ENV]
        self.assertEqual(self.run_pipeline()["explanation"], "failed:github_no_secret")
        self.assert_failed_but_analyzed("github_no_secret")
        self.assertEqual(Fake.log, [])

    def test_ced_taker_error(self):
        self.spool()
        self.write_config("exit")
        self.assertEqual(self.run_pipeline()["explanation"], "failed:exit_code")
        self.assert_failed_but_analyzed("exit_code")

    def test_ced_taker_not_configured(self):
        self.spool()
        self.config.write_text(json.dumps({"github_app_url": self.url}))
        self.assertEqual(self.run_pipeline()["explanation"], "failed:not_configured")
        self.assert_failed_but_analyzed("not_configured")

    def test_ced_taker_missing_command(self):
        self.spool()
        self.config.write_text(json.dumps({"ced_taker_command": [str(self.dir / "nope")], "github_app_url": self.url,
                                           "github_app_secret_env": SECRET_ENV}))
        self.run_pipeline()
        self.assert_failed_but_analyzed("not_found")

    def test_a_broken_config_starts_the_default_wrapper_and_says_why(self):
        self.spool()
        for raw, reason in (("{", "config_unreadable"), (json.dumps({"ced_taker_command": ["relative"]}), "config_invalid")):
            with self.subTest(reason=reason):
                self.launched = []
                self.config.write_text(raw)
                summary = self.run_pipeline()
                self.assertEqual(summary["explanation"], f"failed:{reason}")
                self.assertEqual(self.launched[0]["command"], [str(self.home / "testgate" / "testgate-run")])
                self.assert_failed_but_analyzed(reason)

    def test_an_answer_too_large_for_ced_taker_calls_is_stopped_at_that_step(self):
        # 해설이 너무 크면 ced-taker 호출 단계에서 먼저 걸러진다(상한이 testgate의 읽기 상한보다 작다).
        self.spool()
        self.write_config("huge")
        self.assertEqual(self.run_pipeline()["explanation"], "failed:output_too_large")
        self.assert_failed_but_analyzed("output_too_large")

    def test_a_response_too_large_for_the_file_is_replaced_by_a_reason(self):
        # 파일을 쓰는 단계의 방어: 응답이 파일 상한을 넘으면 사유만 담은 파일로 바꿔 쓴다.
        big = {"version": 1, "docs": [{"id": "a", "title": "t", "text": "가" * 800000}], "notices": []}
        self.assertTrue(pipeline._write(self.requests, "d-1", big))
        self.assertEqual(self.context(), {"version": 1, "docs": [], "notices": [self.failure_notice("context_too_large")]})

    def test_the_failure_wording_is_the_one_the_contract_promises(self):
        self.spool()
        self.write_config("exit")
        self.run_pipeline()
        self.assertEqual(self.context()["notices"], ["참고 문서 공급자가 응답하지 않아 해설 없이 분석함 (exit_code)."])


class AlwaysStartsTheWrapperTest(PipelineCase):
    """가장 중요한 약속: 어떤 오류가 나도 마지막에 래퍼를 실행한다."""

    def test_an_unexpected_error_still_starts_the_wrapper(self):
        self.spool()

        def boom(*args, **kwargs):
            raise RuntimeError(EXC_SENTINEL)

        summary = self.run_pipeline(ced_runner=boom)
        self.assertEqual(summary, {"explanation": "error", "wrapper": "started"})
        self.assertEqual(len(self.launched), 1)

    def test_an_interrupt_still_starts_the_wrapper_and_is_not_swallowed(self):
        self.spool()

        def interrupt(*args, **kwargs):
            raise KeyboardInterrupt()

        with self.assertRaises(KeyboardInterrupt):
            self.run_pipeline(ced_runner=interrupt)
        self.assertEqual(len(self.launched), 1)

    def test_an_unexpected_error_in_the_github_client_still_starts_the_wrapper(self):
        self.spool()

        class BadApp:
            def __init__(self, *args, **kwargs):
                raise ZeroDivisionError

        self.assertEqual(self.run_pipeline(app_factory=BadApp)["wrapper"], "started")
        self.assertEqual(len(self.launched), 1)

    def test_an_unwritable_folder_still_starts_the_wrapper(self):
        self.spool()
        self.requests.chmod(0o500)
        self.addCleanup(self.requests.chmod, 0o700)
        summary = self.run_pipeline()
        self.assertEqual(summary["wrapper"], "started")
        self.assertEqual(len(self.launched), 1)
        self.assertIsNone(self.launched[0]["context"])

    def test_failing_to_start_the_wrapper_is_reported_not_hidden(self):
        self.spool()

        def cannot(command, delivery_id):
            raise FileNotFoundError

        summary = self.run_pipeline(launcher=cannot)
        self.assertEqual(summary["wrapper"], "failed")

    def test_the_wrapper_is_started_even_when_every_step_fails(self):
        self.spool()
        del self.env[SECRET_ENV]
        self.config.write_text("{")
        self.requests.chmod(0o500)
        self.addCleanup(self.requests.chmod, 0o700)
        self.assertEqual(self.run_pipeline()["wrapper"], "started")


class LogTest(PipelineCase):
    """기록에는 배달 ID, 단계, 사유 코드, 오류의 종류와 위치만 남고 내용은 남지 않는다."""

    def setUp(self):
        super().setUp()
        self.handler = cli.setup_logging(self.env)
        self.addCleanup(logging.getLogger("hermes_controller").removeHandler, self.handler)
        self.addCleanup(self.handler.close)

    def log_text(self):
        self.handler.flush()
        return (self.home / "logs" / "controller.log").read_text(encoding="utf-8")

    def assert_no_sentinels(self, text):
        for sentinel in (QA_SENTINEL, TITLE_SENTINEL, DIFF_SENTINEL, DOC_SENTINEL, EXC_SENTINEL, SECRET, "금액의 뜻", "공급자의 오류 문장"):
            self.assertNotIn(sentinel, text)

    def test_nothing_from_the_content_reaches_the_log_on_success(self):
        self.spool()
        self.run_pipeline()
        text = self.log_text()
        self.assertIn("d-1", text)
        self.assertIn("docs=1", text)
        self.assert_no_sentinels(text)

    def test_nothing_reaches_the_log_on_failures(self):
        for mode in ("exit", "huge"):
            self.spool()
            self.write_config(mode)
            self.run_pipeline()
        Fake.behavior = {"mode": "status", "status": 500}
        self.write_config("ok")
        self.run_pipeline()
        self.assert_no_sentinels(self.log_text())

    def test_an_unexpected_exception_logs_its_kind_and_place_but_not_its_message(self):
        self.spool()

        def boom(*args, **kwargs):
            raise RuntimeError(EXC_SENTINEL + SECRET + QA_SENTINEL)

        self.run_pipeline(ced_runner=boom)
        text = self.log_text()
        self.assertIn("RuntimeError", text)
        self.assertRegex(text, r"at=\w+\.py:\d+ \w+")
        self.assert_no_sentinels(text)

    def test_the_log_file_is_private_and_under_the_home_logs_folder(self):
        self.spool()
        self.run_pipeline()
        path = self.home / "logs" / "controller.log"
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_a_big_log_is_rotated_to_one_old_generation(self):
        path = self.home / "logs" / "controller.log"
        self.handler.close()
        logging.getLogger("hermes_controller").removeHandler(self.handler)
        path.write_bytes(b"x" * (cli.LOG_LIMIT_BYTES + 1))
        self.handler = cli.setup_logging(self.env)
        self.addCleanup(logging.getLogger("hermes_controller").removeHandler, self.handler)
        self.addCleanup(self.handler.close)
        self.assertTrue((self.home / "logs" / "controller.log.1").exists())
        self.assertLess(path.stat().st_size, cli.LOG_LIMIT_BYTES)

    def test_an_unwritable_log_location_does_not_stop_the_analysis(self):
        logs = self.home / "logs"
        for p in logs.iterdir():
            p.unlink()
        logs.chmod(0o500)
        self.addCleanup(logs.chmod, 0o700)
        handler = cli.setup_logging(self.env)
        self.addCleanup(logging.getLogger("hermes_controller").removeHandler, handler)
        self.addCleanup(handler.close)
        self.spool()
        self.assertEqual(self.run_pipeline()["wrapper"], "started")


class CommandTest(ServerCase):
    """bin/hermes-controller를 실제 프로세스로 띄운다. 가짜 래퍼가 시작되는 순간 해설 파일이 이미 있는지 본다."""

    WRAPPER = ('#!/usr/bin/env bash\n'
               'f="$(dirname "$0")/requests/$1.context.json"\n'
               '{ echo "args=$*"; if [ -f "$f" ]; then echo "context=present"; cat "$f"; else echo "context=none"; fi; } > "$WRAPPER_RECORD"\n')

    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = pathlib.Path(tmp.name)
        self.home = self.dir / "home"
        self.requests = self.home / "testgate" / "requests"
        self.requests.mkdir(parents=True)
        self.record = self.dir / "wrapper-record.txt"
        self.expect_wrapper = True
        self.addCleanup(self._let_wrapper_finish)
        wrapper = self.home / "testgate" / "testgate-run"
        wrapper.write_text(self.WRAPPER)
        wrapper.chmod(0o755)
        script = self.dir / "ced.py"
        script.write_text(CED_SCRIPT, encoding="utf-8")
        self.config = self.dir / "config.json"
        self.config.write_text(json.dumps({
            "ced_taker_command": [sys.executable, str(script), str(self.dir / "ced-record.json"), "ok"],
            "github_app_url": self.url, "github_app_secret_env": SECRET_ENV}))
        Fake.behavior = {"payload": {"title": "제목", "body": "설명", "diff": "diff --git a/x b/x\n+y\n"}}
        (self.requests / "d-1.json").write_text(json.dumps(REQUEST))

    def _let_wrapper_finish(self):
        """백그라운드로 뜬 가짜 래퍼가 기록을 쓰는 도중 임시 폴더를 지우면 정리가 실패한다."""
        if self.expect_wrapper:
            self.wait_record()

    def wait_record(self, wait=10.0):
        deadline = time.time() + wait
        while time.time() < deadline:
            if self.record.exists() and self.record.read_text().strip():
                return self.record.read_text().splitlines()
            time.sleep(0.05)
        return []

    def command(self, delivery_id="d-1", config=True, env=None, cwd=None):
        base = {"HERMES_HOME": str(self.home), SECRET_ENV: SECRET, "WRAPPER_RECORD": str(self.record), "PATH": os.environ.get("PATH", "")}
        base.update(env or {})
        argv = [sys.executable, str(ROOT / "bin" / "hermes-controller"), delivery_id]
        if config:
            argv += ["--config", str(self.config)]
        with tempfile.TemporaryDirectory() as elsewhere:
            return subprocess.run(argv, capture_output=True, text=True, env=base, cwd=cwd or elsewhere, timeout=60)

    def test_the_wrapper_starts_with_the_explanation_already_in_place(self):
        done = self.command()
        self.assertEqual((done.returncode, done.stdout, done.stderr), (0, "", ""))
        lines = self.wait_record()
        self.assertEqual(lines[0], "args=d-1")
        self.assertEqual(lines[1], "context=present")
        self.assertEqual(json.loads(lines[2])["docs"][0]["id"], "ced:amount")

    def test_it_works_from_another_directory_without_any_install(self):
        self.assertEqual(self.command(cwd="/").returncode, 0)
        self.assertEqual(self.wait_record()[1], "context=present")

    def test_without_any_config_the_wrapper_still_starts_and_the_reason_is_left_in_the_file(self):
        done = self.command(config=False, env={config.ENV_CONFIG: str(self.dir / "no-such-config.json")})
        self.assertEqual(done.returncode, 0)
        lines = self.wait_record()
        self.assertEqual(lines[1], "context=present")
        self.assertEqual(json.loads(lines[2])["notices"], ["참고 문서 공급자가 응답하지 않아 해설 없이 분석함 (not_configured)."])

    def test_a_free_conversation_starts_the_wrapper_with_no_context_file(self):
        (self.requests / "d-1.json").write_text(json.dumps(dict(REQUEST, free=True)))
        self.assertEqual(self.command().returncode, 0)
        self.assertEqual(self.wait_record(), ["args=d-1", "context=none"])
        self.assertEqual(Fake.log, [])

    def test_a_missing_wrapper_is_reported_with_exit_code_one(self):
        self.expect_wrapper = False
        (self.home / "testgate" / "testgate-run").unlink()
        done = self.command()
        self.assertEqual(done.returncode, 1)
        self.assertTrue((self.home / "logs" / "controller.log").exists())
        self.assertIn("래퍼를 시작하지 못함", (self.home / "logs" / "controller.log").read_text(encoding="utf-8"))

    def test_a_bad_delivery_id_does_nothing_and_exits_with_two(self):
        self.expect_wrapper = False
        for bad in ("../x", "a/b", "..", "x" * 101):
            with self.subTest(bad=bad):
                done = self.command(bad)
                self.assertEqual(done.returncode, 2)
                self.assertEqual(done.stderr.strip(), "오류: bad_delivery_id")
        self.assertFalse(self.record.exists())

    def test_the_log_file_is_created_under_the_home_and_never_holds_content(self):
        self.command()
        self.wait_record()
        log = (self.home / "logs" / "controller.log").read_text(encoding="utf-8")
        self.assertIn("래퍼 시작 id=d-1", log)
        for forbidden in (QA_SENTINEL, SECRET, "금액의 뜻"):
            self.assertNotIn(forbidden, log)


if __name__ == "__main__":
    unittest.main()
