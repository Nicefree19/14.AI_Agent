# CLAUDE.md

## 보안 정책

- 텔레그램 봇 토큰과 허용 사용자 ID는 `.env` 파일로만 관리한다.
- `.env` 파일은 이 프로젝트 루트에 유일하게 관리되며, 코드 본문에 직접 적지 않는다.
- `.env`는 Git에 커밋하지 않는다 (`.gitignore`에 추가).
- Credentials는 dotenv 라이브러리를 통해 런타임에 로드한다.

---

## 프로젝트 구조

**ResearchVault (14.AI_Agent)** - P5 복합동 건설 프로젝트 연구 자동화 시스템

```
D:\00.Work_AI_Tool\14.AI_Agent\
├── .env                          # 환경 변수 (봇 토큰 등)
├── CLAUDE.md                     # 이 파일 (시스템 프롬프트)
├── ResearchVault/                # Obsidian 볼트
│   ├── P5-Project/              # P5 프로젝트 지식베이스
│   └── _config/                 # 설정 파일
├── scripts/
│   ├── telegram/                # 텔레그램 봇 모듈
│   │   ├── telegram_bot.py      # 통합 봇 로직 (핵심 API)
│   │   ├── telegram_sender.py   # 응답 전송기
│   │   ├── telegram_listener.py # 메시지 수집기
│   │   └── telegram_runner.py   # 작업 실행기
│   ├── p5_autoexecutor.bat      # Claude Code 자동 실행기
│   ├── p5_daily.bat             # 일일 배치
│   └── p5_daemons_start.bat     # 데몬 시작
└── telegram_data/               # 텔레그램 데이터 저장소
    ├── telegram_messages.json   # 메시지 내역
    ├── working.json             # 작업 잠금
    └── tasks/                   # 작업 폴더
        ├── index.json           # 작업 인덱스
        └── msg_{id}/            # 개별 작업 폴더
```

---

## 텔레그램 봇 시스템 (Telegram Bot)

**상태**: ✅ 구현 완료

텔레그램을 통해 실시간으로 지시사항을 받고 결과를 회신하는 자율 작업 봇입니다.

### 시스템 개요
- **목적**: 텔레그램을 통해 실시간으로 지시사항 주고받기
- **구현 범위**:
  1. `telegram_listener.py` - 10초 간격으로 텔레그램 메시지 수집
  2. `telegram_sender.py` - Claude Code 작업 결과를 텔레그램으로 전송
  3. `telegram_bot.py` - 통합 봇 로직 (check_telegram, report_telegram, mark_done_telegram)
  4. `telegram_messages.json` - 메시지 내역 저장 및 처리 상태 관리

### 핵심 특징
- **🆕 완전한 대화 컨텍스트**: 새로운 명령 + 최근 24시간 대화 내역 (사용자 메시지 + 봇 응답 모두 포함)
  - **[명령]**: 실행해야 할 새로운 지시사항
  - **[참고사항]**: 최근 24시간 대화 내역 - 사용자 메시지와 봇 응답을 모두 포함하여 대화 흐름 이해
  - 예: "거기에 다크모드 추가해줘" → Claude Code가 "거기"가 이전에 만든 파일임을 알 수 있음
- **폴링 주기**: 10초마다 실시간 확인 - 빠른 응답
- **키워드 필터**: 키워드 필수 없음, 모든 메시지 처리
- **사용자 검증**: `.env`의 `TELEGRAM_ALLOWED_USERS`에 등록된 사용자만 허용
- **이미지/파일/위치 지원**: 텔레그램 메시지에 첨부된 이미지, 문서, 비디오, 오디오, 위치 정보 자동 처리

### 현재 봇 정보

**환경 변수 (.env) 구조**:
```env
TELEGRAM_BOT_TOKEN=<@BotFather에서 발급한 봇 토큰>
TELEGRAM_ALLOWED_USERS=<허용할 텔레그램 사용자 ID>
TELEGRAM_POLLING_INTERVAL=10
```

---

## 작업 처리 원칙 (중요!)

텔레그램으로 새로운 명령을 받으면 **반드시** 다음 순서로 처리해야 한다:

### 1. 즉시 답장 (작업 시작 알림)
새 메시지 확인 즉시 작업 시작을 알리는 답장을 보낸다.
```python
from scripts.telegram.telegram_sender import send_message_sync

# 즉시 답장
send_message_sync(task['chat_id'], "✅ 작업을 시작했습니다!")
```

