"""Skill dictionary: maps different spellings of a skill to one canonical name.

The dictionary lives in ``data/skill_dictionary.csv`` so anyone on the team can
edit it without touching code. Each row is one skill:

    skill,category,aliases
    Power BI,BI & Visualization,PowerBI;Power-BI;Microsoft Power BI

Matching rules:
- The canonical name always counts as an alias of itself.
- Matching ignores case, except for aliases of 1-2 characters ("R", "ML"),
  which must match exactly so ordinary words are not tagged as skills.
- Matches need word boundaries, so "R" does not match inside "Recruiter" and
  "Git" does not match inside "GitHub".
- Longer aliases win, so "ETL pipelines" is one mention of ETL, not two.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

DEFAULT_DICTIONARY_PATH = Path(__file__).resolve().parent.parent / "data" / "skill_dictionary.csv"

# Characters that count as part of a word when checking boundaries. "+" and "#"
# are included so aliases such as "C++" or "C#" work if they are added later.
_WORD_CHARS = r"\w+#"
_SHORT = 2  # aliases this long or shorter are matched case-sensitively


class SkillDictionaryError(ValueError):
    """The dictionary file has a problem (duplicate skill, alias used twice, ...)."""


def _squash(s: str) -> str:
    """Trim and collapse inner whitespace."""
    return " ".join(s.split())


class SkillDictionary:
    def __init__(self, entries: dict[str, tuple[str, list[str]]]):
        """``entries`` maps canonical skill -> (category, aliases). Use load_skill_dictionary()."""
        self.categories: dict[str, str] = {}
        self._by_alias: dict[str, str] = {}  # lower-cased alias -> canonical
        self._short_exact: set[str] = set()  # short aliases, exact spelling

        for skill, (category, aliases) in entries.items():
            self.categories[skill] = category
            for alias in dict.fromkeys([skill, *aliases]):
                owner = self._by_alias.setdefault(alias.lower(), skill)
                if owner != skill:
                    raise SkillDictionaryError(f"alias '{alias}' is used by both '{owner}' and '{skill}'")
                if len(alias) <= _SHORT:
                    self._short_exact.add(alias)

        all_aliases = sorted({a for s, (_, al) in entries.items() for a in [s, *al]}, key=len, reverse=True)
        alternatives = "|".join(self._alias_regex(a) for a in all_aliases)
        self._pattern = re.compile(rf"(?<![{_WORD_CHARS}])(?:{alternatives})(?![{_WORD_CHARS}])")

    @staticmethod
    def _alias_regex(alias: str) -> str:
        body = r"\s+".join(re.escape(part) for part in alias.split())
        return body if len(alias) <= _SHORT else f"(?i:{body})"

    @property
    def skills(self) -> list[str]:
        return list(self.categories)

    def normalize(self, term: str) -> str | None:
        """Return the canonical name for a single skill term, or None if unknown.

        Use this for terms a user types or picks (e.g. in the skill-gap checker).
        """
        term = _squash(term)
        if len(term) <= _SHORT and term not in self._short_exact:
            return None
        return self._by_alias.get(term.lower())

    def find_mentions(self, text: str, title: str | None = None) -> list[tuple[str, str]]:
        """Return each skill mention in ``text`` as (text as written, canonical skill).

        If ``title`` is given, the job title is removed from the text first (whole
        words only), so only skills the posting lists count. For example, "hiring a
        ETL Developer. Required skills: SQL" gives SQL, not ETL.
        """
        if not text:
            return []
        if title and title.strip():
            title_regex = r"\s+".join(re.escape(part) for part in title.split())
            text = re.sub(
                rf"(?<![{_WORD_CHARS}]){title_regex}(?![{_WORD_CHARS}])", " ", text, flags=re.IGNORECASE
            )
        return [(m.group(0), self._by_alias[_squash(m.group(0)).lower()]) for m in self._pattern.finditer(text)]

    def skills_in(self, text: str, title: str | None = None) -> list[str]:
        """Return the distinct canonical skills in ``text``, in order of first mention."""
        return list(dict.fromkeys(skill for _, skill in self.find_mentions(text, title)))


def load_skill_dictionary(path: str | Path = DEFAULT_DICTIONARY_PATH) -> SkillDictionary:
    """Load and validate the skill dictionary CSV."""
    path = Path(path)
    entries: dict[str, tuple[str, list[str]]] = {}

    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        missing = {"skill", "category", "aliases"} - set(reader.fieldnames or [])
        if missing:
            raise SkillDictionaryError(f"{path.name} is missing column(s): {', '.join(sorted(missing))}")

        for line_no, row in enumerate(reader, start=2):
            skill = _squash(row["skill"] or "")
            if not skill:
                raise SkillDictionaryError(f"{path.name} line {line_no}: skill name is empty")
            if skill in entries:
                raise SkillDictionaryError(f"{path.name} line {line_no}: '{skill}' is listed twice")
            aliases = [a for a in (_squash(x) for x in (row["aliases"] or "").split(";")) if a]
            entries[skill] = (_squash(row["category"] or ""), aliases)

    try:
        return SkillDictionary(entries)
    except SkillDictionaryError as e:
        raise SkillDictionaryError(f"{path.name}: {e}") from None
