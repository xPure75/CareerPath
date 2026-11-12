"""Extract skills from every job posting (CP-52).

Adds two columns to each posting:

- ``skills``: the standard skill names found in the description, in order of
  first mention, separated by "; " (for example "SQL; Python; Power BI").
- ``skills_flag``: why the skills column is what it is.
    - ``ok``: at least one skill was found.
    - ``no_skills``: the posting has a description, but no known skill was found.
    - ``no_description``: the description is blank or a placeholder such as "null".

Skills are found with the skill dictionary (CP-26), so spelling variants are
merged and the job title is ignored.

Run from the repo root:

    python src/extract_skills.py
    python src/extract_skills.py --postings path/to/clean.csv --out data/postings_with_skills.csv
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path

from skill_dictionary import DEFAULT_DICTIONARY_PATH, SkillDictionary, load_skill_dictionary

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_POSTINGS = REPO_ROOT / "synthetic_job_postings.csv"
DEFAULT_OUT = REPO_ROOT / "data" / "postings_with_skills.csv"

SKILL_SEPARATOR = "; "
FLAG_OK = "ok"
FLAG_NO_SKILLS = "no_skills"
FLAG_NO_DESCRIPTION = "no_description"

# Placeholders that mean "unknown", from the Data Evaluation page.
MISSING_VALUES = {"", "?", "n/a", "na", "null", "none"}


def has_description(text: str | None) -> bool:
    """True if ``text`` is a real description, not blank or a placeholder."""
    return (text or "").strip().lower() not in MISSING_VALUES


def extract_skills(row: dict, sd: SkillDictionary) -> tuple[list[str], str]:
    """Return (skills, flag) for one posting row with ``description`` and ``job_title``."""
    description = row.get("description")
    if not has_description(description):
        return [], FLAG_NO_DESCRIPTION
    skills = sd.skills_in(description, title=row.get("job_title"))
    return skills, (FLAG_OK if skills else FLAG_NO_SKILLS)


def add_skill_columns(rows: list[dict], sd: SkillDictionary) -> list[dict]:
    """Return copies of ``rows`` with ``skills`` and ``skills_flag`` columns added."""
    out = []
    for row in rows:
        skills, flag = extract_skills(row, sd)
        out.append({**row, "skills": SKILL_SEPARATOR.join(skills), "skills_flag": flag})
    return out


def split_skills(value: str) -> list[str]:
    """Turn a ``skills`` column value back into a list."""
    return [s for s in (part.strip() for part in (value or "").split(";")) if s]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Add a skills column to every job posting.")
    parser.add_argument("--postings", type=Path, default=DEFAULT_POSTINGS)
    parser.add_argument("--dictionary", type=Path, default=DEFAULT_DICTIONARY_PATH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    sd = load_skill_dictionary(args.dictionary)
    with args.postings.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or []) + ["skills", "skills_flag"]
        rows = list(reader)

    result = add_skill_columns(rows, sd)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(result)

    flags = Counter(r["skills_flag"] for r in result)
    print(f"Wrote {len(result)} postings to {args.out}")
    for flag in (FLAG_OK, FLAG_NO_SKILLS, FLAG_NO_DESCRIPTION):
        print(f"  {flag:<15} {flags[flag]}")


if __name__ == "__main__":
    main()
