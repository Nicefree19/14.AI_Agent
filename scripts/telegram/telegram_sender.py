"""
텔레그램 응답 전송기 (Sender)

역할:
- Claude Code 작업 결과를 텔레그램으로 전송
- 텍스트 메시지 및 파일 첨부 지원
- 마크다운 포맷 지원

사용법:
    from telegram_sender import send_message, send_files

    # 텍스트 메시지 전송
    await send_message(chat_id, "메시지 내용")

    # 파일과 함께 전송
    await send_files(chat_id, "메시지 내용", ["파일1.txt", "파일2.png"])
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv
import asyncio

from ._compat import get_bot_class as _get_bot_class, get_input_file_class as _get_input_file_class

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
ENV_PATH = str(_PROJECT_ROOT / ".env")

# .env 파일 로드
load_dotenv(ENV_PATH)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# 마지막 전송 에러 정보 보존 (반환형 변경 없이 에러 전달)
_last_send_error: str | None = None


def get_last_send_error() -> str | None:
    """마지막 send_message 실패 시 에러 메시지 반환."""
    return _last_send_error


async def send_message(chat_id, text, parse_mode="Markdown"):
    """
    텔레그램 메시지 전송

    Args:
        chat_id: 채팅 ID (사용자 ID)
        text: 전송할 메시지
        parse_mode: 파싱 모드 (Markdown, HTML, None)

    Returns:
        bool: 성공 여부
    """
    if not BOT_TOKEN or BOT_TOKEN in ("your_bot_token_here", "YOUR_BOT_TOKEN"):
        print("❌ TELEGRAM_BOT_TOKEN 미설정.")
        print("   먼저 'python telegram_listener.py'를 실행하여 토큰을 설정해주세요.")
        return False

    try:
        Bot = _get_bot_class()
        bot = Bot(token=BOT_TOKEN)

        # 텔레그램 메시지 길이 제한 (4096자)
        if len(text) > 4000:
            # 긴 메시지는 분할 전송
            chunks = [text[i : i + 4000] for i in range(0, len(text), 4000)]
            for i, chunk in enumerate(chunks):
                if i > 0:
                    await asyncio.sleep(0.5)  # 연속 전송 시 잠시 대기
                await bot.send_message(
                    chat_id=chat_id, text=chunk, parse_mode=parse_mode
                )
        else:
            await bot.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode)

        return True

    except Exception as e:
        # Markdown 파싱 실패 시 plain text로 재시도
        if parse_mode is not None:
            try:
                if len(text) > 4000:
                    chunks = [text[i : i + 4000] for i in range(0, len(text), 4000)]
                    for chunk in chunks:
                        await bot.send_message(chat_id=chat_id, text=chunk)
                else:
                    await bot.send_message(chat_id=chat_id, text=text)
                return True
            except Exception as retry_err:
                print(f"❌ plain text 재시도도 실패: {retry_err}")
        global _last_send_error
        _last_send_error = str(e)
        print(f"❌ 메시지 전송 실패: {e}")
        return False


async def send_file(chat_id, file_path, caption=None):
    """
    텔레그램 파일 전송

    Args:
        chat_id: 채팅 ID
        file_path: 파일 경로
        caption: 파일 설명 (선택)

    Returns:
        bool: 성공 여부
    """
    if not BOT_TOKEN or BOT_TOKEN in ("your_bot_token_here", "YOUR_BOT_TOKEN"):
        print("❌ TELEGRAM_BOT_TOKEN 미설정.")
        print("   먼저 'python telegram_listener.py'를 실행하여 토큰을 설정해주세요.")
        return False

    if not os.path.exists(file_path):
        print(f"❌ 파일을 찾을 수 없습니다: {file_path}")
        return False

    try:
        Bot = _get_bot_class()
        bot = Bot(token=BOT_TOKEN)

        # 파일 크기 확인 (텔레그램 제한: 50MB)
        file_size = os.path.getsize(file_path)
        if file_size > 50 * 1024 * 1024:
            print(
                f"⚠️  파일이 너무 큽니다 ({file_size / 1024 / 1024:.1f}MB). 50MB 이하만 전송 가능합니다."
            )
            return False

        with open(file_path, "rb") as f:
            file_bytes = f.read()
        InputFile = _get_input_file_class()
        input_file = InputFile(file_bytes, filename=os.path.basename(file_path))
        await bot.send_document(
            chat_id=chat_id,
            document=input_file,
            caption=caption,
        )

        return True

    except Exception as e:
        print(f"❌ 파일 전송 실패: {e}")
        return False


async def send_files(chat_id, text, file_paths):
    """
    텔레그램 메시지 + 여러 파일 전송

    Args:
        chat_id: 채팅 ID
        text: 메시지 내용
        file_paths: 파일 경로 리스트

    Returns:
        bool: 성공 여부
    """
    # 먼저 메시지 전송
    success = await send_message(chat_id, text)

    if not success:
        return False

    # 파일이 없으면 종료
    if not file_paths:
        return True

    # 파일들 전송
    for i, file_path in enumerate(file_paths):
        if i > 0:
            await asyncio.sleep(0.5)  # 연속 전송 시 잠시 대기

        file_name = os.path.basename(file_path)
        print(f"📎 파일 전송 중: {file_name}")

        success = await send_file(chat_id, file_path, caption=f"📎 {file_name}")

        if success:
            print(f"✅ 파일 전송 완료: {file_name}")
        else:
            print(f"❌ 파일 전송 실패: {file_name}")

    return True


def run_async_safe(coro):
    """이벤트 루프가 이미 실행 중이면 별도 스레드에서 실행"""
    try:
        asyncio.get_running_loop()
        # 루프가 실행 중 → 별도 스레드에서 새 루프 생성
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    except RuntimeError:
        # 실행 중인 루프 없음 → 직접 실행
        return asyncio.run(coro)


# 동기 함수 래퍼
import time as _time

_SIDE_EFFECT_INTERVAL = 30  # seconds — 무거운 사이드이펙트 쓰로틀
_last_side_effect_ts: float = 0.0


def send_message_sync(chat_id, text, parse_mode="Markdown"):
    """
    동기 방식 메시지 전송

    메시지 전송 시마다:
    1. working.json의 last_activity 갱신 (항상)
    2. 봇 응답 기록 + 새 메시지 확인 (30초 쓰로틀)
    """
    global _last_side_effect_ts
    result = run_async_safe(send_message(chat_id, text, parse_mode))

    if not result:
        return result

    try:
        from .telegram_bot import (
            update_working_activity,
            check_new_messages_during_work,
            save_new_instructions,
            save_bot_response,
            check_working_lock,
        )

        # 항상: 활동 시각 갱신 (경량: 1읽기 + 1쓰기, 스탈 감지 필수)
        update_working_activity()

        # 30초 쓰로틀: 무거운 작업 (봇 응답 기록 + 새 메시지 감지)
        now = _time.time()
        if now - _last_side_effect_ts >= _SIDE_EFFECT_INTERVAL:
            _last_side_effect_ts = now

            # 봇 응답 기록 (대화 컨텍스트 유지)
            lock_info = check_working_lock()
            if lock_info:
                reply_ids = lock_info.get("message_id", [])
                if not isinstance(reply_ids, list):
                    reply_ids = [reply_ids]
                if reply_ids:
                    save_bot_response(chat_id, text[:500], reply_ids)

            # 새 메시지 감지
            new_msgs = check_new_messages_during_work()
            if new_msgs:
                save_new_instructions(new_msgs)

                alert_text = f"✅ **새로운 요청 {len(new_msgs)}개 확인**\n\n"
                for i, msg in enumerate(new_msgs, 1):
                    alert_text += f"{i}. {msg['instruction'][:50]}...\n"
                alert_text += "\n진행 중인 작업에 반영하겠습니다."

                # 재귀 호출 방지 (알림은 raw send만)
                run_async_safe(send_message(chat_id, alert_text, parse_mode))

    except ImportError:
        pass  # telegram_bot not available (standalone usage)
    except Exception as e:
        # Side-effect failure must not mask the send result, but log it
        print(f"⚠️ send_message_sync 사이드이펙트 오류: {e}")

    return result


def send_files_sync(chat_id, text, file_paths):
    """동기 방식 파일 전송"""
    return run_async_safe(send_files(chat_id, text, file_paths))


if __name__ == "__main__":
    # 테스트
    import sys

    if len(sys.argv) < 3:
        print("사용법: python telegram_sender.py <chat_id> <message>")
        print("예: python telegram_sender.py 1234567890 '테스트 메시지'")
        sys.exit(1)

    chat_id = int(sys.argv[1])
    message = sys.argv[2]

    print(f"메시지 전송 중: {chat_id}")
    success = send_message_sync(chat_id, message)

    if success:
        print("✅ 전송 성공!")
    else:
        print("❌ 전송 실패!")
