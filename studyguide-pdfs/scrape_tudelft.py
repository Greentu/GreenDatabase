"""
scrape_tudelft.py — Scrape the TU Delft online study guide for course data.

Navigates to https://studiegids.tudelft.nl/courses using a real browser
(Playwright/Chromium), scrolls to load all course links, then visits each
course page to extract: course name, code, description, learning objectives,
level, faculty, and programme.

Results are written incrementally to a CSV so the run can be safely
interrupted and resumed.

Usage:
    python scrape_tudelft.py [--year 25-26]

Output: <year>/csvs/tudelft_courses_<year>_scraped.csv
"""

import argparse
import time
import logging
import pandas as pd
import csv
import os
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

# -------------
# Config
# -------------

START_URL = "https://studiegids.tudelft.nl/courses"
BASE_DIR = Path(__file__).resolve().parent


def fatal(msg):
    """Log a fatal error and exit immediately."""
    logging.error(msg)
    print(f"[FATAL] {msg}")
    sys.exit(1)


# -------------
# Utility
# -------------


def scroll_full_page(page):
    """Scroll till no new items are loaded."""
    print("Scrolling to load all courses...")
    last_height = page.evaluate("() => document.body.scrollHeight")
    while True:
        page.mouse.wheel(0, 4000)
        time.sleep(1.5)
        new_height = page.evaluate("() => document.body.scrollHeight")
        if new_height == last_height:
            # Double-check: wait a bit longer and measure again before stopping
            time.sleep(2)
            new_height = page.evaluate("() => document.body.scrollHeight")
            if new_height == last_height:
                break
        last_height = new_height
    print("Finished scrolling.")


def get_course_links(page):
    """Extract all course links and names from the fully-scrolled main list."""
    # Selector derived from DOM inspection of the study guide listing page
    links = page.locator("a[href^='/courses/study-guide/educations/']").all()
    courses = []
    seen_urls = set()

    for link in links:
        href = link.get_attribute("href")
        name = link.inner_text().strip()

        if href:
            if href.startswith("/"):
                href = "https://studiegids.tudelft.nl" + href

            if href not in seen_urls:
                courses.append({"url": href, "name": name})
                seen_urls.add(href)

    return courses


def extract_sidebar_value(page, label, retries=3):
    """
    Extract the value for a sidebar label, with retries for lazy-loaded content.

    The sidebar structure is typically:
      <div class="pub-list-item-content">
        <div class="pub-title">Label</div>
        <div class="pub-value">Value</div>
      </div>

    Two strategies are tried in order:
      1. Match .pub-title by exact text, then grab its sibling .pub-value.
      2. Generic XPath: find any element with the label text, take its next sibling.
    """
    for _ in range(retries):
        try:
            # Strategy 1: Specific class selectors (most reliable)
            # Look for .pub-title with exact text
            title_el = page.locator(f".pub-title:text-is('{label}')")
            if title_el.count() > 0:
                # Get sibling .pub-value
                val_el = title_el.locator(
                    "xpath=following-sibling::*[contains(@class, 'pub-value')]"
                )
                if val_el.count() > 0:
                    text = val_el.first.inner_text().strip()
                    if text:
                        return text

            # Strategy 2: Generic Sibling
            # Find any element with the label text, take the next sibling
            val_loc = page.locator(
                f"//*[normalize-space(text())='{label}']/following-sibling::*"
            )
            if val_loc.count() > 0:
                text = val_loc.first.inner_text().strip()
                if text:
                    return text
        except Exception:
            pass

        # Wait before retry
        time.sleep(1)

    return None


