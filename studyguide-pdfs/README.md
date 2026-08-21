# How to use these scripts

## Install dependencies (first time only)

**conda:**
```bash
conda activate greenTU
pip install -r requirements.txt
playwright install chromium
```

**venv / pip:**
```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Mac/Linux
pip install -r requirements.txt
playwright install chromium
```

> `playwright install chromium` downloads the browser used by the scraper. Only needed once.

---

## Step 1: Get course data

You need a courses CSV before you can rate SDGs. Use **either** method below depending on the year.

### From the website (25-26 and onwards)

Scrapes the live TU Delft study guide. A browser window will open — that's normal.

```bash
python scrape_tudelft.py
```

Defaults to `25-26`. For a different year:

```bash
python scrape_tudelft.py --year 26-27
```

Output: `<year>/csvs/tudelft_courses_<year>_scraped.csv`

### From PDFs (22-23, 23-24, 24-25)

Put the study guide PDFs in the correct `pdfs` folder:
- `22-23/pdfs/` for the 2022–2023 study guides
- `23-24/pdfs/` for the 2023–2024 study guides
- `24-25/pdfs/` for the 2024–2025 study guides

Then run:

```bash
python pdf_scrape.py 22-23
```

Change `22-23` to whichever year you want.

Output: `<year>/csvs/tudelft_courses_<year>_from_pdfs.csv`

Both scripts resume automatically if interrupted.

---

## Step 2: Rate courses against SDGs

```bash
python sdg_rating.py --input 22-23/csvs/tudelft_courses_22-23_from_pdfs.csv --output 22-23/csvs/tudelft_courses_22-23_sdg.csv
```

Reads the CSV from Step 1, calls OpenAI to rate each course, and saves the result. It needs your OpenAI API key saved in `openai_api_key.txt` (already in this folder).

If interrupted, run the same command again — it will pick up where it left off.

The default model is `gpt-4o-mini`. To use a different model, add `--model`:

```bash
python sdg_rating.py --input 22-23/csvs/tudelft_courses_22-23_from_pdfs.csv --output 22-23/csvs/tudelft_courses_22-23_sdg.csv --model gpt-4o
```

Common options: `gpt-4o-mini` (cheaper), `gpt-4o` (more accurate), `gpt-4-turbo`.

---

## Step 3: Compare with manual ratings

If you have manually rated CSVs, you can compare them against the ChatGPT ratings.

Each course in the output is colour-coded:
- **GREEN** — ChatGPT and manual agree
- **ORANGE** — both rated the course, but different SDGs
- **RED** — only ChatGPT rated it
- **BROWN** — only the manual rating has it

### 25-26

Manual rating files go in `25-26/Manual_ratings/` — one CSV per faculty (e.g. `ABE.csv`, `CEG.csv`).

```bash
cd 25-26
python compile_comparison.py
```

Output: `25-26/csvs/25-26_comparison.csv`

### 22-23

Uses a single merged manual CSV (`DB-22-23.csv`) already in `22-23/csvs/`.

```bash
cd 22-23
python compile_comparison.py
```

Output: `22-23/csvs/comparison_22-23.csv`
