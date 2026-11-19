"""약속 사본 확인. 원본은 이 저장소의 contracts/ 이다.

다른 저장소는 자기가 쓰는 약속의 사본을 자기 contracts/ 에 두고 그 사본으로 시험한다(서로의 코드나 파일을 직접 읽지 않는다).
이 명령은 사본이 원본과 같은지만 본다. 다르거나 원본에 없는 사본은 문제로 알린다.
"""

from pathlib import Path

ORIGIN = Path(__file__).resolve().parents[2] / "contracts"


def check(repo_dirs, origin=ORIGIN):
    """문제 목록을 돌려준다. 비어 있으면 모든 사본이 원본과 같다."""
    problems = []
    for repo in repo_dirs:
        copies = Path(repo) / "contracts"
        if not copies.is_dir():
            problems.append(f"{repo}: contracts/ 폴더가 없다")
            continue
        for copy in sorted(copies.glob("*.json")):
            source = origin / copy.name
            if not source.is_file():
                problems.append(f"{repo}: {copy.name} 의 원본이 없다")
            elif source.read_bytes() != copy.read_bytes():
                problems.append(f"{repo}: {copy.name} 이 원본과 다르다")
    return problems
