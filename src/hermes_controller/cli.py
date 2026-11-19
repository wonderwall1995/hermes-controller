"""명령줄.

  hermes-controller intake              Hermes 필터. 표준 입력의 웹훅 페이로드를 받는다.
  hermes-controller run <배달ID>        요청 하나를 처리한다(intake가 백그라운드로 시작).
  hermes-controller stub                Hermes의 scripts/ 에 둘 시작 파일의 내용을 출력한다.
  hermes-controller contracts-check <저장소>...   다른 저장소의 약속 사본이 원본과 같은지 본다.

intake와 run의 출력은 기록 파일(<홈>/logs/controller.log)로만 남는다.
"""

import argparse
import logging
import os
import sys

from hermes_controller import config as cfg
from hermes_controller import contracts, intake, pipeline
from hermes_controller.request import valid_delivery_id

LOG_LIMIT_BYTES = 1024 * 1024

STUB = '''"""hermes-controller 시작 파일. Hermes 웹훅 라우트의 script로 쓴다.

Hermes는 scripts/ 폴더 안의 진짜 파일만 필터로 실행한다(링크는 거부). 이 파일은 저장소의 intake를 실행할 뿐이다.
코드는 모두 저장소에 있다. 다시 만들려면: hermes-controller stub > <홈>/scripts/hermes_controller_filter.py
"""
import os
import sys

BIN = {bin!r}
os.execv(sys.executable, [sys.executable, BIN, "intake"])
'''


def setup_logging(env=None):
    """기록을 <홈>/logs/controller.log에 남긴다. 소유자만 읽게 하고, 1MB를 넘으면 한 세대만 남긴다. 쓸 수 없으면 버린다."""
    log = logging.getLogger("hermes_controller")
    log.setLevel(logging.INFO)
    path = cfg.log_path(env)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > LOG_LIMIT_BYTES:
            os.replace(path, str(path) + ".1")
        old = os.umask(0o077)
        try:
            handler = logging.FileHandler(path, encoding="utf-8")
        finally:
            os.umask(old)
    except OSError:
        handler = logging.NullHandler()  # 기록 때문에 일이 멈추면 안 된다.
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(handler)
    return handler


def _with_log(env, work):
    handler = setup_logging(env)
    try:
        return work()
    finally:
        logging.getLogger("hermes_controller").removeHandler(handler)
        handler.close()


def main(argv=None, env=None, stdin=None, stdout=None, **deps):
    parser = argparse.ArgumentParser(prog="hermes-controller")
    parser.add_argument("--config", help="설정 파일 경로 (기본: 저장소의 local/config.json)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("intake", help="Hermes 필터: 표준 입력의 웹훅 페이로드를 받는다")
    run_p = sub.add_parser("run", help="요청 하나를 처리한다")
    run_p.add_argument("delivery_id")
    sub.add_parser("stub", help="Hermes scripts/ 에 둘 시작 파일 내용을 출력한다")
    check_p = sub.add_parser("contracts-check", help="다른 저장소의 약속 사본이 원본과 같은지 본다")
    check_p.add_argument("repos", nargs="+")
    args = parser.parse_args(argv)
    env = os.environ if env is None else env
    stdin = sys.stdin if stdin is None else stdin
    stdout = sys.stdout if stdout is None else stdout

    if args.command == "stub":
        stdout.write(STUB.format(bin=str(intake.BIN)))
        return 0
    if args.command == "contracts-check":
        problems = contracts.check(args.repos)
        for line in problems:
            stdout.write(line + "\n")
        if not problems:
            stdout.write("모든 사본이 원본과 같다\n")
        return 1 if problems else 0
    if args.command == "intake":
        code, out = _with_log(env, lambda: intake.handle(stdin.read(), env=env, config_path=args.config, **deps))
        if out:
            stdout.write(out)
        return code
    if not valid_delivery_id(args.delivery_id):
        sys.stderr.write("오류: bad_delivery_id\n")
        return 2
    summary = _with_log(env, lambda: pipeline.run(args.delivery_id, env=env, config_path=args.config, **deps))
    return 0 if summary["project"] in ("done", "ignored") else 1
