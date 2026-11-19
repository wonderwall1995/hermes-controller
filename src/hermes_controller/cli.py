"""명령줄. testgate 필터의 분석 시작 명령으로 쓰인다: hermes-controller <배달ID>

필터가 이 명령을 표준 입출력을 닫은 채 백그라운드로 띄우므로 출력은 파일 기록으로만 남는다.
종료 코드: 0 = 래퍼를 시작했다, 1 = 래퍼를 시작하지 못했다, 2 = 배달 ID가 올바르지 않아 아무것도 하지 않았다.
"""

import argparse
import logging
import os
import sys

from hermes_controller import config as cfg
from hermes_controller import pipeline
from hermes_controller.request import valid_delivery_id

LOG_LIMIT_BYTES = 1024 * 1024


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
        handler = logging.NullHandler()  # 기록 때문에 분석이 멈추면 안 된다.
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(handler)
    return handler


def main(argv=None, env=None, **deps):
    parser = argparse.ArgumentParser(prog="hermes-controller")
    parser.add_argument("delivery_id")
    parser.add_argument("--config", help="설정 파일 경로 (기본: 저장소의 local/config.json)")
    args = parser.parse_args(argv)
    if not valid_delivery_id(args.delivery_id):
        sys.stderr.write("오류: bad_delivery_id\n")
        return 2
    env = os.environ if env is None else env
    handler = setup_logging(env)
    try:
        summary = pipeline.run(args.delivery_id, env=env, config_path=args.config, **deps)
    finally:
        logging.getLogger("hermes_controller").removeHandler(handler)
        handler.close()
    return 0 if summary["wrapper"] == "started" else 1
