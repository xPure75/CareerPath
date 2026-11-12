"""Title roles: builds standard roles from the job titles in a postings file.

Nothing here is written by hand. ``discover_roles()`` reads the raw titles, strips
the level words, and groups spelling variants into one role. The result is saved to
``data/title_roles.csv`` so the team can review and edit it:

    role,aliases
    Business Analyst,BA
    Data Engineer,Data Eng;Big Data Engineer

Grouping rules (a title is the job title with level words and noise removed):
- Level words (Sr., Senior, Jr., II, ...) and noise like "(Remote)" are dropped, and
  case and punctuation are ignored, so "Sr. Data Scientist" and "Data Scientist II"
  are the same title. The level does not come from the title (see below).
- An initialism joins the full title ("BA" and "Business Analyst").
- A truncated spelling joins the full title ("Data Eng." and "Data Engineer").
- Every other title is its own role, including specializations that contain
  another title ("Big Data Engineer", "Research Data Scientist") and one-offs
  ("Data Ninja", "ML Scientist").
The most complete spelling names the role. To merge or split roles after a run,
edit the CSV and run again with --use-existing-mapping.

Matching a title to a role:
- The role comes from the job title only. The description is never used, so an
  empty description does not change it.
- Aliases shorter than 4 characters ("BA") must match the whole title, so ordinary
  words are not tagged.

Level rules (the user's policy, set in DEFAULT_LEVELS):
1. The experience level column decides. Its text is matched against the level names.
2. If the column is blank or not recognized, the years in the description decide.
   The first "N years", "N-M years" or "N+ years" counts, using N: 0-2 is Entry,
   3-5 is Mid, 6+ is Senior.
3. If neither gives an answer, the level is None and no standard title is built.
   An empty description is never read as a level.
The prefix is Jr. for Entry, none for Mid and Sr. for Senior.
"""

from __future__ import annotations

import csv
import difflib
import re
from collections import Counter, defaultdict
from pathlib import Path

DEFAULT_ROLES_PATH = Path(__file__).resolve().parent.parent / "data" / "title_roles.csv"

# level -> (prefix, min_years, spellings seen in the experience level column)
DEFAULT_LEVELS = {
    "Entry": ("Jr.", 0, ["Junior", "Jr", "Entry Level"]),
    "Mid": ("", 3, ["Mid Level", "Intermediate"]),
    "Senior": ("Sr.", 6, ["Sr", "Senior Level"]),
}

# Words dropped from a title before matching. They never decide the level.
_TITLE_LEVEL_WORDS = {"senior", "sr", "junior", "jr", "lead", "principal", "staff", "associate", "entry", "level"}
_TITLE_LEVEL_SUFFIXES = {"i", "ii", "iii", "iv", "v", "1", "2", "3", "4", "5"}
_TITLE_NOISE = {"remote", "hybrid", "onsite", "contract", "contractor", "temporary", "temp", "fulltime", "parttime"}

_WORD_CHARS = r"a-z0-9+#"  # characters that count as part of a word in a cleaned title
_MIN_INSIDE = 4  # aliases shorter than this only match a whole title
_EMPTY = {"", "null", "none", "nan", "n/a"}

# "3-5 years", "6+ years", "5 years", "2 to 4 yrs": the first number is what counts.
_YEARS = re.compile(r"(\d+)\s*(?:(?:-|–|to)\s*\d+\s*)?\+?\s*(?:years?|yrs?)\b", re.IGNORECASE)


class TitleRoleError(ValueError):
    """A mapping file has a problem (alias used twice, missing column, ...)."""


def _squash(s: str) -> str:
    """Trim and collapse inner whitespace."""
    return " ".join(s.split())


def _clean_words(text: str) -> list[str]:
    """Words of a title with punctuation, noise and level words removed (original case kept)."""
    text = text.replace("&", " and ")
    text = re.sub(r"[.'’]", "", text)
    text = re.sub(r"[^A-Za-z0-9+# ]", " ", text)
    words = [w for w in text.split() if w.lower() not in _TITLE_NOISE]
    while words and words[0].lower() in _TITLE_LEVEL_WORDS:
        words.pop(0)
    while words and (words[-1].lower() in _TITLE_LEVEL_SUFFIXES or words[-1].lower() in _TITLE_LEVEL_WORDS):
        words.pop()
    return words


def _clean(text: str) -> str:
    return " ".join(_clean_words(text)).lower()


