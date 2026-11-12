"""Measure skill extraction against a labelled sample of 50 postings (CP-55).

``data/skill_labels_sample.csv`` holds 50 postings and the skills each one
really asks for (``expected_skills``). This script runs the extractor on those
postings and reports:

- recall: of the skills the postings ask for, how many were found
- precision: of the skills found, how many the postings really ask for

The CP-52 acceptance criterion is recall of at least 80%.

Run from the repo root:

    python src/measure_recall.py

To draw a new sample (this overwrites the labels file, so review it again after):

    python src/measure_recall.py --make-sample
"""

from __future__ import annotations

import argparse
import csv
import random
import re
from dataclasses import dataclass, field
from pathlib import Path

from extract_skills import SKILL_SEPARATOR, extract_skills, has_description, split_skills
from skill_dictionary import SkillDictionary, load_skill_dictionary

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_POSTINGS = REPO_ROOT / "synthetic_job_postings.csv"
DEFAULT_LABELS = REPO_ROOT / "data" / "skill_labels_sample.csv"
DEFAULT_REPORT = REPO_ROOT / "reports" / "recall_check.md"

SAMPLE_SIZE = 50
SAMPLE_SEED = 52  # fixed, so the same 50 postings are drawn every time
RECALL_TARGET = 0.80

# Every description in synthetic_job_postings.csv lists its skills after one of
# these phrases. Used only to pre-fill labels for review, never by the extractor.
_LEAD_IN = re.compile(
    r"(?:Required skills:|You will use|Experience with|Must have working knowledge of|Our stack includes)"
    r"\s+(.*?)(?:\s+daily|\s+is required)?\.\s"
)


@dataclass
class RecallResult:
    postings: int = 0
    true_positives: int = 0
    false_negatives: int = 0
    false_positives: int = 0
    missed: list[tuple[str, str]] = field(default_factory=list)  # (posting_id, skill)
    extra: list[tuple[str, str]] = field(default_factory=list)  # (posting_id, skill)

    @property
    def recall(self) -> float:
        expected = self.true_positives + self.false_negatives
        return self.true_positives / expected if expected else 1.0

    @property
    def precision(self) -> float:
        found = self.true_positives + self.false_positives
        return self.true_positives / found if found else 1.0


def measure(labels: list[dict], sd: SkillDictionary) -> RecallResult:
    """Compare extracted skills with ``expected_skills`` for each labelled posting."""
    result = RecallResult()
    for row in labels:
        expected = set(split_skills(row["expected_skills"]))
        found = set(extract_skills(row, sd)[0])
        result.postings += 1
        result.true_positives += len(found & expected)
        result.false_negatives += len(expected - found)
        result.false_positives += len(found - expected)
        result.missed += [(row["posting_id"], s) for s in sorted(expected - found)]
        result.extra += [(row["posting_id"], s) for s in sorted(found - expected)]
    return result


def prefill_expected(description: str, sd: SkillDictionary) -> list[str]:
    """Pre-fill expected skills from the posting's own skill list, for a person to review."""
    if not has_description(description):
        return []
    m = _LEAD_IN.search(description)
    if not m:
        return []
    items = [s.strip() for s in re.split(r",\s*|\s+and\s+", m.group(1)) if s.strip()]
    return [sd.normalize(s) or s for s in items]  # unknown terms stay as written, so they show up as misses


def make_sample(rows: list[dict], sd: SkillDictionary) -> list[dict]:
    sample = random.Random(SAMPLE_SEED).sample(rows, SAMPLE_SIZE)
    sample.sort(key=lambda r: int(r["posting_id"]))
    return [
        {
            "posting_id": r["posting_id"],
            "job_title": r["job_title"],
            "description": r["description"],
            "expected_skills": SKILL_SEPARATOR.join(prefill_expected(r["description"], sd)),
        }
        for r in sample
    ]


def report(result: RecallResult, labels_name: str) -> str:
    status = "meets" if result.recall >= RECALL_TARGET else "DOES NOT meet"
    lines = [
        "# Skill extraction recall check (CP-55)",
        "",
        f"Labelled sample: `{labels_name}` ({result.postings} postings, drawn with seed {SAMPLE_SEED}).",
        "",
        "| Measure | Value |",
        "|---|---:|",
        f"| Recall (skills asked for that were found) | {result.recall:.1%} |",
        f"| Precision (skills found that were asked for) | {result.precision:.1%} |",
        f"| Skills found correctly | {result.true_positives} |",
        f"| Skills missed | {result.false_negatives} |",
        f"| Skills found that weren't asked for | {result.false_positives} |",
        "",
        f"Recall {status} the {RECALL_TARGET:.0%} target.",
        "",
    ]
    if result.missed:
        lines += ["## Missed", "", "| Posting | Skill |", "|---|---|"]
        lines += [f"| {pid} | {skill} |" for pid, skill in result.missed] + [""]
    if result.extra:
        lines += ["## Found but not asked for", "", "| Posting | Skill |", "|---|---|"]
        lines += [f"| {pid} | {skill} |" for pid, skill in result.extra] + [""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Measure skill extraction recall on a labelled sample.")
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--postings", type=Path, default=DEFAULT_POSTINGS)
    parser.add_argument("--make-sample", action="store_true", help="draw a new sample and overwrite the labels file")
    args = parser.parse_args(argv)

    sd = load_skill_dictionary()

    if args.make_sample:
        with args.postings.open(encoding="utf-8", newline="") as f:
            sample = make_sample(list(csv.DictReader(f)), sd)
        args.labels.parent.mkdir(parents=True, exist_ok=True)
        with args.labels.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(sample[0]))
            writer.writeheader()
            writer.writerows(sample)
        print(f"Wrote {len(sample)} postings to {args.labels}. Review expected_skills by hand before measuring.")
        return

    with args.labels.open(encoding="utf-8", newline="") as f:
        labels = list(csv.DictReader(f))
    result = measure(labels, sd)
    md = report(result, args.labels.name)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(md, encoding="utf-8")
    print(md)


if __name__ == "__main__":
    main()
