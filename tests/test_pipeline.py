"""run 시험. github-app, ced-taker, 프로젝트, 세션 이름은 모두 가짜이다."""

import json
import pathlib
import subprocess
import sys

from hermes_controller import contextfile, pipeline, project
from hermes_controller import request as req
from hermes_controller.cedtaker import CedTakerError
from hermes_controller.githubapp import GithubAppError
from tests.helpers import QA_SENTINEL, HomeCase

CONTRACTS = pathlib.Path(__file__).resolve().parent.parent / "contracts"
DOC = json.loads((CONTRACTS / "request.v1.json").read_text())
CONTEXT = json.loads((CONTRACTS / "context.v1.json").read_text())


class FakeApp:
    calls = []

    def __init__(self, url, secret, timeout):
        self.secret = secret

    def fetch_pr(self, repo, pr, commit):
        FakeApp.calls.append((repo, pr, commit))
        return {"title": "t", "description": "d", "diff": "+balance"}


class BrokenApp(FakeApp):
    def fetch_pr(self, repo, pr, commit):
        raise GithubAppError("github_timeout")


class Recorder:
    def __init__(self, result=None, error=None):
        self.calls, self.result, self.error = [], result or {"status": "done", "session_name": "[PR7 - t #1]"}, error

    def __call__(self, *args):
        self.calls.append(args)
        if self.error:
            raise self.error
        return self.result


class PipelineTest(HomeCase):
    def setUp(self):
        super().setUp()
        FakeApp.calls = []
        self.dir = self.home / "controller" / "requests"

    def put(self, **changes):
        doc = dict(DOC, **changes)
        req.write_request(self.dir, doc)
        return doc["deliveryId"]

    def run_it(self, delivery="d-0001", app=FakeApp, ced=None, proj=None, renamer=None):
        self.proj = proj or Recorder()
        self.renamer = renamer or Recorder(result="renamed")
        ced = ced or (lambda cmd, payload, timeout: CONTEXT)
        return pipeline.run(delivery, env=self.env, config_path=self.config_path, app_factory=app,
                            ced_runner=ced, project_runner=self.proj, renamer=self.renamer)

    def context(self, delivery="d-0001"):
        return json.loads(pathlib.Path(contextfile.context_path(self.dir, delivery)).read_text())

    def test_full_path_context_project_and_rename(self):
        self.put()
        summary = self.run_it()
        self.assertEqual(summary, {"context": "attached:1", "project": "done", "rename": "renamed"})
        self.assertEqual(FakeApp.calls, [("acme/shop", 7, None)])  # 늘 PR 전체 diff
        self.assertEqual(self.context(), CONTEXT)
        (command, request_path, context_path, timeout), = self.proj.calls
        self.assertEqual(request_path, req.request_path(self.dir, "d-0001"))
        self.assertEqual(context_path, contextfile.context_path(self.dir, "d-0001"))
        self.assertEqual(self.renamer.calls[0][2:4], ("d-0001", "[PR7 - t #1]"))

    def test_context_failures_still_run_the_project(self):
        cases = [(dict(app=BrokenApp), "failed:github_timeout"),
                 (dict(ced=lambda *a: (_ for _ in ()).throw(CedTakerError("timeout"))), "failed:timeout"),
                 (dict(ced=lambda *a: 1 / 0), "error")]
        for i, (kw, expected) in enumerate(cases):
            delivery = self.put(deliveryId=f"d-{i}")
            with self.subTest(expected=expected):
                summary = self.run_it(delivery, **kw)
                self.assertEqual((summary["context"], summary["project"]), (expected, "done"))

    def test_failed_context_leaves_a_reason_for_the_project(self):
        self.put()
        self.run_it(app=BrokenApp)
        ctx = self.context()
        self.assertEqual(ctx["docs"], [])
        self.assertIn("github_timeout", ctx["notices"][0])

    def test_no_context_for_issue_comments_or_routes_without_context(self):
        self.put(deliveryId="d-i", target="issue")
        self.assertEqual(self.run_it("d-i")["context"], "skipped:target")
        self.write_config(routes=[{"name": "testgate", "prefix": "/qa", "command": [str(self.project)]}])
        self.put(deliveryId="d-n")
        self.assertEqual(self.run_it("d-n")["context"], "skipped:route")
        self.assertEqual(FakeApp.calls, [])

    def test_missing_ced_command_is_reported(self):
        self.write_config(ced_taker_command=None)
        cfg = json.loads(self.config_path.read_text()); cfg.pop("ced_taker_command"); self.config_path.write_text(json.dumps(cfg))
        self.put()
        self.assertEqual(self.run_it()["context"], "failed:not_configured")

    def test_project_errors_and_no_name_skip_rename(self):
        self.put(deliveryId="d-a")
        s = self.run_it("d-a", proj=Recorder(error=project.ProjectError(project.TIMEOUT)))
        self.assertEqual((s["project"], s["rename"]), ("project_timeout", "skipped"))
        self.put(deliveryId="d-b")
        s = self.run_it("d-b", proj=Recorder(result={"status": "ignored", "session_name": None}))
        self.assertEqual((s["project"], s["rename"]), ("ignored", "skipped"))

    def test_bad_request_or_unknown_route_does_not_start(self):
        self.assertEqual(self.run_it("d-none")["project"], "not_started")
        self.put(route="gone")
        self.assertEqual(self.run_it()["project"], "not_started")


