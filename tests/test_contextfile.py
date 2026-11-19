"""해설 파일 쓰기(contextfile.py) 시험. 시험 자료는 모두 가짜다."""

import json
import os
import pathlib
import stat
import tempfile
import unittest
from unittest import mock

from hermes_controller import contextfile
from hermes_controller.contextfile import ContextWriteError, write_context

RESPONSE = {"version": 1, "docs": [{"id": "ced:amount", "title": "CED 해설: amount", "text": "금액의 뜻\n둘째 줄"}], "notices": ["안내 하나"]}


class WriteCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = pathlib.Path(tmp.name)
        self.target = self.dir / "d-1.context.json"

    def reason(self, delivery_id="d-1", response=RESPONSE):
        with self.assertRaises(ContextWriteError) as ctx:
            write_context(self.dir, delivery_id, response)
        return ctx.exception.reason

    def leftovers(self):
        return sorted(p.name for p in self.dir.iterdir() if p.name != "d-1.context.json")


class WriteTest(WriteCase):
    def test_the_file_round_trips_and_keeps_korean_unescaped(self):
        write_context(self.dir, "d-1", RESPONSE)
        raw = self.target.read_bytes()
        self.assertEqual(json.loads(raw), RESPONSE)
        self.assertIn("금액의 뜻".encode(), raw)

    def test_the_mode_is_600(self):
        write_context(self.dir, "d-1", RESPONSE)
        self.assertEqual(stat.S_IMODE(self.target.stat().st_mode), 0o600)

    def test_no_temporary_file_is_left(self):
        write_context(self.dir, "d-1", RESPONSE)
        self.assertEqual(self.leftovers(), [])

    def test_an_existing_file_is_replaced(self):
        self.target.write_text("옛 내용")
        write_context(self.dir, "d-1", RESPONSE)
        self.assertEqual(json.loads(self.target.read_bytes()), RESPONSE)

    def test_a_stale_temporary_file_is_cleaned_up(self):
        (self.dir / ".d-1.context.tmp").write_text("지난번에 남은 것")
        write_context(self.dir, "d-1", RESPONSE)
        self.assertEqual(self.leftovers(), [])

    def test_a_symlink_planted_at_the_temporary_name_is_not_followed(self):
        outside = self.dir / "outside.txt"
        outside.write_text("원래 내용")
        os.symlink(outside, self.dir / ".d-1.context.tmp")
        write_context(self.dir, "d-1", RESPONSE)
        self.assertEqual(outside.read_text(), "원래 내용")  # 링크 대상은 건드리지 않았다
        self.assertEqual(json.loads(self.target.read_bytes()), RESPONSE)

    def test_a_symlink_at_the_final_name_is_replaced_not_written_through(self):
        outside = self.dir / "outside.txt"
        outside.write_text("원래 내용")
        os.symlink(outside, self.target)
        write_context(self.dir, "d-1", RESPONSE)
        self.assertEqual(outside.read_text(), "원래 내용")
        self.assertFalse(self.target.is_symlink())
        self.assertEqual(json.loads(self.target.read_bytes()), RESPONSE)

    def test_the_final_file_never_appears_half_written(self):
        # 이름 바꾸기에서 실패하면 최종 파일은 없고 임시 파일도 남지 않는다.
        with mock.patch("hermes_controller.contextfile.os.replace", side_effect=OSError("disk full")):
            self.assertEqual(self.reason(), contextfile.CONTEXT_UNWRITABLE)
        self.assertFalse(self.target.exists())
        self.assertEqual(self.leftovers(), [])

    def test_an_empty_answer_with_only_a_notice(self):
        notice = {"version": 1, "docs": [], "notices": ["참고 문서 공급자가 응답하지 않아 해설 없이 분석함 (timeout)."]}
        write_context(self.dir, "d-1", notice)
        self.assertEqual(json.loads(self.target.read_bytes()), notice)


class FailureTest(WriteCase):
    def test_a_missing_folder(self):
        self.dir.rmdir()
        self.assertEqual(self.reason(), contextfile.CONTEXT_UNWRITABLE)
        self.dir.mkdir()  # 정리 단계가 폴더를 지울 수 있게 되돌린다

    def test_a_folder_at_the_final_name(self):
        self.target.mkdir()
        self.assertEqual(self.reason(), contextfile.CONTEXT_UNWRITABLE)
        self.assertEqual(self.leftovers(), [])

    def test_bad_delivery_ids_are_refused(self):
        for bad in ("", "../x", "a/b", ".", "..", "x" * 101, None, 5):
            with self.subTest(bad=bad):
                self.assertEqual(self.reason(bad), contextfile.BAD_DELIVERY_ID)
        self.assertEqual(self.leftovers(), [])

    def test_a_file_over_the_limit_is_not_written(self):
        big = {"version": 1, "docs": [{"id": "a", "title": "t", "text": "가" * 800000}], "notices": []}
        self.assertEqual(self.reason(response=big), contextfile.CONTEXT_TOO_LARGE)
        self.assertFalse(self.target.exists())

    def test_the_limit_is_inside_what_testgate_reads(self):
        self.assertLess(contextfile.MAX_FILE_BYTES, 2 * 1024 * 1024)

    def test_errors_never_contain_the_path_or_the_content(self):
        with self.assertRaises(ContextWriteError) as ctx:
            write_context(self.dir / "missing", "d-1", RESPONSE)
        self.assertNotIn(str(self.dir), str(ctx.exception))
        self.assertNotIn("금액", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
