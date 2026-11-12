# Skill dictionary (CP-26)

`data/skill_dictionary.csv` maps different spellings of a skill to one name, so
"SQL", "Sql" and "sql" are counted as one skill.

## Editing the dictionary

One row per skill. You can edit it in Excel or any text editor.

| Column | What to put |
|---|---|
| `skill` | The name to show in charts, e.g. `Power BI` |
| `category` | A group for the skill, e.g. `BI & Visualization` |
| `aliases` | Other spellings, separated by `;`, e.g. `PowerBI;Power-BI` |

- The skill name always counts as a spelling of itself. You don't need to list it again.
- Upper and lower case don't matter (`tableau` matches `Tableau`), except for
  spellings of 1-2 characters such as `R` or `ML`, which must match exactly.
- Each spelling can belong to only one skill. The loader stops with an error if
  a spelling is listed under two skills, or if a skill is listed twice.
- Don't add ambiguous short words (`PM`, `TF`, `Go`) unless the descriptions
  really use them that way. They create false matches.

After editing, run the tests and regenerate the counts:

```bash
python -m pytest
python src/skill_counts.py
```

## Using it in code

```python
from skill_dictionary import load_skill_dictionary

sd = load_skill_dictionary()
sd.normalize("PowerBI")                 # "Power BI"
sd.skills_in(description, title=title)  # ["SQL", "Python", ...]
sd.find_mentions(description)           # [("Sql", "SQL"), ...] text as written + skill
```

Pass the posting's `title` so that skills inside the job title are not counted.
The descriptions repeat the title ("Join us as a ML Scientist"), which would
otherwise count as Machine Learning.

## Before/after counts

`python src/skill_counts.py` writes `reports/skill_counts.md`: for each skill, the
postings that mention it after merging, the count for the standard spelling
alone, its rank before and after, and the spellings that were merged. It is
ready to paste into Confluence.

On `synthetic_job_postings.csv`, 34 spellings merge into 21 skills. The biggest
change is PostgreSQL, which moves from rank 32 to rank 19 because most postings
write "Postgres".