def _split(title: str | None) -> list[str]:
    """Split "Data Scientist (Remote) - NLP Team" into its parts."""
    if not title:
        return []
    title = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", str(title))
    return re.split(r"\s[-–—]\s|\||,|/|@|:|;", title)


def _segments(title: str | None) -> list[str]:
    return [s for s in (_clean(p) for p in _split(title)) if s]


def base_title(title: str | None) -> str:
    """The main part of a title without level words or noise, e.g. 'Sr. Data Eng. (Remote)' -> 'Data Eng'."""
    for part in _split(title):
        words = _clean_words(part)
        if words:
            return " ".join(words)
    return ""


def _label(text: str) -> str:
    """Normalize an experience level label: 'Mid-level' and 'mid level' match."""
    return _squash(re.sub(r"[-_/.]", " ", str(text).lower()))


def years_in(text: str | None) -> int | None:
    """Return the first number of years mentioned in ``text``, or None."""
    if text is None or str(text).strip().lower() in _EMPTY:
        return None
    m = _YEARS.search(str(text))
    return int(m.group(1)) if m else None


# --- building the roles from the postings ---------------------------------------

def _is_variant(a: list[str], b: list[str]) -> bool:
    """True when title ``a`` is an initialism or a truncation of title ``b``."""
    if len(a) == 1 and len(b) >= 2 and a[0] == "".join(w[0] for w in b):
        return True  # BA -> business analyst
    if len(a) == len(b) >= 2 and a != b:
        if all(x == y or (len(x) >= 3 and y.startswith(x)) for x, y in zip(a, b)):
            return True  # data eng -> data engineer
    return False


def _pick_form(spellings: Counter) -> str:
    """Display spelling: prefer one that is not all lowercase, then the most common."""
    form = sorted(spellings.items(), key=lambda kv: (kv[0] == kv[0].lower(), -kv[1], kv[0]))[0][0]
    return form.title() if form == form.lower() else form


def discover_roles(titles: list[str | None]) -> dict[str, list[str]]:
    """Group raw job titles into standard roles. Returns role -> aliases, biggest role first."""
    spellings: dict[str, Counter] = defaultdict(Counter)
    counts: Counter = Counter()
    for t in titles:
        base = base_title(t)
        if base:
            spellings[base.lower()][base] += 1
            counts[base.lower()] += 1

    parent = {b: b for b in counts}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a in counts:
        for b in counts:
            if a != b and _is_variant(a.split(), b.split()):
                parent[find(a)] = find(b)

    groups: dict[str, list[str]] = defaultdict(list)
    for b in counts:
        groups[find(b)].append(b)

    ranked = []
    for members in groups.values():
        # the role is named by the shortest, most complete spelling (never a lone initialism)
        heads = [m for m in members if len(m.split()) > 1 or len(members) == 1]
        head = min(heads, key=lambda m: (len(m.split()), -len(m), -counts[m], m))
        aliases = [_pick_form(spellings[m]) for m in sorted(members, key=lambda m: (-counts[m], m)) if m != head]
        ranked.append((sum(counts[m] for m in members), _pick_form(spellings[head]), aliases))

    ranked.sort(key=lambda r: (-r[0], r[1]))
    return {role: aliases for _, role, aliases in ranked}


