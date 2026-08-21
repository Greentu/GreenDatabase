/**
 * script.js — GreenDatabase interactive frontend
 *
 * Fetches course/project data from a Google Sheet via the Sheets API (gapi),
 * renders category cards and item cards, and handles search, filtering,
 * sorting, and the live SDG Analytics panel.
 *
 * Entry point: the gapi.load() call at the bottom of this file.
 * Key setting: `spreadsheetId` — update this if the backing spreadsheet changes.
 *
 * Worksheet naming convention: tabs must be named "DB <Category>" to be picked up.
 * Bilingual strings in the sheet use the format "English///Dutch".
 */
"use strict";

/* Settings */
const spreadsheetId = '1yX6eZHzLWRCrbaOOvgJ2-ay5sBzYVEM0LxvuqVR34-8';

/* Global variables */
const language = document.documentElement.getAttribute("lang");
// Elements
const databaseIntroContainer = document.getElementById("greendatabase-intro-container");
const databaseCategoriesContainer = document.getElementById("greendatabase-categories-container");
const databaseEntriesContainer = document.getElementById("greendatabase-entries-container");
const headerElement = document.getElementById("greendatabase-header");
const statusElement = document.getElementById("greendatabase-status");
const searchElement = document.getElementById("greendatabase-search");
const filtersWrapper = document.getElementById("greendatabase-filters-wrapper");
const sortElement = document.getElementById("greendatabase-sort");
const homeButton = document.getElementById("greendatabase-home-button");
const filtersButton = document.getElementById("greendatabase-filters-button");
const sidebar = document.getElementById("greendatabase-sidebar");
const introText = document.getElementById("greendatabase-intro-text");

// Database data
class CategoryData {
    constructor(init) {
        this.order = -1;
        this.metadata = {};
        this.items = [];
        this.filters = {}; // { [key: string]: string }[]
        this.isStored = false;
        Object.assign(this, init);
    }
}
;
let databaseData = {};
let currentSheetName = "";

/* FUNCTIONS */
/* Data loading */

/**
 * Fetch all worksheet tabs from the Google Sheet and register the ones
 * whose name starts with "DB " as database categories.
 * Populates the global `databaseData` object with one entry per category,
 * each holding the category's metadata (title, colour, field definitions).
 */
const loadAllCategories = async function () {
    try {
        const worksheetsResult = (await gapi.client.sheets.spreadsheets.get({
            spreadsheetId: spreadsheetId
        })).result.sheets;
        const dbWorksheets = worksheetsResult === null || worksheetsResult === void 0 ? void 0 : worksheetsResult.filter((worksheet) => { var _a, _b; return (_b = (_a = worksheet.properties) === null || _a === void 0 ? void 0 : _a.title) === null || _b === void 0 ? void 0 : _b.startsWith("DB "); });
        if (!dbWorksheets) {
            console.warn("No database worksheets found!");
            return;
        }
        await Promise.all(dbWorksheets.map(async (worksheet) => {
            var _a;
            const title = (_a = worksheet.properties) === null || _a === void 0 ? void 0 : _a.title;
            if (title) {
                databaseData[title] = new CategoryData({ order: dbWorksheets.indexOf(worksheet), metadata: await loadCategoryMetadata(title) });
            }
        }));
    }
    catch (err) {
        console.warn(err);
        return;
    }
};
/**
 * Read the metadata rows (B2:B5 and B7:11) from a single "DB " worksheet
 * and return a structured object with the category title, description,
 * colour, visibility flag, and per-column field definitions.
 * Field definitions control which columns are shown, filtered, and sorted.
 * @param {string} sheetName - The full worksheet tab name (e.g. "DB Courses")
 */
const loadCategoryMetadata = async function (sheetName) {
    try {
        const metadataResult = await gapi.client.sheets.spreadsheets.values.batchGet({
            spreadsheetId: spreadsheetId,
            ranges: [sheetName + '!B2:B5', sheetName + '!B7:11'],
            majorDimension: "COLUMNS"
        });
        if (metadataResult.result.valueRanges && metadataResult.result.valueRanges[0].values && metadataResult.result.valueRanges[1].values) {
            // Sheet title and color
            const categoryTitle = getLocalizedValue(metadataResult.result.valueRanges[0].values[0][0].toString(), true);
            const categoryDescription = getLocalizedValue(metadataResult.result.valueRanges[0].values[0][1].toString(), false);
            const categoryColor = metadataResult.result.valueRanges[0].values[0][2].toString();
            const categoryVisible = yesNoToBoolean(metadataResult.result.valueRanges[0].values[0][3].toString());
            // Table metadata
            let fieldMetadata = [];
            metadataResult.result.valueRanges[1].values.forEach((item) => {
                fieldMetadata.push({
                    id: makeId(item[0]),
                    title: getLocalizedValue(item[0], true),
                    show: (item[1] === "TRUE"),
                    fieldType: item[2],
                    filterable: (item[3] === "TRUE"),
                    sortable: (item[4] === "TRUE")
                });
            });
            return {
                categoryTitle,
                categoryDescription,
                categoryColor,
                categoryVisible,
                fieldMetadata
            };
        }
    }
    catch (err) {
        console.warn(err);
        return;
    }
};

/**
 * Render one clickable card on the home screen for each *visible* category
 * in `databaseData`, sorted by their worksheet order.
 * Clicking a card calls `loadCategory` with that worksheet's title.
 */
const renderCategoryCards = async function () {
    let itemsHtml = "";
    let orderedData = Object.entries(databaseData).sort((a, b) => {
        const x = a[1]["order"];
        const y = b[1]["order"];
        return ((x < y) ? -1 : ((x > y) ? 1 : 0));
    });
    for (const [worksheetTitle, categoryData] of orderedData) {
        if (categoryData.metadata.categoryVisible) {
            // The worksheet title is passed via the cardAttributes argument and read on click.
            itemsHtml += getCardHtml(true, "&nbsp;", categoryData.metadata.categoryTitle, categoryData.metadata.categoryColor, "#", null, { "database-worksheet-title": worksheetTitle });
        }
    }
    if (databaseCategoriesContainer) {
        databaseCategoriesContainer.innerHTML = itemsHtml;
    }
};

/**
 * Fetch all data rows (starting at row 12) from a worksheet and convert them
 * into structured item objects ready for rendering.
 * Also counts all rows (visible and hidden) per faculty/programme for the
 * analytics panel denominator.
 * @param {string} sheetName - Worksheet tab name
 * @param {Array}  fieldMetadata - Column definitions from loadCategoryMetadata
 * @returns {{ items: Array, totalPerFaculty: Object }}
 */
