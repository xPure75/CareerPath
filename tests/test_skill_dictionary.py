import csv
import re
from pathlib import Path

import pytest

from skill_counts import build_tables
from skill_dictionary import SkillDictionary, SkillDictionaryError, load_skill_dictionary

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def sd() -> SkillDictionary:
    return load_skill_dictionary()


def _write(tmp_path, text):
    p = tmp_path / "dict.csv"
    p.write_text(text, encoding="utf-8")
    return p


# --- merging spelling variants -------------------------------------------------

@pytest.mark.parametrize(
    "term, skill",
    [
        ("SQL", "SQL"), ("Sql", "SQL"), ("sql", "SQL"),
        ("Python3", "Python"), ("python", "Python"),
        ("PowerBI", "Power BI"), ("power  bi", "Power BI"),
        ("Amazon Web Services", "AWS"),
        ("Postgres", "PostgreSQL"), ("postgresql", "PostgreSQL"),
        ("ML", "Machine Learning"), ("machine learning", "Machine Learning"),
        ("Tensorflow", "TensorFlow"),
        ("ETL pipelines", "ETL"),
        ("R", "R"),
    ],
)
def test_normalize_merges_variants(sd, term, skill):
    assert sd.normalize(term) == skill


@pytest.mark.parametrize("term", ["r", "ml", "Cobol", "", "   "])
def test_normalize_rejects_unknown_and_wrong_case_short_terms(sd, term):
    assert sd.normalize(term) is None


# --- finding mentions in text ---------------------------------------------------

def test_find_mentions_returns_text_as_written_and_canonical(sd):
    text = "Required skills: Sql, PowerBI, Python3. Experience level: 3-5 years."
    assert sd.find_mentions(text) == [("Sql", "SQL"), ("PowerBI", "Power BI"), ("Python3", "Python")]


def test_word_boundaries(sd):
    # "R" must not match inside words; "Git" must not match inside an unrelated word.
    assert sd.skills_in("Recruiter seeks a Rockstar with Gitter experience") == []
    assert sd.skills_in("Skills: R, SQL") == ["R", "SQL"]


def test_short_aliases_are_case_sensitive(sd):
    assert sd.skills_in("we use r and ml daily") == []
    assert sd.skills_in("we use R and ML daily") == ["R", "Machine Learning"]


def test_longest_alias_wins(sd):
    assert sd.find_mentions("Build ETL pipelines") == [("ETL pipelines", "ETL")]
    assert sd.find_mentions("Amazon Web Services") == [("Amazon Web Services", "AWS")]


def test_job_title_is_ignored(sd):
    text = "Cobalt Labs is hiring a ML Scientist. Our stack includes Python, R."
    assert sd.skills_in(text) == ["Machine Learning", "Python", "R"]
    assert sd.skills_in(text, title="ML Scientist") == ["Python", "R"]


def test_skill_only_in_title_is_not_counted(sd):
    text = "Ironbridge Capital is hiring a ETL Developer. Required skills: Docker, SQL."
    assert sd.skills_in(text, title="ETL Developer") == ["Docker", "SQL"]


def test_title_removal_matches_whole_words_only(sd):
    # Removing "BA" from inside "Rba" would leave a stray "R" that matches the R skill.
    text = "Hiring a BA at Rba Holdings. Skills: SQL."
    assert sd.skills_in(text, title="BA") == ["SQL"]
    assert sd.skills_in("Hiring a ba. Skills: SQL", title="BA") == ["SQL"]  # still case-insensitive


def test_skills_in_is_distinct_in_order(sd):
    assert sd.skills_in("SQL, Python, sql, Python3") == ["SQL", "Python"]


def test_empty_text(sd):
    assert sd.find_mentions("") == []
    assert sd.skills_in(None) == []


# --- dictionary file validation -------------------------------------------------

def test_shipped_dictionary_loads(sd):
    assert len(sd.skills) >= 20
    assert all(sd.categories[s] for s in sd.skills), "every skill needs a category"


def test_duplicate_skill_is_rejected(tmp_path):
    p = _write(tmp_path, "skill,category,aliases\nSQL,Programming,\nSQL,Programming,\n")
    with pytest.raises(SkillDictionaryError, match="listed twice"):
        load_skill_dictionary(p)


def test_alias_used_by_two_skills_is_rejected(tmp_path):
    p = _write(tmp_path, "skill,category,aliases\nPostgreSQL,Databases,Postgres\nPostgres DB,Databases,postgres\n")
    with pytest.raises(SkillDictionaryError, match="used by both"):
        load_skill_dictionary(p)


def test_missing_column_is_rejected(tmp_path):
    p = _write(tmp_path, "skill,aliases\nSQL,\n")
    with pytest.raises(SkillDictionaryError, match="missing column"):
        load_skill_dictionary(p)


# --- before/after counts --------------------------------------------------------

def test_counts_merge_variants_and_count_postings_once(sd):
    rows = [
        {"job_title": "Data Analyst", "description": "Required skills: SQL, sql, Excel."},
        {"job_title": "BA", "description": "Required skills: Sql."},
        {"job_title": "ML Scientist", "description": "Hiring a ML Scientist. Skills: Python."},
    ]
    before, after = build_tables(rows, sd)
    after_by_skill = {r["skill"]: r for r in after}

    assert after_by_skill["SQL"]["postings"] == 2  # posting 1 counted once despite two spellings
    assert after_by_skill["SQL"]["postings_canonical_spelling_only"] == 1
    assert "Machine Learning" not in after_by_skill  # came only from the job title
    assert {r["spelling"] for r in before} == {"SQL", "sql", "Sql", "Excel", "Python"}


# --- independent check against the dataset ---------------------------------------

# Every description in synthetic_job_postings.csv lists its skills after one of
# these phrases. Reading that list directly gives an answer key that doesn't
# depend on the dictionary, so a skill missing from the dictionary fails here.
LEAD_IN = re.compile(
    r"(?:Required skills:|You will use|Experience with|Must have working knowledge of|Our stack includes)"
    r"\s+(.*?)(?:\s+daily|\s+is required)?\.\s"
)


def test_matcher_finds_exactly_the_listed_skills_in_every_posting(sd):
    with (REPO_ROOT / "synthetic_job_postings.csv").open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    with_text = [r for r in rows if (r["description"] or "").strip().lower() not in ("", "null")]
    checked = 0
    for row in with_text:
        m = LEAD_IN.search(row["description"])
        assert m, f"posting {row['posting_id']}: no skill list found, the test needs a new lead-in phrase"
        listed = [s.strip() for s in re.split(r",\s*|\s+and\s+", m.group(1)) if s.strip()]

        unknown = [s for s in listed if sd.normalize(s) is None]
        assert not unknown, f"posting {row['posting_id']}: not in the dictionary: {unknown}"

        expected = {sd.normalize(s) for s in listed}
        found = set(sd.skills_in(row["description"], title=row["job_title"]))
        assert found == expected, f"posting {row['posting_id']}: found {sorted(found)}, listed {sorted(expected)}"
        checked += 1

    assert checked == len(with_text) > 900
