import csv
from pathlib import Path

import pytest

from extract_skills import (
    FLAG_NO_DESCRIPTION,
    FLAG_NO_SKILLS,
    FLAG_OK,
    add_skill_columns,
    extract_skills,
    has_description,
    split_skills,
)
from measure_recall import RECALL_TARGET, SAMPLE_SIZE, measure
from skill_dictionary import SkillDictionary, load_skill_dictionary

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def sd() -> SkillDictionary:
    return load_skill_dictionary()


def _read(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


@pytest.fixture(scope="module")
def postings() -> list[dict]:
    return _read(REPO_ROOT / "synthetic_job_postings.csv")


@pytest.fixture(scope="module")
def labels() -> list[dict]:
    return _read(REPO_ROOT / "data" / "skill_labels_sample.csv")


# --- one posting ----------------------------------------------------------------

def test_skills_are_standard_names_in_order(sd):
    row = {"job_title": "Data Analyst", "description": "Required skills: sql, PowerBI, Python3, SQL."}
    assert extract_skills(row, sd) == (["SQL", "Power BI", "Python"], FLAG_OK)


def test_job_title_is_ignored(sd):
    row = {"job_title": "ETL Developer", "description": "Hiring a ETL Developer. Required skills: Docker, SQL."}
    assert extract_skills(row, sd) == (["Docker", "SQL"], FLAG_OK)


def test_description_without_skills_is_flagged(sd):
    row = {"job_title": "Data Analyst", "description": "We value curiosity and learning."}
    assert extract_skills(row, sd) == ([], FLAG_NO_SKILLS)


@pytest.mark.parametrize("placeholder", ["", "   ", "null", "NULL", "?", "N/A", "none", None])
def test_missing_description_is_flagged_separately(sd, placeholder):
    row = {"job_title": "Data Analyst", "description": placeholder}
    assert extract_skills(row, sd) == ([], FLAG_NO_DESCRIPTION)
    assert not has_description(placeholder)


# --- the new columns --------------------------------------------------------------

def test_columns_are_added_and_originals_kept(sd):
    rows = [{"posting_id": "1", "job_title": "BA", "description": "Required skills: Excel, Agile."}]
    out = add_skill_columns(rows, sd)
    assert out[0] == {**rows[0], "skills": "Excel; Agile", "skills_flag": FLAG_OK}
    assert "skills" not in rows[0], "input rows must not be changed"


def test_split_skills_reverses_the_column():
    assert split_skills("SQL; Power BI; Python") == ["SQL", "Power BI", "Python"]
    assert split_skills("") == []


def test_every_posting_gets_a_flag(sd, postings):
    out = add_skill_columns(postings, sd)
    assert len(out) == len(postings)
    flags = {r["skills_flag"] for r in out}
    assert flags <= {FLAG_OK, FLAG_NO_SKILLS, FLAG_NO_DESCRIPTION}
    no_description = [r for r in out if r["skills_flag"] == FLAG_NO_DESCRIPTION]
    assert len(no_description) == 20  # 10 "null" + 10 blank, per the Data Evaluation
    assert all(r["skills"] for r in out if r["skills_flag"] == FLAG_OK)


# --- recall measurement -----------------------------------------------------------

def test_measure_counts_hits_misses_and_extras(sd):
    labels = [
        {"posting_id": "1", "job_title": "", "description": "Skills: SQL, Excel.", "expected_skills": "SQL; Excel; Tableau"},
        {"posting_id": "2", "job_title": "", "description": "Skills: Python, Docker.", "expected_skills": "Python"},
    ]
    r = measure(labels, sd)
    assert (r.true_positives, r.false_negatives, r.false_positives) == (3, 1, 1)
    assert r.recall == pytest.approx(3 / 4)
    assert r.precision == pytest.approx(3 / 4)
    assert r.missed == [("1", "Tableau")]
    assert r.extra == [("2", "Docker")]


def test_label_sample_matches_the_dataset(labels, postings, sd):
    by_id = {r["posting_id"]: r for r in postings}
    assert len(labels) == SAMPLE_SIZE == 50
    assert len({r["posting_id"] for r in labels}) == 50, "posting IDs must be unique"
    for row in labels:
        assert row["description"] == by_id[row["posting_id"]]["description"], "labels file is out of date"
        for skill in split_skills(row["expected_skills"]):
            assert sd.normalize(skill) == skill, f"posting {row['posting_id']}: '{skill}' is not a standard skill name"


def test_recall_meets_cp52_target(labels, sd):
    """CP-52 acceptance: at least 80% recall on a sample of 50 postings."""
    result = measure(labels, sd)
    assert result.recall >= RECALL_TARGET, f"recall {result.recall:.1%}; missed: {result.missed}"
