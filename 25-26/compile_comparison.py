import ast
import json
from pathlib import Path

import pandas as pd

CHATGPT_CSV = Path("tudelft_courses_sdg_formatted.csv")
MANUAL_DIR = Path("Manual_ratings")
OUTPUT_CSV = Path("sdg_comparison.csv")

COLOR_ONLY_CHATGPT = "RED"
COLOR_ONLY_MANUAL = "BROWN"
COLOR_MATCH = "GREEN"
COLOR_MISMATCH = "ORANGE"


def normalize_text(value) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() == "nan":
        return ""
    return text


def to_bool(value) -> bool:
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


def parse_manual_file(path: Path) -> pd.DataFrame:
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
        missing_rows = ",".join(str(idx) for idx in course_code[missing_codes].index[:5])
        detail = f" (rows: {missing_rows})" if missing_rows else ""
        raise AssertionError(
            f"{path.name} has {missing_count} row(s) without Course code after cleanup{detail}"
        )

    out = pd.DataFrame(
        {
            "course_code": course_code,
            "course_name_manual": course_name.map(normalize_text),
            "level_manual": level.map(normalize_text),
            "sdgs_manual": df.apply(build_sdg_list, axis=1),
            "manual_source": path.name,
        }
    )
    return out


def aggregate_manual(manual_frames: list[pd.DataFrame]) -> pd.DataFrame:
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

    manual = (
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
    return manual


def build_chatgpt() -> pd.DataFrame:
    df = pd.read_csv(CHATGPT_CSV)
    out = pd.DataFrame(
        {
            "course_code": df["Course code///Vakcode"].map(normalize_text),
            "course_name_chatgpt": df["Course name///Vaknaam"].map(normalize_text),
            "faculty_chatgpt": df["Faculty///Faculteit"].map(normalize_text),
            "level_chatgpt": df["Level///Niveau"].map(normalize_text),
            "sdgs_chatgpt": df["SDGs///SDG's"].map(parse_sdg_list),
        }
    )
    out = out[out["course_code"].str.len() > 0]
    return out


def format_list(values) -> str:
    if values is None or (isinstance(values, float) and pd.isna(values)):
        return json.dumps([])
    if not isinstance(values, (list, tuple, set)):
        return json.dumps([])
    return json.dumps(sorted(set(int(x) for x in values)))


def compare_rows(row) -> tuple[str, str]:
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
    merged["sdgs_chatgpt"] = merged["sdgs_chatgpt"].apply(
        lambda items: format_list(items or [])
    )
    merged["sdgs_manual"] = merged["sdgs_manual"].apply(
        lambda items: format_list(items or [])
    )
    status_color = merged.apply(compare_rows, axis=1, result_type="expand")
    merged["comparison_status"] = status_color[0]
    merged["color"] = status_color[1]

    column_order = [
        "course_code",
        "course_name_chatgpt",
        "course_name_manual",
        "faculty_chatgpt",
        "level_chatgpt",
        "level_manual",
        "sdgs_chatgpt",
        "sdgs_manual",
        "comparison_status",
        "color",
        "manual_source",
    ]
    merged = merged[column_order]
    merged.to_csv(OUTPUT_CSV, index=False)


if __name__ == "__main__":
    main()
