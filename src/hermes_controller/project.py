"""분석 프로젝트 명령을 실행하고 결과를 읽는다. 약속은 contracts/result.v1.json.

  실행  <command...> --request <요청 파일> --context <맥락 파일>
        맥락 파일은 없을 수도 있다. 없으면 프로젝트는 맥락 없이 일한다.
  결과  표준 출력의 마지막 줄에 JSON 한 개
        {"version": 1, "status": "done" | "failed" | "ignored", "session_name": "..." 또는 null}

프로젝트는 GitHub에 결과를 게시하는 일까지 스스로 한다. controller는 결과로 세션 이름만 받는다.
프로젝트가 쓰는 비밀(서명 키 등)은 Hermes 실행 환경에서 오므로 환경 변수를 그대로 넘긴다.
"""

import json
import re
import subprocess

VERSION = 1
STATUSES = ("done", "failed", "ignored")
MAX_NAME_CHARS = 200
_NAME_BAD = re.compile(r"[\x00-\x1f\x7f]")

TIMEOUT = "project_timeout"
NOT_RUNNABLE = "project_not_runnable"
NO_RESULT = "project_no_result"


class ProjectError(Exception):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def parse_result(stdout):
    """표준 출력의 마지막 비어 있지 않은 줄을 결과로 읽는다. 틀리면 ProjectError(project_no_result)."""
    lines = [line for line in (stdout or "").splitlines() if line.strip()]
    try:
        data = json.loads(lines[-1]) if lines else None
    except ValueError:
        data = None
    if not isinstance(data, dict) or data.get("version") != VERSION or data.get("status") not in STATUSES:
        raise ProjectError(NO_RESULT)
    name = data.get("session_name")
    if not isinstance(name, str) or not name.strip() or _NAME_BAD.search(name):
        name = None
    return {"status": data["status"], "session_name": name[:MAX_NAME_CHARS] if name else None}


def run_project(command, request_path, context_path, timeout, run=subprocess.run):
    argv = list(command) + ["--request", str(request_path), "--context", str(context_path)]
    try:
        done = run(argv, stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8",
                   errors="replace", timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        raise ProjectError(TIMEOUT) from None
    except OSError:
        raise ProjectError(NOT_RUNNABLE) from None
    return parse_result(done.stdout)