def extract_sidebar_values_list(page, label, retries=3):
    """
    Like extract_sidebar_value, but returns all matching values as a list.
    Used for multi-value sidebar fields such as Programme.
    """
    for _ in range(retries):
        try:
            title_el = page.locator(f".pub-title:text-is('{label}')")
            if title_el.count() > 0:
                val_els = title_el.locator(
                    "xpath=following-sibling::*[contains(@class, 'pub-value')]"
                )
                if val_els.count() > 0:
                    values = []
                    for i in range(val_els.count()):
                        text = val_els.nth(i).inner_text().strip()
                        values.extend(
                            [v.strip() for v in text.split("\n") if v.strip()]
                        )
                    if values:
                        return values

            val_loc = page.locator(
                f"//*[normalize-space(text())='{label}']/following-sibling::*"
            )
            if val_loc.count() > 0:
                values = []
                for i in range(val_loc.count()):
                    text = val_loc.nth(i).inner_text().strip()
                    values.extend([v.strip() for v in text.split("\n") if v.strip()])
                if values:
                    return values
        except Exception:
            pass

        time.sleep(1)

    return []


def extract_section_text(page, header_text):
    """
    Extract text from a collapsible course section (e.g. 'Description', 'Learning objectives').

    The section is revealed by a toggle button. If the button's aria-expanded is "false",
    it is clicked to expand the content before reading it.
    The content element is the immediate sibling of the button.
    """
    try:
        # Primary: find button by descendant text (handles nested spans inside buttons)
        descendant_xpath = f"//button[descendant::*[contains(text(), '{header_text}')]]"
        btn = page.locator(descendant_xpath)

        if btn.count() == 0:
            # Fallback: simpler text match directly on the button element
            btn = page.locator(f"button:has-text('{header_text}')")
            if btn.count() == 0:
                return None

        # Expand the section if it is currently collapsed
        if btn.first.is_visible():
            try:
                is_expanded = btn.first.get_attribute("aria-expanded")
                if is_expanded == "false":
                    btn.first.click()
                    time.sleep(0.5)
            except Exception:
                pass

        # Content is the immediate sibling of the toggle button
        content = btn.locator("xpath=following-sibling::*[1]")
        if content.count() > 0:
            return content.first.inner_text().strip()

        return None

    except Exception:
        return None


# -------------
# Main
# -------------


