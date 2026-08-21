"""
sdg_rating.py — Rate TU Delft courses against the 17 UN SDGs using the OpenAI API.

Reads a scraped courses CSV (course_name, course_code, description,
learning_objectives, level, faculty, url, program), sends each course's
text to a GPT model, and writes a new CSV with SDG presence flags and
a 'Sustainable course?' column.

Supports single-course and batched API calls, resumable runs, and a
--mock flag for offline testing without an API key.

Usage:
    python sdg_rating.py --input tudelft_courses.csv --output tudelft_courses_sdg.csv
    python sdg_rating.py --mock          # dry run using keyword matching
    python sdg_rating.py --batch-size 5  # send 5 courses per API call
"""

import argparse
import csv
import json
import os
import time
import urllib.error
import urllib.request
from tqdm import tqdm

SDG_LABELS = [
    "SDG 1 No Poverty",
    "SDG 2 Zero Hunger",
    "SDG 3 Good Health & Well-Being",
    "SDG 4 Quality Education",
    "SDG 5 Gender Equality",
    "SDG 6 Clean Water & Sanitation",
    "SDG 7 Affordable & Clean Energy",
    "SDG 8 Decent Work & Economic Growth",
    "SDG 9 Industry, Innovation & Infrastructure",
    "SDG 10 Reduced Inequalities",
    "SDG 11 Sustainable Cities & Communities",
    "SDG 12 Responsible Consumption & Production",
    "SDG 13 Climate Action",
    "SDG 14 Life Below Water",
    "SDG 15 Life On Land",
    "SDG 16 Peace, Justice & Strong Institutions",
    "SDG 17 Partnerships for the Goals",
]

OUTPUT_FIELDS = [
    "Field name",
    "Course code///Vakcode",
    "Course name///Vaknaam",
    "Link",
    "Sustainable course?///Duurzaam vak?",
    "Level///Niveau",
    "Faculty///Faculteit",
    "Program",
    "SDGs///SDG's",
]

SYSTEM_PROMPT = (
    "You are an expert classifier mapping course content to UN SDGs. "
    "Mark an SDG as present ONLY if the course explicitly teaches that SDG topic. "
    "If unsure, mark false. Respond with JSON only."
)


def truncate(text, limit=4000):
    """Trim text to `limit` characters to stay within API token budgets."""
    if text is None:
        return ""
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def build_user_prompt(course, description, objectives):
    """
    Build the user-side prompt for a single course API call.
    Includes the full SDG label list so the model knows what each number means,
    then the course metadata and (truncated) description + learning objectives.
    The model is expected to return a JSON object like:
        {"sdg_presence": {"SDG 1": false, "SDG 2": false, ..., "SDG 13": true, ...}}
    """
    sdg_map = "\n".join(
        [f"- SDG {i + 1}: {label}" for i, label in enumerate(SDG_LABELS)]
    )
    lines = [
        "Return a JSON object with keys 'sdg_presence' and values true/false.",
        "The 'sdg_presence' object must contain keys 'SDG 1' through 'SDG 17'.",
        "Only mark an SDG true if explicitly taught in the provided text.",
        "SDG labels:",
        sdg_map,
        "Course details:",
        f"Name: {course.get('course_name', '')}",
        f"Code: {course.get('course_code', '')}",
        f"Level: {course.get('level', '')}",
        f"Faculty: {course.get('faculty', '')}",
        f"URL: {course.get('url', '')}",
        "Description:",
        truncate(description),
        "Learning objectives:",
        truncate(objectives),
    ]
    return "\n".join(lines)


def build_batch_prompt(courses):
    """
    Build a single prompt containing multiple courses for one batched API call.
    Courses are separated by "---". The model is expected to return a JSON array:
        [{"course_code": "...", "sdg_presence": {"SDG 1": false, ..., "SDG 13": true}}, ...]
    Use --batch-size > 1 to enable this path. Batching reduces API calls but
    can produce lower-quality results if the context gets too large.
    """
    sdg_map = "\n".join(
        [f"- SDG {i + 1}: {label}" for i, label in enumerate(SDG_LABELS)]
    )
    lines = [
        "Return a JSON array. Each item must include:",
        "- course_code (string)",
        "- sdg_presence object with keys 'SDG 1' through 'SDG 17' and boolean values",
        "Only mark an SDG true if explicitly taught in the provided text.",
        "SDG labels:",
        sdg_map,
        "Courses:",
    ]

    for course in courses:
        lines.extend(
            [
                f"Course code: {course.get('course_code', '')}",
                f"Name: {course.get('course_name', '')}",
                f"Level: {course.get('level', '')}",
                f"Faculty: {course.get('faculty', '')}",
                f"URL: {course.get('url', '')}",
                "Description:",
                truncate(course.get("description", "")),
                "Learning objectives:",
                truncate(course.get("learning_objectives", "")),
                "---",
            ]
        )

    return "\n".join(lines)


