"""요청 파일(requests/<배달ID>.json). intake가 쓰고, run과 프로젝트가 읽는다. 약속은 contracts/request.v1.json.

  {"version": 1, "deliveryId": "...", "route": "testgate", "repo": "owner/name", "pr": 7,
   "target": "pull_request" | "issue" | "pull_request_review", "author": "login",
   "url": "...", "commentId": 123, "body": "코멘트 원문", "receivedAt": 1700000000}

controller는 코멘트 원문(body)을 해석하지 않는다. 접두어로 프로젝트를 고를 뿐이고, 문법은 프로젝트가 읽는다.
파일은 신뢰하지 않는 입력으로 다시 읽는다. 심볼릭 링크와 특수 파일은 읽지 않고, 크기를 제한하고, 값을 검증한다.
오류에는 사유 코드만 담는다.
"""

import json
import os
import re
import stat
from dataclasses import dataclass

from hermes_controller.githubapp import REPO_PATTERN

VERSION = 1
DELIVERY_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
TARGETS = ("pull_request", "issue", "pull_request_review")
MAX_BODY_CHARS = 20000
MAX_REQUEST_BYTES = 1024 * 1024

BAD_DELIVERY_ID = "bad_delivery_id"
REQUEST_EXISTS = "request_exists"
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
    route: str
    repo: str
    pr: int
    target: str


def valid_delivery_id(value):
    return isinstance(value, str) and bool(DELIVERY_ID_PATTERN.match(value)) and set(value) != {"."}


def request_path(requests_dir, delivery_id):
    return os.path.join(str(requests_dir), f"{delivery_id}.json")


def write_request(requests_dir, doc):
    """요청 파일을 새로 쓴다. 같은 배달ID가 이미 있으면 RequestError(request_exists). 권한은 600."""
    delivery_id = doc.get("deliveryId")
    if not valid_delivery_id(delivery_id):
        raise RequestError(BAD_DELIVERY_ID)
    os.makedirs(str(requests_dir), mode=0o700, exist_ok=True)
    target = request_path(requests_dir, delivery_id)
    temp = os.path.join(str(requests_dir), f".{delivery_id}.tmp")
    try:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        raise RequestError(REQUEST_EXISTS) from None
    os.close(fd)  # 자리를 먼저 잡아 같은 배달ID가 두 번 시작되지 않게 한다. 내용은 임시 파일로 바꿔 넣는다.
    try:
        try:
            os.unlink(temp)
        except FileNotFoundError:
            pass
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(doc, handle, ensure_ascii=False)
        os.replace(temp, target)
    except OSError:
        raise RequestError(REQUEST_UNREADABLE) from None


def read_request(requests_dir, delivery_id):
    """요청 파일을 읽어 Request로 돌려준다. 문제가 있으면 RequestError."""
    if not valid_delivery_id(delivery_id):
        raise RequestError(BAD_DELIVERY_ID)
    try:
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
    return validated(doc, delivery_id)


def validated(doc, delivery_id):
    if not isinstance(doc, dict) or doc.get("version") != VERSION or doc.get("deliveryId") != delivery_id:
        raise RequestError(REQUEST_BAD)
    route, repo, pr, target = doc.get("route"), doc.get("repo"), doc.get("pr"), doc.get("target")
    if not isinstance(route, str) or not route:
        raise RequestError(REQUEST_BAD)
    if not isinstance(repo, str) or not REPO_PATTERN.match(repo) or any(p in (".", "..") for p in repo.split("/")):
        raise RequestError(REQUEST_BAD)
    if not isinstance(pr, int) or isinstance(pr, bool) or pr <= 0:
        raise RequestError(REQUEST_BAD)
    if target not in TARGETS or not isinstance(doc.get("body"), str):
        raise RequestError(REQUEST_BAD)
    return Request(delivery_id, route, repo, pr, target)
