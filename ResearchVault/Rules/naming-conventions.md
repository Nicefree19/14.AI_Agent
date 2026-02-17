# 파일/태그 네이밍 규칙

## 파일명 규칙
- 형식: `YYYYMMDD-주제-키워드.md`
- 소문자 영문 + 한글 허용, 공백 대신 하이픈(`-`)
- 예: `20260202-llm-agent-architecture.md`

## 폴더 구조
```
ResearchVault/
├── 00-Inbox/          # 미분류 노트
├── 01-Sources/        # 출처/문헌 노트
├── 02-Notes/          # 영구 노트 (제텔카스텐)
├── 03-Projects/       # 프로젝트별 노트
├── 04-Archive/        # 완료/보관
├── Rules/             # 규칙 문서
├── Workflows/         # 워크플로우
├── Skills/            # 스킬 문서
├── Templates/         # 템플릿
└── _config/           # 설정 파일
```

## 태그 체계
```
#type/research      연구 노트
#type/source        출처 노트
#type/daily         일일 노트
#type/project       프로젝트 노트

#status/inbox       미분류
#status/draft       초안
#status/review      검토 중
#status/final       완료

#topic/[주제명]     주제별 분류
#method/[방법명]    연구 방법론
```

## 링크 규칙
- MOC(Map of Content) 노트: `MOC-주제명.md`
- 출처 노트에는 반드시 `source` 태그 + 원문 URL 포함
- 모든 영구 노트는 최소 1개 이상의 다른 노트와 링크
