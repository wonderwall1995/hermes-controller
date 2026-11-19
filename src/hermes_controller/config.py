"""설정. Git에서 제외된 로컬 설정 파일(local/config.json)과 환경 변수에서 읽는다.

설정 파일(JSON)의 항목.
  allowed_authors         요청을 받아 줄 GitHub 계정 목록. 필수.
  allowed_repo_owners     요청을 받아 줄 저장소 소유자 목록. 필수.
  routes                  나누기 규칙 목록. 필수. 위에서부터 처음 맞는 규칙을 쓴다.
    name                  규칙 이름(요청 파일에 남는다). 영문, 숫자, -, _
    prefix                코멘트가 이 말로 시작하면 이 규칙을 쓴다. 예: "/qa"
    command               실행할 프로젝트 명령(인자 목록, 첫 인자는 절대 경로)
    context               참이면 실행 전에 ced-taker로 맥락 파일을 만든다. 기본 false
    timeout_seconds       프로젝트 명령을 기다리는 시간. 기본 900
  ced_taker_command       ced-taker 공급자 명령(인자 목록, 첫 인자는 절대 경로). 없으면 맥락을 만들지 않는다.
  github_app_url          github-app 주소. 기본: http://127.0.0.1:3200
  github_app_secret_env   서명 키를 담은 환경 변수의 이름. 기본: TESTGATE_GITHUB_APP_SECRET
  github_timeout_seconds  PR 정보를 가져올 때 기다리는 시간. 기본 15
  ced_timeout_seconds     맥락을 만들 때 기다리는 시간. 기본 20
  hermes_binary           세션 이름을 바꿀 때 쓰는 hermes 명령. 기본: hermes
  hermes_route            Hermes 웹훅 라우트 이름(세션을 찾는 데 쓴다). 기본: github-app

설정이 없거나 틀리면 요청을 받지 않는다(fail closed). 허용 목록 없이 요청을 받으면 안 되기 때문이다.
키 자체는 파일에 쓰지 않는다. 이름만 적고 값은 환경 변수에서 읽는다. 오류에는 사유 코드만 담는다.
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
DEFAULT_PROJECT_TIMEOUT = 900
MAX_TIMEOUT = 120
MAX_PROJECT_TIMEOUT = 3600

CONFIG_MISSING = "config_missing"
CONFIG_UNREADABLE = "config_unreadable"
CONFIG_INVALID = "config_invalid"

_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_URL = re.compile(r"^https?://[^\s/]+(:\d+)?$")
_ROUTE_NAME = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
_PREFIX = re.compile(r"^/[A-Za-z0-9_-]{1,30}$")


class ConfigError(Exception):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class Route:
    name: str
    prefix: str
    command: tuple
    context: bool
    timeout: int


@dataclass(frozen=True)
class Settings:
    allowed_authors: tuple
    allowed_owners: tuple
    routes: tuple
    ced_command: tuple  # 비어 있으면 맥락을 만들지 않는다
    github_app_url: str
    secret_env: str
    github_timeout: int
    ced_timeout: int
    hermes_binary: str
    hermes_route: str
    home: Path

    @property
    def requests_dir(self):
        return requests_dir_for(self.home)

    def route(self, name):
        return next((r for r in self.routes if r.name == name), None)


def hermes_home(env=None):
    env = os.environ if env is None else env
    return Path(env.get("HERMES_HOME", "").strip() or "~/.hermes").expanduser()


def requests_dir_for(home):
    """요청 파일과 맥락 파일을 두는 폴더."""
    return Path(home) / "controller" / "requests"


def default_config_path():
    return Path(__file__).resolve().parents[2] / "local" / "config.json"


def log_path(env=None):
    return hermes_home(env) / "logs" / "controller.log"


def _command(value):
    ok = isinstance(value, list) and value and all(isinstance(v, str) and v for v in value) and os.path.isabs(value[0])
    if not ok:
        raise ConfigError(CONFIG_INVALID)
    return tuple(value)


def _timeout(value, limit=MAX_TIMEOUT):
    if isinstance(value, bool) or not isinstance(value, int) or not 0 < value <= limit:
        raise ConfigError(CONFIG_INVALID)
    return value


def _names(value):
    if not isinstance(value, list) or not value or not all(isinstance(v, str) and v for v in value):
        raise ConfigError(CONFIG_INVALID)
    return tuple(value)


def _routes(value):
    if not isinstance(value, list) or not value:
        raise ConfigError(CONFIG_INVALID)
    routes, seen = [], set()
    for item in value:
        if not isinstance(item, dict):
            raise ConfigError(CONFIG_INVALID)
        name, prefix, context = item.get("name"), item.get("prefix"), item.get("context", False)
        if not isinstance(name, str) or not _ROUTE_NAME.match(name) or name in seen:
            raise ConfigError(CONFIG_INVALID)
        if not isinstance(prefix, str) or not _PREFIX.match(prefix) or not isinstance(context, bool):
            raise ConfigError(CONFIG_INVALID)
        timeout = _timeout(item["timeout_seconds"], MAX_PROJECT_TIMEOUT) if "timeout_seconds" in item else DEFAULT_PROJECT_TIMEOUT
        routes.append(Route(name, prefix, _command(item.get("command")), context, timeout))
        seen.add(name)
    return tuple(routes)


def load_settings(env=None, config_path=None):
    """설정을 읽는다. 없거나, 읽을 수 없거나, 틀리면 ConfigError."""
    env = os.environ if env is None else env
    path = Path(config_path or env.get(ENV_CONFIG) or default_config_path())
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ConfigError(CONFIG_MISSING) from None
    except (OSError, UnicodeDecodeError):
        raise ConfigError(CONFIG_UNREADABLE) from None
    try:
        data = json.loads(raw)
    except ValueError:
        raise ConfigError(CONFIG_UNREADABLE) from None
    if not isinstance(data, dict):
        raise ConfigError(CONFIG_UNREADABLE)

    url = data.get("github_app_url", DEFAULT_GITHUB_APP_URL)
    if not isinstance(url, str) or not _URL.match(url.rstrip("/")):
        raise ConfigError(CONFIG_INVALID)
    secret_env = data.get("github_app_secret_env", DEFAULT_SECRET_ENV)
    if not isinstance(secret_env, str) or not _ENV_NAME.match(secret_env):
        raise ConfigError(CONFIG_INVALID)
    hermes_binary = data.get("hermes_binary", "hermes")
    hermes_route = data.get("hermes_route", "github-app")
    if not isinstance(hermes_binary, str) or not hermes_binary or not isinstance(hermes_route, str) or not _ROUTE_NAME.match(hermes_route):
        raise ConfigError(CONFIG_INVALID)
    return Settings(
        allowed_authors=_names(data.get("allowed_authors")),
        allowed_owners=_names(data.get("allowed_repo_owners")),
        routes=_routes(data.get("routes")),
        ced_command=_command(data["ced_taker_command"]) if "ced_taker_command" in data else (),
        github_app_url=url.rstrip("/"),
        secret_env=secret_env,
        github_timeout=_timeout(data["github_timeout_seconds"]) if "github_timeout_seconds" in data else DEFAULT_GITHUB_TIMEOUT,
        ced_timeout=_timeout(data["ced_timeout_seconds"]) if "ced_timeout_seconds" in data else DEFAULT_CED_TIMEOUT,
        hermes_binary=hermes_binary,
        hermes_route=hermes_route,
        home=hermes_home(env),
    )