class ProjectTest(HomeCase):
    def script(self, body):
        path = self.home / "proj.py"
        path.write_text(body)
        return (sys.executable, str(path))

    def test_real_process_round_trip(self):
        cmd = self.script("import sys, json\nprint('잡음')\nprint(json.dumps({'version':1,'status':'done','session_name':'[PR7]','argv':sys.argv[1:]}))\n")
        self.assertEqual(project.run_project(cmd, "r.json", "c.json", 30), {"status": "done", "session_name": "[PR7]"})

    def test_bad_results(self):
        for out in ("", "not json", '{"version":2,"status":"done"}', '{"version":1,"status":"weird"}'):
            with self.subTest(out=out), self.assertRaises(project.ProjectError):
                project.parse_result(out)
        self.assertIsNone(project.parse_result('{"version":1,"status":"done","session_name":"a\\nb"}')["session_name"])

    def test_timeout_and_missing_command(self):
        cmd = self.script("import time\ntime.sleep(5)\n")
        with self.assertRaises(project.ProjectError) as ctx:
            project.run_project(cmd, "r", "c", 1)
        self.assertEqual(ctx.exception.reason, project.TIMEOUT)
        with self.assertRaises(project.ProjectError) as ctx:
            project.run_project(("/nonexistent/x",), "r", "c", 1)
        self.assertEqual(ctx.exception.reason, project.NOT_RUNNABLE)


class SessionTest(HomeCase):
    def test_rename_finds_session_and_calls_hermes(self):
        import sqlite3
        from hermes_controller import session
        db = sqlite3.connect(self.home / "state.db")
        db.execute("create table sessions (id text, chat_id text, started_at real)")
        db.execute("insert into sessions values ('s1', 'webhook:github-app:d-1', 1)")
        db.commit(); db.close()
        calls = []
        run = lambda argv, **kw: calls.append(argv) or subprocess.CompletedProcess(argv, 0)
        self.assertEqual(session.rename(self.home, "github-app", "d-1", "[PR7]", "/bin/sh", run=run, sleep=lambda s: None), "renamed")
        self.assertEqual(calls[0][1:], ["sessions", "rename", "s1", "[PR7]"])
        self.assertEqual(session.rename(self.home, "github-app", "d-2", "x", "/bin/sh", run=run, sleep=lambda s: None), "skipped:no_session")
