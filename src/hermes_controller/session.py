"""Hermes 세션 이름 바꾸기. 프로젝트가 결과로 알려 준 이름을 이 요청의 웹훅 세션에 붙인다.

세션은 Hermes 상태 DB에서 chat_id(webhook:<라우트>:<배달ID>)로 찾는다.
환경 변수 HERMES_SESSION_ID는 쓰지 않는다. 게이트웨이가 프로세스 전체에 마지막 세션의 값을 덮어쓰기 때문이다.
실패해도 분석 결과에는 영향이 없다. 결과 문자열만 돌려준다.
"""

import os
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path


def find_session_id(home, route, delivery_id):
    db = Path(home) / "state.db"
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
        try:
            row = conn.execute(
                "select id from sessions where chat_id = ? order by started_at desc limit 1",
                (f"webhook:{route}:{delivery_id}",),
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return None
    return row[0] if row else None


def wait_for_session(home, route, delivery_id, tries=20, delay=1.0, sleep=time.sleep):
    """세션 행이 생길 때까지 기다린다. 빨리 끝나는 요청에서는 아직 없을 수 있다."""
    for attempt in range(tries):
        session_id = find_session_id(home, route, delivery_id)
        if session_id:
            return session_id
        if attempt + 1 < tries:
            sleep(delay)
    return None


def rename(home, route, delivery_id, name, hermes_binary, run=subprocess.run, sleep=time.sleep):
    session_id = wait_for_session(home, route, delivery_id, sleep=sleep)
    if not session_id:
        return "skipped:no_session"
    binary = shutil.which(hermes_binary) or (hermes_binary if os.path.isabs(hermes_binary) and os.access(hermes_binary, os.X_OK) else None)
    if not binary:
        return "skipped:no_hermes_binary"
    try:
        result = run([binary, "sessions", "rename", session_id, name], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return "failed"
    return "renamed" if result.returncode == 0 else "failed"
