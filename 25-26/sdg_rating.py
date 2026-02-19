import argparse
import csv
import json
import os
import time
import urllib.error
import urllib.request
from typing import Optional

try:
    from tqdm import tqdm
except Exception:
    tqdm = None

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

SDG_KEYS = [f"sdg_{i}" for i in range(1, 18)]

SYSTEM_PROMPT = (
    "You are an expert classifier mapping course content to UN SDGs. "
    "Mark an SDG as present ONLY if the course explicitly teaches that SDG topic. "
    "If unsure, mark false. Respond with JSON only."
)


def truncate(text, limit=4000):
    if text is None:
        return ""
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def build_user_prompt(course, description, objectives):
    sdg_map = "\n".join([f"- SDG {i + 1}: {label}" for i, label in enumerate(SDG_LABELS)])
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
    sdg_map = "\n".join([f"- SDG {i + 1}: {label}" for i, label in enumerate(SDG_LABELS)])
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
                time.sleep(2 ** attempt)
                continue
            raise


def parse_sdg_presence(message_content):
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


def mock_sdg_presence(text):
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
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--model", default="gpt-4o-mini")
    parser.add_argument("--sleep", type=float, default=0.0)
    parser.add_argument("--max-retries", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--mock", action="store_true")
    parser.add_argument("--api-key-file", default="api_key.txt")
    args = parser.parse_args()

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key and os.path.isfile(args.api_key_file):
        with open(args.api_key_file, "r", encoding="utf-8") as f:
            api_key = f.read().strip()
    if not args.mock and not api_key:
        raise SystemExit(
            "Missing API key. Set OPENAI_API_KEY or provide --api-key-file. "
            "Use --mock for dry run."
        )

    with open(args.input, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if args.limit:
        rows = rows[: args.limit]

    excluded_fields = {"description", "learning_objectives"}
    output_fields = [k for k in rows[0].keys() if k not in excluded_fields] + SDG_KEYS
    processed_codes = set()
    if os.path.exists(args.output):
        try:
            with open(args.output, "r", encoding="utf-8", newline="") as f:
                existing = csv.DictReader(f)
                for row in existing:
                    code = (row.get("course_code") or "").strip()
                    if code:
                        processed_codes.add(code)
        except Exception:
            processed_codes = set()

    remaining_rows = [r for r in rows if (r.get("course_code") or "").strip() not in processed_codes]
    total_rows = len(rows)
    resume_offset = total_rows - len(remaining_rows)
    if resume_offset:
        print(f"Resuming: {resume_offset}/{total_rows} already processed.")

    write_header = not os.path.exists(args.output) or os.stat(args.output).st_size == 0
    with open(args.output, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=output_fields)
        if write_header:
            writer.writeheader()

        total_rows = len(remaining_rows)
        start_time = time.time()
        progress: Optional[object] = None
        if tqdm is not None:
            progress = tqdm(total=total_rows + resume_offset, unit="course")
            if resume_offset:
                progress.update(resume_offset)

        idx = 0
        while idx < total_rows:
            batch = remaining_rows[idx : idx + max(1, args.batch_size)]

            if args.batch_size > 1:
                prompt = build_batch_prompt(batch)
                if args.mock:
                    batch_presence = {}
                    for course in batch:
                        combined = " ".join(
                            [
                                course.get("course_name", ""),
                                course.get("description", ""),
                                course.get("learning_objectives", ""),
                            ]
                        )
                        batch_presence[course.get("course_code", "")] = mock_sdg_presence(combined)
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
                    presence = batch_presence.get(course.get("course_code", ""), {})
                    out_row = {k: v for k, v in course.items() if k not in excluded_fields}
                    for i in range(1, 18):
                        out_row[f"sdg_{i}"] = "1" if presence.get(i, False) else "0"
                    writer.writerow(out_row)
                f.flush()
            else:
                for course in batch:
                    description = (course.get("description") or "").strip()
                    objectives = (course.get("learning_objectives") or "").strip()
                    has_description = bool(description)
                    has_objectives = bool(objectives)

                    if not has_description and not has_objectives:
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

                    out_row = {k: v for k, v in course.items() if k not in excluded_fields}
                    for i in range(1, 18):
                        out_row[f"sdg_{i}"] = "1" if presence.get(i, False) else "0"
                    writer.writerow(out_row)
                f.flush()

            idx += len(batch)
            if args.sleep:
                time.sleep(args.sleep)
            last_code = batch[-1].get("course_code", "")
            if progress is not None:
                progress.update(len(batch))
                progress.set_postfix({"last": last_code})
            else:
                elapsed = max(time.time() - start_time, 1e-6)
                rate = (idx + resume_offset) / elapsed
                remaining = total_rows - idx
                eta_seconds = int(remaining / rate) if rate > 0 else 0
                minutes, seconds = divmod(eta_seconds, 60)
                processed = idx + resume_offset
                total_all = total_rows + resume_offset
                print(f"Processed {processed}/{total_all}: {last_code} ETA {minutes}m{seconds:02d}s")

        if progress is not None:
            progress.close()


if __name__ == "__main__":
    main()