def main():
    parser = argparse.ArgumentParser(description="Scrape TU Delft study guide website.")
    parser.add_argument(
        "--year",
        default="25-26",
        help="Academic year to save results under (default: 25-26)",
    )
    args = parser.parse_args()

    out_dir = BASE_DIR / args.year / "csvs"
    out_dir.mkdir(parents=True, exist_ok=True)
    OUTPUT_CSV = str(out_dir / f"tudelft_courses_{args.year}_scraped.csv")
    LOG_FILE = str(out_dir / f"scraper_{args.year}.log")

    logging.basicConfig(
        filename=LOG_FILE,
        level=logging.ERROR,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        try:
            print(f"Navigating to {START_URL}...")
            page.goto(START_URL, timeout=60000)

            # Wait for content
            page.wait_for_selector(
                "a[href^='/courses/study-guide/educations/']", timeout=10000
            )

            # Scroll
            scroll_full_page(page)

            # Get links and names
            all_courses = get_course_links(page)
            print(f"Found {len(all_courses)} courses.")

            if not all_courses:
                fatal("No course links found!")

            # -------------------------------------------------------
            # Initialize / Resume CSV
            # -------------------------------------------------------
            fieldnames = [
                "course_name",
                "course_code",
                "description",
                "learning_objectives",
                "level",
                "faculty",
                "url",
                "program",
            ]
            processed_urls = set()

            # Check if exists and read processed URLs
            if os.path.exists(OUTPUT_CSV):
                try:
                    df_existing = pd.read_csv(OUTPUT_CSV)
                    original_count = len(df_existing)

                    # CLEANUP: Remove rows with missing or empty course_name
                    # We want to re-scrape these.
                    df_clean = df_existing.dropna(subset=["course_name"])
                    df_clean = df_clean[df_clean["course_name"].str.strip() != ""]

                    cleaned_count = len(df_clean)
                    dropped_count = original_count - cleaned_count

                    if dropped_count > 0:
                        print(
                            f"Cleaning CSV: Removed {dropped_count} incomplete records (missing course_name)."
                        )
                        df_clean.to_csv(OUTPUT_CSV, index=False)
                        print(
                            f"Rewrote {OUTPUT_CSV} with {cleaned_count} valid records."
                        )

                    if "url" in df_clean.columns:
                        processed_urls = set(df_clean["url"].tolist())

                    print(
                        f"Found {len(processed_urls)} existing valid records in {OUTPUT_CSV}. Resuming..."
                    )
                except Exception as e:
                    print(
                        f"Could not read existing CSV (might be empty or corrupt): {e}"
                    )

            # If file doesn't exist or is empty (implied by read failure above), write header
            if not os.path.exists(OUTPUT_CSV) or os.stat(OUTPUT_CSV).st_size == 0:
                with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()

            # Filter URLs
            courses_to_scrape = [
                c for c in all_courses if c["url"] not in processed_urls
            ]
            print(f"Remaining courses to scrape: {len(courses_to_scrape)}")

            # Visit each course
            for i, item in enumerate(courses_to_scrape, 1):
                url = item["url"]
                course_name = item["name"]  # Use pre-extracted name

                retry_count = 0
                max_retries = 3
                success = False

                while retry_count < max_retries and not success:
                    try:
                        print(
                            f"[{i}/{len(courses_to_scrape)}] Processing {url} (Attempt {retry_count + 1})"
                        )

                        # Go to page
                        page.goto(url, timeout=60000)

                        # Smart Wait for SPA hydration
                        # Strategy: Wait for an element that confirms THIS course is loaded.
                        # 1. 'education-id' attribute matching the URL id
                        # 2. OR the active breadcrumb (router-link-exact-active)
                        try:
                            course_id = url.split("/")[-1]
                            # Selector for specific ID or active breadcrumb
                            # We use a composite selector to fail fast if neither appears
                            page.wait_for_selector(
                                f"div[education-id='{course_id}'], .pub-breadcrumb.router-link-exact-active",
                                state="visible",
                                timeout=20000,
                            )
                        except Exception:
                            print(f"  -> Wait timeout. Reloading page...")
                            page.reload()
                            retry_count += 1
                            continue  # Try again

                        # If we passed the wait, we are good to go.
                        success = True

                        # 1. Course Name (Already extracted from main list)
                        if not course_name:
                            # Fallback if list name was somehow empty (unlikely)
                            h1 = page.locator("h1")
                            if h1.count() > 0:
                                course_name = h1.first.inner_text().strip()

                        if not course_name:
                            logging.error(f"Skipping {url}: Missing Course Name")
                            print("  -> SKIP: Missing Course Name")
                            break

                        # 2. Sidebar Fields (Mixed Criticality)
                        # Course code is critical
                        course_code = extract_sidebar_value(
                            page, "Course code", retries=4
                        )
                        if not course_code:
                            logging.error(f"Skipping {url}: Missing Course code")
                            print("  -> SKIP: Missing Course code")
                            break

                        # Faculty is critical (User Request)
                        faculty = extract_sidebar_value(page, "Faculty", retries=4)
                        if not faculty:
                            logging.error(f"Skipping {url}: Missing Faculty")
                            print("  -> SKIP: Missing Faculty")
                            break

                        level = extract_sidebar_value(page, "Level", retries=1) or ""
                        program = str(
                            extract_sidebar_values_list(page, "Programme", retries=1)
                        )

                        # 3. Sections (Optional — not all courses have these)
                        description = extract_section_text(page, "Description") or ""
                        learning_objectives = (
                            extract_section_text(page, "Learning objectives") or ""
                        )

                        # Collect row
                        row = {
                            "course_name": course_name,
                            "course_code": course_code,
                            "description": description,
                            "learning_objectives": learning_objectives,
                            "level": level,
                            "faculty": faculty,
                            "url": url,
                            "program": program,
                        }

                        # Incremental Write
                        with open(OUTPUT_CSV, "a", newline="", encoding="utf-8") as f:
                            writer = csv.DictWriter(f, fieldnames=fieldnames)
                            writer.writerow(row)

                        print("  -> Saved.")

                    except Exception as e:
                        print(f"  -> Error: {e}. Retrying...")
                        retry_count += 1
                        time.sleep(2)

                if not success:
                    logging.error(
                        f"Failed to process {url} after {max_retries} attempts."
                    )
                    print(f"  -> GIVING UP on {url}")

        except Exception as e:
            fatal(f"Global error: {e}")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
