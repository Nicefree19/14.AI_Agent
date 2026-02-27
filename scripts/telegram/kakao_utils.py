# -*- coding: utf-8 -*-
"""
KakaoTalk Chat Data Utility (Text Export Based)
================================================
카카오톡 PC/모바일 대화 내보내기 파일을 파싱하여
P5 키워드 포함 채팅방의 메시지를 조회/검색/요약하는 유틸리티.

데이터 흐름:
  사용자가 카카오톡 채팅방 → "대화 내보내기" → 지정 폴더에 .txt 저장
  → kakao_utils가 자동 인덱싱 → 텔레그램 스킬에서 조회/검색/요약

보안:
  - 로컬 파일만 접근, 네트워크 전송 없음
  - 원본 파일 읽기 전용
"""

import re
import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

log = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
#  상수
# ═══════════════════════════════════════════════════════════════

# 카카오톡 내보내기 파일 감시 폴더
KAKAO_EXPORT_DIR = Path(os.environ.get(
    "KAKAO_EXPORT_DIR",
    os.path.join(os.environ.get("USERPROFILE", ""), "Documents", "KakaoTalk_Export")
))

# 인덱스 파일 (파싱 결과 캐시)
_INDEX_FILENAME = "kakao_chat_index.json"

# P5 필터 키워드 (기본값)
DEFAULT_FILTER = "P5"

# 파싱 패턴 — PC 내보내기
_DATE_PATTERN_PC = re.compile(r'-+ (\d{4}년 \d{1,2}월 \d{1,2}일.*?) -+')
_MSG_PATTERN_PC = re.compile(r'\[(.*?)\] \[(.*?)\] (.*)')

# 파싱 패턴 — 모바일 내보내기
_MSG_PATTERN_MOBILE = re.compile(
    r'(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.\s*(오전|오후)?\s*(\d{1,2}):(\d{2}),\s*(.*?)\s*:\s*(.*)'
)

# 메모리 캐시
_cache: Dict[str, Any] = {}


# ═══════════════════════════════════════════════════════════════
#  한국어 날짜/시간 파서
# ═══════════════════════════════════════════════════════════════

def _parse_korean_date(date_str: str) -> Optional[datetime]:
    """한국어 날짜 문자열 → datetime."""
    m = re.match(r'(\d{4})년 (\d{1,2})월 (\d{1,2})일', date_str)
    if m:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


def _parse_time(time_str: str, base_date: datetime) -> datetime:
    """시간 문자열 + 기준 날짜 → datetime."""
    time_str = time_str.strip()
    is_pm = "오후" in time_str or "PM" in time_str.upper()
    time_str = re.sub(r'(오전|오후|AM|PM)\s*', '', time_str, flags=re.IGNORECASE).strip()
    m = re.match(r'(\d{1,2}):(\d{2})', time_str)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2))
        if is_pm and hour < 12:
            hour += 12
        elif not is_pm and hour == 12:
            hour = 0
        return base_date.replace(hour=hour, minute=minute, second=0)
    return base_date


# ═══════════════════════════════════════════════════════════════
#  파일 파싱
# ═══════════════════════════════════════════════════════════════

