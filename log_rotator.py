"""
log_rotator.py — 로그 파일 2주 단위 아카이브

실행 조건: 짝수 ISO 주차 월요일 KST 09:00 (UTC 00:00)
동작:
  - 최근 4주 로그는 trader.log 유지
  - 4주 이전 로그는 2주 단위 파일로 분리 저장
    예) trader_2026-W01-W02.log, trader_2026-W03-W04.log
"""
from __future__ import annotations
import logging
import os
from datetime import datetime, timedelta
import config
from logger import get_logger

log = get_logger("log_rotator")


def _parse_entry_date(line: str) -> datetime | None:
    """'[YYYY-MM-DD HH:MM:SS] ...' 형식에서 KST datetime 파싱. 실패 시 None."""
    if not line.startswith('[') or len(line) < 21:
        return None
    try:
        return datetime.strptime(line[1:20], "%Y-%m-%d %H:%M:%S").replace(tzinfo=config.KST)
    except ValueError:
        return None


def _archive_key(dt: datetime) -> tuple:
    """datetime → (ISO 연도, 2주 블록 시작 주차, 종료 주차)
    주차 1-2 → (year, 1, 2), 주차 3-4 → (year, 3, 4), ...
    """
    iso_year, iso_week, _ = dt.isocalendar()
    start = ((iso_week - 1) // 2) * 2 + 1
    return iso_year, start, start + 1


def _reopen_file_handlers(log_path: str):
    """rotate 후 동일 경로를 가리키는 FileHandler를 새 파일로 재오픈."""
    abs_path = os.path.abspath(log_path)
    all_loggers = [logging.getLogger()] + [
        logging.getLogger(name)
        for name in logging.Logger.manager.loggerDict
    ]
    for logger_obj in all_loggers:
        for handler in logger_obj.handlers:
            if not isinstance(handler, logging.FileHandler):
                continue
            if os.path.abspath(handler.baseFilename) != abs_path:
                continue
            handler.acquire()
            try:
                handler.stream.flush()
                handler.stream.close()
                handler.stream = open(abs_path, 'a', encoding=handler.encoding or 'utf-8')
            finally:
                handler.release()


def rotate_logs():
    """
    짝수 ISO 주차 월요일에만 실행.
    최근 4주 로그는 유지, 이전 로그는 2주 단위 아카이브 파일로 분리.
    현재 3개월치가 쌓여 있는 경우 첫 실행 시 여러 개의 아카이브 파일이 생성됩니다.
    """
    now = datetime.now(config.KST)
    iso_week = now.isocalendar()[1]
    if iso_week % 2 != 0:
        return  # 홀수 주차 스킵

    log_path = config.LOG_FILE
    if not os.path.exists(log_path):
        return

    cutoff = now - timedelta(weeks=4)
    log.info(f"📦 로그 로테이션 시작 (ISO {iso_week}주차, 기준일 {cutoff.strftime('%Y-%m-%d')})")

    with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
        raw_lines = f.readlines()

    if not raw_lines:
        log.info("로그 파일 비어있음 — 스킵")
        return

    # 엔트리 단위로 분류. '[' 로 시작하는 줄이 새 엔트리, 나머지는 직전 엔트리에 속함(traceback 등)
    recent_lines: list = []
    archive_chunks: dict = {}  # (year, w_start, w_end) → lines
    entry_buf: list = []
    entry_date = None

    for line in raw_lines:
        dt = _parse_entry_date(line)
        if dt is not None:
            # 이전 엔트리 flush
            if entry_buf:
                if entry_date is None or entry_date >= cutoff:
                    recent_lines.extend(entry_buf)
                else:
                    key = _archive_key(entry_date)
                    archive_chunks.setdefault(key, []).extend(entry_buf)
            entry_buf = [line]
            entry_date = dt
        else:
            entry_buf.append(line)

    # 마지막 엔트리 flush
    if entry_buf:
        if entry_date is None or entry_date >= cutoff:
            recent_lines.extend(entry_buf)
        else:
            key = _archive_key(entry_date)
            archive_chunks.setdefault(key, []).extend(entry_buf)

    if not archive_chunks:
        log.info(f"4주 이전 로그 없음 — 스킵 ({len(recent_lines)}줄 유지)")
        return

    # 아카이브 파일 저장 (기존 파일 있으면 append)
    log_dir = os.path.dirname(os.path.abspath(log_path))
    base = os.path.splitext(os.path.basename(log_path))[0]

    for (year, w_start, w_end), lines in sorted(archive_chunks.items()):
        fname = f"{base}_{year}-W{w_start:02d}-W{w_end:02d}.log"
        fpath = os.path.join(log_dir, fname)
        mode = 'a' if os.path.exists(fpath) else 'w'
        with open(fpath, mode, encoding='utf-8') as f:
            f.writelines(lines)
        log.info(f"  📁 {fname}: {len(lines)}줄")

    # 메인 로그 파일을 최근 4주 내용으로 교체 (atomic rename)
    tmp_path = log_path + ".tmp"
    with open(tmp_path, 'w', encoding='utf-8') as f:
        f.writelines(recent_lines)
    os.replace(tmp_path, log_path)

    # 기존 FileHandler가 구 파일을 가리키므로 재오픈
    _reopen_file_handlers(log_path)

    total_archived = sum(len(v) for v in archive_chunks.values())
    log.info(
        f"✅ 로테이션 완료: {total_archived}줄 → 아카이브 {len(archive_chunks)}개 파일, "
        f"{len(recent_lines)}줄 유지"
    )
