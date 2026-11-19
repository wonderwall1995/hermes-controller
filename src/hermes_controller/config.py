"""설정. 로컬 설정 파일(Git 제외)과 환경 변수에서 읽는다.

설정이 없거나 틀려도 분석은 일어나야 한다. 그래서 testgate 래퍼의 위치에는 표준 설치 위치라는 기본값이 있고,
설정이 틀리면 해설만 포기하고 기본 위치의 래퍼를 실행한다(fallback_settings).

설정 파일(JSON)의 항목. 모두 선택이지만 ced_taker_command가 없으면 해설을 만들지 않는다.
  wrapper_command         testgate 래퍼를 실행할 명령(인자 목록, 첫 인자는 절대 경로). 기본: <홈>/testgate/testgate-run
  ced_taker_command       ced-taker 공급자 명령(인자 목록, 첫 인자는 절대 경로). 예: ["<경로>/bin/ced-taker", "provide"]
  github_app_url          github-app 주소. 기본: http://127.0.0.1:3200
  github_app_secret_env   서명 키를 담은 환경 변수의 이름. 기본: TESTGATE_GITHUB_APP_SECRET
  github_timeout_seconds  PR 정보를 가져올 때 기다리는 시간. 기본 15
  ced_timeout_seconds     해설을 만들 때 기다리는 시간. 기본 20
키 자체는 파일에 쓰지 않는다. 이름만 적고 값은 환경 변수에서 읽는다. 오류에는 사유 코드만 담고 경로와 값은 담지 않는다.
"""

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

ENV_CONFIG = "HERMES_CONTROLLER_CONFIG"
DEFAULT_GITHUB_APP_URL = "http://127.0.0.1:3200"
DEFAULT_SECRET_ENV = "TESTGATE_GITHUB_APP_SECRET"
DEFAULT_GITHUB_TIMEOUT = 15
DEFAULT_CED_TIMEOUT = 20
MAX_TIMEOUT = 120

CONFIG_UNREADABLE = "config_unreadable"
CONFIG_INVALID = "config_invalid"

_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_URL = re.compile(r"^https?://[^\s/]+(:\d+)?$")


class ConfigError(Exception):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class Settings:
    wrapper_command: tuple
    ced_command: tuple  # 비어 있으면 해설을 만들지 않는다
    github_app_url: str
    secret_env: str
    github_timeout: int
    ced_timeout: int
    requests_dir: Path


def hermes_home(env=None):
    env = os.environ if env is None else env
    return Path(env.get("HERMES_HOME", "").strip() or "~/.hermes").expanduser()


def requests_dir(env=None):
    """testgate가 요청 파일을 두는 폴더. 해설 파일도 여기에 둔다."""
    return hermes_home(env) / "testgate" / "requests"


def default_wrapper_command(env=None):
    return (str(hermes_home(env) / "testgate" / "testgate-run"),)


def default_config_path():
    return Path(__file__).resolve().parents[2] / "local" / "config.json"


def log_path(env=None):
    return hermes_home(env) / "logs" / "controller.log"


def fallback_settings(env=None):
    """설정을 읽을 수 없을 때 쓰는 값. 래퍼는 실행하되 해설은 만들지 않는다."""
    return Settings(
        wrapper_command=default_wrapper_command(env),
        ced_command=(),
        github_app_url=DEFAULT_GITHUB_APP_URL,
        secret_env=DEFAULT_SECRET_ENV,
        github_timeout=DEFAULT_GITHUB_TIMEOUT,
        ced_timeout=DEFAULT_CED_TIMEOUT,
        requests_dir=requests_dir(env),
    )


def _command(value):
    ok = isinstance(value, list) and value and all(isinstance(v, str) and v for v in value) and os.path.isabs(value[0])
    if not ok:
        raise ConfigError(CONFIG_INVALID)
    return tuple(value)


def _timeout(value):
    if isinstance(value, bool) or not isinstance(value, int) or not 0 < value <= MAX_TIMEOUT:
        raise ConfigError(CONFIG_INVALID)
    return value


def load_settings(env=None, config_path=None):
    """설정을 읽는다. 파일이 없으면 기본값이다. 있는데 읽을 수 없거나 틀리면 ConfigError."""
    env = os.environ if env is None else env
    path = Path(config_path or env.get(ENV_CONFIG) or default_config_path())
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return fallback_settings(env)
    except (OSError, UnicodeDecodeError):
        raise ConfigError(CONFIG_UNREADABLE) from None
    try:
        data = json.loads(raw)
    except ValueError:
        raise ConfigError(CONFIG_UNREADABLE) from None
    if not isinstance(data, dict):
        raise ConfigError(CONFIG_UNREADABLE)

    base = fallback_settings(env)
    url = data.get("github_app_url", base.github_app_url)
    if not isinstance(url, str) or not _URL.match(url.rstrip("/")):
        raise ConfigError(CONFIG_INVALID)
    secret_env = data.get("github_app_secret_env", base.secret_env)
    if not isinstance(secret_env, str) or not _ENV_NAME.match(secret_env):
        raise ConfigError(CONFIG_INVALID)
    return Settings(
        wrapper_command=_command(data["wrapper_command"]) if "wrapper_command" in data else base.wrapper_command,
        ced_command=_command(data["ced_taker_command"]) if "ced_taker_command" in data else base.ced_command,
        github_app_url=url.rstrip("/"),
        secret_env=secret_env,
        github_timeout=_timeout(data["github_timeout_seconds"]) if "github_timeout_seconds" in data else base.github_timeout,
        ced_timeout=_timeout(data["ced_timeout_seconds"]) if "ced_timeout_seconds" in data else base.ced_timeout,
        requests_dir=base.requests_dir,
    )
