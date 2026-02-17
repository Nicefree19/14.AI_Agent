# 노트 연결 전략

## 링크 유형

### 1. 직접 관련 링크
- 같은 주제, 개념적으로 연결된 노트
- `[[관련노트]]`로 본문에서 자연스럽게 연결

### 2. 출처-노트 링크
- 영구 노트에서 원본 출처 노트로 링크
- "이 아이디어의 출처: [[source-논문제목]]"

### 3. MOC 링크
- Map of Content 노트가 하위 노트들을 목록으로 참조
- 주제별 진입점 역할

### 4. 순차 링크
- 시간순 또는 논리순 연결
- "이전: [[노트A]] → 다음: [[노트B]]"

## 링크 규칙
1. 모든 영구 노트는 최소 **2개** 이상의 링크 포함
2. 고립된 노트(orphan) 월 1회 점검
3. 새 노트 작성 시 기존 관련 노트 검색 후 연결
4. 양방향 링크 활용 (Obsidian 백링크 패널)

## MOC 구조 예시
```markdown
# MOC - LLM Agent

## 핵심 개념
- [[agent-architecture]]
- [[tool-use-patterns]]
- [[memory-systems]]

## 관련 프로젝트
- [[project-research-agent]]

## 출처
- [[source-react-agent-paper]]
```
