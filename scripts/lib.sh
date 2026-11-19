# 공용 값. 다른 스크립트가 source 한다.
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROUTE="${ROUTE:-github-app}"
STUB_NAME="hermes_controller_filter.py"
STUB="$HERMES_HOME/scripts/$STUB_NAME"
SUBS="$HERMES_HOME/webhook_subscriptions.json"
BACKUP_ROOT="$HERMES_HOME/backups/hermes-controller"
PROMPT='Request {deliveryId} ({route}) for {repo} #{pr} was received. A background job handles it and posts the result by itself. Reply with exactly the single word: OK. Do not use any tool.'

# 바꾸기 전에 파일을 백업 폴더(시각별)로 복사한다. 권한은 소유자만.
backup() {
  local dir="$BACKUP_ROOT/$(date +%Y%m%d-%H%M%S)"
  mkdir -p "$dir" && chmod 700 "$BACKUP_ROOT" "$dir"
  for f in "$@"; do [ -e "$f" ] && cp -p "$f" "$dir/"; done
  echo "$dir"
}