def write_title_roles(entries: dict[str, list[str]], path: str | Path = DEFAULT_ROLES_PATH) -> None:
    """Save role -> aliases as the editable mapping CSV."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["role", "aliases"])
        for role, aliases in entries.items():
            writer.writerow([role, ";".join(aliases)])


# --- matching -------------------------------------------------------------------

class TitleRoles:
    def __init__(self, entries: dict[str, list[str]]):
        """``entries`` maps standard role -> aliases. Use discover_roles() or load_title_roles()."""
        self.aliases: dict[str, list[str]] = {}
        self._by_alias: dict[str, str] = {}  # cleaned alias -> role

        for role, aliases in entries.items():
            self.aliases[role] = list(aliases)
            for alias in dict.fromkeys([role, *aliases]):
                key = _clean(alias)
                if not key:
                    continue
                owner = self._by_alias.setdefault(key, role)
                if owner != role:
                    raise TitleRoleError(f"alias '{alias}' is used by both '{owner}' and '{role}'")

        inside = sorted((a for a in self._by_alias if len(a) >= _MIN_INSIDE), key=len, reverse=True)
        alternatives = "|".join(re.escape(a) for a in inside)
        self._pattern = (
            re.compile(rf"(?<![{_WORD_CHARS}])(?:{alternatives})(?![{_WORD_CHARS}])") if inside else None
        )

    @property
    def roles(self) -> list[str]:
        return list(self.aliases)

    def normalize(self, title: str | None) -> str | None:
        """Return the role when the whole (cleaned) title is a known alias, else None."""
        for seg in _segments(title):
            if seg in self._by_alias:
                return self._by_alias[seg]
        return None

    def find_role(self, title: str | None) -> str | None:
        """Return the role for a job title, or None. Tries the whole title, then an alias inside it."""
        role = self.normalize(title)
        if role or not self._pattern:
            return role
        for seg in _segments(title):
            m = self._pattern.search(seg)
            if m:
                return self._by_alias[m.group(0)]
        return None

    def suggest(self, title: str | None, cutoff: float = 0.8) -> tuple[str, float]:
        """Closest known alias for an unmapped title, as (role, score). Empty if nothing is close."""
        segs = _segments(title)
        if not segs:
            return "", 0.0
        best = difflib.get_close_matches(segs[0], list(self._by_alias), n=1, cutoff=cutoff)
        if not best:
            return "", 0.0
        return self._by_alias[best[0]], round(difflib.SequenceMatcher(None, segs[0], best[0]).ratio(), 2)


class ExperienceLevels:
    def __init__(self, entries: dict[str, tuple[str, int, list[str]]] | None = None):
        """``entries`` maps level -> (prefix, min_years, aliases). Defaults to DEFAULT_LEVELS."""
        self.prefixes: dict[str, str] = {}
        self.min_years: dict[str, int] = {}
        self._by_label: dict[str, str] = {}

        for level, (prefix, min_years, aliases) in (entries or DEFAULT_LEVELS).items():
            self.prefixes[level] = prefix
            self.min_years[level] = min_years
            for alias in dict.fromkeys([level, *aliases]):
                owner = self._by_label.setdefault(_label(alias), level)
                if owner != level:
                    raise TitleRoleError(f"label '{alias}' is used by both '{owner}' and '{level}'")

        if 0 not in self.min_years.values():
            raise TitleRoleError("one level must start at 0 years, or small year counts have no level")
        if len(set(self.min_years.values())) != len(self.min_years):
            raise TitleRoleError("two levels start at the same number of years")

    @property
    def levels(self) -> list[str]:
        """Levels from least to most experienced."""
        return sorted(self.min_years, key=self.min_years.get)

    def from_label(self, label: str | None) -> str | None:
        """Level for an experience level column value ('Mid-level', 'Sr', ...), or None."""
        if label is None:
            return None
        return self._by_label.get(_label(label))

    def from_years(self, text: str | None) -> str | None:
        """Level for the years mentioned in ``text``, or None if it mentions none."""
        years = years_in(text)
        if years is None:
            return None
        return max((lv for lv in self.min_years if self.min_years[lv] <= years), key=self.min_years.get)

    def classify(self, label: str | None, description: str | None) -> tuple[str | None, str]:
        """Return (level, source). The column wins; description years are the fallback."""
        level = self.from_label(label) or self.from_years(label)
        if level:
            return level, "column"
        level = self.from_years(description)
        if level:
            return level, "description"
        return None, "unknown"

    def title_for(self, role: str | None, level: str | None) -> str | None:
        """Standard title: 'Jr. Data Scientist', 'Data Scientist' or 'Sr. Data Scientist'."""
        if not role or not level:
            return None
        return _squash(f"{self.prefixes[level]} {role}")


def load_title_roles(path: str | Path = DEFAULT_ROLES_PATH) -> TitleRoles:
    """Load and validate a title-to-role CSV (role,aliases)."""
    path = Path(path)
    entries: dict[str, list[str]] = {}

    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        missing = {"role", "aliases"} - set(reader.fieldnames or [])
        if missing:
            raise TitleRoleError(f"{path.name} is missing column(s): {', '.join(sorted(missing))}")

        for line_no, row in enumerate(reader, start=2):
            role = _squash(row["role"] or "")
            if not role:
                raise TitleRoleError(f"{path.name} line {line_no}: role name is empty")
            if role in entries:
                raise TitleRoleError(f"{path.name} line {line_no}: '{role}' is listed twice")
            entries[role] = [a for a in (_squash(x) for x in (row["aliases"] or "").split(";")) if a]

    try:
        return TitleRoles(entries)
    except TitleRoleError as e:
        raise TitleRoleError(f"{path.name}: {e}") from None
