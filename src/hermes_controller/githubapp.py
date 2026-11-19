"""github-app의 Hermes 연동 API(/api/pr) 클라이언트.

github-app의 서명 약속을 따른다.
  헤더 x-hermes-timestamp: 초 단위 정수
  헤더 x-hermes-signature: "sha256=" + HMAC-SHA256(키, "<timestamp>." + 요청 본문)

PR 정보를 한 번 가져온다(제목, 설명, diff). 이 정보는 해설을 만드는 데만 쓴다.
오류에는 사유 코드만 담는다. 키, 주소, 응답 본문은 담지 않는다.
"""

import hashlib
import hmac
import json
import re
import socket
import time
import urllib.error
import urllib.request

MAX_RESPONSE_BYTES = 16 * 1024 * 1024
REPO_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
COMMIT_PATTERN = re.compile(r"^[0-9a-fA-F]{7,40}$")

# 사유 코드
NO_SECRET = "github_no_secret"
BAD_REQUEST = "github_bad_request"
TIMEOUT = "github_timeout"
UNREACHABLE = "github_unreachable"
BAD_RESPONSE = "github_bad_response"


def http_reason(code):
    return f"github_http_{code}"


class GithubAppError(Exception):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def sign(secret, timestamp, body):
    signed = f"{timestamp}.".encode() + body
    return "sha256=" + hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()


class GithubApp:
    def __init__(self, url, secret, timeout=15, now=time.time):
        if not secret:
            raise GithubAppError(NO_SECRET)
        self.url = url.rstrip("/")
        self.secret = secret
        self.timeout = timeout
        self.now = now

    def _post(self, path, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        timestamp = str(int(self.now()))
        request = urllib.request.Request(
            self.url + path, data=body, method="POST",
            headers={
                "content-type": "application/json",
                "x-hermes-timestamp": timestamp,
                "x-hermes-signature": sign(self.secret, timestamp, body),
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            code = exc.code
            exc.close()
            raise GithubAppError(http_reason(code)) from None
        except (socket.timeout, TimeoutError):
            raise GithubAppError(TIMEOUT) from None
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, (socket.timeout, TimeoutError)):
                raise GithubAppError(TIMEOUT) from None
            raise GithubAppError(UNREACHABLE) from None
        except OSError:
            raise GithubAppError(UNREACHABLE) from None
        if len(data) > MAX_RESPONSE_BYTES:
            raise GithubAppError(BAD_RESPONSE)
        try:
            return json.loads(data.decode("utf-8"))
        except ValueError:
            raise GithubAppError(BAD_RESPONSE) from None

    def fetch_pr(self, repo, pr, commit=None):
        """PR 정보를 한 번 가져온다. {"title", "description", "diff", "truncated"}를 돌려준다."""
        valid_pr = isinstance(pr, int) and not isinstance(pr, bool) and pr > 0
        if not isinstance(repo, str) or not REPO_PATTERN.match(repo) or not valid_pr:
            raise GithubAppError(BAD_REQUEST)
        if any(part in (".", "..") for part in repo.split("/")):  # 점만으로 된 이름은 저장소 이름이 될 수 없다
            raise GithubAppError(BAD_REQUEST)
        payload = {"repo": repo, "pr": pr}
        if commit:
            if not isinstance(commit, str) or not COMMIT_PATTERN.match(commit):
                raise GithubAppError(BAD_REQUEST)
            payload["commit"] = commit
        data = self._post("/api/pr", payload)
        if not isinstance(data, dict):
            raise GithubAppError(BAD_RESPONSE)
        title, body, diff = data.get("title"), data.get("body"), data.get("diff")
        # 설명이 없는 PR은 body가 null일 수 있다. 그 밖의 형식 오류는 받아들이지 않는다.
        if not isinstance(diff, str) or not (title is None or isinstance(title, str)) or not (body is None or isinstance(body, str)):
            raise GithubAppError(BAD_RESPONSE)
        return {"title": title or "", "description": body or "", "diff": diff, "truncated": data.get("truncated") is True}
