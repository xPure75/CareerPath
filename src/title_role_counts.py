"""Title role counts: maps raw job titles to standard roles and counts postings per role and level.

Run from the repo root:

    python src/title_role_counts.py
    python src/title_role_counts.py --postings path/to/clean.csv --out reports
    python src/title_role_counts.py --use-existing-mapping

What it does:
1. Builds the title-to-role mapping from the job titles in the postings
   (title_roles.discover_roles) and saves it to data/title_roles.csv. Nothing is
   pre-written. With --use-existing-mapping it reads that CSV as it stands instead,
   so hand edits (or a mapping built on another dataset) are kept.
2. Takes each posting's level from the experience level column, falling back to the
   years in the description (title_roles.ExperienceLevels).
3. Writes reports/postings_with_roles.csv (every posting with its role, level and
   standard title) for later steps to use, and reports/title_role_counts.md.

Counts are postings. Column names are options so other datasets work:
--title-column, --level-column, --description-column.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

from title_roles import (
    DEFAULT_ROLES_PATH,
    ExperienceLevels,
    TitleRoles,
    discover_roles,
    load_title_roles,
    write_title_roles,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_POSTINGS = REPO_ROOT / "synthetic_job_postings.csv"
DEFAULT_OUT = REPO_ROOT / "reports"
MIN_ROLES = 15
TARGET_MAPPED = 0.9


def map_postings(
    rows: list[dict],
    tr: TitleRoles,
    lv: ExperienceLevels,
    title_column: str = "job_title",
    level_column: str = "experience_level",
    description_column: str = "description",
) -> list[dict]:
    """Return one record per posting: role, level, where the level came from, standard title."""
    mapped = []
    for row in rows:
        title = (row.get(title_column) or "").strip()
        label = (row.get(level_column) or "").strip()
        description = row.get(description_column) or ""

        role = tr.find_role(title)
        level, source = lv.classify(label, description)
        years_level = lv.from_years(description)
        mapped.append(
            {
                "title": title,
                "role": role,
                "level": level,
                "level_source": source,
                "level_label": label,
                "standard_title": lv.title_for(role, level),
                # the column wins, but it is worth knowing when the description says otherwise
                "disagrees": source == "column" and years_level is not None and years_level != level,
            }
        )
    return mapped


def _target_line(roles: int, titles: int) -> str:
    if roles >= MIN_ROLES:
        return f"met ({roles} roles)"
    if titles >= MIN_ROLES:
        return f"met by standard titles ({titles}), not by roles alone ({roles})"
    return f"not met ({roles} roles, {titles} standard titles)"


def _markdown(mapped: list[dict], tr: TitleRoles, lv: ExperienceLevels, source: str, mapping_note: str) -> str:
    total = len(mapped)
    mapped_n = sum(1 for m in mapped if m["role"])
    pct = round(100 * mapped_n / total, 1) if total else 0.0
    sources = Counter(m["level_source"] for m in mapped)
    titles = {m["standard_title"] for m in mapped if m["standard_title"]}
    role_level = Counter((m["role"], m["level"]) for m in mapped if m["role"])
    role_totals = Counter(m["role"] for m in mapped if m["role"])
    levels = lv.levels

    lines = [
        "# Title role counts",
        "",
        f"Source: `{source}` ({total} postings). Counts are postings.",
        f"Role mapping: {mapping_note}",
        "",
        f"- Standard roles: **{len(role_totals)}**",
        f"- Standard titles (role plus level prefix): **{len(titles)}**",
        f"- At least {MIN_ROLES} standard roles: **{_target_line(len(role_totals), len(titles))}**",
        f"- Postings mapped to a role: **{mapped_n} of {total} ({pct}%)**, target of {TARGET_MAPPED:.0%} "
        f"**{'met' if total and mapped_n / total >= TARGET_MAPPED else 'not met'}**",
        f"- Level from the experience level column: **{sources['column']}**",
        f"- Level from years in the description (column blank or unrecognized): **{sources['description']}**",
        f"- Level unknown (no column value, no years): **{sources['unknown']}**",
        f"- Column level differs from the description's years (column used): **{sum(m['disagrees'] for m in mapped)}**",
        "",
        "## Role mapping",
        "",
        "| Role | Raw titles merged into it (postings) |",
        "|---|---|",
    ]
    raw = Counter((m["role"], m["title"]) for m in mapped if m["role"])
    for role, _ in role_totals.most_common():
        spelled = sorted(((t, n) for (r, t), n in raw.items() if r == role), key=lambda x: (-x[1], x[0]))
        lines.append(f"| {role} | " + "; ".join(f"{t} ({n})" for t, n in spelled) + " |")

    header = " | ".join(f"{l} ({lv.prefixes[l] or 'no prefix'})" for l in levels)
    lines += ["", "## Roles by level", "", f"| Role | {header} | Level unknown | Total |", "|---|" + "---:|" * (len(levels) + 2)]
    for role, n in role_totals.most_common():
        cells = " | ".join(str(role_level[(role, l)]) for l in levels)
        lines.append(f"| {role} | {cells} | {role_level[(role, None)]} | {n} |")

    unrecognized = Counter(m["level_label"] for m in mapped if m["level_label"] and m["level_source"] != "column")
    if unrecognized:
        lines += ["", "Experience level values that were not recognized (levels came from the description instead):", ""]
        lines += [f"- {label}: {n}" for label, n in unrecognized.most_common(10)]

    unmapped = Counter(m["title"] for m in mapped if not m["role"])
    if unmapped:
        lines += ["", "Unmapped titles:", "", "| Title | Postings | Closest role |", "|---|---:|---|"]
        for title, n in unmapped.most_common(25):
            lines.append(f"| {title or '(blank)'} | {n} | {tr.suggest(title)[0] or '-'} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--postings", type=Path, default=DEFAULT_POSTINGS)
    parser.add_argument("--roles", type=Path, default=DEFAULT_ROLES_PATH, help="where the role mapping CSV is written")
    parser.add_argument("--use-existing-mapping", action="store_true", help="read --roles instead of rebuilding it")
    parser.add_argument("--title-column", default="job_title")
    parser.add_argument("--level-column", default="experience_level")
    parser.add_argument("--description-column", default="description")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    with args.postings.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fields = list(reader.fieldnames or [])
        rows = list(reader)

    if args.title_column not in fields:
        raise SystemExit(f"column '{args.title_column}' not found. Columns are: {', '.join(fields)}. Use --title-column.")
    for name, option in [(args.level_column, "--level-column"), (args.description_column, "--description-column")]:
        if name not in fields:
            print(f"warning: column '{name}' not found, so it is treated as empty ({option})", file=sys.stderr)

    if args.use_existing_mapping:
        tr = load_title_roles(args.roles)
        note = f"read from `{args.roles.name}`"
    else:
        entries = discover_roles([r.get(args.title_column) for r in rows])
        write_title_roles(entries, args.roles)
        tr = TitleRoles(entries)
        note = f"built from the postings and saved to `{args.roles.name}`"

    lv = ExperienceLevels()
    mapped = map_postings(rows, tr, lv, args.title_column, args.level_column, args.description_column)

    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / "postings_with_roles.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields + ["standard_role", "level", "standard_title"])
        writer.writeheader()
        for row, m in zip(rows, mapped):
            writer.writerow(
                {**row, "standard_role": m["role"] or "", "level": m["level"] or "", "standard_title": m["standard_title"] or ""}
            )

    md = _markdown(mapped, tr, lv, args.postings.name, note)
    (args.out / "title_role_counts.md").write_text(md, encoding="utf-8")
    print(md)


if __name__ == "__main__":
    main()
