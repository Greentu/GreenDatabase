"""
pdf_scrape.py — Extract course data from TU Delft study guide PDFs.

Parses PDFs stored under <year>/pdfs/, detects course blocks using a
regex that matches course headers (e.g. "AESB1120-15 Principles of … 5"),
and extracts 'Course Contents' and 'Study Goals' sections for each course.
Programme metadata (faculty, level, programme name) is read from page 1.

Usage:
    python pdf_scrape.py 22-23

Output: <year>/csvs/tudelft_courses_<year>_from_pdfs.csv
"""

import argparse
import re
from pathlib import Path
import pandas as pd
import pdfplumber

# -----------------------
# CONFIG
# -----------------------
BASE_DIR = Path(__file__).resolve().parent

# Matches a course header line in the PDF full text, e.g.:
#   AESB1120-15 Principles of Chemistry & Thermodynamics 5
# Named groups: code (e.g. "AESB1120-15"), name, ects (credit points)
# Lookaheads require the code to contain both letters and digits.
COURSE_HEADER_RE = re.compile(
    r"^(?P<code>(?=[A-Z0-9-]*[A-Z])(?=[A-Z0-9-]*\d)[A-Z0-9-]{3,})\s+(?P<name>.+?)\s+(?P<ects>\d+(?:[.,]\d+)?)\s*$",
    re.MULTILINE,
)

# The two sections we want to extract text from inside each course block
SECTION_LABELS = ["Course Contents", "Study Goals"]

# When any of these labels appear in the text after a section heading,
# they mark the end of that section's content — stop extracting there
STOP_LABELS = [
    "Responsible Instructor",
    "Course Coordinator",
    "Instructor",
    "Contact Hours / Week",
    "Education Period",
    "Start Education",
    "Exam Period",
    "Course Language",
    "Education Method",
    "Assessment",
    "Course Relations",
    "Expected prior Knowledge",
    "Expected prior knowledge",
    "Literature",
    "Judgement",
    "Remarks",
    "Parts",
    "Prerequisites",
]

# Labels used on page 1 to find the faculty ("Organization") and programme ("Education")
ORG_LABELS = ("Organization", "Organisation")
EDU_LABELS = ("Education",)


# -----------------------
# PDF TEXT EXTRACTION
# -----------------------
def extract_pdf_pages_text(pdf_path: Path) -> list[str]:
    """Return list of page texts. Uses pdfplumber (preferred), fallback to PyPDF2."""

    out = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for p in pdf.pages:
            out.append(p.extract_text() or "")
    return out


def normalize_ws(s: str) -> str:
    """
    Clean up whitespace in extracted PDF text:
    - Normalise Windows line endings to Unix
    - Collapse runs of spaces/tabs to a single space
    - Collapse 3+ consecutive blank lines to 2
    """
    s = s.replace("\r", "\n")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


# -----------------------
# PROGRAM METADATA (page 1)
# -----------------------
def _find_label_value(lines: list[str], labels: tuple[str, ...]) -> str:
    """
    Finds value for label in page-1 text lines.
    Handles patterns like:
      Organization: Wageningen University
      Organization Wageningen University
      Organization
      Wageningen University
    """
    labels_lower = {l.lower() for l in labels}

    for i, line in enumerate(lines):
        if not line:
            continue

        # "Label: value" or "Label - value"
        m = re.match(r"^\s*([A-Za-z][A-Za-z ]{1,40})\s*[:\-]\s*(.+?)\s*$", line)
        if m and m.group(1).strip().lower() in labels_lower:
            return m.group(2).strip()

        # "Label value" or label on its own line
        for lab in labels:
            if re.match(rf"^\s*{re.escape(lab)}\b", line, flags=re.IGNORECASE):
                rest = re.sub(
                    rf"^\s*{re.escape(lab)}\b", "", line, flags=re.IGNORECASE
                ).strip()
                if rest:
                    return rest
                # take next non-empty line
                for j in range(i + 1, min(i + 6, len(lines))):
                    if lines[j].strip():
                        return lines[j].strip()

    return ""


def parse_program_metadata(page1_text: str) -> dict:
    """
    Extract faculty, level, and programme from page 1 of a study guide PDF.
    - faculty : value of the "Organization/Organisation" label (e.g. "TU Delft")
    - program : full value of the "Education" label (e.g. "Master Systems Engineering")
    - level   : first word of the Education value (e.g. "Master"), later
                normalised to "MSc"/"BSc" by sdg_rating.py
    """
    lines = [ln.strip() for ln in (page1_text or "").splitlines()]
    faculty = _find_label_value(lines, ORG_LABELS)
    education_full = _find_label_value(lines, EDU_LABELS)
    level = (
        education_full.split()[0] if education_full.split() else ""
    )  # first word only, e.g. "Master" or "Bachelor"
    return {"faculty": faculty, "level": level, "program": education_full}


# -----------------------
# SECTION EXTRACTION
# -----------------------
def _label_pattern(label: str) -> str:
    """
    Return a regex pattern for a section heading.
    "Course Contents" and "Study Goals" get flexible whitespace patterns
    because pdfplumber sometimes inserts extra spaces between words when
    extracting columnar PDF layouts.
    """
    if label.lower() == "course contents":
        return r"Course\s+Contents\b"
    if label.lower() == "study goals":
        return r"Study\s+Goals\b"
    return re.escape(label)


