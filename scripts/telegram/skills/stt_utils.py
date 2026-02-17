#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
STT (Speech-to-Text) 유틸리티 — Whisper API + P5 도메인 오류 보정

음성/오디오 파일을 텍스트로 변환하고, 건설 프로젝트 도메인에 맞게 보정한다.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Set

# ─── 경로 설정 ───────────────────────────────────────────────
_SKILLS_DIR = Path(__file__).resolve().parent           # scripts/telegram/skills/
_TELEGRAM_DIR = _SKILLS_DIR.parent                       # scripts/telegram/
_PROJECT_ROOT = _TELEGRAM_DIR.parent.parent              # 14.AI_Agent/


# ═══════════════════════════════════════════════════════════════
#  1. Whisper API STT
# ═══════════════════════════════════════════════════════════════

def transcribe_audio(audio_path: str, language: str = "ko") -> str:
    """Whisper API로 오디오 파일을 텍스트로 변환.

    Telegram .ogg(Opus) 직접 지원, 변환 불필요.

    Args:
        audio_path: 오디오 파일 경로
        language: 언어 코드 (기본 "ko")

    Returns:
        변환된 텍스트 (실패 시 에러 메시지 문자열)
    """
    api_key = _get_openai_api_key()
    if not api_key:
        return "[STT 오류] OPENAI_API_KEY가 .env에 설정되지 않았습니다."

    if not os.path.isfile(audio_path):
        return f"[STT 오류] 파일을 찾을 수 없습니다: {audio_path}"

    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)

        with open(audio_path, "rb") as f:
            response = client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                language=language,
                response_format="text",
            )

        text = response.strip() if isinstance(response, str) else str(response).strip()
        if not text:
            return "[STT 오류] 음성 인식 결과가 비어 있습니다."

        return text

    except ImportError:
        return "[STT 오류] openai 패키지가 설치되지 않았습니다. pip install openai"
    except Exception as e:
        return f"[STT 오류] Whisper API 호출 실패: {e}"


def _get_openai_api_key() -> Optional[str]:
    """dotenv에서 OPENAI_API_KEY 로드."""
    # 이미 환경변수에 있으면 사용
    key = os.environ.get("OPENAI_API_KEY")
    if key:
        return key

    # .env 파일에서 로드
    try:
        from dotenv import load_dotenv

        env_path = _PROJECT_ROOT / ".env"
        if env_path.exists():
            load_dotenv(env_path)
            return os.environ.get("OPENAI_API_KEY")
    except ImportError:
        pass

    return None


# ═══════════════════════════════════════════════════════════════
#  2. P5 도메인 사전
# ═══════════════════════════════════════════════════════════════

# 한글 발음 → 영문 약어 매핑 (STT 오류 보정)
_PHONETIC_MAP = {
    "피에스알씨": "PSRC",
    "피에스아르씨": "PSRC",
    "에이치엠비": "HMB",
    "에이에프씨": "AFC",
    "비아이엠": "BIM",
    "이피": "EP",
    "피씨": "PC",
    "에프씨씨": "FCC",
    "디엑스에프": "DXF",
    "플렉비": "PLEGB",
}

# 고정 회사명
_COMPANY_NAMES = {
    "삼성E&A", "삼성이앤에이", "삼성이엔에이",
    "센구조", "센코어테크",
    "이앤디몰", "E&D몰",
    "ENA", "삼우종합건축",
}

# 고정 기술 용어
_TECHNICAL_TERMS = {
    "PSRC", "HMB", "임베디드 플레이트", "EP",
    "샵도면", "Shop DWG", "AFC", "BIM",
    "전단보강", "분리타설", "앵커볼트",
    "슬래브", "기둥", "보", "벽체", "코어",
    "갭플레이트", "스터드", "쉬어커넥터",
    "레벨조정", "그라우팅", "양중",
}

# Zone 패턴
_ZONE_PATTERNS = [
    "1F", "2F", "3F", "4F", "B1", "B2", "RF",
] + [f"{n}열" for n in range(29, 63)]


def load_domain_dictionary() -> Dict[str, Set[str]]:
    """P5 도메인 사전 빌드.

    Returns:
        {"issue_ids": set, "companies": set, "people": set,
         "terms": set, "zones": set, "phonetic": dict}
    """
    domain_dict: Dict[str, any] = {
        "issue_ids": set(),
        "companies": set(_COMPANY_NAMES),
        "people": set(),
        "terms": set(_TECHNICAL_TERMS),
        "zones": set(_ZONE_PATTERNS),
        "phonetic": dict(_PHONETIC_MAP),
    }

    # 이슈 DB에서 동적 로딩
    try:
        from scripts.telegram.skill_utils import load_vault_issues

        issues = load_vault_issues()
        for issue in issues:
            iid = issue.get("issue_id", "")
            if iid:
                domain_dict["issue_ids"].add(iid)
            owner = issue.get("owner", "").strip()
            if owner:
                domain_dict["people"].add(owner)
    except Exception:
        pass

    return domain_dict


def build_correction_prompt(raw_text: str, domain_dict: Dict) -> str:
    """STT 보정용 Claude CLI 프롬프트 생성.

    Args:
        raw_text: Whisper STT 원문
        domain_dict: load_domain_dictionary() 결과

    Returns:
        Claude CLI에 전달할 보정 프롬프트
    """
    # 도메인 사전을 컨텍스트로 변환
    context_parts = []

    issue_ids = sorted(domain_dict.get("issue_ids", set()))
    if issue_ids:
        context_parts.append(f"이슈 ID: {', '.join(issue_ids[:30])}")

    companies = sorted(domain_dict.get("companies", set()))
    if companies:
        context_parts.append(f"회사명: {', '.join(companies)}")

    people = sorted(domain_dict.get("people", set()))
    if people:
        context_parts.append(f"인물: {', '.join(people[:20])}")

    terms = sorted(domain_dict.get("terms", set()))
    if terms:
        context_parts.append(f"기술 용어: {', '.join(terms)}")

    zones = sorted(domain_dict.get("zones", set()))
    if zones:
        context_parts.append(f"Zone/층: {', '.join(zones[:15])}")

    phonetic = domain_dict.get("phonetic", {})
    if phonetic:
        ph_pairs = [f"{k}→{v}" for k, v in phonetic.items()]
        context_parts.append(f"발음 매핑: {', '.join(ph_pairs)}")

    domain_context = "\n".join(context_parts)

    prompt = f"""다음은 P5 복합동 건설 프로젝트 회의/통화의 STT(음성인식) 결과입니다.
건설 도메인 용어와 프로젝트 컨텍스트를 참고하여 STT 오류만 보정해주세요.

[보정 규칙]
1. 의미를 변경하지 말고, STT 인식 오류만 수정
2. 아래 도메인 사전의 용어로 교정 (발음이 비슷한 경우)
3. SEN-xxx 이슈 ID 형식 통일
4. 고유명사(회사명, 인물명) 정확도 향상
5. 보정된 텍스트만 출력 (설명 없이)

[프로젝트 도메인 사전]
{domain_context}

[STT 원문]
{raw_text}

[보정된 텍스트]"""

    return prompt