const loadCategoryItems = async function (sheetName, fieldMetadata) {
    try {
        const itemsResult = await gapi.client.sheets.spreadsheets.values.batchGet({
            spreadsheetId: spreadsheetId,
            ranges: [sheetName + '!A12:' + numberToColName(fieldMetadata.length)],
            majorDimension: "ROWS"
        });
        if (itemsResult.result.valueRanges && itemsResult.result.valueRanges[0].values) {
            const titleIndex = fieldMetadata.findIndex((field) => field.show && field.fieldType === "title");
            const subtitleIndex = fieldMetadata.findIndex((field) => field.show && field.fieldType === "subtitle");
            const linkIndex = fieldMetadata.findIndex((field) => field.show && field.fieldType === "link");
            const sdgsIndex = fieldMetadata.findIndex((field) => field.show && field.fieldType === "sdgs");
            const facultyIndex = fieldMetadata.findIndex((field) => field.id === "faculty");
            const programIndex = fieldMetadata.findIndex((field) => field.id === "program");
            const fieldIndices = fieldMetadata.reduce((accumulator, field, i) => (field.show && ['text', 'boolean', 'description'].includes(field.fieldType)) ? accumulator.concat(i) : accumulator, []);
            const totalPerFaculty = {}; // { [faculty]: { total, programs: { [program]: total } } }
            const items = itemsResult.result.valueRanges[0].values.reduce((accumulator, item, i) => {
                const visible = item[0] === "TRUE";
                // Count totals for all rows (visible or not) per faculty and program
                const rawFaculty = facultyIndex > -1 ? (item[facultyIndex + 1] || "") : "";
                const faculty = rawFaculty ? getLocalizedValue(rawFaculty, false) : "";
                if (faculty) {
                    if (!totalPerFaculty[faculty]) totalPerFaculty[faculty] = { total: 0, programs: {} };
                    totalPerFaculty[faculty].total++;
                    if (programIndex > -1) {
                        const rawProgram = item[programIndex + 1] || "";
                        parseProgramList(rawProgram).forEach((p) => {
                            totalPerFaculty[faculty].programs[p] = (totalPerFaculty[faculty].programs[p] || 0) + 1;
                        });
                    }
                }
                item = item.slice(1); // shift manually so indices stay aligned
                // Check first cell: show or hide item
                if (visible) {
                    // Fields to display
                    let theFields = fieldIndices.reduce((accumulator, fieldIndex) => item[fieldIndex] ? accumulator.concat({ "label": getLocalizedValue(fieldMetadata[fieldIndex].title, true), "value": getLocalizedValue(item[fieldIndex], true), "type": fieldMetadata[fieldIndex].fieldType }) : accumulator, []);
                    // Fields for filtering
                    let filterFields = fieldMetadata.reduce((accumulator, field, j) => {
                        if (field.filterable && field.fieldType !== "sdgs") {
                            accumulator[field.id] = getLocalizedValue(item[j], true);
                        }
                        return accumulator;
                    }, {});
                    // Fields for sorting
                    let sortFields = fieldMetadata.reduce((accumulator, field, k) => {
                        if (field.show && field.sortable) {
                            accumulator[field.id] = getLocalizedValue(item[k], true);
                        }
                        return accumulator;
                    }, { "default": i.toString() }); // Include index as default order number
                    // Create item
                    accumulator.push({
                        title: titleIndex > -1 ? getLocalizedValue(item[titleIndex], true) : null,
                        subtitle: subtitleIndex > -1 ? getLocalizedValue(item[subtitleIndex], true) : null,
                        link: linkIndex > -1 && item[linkIndex],
                        fields: theFields,
                        filterFields: filterFields,
                        sortFields: sortFields,
                        sdgs: (sdgsIndex > -1 && item[sdgsIndex]) ? JSON.parse(item[sdgsIndex]) : []
                    });
                }
                return accumulator;
            }, []);
            return { items, totalPerFaculty };
        }
    }
    catch (err) {
        console.warn(err);
        return;
    }
};

/**
 * Background-load items and filters for every category so the home screen
 * analytics panel can show totals without waiting for the user to click
 * into each category first.
 * Skips categories that have already been loaded (isStored === true).
 */
const preloadAllCategoryItems = async function () {
    await Promise.all(Object.keys(databaseData).map(async (sheetName) => {
        const categoryData = databaseData[sheetName];
        if (!categoryData.metadata.fieldMetadata || categoryData.isStored) return;
        const categoryResult = await loadCategoryItems(sheetName, categoryData.metadata.fieldMetadata);
        if (!categoryResult) return;
        categoryData.items = categoryResult.items;
        categoryData.totalPerFaculty = categoryResult.totalPerFaculty;
        const filterFieldMetadata = categoryData.metadata.fieldMetadata.filter((field) => field.filterable);
        const categoryFilters = {};
        filterFieldMetadata.forEach((filterField) => {
            const filterId = filterField.id;
            const filterType = filterField.fieldType;
            let filterValues;
            if (filterType === "sdgs") {
                filterValues = [...new Set(categoryData.items.map((item) => item.sdgs).flat())];
            } else {
                filterValues = [...new Set(categoryData.items.map((item) => item.filterFields[filterId]))];
            }
            categoryFilters[filterId] = { id: filterId, title: filterField.title, values: filterValues, type: filterType };
        });
        categoryData.filters = categoryFilters;
        categoryData.isStored = true;
        databaseData[sheetName] = categoryData;
    }));
};

/**
 * Load (or retrieve from cache) all items for the given worksheet, then
 * render the category heading and all course/project cards into the page.
 * Also builds the filter value lists used by initializeFilters.
 * @param {string} sheetName - Worksheet tab name (e.g. "DB Courses")
 */
const loadAndRenderCategory = async function (sheetName) {
    currentSheetName = sheetName;
    let categoryData;
    if (databaseData[sheetName].isStored) {
        // Retrieve stored data
        categoryData = databaseData[sheetName];
    }
    else {
        // Define new data and load from Google Sheets
        categoryData = databaseData[sheetName];
        if (!categoryData.metadata.fieldMetadata) {
            console.warn("Missing field metadata");
            return;
        }
        // Load items
        const categoryResult = await loadCategoryItems(sheetName, categoryData.metadata.fieldMetadata);
        if (!categoryResult) {
            return;
        }
        categoryData.items = categoryResult.items;
        categoryData.totalPerFaculty = categoryResult.totalPerFaculty;
        // Load filters
        const filterFieldMetadata = categoryData.metadata.fieldMetadata.filter((field) => field.filterable);
        const categoryFilters = {};
        filterFieldMetadata.forEach((filterField) => {
            const filterId = filterField.id;
            const filterTitle = filterField.title;
            const filterType = filterField.fieldType;
            let filterValues;
            if (filterType === "sdgs") {
                filterValues = [...new Set(categoryData.items.map((item) => item.sdgs).flat())];
            }
            else {
                filterValues = [...new Set(categoryData.items.map((item) => item.filterFields[filterId]))];
            }
            categoryFilters[filterId] = {
                id: filterId,
                title: filterTitle,
                values: filterValues,
                type: filterType
            };
        });
        categoryData.filters = categoryFilters;
        categoryData.isStored = true;
        databaseData[sheetName] = categoryData;
    }
    // Render title
    if (headerElement && categoryData.metadata.categoryTitle) {
        headerElement.innerHTML = getHeadingHtml(categoryData.metadata.categoryTitle, categoryData.metadata.categoryColor, categoryData.metadata.categoryDescription || "");
    }
    // Render items
    let itemsHtml = "";
    categoryData.items.forEach((item) => {
        itemsHtml += getCardHtml(false, item.subtitle, item.title, categoryData.metadata.categoryColor, item.link, item.fields, { ...item.filterFields, ...item.sortFields }, item.sdgs);
    });
    if (databaseEntriesContainer) {
        databaseEntriesContainer.innerHTML = itemsHtml;
    }
};

