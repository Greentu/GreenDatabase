import json
from pathlib import Path

import pandas as pd

INPUT_CSV = Path('tudelft_courses_25-26_sdg.csv')
OUTPUT_CSV = Path('tudelft_courses_25-26_sdg_formatted.csv')


def normalize_level(value: str) -> str:
    if value is None:
        return ''
    text = str(value).strip()
    lower = text.lower()
    if lower == 'master':
        return 'MSc'
    if lower == 'bachelor':
        return 'BSc'
    return text


def main() -> None:
    df = pd.read_csv(INPUT_CSV)
    sdg_cols = [col for col in df.columns if col.startswith('sdg_')]

    def build_sdg_list(row) -> list[int]:
        sdgs: list[int] = []
        for col in sdg_cols:
            value = row[col]
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                numeric = 0
            if numeric:
                sdgs.append(int(col.split('_', 1)[1]))
        return sdgs

    sdg_values = df.apply(build_sdg_list, axis=1)
    is_sustainable = sdg_values.map(lambda items: len(items) > 0)

    out = pd.DataFrame(
        {
            'Field name': is_sustainable.map(lambda v: 'TRUE' if v else 'FALSE'),
            'Course code///Vakcode': df['course_code'],
            'Course name///Vaknaam': df['course_name'],
            'Link': df['url'],
            'Sustainable course?///Duurzaam vak?': is_sustainable.map(
                lambda v: 'Yes' if v else 'No'
            ),
            'Level///Niveau': df['level'].map(normalize_level),
            'Faculty///Faculteit': df['faculty'],
            "SDGs///SDG's": sdg_values.map(json.dumps),
        }
    )

    out.to_csv(OUTPUT_CSV, index=False)


if __name__ == '__main__':
    main()
