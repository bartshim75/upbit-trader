# 작업 정책 (Claude 전용)

이 파일은 Claude가 이 프로젝트에서 작업할 때 반드시 지켜야 하는 규칙을 모아둔 곳입니다. 새 채팅창에서 시작해도 자동으로 로드됩니다.

## 🔒 반영 전 필수 점검 (Must)

**코드 수정 후 깃허브에 반영(push)하기 직전에는 반드시 "정상 실행이 되는 코드인지" 체크를 먼저 해야 한다.**

push 전에 최소한 다음을 수행한다:

1. **문법/임포트 검증** — 수정한 모든 .py 파일을 `python -m py_compile <files>`로 컴파일.
2. **핵심 동작 스모크 테스트** — 수정한 함수/모듈을 실제로 호출하거나 임포트해서 의도대로 동작하는지 확인. 가능한 한 실제 결과값을 출력해 눈으로 확인한다.
3. **부수효과 점검** — 미사용 import, 깨진 참조, 사라진 심볼이 없는지 grep/lint로 확인.
4. **검증 결과를 사용자에게 표 형태로 보고** — 어떤 항목을 어떻게 검증했고, 결과가 OK인지 명시.

검증 단계에서 실패가 있으면 push하지 않고 먼저 고친다. 로컬 환경 한계로 일부 검증이 불가능한 경우(예: streamlit이 dev 머신에 없음)에는 그 사실을 명시하고, 대체 검증 방법(py_compile 통과, 변경 라인 review 등)으로 보완한 뒤 그 한계를 사용자에게 함께 보고한다.

이 정책은 사용자가 명시적으로 "검증 생략하고 바로 push"라고 지시한 경우에만 예외적으로 건너뛸 수 있다.

## 🕘 시간대 정책

이 프로젝트의 모든 기록/표시 시각은 **KST (Asia/Seoul, UTC+9)** 기준이다. 새 코드를 추가할 때 `datetime.now()` 또는 `date.today()`를 그대로 쓰지 말고 `datetime.now(config.KST)` / `datetime.now(config.KST).date()`를 사용한다. VM이 UTC라 naive `now()`는 UTC를 반환한다.

## 📦 배포 환경

- 운영: GCP free tier VM (Ubuntu 22.04). systemd가 `upbit-trader` / `upbit-dashboard` 두 서비스를 관리하며 부팅 시 자동 시작 + 크래시 시 자동 재시작.
- 배포 경로: 로컬에서 `git push origin main` → GitHub Actions가 VM에 SSH 접속 후 `git pull` + `systemctl restart` 수행.
- 자세한 운영 명령어와 자동 재시작 동작은 [README.md](README.md) 참고.
