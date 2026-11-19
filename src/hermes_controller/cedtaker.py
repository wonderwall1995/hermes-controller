"""ced-taker 공급자 명령을 실행해 해설을 받는다.

설정의 명령(인자 목록)을 셸 없이 실행하고, 표준 입력으로 JSON 요청을 주고, 표준 출력의 JSON 응답을 받는다.
이 모듈은 ced-taker의 코드를 가져오지 않는다. 명령과 JSON의 약속만 안다.

  요청  {"version": 1, "repo": "owner/name", "title": "...", "description": "...", "diff": "..."}
  응답  {"version": 1, "docs": [{"id": "...", "title": "...", "text": "..."}], "notices": ["..."]}

- 응답은 검증하고 알려진 필드(version, docs, notices)만 남긴다. 해설 파일에는 이 검증된 내용을 쓴다.
- 자식 프로세스에는 환경 변수 PATH, HOME, HERMES_HOME, LANG, LC_ALL, TZ만 넘긴다. 서명 키 같은 비밀은 넘기지 않는다.
- 실패하면 CedTakerError(사유 코드)를 낸다. 공급자가 쓴 오류 문장은 쓰지 않는다.
"""

import json
import os
import subprocess

VERSION = 1
MAX_OUTPUT_BYTES = 1536 * 1024  # testgate가 읽는 해설 파일의 상한(2MiB)보다 작게 둔다.
MAX_DOCS = 50
MAX_NOTICES = 5
ENV_ALLOWED = ("PATH", "HOME", "HERMES_HOME", "LANG", "LC_ALL", "TZ")

# 사유 코드. 보고서 비고에 그대로 남는다.
TIMEOUT = "timeout"
NOT_FOUND = "not_found"
NOT_RUNNABLE = "not_runnable"
EXIT_CODE = "exit_code"
OUTPUT_TOO_LARGE = "output_too_large"
BAD_OUTPUT = "bad_output"
UNSUPPORTED_VERSION = "unsupported_version"


class CedTakerError(Exception):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def build_request(repo, info):
    """PR 정보(githubapp.fetch_pr의 결과)로 ced-taker 요청을 만든다."""
    return {"version": VERSION, "repo": repo, "title": info["title"], "description": info["description"], "diff": info["diff"]}


def child_env(environ=None):
    environ = os.environ if environ is None else environ
    return {k: environ[k] for k in ENV_ALLOWED if k in environ}


def failure_response(reason):
    """해설을 못 만들었을 때의 응답. 문서는 비우고 보고서 비고에 사유가 남게 안내 한 줄만 담는다."""
    return {"version": VERSION, "docs": [], "notices": [f"참고 문서 공급자가 응답하지 않아 해설 없이 분석함 ({reason})."]}


def _validated(output):
    try:
        data = json.loads(output.decode("utf-8"))
    except ValueError:
        raise CedTakerError(BAD_OUTPUT) from None
    version = data.get("version") if isinstance(data, dict) else None
    if not isinstance(version, int) or isinstance(version, bool):
        raise CedTakerError(BAD_OUTPUT)
    if version != VERSION:
        raise CedTakerError(UNSUPPORTED_VERSION)
    docs, notices = data.get("docs", []), data.get("notices", [])
    if not isinstance(docs, list) or not isinstance(notices, list) or not all(isinstance(n, str) for n in notices):
        raise CedTakerError(BAD_OUTPUT)
    clean_docs = []
    for item in docs[:MAX_DOCS]:
        if not isinstance(item, dict) or not all(isinstance(item.get(k), str) for k in ("id", "title", "text")):
            raise CedTakerError(BAD_OUTPUT)
        clean_docs.append({"id": item["id"], "title": item["title"], "text": item["text"]})
    return {"version": VERSION, "docs": clean_docs, "notices": notices[:MAX_NOTICES]}


def run_ced_taker(command, payload, timeout, run=subprocess.run, environ=None):
    """ced-taker 명령을 실행해 검증된 응답을 돌려준다. 실패하면 CedTakerError."""
    try:
        done = run(
            list(command),
            input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            capture_output=True,
            timeout=timeout,
            env=child_env(environ),
            shell=False,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise CedTakerError(TIMEOUT) from None
    except FileNotFoundError:
        raise CedTakerError(NOT_FOUND) from None
    except OSError:
        raise CedTakerError(NOT_RUNNABLE) from None
    if done.returncode != 0:
        raise CedTakerError(EXIT_CODE)
    if len(done.stdout) > MAX_OUTPUT_BYTES:
        raise CedTakerError(OUTPUT_TOO_LARGE)
    return _validated(done.stdout)
