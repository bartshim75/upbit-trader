# API Timeout 및 Scheduler Hang 방지 패치

## 개요
업비트 API 호출이 무기한 대기할 경우 단일 스케줄 루프가 멈춰 이후 매매가 실행되지 않는 문제를 방지했습니다. API 기본 timeout, job 단위 timeout, scheduler heartbeat 로그를 추가했습니다.

## 주요 변경사항
- 개발한 것: 매매 사이클/exit 체크 timeout 보호 추가
- 수정한 것: pyupbit 내부 requests 호출에 기본 timeout 적용
- 개선한 것: 10분마다 scheduler heartbeat 로그로 루프 생존 여부 확인

## 결과
- ✅ py_compile 통과
- ✅ 스모크 테스트는 사용자 요청에 따라 생략

## 다음 단계
- VM 배포 후 journalctl에서 heartbeat와 timeout 로그 발생 여부 모니터링