def call_openai(prompt, model, api_key, timeout=60, max_retries=5):
    """Send a chat completion request to the OpenAI API with retry/back-off on rate limits."""
    url = "https://api.openai.com/v1/chat/completions"
    payload = {
        "model": model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    }
    data = json.dumps(payload).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    for attempt in range(1, max_retries + 1):
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
            return json.loads(raw)
        except urllib.error.HTTPError as err:
            if err.code == 429 and attempt < max_retries:
                retry_after = err.headers.get("Retry-After")
                try:
                    sleep_seconds = int(retry_after) if retry_after else 10
                except ValueError:
                    sleep_seconds = 10
                time.sleep(sleep_seconds)
                continue
            if err.code in {500, 502, 503, 504} and attempt < max_retries:
                time.sleep(2**attempt)
                continue
            raise


def parse_sdg_presence(message_content):
    """Parse a single-course SDG JSON response into a dict of {sdg_number: bool}."""
    try:
        parsed = json.loads(message_content)
    except json.JSONDecodeError:
        start = message_content.find("{")
        end = message_content.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("No JSON object found in response.")
        parsed = json.loads(message_content[start : end + 1])

    presence = parsed.get("sdg_presence", {})
    result = {}
    for i in range(1, 18):
        key = f"SDG {i}"
        value = presence.get(key, False)
        result[i] = bool(value)
    return result


def parse_batch_presence(message_content):
    """Parse a batch SDG JSON response into a dict of {course_code: {sdg_number: bool}}."""
    try:
        parsed = json.loads(message_content)
    except json.JSONDecodeError:
        start = message_content.find("[")
        end = message_content.rfind("]")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("No JSON array found in response.")
        parsed = json.loads(message_content[start : end + 1])

    results = {}
    for item in parsed:
        course_code = item.get("course_code", "")
        presence = item.get("sdg_presence", {})
        result = {}
        for i in range(1, 18):
            key = f"SDG {i}"
            result[i] = bool(presence.get(key, False))
        if course_code:
            results[course_code] = result
    return results


def normalize_level(value):
    """Normalise level strings to the GreenDatabase convention: 'Master' → 'MSc', 'Bachelor' → 'BSc'."""
    text = str(value or "").strip().lower()
    if text == "master":
        return "MSc"
    if text == "bachelor":
        return "BSc"
    return str(value or "").strip()


def format_row(course, presence):
    """
    Convert a course dict and its SDG presence dict into one output CSV row.
    Collects the SDG numbers that are True into a JSON list (e.g. [3, 13]),
    sets 'Field name' to TRUE/FALSE and 'Sustainable course?' to Yes/No
    based on whether any SDGs were found.
    """
    sdg_list = [i for i in range(1, 18) if presence.get(i, False)]
    is_sustainable = len(sdg_list) > 0
    return {
        "Field name": "TRUE" if is_sustainable else "FALSE",
        "Course code///Vakcode": course.get("course_code", ""),
        "Course name///Vaknaam": course.get("course_name", ""),
        "Link": course.get("url", ""),
        "Sustainable course?///Duurzaam vak?": "Yes" if is_sustainable else "No",
        "Level///Niveau": normalize_level(course.get("level", "")),
        "Faculty///Faculteit": course.get("faculty", ""),
        "Program": course.get("program", ""),
        "SDGs///SDG's": json.dumps(sdg_list),
    }


def mock_sdg_presence(text):
    """
    Offline fallback: detect SDGs by keyword matching instead of calling the API.
    Used when --mock is passed. Covers only a subset of SDGs — not a replacement
    for the real classifier.
    """
    keywords = {
        3: ["health", "medical", "well-being"],
        4: ["education", "learning", "teaching", "pedagogy"],
        6: ["water", "sanitation", "wastewater"],
        7: ["energy", "power", "renewable"],
        9: ["innovation", "infrastructure", "industry", "engineering"],
        11: ["urban", "city", "cities", "community", "communities"],
        12: ["sustainab", "consumption", "production", "circular"],
        13: ["climate", "carbon", "emissions"],
        14: ["ocean", "marine", "sea", "water"],
        15: ["biodiversity", "ecosystem", "forest", "soil", "land"],
    }
    text = text.lower()
    result = {i: False for i in range(1, 18)}
    for sdg_id, words in keywords.items():
        if any(word in text for word in words):
            result[sdg_id] = True
    return result


