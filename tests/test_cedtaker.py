"""ced-taker 호출(cedtaker.py) 시험. ced-taker 자체는 필요 없다. 약속을 지키는 가짜 명령으로 시험한다."""

import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

from hermes_controller import cedtaker
from hermes_controller.cedtaker import CedTakerError, build_request, failure_response, run_ced_taker

DOC = {"id": "ced:amount", "title": "CED 해설: amount", "text": "금액의 뜻"}
INFO = {"title": "제목", "description": "설명", "diff": "diff --git a/x b/x\n", "truncated": False}

SCRIPT = r'''
import json, os, sys, time
request = json.loads(sys.stdin.read())
record, mode = sys.argv[1], sys.argv[2]
open(record, "w").write(json.dumps({"request": request, "env": sorted(os.environ), "argv": sys.argv[1:]}))
doc = {"id": "ced:amount", "title": "CED 해설: amount", "text": "금액의 뜻"}
if mode == "ok":
    print(json.dumps({"version": 1, "docs": [doc], "notices": ["안내 하나"], "future": "무시된다"}))
elif mode == "empty":
    print(json.dumps({"version": 1, "docs": [], "notices": []}))
elif mode == "sleep":
    time.sleep(10)
elif mode == "exit":
    sys.stderr.write("오류 문장 비밀"); sys.exit(3)
elif mode == "garbage":
    print("nope")
elif mode == "v2":
    print(json.dumps({"version": 2, "docs": []}))
elif mode == "big":
    sys.stdout.write("x" * (2 * 1024 * 1024))
elif mode == "many":
    print(json.dumps({"version": 1, "docs": [dict(doc, id=f"d{i}") for i in range(60)], "notices": [f"n{i}" for i in range(9)]}))
elif mode == "baddoc":
    print(json.dumps({"version": 1, "docs": [{"id": "x", "title": "t"}]}))
elif mode == "badnotices":
    print(json.dumps({"version": 1, "docs": [], "notices": "문자열"}))
elif mode == "noversion":
    print(json.dumps({"docs": []}))
'''


class CmdCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = pathlib.Path(tmp.name)
        self.script = self.dir / "fake.py"
        self.script.write_text(SCRIPT, encoding="utf-8")
        self.record = self.dir / "record.json"

    def command(self, mode):
        return [sys.executable, str(self.script), str(self.record), mode]

    def run_it(self, mode, timeout=10):
        return run_ced_taker(self.command(mode), build_request("acme/shop", INFO), timeout)

    def reason(self, mode, timeout=10):
        with self.assertRaises(CedTakerError) as ctx:
            self.run_it(mode, timeout)
        return ctx.exception.reason

    def recorded(self):
        return json.loads(self.record.read_text(encoding="utf-8"))


class RequestTest(CmdCase):
    def test_request_shape(self):
        self.assertEqual(build_request("acme/shop", INFO),
                         {"version": 1, "repo": "acme/shop", "title": "제목", "description": "설명", "diff": "diff --git a/x b/x\n"})

    def test_the_command_receives_exactly_that_request(self):
        self.run_it("ok")
        self.assertEqual(self.recorded()["request"], build_request("acme/shop", INFO))


class SuccessTest(CmdCase):
    def test_validated_answer_keeps_only_known_fields(self):
        got = self.run_it("ok")
        self.assertEqual(got, {"version": 1, "docs": [DOC], "notices": ["안내 하나"]})
        self.assertNotIn("future", got)

    def test_empty_answer_is_valid(self):
        self.assertEqual(self.run_it("empty"), {"version": 1, "docs": [], "notices": []})

    def test_docs_and_notices_are_limited(self):
        got = self.run_it("many")
        self.assertEqual((len(got["docs"]), len(got["notices"])), (cedtaker.MAX_DOCS, cedtaker.MAX_NOTICES))


class FailureTest(CmdCase):
    def test_reasons(self):
        cases = {"exit": cedtaker.EXIT_CODE, "garbage": cedtaker.BAD_OUTPUT, "v2": cedtaker.UNSUPPORTED_VERSION,
                 "big": cedtaker.OUTPUT_TOO_LARGE, "baddoc": cedtaker.BAD_OUTPUT, "badnotices": cedtaker.BAD_OUTPUT,
                 "noversion": cedtaker.BAD_OUTPUT}
        for mode, expected in cases.items():
            with self.subTest(mode=mode):
                self.assertEqual(self.reason(mode), expected)

    def test_timeout(self):
        self.assertEqual(self.reason("sleep", timeout=1), cedtaker.TIMEOUT)

    def test_missing_command(self):
        with self.assertRaises(CedTakerError) as ctx:
            run_ced_taker([str(self.dir / "nope")], {}, 5)
        self.assertEqual(ctx.exception.reason, cedtaker.NOT_FOUND)

    def test_not_executable(self):
        plain = self.dir / "plain"
        plain.write_text("x")
        with self.assertRaises(CedTakerError) as ctx:
            run_ced_taker([str(plain)], {}, 5)
        self.assertEqual(ctx.exception.reason, cedtaker.NOT_RUNNABLE)

    def test_no_shell_is_used(self):
        marker = self.dir / "should-not-exist"
        with self.assertRaises(CedTakerError):
            run_ced_taker([f"echo hi; touch {marker}"], {}, 5)
        self.assertFalse(marker.exists())

    def test_the_providers_own_words_never_reach_the_reason(self):
        with self.assertRaises(CedTakerError) as ctx:
            self.run_it("exit")
        self.assertNotIn("비밀", str(ctx.exception))


class EnvironmentTest(CmdCase):
    def test_only_a_few_environment_variables_reach_the_command(self):
        with mock.patch.dict(os.environ, {"TESTGATE_GITHUB_APP_SECRET": "s3cret", "OTHER_TOKEN": "t"}):
            self.run_it("ok")
        env = set(self.recorded()["env"])
        self.assertNotIn("TESTGATE_GITHUB_APP_SECRET", env)
        self.assertNotIn("OTHER_TOKEN", env)
        self.assertIn("PATH", env)
        self.assertTrue(env <= set(cedtaker.ENV_ALLOWED) | {"LC_CTYPE", "__CF_USER_TEXT_ENCODING"}, env)

    def test_child_env_only_passes_the_allowed_names(self):
        self.assertEqual(cedtaker.child_env({"PATH": "/bin", "HOME": "/h", "SECRET": "x", "HERMES_HOME": "/hh"}),
                         {"PATH": "/bin", "HOME": "/h", "HERMES_HOME": "/hh"})


class FailureResponseTest(unittest.TestCase):
    def test_a_failure_becomes_a_file_with_no_documents_and_one_line(self):
        self.assertEqual(failure_response("timeout"), {
            "version": 1, "docs": [],
            "notices": ["참고 문서 공급자가 응답하지 않아 해설 없이 분석함 (timeout)."]})

    def test_the_wording_matches_what_the_contract_document_promises(self):
        self.assertIn("해설 없이 분석함", failure_response("exit_code")["notices"][0])


if __name__ == "__main__":
    unittest.main()
