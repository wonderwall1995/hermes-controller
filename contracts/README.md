# 약속 (contracts)

세 프로젝트는 서로의 코드를 가져오지 않는다. 아래 네 가지 JSON 모양으로만 이어진다. 이 폴더가 원본이다.

```
Hermes ─(웹훅 페이로드)→ controller intake
controller ─ request.v1 ──────────────→ 분석 프로젝트 (예: testgate)
controller ─ provide-request.v1 ──────→ ced-taker ─ provide-response.v1 ─→ controller
controller ─ context.v1 ──────────────→ 분석 프로젝트
분석 프로젝트 ─ result.v1 ─────────────→ controller
```

| 파일 | 누가 쓰고 누가 읽나 | 요점 |
|---|---|---|
| [request.v1.json](request.v1.json) | controller가 쓰고 분석 프로젝트가 읽는다 | 코멘트 원문(`body`)을 그대로 담는다. 문법 해석은 프로젝트가 한다. |
| [provide-request.v1.json](provide-request.v1.json) | controller가 ced-taker의 표준 입력으로 준다 | PR 제목, 설명, 전체 diff |
| [provide-response.v1.json](provide-response.v1.json) | ced-taker가 표준 출력으로 낸다 | 고른 용어 문서 `docs`와 안내 `notices` |
| [context.v1.json](context.v1.json) | controller가 쓰고 분석 프로젝트가 읽는다 | provide-response와 같은 모양. 없을 수도 있다. |
| [result.v1.json](result.v1.json) | 분석 프로젝트가 표준 출력의 마지막 줄로 낸다 | `status`(done, failed, ignored)와 Hermes 세션 이름 |

## 분석 프로젝트를 붙이는 법

1. 명령 하나를 만든다: `<명령> --request <요청 파일> --context <맥락 파일>`. 맥락 파일은 없을 수 있다.
2. 결과를 게시하는 일(예: GitHub 코멘트)은 프로젝트가 스스로 한다.
3. 끝나면 표준 출력의 마지막 줄에 result.v1 모양의 JSON을 낸다.
4. controller 설정의 `routes`에 접두어와 명령을 한 줄 더한다. Hermes 설정은 바꾸지 않는다.
5. 쓰는 약속의 사본을 자기 저장소의 `contracts/`에 두고 그 사본으로 시험한다. `hermes-controller contracts-check <저장소>`로 원본과 같은지 확인한다.

## 바꾸는 법

모양을 바꾸면 `version`을 올리고 새 파일(`*.v2.json`)을 둔다. 옛 버전은 읽는 쪽이 모두 옮겨 간 뒤에 지운다.
참고 문서(`docs`)의 제목과 내용은 GitHub 코멘트에 나가지 않아야 한다. 용어 해석에만 쓴다.
