# hermes-controller

Hermes에 들어온 PR 코멘트를 받아 **알맞은 분석 프로젝트에 나눠 주는 오케스트레이터**이다. 분석 전에 컬럼 용어집(CED)을 맥락으로 붙인다.

## 왜 만드는가

PR의 diff에는 `balance`, `status` 같은 이름이 나온다. 이름만으로는 이 프로젝트에서의 뜻을 알 수 없다. 그래서 DB 컬럼의 뜻을 사람이 적은 문서(CED)를 ced-taker가 관리하고, 분석 프로젝트(testgate 등)는 그 문서를 용어집으로만 읽는다.

분석 프로젝트와 ced-taker가 서로를 모르게 하려면, 순서를 정하는 쪽이 따로 있어야 한다. 그 일이 이 프로젝트이다. 분석 프로젝트가 늘어도 Hermes 설정은 바꾸지 않고 이 프로젝트의 설정에 한 줄만 더한다.

## 구조

```
GitHub → github-app → Hermes 웹훅
                        │  scripts/ 의 시작 파일 하나 (hermes-controller stub 으로 만든다)
                        v
              hermes-controller intake   허용 계정 확인, 접두어(/qa 등)로 프로젝트 고르기, 요청 파일 저장
                        │  (백그라운드)
                        v
              hermes-controller run
                        │  1) PR 전체 diff를 github-app에서 받아 ced-taker에 묻는다 → 맥락 파일
                        │  2) 프로젝트 명령 실행: --request <요청 파일> --context <맥락 파일>
                        │  3) 프로젝트가 낸 결과로 Hermes 세션 이름을 바꾼다
                        v
              분석 프로젝트 (testgate: 분석하고 PR에 코멘트)
```

이어지는 모양은 [contracts/](contracts/README.md)에 있다. 새 프로젝트를 붙이는 법도 거기에 있다.

## 원칙

- **요청을 받았으면 프로젝트는 반드시 실행한다.** 맥락을 못 만들어도, PR 정보를 못 가져와도 실행한다(`finally`에서 실행). 맥락 파일에 사유 코드가 남는다.
- **받을 수 없으면 처음부터 받지 않는다.** 설정이 없거나 프로젝트 명령을 실행할 수 없으면 요청을 저장하지 않는다(fail closed).
- **코멘트 문법은 프로젝트가 읽는다.** controller는 접두어만 본다.
- **서로의 코드를 가져오지 않는다.** 명령, 파일, API의 약속으로만 부른다. 시험은 가짜 상대로 통과한다.
- **내용은 기록에 남기지 않는다.** 로그에는 배달ID, 단계, 사유 코드만 남는다. 서명 키는 환경 변수 이름만 설정에 적는다.

## 실행

```
pnpm test                                   # 시험
bin/hermes-controller stub                  # Hermes scripts/ 에 둘 시작 파일 내용
bin/hermes-controller contracts-check <저장소>...   # 약속 사본이 원본과 같은지
```

설정은 Git에서 제외된 `local/config.json`이다. 항목은 [config.py](src/hermes_controller/config.py) 맨 위에 있다.

## 지금 상태

- 가짜 상대와 임시 홈으로 intake, run, 맥락, 프로젝트 실행, 세션 이름까지 시험했다.
- 실제 Hermes에는 아직 연결하지 않았다. 시작 파일 등록과 라우트 변경은 사용자 확인 뒤에 한다.

## 공개 저장소 원칙

개인 정보, 접속 정보, 개인 경로, 서명 키를 넣지 않는다. 시험 자료는 모두 가짜이다.
