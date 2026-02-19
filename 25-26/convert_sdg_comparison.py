"""Convert an `sdg_comparison_*.csv` file into a 25-style CSV (e.g. `25-26.csv`).

Usage:
  python convert_sdg_comparison.py --in sdg_comparison_25-26.csv --out 25-26-converted.csv

If `--out` is omitted and the input filename starts with `sdg_comparison_`, the output
filename will be the input name with that prefix removed. The script will NOT try to
merge links; `Link` is left empty. It preserves comparison info in `Internal comments`.
"""
from __future__ import annotations

import argparse
import ast
import sys
from typing import Any

import pandas as pd


def parse_sdgs_cell(cell: Any) -> list:
    if pd.isna(cell):
        return []
    if isinstance(cell, list):
        return cell
    s = str(cell).strip()
    if s == "" or s == "[]":
        return []
    try:
        val = ast.literal_eval(s)
        if isinstance(val, (list, tuple)):
            return list(val)
        return [val]
    except Exception:
        # fallback: try to split on non-digits
        cleaned = s.strip(" []")
        if cleaned == "":
            return []
        parts = [p.strip() for p in cleaned.split(",") if p.strip()]
        return parts


def sdgs_to_str(lst: list) -> str:
    if not lst:
        return "[]"
    return "[" + ", ".join(str(x) for x in lst) + "]"


def parse_internal_comments_str(s: str) -> dict:
    """Parse an internal comments string like:
    "comparison_status=only_chatgpt;color=RED;sdgs_chatgpt=[...];sdgs_manual=[...]"
    Returns a dict with keys for present items.
    """
    out = {}
    if not s:
        return out
    parts = [p for p in s.split(";") if p.strip()]
    for p in parts:
        if "=" not in p:
            continue
        k, v = p.split("=", 1)
        k = k.strip()
        v = v.strip()
        if k in ("sdgs_chatgpt", "sdgs_manual"):
            try:
                out[k] = ast.literal_eval(v)
            except Exception:
                cleaned = v.strip(" []")
                out[k] = [x.strip() for x in cleaned.split(",") if x.strip()]
        else:
            out[k] = v
    return out


def convert(df: pd.DataFrame) -> pd.DataFrame:
    # Ensure all expected columns exist (use empty when missing)
    for c in [
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
    ]:
        if c not in df.columns:
            df[c] = ""

    out_rows = []
    for _, r in df.iterrows():
        sdg_chat = parse_sdgs_cell(r.get("sdgs_chatgpt", ""))
        sdg_manual = parse_sdgs_cell(r.get("sdgs_manual", ""))
        # If sdgs weren't present in columns, try to parse from an Internal comments string
        internal_comments_raw = r.get("Internal comments", "") or r.get("internal_comments", "")
        if (not sdg_chat or not sdg_manual) and internal_comments_raw:
            parsed_ic = parse_internal_comments_str(internal_comments_raw)
            sdg_chat = sdg_chat or parsed_ic.get("sdgs_chatgpt", [])
            sdg_manual = sdg_manual or parsed_ic.get("sdgs_manual", [])

        # determine other parsed fields (comparison_status, color)
        comparison_status = r.get("comparison_status", "")
        color = r.get("color", "")
        if (not comparison_status or not color) and internal_comments_raw:
            parsed_ic = parsed_ic if 'parsed_ic' in locals() else parse_internal_comments_str(internal_comments_raw)
            comparison_status = comparison_status or parsed_ic.get("comparison_status", "")
            color = color or parsed_ic.get("color", "")
        chosen_sdgs = sdg_manual if sdg_manual else sdg_chat

        is_sustainable = bool(chosen_sdgs)
        field_name = "TRUE" if is_sustainable else "FALSE"
        sustainable_label = "Yes" if is_sustainable else "No"

        course_code = r.get("course_code", "")
        course_name = r.get("course_name_manual") or r.get("course_name_chatgpt") or ""
        level = r.get("level_manual") or r.get("level_chatgpt") or ""
        faculty = r.get("faculty_chatgpt", "")

        internal_comments = (
            f"comparison_status={r.get('comparison_status','')};"
            f"color={r.get('color','')};"
            f"sdgs_chatgpt={sdgs_to_str(sdg_chat)};"
            f"sdgs_manual={sdgs_to_str(sdg_manual)}"
        )

        out_rows.append(
            {
                "Field name": field_name,
                "Course code///Vakcode": course_code,
                "Course name///Vaknaam": course_name,
                "Link": "",
                "Sustainable course?///Duurzaam vak?": sustainable_label,
                "Level///Niveau": level,
                "Faculty///Faculteit": faculty,
                "SDGs///SDG's": sdgs_to_str(chosen_sdgs),
                "Comments///Toelichting": r.get("manual_source", ""),
                "comparison_status": comparison_status,
                "color": color,
                "sdgs_chatgpt": sdgs_to_str(sdg_chat),
                "sdgs_manual": sdgs_to_str(sdg_manual),
                "Internal comments": internal_comments,
            }
        )

    out_df = pd.DataFrame(out_rows)
    # Keep the same column order as the 25-style CSV
    cols = [
        "Field name",
        "Course code///Vakcode",
        "Course name///Vaknaam",
        "Link",
        "Sustainable course?///Duurzaam vak?",
        "Level///Niveau",
        "Faculty///Faculteit",
        "SDGs///SDG's",
        "Comments///Toelichting",
        "comparison_status",
        "color",
        "sdgs_chatgpt",
        "sdgs_manual",
        "Internal comments",
    ]
    return out_df[cols]


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    p = argparse.ArgumentParser(description="Convert sdg_comparison CSV into 25-style CSV")
    p.add_argument("--in", dest="infile", required=True, help="input sdg_comparison CSV")
    p.add_argument("--out", dest="outfile", required=False, help="output CSV (optional)")
    p.add_argument("--preview", action="store_true", help="print preview and do not write file")
    args = p.parse_args(argv)

    infile = args.infile
    outfile = args.outfile
    if not outfile:
        if infile.startswith("sdg_comparison_"):
            outfile = infile.replace("sdg_comparison_", "", 1)
        else:
            outfile = f"converted_{infile}"

    df = pd.read_csv(infile, dtype=str)
    df = df.fillna("")

    out_df = convert(df)

    if args.preview:
        print(out_df.head().to_csv(index=False))
    else:
        out_df.to_csv(outfile, index=False)
        print(f"Wrote {outfile}")


if __name__ == "__main__":
    main()