/**
 * Main setup function, called once the Google API client is ready.
 * Loads all category metadata, renders the home screen, wires up the
 * home/filters buttons and deep-link URL handling, creates the analytics
 * panel, and kicks off background pre-loading of all category data.
 */
const initializeDatabase = async function () {
    setStatus("Initialising database");
    await loadAllCategories();
    setStatus("Loaded categories");
    await renderCategoryCards();
    setStatus("Rendered category cards");

    // NEW: Add a single event listener to the categories container for handling clicks on category cards.
    if (databaseCategoriesContainer) {
        databaseCategoriesContainer.addEventListener('click', (event) => {
            const cardWrapper = event.target.closest('.card-wrapper');
            if (!cardWrapper) {
                return; // Click was not inside a card wrapper
            }

            const worksheetTitle = cardWrapper.dataset.databaseWorksheetTitle;
            if (worksheetTitle) {
                event.preventDefault(); // Prevent the link's default # behavior
                loadCategory(worksheetTitle);
            }
        });
    }

    if (databaseIntroContainer) {
        databaseIntroContainer.style.display = "none";
    }
    // Create analytics panel early so home screen can use it
    if (!document.getElementById("greendatabase-analytics")) {
        const analyticsEl = document.createElement("div");
        analyticsEl.id = "greendatabase-analytics";
        analyticsEl.innerHTML = `<div class="analytics-header"><span class="analytics-title">SDG Analytics</span><button class="analytics-close" title="Close">✕</button></div><div class="analytics-body"></div>`;
        document.body.appendChild(analyticsEl);
        analyticsEl.querySelector(".analytics-close").addEventListener("click", () => {
            analyticsEl.classList.add("collapsed");
            const btn = document.getElementById("greendatabase-analytics-toggle");
            if (btn) btn.style.display = "block";
        });
        const toggleBtn = document.createElement("button");
        toggleBtn.id = "greendatabase-analytics-toggle";
        toggleBtn.title = "Show SDG Analytics";
        toggleBtn.textContent = "SDG";
        toggleBtn.style.display = "none";
        toggleBtn.addEventListener("click", () => {
            analyticsEl.classList.remove("collapsed");
            toggleBtn.style.display = "none";
        });
        document.body.appendChild(toggleBtn);
    }
    loadStartScreen();
    setStatus("Loaded start screen");
    // Initialize home button
    if (homeButton) {
        homeButton.innerText = getLocalizedValue("Back to start///Terug naar begin", true);
        homeButton.addEventListener("click", () => {
            if ('URLSearchParams' in window) {
                const searchParams = new URLSearchParams(window.location.search);
                searchParams.delete("category");
                const newRelativePathQuery = window.location.pathname + '?' + searchParams.toString();
                history.pushState(null, '', newRelativePathQuery);
            }
            loadStartScreen();
        });
    }
    // Initialize filters button
    if (filtersButton) {
        filtersButton.innerText = getLocalizedValue("Filters///Filters", true);
        filtersButton.addEventListener("click", toggleMobileFiltersVisibility);
    }
    if ('URLSearchParams' in window) {
        const searchParams = new URLSearchParams(window.location.search);
        const category = searchParams.has("category") && searchParams.get("category");
        if (category && Object.keys(databaseData).includes(category)) {
            loadCategory(category);
        }
    }
    // Pre-load all category data in background for home screen analytics
    preloadAllCategoryItems().then(() => {
        setStatus("All categories pre-loaded.");
        if (!currentSheetName) {
            updateHomeAnalytics();
        }
    });
};

/** Toggle the sidebar filter panel open/closed on mobile screens. */
const toggleMobileFiltersVisibility = function () {
    filtersButton === null || filtersButton === void 0 ? void 0 : filtersButton.classList.toggle("mobile-filters-visible");
};

/**
 * Show the home screen: hide the entries list, reveal the intro text and
 * category cards, set the "Welcome!" heading, and refresh the home analytics.
 * Called on initial load and when the user clicks "Back to start".
 */
const loadStartScreen = function () {
    setStatus("Loading start screen");
    // Hide entries
    if (databaseEntriesContainer) {
        databaseEntriesContainer.style.display = "none";
    }
    if (introText) {
        introText.classList.remove("hidden");
    }
    // Render title
    if (headerElement) {
        headerElement.innerHTML = getHeadingHtml(getLocalizedValue("Welcome!///Welkom!", true), "green", "");
    }
    // Show categories
    if (databaseCategoriesContainer) {
        databaseCategoriesContainer.style.removeProperty("display");
    }
    // Show year-wise analytics on home screen
    updateHomeAnalytics();
    setStatus("Loaded start screen");
};

/**
 * Switch from the home screen to a specific category view.
 * Updates the URL query string (?category=...) for deep-linking,
 * hides the category cards, renders the chosen worksheet's items,
 * initialises filters and sorting, and shows the analytics panel.
 * @param {string} worksheetTitle - Full worksheet tab name (e.g. "DB Courses")
 */
const loadCategory = async function (worksheetTitle) {
    if ('URLSearchParams' in window) {
        const searchParams = new URLSearchParams(window.location.search);
        searchParams.set("category", worksheetTitle);
        const newRelativePathQuery = window.location.pathname + '?' + searchParams.toString();
        history.pushState(null, '', newRelativePathQuery);
    }
    setStatus("Loading category " + worksheetTitle);
    // Hide categories
    if (databaseCategoriesContainer) {
        databaseCategoriesContainer.style.display = "none";
    }
    await loadAndRenderCategory(worksheetTitle);
    setStatus("Worksheet rendered.");
    setStatus("Initializing filters and sorting...");
    initializeFilters();
    setStatus("Filters initialized.");
    initializeSorting();
    setStatus("Sorting initialized.");
    setStatus("Done!");
    if (databaseEntriesContainer) {
        databaseEntriesContainer.style.removeProperty("display");
    }
    if (introText) {
        introText.classList.add("hidden");
    }
    // Show analytics panel for this category
    const analyticsEl = document.getElementById("greendatabase-analytics");
    if (analyticsEl) analyticsEl.classList.remove("collapsed");
    const toggleBtn = document.getElementById("greendatabase-analytics-toggle");
    if (toggleBtn) toggleBtn.style.display = "none";
    updateAnalytics();
    setStatus("Loaded category " + worksheetTitle);
};