def extract_section(block: str, label: str) -> str:
    """
    Extract the body text of a named section from a course text block.

    Starts reading after the section heading (e.g. "Course Contents" or
    "Study Goals"), and stops at whichever comes first:
      - Any label in STOP_LABELS (e.g. "Assessment", "Literature")
      - The other section heading (e.g. stop "Course Contents" at "Study Goals")
      - The next course header matched by COURSE_HEADER_RE
    The word "continuation" after a heading is skipped — some PDFs repeat the
    heading on a new page with "(continuation)" appended.

    Returns an empty string if the label is not found in the block.
    """
    start_re = re.compile(
        rf"{_label_pattern(label)}\s*(?:continuation)?\s*", re.IGNORECASE
    )
    m = start_re.search(block)
    if not m:
        return ""

    tail = block[m.end() :]

    # Collect the character position of every possible stop point
    stop_positions = []
    for lab in STOP_LABELS + [l for l in SECTION_LABELS if l.lower() != label.lower()]:
        lab_re = re.compile(rf"\n{re.escape(lab)}\b", re.IGNORECASE)
        mm = lab_re.search(tail)
        if mm:
            stop_positions.append(mm.start())

    # Also stop at the next course header (start of the following course block)
    mm = COURSE_HEADER_RE.search(tail)
    if mm:
        stop_positions.append(mm.start())

    end = min(stop_positions) if stop_positions else len(tail)
    return normalize_ws(tail[:end])


# -----------------------
# PARSE ONE PDF
# -----------------------
def parse_pdf_courses(pdf_path: Path) -> list[dict]:
    """
    Parse all courses out of a single study guide PDF and return them as a
    list of dicts (one per course).

    Strategy:
      1. Concatenate all page texts into one string.
      2. Find every course header with COURSE_HEADER_RE and every
         "Course Contents" heading with a separate search.
      3. For each "Course Contents" hit, walk backwards through the header
         list to find the closest preceding header — that is the course this
         content belongs to.
      4. The course block runs from that header to the start of the next
         header (or end of file), and section text is extracted within it.

    Programme metadata (faculty, level, programme) is shared across all
    courses in the PDF — it is read once from page 1.
    """
    pages = extract_pdf_pages_text(pdf_path)
    page1 = pages[0] if pages else ""
    program_meta = parse_program_metadata(page1)

    full_text = "\n".join(pages)
    matches = list(COURSE_HEADER_RE.finditer(full_text))
    content_hits = list(re.finditer(r"\bCourse\s+Contents\b", full_text, re.IGNORECASE))

    rows = []
    if not matches or not content_hits:
        return rows

    # Walk through every "Course Contents" hit and pair it with the nearest
    # preceding course header using a running index (header_idx)
    header_idx = 0
    for hit in content_hits:
        # Advance header_idx so it always points to the last header before this hit
        while (
            header_idx + 1 < len(matches)
            and matches[header_idx + 1].start() < hit.start()
        ):
            header_idx += 1
        header_match = matches[header_idx]
        # Skip if no header precedes this "Course Contents" (shouldn't happen normally)
        if header_match.start() >= hit.start():
            continue

        code = header_match.group("code").strip()
        name = header_match.group("name").strip()

        # The course block spans from the header to the start of the next header
        start = header_match.start()
        end = (
            matches[header_idx + 1].start()
            if header_idx + 1 < len(matches)
            else len(full_text)
        )
        block = full_text[start:end]

        rows.append(
            {
                "course_name": name,
                "course_code": code,
                "description": extract_section(block, "Course Contents"),
                "learning_objectives": extract_section(block, "Study Goals"),
                "level": program_meta["level"],
                "faculty": program_meta["faculty"],
                "program": program_meta["program"],
                "url": "",  # PDFs have no URL; filled in later if needed
            }
        )

    return rows


# -----------------------
# MAIN: ALL PDFS -> CSV
# -----------------------
def main():
    parser = argparse.ArgumentParser(
        description="Scrape TU Delft study guide PDFs to CSV."
    )
    parser.add_argument(
        "year",
        choices=["22-23", "23-24", "24-25"],
        help="Academic year folder to process (e.g. 22-23)",
    )
    args = parser.parse_args()

    # Input: <year>/pdfs/*.pdf  →  Output: <year>/csvs/tudelft_courses_<year>_from_pdfs.csv
    input_dir = BASE_DIR / args.year / "pdfs"
    out_csv = (
        BASE_DIR / args.year / "csvs" / f"tudelft_courses_{args.year}_from_pdfs.csv"
    )
    out_csv.parent.mkdir(exist_ok=True)

    pdfs = sorted(input_dir.glob("*.pdf"))
    if not pdfs:
        raise FileNotFoundError(f"No PDFs found in {input_dir}")

    all_rows = []
    errors = []  # collects (filename, error message) for PDFs that failed
    total = len(pdfs)
    for idx, pdf in enumerate(pdfs, start=1):
        try:
            pdf_rows = parse_pdf_courses(pdf)
            all_rows.extend(pdf_rows)
            print(f"{pdf.name}: found {len(pdf_rows)} courses")
        except Exception as exc:
            # Don't abort the whole run for one bad PDF — log and continue
            errors.append((pdf.name, str(exc)))
        if idx % 5 == 0 or idx == total:
            print(f"Processed {idx}/{total} PDFs")

    if not all_rows:
        print(
            "WARNING: No courses found in any PDF. Check that COURSE_HEADER_RE matches your PDF format."
        )
        return

    df = pd.DataFrame(all_rows).sort_values(["course_code"], kind="stable")

    # Reorder columns to match the expected input format of sdg_rating.py
    df = df[
        [
            "course_name",
            "course_code",
            "description",
            "learning_objectives",
            "level",
            "faculty",
            "program",
            "url",
        ]
    ]

    # utf-8-sig adds a BOM so Excel opens the file correctly without garbled characters
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"Parsed {len(pdfs)} PDFs, wrote {len(df)} courses to {out_csv}")
    if errors:
        print(f"Skipped {len(errors)} PDFs due to errors:")
        for name, msg in errors:
            print(f"  {name}: {msg}")


if __name__ == "__main__":
    main()
