"""시험 공용: 임시 홈과 설정 파일을 만든다. 실제 홈, 실제 문서, 실제 키는 쓰지 않는다."""

import json
import os
import pathlib
import stat
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
QA_SENTINEL = "SENTINEL_QA_9f3a"


def payload(body="/qa 확인했다 " + QA_SENTINEL, delivery="d-1", target="pull_request", login="tester", owner="acme",
            action="created", number=7):
    return {"deliveryId": delivery, "event": {
        "kind": "comment", "action": action, "target": target, "number": number,
        "author": {"login": login, "type": "User"},
        "repo": {"owner": owner, "fullName": f"{owner}/shop"},
        "url": "https://example.test/c/1", "commentId": 1, "body": body}}


class HomeCase(unittest.TestCase):
    """임시 HERMES_HOME과 설정 파일. self.project는 실행 가능한 가짜 프로젝트 명령이다."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = pathlib.Path(tmp.name)
        self.env = {"HERMES_HOME": str(self.home), "PATH": os.environ.get("PATH", "")}
        self.project = self.home / "fake-project"
        self.project.write_text("#!/bin/sh\nexit 0\n")
        self.project.chmod(self.project.stat().st_mode | stat.S_IXUSR)
        self.config_path = self.home / "config.json"
        self.write_config()

    def write_config(self, **overrides):
        data = {"allowed_authors": ["tester"], "allowed_repo_owners": ["acme"],
                "routes": [{"name": "testgate", "prefix": "/qa", "command": [str(self.project)], "context": True}],
                "ced_taker_command": [str(self.project)], "github_app_secret_env": "UNIT_TEST_APP_KEY"}
        data.update(overrides)
        self.config_path.write_text(json.dumps(data))
        return data
