#!/usr/bin/env bash
# Hermes 웹훅 라우트가 controller 시작 파일을 필터로 쓰게 한다.
# 사용법: scripts/subscribe.sh [--check]
# - 라우트가 있으면 script, prompt, description 만 바꾸고 세션 도구(toolsets)를 지운다. 서명 키는 읽지도 바꾸지도 않는다.
# - 라우트가 없으면 hermes webhook subscribe 로 만든다. 이때 Hermes 가 새 키를 만들며, 그 키는 github-app 의 sink 설정에 넣어야 한다.
# - 바꾸기 전에 webhook_subscriptions.json 을 백업한다. 되돌리기: scripts/rollback.sh
# 라우트는 다음 요청부터 적용된다(게이트웨이 재시작 불필요).
set -euo pipefail
source "$(dirname "$0")/lib.sh"
export ROUTE SUBS STUB_NAME PROMPT
state() {
  python3 - <<'PY'
import json, os
try:
    r = json.load(open(os.environ["SUBS"], encoding="utf-8")).get(os.environ["ROUTE"])
except (OSError, ValueError):
    r = None
if r is None:
    print("missing")
elif r.get("script") == os.environ["STUB_NAME"] and r.get("prompt") == os.environ["PROMPT"] and not r.get("toolsets"):
    print("ok")
else:
    print("old")
PY
}
s="$(state)"
if [ "${1:-}" = "--check" ]; then
  case "$s" in ok) echo "라우트 $ROUTE 가 controller 시작 파일을 쓴다"; exit 0;; *) echo "라우트 $ROUTE 상태: $s" >&2; exit 1;; esac
fi
[ -f "$STUB" ] || { echo "시작 파일이 없다. 먼저 scripts/install.sh" >&2; exit 1; }
if [ "$s" = "missing" ]; then
  hermes webhook subscribe "$ROUTE" --events comment --script "$STUB_NAME" --deliver log \
    --description "github-app sink: PR comment -> hermes-controller" --prompt "$PROMPT"
  echo "새 라우트를 만들었다. 위에 나온 키를 github-app 의 sink 설정에 넣어야 한다(사용자 몫)."
  exit 0
fi
echo "백업: $(backup "$SUBS")"
python3 - <<'PY'
import json, os
path, route = os.environ["SUBS"], os.environ["ROUTE"]
data = json.load(open(path, encoding="utf-8"))
r = data[route]
before = r.get("script")
r.update(script=os.environ["STUB_NAME"], prompt=os.environ["PROMPT"], description="github-app sink: PR comment -> hermes-controller")
r.pop("toolsets", None)
tmp = path + ".tmp"
with open(tmp, "w", encoding="utf-8") as handle:
    json.dump(data, handle, ensure_ascii=False, indent=2)
os.chmod(tmp, 0o600)
os.replace(tmp, path)
print(f"라우트 {route}: script {before} -> {r['script']} (서명 키는 그대로)")
PY
