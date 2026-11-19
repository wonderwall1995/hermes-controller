"""해설 파일(requests/<배달ID>.context.json)을 쓴다.

약속(해설 파일의 약속 문서)을 지킨다.
- 임시 이름에 쓴 뒤 최종 이름으로 바꾼다. 읽는 쪽이 반쯤 쓰인 파일을 보지 않는다.
- 권한은 600이다. 본문에 CED 설명이 들어 있다.
- 임시 이름 자리에 미리 심어 둔 심볼릭 링크를 따라가지 않는다.
- testgate가 읽는 상한(2MiB)을 넘는 파일은 쓰지 않는다.
오류에는 사유 코드만 담는다. 경로와 내용은 담지 않는다.
"""

import json
import os

from hermes_controller.request import valid_delivery_id

MAX_FILE_BYTES = 2 * 1024 * 1024 - 1  # testgate의 읽기 상한(2MiB) 안에 들어와야 한다.

BAD_DELIVERY_ID = "bad_delivery_id"
CONTEXT_TOO_LARGE = "context_too_large"
CONTEXT_UNWRITABLE = "context_unwritable"


class ContextWriteError(Exception):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def context_path(requests_dir, delivery_id):
    return os.path.join(str(requests_dir), f"{delivery_id}.context.json")


def write_context(requests_dir, delivery_id, response):
    """응답(version, docs, notices)을 해설 파일로 쓴다. 쓸 수 없으면 ContextWriteError."""
    if not valid_delivery_id(delivery_id):
        raise ContextWriteError(BAD_DELIVERY_ID)
    data = json.dumps(response, ensure_ascii=False).encode("utf-8")
    if len(data) > MAX_FILE_BYTES:
        raise ContextWriteError(CONTEXT_TOO_LARGE)
    target = context_path(requests_dir, delivery_id)
    temp = os.path.join(str(requests_dir), f".{delivery_id}.context.tmp")
    try:
        try:
            os.unlink(temp)  # 지난번에 남은 임시 파일이나 심어 둔 링크는 지우고 새로 만든다.
        except FileNotFoundError:
            pass
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(temp, target)
    except OSError:
        try:
            os.unlink(temp)
        except OSError:
            pass
        raise ContextWriteError(CONTEXT_UNWRITABLE) from None
