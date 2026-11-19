"""run: 요청 하나를 끝까지 처리한다. 요청 파일 → (맥락) → 프로젝트 실행 → 세션 이름.

가장 중요한 약속: **요청 파일과 규칙이 올바르면, 어떤 오류가 나도 프로젝트를 실행한다.**
맥락 준비 전체를 try로 감싸고 프로젝트 실행은 finally에 둔다. 맥락을 못 만들면 맥락 파일에 사유 코드만 남겨
프로젝트가 "맥락 없이 일했다"는 것을 알 수 있게 한다.

맥락은 규칙의 context가 참이고 PR 대화창의 요청(target=pull_request)일 때만 만든다. 늘 PR 전체 diff로 고른다.
controller는 코멘트 문법(커밋ID 등)을 모르기 때문이다. 용어집은 PR 전체 기준이어도 문제가 없다.

기록(로그)에는 배달ID, 단계, 사유 코드, 오류의 종류와 위치만 쓴다. 요청 내용, PR 제목과 diff, 맥락 본문,
서명 키, 오류 메시지는 쓰지 않는다.
"""

import logging
import os
import traceback
from pathlib import Path

from hermes_controller import config as cfg
from hermes_controller import contextfile, project, session
from hermes_controller.cedtaker import CedTakerError, build_request, failure_response, run_ced_taker
from hermes_controller.githubapp import GithubApp, GithubAppError
from hermes_controller.request import RequestError, read_request, request_path

log = logging.getLogger("hermes_controller")

NOT_CONFIGURED = "not_configured"


class _Failed(Exception):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def _where(exc):
    frames = traceback.extract_tb(exc.__traceback__)
    if not frames:
        return "?"
    last = frames[-1]
    return f"{Path(last.filename).name}:{last.lineno} {last.name}"


def _explain(settings, request, env, app_factory, ced_runner):
    if not settings.ced_command:
        raise _Failed(NOT_CONFIGURED)
    try:
        app = app_factory(settings.github_app_url, env.get(settings.secret_env, ""), timeout=settings.github_timeout)
        info = app.fetch_pr(request.repo, request.pr, None)
    except GithubAppError as exc:
        raise _Failed(exc.reason) from None
    try:
        return ced_runner(settings.ced_command, build_request(request.repo, info), settings.ced_timeout)
    except CedTakerError as exc:
        raise _Failed(exc.reason) from None


def _write(requests_dir, delivery_id, response):
    try:
        contextfile.write_context(requests_dir, delivery_id, response)
        return True
    except contextfile.ContextWriteError as exc:
        log.error("맥락 파일을 쓰지 못함 id=%s reason=%s", delivery_id, exc.reason)
        if exc.reason == contextfile.CONTEXT_TOO_LARGE:
            return _write(requests_dir, delivery_id, failure_response(exc.reason))
        return False


def _prepare(settings, request, route, env, app_factory, ced_runner):
    if not route.context:
        return "skipped:route"
    if request.target != "pull_request":
        return "skipped:target"
    try:
        response = _explain(settings, request, env, app_factory, ced_runner)
    except _Failed as exc:
        log.warning("맥락을 만들지 못함 id=%s reason=%s", request.delivery_id, exc.reason)
        _write(settings.requests_dir, request.delivery_id, failure_response(exc.reason))
        return f"failed:{exc.reason}"
    _write(settings.requests_dir, request.delivery_id, response)
    log.info("맥락 준비 id=%s docs=%d", request.delivery_id, len(response["docs"]))
    return f"attached:{len(response['docs'])}" if response["docs"] else "empty"


def run(delivery_id, env=None, config_path=None, app_factory=GithubApp, ced_runner=run_ced_taker,
        project_runner=project.run_project, renamer=session.rename):
    """요청 하나를 처리하고 요약 사전을 돌려준다. 예외를 밖으로 내지 않는다.

    {"context": 맥락 단계 결과, "project": 프로젝트 결과 또는 사유, "rename": 세션 이름 결과}
    """
    env = os.environ if env is None else env
    summary = {"context": "none", "project": "not_started", "rename": "skipped"}
    try:
        settings = cfg.load_settings(env, config_path)
    except cfg.ConfigError as exc:
        log.error("run: 설정을 읽지 못함 id=%s reason=%s", delivery_id, exc.reason)
        return summary
    try:
        request = read_request(settings.requests_dir, delivery_id)
    except RequestError as exc:
        log.error("run: 요청 파일을 읽지 못함 id=%s reason=%s", delivery_id, exc.reason)
        return summary
    route = settings.route(request.route)
    if route is None:
        log.error("run: 규칙이 없음 id=%s route=%s", delivery_id, request.route)
        return summary

    result = None
    try:
        summary["context"] = _prepare(settings, request, route, env, app_factory, ced_runner)
    except Exception as exc:  # noqa: BLE001 - 예상 밖 오류. 프로젝트는 그래도 실행한다.
        log.error("맥락 준비 중 예상 밖 오류 id=%s type=%s at=%s", delivery_id, type(exc).__name__, _where(exc))
        summary["context"] = "error"
    finally:
        # 중단 신호(KeyboardInterrupt)가 와도 여기는 실행된다.
        try:
            result = project_runner(route.command, request_path(settings.requests_dir, delivery_id),
                                    contextfile.context_path(settings.requests_dir, delivery_id), route.timeout)
            summary["project"] = result["status"]
        except project.ProjectError as exc:
            summary["project"] = exc.reason
        log.info("프로젝트 끝 id=%s route=%s context=%s project=%s", delivery_id, route.name, summary["context"], summary["project"])

    if result and result["session_name"]:
        try:
            summary["rename"] = renamer(settings.home, settings.hermes_route, delivery_id, result["session_name"], settings.hermes_binary)
        except Exception as exc:  # noqa: BLE001
            log.error("세션 이름 변경 중 오류 id=%s type=%s", delivery_id, type(exc).__name__)
            summary["rename"] = "failed"
    log.info("run 끝 id=%s rename=%s", delivery_id, summary["rename"])
    return summary
