"""
compile_comparison.py (22-23) — Compare ChatGPT-rated and manually-rated SDG data.

Merges two CSVs on course code and classifies each row as:
  - match        : both sources agree on the SDG list  (GREEN)
  - mismatch     : both sources present but SDGs differ (ORANGE)
  - only_chatgpt : course exists only in the ChatGPT CSV (RED)
  - only_manual  : course exists only in the manual CSV  (BROWN)

The manual data for 22-23 comes from a single pre-merged CSV (DB-22-23.csv)
already formatted with bilingual column names (///Vakcode style), unlike the
25-26 version which reads from per-faculty files.

Output columns follow the GreenDatabase sheet format so the CSV can be
reviewed before uploading to the Google Sheet.

Run from the studyguide/22-23/ directory:
    python compile_comparison.py
"""

import ast
import json
from pathlib import Path

import pandas as pd

CHATGPT_CSV = Path("csvs/tudelft_courses_22-23_sdg.csv")
MANUAL_CSV = Path("csvs/DB-22-23.csv")
OUTPUT_CSV = Path("csvs/comparison_22-23.csv")

# Color labels written to the output CSV to make review easier in spreadsheet tools
COLOR_ONLY_CHATGPT = "RED"
COLOR_ONLY_MANUAL = "BROWN"
COLOR_MATCH = "GREEN"
COLOR_MISMATCH = "ORANGE"


def normalize_text(value) -> str:
    """Strip whitespace and convert pandas NaN / None to an empty string."""
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() == "nan":
        return ""
    return text


def parse_sdg_list(raw) -> list[int]:
    """
    Parse an SDG field into a list of integers.
    Handles JSON strings ('[3, 13]'), Python literal strings, or plain lists.
    Returns [] for missing / unparseable values.
    """
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return []
    if isinstance(raw, list):
        return [int(x) for x in raw]
    text = normalize_text(raw)
    if not text:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        try:
            data = ast.literal_eval(text)
        except (ValueError, SyntaxError):
            return []
    if isinstance(data, list):
        return [int(x) for x in data]
    return []


def sdgs_to_str(lst: list) -> str:
    """Format a list of SDG numbers as a compact JSON-style string, e.g. '[3, 13]'."""
    if not lst:
        return "[]"
    return "[" + ", ".join(str(x) for x in lst) + "]"


def build_chatgpt() -> pd.DataFrame:
    """Load and normalise the ChatGPT-rated CSV into a standard DataFrame."""
    df = pd.read_csv(CHATGPT_CSV)
    return pd.DataFrame(
        {
            "course_code": df["Course code///Vakcode"].map(normalize_text),
            "course_name_chatgpt": df["Course name///Vaknaam"].map(normalize_text),
            "link_chatgpt": df["Link"].map(normalize_text)
            if "Link" in df.columns
            else "",
            "faculty_chatgpt": df["Faculty///Faculteit"].map(normalize_text),
            "level_chatgpt": df["Level///Niveau"].map(normalize_text),
            "program_chatgpt": df["Program"].map(normalize_text)
            if "Program" in df.columns
            else "",
            "sdgs_chatgpt": df["SDGs///SDG's"].map(parse_sdg_list),
        }
    )


# DB-22-23.csv is a single merged manual CSV already in the ///Vakcode format,
# unlike 25-26 which uses per-faculty files with simple column names.
def build_manual() -> pd.DataFrame:
    df = pd.read_csv(MANUAL_CSV)
    return pd.DataFrame(
        {
            "course_code": df["Course code///Vakcode"].map(normalize_text),
            "course_name_manual": df["Course name///Vaknaam"].map(normalize_text),
            "level_manual": df["Level///Niveau"].map(normalize_text),
            "sdgs_manual": df["SDGs///SDG's"].map(parse_sdg_list),
            "manual_source": MANUAL_CSV.name,
        }
    )


def compare_rows(row) -> tuple[str, str]:
    """
    Classify a merged row by comparing ChatGPT and manual SDG lists.
    Returns a (status, color) tuple used for review in spreadsheet tools.
    """
    merge_status = row.get("_merge")
    if merge_status == "left_only":
        return "only_chatgpt", COLOR_ONLY_CHATGPT
    if merge_status == "right_only":
        return "only_manual", COLOR_ONLY_MANUAL

    chatgpt_sdgs = set(row.get("sdgs_chatgpt") or [])
    manual_sdgs = set(row.get("sdgs_manual") or [])
    if chatgpt_sdgs == manual_sdgs:
        return "match", COLOR_MATCH
    return "mismatch", COLOR_MISMATCH


def main() -> None:
    chatgpt = build_chatgpt()
    manual = build_manual()

    merged = chatgpt.merge(manual, on="course_code", how="outer", indicator=True)

    status_color = merged.apply(compare_rows, axis=1, result_type="expand")
    merged["comparison_status"] = status_color[0]
    merged["color"] = status_color[1]

    out_rows = []
    for _, r in merged.iterrows():
        sdg_chat = r.get("sdgs_chatgpt")
        sdg_chat = sdg_chat if isinstance(sdg_chat, list) else []
        sdg_manual = r.get("sdgs_manual")
        sdg_manual = sdg_manual if isinstance(sdg_manual, list) else []
        # Manual ratings take precedence; fall back to ChatGPT if manual is empty
        chosen_sdgs = sdg_manual if sdg_manual else sdg_chat
        is_sustainable = bool(chosen_sdgs)

        course_name = normalize_text(r.get("course_name_manual")) or normalize_text(
            r.get("course_name_chatgpt")
        )
        level = normalize_text(r.get("level_manual")) or normalize_text(
            r.get("level_chatgpt")
        )

        internal_comments = (
            f"comparison_status={r.get('comparison_status', '')};"
            f"color={r.get('color', '')};"
            f"sdgs_chatgpt={sdgs_to_str(sdg_chat)};"
            f"sdgs_manual={sdgs_to_str(sdg_manual)}"
        )

        out_rows.append(
            {
                "Field name": "TRUE" if is_sustainable else "FALSE",
                "Course code///Vakcode": normalize_text(r.get("course_code")),
                "Course name///Vaknaam": course_name,
                "Link": normalize_text(r.get("link_chatgpt")),
                "Sustainable course?///Duurzaam vak?": "Yes"
                if is_sustainable
                else "No",
                "Level///Niveau": level,
                "Faculty///Faculteit": normalize_text(r.get("faculty_chatgpt")),
                "Program": normalize_text(r.get("program_chatgpt")),
                "SDGs///SDG's": sdgs_to_str(chosen_sdgs),
                "Comments///Toelichting": normalize_text(r.get("manual_source")),
                "comparison_status": r.get("comparison_status", ""),
                "color": r.get("color", ""),
                "sdgs_chatgpt": sdgs_to_str(sdg_chat),
                "sdgs_manual": sdgs_to_str(sdg_manual),
                "Internal comments": internal_comments,
            }
        )

    out_df = pd.DataFrame(out_rows)
    out_df.to_csv(OUTPUT_CSV, index=False)
    print(f"Wrote {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
