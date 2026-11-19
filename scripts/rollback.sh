#!/usr/bin/env bash
# 가장 최근 백업으로 되돌린다(webhook_subscriptions.json, 시작 파일). 사용법: scripts/rollback.sh [백업 폴더]
set -euo pipefail
source "$(dirname "$0")/lib.sh"
dir="${1:-$(ls -1d "$BACKUP_ROOT"/*/ 2>/dev/null | sort | tail -1)}"
[ -n "$dir" ] && [ -d "$dir" ] || { echo "백업이 없다: $BACKUP_ROOT" >&2; exit 1; }
for f in "$dir"/*; do
  case "$(basename "$f")" in
    webhook_subscriptions.json) cp -p "$f" "$SUBS"; echo "되돌림: $SUBS";;
    "$STUB_NAME") cp -p "$f" "$STUB"; echo "되돌림: $STUB";;
  esac
done
echo "백업 $dir 로 되돌렸다. 라우트는 다음 요청부터 적용된다."
