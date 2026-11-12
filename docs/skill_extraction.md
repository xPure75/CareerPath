# Skill extraction (CP-52)

Adds the skills from each job description as a new column, using the
[skill dictionary](skill_dictionary.md).

## Run it

From the repo root:

```bash
python src/extract_skills.py
```

This writes `data/postings_with_skills.csv`: every column from the postings
file, plus two new ones.

| Column | Example | Meaning |
|---|---|---|
| `skills` | `SQL; Python; Power BI` | Standard skill names found in the description, in order of first mention, separated by `; ` |
| `skills_flag` | `ok` | `ok` if skills were found, `no_skills` if the description has none we know, `no_description` if the description is blank or a placeholder (`null`, `?`, `N/A`) |

On `synthetic_job_postings.csv`: 995 postings are `ok`, 0 are `no_skills`,
and 20 are `no_description` (10 `null` and 10 blank).

To read the column back into a list, use `split_skills()` from
`src/extract_skills.py`. To extract skills for a single posting in code, use
`extract_skills(row, sd)`, which returns `(skills, flag)`.

## Measure recall (CP-55)

```bash
python src/measure_recall.py
```

This compares the extracted skills with `data/skill_labels_sample.csv`, which
holds 50 postings and the skills each one asks for (`expected_skills`), and
writes `reports/recall_check.md`.

- **Recall:** of the skills the postings ask for, the share that were found. The CP-52 target is at least 80%.
- **Precision:** of the skills found, the share the postings actually ask for.

**How the labels were made.** The 50 postings were drawn at random with a fixed
seed (52), so the same sample comes out every time. `expected_skills` was
pre-filled from each posting's own skill list, then checked by hand against the
description. The extractor never reads the labels file.

`python src/measure_recall.py --make-sample` draws the sample again and
overwrites the labels file. Only do this for a new dataset, and review the
labels by hand afterwards. The pre-fill only works for the phrasing in the
synthetic data, so real job postings will need labelling by hand.

## Limits

The synthetic postings list their skills in a clean comma list, which makes
extraction easy: recall and precision are both 100% on the sample. Real job
postings are full prose and will score lower. Watch for ordinary words that
match skills (for example "you will excel"), skills missing from the
dictionary, and "nice to have" skills counted as required.
