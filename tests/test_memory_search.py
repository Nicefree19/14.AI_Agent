"""W5 — Memory search scoring tests.

Tests for:
  - Korean particle stripping
  - Query tokenization
  - TF-weighted task scoring
  - Ranking with tiebreaks
  - Feature-flag guard (flag OFF = legacy, flag ON = scored)
"""

from __future__ import annotations

import time

import pytest


# ════════════════════════════════════════════════════════════
#  Helpers
# ════════════════════════════════════════════════════════════

def _make_task(
    message_id: int = 1,
    instruction: str = "",
    keywords: list[str] | None = None,
    topics: list[str] | None = None,
    result_summary: str = "",
    files: list[str] | None = None,
) -> dict:
    """Create a minimal index-shaped task dict for testing."""
    return {
        "message_id": message_id,
        "timestamp": "2026-02-15",
        "instruction": instruction,
        "keywords": keywords or [],
        "topics": topics or [],
        "result_summary": result_summary,
        "files": files or [],
        "chat_id": "123",
        "task_dir": f"tasks/msg_{message_id}",
    }


# ════════════════════════════════════════════════════════════
#  1. TestStripParticles
# ════════════════════════════════════════════════════════════

class TestStripParticles:
    """Korean particle removal from word suffixes."""

    def test_strip_common_particles(self):
        from scripts.telegram.memory_search import strip_particles

        assert strip_particles("물량을") == "물량"
        assert strip_particles("계산이") == "계산"
        assert strip_particles("리스크가") == "리스크"
        assert strip_particles("현황은") == "현황"
        assert strip_particles("발주를") == "발주"
        assert strip_particles("결과는") == "결과"

    def test_strip_multi_char_particles(self):
        from scripts.telegram.memory_search import strip_particles

        assert strip_particles("6층에서") == "6층"
        assert strip_particles("철골으로") == "철골"

    def test_no_strip_short_words(self):
        """Single-char words equal to a particle must not become empty."""
        from scripts.telegram.memory_search import strip_particles

        assert strip_particles("을") == "을"
        assert strip_particles("이") == "이"
        assert strip_particles("가") == "가"

    def test_no_strip_non_particle_suffix(self):
        """Words ending in non-particle chars are unchanged."""
        from scripts.telegram.memory_search import strip_particles

        assert strip_particles("엑셀") == "엑셀"
        assert strip_particles("분석") == "분석"
        assert strip_particles("프로젝트") == "프로젝트"


# ════════════════════════════════════════════════════════════
#  2. TestTokenizeQuery
# ════════════════════════════════════════════════════════════

class TestTokenizeQuery:
    """Query tokenization with particle removal and stopwords."""

    def test_basic_tokenization(self):
        from scripts.telegram.memory_search import tokenize_query

        tokens = tokenize_query("P5 물량 산출")
        assert tokens == ["p5", "물량", "산출"]

    def test_particle_removal_in_tokens(self):
        from scripts.telegram.memory_search import tokenize_query

        tokens = tokenize_query("리스크가 발주를 적용하면")
        assert "리스크" in tokens
        assert "발주" in tokens
        # "적용하면" — "하면" is NOT a particle, so it stays as-is
        assert "적용하면" in tokens

    def test_stopword_filtering(self):
        from scripts.telegram.memory_search import tokenize_query

        # Use a small stopword set matching production _MEMORY_STOPWORDS
        sw = {"이거", "해줘", "좀", "것"}
        tokens = tokenize_query("이거 해줘 분석 좀", stopwords=sw)
        assert tokens == ["분석"]

    def test_deduplication(self):
        """'물량', '물량을', '물량이' all normalise to '물량'."""
        from scripts.telegram.memory_search import tokenize_query

        tokens = tokenize_query("물량 물량을 물량이")
        assert tokens == ["물량"]


# ════════════════════════════════════════════════════════════
#  3. TestScoreTask
# ════════════════════════════════════════════════════════════

class TestScoreTask:
    """TF-weighted scoring against index task metadata."""

    def test_exact_match_high_score(self):
        from scripts.telegram.memory_search import score_task

        task = _make_task(
            instruction="P5 물량 산출 분석",
            keywords=["물량", "산출"],
            topics=["데이터분석"],
            result_summary="물량 산출 완료",
            files=["quantity.xlsx"],
        )
        score = score_task(task, ["p5", "물량", "산출"])
        assert score > 3.0, f"Expected > 3.0, got {score}"

    def test_partial_match_moderate_score(self):
        from scripts.telegram.memory_search import score_task

        task = _make_task(
            instruction="P5 물량 산출 분석",
            keywords=["물량", "산출"],
        )
        full_score = score_task(task, ["p5", "물량", "산출"])
        partial_score = score_task(task, ["p5", "도면"])
        assert 0 < partial_score < full_score

    def test_no_match_zero_score(self):
        from scripts.telegram.memory_search import score_task

        task = _make_task(instruction="P5 물량 산출")
        score = score_task(task, ["카카오톡", "읽기"])
        assert score == 0.0

    def test_field_weight_ordering(self):
        """Matching in instruction should score higher than matching in files."""
        from scripts.telegram.memory_search import score_task

        task_instr = _make_task(instruction="물량 분석", files=[])
        task_files = _make_task(instruction="기타 작업", files=["물량_보고서.xlsx"])

        s_instr = score_task(task_instr, ["물량"])
        s_files = score_task(task_files, ["물량"])
        assert s_instr > s_files, (
            f"instruction score ({s_instr}) should beat files score ({s_files})"
        )


# ════════════════════════════════════════════════════════════
#  4. TestRankTasks
# ════════════════════════════════════════════════════════════