/**
 * Initialise the Google API client with the Sheets discovery doc and API key,
 * then hand off to `initializeDatabase`.
 * Called by gapi.load() at the bottom of this file.
 */
const loadApi = async function () {
    setStatus("Initialising API");
    // 2. Initialize the JavaScript client library.
    await gapi.client.init({
        'apiKey': 'AIzaSyAjHCg8HQuznNDt6GrH4ovZ7wPDX1NDGqA',
        discoveryDocs: ["https://sheets.googleapis.com/$discovery/rest?version=v4"],
    }).then(initializeDatabase);
};

/**
 * Build and inject the filter sidebar for the currently loaded category.
 * Renders checkboxes for each filterable field: SDG coloured blocks for the
 * SDGs filter, a hierarchical faculty → programme tree for the faculty filter,
 * and plain checkboxes for all other fields.
 * Also attaches the search box listener (once only, on first call).
 */
const initializeFilters = function () {
    // Render filter checkboxes
    if (filtersWrapper && currentSheetName && databaseData.hasOwnProperty(currentSheetName)) {
        const filters = databaseData[currentSheetName].filters;

        // Build faculty -> programs map from rendered cards
        const facultyProgramMap = {};
        for (let card of getCurrentCards()) {
            const faculty = card.getAttribute("data-faculty");
            const programs = parseProgramList(card.getAttribute("data-program"));
            if (faculty && programs.length > 0) {
                if (!facultyProgramMap[faculty]) facultyProgramMap[faculty] = new Set();
                programs.forEach((p) => facultyProgramMap[faculty].add(p));
            }
        }

        let filtersHtml = "";
        if (Object.keys(filters).length > 0) {
            Object.values(filters).forEach((filter) => {
                if (filter.id === "program") return; // embedded under faculty
                if (filter.values.length > 0) {
                    filtersHtml += `<h4>${filter.title}</h4><div class="greendatabase-filter-group" data-filter-id="${filter.id}" style="margin-top: -10px; margin-bottom: 10px">`;
                    if (filter.type === "sdgs") {
                        const sortedValues = filter.values.sort((a, b) => Number(a) - Number(b));
                        sortedValues.forEach((value) => {
                            if (value) {
                                filtersHtml += `<div class="sdg-checkbox-wrapper"><label class="sdg-checkbox-label"><input type="checkbox" class="sdg-checkbox" value="${value}" name="${filter.id}-${makeId(value)}" /> <div href="https://sdgs.un.org/goals/goal${value}" target="_blank" class="sdg-block sdg-${value}">${value}</div></label></div>`;
                            }
                        });
                    }
                    else if (filter.id === "faculty") {
                        filter.values.forEach((value) => {
                            if (!value) return;
                            const programs = facultyProgramMap[value]
                                ? Array.from(facultyProgramMap[value]).sort()
                                : [];
                            filtersHtml += `<div class="faculty-filter-item">`;
                            filtersHtml += `<div><label><input type="checkbox" class="faculty-parent-checkbox" value="${value}" name="faculty-${makeId(value)}" /> ${value}</label></div>`;
                            if (programs.length > 1) {
                                filtersHtml += `<div class="program-subfilter-group">`;
                                programs.forEach((program) => {
                                    filtersHtml += `<div><label><input type="checkbox" class="program-child-checkbox" value="${program}" name="program-${makeId(program)}" data-parent-faculty="${value}" /> ${program}</label></div>`;
                                });
                                filtersHtml += `</div>`;
                            }
                            filtersHtml += `</div>`;
                        });
                    }
                    else {
                        filter.values.forEach((value) => {
                            if (value) {
                                filtersHtml += `<div><label><input type="checkbox" value="${value}" name="${filter.id}-${makeId(value)}" /> ${value}</label></div>`;
                            }
                        });
                    }
                    filtersHtml += "</div>";
                }
            });
        }
        if (filtersHtml) {
            filtersWrapper.innerHTML = filtersHtml;
        }
        else {
            filtersWrapper.innerText = "-";
        }
    }
    // Initialize filter checkboxes
    const filterCheckboxes = filtersWrapper === null || filtersWrapper === void 0 ? void 0 : filtersWrapper.querySelectorAll('.greendatabase-filter-group input[type="checkbox"]');
    if (filterCheckboxes) {
        filterCheckboxes.forEach((checkbox) => {
            checkbox.addEventListener("input", (Event) => filterFromCheckbox(Event.target));
        });
    }
    // Initialize search box
    if (searchElement && !hasSortingBeenInitializedOnce) {
        searchElement.addEventListener("input", () => searchItems(searchElement.value));
    }
};

/** Return the live HTMLCollection of all card-wrapper elements in the entries container. */
const getCurrentCards = function () {
    return databaseEntriesContainer === null || databaseEntriesContainer === void 0 ? void 0 : databaseEntriesContainer.getElementsByClassName("card-wrapper");
};

/**
 * Handle a checkbox change inside the hierarchical faculty/programme filter.
 * Checking a faculty expands its programme sub-list. The visibility of each
 * card is then recomputed: a card passes if its faculty is checked AND either
 * no programmes are selected within that faculty or one of its programmes is.
 * @param {Element} filterGroup           - The .greendatabase-filter-group container
 * @param {HTMLInputElement} targetCheckboxElement - The checkbox that was just toggled
 */
