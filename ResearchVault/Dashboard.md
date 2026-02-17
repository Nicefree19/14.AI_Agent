---
title: "연구 대시보드"
tags: [type/dashboard]
date: 2026-02-02
---

# 연구 대시보드

## 최근 노트
```dataview
TABLE title, tags, date
FROM ""
WHERE file.name != "Dashboard"
SORT date DESC
LIMIT 20
```

## 상태별 현황
### Inbox (미분류)
```dataview
LIST
FROM #status/inbox
SORT date DESC
```

### Draft (초안)
```dataview
LIST
FROM #status/draft
SORT date DESC
```

### 완료
```dataview
LIST
FROM #status/final OR #status/complete OR #status/published
SORT date DESC
```

## NotebookLM 동기화 노트
```dataview
TABLE title, date, source
FROM #source/notebooklm
SORT date DESC
```

## 연구 노트
```dataview
TABLE title, date, tags
FROM #type/research
SORT date DESC
LIMIT 15
```

## 출처 노트
```dataview
TABLE title, author, date
FROM #type/source
SORT date DESC
LIMIT 15
```

## 고립된 노트 (링크 없음)
```dataview
LIST
FROM ""
WHERE length(file.inlinks) = 0 AND length(file.outlinks) = 0
AND !contains(file.path, "Templates")
AND !contains(file.path, "Rules")
AND !contains(file.path, "Workflows")
AND !contains(file.path, "Skills")
AND !contains(file.path, "_config")
AND file.name != "Dashboard"
SORT date DESC
```