### 2. 진행 중 경과 보고 (실시간 피드백)
작업이 여러 단계로 나뉘거나 시간이 오래 걸리는 경우, **각 주요 단계마다** 경과를 보고한다.
```python
# 작업 진행 중간중간 보고
send_message_sync(chat_id, "📊 30% - 파일 읽기 완료")
send_message_sync(chat_id, "📊 50% - 데이터 처리 중...")
send_message_sync(chat_id, "📊 90% - 최종 검토 중...")
```

### 3. 최종 결과 보고 (작업 완료)
작업이 모두 끝나면 `report_telegram()`으로 최종 결과와 파일을 전송한다.
```python
from scripts.telegram.telegram_bot import report_telegram

# 최종 결과 전송
report_telegram(
    instruction=task['instruction'],
    result_text="작업 완료! 총 3개 파일을 생성했습니다.",
    chat_id=task['chat_id'],
    timestamp=task['timestamp'],
    files=["결과1.pdf", "결과2.png"]
)
```

### 4. 처리 완료 표시
```python
from scripts.telegram.telegram_bot import mark_done_telegram
mark_done_telegram(task['message_id'])
```

### 주의사항
- **즉시 답장 없이 작업만 하면 안 된다** - 사용자가 봇이 응답하는지 모를 수 있음
- **진행 경과 없이 오래 걸리면 안 된다** - 사용자가 작업이 멈춘 것으로 오해할 수 있음
- **최종 결과 없이 끝내면 안 된다** - 메모리에 기록되지 않고 파일도 전송되지 않음

---

## 동시 작업 방지 (이중 안전 장치)

### 1. 프로세스 레벨 중복 방지 (p5_autoexecutor.bat)

**3단계 안전 장치**:

```batch
REM 1. Claude 프로세스 먼저 확인! (실제 진행 중인지)
tasklist... find "claude" | find "append-system-prompt-file"
→ 프로세스 있으면 exit /b 98 (정상 실행 중)

REM 2. Lock 파일 확인 (프로세스 없는데 Lock 있으면 오류!)
if exist "p5_autoexecutor.lock"
→ 프로세스 없음 + Lock 있음 = 오류 중단! Lock 삭제 후 복구

REM 3. 빠른 메시지 확인 (Claude Code 실행 전!)
python quick_check.py
→ exit code 0: 새 메시지 없음 → 즉시 종료 (Claude Code 실행 안 함!)
→ exit code 1: 새 메시지 있음 → Claude Code 실행
```

### 2. 메시지 레벨 중복 방지 (telegram_bot.py)

**working.json**으로 동일 메시지를 여러 에이전트가 처리하는 것을 방지:

- **잠금 파일**: `telegram_data/working.json`
- **활동 기반 스탈네스 감지**: 마지막 활동으로부터 30분 경과 → 스탈 작업으로 간주
- **자동 처리**: `check_telegram()`이 working.json 자동 확인

### 잠금 파일 관리

두 잠금 파일 모두 Git에 커밋하지 않음:
- `p5_autoexecutor.lock` - 프로세스 잠금
- `telegram_data/working.json` - 메시지 잠금

---

## 작업 시작 전 메모리 조사 (필수)

지시사항을 실행하기 **앞서** 반드시 관련된 메모리를 먼저 조사해야 한다.

- `load_memory()`를 호출하여 기존 메모리 파일을 전부 읽는다.
- 지시사항의 키워드와 관련된 메모리가 있으면 해당 내용을 참고한다.
- 특히 `[보낸파일]` 섹션을 확인하여 이전에 보낸 파일이 있으면 **해당 작업 폴더 (`tasks/msg_X/`)에서 파일을 찾아** 기반으로 작업해야 한다.

### 작업 폴더 구조 (중요!)

각 텔레그램 메시지는 독립적인 작업 폴더에서 관리된다:

```
telegram_data/tasks/
├── msg_5/
│   ├── task_info.txt       # 메모리 (지시사항, 결과, 보낸파일)
│   ├── result.html         # 작업 결과물
│   └── preview.png
├── msg_6/
│   ├── task_info.txt
│   └── report.pdf
└── index.json              # 인덱스 (빠른 검색)
```

### 메모리 검색 (인덱스 기반 - 빠름!)

