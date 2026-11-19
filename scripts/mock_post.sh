#!/usr/bin/env bash
# Hermes 웹훅 라우트에 가짜 github-app 요청을 서명해 보낸다. 키는 화면에 출력하지 않는다.
# 사용법: scripts/mock_post.sh <qa|plain|other-author>   MOCK_DRY_RUN=1 이면 보내지 않고 intake 결과만 본다.
# MOCK_PR, MOCK_REPO 가 실제 PR 을 가리키면 분석이 실제로 실행되고 코멘트가 게시된다. 기본은 존재하지 않는 PR 번호이다.
set -euo pipefail
source "$(dirname "$0")/lib.sh"
CASE="${1:-qa}"
export CASE MOCK_PR="${MOCK_PR:-99999}" MOCK_REPO="${MOCK_REPO:-mock-repo}" CONFIG="$REPO/local/config.json"
BODY="$(python3 - <<'PY'
import json, os, time
cfg = json.load(open(os.environ["CONFIG"], encoding="utf-8"))
author, owner = cfg["allowed_authors"][0], cfg["allowed_repo_owners"][0]
case = os.environ["CASE"]
text = {"qa": "/qa 모의 요청입니다.", "plain": "일반 코멘트", "other-author": "/qa 다른 사람"}[case]
login = "someone-else" if case == "other-author" else author
print(json.dumps({"deliveryId": f"mock-{int(time.time())}", "event": {
    "kind": "comment", "action": "created", "target": "pull_request", "number": int(os.environ["MOCK_PR"]),
    "author": {"login": login, "type": "User"},
    "repo": {"owner": owner, "fullName": f"{owner}/{os.environ['MOCK_REPO']}"},
    "url": "https://example.invalid/mock", "commentId": 1, "body": text}}, ensure_ascii=False))
PY
)"
if [ -n "${MOCK_DRY_RUN:-}" ]; then
  # 임시 홈에서 intake 판정만 본다. run 은 시작하지 않는다(가짜 popen).
  export BODY
  HERMES_HOME="$(mktemp -d)" PYTHONPATH="$REPO/src" python3 -c '
import os, sys
from hermes_controller import intake
code, out = intake.handle(os.environ["BODY"], popen=lambda *a, **k: None)
print(out or "(버림)", f"종료 코드 {code}")
'
  exit 0
fi
export BODY SUBS ROUTE
python3 - <<'PY'
import hashlib, hmac, json, os, urllib.request
secret = json.load(open(os.environ["SUBS"], encoding="utf-8"))[os.environ["ROUTE"]]["secret"]
body = os.environ["BODY"].encode()
sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
req = urllib.request.Request(f"http://127.0.0.1:8644/webhooks/{os.environ['ROUTE']}", data=body, method="POST",
                             headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig, "X-GitHub-Event": "comment"})
with urllib.request.urlopen(req, timeout=15) as resp:
    print(resp.status, resp.read().decode()[:300])
PY