const handleFacultyFilterChange = function (filterGroup, targetCheckboxElement) {
    // Expand/collapse program sub-group when faculty parent is clicked (no auto-cascade)
    if (targetCheckboxElement.classList.contains("faculty-parent-checkbox")) {
        const item = targetCheckboxElement.closest(".faculty-filter-item");
        if (item) {
            item.classList.toggle("is-expanded", targetCheckboxElement.checked);
        }
    }
    // Recompute filter for all cards
    const cards = getCurrentCards();
    if (!cards) return;
    const facultyParentCheckboxes = Array.from(filterGroup.querySelectorAll(".faculty-parent-checkbox"));
    const programChildCheckboxes = Array.from(filterGroup.querySelectorAll(".program-child-checkbox"));
    const anyFacultyChecked = facultyParentCheckboxes.some((cb) => cb.checked);
    for (let card of cards) {
        card.removeAttribute("data-filtered-program");
        if (!anyFacultyChecked) {
            card.removeAttribute("data-filtered-faculty");
            continue;
        }
        const cardFaculty = card.getAttribute("data-faculty");
        const cardPrograms = parseProgramList(card.getAttribute("data-program"));
        const matchingFacultyCb = facultyParentCheckboxes.find((cb) => cb.value === cardFaculty);
        if (!matchingFacultyCb || !matchingFacultyCb.checked) {
            card.setAttribute("data-filtered-faculty", "filtered");
        } else {
            // Faculty matches — check if any programs are selected within this faculty
            const checkedProgramsForFaculty = programChildCheckboxes
                .filter((cb) => cb.dataset.parentFaculty === cardFaculty && cb.checked)
                .map((cb) => cb.value);
            if (checkedProgramsForFaculty.length === 0 || checkedProgramsForFaculty.some((p) => cardPrograms.includes(p))) {
                card.removeAttribute("data-filtered-faculty");
            } else {
                card.setAttribute("data-filtered-faculty", "filtered");
            }
        }
    }
    updateFilteredCards();
};

/**
 * Called whenever any filter checkbox changes.
 * Delegates to `handleFacultyFilterChange` for the faculty group (which needs
 * hierarchical logic), and applies simple set-membership filtering for all
 * other groups (SDGs, level, etc.).
 * Marks non-matching cards with a data-filtered-<fieldId> attribute, then
 * calls `updateFilteredCards` to apply the CSS hide class.
 * @param {HTMLInputElement} targetCheckboxElement - The checkbox that changed
 */
const filterFromCheckbox = function (targetCheckboxElement) {
    if (targetCheckboxElement && targetCheckboxElement instanceof Element) {
        const filterGroup = targetCheckboxElement.closest(".greendatabase-filter-group");
        const cards = getCurrentCards();
        const isSdgFilter = targetCheckboxElement.classList.contains("sdg-checkbox");
        if (filterGroup && cards) {
            // Branch: faculty group uses hierarchical logic
            if (filterGroup.getAttribute("data-filter-id") === "faculty") {
                handleFacultyFilterChange(filterGroup, targetCheckboxElement);
                return;
            }
            const filterId = filterGroup === null || filterGroup === void 0 ? void 0 : filterGroup.getAttribute("data-filter-id");
            const selectedValues = Array.from(filterGroup === null || filterGroup === void 0 ? void 0 : filterGroup.querySelectorAll('input[type="checkbox"]:checked')).map((checkboxElement) => checkboxElement.getAttribute("value"));
            if (selectedValues.length > 0) {
                // Filter selected values
                for (let card of cards) {
                    let isSelected;
                    if (isSdgFilter) {
                        isSelected = selectedValues.some((x) => { var _a; return x && ((_a = card.getAttribute(`data-${filterId}`)) === null || _a === void 0 ? void 0 : _a.split(",").includes(x)); });
                    }
                    else {
                        isSelected = selectedValues.includes(card.getAttribute(`data-${filterId}`));
                    }
                    if (isSelected) {
                        card.removeAttribute(`data-filtered-${filterId}`);
                    }
                    else {
                        card.setAttribute(`data-filtered-${filterId}`, "filtered");
                    }
                }
            }
            else {
                // No values selected --> show all (at least, regarding this filter)
                for (let card of cards) {
                    card.removeAttribute(`data-filtered-${filterId}`);
                }
            }
            updateFilteredCards();
        }
    }
};

/**
 * Filter visible cards by a search string.
 * Each card stores a pre-built lowercase searchstring data attribute (title +
 * subtitle + all field values). Cards that don't contain `val` are hidden.
 * @param {string} val - The current search box value
 */
const searchItems = function (val) {
    var _a;
    if (!val) {
        clearSearch();
        return;
    }
    const cards = getCurrentCards();
    if (cards) {
        for (let card of cards) {
            if ((_a = card.getAttribute("data-searchstring")) === null || _a === void 0 ? void 0 : _a.includes(val.toLowerCase())) {
                card.removeAttribute("data-filtered-searchstring");
            }
            else {
                card.setAttribute("data-filtered-searchstring", "filtered");
            }
        }
    }
    updateFilteredCards();
};

/** Remove the search filter from all cards and refresh visibility. */
const clearSearch = function () {
    const cards = getCurrentCards();
    if (cards) {
        for (let card of cards) {
            card.removeAttribute("data-filtered-searchstring");
        }
    }
    updateFilteredCards();
};

/**
 * Recompute which cards should be visible based on all active filters.
 * A card is hidden (gets the CSS class "filtered") if it has ANY
 * data-filtered-* attribute set. Afterwards, refreshes the analytics panel.
 */
const updateFilteredCards = function () {
    const cards = getCurrentCards();
    if (cards) {
        for (let card of cards) {
            if (Array.from(card.attributes).filter((attributeNode) => attributeNode.nodeName.indexOf("data-filtered") === 0).length > 0) {
                card.classList.add("filtered");
            }
            else {
                card.classList.remove("filtered");
            }
        }
    }
    updateAnalytics();
};

/**
 * Given an array of card DOM elements, count how often each SDG number appears
 * across their data-sdgs attributes and return HTML for the top-3 SDG blocks.
 * Used by the analytics panel when a category is open.
 * @param {Element[]} cards - Array of .card-wrapper elements
 * @returns {string} HTML string (empty string if no SDGs found)
 */
const getTopSdgsHtml = function (cards) {
    const sdgCounts = {};
    cards.forEach((card) => {
        const sdgs = card.getAttribute("data-sdgs");
        if (sdgs) sdgs.split(",").forEach((s) => { if (s) sdgCounts[s] = (sdgCounts[s] || 0) + 1; });
    });
    const top3 = Object.entries(sdgCounts).sort((a, b) => b[1] - a[1]).slice(0, 3);
    if (top3.length === 0) return "";
    let html = `<div class="analytics-top3"><span class="analytics-top3-label">Top 3 SDGs:</span>`;
    top3.forEach(([sdg]) => {
        html += `<a href="https://sdgs.un.org/goals/goal${sdg}" target="_blank" class="sdg-block sdg-${sdg}">${sdg}</a>`;
    });
    html += `</div>`;
    return html;
};

/**
 * Build one analytics row: "X / Y courses (Z%)" with an optional left-indent
 * style used for programme-level rows nested under a faculty row.
 * @param {number}  sdgCount - Number of courses with at least one SDG (numerator)
 * @param {number}  total    - Total courses in this group (denominator)
 * @param {string}  label    - Row label (faculty or programme name)
 * @param {boolean} indent   - Whether to render as an indented sub-row
 * @returns {string} HTML string
 */
