import csv
from pathlib import Path

import pytest

from title_role_counts import _markdown, map_postings
from title_roles import (
    ExperienceLevels,
    TitleRoleError,
    TitleRoles,
    base_title,
    discover_roles,
    load_title_roles,
    write_title_roles,
    years_in,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

TITLES = [
    "Data Analyst (Remote)", "Sr. Data Analyst", "data analyst", "Data Analyst II", "Jr Data Analyst",
    "Business Analyst", "business analyst", "BA", "Sr. Business Analyst",
    "Data Engineer", "Data Engineer II", "Data Eng.", "Big Data Engineer", "ETL Developer",
    "Data Scientist", "Research Data Scientist", "ML Scientist", "Data Ninja II", "Analytics Analyst",
]


@pytest.fixture(scope="module")
def tr():
    return TitleRoles(discover_roles(TITLES))


@pytest.fixture(scope="module")
def lv():
    return ExperienceLevels()


@pytest.fixture(scope="module")
def postings():
    with (REPO_ROOT / "synthetic_job_postings.csv").open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


# --- building roles from titles --------------------------------------------------

@pytest.mark.parametrize(
    "title, expected",
    [("Sr. Data Eng. (Remote)", "Data Eng"), ("Data Scientist II", "Data Scientist"), ("BA", "BA"), ("  ", ""), (None, "")],
)
def test_base_title(title, expected):
    assert base_title(title) == expected


def test_variants_merge_and_distinct_titles_stay_separate(tr):
    assert set(tr.roles) == {
        "Data Analyst", "Business Analyst", "Data Engineer", "Data Scientist",
        "ETL Developer", "ML Scientist", "Data Ninja", "Analytics Analyst",
        "Big Data Engineer", "Research Data Scientist",
    }


@pytest.mark.parametrize(
    "title, role",
    [
        ("Sr. Data Scientist", "Data Scientist"),
        ("Data Scientist II", "Data Scientist"),
        ("data analyst", "Data Analyst"),
        ("Data Analyst (Remote)", "Data Analyst"),
        ("BA", "Business Analyst"),               # initialism
        ("Jr Business Analyst", "Business Analyst"),
        ("Data Eng.", "Data Engineer"),           # truncation
        ("Big Data Engineer", "Big Data Engineer"),           # contains Data Engineer but stays separate
        ("Sr. Research Data Scientist", "Research Data Scientist"),
        ("Data Ninja II", "Data Ninja"),          # its own role
        ("ML Scientist", "ML Scientist"),         # not folded into Data Scientist
    ],
)
def test_titles_map_to_role(tr, title, role):
    assert tr.find_role(title) == role


@pytest.mark.parametrize("title", ["", None, "Chef"])
def test_unknown_titles_are_none(tr, title):
    assert tr.find_role(title) is None


def test_role_names_use_the_proper_spelling(tr):
    assert "Data Analyst" in tr.roles and "ETL Developer" in tr.roles  # not "data analyst" / "Etl Developer"


def test_discover_roles_is_stable(tr):
    assert discover_roles(TITLES) == tr.aliases
    assert discover_roles(list(reversed(TITLES))) == tr.aliases


def test_mapping_file_round_trip(tmp_path, tr):
    p = tmp_path / "title_roles.csv"
    write_title_roles(tr.aliases, p)
    loaded = load_title_roles(p)
    assert loaded.roles == tr.roles
    assert loaded.find_role("Data Eng.") == "Data Engineer"


def test_edited_mapping_is_respected(tmp_path):
    p = tmp_path / "m.csv"
    p.write_text("role,aliases\nData Engineer,ETL Developer;Data Eng\n", encoding="utf-8")
    assert load_title_roles(p).find_role("Sr. ETL Developer") == "Data Engineer"


def test_alias_used_by_two_roles_is_rejected(tmp_path):
    p = tmp_path / "m.csv"
    p.write_text("role,aliases\nData Analyst,Analyst\nBusiness Analyst,Analyst\n", encoding="utf-8")
    with pytest.raises(TitleRoleError, match="used by both"):
        load_title_roles(p)


def test_missing_column_is_rejected(tmp_path):
    p = tmp_path / "m.csv"
    p.write_text("role\nData Analyst\n", encoding="utf-8")
    with pytest.raises(TitleRoleError, match="missing column"):
        load_title_roles(p)


# --- experience level ------------------------------------------------------------

@pytest.mark.parametrize(
    "text, years",
    [("Experience level: 3-5 years.", 3), ("6+ years", 6), ("0-2 years", 0), ("1 year", 1), ("none", None), ("", None), (None, None)],
)
def test_years_in(text, years):
    assert years_in(text) == years


@pytest.mark.parametrize(
    "label, level",
    [("Entry", "Entry"), ("Junior", "Entry"), ("Mid", "Mid"), ("Mid-level", "Mid"), ("Senior", "Senior"), ("Sr", "Senior"), ("?", None), ("", None), (None, None)],
)
def test_from_label(lv, label, level):
    assert lv.from_label(label) == level


@pytest.mark.parametrize(
    "text, level",
    [("Experience level: 0-2 years.", "Entry"), ("Experience level: 3-5 years.", "Mid"), ("5 years", "Mid"), ("6+ years", "Senior"), ("no years", None)],
)
def test_from_years_thresholds(lv, text, level):
    assert lv.from_years(text) == level


def test_column_wins_and_description_is_the_fallback(lv):
    assert lv.classify("Entry", "Experience level: 6+ years.") == ("Entry", "column")
    assert lv.classify("?", "Experience level: 6+ years.") == ("Senior", "description")
    assert lv.classify("", "") == (None, "unknown")
    assert lv.classify(None, "null") == (None, "unknown")


def test_prefixes(lv):
    assert lv.title_for("Data Scientist", "Entry") == "Jr. Data Scientist"
    assert lv.title_for("Data Scientist", "Mid") == "Data Scientist"
    assert lv.title_for("Data Scientist", "Senior") == "Sr. Data Scientist"
    assert lv.title_for("Data Scientist", None) is None


def test_levels_need_a_zero_year_start():
    with pytest.raises(TitleRoleError, match="start at 0"):
        ExperienceLevels({"Mid": ("", 3, []), "Senior": ("Sr.", 6, [])})


# --- mapping postings ----------------------------------------------------------------

def test_one_record_per_posting(tr, lv):
    rows = [
        {"job_title": "Sr. Data Analyst", "experience_level": "Entry", "description": "Experience level: 6+ years."},
        {"job_title": "Data Analyst", "experience_level": "", "description": "Experience level: 3-5 years."},
        {"job_title": "Data Ninja II", "experience_level": "Senior", "description": ""},
    ]
    m = map_postings(rows, tr, lv)
    assert [r["standard_title"] for r in m] == ["Jr. Data Analyst", "Data Analyst", "Sr. Data Ninja"]
    assert [r["level_source"] for r in m] == ["column", "description", "column"]
    assert m[0]["disagrees"] is True  # title says Sr., column says Entry, description says 6+: column wins


def test_empty_description_does_not_change_the_role(tr, lv):
    rows = [{"job_title": "Data Engineer", "experience_level": "Mid", "description": d} for d in ("", "null", "Experience level: 6+ years.")]
    m = map_postings(rows, tr, lv)
    assert {r["role"] for r in m} == {"Data Engineer"}
    assert {r["level"] for r in m} == {"Mid"}  # the column decides, not the description


def test_no_level_means_no_standard_title(tr, lv):
    m = map_postings([{"job_title": "Data Ninja", "experience_level": "?", "description": ""}], tr, lv)
    assert m[0]["role"] == "Data Ninja" and m[0]["level"] is None and m[0]["standard_title"] is None


# --- the real dataset --------------------------------------------------------------

def test_real_postings_all_map_and_meet_the_targets(lv, postings):
    tr = TitleRoles(discover_roles([r["job_title"] for r in postings]))
    mapped = map_postings(postings, tr, lv)
    assert all(m["role"] for m in mapped)
    assert len({m["standard_title"] for m in mapped if m["standard_title"]}) >= 15
    assert {"Data Ninja", "ML Scientist", "Data Scientist", "Big Data Engineer", "Research Data Scientist"} <= set(tr.roles)


def test_report_lists_every_role_and_raw_title_and_no_skills(lv, postings):
    tr = TitleRoles(discover_roles([r["job_title"] for r in postings]))
    md = _markdown(map_postings(postings, tr, lv), tr, lv, "x.csv", "built")
    for role in tr.roles:
        assert f"| {role} |" in md
    for title in {r["job_title"] for r in postings}:
        assert title in md
    assert "skill" not in md.lower()
