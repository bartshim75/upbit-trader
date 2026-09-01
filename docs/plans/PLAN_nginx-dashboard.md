# Nginx 기반 대시보드 전환 계획

## PROGRESS PROTOCOL
After each phase:
1. ✅ Check off completed tasks
2. 🔍 Verify ALL quality gate items pass
3. 📝 Document learnings in Notes section
4. ➡️ Only then start the next phase

⛔ Do not skip quality gates or proceed with failing checks.

## 목표

Streamlit의 전체 페이지 재실행을 제거하고, Nginx 뒤에서 동작하는 FastAPI와 순수 HTML/CSS/JS 대시보드로 교체한다. 트레이딩 프로세스와 데이터 파일 형식은 변경하지 않는다.

## Phase 1: 데이터 API

**Goal**: 기존 화면과 동일한 정보를 캐시된 JSON API로 제공한다.
**Duration**: 2–3시간
**Tasks**:
- [x] KPI, 포지션, 시장 상태, 차트, 거래 내역, 로그 응답 구현
- [x] 비밀번호 세션 인증과 CSV 다운로드 구현
- [x] Upbit 조회 결과를 TTL 동안 재사용
**Quality Gate**: 수정 Python 파일이 컴파일되고 기존 계산식과 응답값이 일치한다.
**Dependencies**: 기존 JSON/CSV 파일 및 `upbit_api.py`, `strategy.py`, `mean_revert.py`
**Rollback**: 기존 Streamlit 버전 커밋으로 되돌린다.

## Phase 2: 정적 웹 화면

**Goal**: 현재 대시보드 기능을 반응형 HTML/CSS/JS 화면으로 제공한다.
**Duration**: 3–4시간
**Tasks**:
- [x] 로그인, 종목 탭, KPI, 포지션, 시장 상태 구현
- [x] 손익 차트, 거래 필터/표, CSV 다운로드, 로그 구현
- [x] 자동 갱신과 오류/로딩 상태 구현
**Quality Gate**: 데스크톱·모바일 레이아웃에서 모든 API 데이터가 표시된다.
**Dependencies**: Phase 1 API 계약
**Rollback**: 정적 웹 디렉터리를 제거하고 이전 서비스를 재시작한다.

## Phase 3: Nginx 및 서비스 전환

**Goal**: Nginx를 공개 진입점으로 사용하고 API는 localhost에만 바인딩한다.
**Duration**: 2–3시간
**Tasks**:
- [x] Nginx 프록시와 정적 파일 설정 추가
- [x] systemd 서비스를 Uvicorn 실행 방식으로 변경
- [x] 배포 워크플로와 운영 문서 갱신
**Quality Gate**: 외부에서는 Nginx만 접근 가능하고 재부팅 후 두 서비스가 자동 시작된다.
**Dependencies**: Phase 1–2
**Rollback**: 이전 systemd 서비스 정의와 8501 포트 접속으로 복구한다.

## Phase 4: 검증 및 전환

**Goal**: 변경 범위와 기본 안정성을 확인하고 배포 가능한 상태로 만든다.
**Duration**: 1–2시간
**Tasks**:
- [x] 변경 Python 파일 `py_compile`
- [x] 의도하지 않은 변경 파일 확인
- [ ] 사용자 승인 시 스모크 테스트 수행
**Quality Gate**: 필수 검증이 통과하고 실패 항목이 없다.
**Dependencies**: Phase 1–3
**Rollback**: 배포하지 않고 실패 원인을 수정한다.

## 위험

| 위험 | 확률 | 영향 | 대응 |
|---|---|---|---|
| API 응답과 기존 화면 계산 불일치 | 중 | 높음 | 기존 계산식을 그대로 이전하고 스모크 비교 |
| Nginx 설정 후 접속 불가 | 중 | 중 | Uvicorn localhost 직접 확인 후 Nginx 전환 |
| 인증 쿠키가 HTTP/HTTPS 환경에서 다르게 동작 | 중 | 높음 | 프록시 프로토콜을 반영하고 HttpOnly/SameSite 적용 |
| Upbit 장애로 초기 응답 지연 | 중 | 중 | TTL 캐시 및 부분 오류 메시지 제공 |

## Notes & Learnings

- 기존 Streamlit은 자동 갱신 때 전체 스크립트와 모든 UI를 다시 구성한다.
- 새 API는 전체 대시보드 스냅샷을 TTL 동안 공유해 중복 거래소 호출을 막는다.
- 정적 화면은 외부 차트 라이브러리 없이 Canvas로 그려 초기 다운로드와 런타임 비용을 줄였다.
- 최초 전환 전에는 기존 Streamlit 서비스를 재시작하지 않도록 배포 워크플로에서 감지한다.