const getStatRowHtml = function (sdgCount, total, label, indent) {
    const pct = total > 0 ? Math.round((sdgCount / total) * 100) : 0;
    return `<div class="analytics-row${indent ? " analytics-row--indent" : ""}">
        <div class="analytics-row-label">${escapeHtml(label)}</div>
        <div class="analytics-row-stat"><strong>${sdgCount}</strong>/<strong>${total}</strong> courses <span class="analytics-pct">(${pct}%)</span></div>
    </div>`;
};

/**
 * Like `getTopSdgsHtml` but operates on raw item objects (from `databaseData`)
 * rather than DOM elements. Used on the home screen before cards are rendered.
 * @param {Array} items - Array of item objects with an `sdgs` number array
 * @returns {string} HTML string (empty string if no SDGs found)
 */
const getTopSdgsHtmlFromItems = function (items) {
    const sdgCounts = {};
    items.forEach((item) => {
        if (item.sdgs) item.sdgs.forEach((s) => { if (s) sdgCounts[String(s)] = (sdgCounts[String(s)] || 0) + 1; });
    });
    const top3 = Object.entries(sdgCounts).sort((a, b) => b[1] - a[1]).slice(0, 3);
    if (top3.length === 0) return "";
    let html = `<div class="analytics-top3"><span class="analytics-top3-label">Top 3 SDGs:</span>`;
    top3.forEach(([sdg]) => {
        html += `<a href="https://sdgs.un.org/goals/goal${sdg}" target="_blank" class="sdg-block sdg-${sdg}">${sdg}</a>`;
    });
    html += `</div>`;
    return html;
};

/**
 * Populate the analytics panel for the home screen.
 * Shows one stat row per visible category (e.g. "22-23 Courses",
 * "25-26 Courses") with SDG course counts and top-3 SDG blocks.
 * Called after background pre-loading completes.
 */
const updateHomeAnalytics = function () {
    const analyticsEl = document.getElementById("greendatabase-analytics");
    if (!analyticsEl) return;
    analyticsEl.classList.remove("collapsed");
    const toggleBtn = document.getElementById("greendatabase-analytics-toggle");
    if (toggleBtn) toggleBtn.style.display = "none";
    const body = analyticsEl.querySelector(".analytics-body");
    if (!body) return;
    const orderedData = Object.entries(databaseData)
        .filter(([, d]) => d.metadata && d.metadata.categoryVisible)
        .sort((a, b) => a[1].order - b[1].order);
    if (orderedData.length === 0 || !orderedData.some(([, d]) => d.totalPerFaculty)) {
        body.innerHTML = `<em>Loading...</em>`;
        return;
    }
    let html = "";
    orderedData.forEach(([, categoryData], idx) => {
        if (!categoryData.totalPerFaculty) return;
        const total = Object.values(categoryData.totalPerFaculty).reduce((s, f) => s + f.total, 0);
        const sdgCount = categoryData.items ? categoryData.items.length : 0;
        const title = categoryData.metadata.categoryTitle || "Unknown";
        html += getStatRowHtml(sdgCount, total, title, false);
        if (categoryData.items) html += getTopSdgsHtmlFromItems(categoryData.items);
        if (idx < orderedData.length - 1) html += `<div class="analytics-divider"></div>`;
    });
    body.innerHTML = html || `<em>No data available.</em>`;
};

/**
 * Refresh the analytics panel for the currently open category.
 * Counts only the cards that are currently visible (not filtered out).
 * - No faculty filter active: shows an "All courses" total row plus one row
 *   per faculty, each with its own top-3 SDG blocks.
 * - Faculty/programme filters active: shows one row per checked faculty,
 *   with indented sub-rows for any checked programmes within it.
 * The denominator for each row always uses the full course count from the
 * sheet (including hidden rows), not just the currently visible cards.
 */
const updateAnalytics = function () {
    const analyticsEl = document.getElementById("greendatabase-analytics");
    if (!analyticsEl || !currentSheetName || !databaseData[currentSheetName]) return;

    const body = analyticsEl.querySelector(".analytics-body");
    if (!body) return;

    const cards = getCurrentCards();
    if (!cards) return;

    const totalPerFaculty = databaseData[currentSheetName].totalPerFaculty || {};
    const allCards = Array.from(cards);
    const visibleCards = allCards.filter((c) => !c.classList.contains("filtered"));

    const facultyGroup = filtersWrapper ? filtersWrapper.querySelector(".greendatabase-filter-group[data-filter-id='faculty']") : null;
    const checkedFaculties = facultyGroup ? Array.from(facultyGroup.querySelectorAll(".faculty-parent-checkbox:checked")).map((cb) => cb.value) : [];
    const checkedPrograms = facultyGroup ? Array.from(facultyGroup.querySelectorAll(".program-child-checkbox:checked")).map((cb) => cb.value) : [];

    let html = "";

    if (checkedFaculties.length === 0) {
        // No filter — show overall + per-faculty breakdown
        const total = Object.values(totalPerFaculty).reduce((s, f) => s + f.total, 0);
        html += getStatRowHtml(visibleCards.length, total, "All courses", false);
        html += getTopSdgsHtml(visibleCards);
        html += `<div class="analytics-divider"></div>`;
        Object.keys(totalPerFaculty).sort().forEach((faculty) => {
            const facCards = visibleCards.filter((c) => c.getAttribute("data-faculty") === faculty);
            const facTotal = totalPerFaculty[faculty].total;
            html += getStatRowHtml(facCards.length, facTotal, faculty, false);
            html += getTopSdgsHtml(facCards);
        });
    } else {
        // Faculty/program filters active — cascade
        checkedFaculties.forEach((faculty) => {
            const facData = totalPerFaculty[faculty] || { total: 0, programs: {} };
            const facCards = visibleCards.filter((c) => c.getAttribute("data-faculty") === faculty);

            // Programs selected within this faculty
            const programsForFaculty = [...new Set(checkedPrograms.filter((p) =>
                facultyGroup && facultyGroup.querySelector(`.program-child-checkbox[value="${CSS.escape(p)}"][data-parent-faculty="${CSS.escape(faculty)}"]`)
            ))];

            // Faculty row always uses the full faculty total as denominator
            const facTotal = facData.total;

            html += getStatRowHtml(facCards.length, facTotal, faculty, false);
            html += getTopSdgsHtml(facCards);

            if (programsForFaculty.length > 0) {
                html += `<div class="analytics-programs">`;
                programsForFaculty.forEach((program) => {
                    const progCards = facCards.filter((c) => parseProgramList(c.getAttribute("data-program")).includes(program));
                    const progTotal = facData.programs[program] || 0;
                    html += getStatRowHtml(progCards.length, progTotal, program, true);
                    html += getTopSdgsHtml(progCards);
                });
                html += `</div>`;
            }
        });
    }

    body.innerHTML = html;
};