```python
from scripts.telegram.telegram_bot import search_memory

# 키워드로 검색
matches = search_memory(keyword="P5")
# → [{"message_id": 5, "instruction": "...", "task_dir": "tasks/msg_5"}, ...]

# 특정 message_id로 검색
task = search_memory(message_id=5)[0]
```

---

## 작업 흐름 (자동화됨)

1. 사용자가 텔레그램에 메시지 보냄 (여러 개 가능!)
2. Windows 작업 스케줄러가 1분마다 `p5_autoexecutor.bat` 실행
3. **1단계: Claude 프로세스 확인** → 실제 진행 중이면 즉시 종료
4. **2단계: Lock 파일 확인** → 프로세스 없는데 Lock 있으면 오류 중단, Lock 삭제 후 복구
5. **3단계: 빠른 메시지 확인 (Python)** → `quick_check.py` 실행
   - 새 메시지 없으면 → **즉시 종료 (Claude Code 실행 안 함!)** ← 90% 시간 절약!
   - 새 메시지 있으면 → 6번으로
6. **4단계: Lock 파일 생성** → Claude Code 실행 직전에 생성
7. **Claude Code 실행** → `check_telegram()` 호출 → **메시지 레벨 중복 방지**
8. 새 메시지가 있으면:
   - **여러 메시지를 합산** → `combine_tasks(pending)` 통합
   - **즉시 답장** → `send_message_sync()` 작업 시작 알림
   - **`create_working_lock()`** → 원자적 잠금 생성
   - **`reserve_memory_telegram()`** → 메모리 예약
   - **`load_memory()`** → 관련 작업 조사
   - **작업 실행** + 경과 보고
   - **`report_telegram()`** → 결과 전송 + 메모리 저장
   - **`mark_done_telegram()`** → 완료 표시
   - **`remove_working_lock()`** → 잠금 해제

---

## telegram_bot.py API

```python
from scripts.telegram.telegram_bot import (
    check_telegram,
    combine_tasks,
    create_working_lock,
    remove_working_lock,
    reserve_memory_telegram,
    report_telegram,
    mark_done_telegram,
    load_memory,
    get_task_dir,
    load_new_instructions,
    clear_new_instructions
)
from scripts.telegram.telegram_sender import send_message_sync

# 1. 대기 중인 지시사항 확인 (working.json 자동 확인)
pending = check_telegram()
if not pending:
    print("임무 완료")
    exit()

# 2. 여러 메시지를 하나로 합산
combined = combine_tasks(pending)

# 3. 즉시 답장 (작업 시작 알림)
if len(combined['message_ids']) > 1:
    msg = f"✅ 작업을 시작했습니다! (총 {len(combined['message_ids'])}개 요청 합산 처리)"
else:
    msg = "✅ 작업을 시작했습니다!"
send_message_sync(combined['chat_id'], msg)

# 4. 작업 잠금 생성
if not create_working_lock(combined['message_ids'], combined['combined_instruction']):
    print("⚠️ 잠금 실패. 다른 작업이 진행 중입니다.")
    exit()

# 5. 메모리 예약
reserve_memory_telegram(
    combined['combined_instruction'],
    combined['chat_id'],
    combined['all_timestamps'],
    combined['message_ids']
)

# 6. 기존 메모리 읽기
memories = load_memory()

# 7. 작업 수행 + 진행 경과 보고
task_dir = get_task_dir(combined['message_ids'][0])
os.chdir(task_dir)
send_message_sync(combined['chat_id'], "📊 50% - 데이터 처리 중...")

# 8. 결과 전송 + 메모리 저장
report_telegram(
    combined['combined_instruction'],
    result_text="작업 완료!",
    chat_id=combined['chat_id'],
    timestamp=combined['all_timestamps'],
    message_id=combined['message_ids'],
    files=["result.html", "preview.png"]
)

# 9. 처리 완료 기록
mark_done_telegram(combined['message_ids'])

# 10. 작업 잠금 해제
remove_working_lock()
```

> **중요**:
> - `check_telegram()`은 working.json을 자동으로 확인하여 다른 작업이 진행 중이면 빈 리스트를 반환합니다.
> - `combine_tasks()`로 여러 메시지를 하나로 합산하여 처리합니다.

---

## Claude Code 세션 컨텍스트 연속성

### 구현 방법

`p5_autoexecutor.bat`에서 자동으로 처리:

