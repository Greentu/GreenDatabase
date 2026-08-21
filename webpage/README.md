# GreenTU Webpage - Script & Style Guide

> New to this project? [HANDOVER.md](HANDOVER.md) walks through how the page is deployed via Typo3 and how everything fits together. This file is the technical reference for `script.js` and `style.css` specifically.

This folder contains the two files that power the interactive GreenDatabase on the TU Delft GreenTU webpage:

- **`script.js`** — handles all the logic: loading data from Google Sheets, rendering course cards, filtering, sorting, searching, and the analytics panel.
- **`style.css`** — controls the visual appearance of everything: card layout, SDG colour blocks, the analytics panel, and responsive behaviour.

Both files are embedded directly in the TU Delft CMS (the website editor). You do **not** need to run a server or install anything to work with them — just edit the files and paste the contents into the CMS.

---

## How it works (overview)

1. When the page loads, the script connects to a **Google Sheet** (the GreenDatabase) using a public API key.
2. It reads all worksheets whose names start with `DB ` (e.g. `DB Courses`, `DB Projects`). Each worksheet is one "category" shown on the home screen.
3. Clicking a category card loads that sheet's rows and displays them as course/project cards with filters, sorting, and a search box.
4. A floating **SDG Analytics panel** (bottom-right corner) shows live statistics — how many courses are linked to sustainability goals, broken down by faculty and programme.

---

## Key setting to know

At the very top of `script.js`:

```js
const spreadsheetId = '1yX6eZHzLWRCrbaOOvgJ2-ay5sBzYVEM0LxvuqVR34-8';
```

This is the ID of the Google Sheet that feeds the database. If you ever move the data to a new spreadsheet, change this value to the new sheet's ID (the long string in its URL).

---

## How the Google Sheet must be structured

See [HANDOVER.md's "Updating the published SDG ratings"](HANDOVER.md#updating-the-published-sdg-ratings) — the exact sheet layout and field types the script expects are documented there, alongside the rest of the update workflow.

---

## Common tweaks

### Change which SDG numbers are shown as coloured blocks

SDG colours and icons are defined in `style.css`. Each SDG has its own block like:

```css
.sdg-block.sdg-3 {
    background-color: #4ca146;
}
.sdg-block.sdg-3:after {
    background-image: url("https://sdgs.un.org/sites/default/files/goals/E_SDG_Icons-03.jpg");
}
```

There are blocks for SDGs 1–17. If the UN ever changes the icon URLs, update them here.

### Change the analytics panel position

In `style.css`, find `#greendatabase-analytics` and `#greendatabase-analytics-toggle`. The relevant properties:

```css
#greendatabase-analytics {
    bottom: 70px;   /* distance from the bottom of the page */
    right: 24px;    /* distance from the right edge */
    width: 280px;   /* panel width */
}
```

Adjust `bottom`, `right`, and `width` to move or resize the panel.

### Change the analytics panel colour (the green header bar)

Search `style.css` for `background: #4ca146` inside `#greendatabase-analytics`. Replace `#4ca146` with any colour you like.

The same green is used for the SDG toggle button (`#greendatabase-analytics-toggle`) and the percentage text (`.analytics-pct`). Change all three to keep them consistent.

<!-- 
### Change how many cards appear per row

By default:
- **Mobile** (< 1024 px): 1 card per row
- **Desktop** (1024–1280 px): 2 cards per row
- **Wide screen** (> 1280 px): 3 cards per row

These breakpoints are in `style.css` under `.greendatabase-items-container > .card-wrapper`:

```css
@media (min-width: 64em) {   /* ~1024px → 2 columns */
    width: 50%;
}
@media (min-width: 80em) {   /* ~1280px → 3 columns */
    width: 33%;
}
``` -->

To get 2 columns at all desktop sizes, remove the `80em` block (or change `33%` to `50%`).

### Change the home screen title ("Welcome!")

In `script.js`, search for:

```js
getLocalizedValue("Welcome!///Welkom!", true)
```

Edit the English text before `///` and the Dutch text after it.

### Change the "Back to start" button label

Search `script.js` for:

```js
"Back to start///Terug naar begin"
```

Same bilingual format — English first, Dutch after `///`.

### Add or rename a faculty in the English↔Dutch translation

Near the bottom of `script.js` there is an `englishDutchMap` object. It maps English faculty names to their Dutch equivalents, and is used to display the correct language depending on the page language. Add a new line if a faculty is missing:

```js
"Faculty Name in English": "Faculteitsnaam in het Nederlands",
```

---

## Bilingual content format

Anywhere in the Google Sheet where a field should appear in both languages, use the separator `///`:

```
English text///Nederlandse tekst
```

The script detects the page language automatically (`en` vs `nl-NL`) and shows the correct half. If no `///` is present, the value is shown as-is in both languages.

---

## The SDG Analytics panel (what it shows)

- **Home screen**: for each visible category (e.g. "2022–23 courses"), shows how many courses have at least one SDG link, out of the total, plus the top 3 most-common SDGs.
- **Inside a category**: shows the same breakdown filtered to what is currently visible on screen — so if you filter by faculty or search for a keyword, the numbers update live.
- The panel can be minimised with the ✕ button and reopened with the green "SDG" button in the bottom-right corner.

---

## Files at a glance

| File | What to change here |
|------|---------------------|
| `script.js` | Spreadsheet ID, text labels, translation map, analytics logic |
| `style.css` | Layout, colours, panel position, card dimensions, SDG icon styles |
