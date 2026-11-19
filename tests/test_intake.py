"""intake(Hermes 필터) 시험. 실제 run은 시작하지 않고 가짜 popen으로 확인한다."""

import io
import json
import os
import pathlib

from hermes_controller import cli, intake
from hermes_controller import request as req
from tests.helpers import QA_SENTINEL, HomeCase, payload


class FakePopen:
    def __init__(self):
        self.calls = []

    def __call__(self, argv, **kw):
        self.calls.append((argv, kw))


class IntakeTest(HomeCase):
    def handle(self, data, popen=None):
        self.popen = popen or FakePopen()
        return intake.handle(json.dumps(data), env=self.env, config_path=self.config_path, popen=self.popen, now=lambda: 1)

    def saved(self, delivery="d-1"):
        return json.loads(pathlib.Path(req.request_path(self.home / "controller" / "requests", delivery)).read_text())

    def test_qa_comment_is_saved_with_the_original_body_and_run_starts(self):
        code, out = self.handle(payload())
        self.assertEqual(code, 0)
        doc = self.saved()
        self.assertEqual((doc["route"], doc["repo"], doc["pr"], doc["target"], doc["author"]), ("testgate", "acme/shop", 7, "pull_request", "tester"))
        self.assertIn(QA_SENTINEL, doc["body"])
        (argv, kw), = self.popen.calls
        self.assertEqual(argv[-2:], ["run", "d-1"])
        self.assertTrue(kw["start_new_session"])
        self.assertNotIn(QA_SENTINEL, out)  # Hermes 세션에는 원문이 가지 않는다
        self.assertEqual(json.loads(out)["route"], "testgate")

    def test_dropped_events_save_nothing(self):
        cases = [payload(body="그냥 코멘트"), payload(body="/qatest"), payload(login="stranger"), payload(owner="other"),
                 payload(action="edited"), payload(target="commit"), {"event": "x"}, []]
        for data in cases:
            with self.subTest(data=data):
                code, out = self.handle(data)
                self.assertEqual((code, out), (0, ""))
                self.assertEqual(self.popen.calls, [])
        self.assertFalse((self.home / "controller" / "requests").exists())

    def test_issue_and_review_comments_are_passed_to_the_project(self):
        for target, delivery in (("issue", "d-i"), ("pull_request_review", "d-r")):
            self.handle(payload(target=target, delivery=delivery))
            self.assertEqual(self.saved(delivery)["target"], target)

    def test_first_matching_route_wins(self):
        self.write_config(routes=[{"name": "api", "prefix": "/api", "command": [str(self.project)]},
                                  {"name": "testgate", "prefix": "/qa", "command": [str(self.project)]}])
        self.handle(payload(body="/api 만들어 줘", delivery="d-a"))
        self.assertEqual(self.saved("d-a")["route"], "api")

    def test_same_delivery_twice_starts_once(self):
        self.handle(payload())
        code, _ = self.handle(payload())
        self.assertEqual(code, 0)
        self.assertEqual(self.popen.calls, [])

    def test_fail_closed_without_config_or_runnable_project(self):
        self.config_path.unlink()
        self.assertEqual(self.handle(payload())[0], 1)
        self.write_config(routes=[{"name": "testgate", "prefix": "/qa", "command": ["/nonexistent/x"]}])
        self.assertEqual(self.handle(payload())[0], 1)
        self.assertFalse((self.home / "controller" / "requests" / "d-1.json").exists())

    def test_cli_intake_writes_output_and_log_without_body(self):
        out = io.StringIO()
        code = cli.main(["--config", str(self.config_path), "intake"], env=self.env,
                        stdin=io.StringIO(json.dumps(payload())), stdout=out, popen=FakePopen())
        self.assertEqual(code, 0)
        self.assertIn("testgate", out.getvalue())
        log = (self.home / "logs" / "controller.log").read_text()
        self.assertIn("d-1", log)
        self.assertNotIn(QA_SENTINEL, log)


class StubTest(HomeCase):
    def test_stub_runs_the_repo_intake(self):
        out = io.StringIO()
        self.assertEqual(cli.main(["stub"], env=self.env, stdout=out), 0)
        text = out.getvalue()
        compile(text, "stub", "exec")
        self.assertIn(str(intake.BIN), text)
        self.assertIn('"intake"', text)
        self.assertTrue(os.access(intake.BIN, os.X_OK))
