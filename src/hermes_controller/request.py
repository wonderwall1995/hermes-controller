"""testgate가 저장한 요청 파일(requests/<배달ID>.json)을 읽는다.

controller에게 필요한 것은 어느 저장소의 몇 번 PR인지, 커밋을 지정했는지, 어떤 종류의 요청인지뿐이다.
요청 파일에는 QA 서술 원문(text)이 있지만 이 모듈은 그것을 읽어서 보관하지 않는다.
파일은 신뢰하지 않는 입력이다. 심볼릭 링크와 특수 파일은 읽지 않고, 크기를 제한하고, 값을 다시 검증한다.
오류에는 사유 코드만 담는다.
"""

import json
import os
import re
import stat
from dataclasses import dataclass

from hermes_controller.githubapp import COMMIT_PATTERN, REPO_PATTERN

# testgate가 배달 ID를 검사하는 규칙과 같다.
DELIVERY_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
MAX_REQUEST_BYTES = 1024 * 1024

BAD_DELIVERY_ID = "bad_delivery_id"
REQUEST_MISSING = "request_missing"
REQUEST_UNREADABLE = "request_unreadable"
REQUEST_BAD = "request_bad"


class RequestError(Exception):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class Request:
    delivery_id: str
    repo: str
    pr: int
    commit: str  # 없으면 None
    free: bool
    unsupported: str  # 안내만 하는 요청이면 그 위치 이름, 아니면 None


def valid_delivery_id(value):
    return isinstance(value, str) and bool(DELIVERY_ID_PATTERN.match(value)) and set(value) != {"."}


def request_path(requests_dir, delivery_id):
    return os.path.join(str(requests_dir), f"{delivery_id}.json")


def read_request(requests_dir, delivery_id):
    """요청 파일을 읽어 Request로 돌려준다. 문제가 있으면 RequestError."""
    if not valid_delivery_id(delivery_id):
        raise RequestError(BAD_DELIVERY_ID)
    try:
        # 심볼릭 링크는 따라가지 않는다. O_NONBLOCK은 FIFO를 열 때 멈추지 않게 한다.
        fd = os.open(request_path(requests_dir, delivery_id), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        raise RequestError(REQUEST_MISSING) from None
    except OSError:
        raise RequestError(REQUEST_UNREADABLE) from None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise RequestError(REQUEST_UNREADABLE)
        with os.fdopen(fd, "rb", closefd=False) as handle:
            data = handle.read(MAX_REQUEST_BYTES + 1)
    except OSError:
        raise RequestError(REQUEST_UNREADABLE) from None
    finally:
        os.close(fd)
    if len(data) > MAX_REQUEST_BYTES:
        raise RequestError(REQUEST_BAD)
    try:
        doc = json.loads(data.decode("utf-8"))
    except ValueError:
        raise RequestError(REQUEST_BAD) from None
    return _validated(doc, delivery_id)


def _validated(doc, delivery_id):
    if not isinstance(doc, dict):
        raise RequestError(REQUEST_BAD)
    repo, pr, commit = doc.get("repo"), doc.get("pr"), doc.get("commit")
    free, unsupported = doc.get("free", False), doc.get("unsupported")
    if not isinstance(repo, str) or not REPO_PATTERN.match(repo) or any(p in (".", "..") for p in repo.split("/")):
        raise RequestError(REQUEST_BAD)
    if not isinstance(pr, int) or isinstance(pr, bool) or pr <= 0:
        raise RequestError(REQUEST_BAD)
    if commit is not None and not (isinstance(commit, str) and COMMIT_PATTERN.match(commit)):
        raise RequestError(REQUEST_BAD)
    if not isinstance(free, bool) or not (unsupported is None or isinstance(unsupported, str)):
        raise RequestError(REQUEST_BAD)
    return Request(delivery_id, repo, pr, commit, free, unsupported or None)


def needs_explanation(request):
    """일반 분석 요청에서만 해설을 만든다. 자유 대화와 안내만 하는 요청은 건너뛴다."""
    return not request.free and not request.unsupported