def _read_file_content(filepath: Path) -> Optional[str]:
    """다중 인코딩 시도로 파일 읽기."""
    for enc in ["utf-8", "cp949", "euc-kr", "utf-16"]:
        try:
            return filepath.read_text(encoding=enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
    log.error(f"인코딩 실패: {filepath}")
    return None


def _extract_chat_name_from_file(filepath: Path, content: str) -> str:
    """파일에서 채팅방 이름 추출.

    PC 내보내기 첫 줄: '{chat_name} 님과 카카오톡 대화' 또는
                      '{chat_name} 카카오톡 대화'
    """
    first_line = content.split('\n', 1)[0].strip()
    # "xxx 님과 카카오톡 대화" 패턴
    m = re.match(r'^(.+?)\s*님과\s*카카오톡\s*대화', first_line)
    if m:
        return m.group(1).strip()
    # "xxx 카카오톡 대화" 패턴
    m = re.match(r'^(.+?)\s*카카오톡\s*대화', first_line)
    if m:
        return m.group(1).strip()
    # Fallback: 파일명 사용
    return filepath.stem


def parse_export_file(filepath: Path) -> Dict[str, Any]:
    """카카오톡 내보내기 파일 파싱.

    Returns:
        {"chat_name": str, "messages": List[Dict], "filepath": str,
         "first_ts": str, "last_ts": str, "msg_count": int}
    """
    content = _read_file_content(filepath)
    if not content:
        return {"chat_name": filepath.stem, "messages": [], "filepath": str(filepath),
                "first_ts": "", "last_ts": "", "msg_count": 0}

    chat_name = _extract_chat_name_from_file(filepath, content)
    messages = _parse_pc_format(content)
    if not messages:
        messages = _parse_mobile_format(content)

    first_ts = messages[0]["timestamp"].isoformat() if messages else ""
    last_ts = messages[-1]["timestamp"].isoformat() if messages else ""

    return {
        "chat_name": chat_name,
        "messages": messages,
        "filepath": str(filepath),
        "first_ts": first_ts,
        "last_ts": last_ts,
        "msg_count": len(messages),
    }


def _parse_pc_format(content: str) -> List[Dict]:
    """PC 내보내기 형식 파싱."""
    messages = []
    current_date = datetime.now()
    last_msg = None

    for line in content.splitlines():
        line_s = line.strip()
        if not line_s:
            continue

        date_match = _DATE_PATTERN_PC.search(line_s)
        if date_match:
            parsed = _parse_korean_date(date_match.group(1))
            if parsed:
                current_date = parsed
            continue

        msg_match = _MSG_PATTERN_PC.match(line_s)
        if msg_match:
            name, time_str, text = msg_match.groups()
            ts = _parse_time(time_str, current_date)
            last_msg = {
                "sender": name,
                "timestamp": ts,
                "text": text,
            }
            messages.append(last_msg)
        elif last_msg and line_s:
            # 이전 메시지의 연속 줄 (줄바꿈 포함 메시지)
            last_msg["text"] += "\n" + line_s

    return messages


def _parse_mobile_format(content: str) -> List[Dict]:
    """모바일 내보내기 형식 파싱."""
    messages = []
    for line in content.splitlines():
        line_s = line.strip()
        if not line_s:
            continue
        m = _MSG_PATTERN_MOBILE.match(line_s)
        if m:
            year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
            ampm = m.group(4) or ""
            hour, minute = int(m.group(5)), int(m.group(6))
            if "오후" in ampm and hour < 12:
                hour += 12
            elif "오전" in ampm and hour == 12:
                hour = 0
            messages.append({
                "sender": m.group(7),
                "timestamp": datetime(year, month, day, hour, minute),
                "text": m.group(8),
            })
    return messages


# ═══════════════════════════════════════════════════════════════
#  인덱스 관리
# ═══════════════════════════════════════════════════════════════

def _get_index_path() -> Path:
    """인덱스 파일 경로."""
    return KAKAO_EXPORT_DIR / _INDEX_FILENAME


def _load_index() -> Dict[str, Any]:
    """인덱스 로드 (캐시 우선)."""
    if "index" in _cache:
        return _cache["index"]
    idx_path = _get_index_path()
    if idx_path.exists():
        try:
            data = json.loads(idx_path.read_text(encoding="utf-8"))
            _cache["index"] = data
            return data
        except Exception as e:
            log.warning(f"인덱스 로드 실패: {e}")
    return {"chats": {}, "updated_at": ""}


def _save_index(index: Dict[str, Any]):
    """인덱스 저장."""
    index["updated_at"] = datetime.now().isoformat()
    idx_path = _get_index_path()
    idx_path.parent.mkdir(parents=True, exist_ok=True)
    idx_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    _cache["index"] = index


def refresh_index(filter_keyword: str = DEFAULT_FILTER) -> Dict[str, Any]:
    """내보내기 폴더를 스캔하여 인덱스 갱신.

    Args:
        filter_keyword: 채팅방 이름 필터 (기본: "P5")

    Returns:
        {"chats": {filename: {chat_name, msg_count, first_ts, last_ts, filepath}},
         "total_p5": int, "total_files": int}
    """
    if not KAKAO_EXPORT_DIR.exists():
        KAKAO_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        return {"chats": {}, "total_p5": 0, "total_files": 0, "updated_at": ""}

    index = {"chats": {}, "updated_at": ""}
    total_files = 0
    total_p5 = 0

    for fp in sorted(KAKAO_EXPORT_DIR.glob("*.txt")):
        total_files += 1
        parsed = parse_export_file(fp)
        chat_name = parsed["chat_name"]

        # P5 필터: 파일명 또는 채팅방 이름에 키워드 포함
        if filter_keyword and filter_keyword.upper() not in chat_name.upper():
            if filter_keyword.upper() not in fp.name.upper():
                continue

        total_p5 += 1
        index["chats"][fp.name] = {
            "chat_name": chat_name,
            "msg_count": parsed["msg_count"],
            "first_ts": parsed["first_ts"],
            "last_ts": parsed["last_ts"],
            "filepath": str(fp),
        }

    _save_index(index)
    return {
        "chats": index["chats"],
        "total_p5": total_p5,
        "total_files": total_files,
        "updated_at": index["updated_at"],
    }


# ═══════════════════════════════════════════════════════════════
#  채팅방 목록
# ═══════════════════════════════════════════════════════════════

def list_chat_rooms(filter_keyword: str = DEFAULT_FILTER,
                    limit: int = 50) -> List[Dict[str, Any]]:
    """P5 키워드 포함 채팅방 목록 반환.

    Returns:
        [{"chat_name", "msg_count", "last_ts", "filepath", "filename"}]
        최근 내보내기 순 정렬
    """
    idx = _load_index()
    if not idx.get("chats"):
        idx_result = refresh_index(filter_keyword)
        idx = _load_index()

    rooms = []
    for filename, info in idx.get("chats", {}).items():
        # 추가 필터
        if filter_keyword:
            if (filter_keyword.upper() not in info["chat_name"].upper()
                    and filter_keyword.upper() not in filename.upper()):
                continue
        rooms.append({
            "chat_name": info["chat_name"],
            "msg_count": info["msg_count"],
            "last_ts": info.get("last_ts", ""),
            "first_ts": info.get("first_ts", ""),
            "filepath": info["filepath"],
            "filename": filename,
        })

    # 최근 메시지 순 정렬
    rooms.sort(key=lambda r: r.get("last_ts", ""), reverse=True)
    return rooms[:limit]


# ═══════════════════════════════════════════════════════════════
#  메시지 읽기
# ═══════════════════════════════════════════════════════════════

def get_chat_messages(chat_name_or_file: str,
                      limit: int = 50,
                      since_hours: int = 0) -> List[Dict[str, Any]]:
    """특정 채팅방의 메시지 조회.

    Args:
        chat_name_or_file: 채팅방 이름(부분 매치) 또는 파일명
        limit: 최대 메시지 수 (0=전체)
        since_hours: N시간 이내 메시지만 (0=전체)

    Returns:
        [{"sender", "text", "timestamp", "chat_name"}]
    """
    target_file = _find_chat_file(chat_name_or_file)
    if not target_file:
        return []

    parsed = parse_export_file(Path(target_file))
    messages = parsed["messages"]

    # 시간 필터
    if since_hours > 0:
        cutoff = datetime.now() - timedelta(hours=since_hours)
        messages = [m for m in messages if m["timestamp"] >= cutoff]

    # 최근 N개
    if limit > 0:
        messages = messages[-limit:]

    return [
        {
            "sender": m["sender"],
            "text": m["text"],
            "timestamp": m["timestamp"].isoformat(),
            "chat_name": parsed["chat_name"],
        }
        for m in messages
    ]


def _find_chat_file(query: str) -> Optional[str]:
    """채팅방 이름 또는 파일명으로 파일 경로 찾기."""
    # 직접 파일 경로인 경우
    if os.path.isfile(query):
        return query

    idx = _load_index()
    if not idx.get("chats"):
        refresh_index()
        idx = _load_index()

    query_upper = query.upper()

    # 1차: 정확한 파일명 매치
    for filename, info in idx.get("chats", {}).items():
        if filename.upper() == query_upper:
            return info["filepath"]

    # 2차: 채팅방 이름 부분 매치
    best_match = None
    best_score = 0
    for filename, info in idx.get("chats", {}).items():
        name = info["chat_name"].upper()
        if query_upper in name:
            # 매치 길이 비율이 높을수록 좋은 매치
            score = len(query_upper) / max(len(name), 1)
            if score > best_score:
                best_score = score
                best_match = info["filepath"]

    # 3차: 파일명 부분 매치
    if not best_match:
        for filename, info in idx.get("chats", {}).items():
            if query_upper in filename.upper():
                best_match = info["filepath"]
                break

    return best_match


# ═══════════════════════════════════════════════════════════════
#  메시지 검색
# ═══════════════════════════════════════════════════════════════

def search_messages(keyword: str,
                    filter_keyword: str = DEFAULT_FILTER,
                    limit: int = 20) -> List[Dict[str, Any]]:
    """P5 채팅방 내에서 키워드 검색.

    Args:
        keyword: 검색어
        filter_keyword: 채팅방 필터 (기본: "P5")
        limit: 최대 결과 수

    Returns:
        [{"sender", "text", "timestamp", "chat_name", "filepath"}]
    """
    rooms = list_chat_rooms(filter_keyword, limit=100)
    results = []
    keyword_upper = keyword.upper()

    for room in rooms:
        parsed = parse_export_file(Path(room["filepath"]))
        for msg in parsed["messages"]:
            if keyword_upper in msg["text"].upper() or keyword_upper in msg["sender"].upper():
                results.append({
                    "sender": msg["sender"],
                    "text": msg["text"],
                    "timestamp": msg["timestamp"].isoformat(),
                    "chat_name": room["chat_name"],
                    "filepath": room["filepath"],
                })
                if len(results) >= limit:
                    return results

    # 최근 메시지 우선 정렬
    results.sort(key=lambda r: r["timestamp"], reverse=True)
    return results[:limit]


# ═══════════════════════════════════════════════════════════════
#  요약 / 분석
# ═══════════════════════════════════════════════════════════════

def get_chat_summary(chat_name_or_file: str,
                     hours: int = 24,
                     max_messages: int = 200) -> Dict[str, Any]:
    """채팅방 대화 요약 데이터 생성.

    Returns:
        {"chat_name", "period", "participants": {name: count},
         "topics": [str], "messages": [Dict], "total_count": int}
    """
    messages = get_chat_messages(chat_name_or_file, limit=max_messages, since_hours=hours)
    if not messages:
        return {"chat_name": chat_name_or_file, "period": f"최근 {hours}시간",
                "participants": {}, "topics": [], "messages": [], "total_count": 0}

    chat_name = messages[0]["chat_name"] if messages else chat_name_or_file

    # 참여자 빈도
    participants: Dict[str, int] = {}
    for m in messages:
        participants[m["sender"]] = participants.get(m["sender"], 0) + 1

    # 핵심 키워드 추출 (간이)
    all_text = " ".join(m["text"] for m in messages)
    topics = _extract_topics(all_text)

    return {
        "chat_name": chat_name,
        "period": f"최근 {hours}시간",
        "participants": dict(sorted(participants.items(), key=lambda x: -x[1])),
        "topics": topics,
        "messages": messages,
        "total_count": len(messages),
    }


def _extract_topics(text: str, top_n: int = 5) -> List[str]:
    """간이 토픽 추출 (한국어/영문 키워드)."""
    # SEN-XXX 이슈 참조
    sen_refs = re.findall(r'SEN-\d{3,}', text, re.IGNORECASE)

    # 2글자 이상 한국어 단어 빈도
    words = re.findall(r'[가-힣]{2,}', text)
    # 불용어 제외
    stopwords = {"있습니다", "합니다", "그리고", "하겠습", "감사합", "네네",
                 "확인", "부탁", "드립니다", "했습니다", "됩니다", "입니다",
                 "사진", "이모티콘", "하는", "하고", "그래서", "그런데",
                 "오늘", "내일", "어제", "지금", "여기", "거기"}
    filtered = [w for w in words if w not in stopwords and len(w) >= 2]

    freq: Dict[str, int] = {}
    for w in filtered:
        freq[w] = freq.get(w, 0) + 1

    top_words = sorted(freq.items(), key=lambda x: -x[1])[:top_n]
    result = list(set(sen_refs))  # SEN 참조 우선
    result.extend(w for w, _ in top_words if w not in result)
    return result[:top_n]


# ═══════════════════════════════════════════════════════════════
#  가용성 확인
# ═══════════════════════════════════════════════════════════════

def is_available() -> Tuple[bool, str]:
    """카카오톡 데이터 접근 가능 여부 확인.

    Returns:
        (available: bool, message: str)
    """
    if not KAKAO_EXPORT_DIR.exists():
        KAKAO_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        return False, (
            f"내보내기 폴더가 비어 있습니다.\n"
            f"카카오톡에서 P5 채팅방 → ☰ → 대화 내보내기 → "
            f"'{KAKAO_EXPORT_DIR}' 폴더에 저장해주세요."
        )

    txt_files = list(KAKAO_EXPORT_DIR.glob("*.txt"))
    if not txt_files:
        return False, (
            f"내보내기 폴더에 .txt 파일이 없습니다.\n"
            f"카카오톡에서 채팅방 → ☰ → 대화 내보내기 후\n"
            f"'{KAKAO_EXPORT_DIR}'에 저장해주세요."
        )

    # P5 파일 확인
    p5_count = 0
    for fp in txt_files:
        content = _read_file_content(fp)
        if content:
            name = _extract_chat_name_from_file(fp, content)
            if DEFAULT_FILTER.upper() in name.upper() or DEFAULT_FILTER.upper() in fp.name.upper():
                p5_count += 1

    if p5_count == 0:
        return False, (
            f"내보내기 파일 {len(txt_files)}개 중 P5 관련 채팅방이 없습니다.\n"
            f"P5 키워드가 포함된 채팅방을 내보내주세요."
        )

    return True, f"P5 채팅방 {p5_count}개 사용 가능"


def get_export_guide() -> str:
    """카카오톡 대화 내보내기 가이드 텍스트."""
    return (
        "📋 카카오톡 대화 내보내기 방법\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n"
        "1. 카카오톡 PC에서 원하는 채팅방 열기\n"
        "2. 우상단 ☰ (서랍) 클릭\n"
        "3. ⚙️ 설정 → '대화 내보내기' 클릭\n"
        "4. 저장 위치를 아래 폴더로 지정:\n"
        f"   📁 {KAKAO_EXPORT_DIR}\n"
        "5. '저장' 클릭\n"
        "\n"
        "💡 팁: P5 관련 채팅방만 내보내면 됩니다.\n"
        "내보내기 후 '카톡 목록' 명령으로 확인하세요."
    )


# ═══════════════════════════════════════════════════════════════
#  클립보드 텍스트 파싱 (라이브 읽기용)
# ═══════════════════════════════════════════════════════════════

def parse_clipboard_text(clipboard_text: str) -> List[Dict]:
    """클립보드에서 복사한 카카오톡 텍스트 파싱.

    카카오톡 PC에서 Ctrl+A → Ctrl+C로 복사한 텍스트는
    PC 내보내기(.txt)와 동일한 형식이므로 _parse_pc_format()을 재사용.

    Args:
        clipboard_text: 클립보드에서 가져온 카카오톡 대화 텍스트

    Returns:
        [{"sender", "text", "timestamp", "chat_name"}] 형태의 메시지 리스트
    """
    if not clipboard_text or not clipboard_text.strip():
        return []
    return _parse_pc_format(clipboard_text)
