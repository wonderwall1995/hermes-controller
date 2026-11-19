"""github-app 클라이언트(githubapp.py) 시험. 가짜 서버를 쓰며 실제 github-app과 키는 필요 없다."""

import hashlib
import hmac
import json
import socket
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from hermes_controller import githubapp
from hermes_controller.githubapp import GithubApp, GithubAppError

SECRET = "unit-test-secret"


class Fake(BaseHTTPRequestHandler):
    log = []
    behavior = {}

    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("content-length", 0))
        body = self.rfile.read(length)
        Fake.log.append({"path": self.path, "body": body, "headers": {k.lower(): v for k, v in self.headers.items()}})
        mode = Fake.behavior.get("mode", "ok")
        if mode == "sleep":
            time.sleep(Fake.behavior.get("seconds", 3))
        if mode == "status":
            self.send_response(Fake.behavior["status"])
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "secret-looking-detail"}).encode())
            return
        payload = Fake.behavior.get("payload", {"title": "제목", "body": "설명", "diff": "diff --git a/x b/x\n", "truncated": False})
        raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        try:
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(raw)
        except BrokenPipeError:  # 시간 초과 시험에서 클라이언트가 먼저 끊는다
            pass


class ServerCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), Fake)
        cls.url = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        Fake.log = []
        Fake.behavior = {}

    def app(self, **kw):
        return GithubApp(self.url, SECRET, **kw)


class SignTest(unittest.TestCase):
    def test_signature_follows_the_documented_formula(self):
        body = '{"repo":"o/r","pr":1}'.encode()
        expected = "sha256=" + hmac.new(b"k", b"1700000000." + body, hashlib.sha256).hexdigest()
        self.assertEqual(githubapp.sign("k", "1700000000", body), expected)

    def test_a_known_vector(self):
        # 독립적으로 계산한 값: HMAC-SHA256("k", "1700000000.{}")
        self.assertEqual(githubapp.sign("k", "1700000000", b"{}"),
                         "sha256=" + hmac.new(b"k", b"1700000000.{}", hashlib.sha256).hexdigest())

    def test_different_secret_timestamp_or_body_changes_the_signature(self):
        base = githubapp.sign("k", "1", b"b")
        self.assertNotEqual(base, githubapp.sign("k2", "1", b"b"))
        self.assertNotEqual(base, githubapp.sign("k", "2", b"b"))
        self.assertNotEqual(base, githubapp.sign("k", "1", b"c"))


class FetchPrTest(ServerCase):
    def test_request_is_signed_and_has_the_expected_shape(self):
        self.app(now=lambda: 1700000000).fetch_pr("acme/shop", 7)
        (call,) = Fake.log
        self.assertEqual(call["path"], "/api/pr")
        self.assertEqual(json.loads(call["body"]), {"repo": "acme/shop", "pr": 7})
        self.assertEqual(call["headers"]["x-hermes-timestamp"], "1700000000")
        self.assertEqual(call["headers"]["x-hermes-signature"], githubapp.sign(SECRET, "1700000000", call["body"]))
        self.assertEqual(call["headers"]["content-type"], "application/json")

    def test_commit_is_sent_only_when_given(self):
        self.app().fetch_pr("o/r", 1, commit="abc1234")
        self.assertEqual(json.loads(Fake.log[-1]["body"])["commit"], "abc1234")
        self.app().fetch_pr("o/r", 1)
        self.assertNotIn("commit", json.loads(Fake.log[-1]["body"]))

    def test_successful_answer(self):
        got = self.app().fetch_pr("o/r", 1)
        self.assertEqual(got, {"title": "제목", "description": "설명", "diff": "diff --git a/x b/x\n", "truncated": False})

    def test_a_pr_without_a_description_has_an_empty_one(self):
        Fake.behavior = {"payload": {"title": None, "body": None, "diff": "d"}}
        got = self.app().fetch_pr("o/r", 1)
        self.assertEqual((got["title"], got["description"]), ("", ""))

    def test_truncated_flag_is_passed_through_only_when_true(self):
        Fake.behavior = {"payload": {"diff": "d", "truncated": True}}
        self.assertTrue(self.app().fetch_pr("o/r", 1)["truncated"])
        Fake.behavior = {"payload": {"diff": "d", "truncated": "yes"}}
        self.assertFalse(self.app().fetch_pr("o/r", 1)["truncated"])

    def test_http_errors_become_a_code(self):
        for status in (400, 401, 404, 409, 500):
            with self.subTest(status=status):
                Fake.behavior = {"mode": "status", "status": status}
                with self.assertRaises(GithubAppError) as ctx:
                    self.app().fetch_pr("o/r", 1)
                self.assertEqual(ctx.exception.reason, f"github_http_{status}")
                self.assertNotIn("secret-looking-detail", str(ctx.exception))  # 응답 본문은 오류에 넣지 않는다

    def test_bad_answers(self):
        bad = [b"not json", b"[]", b"5", b"null", json.dumps({"title": "t"}).encode(),
               json.dumps({"diff": 5}).encode(), json.dumps({"diff": "d", "title": 5}).encode(),
               json.dumps({"diff": "d", "body": ["x"]}).encode()]
        for payload in bad:
            with self.subTest(payload=payload):
                Fake.behavior = {"payload": payload}
                with self.assertRaises(GithubAppError) as ctx:
                    self.app().fetch_pr("o/r", 1)
                self.assertEqual(ctx.exception.reason, githubapp.BAD_RESPONSE)

    def test_timeout(self):
        Fake.behavior = {"mode": "sleep", "seconds": 3}
        with self.assertRaises(GithubAppError) as ctx:
            self.app(timeout=1).fetch_pr("o/r", 1)
        self.assertEqual(ctx.exception.reason, githubapp.TIMEOUT)

    def test_unreachable_server(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]  # 닫힌 포트
        with self.assertRaises(GithubAppError) as ctx:
            GithubApp(f"http://127.0.0.1:{port}", SECRET, timeout=2).fetch_pr("o/r", 1)
        self.assertEqual(ctx.exception.reason, githubapp.UNREACHABLE)

    def test_invalid_inputs_are_refused_before_any_request(self):
        for call in ({"repo": "no-slash", "pr": 1}, {"repo": "a/b/c", "pr": 1}, {"repo": "../x", "pr": 1}, {"repo": "o/..", "pr": 1}, {"repo": "./r", "pr": 1}, {"repo": 5, "pr": 1},
                     {"repo": "o/r", "pr": 0}, {"repo": "o/r", "pr": "1"}, {"repo": "o/r", "pr": True},
                     {"repo": "o/r", "pr": 1, "commit": "xyz"}, {"repo": "o/r", "pr": 1, "commit": "abc"}):
            with self.subTest(call=call):
                with self.assertRaises(GithubAppError) as ctx:
                    self.app().fetch_pr(**call)
                self.assertEqual(ctx.exception.reason, githubapp.BAD_REQUEST)
        self.assertEqual(Fake.log, [])

    def test_a_missing_secret_is_an_error(self):
        for secret in ("", None):
            with self.assertRaises(GithubAppError) as ctx:
                GithubApp(self.url, secret)
            self.assertEqual(ctx.exception.reason, githubapp.NO_SECRET)

    def test_errors_never_contain_the_secret_or_the_address(self):
        Fake.behavior = {"mode": "status", "status": 401}
        with self.assertRaises(GithubAppError) as ctx:
            self.app().fetch_pr("o/r", 1)
        self.assertNotIn(SECRET, str(ctx.exception))
        self.assertNotIn(self.url, str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