def main():
    parser = argparse.ArgumentParser(description="Rate courses against SDGs.")
    parser.add_argument("--input", default="tudelft_courses.csv")
    parser.add_argument("--output", default="tudelft_courses_sdg.csv")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process only the first N courses (useful for testing)",
    )
    parser.add_argument(
        "--model",
        default="gpt-4o-mini",
        help="OpenAI model to use (e.g. gpt-4o, gpt-4o-mini)",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.0,
        help="Seconds to wait between API calls (use if hitting rate limits)",
    )
    parser.add_argument("--max-retries", type=int, default=8)
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1,
        help="Number of courses to send in one API call (default: 1)",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Skip the API and use keyword matching instead (no key needed)",
    )
    parser.add_argument(
        "--api-key-file",
        default="openai_api_key.txt",
        help="Path to a plain-text file containing the OpenAI API key",
    )
    args = parser.parse_args()

    # Load API key: environment variable takes precedence over key file
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key and os.path.isfile(args.api_key_file):
        with open(args.api_key_file, "r", encoding="utf-8") as f:
            api_key = f.read().strip()
    if not args.mock and not api_key:
        raise SystemExit(
            "Missing API key. Set OPENAI_API_KEY or provide --api-key-file. "
            "Use --mock for dry run."
        )

    # Read all input rows upfront
    with open(args.input, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if args.limit:
        rows = rows[: args.limit]

    # Resume support: read course codes already present in the output file
    # so interrupted runs can continue without re-processing courses
    processed_codes = set()
    if os.path.exists(args.output):
        try:
            with open(args.output, "r", encoding="utf-8", newline="") as f:
                existing = csv.DictReader(f)
                for row in existing:
                    code = (row.get("Course code///Vakcode") or "").strip()
                    if code:
                        processed_codes.add(code)
        except Exception:
            processed_codes = set()

    remaining_rows = [
        r for r in rows if (r.get("course_code") or "").strip() not in processed_codes
    ]
    total_rows = len(rows)
    resume_offset = total_rows - len(remaining_rows)
    if resume_offset:
        print(f"Resuming: {resume_offset}/{total_rows} already processed.")

    # Open output in append mode so partial results are never overwritten;
    # write the CSV header only when creating the file fresh
    write_header = not os.path.exists(args.output) or os.stat(args.output).st_size == 0
    with open(args.output, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
        if write_header:
            writer.writeheader()

        total_rows = len(remaining_rows)
        progress = tqdm(total=total_rows + resume_offset, unit="course")
        if resume_offset:
            progress.update(resume_offset)  # start bar at the already-done count

        idx = 0
        while idx < total_rows:
            batch = remaining_rows[idx : idx + max(1, args.batch_size)]

            if args.batch_size > 1:
                # --- Batched path: one API call for multiple courses ---
                prompt = build_batch_prompt(batch)
                if args.mock:
                    # Mock: run keyword matching per course, store under course_code key
                    batch_presence = {}
                    for course in batch:
                        combined = " ".join(
                            [
                                course.get("course_name", ""),
                                course.get("description", ""),
                                course.get("learning_objectives", ""),
                            ]
                        )
                        batch_presence[course.get("course_code", "")] = (
                            mock_sdg_presence(combined)
                        )
                else:
                    response = call_openai(
                        prompt,
                        args.model,
                        api_key,
                        max_retries=args.max_retries,
                    )
                    content = response["choices"][0]["message"]["content"]
                    batch_presence = parse_batch_presence(content)

                for course in batch:
                    # Fall back to empty presence if model omitted this course_code
                    presence = batch_presence.get(course.get("course_code", ""), {})
                    writer.writerow(format_row(course, presence))
                f.flush()  # write to disk after each batch so partial runs are recoverable
            else:
                # --- Single-course path (default): one API call per course ---
                for course in batch:
                    description = (course.get("description") or "").strip()
                    objectives = (course.get("learning_objectives") or "").strip()

                    if not description and not objectives:
                        # No text to classify — mark all SDGs false
                        presence = {i: False for i in range(1, 18)}
                    else:
                        prompt = build_user_prompt(course, description, objectives)
                        if args.mock:
                            combined = " ".join(
                                [course.get("course_name", ""), description, objectives]
                            )
                            presence = mock_sdg_presence(combined)
                        else:
                            response = call_openai(
                                prompt,
                                args.model,
                                api_key,
                                max_retries=args.max_retries,
                            )
                            content = response["choices"][0]["message"]["content"]
                            presence = parse_sdg_presence(content)

                    writer.writerow(format_row(course, presence))
                f.flush()

            idx += len(batch)
            if args.sleep:
                time.sleep(args.sleep)
            last_code = batch[-1].get("course_code", "")
            progress.update(len(batch))
            progress.set_postfix({"last": last_code})

        progress.close()


if __name__ == "__main__":
    main()