/* Sorting */

// Flag to ensure the sort <select> change listener is only attached once
let hasSortingBeenInitializedOnce = false;

/**
 * Populate the sort <select> dropdown with ascending/descending options for
 * every sortable field in the current category, plus a "Default" option.
 * The change listener is attached only on the first call; subsequent calls
 * (when navigating between categories) just repopulate the options.
 */
const initializeSorting = function () {
    var _a;
    if (sortElement && currentSheetName && databaseData.hasOwnProperty(currentSheetName)) {
        if (hasSortingBeenInitializedOnce) {
            // Clear previous list
            sortElement.textContent = '';
        }
        let sortFields = (_a = databaseData[currentSheetName].metadata.fieldMetadata) === null || _a === void 0 ? void 0 : _a.filter((field) => field.sortable);
        if (!sortFields) {
            sortFields = [];
        }
        ;
        sortFields = [
            {
                title: getLocalizedValue("Default///Standaard", true),
                id: "default"
            },
            ...sortFields
        ];
        if (sortFields) {
            sortFields.forEach((field) => {
                const optionAscending = document.createElement("option");
                optionAscending.text = field.title + " ↑";
                optionAscending.value = field.id + "-ascending";
                const optionDescending = document.createElement("option");
                optionDescending.text = field.title + " ↓";
                optionDescending.value = field.id + "-descending";
                sortElement.appendChild(optionAscending);
                sortElement.appendChild(optionDescending);
                sortElement.value = "default-ascending";
            });
        }
        if (!hasSortingBeenInitializedOnce) {
            sortElement.addEventListener("input", sortCurrentCards);
        }
        hasSortingBeenInitializedOnce = true;
    }
};

/**
 * Re-order the rendered cards in the DOM to match the currently selected
 * sort option. Parses the <select> value (format: "<fieldId>-ascending" or
 * "<fieldId>-descending") and sorts by the corresponding data-* attribute.
 */
const sortCurrentCards = function () {
    const cards = getCurrentCards();
    if (cards && sortElement) {
        let sortAttributeSplit = sortElement.value.split("-");
        const parentElement = cards[0].parentElement;
        let sortField, sortOrder;
        if (sortAttributeSplit.length > 1) {
            sortOrder = sortAttributeSplit.pop();
            sortField = sortAttributeSplit.join("-");
        }
        else {
            sortOrder = "ascending";
            sortField = sortAttributeSplit[0];
        }
        if (parentElement) {
            const sortedCards = Array.from(cards).sort(sortByAttribute("data-" + sortField, sortOrder === "ascending"));
            for (var i = 0; i < sortedCards.length; i++) {
                parentElement.appendChild(sortedCards[i]);
            }
        }
    }
};

/* Helper functions */

/** Convert the sheet string "Yes" to true and anything else to false. */
const yesNoToBoolean = function (val) {
    return val === 'Yes';
};
/**
 * Convert a 0-based column index to a spreadsheet column letter (A, B, … Z, AA, …).
 * Used to build the range string for the Sheets API call (e.g. "A12:P").
 * @param {number} n - 0-based column index
 * @returns {string} Column letter(s)
 */
const numberToColName = function (n) {
    const ordA = 'a'.charCodeAt(0);
    const ordZ = 'z'.charCodeAt(0);
    const len = ordZ - ordA + 1;
    let s = "";
    while (n >= 0) {
        s = String.fromCharCode(n % len + ordA) + s;
        n = Math.floor(n / len) - 1;
    }
    return s;
};

/**
 * Return a random integer in [0, max).
 * Used to pick one of the five TU Delft card flame-style variants.
 * @param {number} max - Upper bound (exclusive)
 */
function getRandomInt(max) {
    return Math.floor(Math.random() * max);
}

/**
 * Bidirectional map for English ↔ Dutch faculty name translation.
 * Used when the sheet stores English names but the page language is Dutch,
 * or vice versa.
 */
class TwoWayMap {
    constructor(map) {
        this.map = map;
        this.reverseMap = {};
        for (const key in map) {
            const value = map[key];
            this.reverseMap[value] = key;
        }
    }
    getDutch(key) { return this.map.hasOwnProperty(key) ? this.map[key] : key; }
    getEnglish(key) { return this.reverseMap.hasOwnProperty(key) ? this.reverseMap[key] : key; }
}
const englishDutchMap = new TwoWayMap({
    // Faculties
    "Technology, Policy and Management": "Techniek, Bestuur en Management",
    "Mechanical, Maritime and Materials Engineering": "Werktuigbouwkunde, Maritieme Techniek &amp; Technische Materiaalwetenschappen",
    "Industrial Design Engineering": "Industrieel Ontwerpen",
    "Electrical Engineering, Mathematics and Computer Science": "Elektrotechniek, Wiskunde en Informatica",
    "Civil Engineering and Geosciences": "Civiele Techniek en Geowetenschappen",
    "Architecture and the Built Environment": "Bouwkunde",
    "Applied Sciences": "Technische Natuurwetenschappen",
    "Aerospace Engineering": "Luchtvaart- en Ruimtevaarttechniek"
});

/**
 * Return the correctly-localised version of a value for the current page language.
 * Handles three cases:
 *   1. Bilingual string "English///Dutch" — splits and picks the right half.
 *   2. Plain string — looks it up in the englishDutchMap for faculty names.
 *   3. "Yes"/"No" — translates to "Ja"/"Nee" on Dutch pages.
 * Optionally HTML-escapes the result before returning.
 * @param {string}  val          - Raw value from the sheet
 * @param {boolean} doEscapeHtml - Whether to escape HTML special characters
 * @returns {string}
 */
function getLocalizedValue(val, doEscapeHtml) {
    if (!val) {
        val = "?";
    }
    if (doEscapeHtml) {
        val = escapeHtml(val);
    }
    // Translate booleans
    if (["Yes", "No"].includes(val) && language === "nl-NL") {
        return (val === "Yes") ? "Ja" : "Nee";
    }
    // Get localized value, from a string with the format "English///Dutch"
    const splitValue = val.split("///");
    if (splitValue.length > 1) {
        // Value is localized
        if (language === "nl-NL") {
            // Dutch
            return splitValue[1];
        }
        else {
            // English
            return splitValue[0];
        }
    }
    else {
        // Value is not localized, but perhaps it is in the translation map
        if (language === "nl-NL") {
            // Dutch
            return englishDutchMap.getDutch(val);
        }
        else {
            // English
            return englishDutchMap.getEnglish(val);
        }
    }
}

/** Escape the five HTML special characters to prevent XSS when injecting sheet data into innerHTML. */
const escapeHtml = (str) => str.replace(/[&<>'"]/g, (tag) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    "'": '&#39;',
    '"': '&quot;'
}[tag]));

