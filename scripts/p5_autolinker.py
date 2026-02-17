"""
P5 Auto-Linker
Vault의 문서(파일명, 별칭)를 인덱싱하여 텍스트 내 키워드를 자동으로 WikiLink로 변환한다.
기존 링크([[...]])나 마크다운 링크([..](..))는 건드리지 않는다.
"""

import re
import sys
import logging
from pathlib import Path
from typing import Dict, List, Set, Optional, Tuple

# Import project utilities
try:
    from p5_config import VAULT_PATH
    from p5_utils import parse_frontmatter, setup_logger
except ImportError:
    # Fallback for standalone execution if paths are not set
    sys.path.append(str(Path(__file__).parent))
    from p5_config import VAULT_PATH
    from p5_utils import parse_frontmatter, setup_logger

log = setup_logger("p5_autolinker")


class AutoLinker:
    def __init__(self, vault_path: Path = VAULT_PATH):
        self.vault_path = vault_path
        self.term_map: Dict[str, str] = {}  # { "term": "Target Note Name" }
        self.regex: Optional[re.Pattern] = None
        self.ignore_terms = {
            "the",
            "and",
            "for",
            "with",
            "note",
            "data",
            "date",
            "image",
            "todo",
            "done",
            "test",
            "temp",
            "view",
            "edit",
            "copy",
            "이슈",
            "날짜",
            "참조",
            "설명",
            "비고",
            "상태",
            "제목",  # 흔한 컬럼명
        }

    def build_index(self):
        """Vault를 스캔하여 용어 인덱스를 구축한다."""
        log.info(f"Building AutoLinker index from {self.vault_path}...")
        count = 0
        new_map = {}

        # 1. Scan all markdown files
        for md_file in self.vault_path.rglob("*.md"):
            # Exclude specific folders
            if any(
                p.startswith(".") or p.startswith("_")
                for p in md_file.relative_to(self.vault_path).parts
            ):
                continue

            stem = md_file.stem

            # 1. Filename as term
            if self._is_valid_term(stem):
                new_map[stem.lower()] = stem

            # 2. Aliases from frontmatter
            fm = parse_frontmatter(md_file)
            aliases = fm.get("aliases", [])
            if isinstance(aliases, str):
                aliases = [aliases]

            for alias in aliases:
                if self._is_valid_term(alias):
                    new_map[alias.lower()] = stem  # Link to the original filename

            count += 1

        self.term_map = new_map
        log.info(f"Indexed {len(self.term_map)} terms from {count} files.")
        self._compile_regex()

    def _is_valid_term(self, term: str) -> bool:
        """유효한 용어인지 검사 (길이, 불용어 등)"""
        term = term.strip()
        if len(term) < 2:
            return False
        if term.lower() in self.ignore_terms:
            return False
        if term.isnumeric():  # 2024, 01 등 숫자만 있는 경우 제외
            return False
        return True

    def _compile_regex(self):
        """인덱스된 용어로 정규식 컴파일 (긴 단어 우선)"""
        if not self.term_map:
            self.regex = None
            return

        # Sort by length descending to match longest terms first
        sorted_terms = sorted(self.term_map.keys(), key=len, reverse=True)

        # Escape for regex
        escaped_terms = [re.escape(t) for t in sorted_terms]

        # Pattern: Word boundary + (Term1|Term2|...) + Word boundary
        # Note: \b works well for English, but for Korean we might need relaxad boundaries.
        # However, making it too loose causes partial matches inside words.
        # For now, we use a custom boundary check if needed, or reliable \b.
        # Since mixed CJK/English is common, we'll try a simpler approach first using simple lookaheads/behinds if boundaries fail.
        # Actually \b matches between \w and \W. Korean chars are \w. So \b works for "단어 " but not "단어는".

        # Strategy: Strict matching for now to avoid noise.
        pattern_str = (
            r"(?<!\[\[)(?<!\[)(?<!\()\b("
            + "|".join(escaped_terms)
            + r")\b(?!\]\])(?!\])(?!\))"
        )
        self.regex = re.compile(pattern_str, re.IGNORECASE)

    def link_text(self, text: str) -> str:
        """텍스트 내 용어를 WikiLink로 변환 (기존 링크 보호)"""
        if not self.regex or not text:
            return text

        # 1. Mask existing links and code blocks
        protected = {}
        counter = 0

        def mask(match):
            nonlocal counter
            token = f"__PROTECTED_{counter}__"
            protected[token] = match.group(0)
            counter += 1
            return token

        # Order matters: Code blocks -> WikiLinks -> Markdown Links
        # Code blocks ```...```
        text = re.sub(r"```[\s\S]*?```", mask, text)
        # Inline code `...`
        text = re.sub(r"`[^`\n]+`", mask, text)
        # WikiLinks [[...]]
        text = re.sub(r"\[\[.*?\]\]", mask, text)
        # Markdown Links [text](url)
        text = re.sub(r"\[.*?\]\(.*?\)", mask, text)

        # 2. Apply Auto-Linking
        def replace(match):
            term = match.group(0)
            target = self.term_map.get(term.lower())

            if not target:
                return term

            # If term matches target exactly (case-insensitive), just [[Term]]
            # If alias, [[Target|Alias]]
            if term.lower() == target.lower():
                # Keep original casing of the term in the text
                return f"[[{target}]]" if target == term else f"[[{target}|{term}]]"
            else:
                return f"[[{target}|{term}]]"

        new_text = self.regex.sub(replace, text)

        # 3. Restore protected blocks
        for token, original in protected.items():
            new_text = new_text.replace(token, original)

        return new_text


if __name__ == "__main__":
    # Test Driver
    linker = AutoLinker()
    linker.build_index()

    sample = """
    This is a test logic.
    Check the 20260207-리스크-매트릭스 document.
    Also review SS-Splice issues.
    Do not touch [[SS-Splice]] or [Link](http://google.com).
    """

    print("-" * 40)
    print("Original:", sample)
    print("-" * 40)
    print("Linked:", linker.link_text(sample))
    print("-" * 40)
