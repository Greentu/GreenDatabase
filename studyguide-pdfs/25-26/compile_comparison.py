"""
compile_comparison.py (25-26) — Compare ChatGPT-rated and manually-rated SDG data.

Merges two data sources on course code and classifies each row as:
  - match        : both sources agree on the SDG list  (GREEN)
  - mismatch     : both sources present but SDGs differ (ORANGE)
  - only_chatgpt : course exists only in the ChatGPT CSV (RED)
  - only_manual  : course exists only in a manual CSV   (BROWN)

Unlike the 22-23 version, manual data here comes from multiple per-faculty
CSV files inside Manual_ratings/. Each file has one boolean column per SDG
(e.g. "SDG 3", "SDG 13"). These are merged by course code before comparison.

Output columns follow the GreenDatabase sheet format so the CSV can be
reviewed before uploading to the Google Sheet.

Run from the studyguide/25-26/ directory:
    python compile_comparison.py
"""

import ast
import json
from pathlib import Path

import pandas as pd

CHATGPT_CSV = Path("csvs/tudelft_courses_25-26_sdg.csv")
MANUAL_DIR = Path("Manual_ratings")  # folder of per-faculty manual rating CSVs
OUTPUT_CSV = Path("csvs/25-26_comparison.csv")

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


def to_bool(value) -> bool:
    """Convert a variety of truthy/falsy representations to a Python bool."""
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    text = normalize_text(value).lower()
    if text in {"true", "t", "yes", "y", "1"}:
        return True
    if text in {"false", "f", "no", "n", "0"}:
        return False
    try:
        return float(text) != 0
    except ValueError:
        return False


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


def parse_manual_file(path: Path) -> pd.DataFrame:
    """
    Parse one per-faculty manual rating CSV into a normalised DataFrame.

    Each column whose name starts with 'SDG' and contains a number is treated
    as a boolean flag for that SDG. Raises AssertionError if any row is missing
    a course code (which would make merging unreliable).
    """
    df = pd.read_csv(path, skipinitialspace=True)
    df.columns = [normalize_text(col) for col in df.columns]
    sdg_cols = []
    sdg_numbers = {}
    for col in df.columns:
        if not col.strip().lower().startswith("sdg"):
            continue
        digits = "".join(ch for ch in col if ch.isdigit())
        if not digits:
            continue
        number = int(digits)
        sdg_cols.append(col)
        sdg_numbers[col] = number

    def build_sdg_list(row) -> list[int]:
        sdgs = []
        for col in sdg_cols:
            if to_bool(row.get(col)):
                sdgs.append(sdg_numbers[col])
        return sorted(set(sdgs))

    course_code = (
        df["Course code"] if "Course code" in df.columns else pd.Series([""] * len(df))
    )
    course_name = (
        df["Course Name"] if "Course Name" in df.columns else pd.Series([""] * len(df))
    )
    level = df["Level"] if "Level" in df.columns else pd.Series([""] * len(df))

    course_code = course_code.map(normalize_text)
    missing_codes = course_code.str.len() == 0
    if missing_codes.any():
        missing_count = int(missing_codes.sum())
        missing_rows = ",".join(
            str(idx) for idx in course_code[missing_codes].index[:5]
        )
        detail = f" (rows: {missing_rows})" if missing_rows else ""
        raise AssertionError(
            f"{path.name} has {missing_count} row(s) without Course code after cleanup{detail}"
        )

    return pd.DataFrame(
        {
            "course_code": course_code,
            "course_name_manual": course_name.map(normalize_text),
            "level_manual": level.map(normalize_text),
            "sdgs_manual": df.apply(build_sdg_list, axis=1),
            "manual_source": path.name,
        }
    )


def aggregate_manual(manual_frames: list[pd.DataFrame]) -> pd.DataFrame:
    """
    Concatenate all per-faculty DataFrames and merge duplicate course codes.
    SDG lists are unioned across files (a course marked in any file keeps all its SDGs).
    The manual_source column records which files contributed to each row.
    """
    if not manual_frames:
        return pd.DataFrame(
            columns=[
                "course_code",
                "course_name_manual",
                "level_manual",
                "sdgs_manual",
                "manual_source",
            ]
        )
    manual = pd.concat(manual_frames, ignore_index=True)
    manual = manual[manual["course_code"].str.len() > 0]

    def merge_lists(series: pd.Series) -> list[int]:
        merged = set()
        for items in series:
            merged.update(items)
        return sorted(merged)

    return (
        manual.groupby("course_code", as_index=False)
        .agg(
            {
                "course_name_manual": "first",
                "level_manual": "first",
                "sdgs_manual": merge_lists,
                "manual_source": lambda s: ";".join(sorted(set(s))),
            }
        )
        .reset_index(drop=True)
    )


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
    manual_frames = [
        parse_manual_file(path)
        for path in sorted(MANUAL_DIR.glob("*.csv"))
        if path.is_file()
    ]
    manual = aggregate_manual(manual_frames)
    chatgpt = build_chatgpt()

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
