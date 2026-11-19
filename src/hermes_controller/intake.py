"""Hermes 웹훅 라우트의 필터. Hermes가 아는 이 프로젝트의 유일한 입구이다.

입력: 표준 입력의 JSON. github-app의 sink가 보낸 {"deliveryId", "event": {...}} 이다.
출력: 받으면 표준 출력에 짧은 JSON 하나(코멘트 원문은 넣지 않는다). 버리면 아무것도 출력하지 않는다.

하는 일
  1. 새로 쓴 코멘트인지, 지원하는 위치인지, 허용 계정과 허용 소유자인지 본다.
  2. 코멘트가 어느 규칙의 접두어로 시작하는지 보고 프로젝트를 고른다. 접두어 뒤의 문법은 해석하지 않는다.
  3. 요청 파일을 쓰고, `hermes-controller run <배달ID>`를 백그라운드로 시작한다. 기다리지 않는다.
Hermes는 필터를 짧은 제한 시간 안에 끝내야 하므로, 오래 걸리는 일(맥락, 분석)은 모두 run이 한다.

설정이 없거나 틀리거나, 고른 프로젝트 명령을 실행할 수 없으면 요청을 저장하지 않고 종료 코드 1로 끝난다(fail closed).
저장만 되고 아무도 처리하지 않는 요청을 만들지 않기 위해서다.
"""

import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

from hermes_controller import config as cfg
from hermes_controller import request as req

log = logging.getLogger("hermes_controller")

BIN = Path(__file__).resolve().parents[2] / "bin" / "hermes-controller"
# 번호가 있는 위치만 받는다. 커밋 코멘트는 답할 번호가 없어 버린다.
SUPPORTED_TARGETS = req.TARGETS


def match_route(body, routes):
    """코멘트가 시작하는 접두어의 규칙. 접두어 바로 뒤는 공백이거나 끝이어야 한다("/qatest"는 아님)."""
    stripped = body.strip()
    for route in routes:
        if stripped.startswith(route.prefix):
            rest = stripped[len(route.prefix):]
            if not rest or rest[0].isspace():
                return route
    return None


def decide(payload, settings, now=time.time):
    """받을 요청이면 (규칙, 요청 문서)를, 버릴 요청이면 None을 돌려준다."""
    if not isinstance(payload, dict) or not isinstance(payload.get("event"), dict):
        return None
    event = payload["event"]
    if event.get("kind") != "comment" or event.get("action") != "created":
        return None  # 수정이나 삭제로 일을 다시 시작하지 않는다.
    target = event.get("target")
    number = event.get("number")
    if target not in SUPPORTED_TARGETS or not isinstance(number, int) or isinstance(number, bool):
        return None
    author = event.get("author") or {}
    if author.get("login") not in settings.allowed_authors or author.get("type") != "User":
        return None
    repo = event.get("repo") or {}
    if repo.get("owner") not in settings.allowed_owners:
        return None
    body = event.get("body")
    if not isinstance(body, str):
        return None
    route = match_route(body, settings.routes)
    if route is None:
        return None
    doc = {
        "version": req.VERSION,
        "deliveryId": payload.get("deliveryId"),
        "route": route.name,
        "repo": repo.get("fullName"),
        "pr": number,
        "target": target,
        "author": author.get("login"),
        "url": event.get("url"),
        "commentId": event.get("commentId"),
        "body": body.strip()[: req.MAX_BODY_CHARS],
        "receivedAt": int(now()),
    }
    try:
        req.validated(doc, doc["deliveryId"])
    except req.RequestError:
        return None
    return route, doc


def launch_run(delivery_id, popen=subprocess.Popen):
    """run을 백그라운드로 시작한다. 표준 입출력을 닫고 새 세션으로 띄워 Hermes가 기다리지 않게 한다."""
    popen(
        [sys.executable, str(BIN), "run", delivery_id],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True, close_fds=True, cwd=str(BIN.parent),
    )


def handle(stdin_text, env=None, config_path=None, popen=subprocess.Popen, now=time.time):
    """(종료 코드, 표준 출력 문자열)을 돌려준다."""
    try:
        settings = cfg.load_settings(env, config_path)
    except cfg.ConfigError as exc:
        log.error("intake: 설정을 읽지 못해 요청을 받지 않음 reason=%s", exc.reason)
        return 1, ""
    try:
        payload = json.loads(stdin_text)
    except ValueError:
        return 0, ""
    decided = decide(payload, settings, now)
    if decided is None:
        return 0, ""
    route, doc = decided
    delivery_id = doc["deliveryId"]
    if not os.access(route.command[0], os.X_OK):
        log.error("intake: 프로젝트 명령을 실행할 수 없어 받지 않음 id=%s route=%s", delivery_id, route.name)
        return 1, ""
    try:
        req.write_request(settings.requests_dir, doc)
    except req.RequestError as exc:
        if exc.reason == req.REQUEST_EXISTS:
            log.info("intake: 이미 받은 요청 id=%s", delivery_id)
            return 0, ""
        log.error("intake: 요청 파일을 쓰지 못함 id=%s reason=%s", delivery_id, exc.reason)
        return 1, ""
    try:
        launch_run(delivery_id, popen)
    except OSError as exc:
        log.error("intake: run을 시작하지 못함 id=%s type=%s", delivery_id, type(exc).__name__)
        return 1, ""
    log.info("intake: 받음 id=%s route=%s target=%s", delivery_id, route.name, doc["target"])
    out = {"deliveryId": delivery_id, "route": route.name, "repo": doc["repo"], "pr": doc["pr"],
           "target": doc["target"], "body_chars": len(doc["body"])}
    return 0, json.dumps(out, ensure_ascii=False)
