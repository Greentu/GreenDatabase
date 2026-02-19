import time
import logging
import pandas as pd
import csv
import os
import sys
from playwright.sync_api import sync_playwright, TimeoutError

# -------------
# Config
# -------------

START_URL = "https://studiegids.tudelft.nl/courses"
OUTPUT_CSV = "tudelft_courses_25-26.csv"
LOG_FILE = "scraper.log"

# Setup logger
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.ERROR,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

def fatal(msg):
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
    # count = 0
    while True:
        page.mouse.wheel(0, 4000)
        time.sleep(1.5)
        new_height = page.evaluate("() => document.body.scrollHeight")
        if new_height == last_height:
            # Try one more time to be sure
            time.sleep(2)
            new_height = page.evaluate("() => document.body.scrollHeight")
            if new_height == last_height:
                break
        last_height = new_height
        # # For Debugging purposes
        # if count > 10:
        #     break
        # count += 1
    print("Finished scrolling.")


def get_course_links(page):
    """Extract all course links and names from the main list."""
    # Selector based on inspection
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
    Extracts value for a label in the sidebar with retry support for lazy loading.
    Structure usually: 
      <div class="pub-list-item-content">
         <div class="pub-title">Label</div>
         <div class="pub-value">Value</div>
      </div>
    """
    for _ in range(retries):
        try:
            # Strategy 1: Specific class selectors (most reliable)
            # Look for .pub-title with exact text
            title_el = page.locator(f".pub-title:text-is('{label}')")
            if title_el.count() > 0:
                # Get sibling .pub-value
                val_el = title_el.locator("xpath=following-sibling::*[contains(@class, 'pub-value')]")
                if val_el.count() > 0:
                    text = val_el.first.inner_text().strip()
                    if text: return text
            
            # Strategy 2: Generic Sibling
            # Find any element with the label text, take the next sibling
            val_loc = page.locator(f"//*[normalize-space(text())='{label}']/following-sibling::*")
            if val_loc.count() > 0:
                text = val_loc.first.inner_text().strip()
                if text: return text
        except Exception:
            pass
            
        # Wait before retry
        time.sleep(1)

    return None


def extract_section_text(page, header_text):
    """
    Extracts text from a collapsible section like 'Description'.
    """
    try:
        # Locate button with header text
        # Using xpath to find button that contains the text
        # //button[descendant::*[contains(text(), 'Header')]]
        descendant_xpath = f"//button[descendant::*[contains(text(), '{header_text}')]]"
        btn = page.locator(descendant_xpath)
        
        if btn.count() == 0:
            # Fallback: simple text match on button
            btn = page.locator(f"button:has-text('{header_text}')")
            if btn.count() == 0:
                return None
        
        # Click if visible to ensure content is loaded/visible
        # (Course pages often load with sections collapsed or expanded, clicking toggles)
        # We need to check if it's already expanded usually by looking at aria-expanded or just click.
        # But brute force click often works if we wait.
        
        # Actually, if we just want text, sometimes it's hidden. 
        # But 'inner_text' might get it if it's just in DOM.
        # Let's try to expand.
        if btn.first.is_visible():
            try:
                # Check expanded state if possible, but for now just click if needed?
                # The site toggles. If we click, it might close. 
                # Inspecting DOM: aria-expanded="true" or "false".
                is_expanded = btn.first.get_attribute("aria-expanded")
                if is_expanded == "false":
                    btn.first.click()
                    time.sleep(0.5)
            except:
                pass 
        
        # Content is the next sibling element (often a span wrapping a div)
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
    courses_data = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        try:
            print(f"Navigating to {START_URL}...")
            page.goto(START_URL, timeout=60000)
            
            # Wait for content
            page.wait_for_selector("a[href^='/courses/study-guide/educations/']", timeout=10000)
            
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
            fieldnames = ["course_name", "course_code", "description", "learning_objectives", "level", "faculty", "url"]
            processed_urls = set()
            
            # Check if exists and read processed URLs
            if os.path.exists(OUTPUT_CSV):
                try:
                    df_existing = pd.read_csv(OUTPUT_CSV)
                    original_count = len(df_existing)
                    
                    # CLEANUP: Remove rows with missing or empty course_name
                    # We want to re-scrape these.
                    df_clean = df_existing.dropna(subset=['course_name'])
                    df_clean = df_clean[df_clean['course_name'].str.strip() != '']
                    
                    cleaned_count = len(df_clean)
                    dropped_count = original_count - cleaned_count
                    
                    if dropped_count > 0:
                        print(f"Cleaning CSV: Removed {dropped_count} incomplete records (missing course_name).")
                        df_clean.to_csv(OUTPUT_CSV, index=False)
                        print(f"Rewrote {OUTPUT_CSV} with {cleaned_count} valid records.")
                    
                    if "url" in df_clean.columns:
                        processed_urls = set(df_clean["url"].tolist())
                        
                    print(f"Found {len(processed_urls)} existing valid records in {OUTPUT_CSV}. Resuming...")
                except Exception as e:
                    print(f"Could not read existing CSV (might be empty or corrupt): {e}")

            # If file doesn't exist or is empty (implied by read failure above), write header
            if not os.path.exists(OUTPUT_CSV) or os.stat(OUTPUT_CSV).st_size == 0:
                 with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
            
            # Filter URLs
            courses_to_scrape = [c for c in all_courses if c["url"] not in processed_urls]
            print(f"Remaining courses to scrape: {len(courses_to_scrape)}")

            # Visit each course
            for i, item in enumerate(courses_to_scrape, 1):
                url = item["url"]
                course_name = item["name"] # Use pre-extracted name
                
                retry_count = 0
                max_retries = 3
                success = False
                
                while retry_count < max_retries and not success:
                    try:
                        print(f"[{i}/{len(courses_to_scrape)}] Processing {url} (Attempt {retry_count+1})")
                        
                        # Go to page
                        page.goto(url, timeout=60000)
                        
                        # Smart Wait for SPA hydration
                        # Strategy: Wait for an element that confirms THIS course is loaded.
                        # 1. 'education-id' attribute matching the URL id
                        # 2. OR the active breadcrumb (router-link-exact-active)
                        try:
                            course_id = url.split('/')[-1]
                            # Selector for specific ID or active breadcrumb
                            # We use a composite selector to fail fast if neither appears
                            page.wait_for_selector(
                                f"div[education-id='{course_id}'], .pub-breadcrumb.router-link-exact-active", 
                                state="visible", 
                                timeout=20000
                            )
                        except Exception:
                            print(f"  -> Wait timeout. Reloading page...")
                            page.reload()
                            retry_count += 1
                            continue # Try again
                        
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
                             print(f"  -> SKIP: Missing Course Name")
                             break 


                        # 2. Sidebar Fields (Mixed Criticality)
                        # Course code is critical
                        course_code = extract_sidebar_value(page, "Course code", retries=4)
                        if not course_code:
                            logging.error(f"Skipping {url}: Missing Course code")
                            print(f"  -> SKIP: Missing Course code")
                            break

                        # Faculty is critical (User Request)
                        faculty = extract_sidebar_value(page, "Faculty", retries=4)
                        if not faculty:
                            logging.error(f"Skipping {url}: Missing Faculty")
                            print(f"  -> SKIP: Missing Faculty")
                            break

                        level = extract_sidebar_value(page, "Level", retries=1) or ""

                        # 3. Sections (Optional)
                        description = extract_section_text(page, "Description")
                        if not description:
                            description = ""
                            # logging.warning(f"Missing Description at {url}")
                        
                        learning_objectives = extract_section_text(page, "Learning objectives")
                        if not learning_objectives:
                             learning_objectives = ""
                             # logging.warning(f"Missing Learning objectives at {url}")

                        # Collect row
                        row = {
                            "course_name": course_name,
                            "course_code": course_code,
                            "description": description,
                            "learning_objectives": learning_objectives,
                            "level": level,
                            "faculty": faculty,
                            "url": url
                        }

                        # Incremental Write
                        with open(OUTPUT_CSV, "a", newline="", encoding="utf-8") as f:
                            writer = csv.DictWriter(f, fieldnames=fieldnames)
                            writer.writerow(row)
                        
                        print(f"  -> Saved.")

                    except Exception as e:
                        print(f"  -> Error: {e}. Retrying...")
                        retry_count += 1
                        time.sleep(2)
                
                if not success:
                    logging.error(f"Failed to process {url} after {max_retries} attempts.")
                    print(f"  -> GIVING UP on {url}")

        except Exception as e:
             fatal(f"Global error: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    main()