class TestRankTasks:
    """Ranking, tiebreaking, filtering, and performance."""

    def test_relevance_ordering(self):
        from scripts.telegram.memory_search import rank_tasks

        tasks = [
            _make_task(1, instruction="기타 작업"),
            _make_task(2, instruction="P5 물량 산출 리스크 발주"),
            _make_task(3, instruction="P5 물량"),
        ]
        ranked = rank_tasks(tasks, ["p5", "물량", "산출"])
        ids = [t["message_id"] for t, _s in ranked]
        # task 2 matches all 3 tokens in instruction → highest
        assert ids[0] == 2

    def test_recency_tiebreak(self):
        """Equal scores → higher message_id (more recent) first."""
        from scripts.telegram.memory_search import rank_tasks

        tasks = [
            _make_task(10, instruction="P5 물량"),
            _make_task(20, instruction="P5 물량"),
        ]
        ranked = rank_tasks(tasks, ["p5", "물량"])
        assert ranked[0][0]["message_id"] == 20
        assert ranked[1][0]["message_id"] == 10
        # scores should be equal
        assert ranked[0][1] == ranked[1][1]

    def test_min_score_filter(self):
        from scripts.telegram.memory_search import rank_tasks

        tasks = [
            _make_task(1, instruction="P5 물량 산출"),
            _make_task(2, instruction="완전 무관한 내용"),
        ]
        ranked = rank_tasks(tasks, ["p5", "물량"], min_score=0.1)
        ids = [t["message_id"] for t, _s in ranked]
        assert 1 in ids
        assert 2 not in ids  # zero score excluded

    def test_performance_150_tasks(self):
        """150 synthetic tasks scored in under 2 seconds."""
        from scripts.telegram.memory_search import rank_tasks

        tasks = []
        base_words = ["물량", "산출", "리스크", "발주", "도면", "이슈", "현황", "분석"]
        for i in range(150):
            w1, w2 = base_words[i % len(base_words)], base_words[(i + 3) % len(base_words)]
            tasks.append(_make_task(
                message_id=i,
                instruction=f"P5 {w1} {w2} 작업 #{i}",
                keywords=[w1, w2, "P5"],
                topics=["데이터분석"],
                result_summary=f"{w1} {w2} 완료",
                files=[f"report_{i}.pdf"],
            ))

        query = ["물량", "산출", "리스크"]
        start = time.perf_counter()
        ranked = rank_tasks(tasks, query)
        elapsed = time.perf_counter() - start

        assert elapsed < 2.0, f"Took {elapsed:.3f}s (limit: 2s)"
        assert len(ranked) > 0


# ════════════════════════════════════════════════════════════
#  5. TestFeatureFlagGuard
# ════════════════════════════════════════════════════════════

class TestFeatureFlagGuard:
    """Verify flag OFF = legacy behaviour, flag ON = scored ranking."""

    @pytest.fixture()
    def _mock_index(self, monkeypatch, tmp_path):
        """Provide a fake index with 3 tasks and patch load_index."""
        tasks = [
            _make_task(1, instruction="P5 물량 산출 리스크 발주 분석",
                       keywords=["물량", "산출", "리스크", "발주"]),
            _make_task(2, instruction="P5 물량 현황",
                       keywords=["물량", "현황"]),
            _make_task(3, instruction="카카오톡 메시지 읽기",
                       keywords=["카카오톡", "메시지"]),
        ]
        fake_index = {"tasks": tasks}

        import scripts.telegram.telegram_bot as bot_mod
        monkeypatch.setattr(bot_mod, "load_index", lambda: fake_index)

    def test_search_memory_flag_off(self, monkeypatch, _mock_index):
        """Flag OFF → simple substring matching (legacy behaviour)."""
        import scripts.telegram.config as cfg
        monkeypatch.setitem(cfg.FEATURE_FLAGS, "rag_search", False)

        from scripts.telegram.telegram_bot import search_memory

        results = search_memory(keyword="물량")
        ids = [t["message_id"] for t in results]
        # Both task 1 and 2 contain "물량" in instruction → included
        assert 1 in ids
        assert 2 in ids
        # task 3 does NOT contain "물량"
        assert 3 not in ids

    def test_search_memory_flag_on(self, monkeypatch, _mock_index):
        """Flag ON → results sorted by relevance score."""
        import scripts.telegram.config as cfg
        monkeypatch.setitem(cfg.FEATURE_FLAGS, "rag_search", True)

        from scripts.telegram.telegram_bot import search_memory

        results = search_memory(keyword="물량 산출 리스크")
        ids = [t["message_id"] for t in results]
        # task 1 matches all 3 tokens → should be ranked first
        assert ids[0] == 1
        # task 3 should be excluded (zero score)
        assert 3 not in ids

    def test_load_memory_flag_off_order(self, monkeypatch, tmp_path, _mock_index):
        """Flag OFF → load_memory returns in message_id desc order."""
        import scripts.telegram.config as cfg
        monkeypatch.setitem(cfg.FEATURE_FLAGS, "rag_search", False)

        import scripts.telegram.telegram_bot as bot_mod
        monkeypatch.setattr(bot_mod, "TASKS_DIR", str(tmp_path))

        # Create dummy task_info.txt files so load_memory can read them
        for mid in [1, 2]:
            d = tmp_path / f"msg_{mid}"
            d.mkdir()
            (d / "task_info.txt").write_text(
                f"[지시] test instruction {mid}", encoding="utf-8"
            )

        from scripts.telegram.telegram_bot import load_memory

        results = load_memory(keywords=["물량"])
        if len(results) >= 2:
            # legacy order: message_id descending
            assert results[0]["message_id"] >= results[1]["message_id"]
