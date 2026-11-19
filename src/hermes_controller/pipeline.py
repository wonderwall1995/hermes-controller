"""파이프라인 하나: 요청 파일 읽기 → PR 정보 → 해설 → 해설 파일 → testgate 래퍼.

가장 중요한 약속: **어떤 오류가 나도 마지막에 testgate 래퍼를 실행한다.**
해설 준비 전체를 try로 감싸고 래퍼 실행은 finally에 둔다. 그래서 해설을 못 만들어도, PR 정보를 못 가져와도,
예상 밖 오류가 나도, 중단 신호가 와도 분석은 일어난다. 해설을 못 만든 경우는 해설 파일에 사유 코드를 남겨
보고서 비고에 한 줄이 남게 한다(해설 없이 분석함).

기록(로그)에는 배달 ID, 단계, 사유 코드, 오류의 종류와 위치만 쓴다. 요청 내용, PR 제목과 diff, 해설 본문,
서명 키, 오류 메시지는 쓰지 않는다. 예상 밖 예외의 메시지에 요청 내용이 섞일 수 있기 때문이다.
"""

import logging
import os
import subprocess
import traceback
from pathlib import Path

from hermes_controller import config as cfg
from hermes_controller import contextfile
from hermes_controller.cedtaker import CedTakerError, build_request, failure_response, run_ced_taker
from hermes_controller.githubapp import GithubApp, GithubAppError
from hermes_controller.request import RequestError, needs_explanation, read_request, valid_delivery_id

log = logging.getLogger("hermes_controller")

NOT_CONFIGURED = "not_configured"


class _Failed(Exception):
    """해설을 만들지 못했다. 사유 코드만 담는다."""

    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def launch(command, delivery_id):
    """testgate 래퍼를 백그라운드로 시작하고 기다리지 않는다. 표준 입출력을 닫고 새 세션으로 띄운다."""
    subprocess.Popen(
        list(command) + [delivery_id],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True, close_fds=True, cwd=str(Path(command[0]).parent),
    )


def _where(exc):
    """오류가 난 곳(파일 이름, 줄, 함수)만 돌려준다. 메시지는 돌려주지 않는다."""
    frames = traceback.extract_tb(exc.__traceback__)
    if not frames:
        return "?"
    last = frames[-1]
    return f"{Path(last.filename).name}:{last.lineno} {last.name}"


def _explain(settings, request, env, app_factory, ced_runner):
    """PR 정보를 가져와 해설 응답을 만든다. 못 만들면 _Failed(사유 코드)."""
    if not settings.ced_command:
        raise _Failed(NOT_CONFIGURED)
    try:
        app = app_factory(settings.github_app_url, env.get(settings.secret_env, ""), timeout=settings.github_timeout)
        info = app.fetch_pr(request.repo, request.pr, request.commit)
    except GithubAppError as exc:
        raise _Failed(exc.reason) from None
    try:
        return ced_runner(settings.ced_command, build_request(request.repo, info), settings.ced_timeout)
    except CedTakerError as exc:
        raise _Failed(exc.reason) from None


def _write(requests_dir, delivery_id, response):
    """해설 파일을 쓴다. 쓸 수 없으면 기록만 남긴다. 너무 크면 사유만 담은 파일로 바꿔 쓴다."""
    try:
        contextfile.write_context(requests_dir, delivery_id, response)
        return True
    except contextfile.ContextWriteError as exc:
        log.error("해설 파일을 쓰지 못함 id=%s reason=%s", delivery_id, exc.reason)
        if exc.reason == contextfile.CONTEXT_TOO_LARGE:
            return _write(requests_dir, delivery_id, failure_response(exc.reason))
        return False


def _prepare(delivery_id, settings, config_reason, env, app_factory, ced_runner):
    """해설을 준비해 해설 파일을 쓴다. 한 줄짜리 결과 문자열을 돌려준다(시험과 기록용)."""
    try:
        request = read_request(settings.requests_dir, delivery_id)
    except RequestError as exc:
        log.warning("요청 파일을 읽지 못함 id=%s reason=%s", delivery_id, exc.reason)
        return f"request:{exc.reason}"  # 래퍼가 자기 방식으로 처리한다. 쓸 해설 파일도 없다.
    if not needs_explanation(request):
        kind = "free" if request.free else "unsupported"
        log.info("해설 건너뜀 id=%s kind=%s", delivery_id, kind)
        return f"skipped:{kind}"
    try:
        if config_reason:
            raise _Failed(config_reason)
        response = _explain(settings, request, env, app_factory, ced_runner)
    except _Failed as exc:
        log.warning("해설을 만들지 못함 id=%s reason=%s", delivery_id, exc.reason)
        _write(settings.requests_dir, delivery_id, failure_response(exc.reason))
        return f"failed:{exc.reason}"
    wrote = _write(settings.requests_dir, delivery_id, response)
    log.info("해설 준비 id=%s docs=%d notices=%d written=%s", delivery_id, len(response["docs"]), len(response["notices"]), wrote)
    return f"attached:{len(response['docs'])}" if response["docs"] else "empty"


def run(delivery_id, env=None, config_path=None, app_factory=GithubApp, ced_runner=run_ced_taker, launcher=launch):
    """파이프라인을 실행한다. 래퍼를 시작하지 못한 경우를 빼고는 예외를 밖으로 내지 않는다.

    돌려주는 값: {"explanation": 해설 단계의 결과, "wrapper": "started" 또는 "failed"}
    """
    env = os.environ if env is None else env
    summary = {"explanation": "none", "wrapper": "failed"}
    wrapper = cfg.default_wrapper_command(env)  # 설정을 읽지 못해도 알려진 위치
    try:
        config_reason = None
        try:
            settings = cfg.load_settings(env, config_path)
        except cfg.ConfigError as exc:
            config_reason = exc.reason
            settings = cfg.fallback_settings(env)
        wrapper = settings.wrapper_command
        summary["explanation"] = _prepare(delivery_id, settings, config_reason, env, app_factory, ced_runner)
    except Exception as exc:  # noqa: BLE001 - 예상 밖 오류. 분석은 계속해야 한다.
        log.error("해설 준비 중 예상 밖 오류 id=%s type=%s at=%s", delivery_id, type(exc).__name__, _where(exc))
        summary["explanation"] = "error"
    finally:
        # 중단 신호(KeyboardInterrupt)가 와도 여기는 실행된다. 어떤 일이 있어도 분석은 시작한다.
        try:
            launcher(wrapper, delivery_id)
            summary["wrapper"] = "started"
            log.info("래퍼 시작 id=%s explanation=%s", delivery_id, summary["explanation"])
        except OSError as exc:
            log.error("래퍼를 시작하지 못함 id=%s type=%s", delivery_id, type(exc).__name__)
    return summary


__all__ = ["run", "launch", "valid_delivery_id"]
