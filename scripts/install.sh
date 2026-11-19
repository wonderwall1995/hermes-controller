#!/usr/bin/env bash
# Hermes 의 scripts/ 에 시작 파일 하나를 둔다. 코드는 저장소에 있고, 시작 파일은 저장소의 intake 를 실행할 뿐이다.
# 사용법: scripts/install.sh [--check]    --check 는 바꾸지 않고 같은지만 본다.
set -euo pipefail
source "$(dirname "$0")/lib.sh"
want="$(python3 "$REPO/bin/hermes-controller" stub)"
if [ "${1:-}" = "--check" ]; then
  if [ -f "$STUB" ] && [ "$(cat "$STUB")" = "$want" ]; then echo "시작 파일이 최신이다: $STUB"; exit 0; fi
  echo "시작 파일이 없거나 다르다: $STUB" >&2; exit 1
fi
[ -f "$REPO/local/config.json" ] || { echo "설정이 없다: $REPO/local/config.json (README 참고). 설정 없이는 모든 요청을 거절한다." >&2; exit 1; }
mkdir -p "$HERMES_HOME/scripts"
[ -f "$STUB" ] && echo "백업: $(backup "$STUB")"
printf '%s\n' "$want" > "$STUB"
chmod 644 "$STUB"
echo "시작 파일을 두었다: $STUB"