/**
 * Derive a safe lowercase identifier from a field name.
 * Takes only the part before any "/" (strips bilingual suffix), removes
 * spaces and "?" characters. Used as the data-* attribute key for filtering.
 */
const makeId = (str) => str.toString().split("/")[0].toLowerCase().replace(" ", "").replace("?", "");

/**
 * Parse a programme field value into an array of programme name strings.
 * The value may be a Python-style list literal written by the scraper
 * (e.g. "['MSc Systems Engineering', 'MSc Management']") or a plain string.
 * Returns an empty array for missing or "#N/A" values.
 * @param {string|null} val - Raw programme value from the sheet or card attribute
 * @returns {string[]}
 */
const parseProgramList = function (val) {
    if (!val || val === "#N/A") return [];
    if (!val.trim().startsWith("[")) return [val.trim()];
    const matches = val.match(/['"]([^'"]+)['"]/g);
    if (!matches) return [];
    return matches.map((s) => s.replace(/^['"]|['"]$/g, "").trim());
};

/**
 * Return a comparator function that sorts two DOM elements by a data attribute.
 * Used with Array.sort() on the card NodeList in `sortCurrentCards`.
 * @param {string}  attribute     - The data-* attribute name to compare (e.g. "data-default")
 * @param {boolean} sortAscending - true for A→Z / 0→9, false for the reverse
 * @returns {function}
 */
function sortByAttribute(attribute, sortAscending) {
    return function (a, b) {
        const aVal = a.getAttribute(attribute);
        const bVal = b.getAttribute(attribute);
        if (aVal && bVal) {
            return aVal.localeCompare(bVal) * (sortAscending ? 1 : -1);
        }
        return 0;
    };
}

/**
 * Log a status message to the browser console and display it in the
 * #greendatabase-status element (visible during local development).
 * @param {string} status - Message describing the current loading step
 */
function setStatus(status) {
    console.log("%cGreenDatabase Status: ", "font-weight: bold;", status);
    if (statusElement) {
        statusElement.innerText = status;
    }
}

/* HTML creating functions */

/**
 * Build the HTML for a coloured heading banner shown above a category's cards.
 * Uses TU Delft grid/background CSS classes from the CMS theme.
 * @param {string} title       - Heading text (already localised and escaped)
 * @param {string} color       - TU Delft colour name (e.g. "green", "blue")
 * @param {string} description - Optional subtitle/description HTML
 * @returns {string} HTML string
 */
const getHeadingHtml = function (title, color, description) {
    return `<div class="grid-background--${color} grid-background--boxed" style="margin-bottom: 20px;">
    <div class="row grid grid--noPaddingBottom layout-0">
    <div class="sm-12">
    <div class="t3ce frame-type-header">
    <h2 style="margin-bottom: 0;">
    ${title}
    </h2>
    ${description}
    </div>
    </div>
    </div>
    </div>`;
};

/**
 * Build the HTML string for a single card.
 * Used for both home-screen category cards and individual course/project cards.
 *
 * @param {boolean}     colored         - true = coloured category card, false = grey content card
 * @param {string}      subtitle        - Small label above the title (e.g. faculty name)
 * @param {string}      title           - Main heading of the card
 * @param {string}      color           - TU Delft colour name applied to the card accent
 * @param {string|null} link            - URL for the "Read more" button or category card href
 * @param {Array|null}  fields          - Array of {label, value, type} display fields
 * @param {Object}      cardAttributes  - Key/value pairs written as data-* attributes (used for
 *                                        filtering, sorting, and search matching)
 * @param {number[]}    [sdgs]          - Array of SDG numbers to render as coloured blocks
 * @returns {string} HTML string for the card wrapper + card
 */
const getCardHtml = function (colored, subtitle, title, color, link, fields, cardAttributes, sdgs) {
    let cardHtml = "";
    // Add an extra attribute for the searchable string
    if (!cardAttributes) {
        cardAttributes = {};
    }
    cardAttributes["searchstring"] = "";
    // Subtitle
    if (subtitle) {
        cardHtml += `<div class="label">` + subtitle + `</div>`;
        cardAttributes["searchstring"] += subtitle;
    }
    // Title
    if (title) {
        cardHtml += `<h3>` + title + `</h3>`;
        cardAttributes["searchstring"] += " " + title;
    }
    // Other fields
    if (fields && fields.length > 0) {
        fields.forEach((field) => {
            if (field && field.label && field.value) {
                if (field.type && field.type === "description") {
                    // Value without label
                    cardHtml += `<div>` + field.value + `</div>`;
                }
                else {
                    // Value with label
                    cardHtml += `<div><strong>${field.label}</strong>: ` + field.value + `</div>`;
                }
                if (cardAttributes) {
                    cardAttributes["searchstring"] += " " + field.value;
                }
            }
        });
    }
    // SDGs
    if (sdgs && sdgs.length > 0) {
        cardHtml += `<div class="sdgs">`;
        sdgs.forEach((sdg) => {
            cardHtml += `<a href="https://sdgs.un.org/goals/goal${sdg}" target="_blank" class="sdg-block sdg-${sdg}">${sdg}</a>`;
        });
        cardHtml += `</div>`;
        cardAttributes["sdgs"] = sdgs.join(",");
    }
    if (link && !colored) {
        cardHtml += `<a href="${link}" target="_blank" class="btn btn--single align-center btn--${color}">${getLocalizedValue("Read more///Meer lezen", true)}</a>`;
    }
    // Content wrapper
    cardHtml = `<section class="card__content">` + cardHtml + '</section>';
    // Card / Link
    const flameStyleIndex = getRandomInt(5) + 1;
    if (!colored) {
        // So that buttons and SDGs stand out
        color = "grey_light";
    }
    if (link && colored) { // This now correctly handles category cards which have a link of "#"
        cardHtml = `<a href="${link}" class="card card--no_description card--colored card--halfHeight card--no_image flameStyle${flameStyleIndex} card--${color}">` + cardHtml + `</a>`;
    }
    else {
        cardHtml = `<div class="card card--no_description card--colored card--halfHeight card--no_image flameStyle${flameStyleIndex} card--${color}">` + cardHtml + `</div>`;
    }
    // Card wrapper
    cardAttributes["searchstring"] = cardAttributes["searchstring"].toLowerCase();
    let cardAttributesString = "";
    for (const [key, value] of Object.entries(cardAttributes)) {
        cardAttributesString += ` data-${key}="${value}"`;
    }
    cardHtml = `<div class="card-wrapper" ${cardAttributesString}>` + cardHtml + '</div>';
    return cardHtml;
};

/* START */
if (databaseIntroContainer && databaseEntriesContainer && databaseEntriesContainer) {
    setStatus("Loading API");
    gapi.load('client', loadApi);
}
