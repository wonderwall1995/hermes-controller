"""요청 파일 읽기(request.py) 시험. 시험 자료는 모두 가짜다."""

import json
import os
import pathlib
import tempfile
import unittest

from hermes_controller import request as req
from hermes_controller.request import Request, RequestError, needs_explanation, read_request

GOOD = {"deliveryId": "d-1", "repo": "acme/shop", "pr": 7, "commit": None, "text": "비밀 서술", "truncated": False,
        "free": False, "unsupported": None, "author": "alice", "receivedAt": 1700000000}


class RequestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = pathlib.Path(tmp.name)

    def put(self, data=None, raw=None, name="d-1"):
        path = self.dir / f"{name}.json"
        path.write_text(raw if raw is not None else json.dumps(data), encoding="utf-8")
        return path

    def reason(self, delivery_id="d-1"):
        with self.assertRaises(RequestError) as ctx:
            read_request(self.dir, delivery_id)
        return ctx.exception.reason


class ReadTest(RequestCase):
    def test_a_normal_request(self):
        self.put(GOOD)
        self.assertEqual(read_request(self.dir, "d-1"), Request("d-1", "acme/shop", 7, None, False, None))

    def test_commit_free_and_unsupported(self):
        self.put(dict(GOOD, commit="abc1234", free=True, unsupported="issue"))
        got = read_request(self.dir, "d-1")
        self.assertEqual((got.commit, got.free, got.unsupported), ("abc1234", True, "issue"))

    def test_optional_fields_may_be_missing(self):
        self.put({"repo": "o/r", "pr": 1})
        self.assertEqual(read_request(self.dir, "d-1"), Request("d-1", "o/r", 1, None, False, None))

    def test_the_qa_text_is_never_kept(self):
        self.put(GOOD)
        got = read_request(self.dir, "d-1")
        self.assertFalse(hasattr(got, "text"))
        self.assertNotIn("비밀", repr(got))

    def test_the_file_is_not_modified(self):
        path = self.put(GOOD)
        before = path.read_bytes()
        read_request(self.dir, "d-1")
        self.assertEqual(path.read_bytes(), before)


class FailureTest(RequestCase):
    def test_missing_file(self):
        self.assertEqual(self.reason(), req.REQUEST_MISSING)

    def test_bad_delivery_ids_are_refused_before_touching_the_disk(self):
        for bad in ("", "../x", "a/b", ".", "..", "...", "x" * 101, "a b", "한글", None, 5):
            with self.subTest(bad=bad):
                self.assertEqual(self.reason(bad), req.BAD_DELIVERY_ID)

    def test_valid_ids_with_dots_and_dashes(self):
        for good in ("d-1", "a.b_c", "e69-1", "052a6be0-dbf6-11f1-8518-02f2778e9379"):
            self.assertTrue(req.valid_delivery_id(good), good)

    def test_broken_files(self):
        cases = ["not json", "[]", "5", "null", "{}", json.dumps({"repo": "o/r"}), json.dumps({"pr": 1}),
                 json.dumps({"repo": "o/r", "pr": 0}), json.dumps({"repo": "o/r", "pr": "1"}), json.dumps({"repo": "o/r", "pr": True}),
                 json.dumps({"repo": "no-slash", "pr": 1}), json.dumps({"repo": "../x", "pr": 1}), json.dumps({"repo": "o/..", "pr": 1}),
                 json.dumps({"repo": 5, "pr": 1}), json.dumps({"repo": "o/r", "pr": 1, "commit": "xyz"}),
                 json.dumps({"repo": "o/r", "pr": 1, "commit": 5}), json.dumps({"repo": "o/r", "pr": 1, "free": "yes"}),
                 json.dumps({"repo": "o/r", "pr": 1, "unsupported": 5})]
        for raw in cases:
            with self.subTest(raw=raw[:40]):
                self.put(raw=raw)
                self.assertEqual(self.reason(), req.REQUEST_BAD)

    def test_invalid_utf8(self):
        (self.dir / "d-1.json").write_bytes(b"\xff\xfe")
        self.assertEqual(self.reason(), req.REQUEST_BAD)

    def test_too_large_even_when_the_json_itself_is_valid(self):
        # 올바른 요청 뒤에 공백을 붙여 제한을 넘긴다. 크기 검사가 없으면 이 파일은 정상으로 읽힌다.
        (self.dir / "d-1.json").write_bytes(json.dumps(GOOD).encode() + b" " * req.MAX_REQUEST_BYTES)
        self.assertEqual(self.reason(), req.REQUEST_BAD)

    def test_a_file_just_under_the_limit_is_read(self):
        body = json.dumps(GOOD).encode()
        (self.dir / "d-1.json").write_bytes(body + b" " * (req.MAX_REQUEST_BYTES - len(body)))
        self.assertEqual(read_request(self.dir, "d-1").pr, 7)

    def test_symlink_directory_and_fifo_are_not_read(self):
        outside = self.dir / "outside.json"
        outside.write_text(json.dumps(GOOD))
        os.symlink(outside, self.dir / "link.json")
        self.assertEqual(self.reason("link"), req.REQUEST_UNREADABLE)
        (self.dir / "dir.json").mkdir()
        self.assertEqual(self.reason("dir"), req.REQUEST_UNREADABLE)
        os.mkfifo(self.dir / "fifo.json")
        self.assertEqual(self.reason("fifo"), req.REQUEST_UNREADABLE)  # 멈추면 이 시험이 끝나지 않는다

    def test_errors_never_contain_the_content_or_the_path(self):
        self.put(raw=json.dumps({"repo": "비밀 저장소", "pr": 1, "text": "비밀 서술"}))
        with self.assertRaises(RequestError) as ctx:
            read_request(self.dir, "d-1")
        self.assertNotIn("비밀", str(ctx.exception))
        self.assertNotIn(str(self.dir), str(ctx.exception))


class NeedsExplanationTest(unittest.TestCase):
    def test_only_normal_analysis_requests_need_one(self):
        self.assertTrue(needs_explanation(Request("d", "o/r", 1, None, False, None)))
        self.assertTrue(needs_explanation(Request("d", "o/r", 1, "abc1234", False, None)))  # 커밋 지정도 일반 분석이다
        self.assertFalse(needs_explanation(Request("d", "o/r", 1, None, True, None)))  # 자유 대화
        self.assertFalse(needs_explanation(Request("d", "o/r", 1, None, False, "issue")))  # 안내만 하는 요청
        self.assertFalse(needs_explanation(Request("d", "o/r", 1, None, True, "issue")))


if __name__ == "__main__":
    unittest.main()
