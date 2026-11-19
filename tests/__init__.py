"""시험 묶음. 로그 설정이 없는 시험에서 경고 메시지가 화면에 섞이지 않게 한다."""

import logging

logging.getLogger("hermes_controller").addHandler(logging.NullHandler())
