"""Before/after skill counts: how rankings change when spelling variants are merged.

"Before" counts every spelling exactly as written ("SQL", "Sql" and "sql" are
three separate entries). "After" merges them through the skill dictionary.
Both count postings, not mentions: a posting that says SQL twice counts once.

Run from the repo root:

    python src/skill_counts.py
    python src/skill_counts.py --postings path/to/clean.csv --out reports

Writes reports/skill_counts.md.
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from pathlib import Path

from skill_dictionary import DEFAULT_DICTIONARY_PATH, SkillDictionary, load_skill_dictionary

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_POSTINGS = REPO_ROOT / "synthetic_job_postings.csv"
DEFAULT_OUT = REPO_ROOT / "reports"


def _rank(counter: Counter) -> dict[str, int]:
    """Competition ranking (1, 2, 2, 4) by count, ties broken alphabetically for display."""
    ranks, prev, rank = {}, None, 0
    for i, (key, n) in enumerate(sorted(counter.items(), key=lambda kv: (-kv[1], kv[0])), start=1):
        if n != prev:
            rank, prev = i, n
        ranks[key] = rank
    return ranks


def count_skills(rows: list[dict], sd: SkillDictionary) -> tuple[Counter, Counter, dict[str, Counter]]:
    """Return (postings per raw spelling, postings per skill, raw spellings seen per skill)."""
    before, after = Counter(), Counter()
    variants: dict[str, Counter] = defaultdict(Counter)
    for row in rows:
        mentions = sd.find_mentions(row.get("description") or "", title=row.get("job_title"))
        before.update({raw for raw, _ in mentions})
        after.update({skill for _, skill in mentions})
        for raw, skill in set(mentions):
            variants[skill][raw] += 1
    return before, after, variants


def build_tables(rows: list[dict], sd: SkillDictionary) -> tuple[list[dict], list[dict]]:
    before, after, variants = count_skills(rows, sd)
    total = len(rows)
    before_rank, after_rank = _rank(before), _rank(after)

    before_table = [
        {
            "spelling": raw,
            "skill": sd.normalize(raw) or "",
            "postings": n,
            "pct_postings": round(100 * n / total, 1),
            "rank": before_rank[raw],
        }
        for raw, n in sorted(before.items(), key=lambda kv: (before_rank[kv[0]], kv[0]))
    ]
    after_table = [
        {
            "skill": skill,
            "category": sd.categories[skill],
            "postings": n,
            "pct_postings": round(100 * n / total, 1),
            "rank": after_rank[skill],
            "postings_canonical_spelling_only": before.get(skill, 0),
            "rank_before": before_rank.get(skill, ""),
            "spellings_merged": "; ".join(f"{raw} ({c})" for raw, c in variants[skill].most_common()),
        }
        for skill, n in sorted(after.items(), key=lambda kv: (after_rank[kv[0]], kv[0]))
    ]
    return before_table, after_table


def _markdown(before_table: list[dict], after_table: list[dict], total: int, source: str) -> str:
    lines = [
        "# Skill counts before and after merging spellings",
        "",
        f"Source: `{source}` ({total} postings). Counts are postings that mention the skill.",
        "",
        f"- Distinct spellings before merging: **{len(before_table)}**",
        f"- Distinct skills after merging: **{len(after_table)}**",
        "",
        "| Rank after | Skill | Postings after | % of postings | Postings (canonical spelling only) | Rank before | Spellings merged |",
        "|---:|---|---:|---:|---:|---:|---|",
    ]
    for r in after_table:
        lines.append(
            f"| {r['rank']} | {r['skill']} | {r['postings']} | {r['pct_postings']}% | "
            f"{r['postings_canonical_spelling_only']} | {r['rank_before'] or '-'} | {r['spellings_merged']} |"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--postings", type=Path, default=DEFAULT_POSTINGS)
    parser.add_argument("--dictionary", type=Path, default=DEFAULT_DICTIONARY_PATH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    sd = load_skill_dictionary(args.dictionary)
    with args.postings.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    before_table, after_table = build_tables(rows, sd)
    args.out.mkdir(parents=True, exist_ok=True)
    md =_markdown(before_table, after_table, len(rows), args.postings.name)
    (args.out / "skill_counts.md").write_text(md, encoding="utf-8")
    print(md)


if __name__ == "__main__":
    main()