1. **먼저 세션 재개 시도** - `claude -p -c` 실행
2. **실패 시 새 세션 생성** - 첫 실행이나 세션 만료 시 자동 처리

```batch
REM 1. Resume 시도
call "%CLAUDE_EXE%" -p -c --dangerously-skip-permissions ^
  --append-system-prompt-file "%SPF%" ^
  "..." >> "%LOG%" 2>&1

REM 2. 실패하면 새 세션
if %EC% NEQ 0 (
  call "%CLAUDE_EXE%" -p --dangerously-skip-permissions ^
    --append-system-prompt-file "%SPF%" ^
    "..." >> "%LOG%" 2>&1
)
```

### 효과

- ✅ **완전한 컨텍스트 연속성** - 이전 작업 내역, 대화 흐름, 도구 사용 기록 모두 유지
- ✅ **무제한 작업 내역** - 24시간 제한 없이 Claude Code 세션 전체 활용 (토큰 한도까지)
- ✅ **메모리 시스템 + 세션 컨텍스트** - 이중 보완으로 더 스마트한 작업 처리
- ✅ **자동 Fallback** - 첫 실행이나 세션 초기화 시에도 문제없음

---

## 실시간 지시사항 업데이트 (작업 중 새 메시지 반영)

**작업 진행 중에 새로운 메시지가 도착하면 자동으로 감지하고 반영합니다.**

- **자동 감지**: `send_message_sync()` 호출 시마다 자동으로 새 메시지 확인
- **즉시 알림**: 새 메시지 발견 시 사용자에게 알림 전송
- **파일 저장**: `new_instructions.json`에 저장하여 작업 중 참조 가능
- **자동 처리**: 작업 완료 시 새 메시지도 함께 처리 완료 표시

```python
# 경과 보고 시 (자동으로 새 메시지 확인됨)
send_message_sync(chat_id, "📊 50% - 데이터 처리 중...")

# 작업 중 새 지시사항 확인 (선택)
new_instructions = load_new_instructions()
if new_instructions:
    for inst in new_instructions:
        print(f"  - {inst['instruction']}")

# 작업 완료 시 (원래 메시지 + 새 메시지 모두 처리)
mark_done_telegram(message_ids)
```

---

## 메모리 시스템 (tasks/)

봇은 작업을 실행할 때마다 결과를 `telegram_data/tasks/msg_{message_id}/` 폴더에 저장한다.

### task_info.txt 내용
```
[시간] 2026-02-12 22:00:00
[메시지ID] 5
[출처] Telegram (chat_id: 1234567890)
[메시지날짜] 2026-02-12 21:55:00
[지시] P5 이슈 분석해줘
[결과] 이슈 분석 완료! 총 15건의 이슈를 정리했습니다.
[보낸파일] issue_report.pdf, summary.html
```

---

## 자동 실행 설정

Windows 작업 스케줄러를 통해 1분마다 자동으로 텔레그램 메시지를 확인하고 처리합니다.

### 설치 방법
```powershell
# 포그라운드 모드 (GUI 가능 - 추천!)
scripts\register_scheduler.bat 우클릭 -> "관리자 권한으로 실행"
```

### 관리 명령어
```powershell
# 비활성화
schtasks /Change /TN "Claude_P5Agent_14.AI_Agent" /DISABLE

# 재시작
schtasks /Change /TN "Claude_P5Agent_14.AI_Agent" /ENABLE

# 완전 삭제
schtasks /Delete /TN "Claude_P5Agent_14.AI_Agent" /F
```

---

## P5 프로젝트 컨텍스트

이 봇은 P5 복합동 건설 프로젝트의 연구 자동화를 지원합니다:

- **ResearchVault**: Obsidian 기반 지식베이스 (P5-Project/ 하위)
- **이슈 관리**: AppSheet 연동 이슈 동기화 (p5_issue_sync.py)
- **이메일 분류**: Outlook 이메일 자동 분류 (p5_email_triage.py)
- **일일 브리핑**: 자동 일일 브리핑 생성 (p5_daily_briefing.py)
- **OCR 파이프라인**: PDF/이미지 OCR 처리 (p5_ocr_pipeline.py)
- **위험 매트릭스**: 리스크 시각화 (p5_risk_matrix.py)

텔레그램으로 받은 P5 관련 요청은 위 도구들을 자율적으로 활용하여 처리합니다.
