(function initTableTools() {
  const SORT_ASCENDING = "ascending";
  const SORT_DESCENDING = "descending";
  const EMPTY_DISPLAY_VALUES = new Set(["", "-", "–", "Nicht angegeben"]);

  function isStaticRow(row) {
    const firstCell = row.children[0];
    return !firstCell || firstCell.hasAttribute("colspan");
  }

  function dataRows(tbody) {
    return Array.from(tbody.rows).filter((row) => !isStaticRow(row));
  }

  function parseGermanNumber(raw) {
    const cleaned = raw.replace(/[^0-9,.-]/g, "").replace(/\.(?=\d{3}(\D|$))/g, "").replace(",", ".");
    const value = Number.parseFloat(cleaned);
    return Number.isNaN(value) ? null : value;
  }

  function parseGermanDate(raw) {
    if (/^\d+$/.test(raw)) {
      // data-sort-value keys such as {{ value|date:"YmdHis" }}
      return Number.parseInt(raw, 10);
    }
    const match = raw.match(/(\d{1,2})\.(\d{1,2})\.(\d{4})(?:\D+?(\d{1,2}):(\d{2}))?/);
    if (!match) return null;
    const [, day, month, year, hour, minute] = match;
    return (
      Number(year) * 100000000 +
      Number(month) * 1000000 +
      Number(day) * 10000 +
      Number(hour || 0) * 100 +
      Number(minute || 0)
    );
  }

  function cellSortKey(row, columnIndex, sortType) {
    const cell = row.children[columnIndex];
    if (!cell) return null;
    const raw = (cell.dataset.sortValue ?? cell.textContent).trim();
    if (EMPTY_DISPLAY_VALUES.has(raw)) return null;
    if (sortType === "number") return parseGermanNumber(raw);
    if (sortType === "date") return parseGermanDate(raw);
    return raw;
  }

  function compareKeys(a, b, direction) {
    // Empty or unparseable cells sort last in both directions.
    if (a === null && b === null) return 0;
    if (a === null) return 1;
    if (b === null) return -1;
    let result;
    if (typeof a === "number" && typeof b === "number") {
      result = a - b;
    } else {
      result = String(a).localeCompare(String(b), "de", { sensitivity: "base", numeric: true });
    }
    return direction === SORT_DESCENDING ? -result : result;
  }

  function headerCells(table) {
    const headRow = table.tHead?.rows[0];
    return headRow ? Array.from(headRow.cells) : [];
  }

  function isSortableHeader(th) {
    if (th.dataset.sort === "none") return false;
    if (!th.textContent.trim()) return false;
    return !th.querySelector("input, button, a, select");
  }

  function setupTable(table) {
    const state = {
      table,
      originalRows: Array.from(table.tBodies).map((tbody) => ({ tbody, rows: dataRows(tbody) })),
      sortSelect: null,
      filterInput: null,
      countEl: null,
      totalRows: Array.from(table.tBodies).reduce((sum, tbody) => sum + dataRows(tbody).length, 0),
    };

    const sortable = table.hasAttribute("data-sortable");
    const filterable = table.hasAttribute("data-filterable");
    const responsive = table.classList.contains("responsive-record-table");
    const sortableHeaders = sortable ? headerCells(table).filter(isSortableHeader) : [];

    if (sortable) {
      sortableHeaders.forEach((th) => enhanceHeader(state, th));
    }
    if (filterable || (sortable && responsive && sortableHeaders.length)) {
      buildToolbar(state, {
        withFilter: filterable,
        withSortSelect: sortable && responsive,
        sortableHeaders,
      });
    }
  }

  function enhanceHeader(state, th) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "table-sort-button";
    while (th.firstChild) {
      button.appendChild(th.firstChild);
    }
    th.appendChild(button);
    button.addEventListener("click", () => {
      const nextDirection = th.getAttribute("aria-sort") === SORT_ASCENDING ? SORT_DESCENDING : SORT_ASCENDING;
      applySort(state, th.cellIndex, nextDirection);
    });
  }

  function applySort(state, columnIndex, direction) {
    const table = state.table;
    const sortType = headerCells(table)[columnIndex]?.dataset.sortType || "text";

    Array.from(table.tBodies).forEach((tbody) => {
      const rows = dataRows(tbody);
      const staticRows = Array.from(tbody.rows).filter(isStaticRow);
      const keyed = rows.map((row) => ({ row, key: cellSortKey(row, columnIndex, sortType) }));
      keyed.sort((a, b) => compareKeys(a.key, b.key, direction));
      const fragment = document.createDocumentFragment();
      keyed.forEach((entry) => fragment.appendChild(entry.row));
      staticRows.forEach((row) => fragment.appendChild(row));
      tbody.appendChild(fragment);
    });

    headerCells(table).forEach((headerCell) => {
      if (headerCell.cellIndex === columnIndex) {
        headerCell.setAttribute("aria-sort", direction);
      } else {
        headerCell.removeAttribute("aria-sort");
      }
    });

    if (state.sortSelect) {
      const value = `${columnIndex}:${direction}`;
      if (state.sortSelect.value !== value) {
        state.sortSelect.value = value;
      }
    }
  }

  function restoreOriginalOrder(state) {
    state.originalRows.forEach(({ tbody, rows }) => {
      const staticRows = Array.from(tbody.rows).filter(isStaticRow);
      const fragment = document.createDocumentFragment();
      rows.forEach((row) => fragment.appendChild(row));
      staticRows.forEach((row) => fragment.appendChild(row));
      tbody.appendChild(fragment);
    });
    headerCells(state.table).forEach((headerCell) => headerCell.removeAttribute("aria-sort"));
  }

  function applyFilter(state) {
    const query = state.filterInput.value.trim().toLocaleLowerCase("de");
    let visible = 0;
    Array.from(state.table.tBodies).forEach((tbody) => {
      dataRows(tbody).forEach((row) => {
        const matches = !query || row.textContent.toLocaleLowerCase("de").includes(query);
        row.hidden = !matches;
        if (matches) visible += 1;
      });
    });
    if (state.countEl) {
      state.countEl.hidden = !query;
      state.countEl.textContent = query ? `${visible} von ${state.totalRows} Zeilen` : "";
    }
  }

  function buildToolbar(state, { withFilter, withSortSelect, sortableHeaders }) {
    const table = state.table;
    const toolbar = document.createElement("div");
    toolbar.className = "table-tools";

    if (withFilter) {
      const label = document.createElement("label");
      label.className = "table-tools__filter";
      label.append("Filtern ");
      const input = document.createElement("input");
      input.type = "search";
      input.placeholder = "Zeilen filtern …";
      label.appendChild(input);
      toolbar.appendChild(label);
      state.filterInput = input;
      input.addEventListener("input", () => applyFilter(state));

      const count = document.createElement("p");
      count.className = "table-tools__count";
      count.setAttribute("aria-live", "polite");
      count.hidden = true;
      state.countEl = count;
      toolbar.appendChild(count);
    }

    if (withSortSelect) {
      const label = document.createElement("label");
      label.className = "table-tools__sort";
      label.append("Sortieren ");
      const select = document.createElement("select");
      const defaultOption = document.createElement("option");
      defaultOption.value = "";
      defaultOption.textContent = "Standard";
      select.appendChild(defaultOption);
      sortableHeaders.forEach((th) => {
        const name = th.textContent.trim();
        [
          [SORT_ASCENDING, "aufsteigend"],
          [SORT_DESCENDING, "absteigend"],
        ].forEach(([direction, wording]) => {
          const option = document.createElement("option");
          option.value = `${th.cellIndex}:${direction}`;
          option.textContent = `${name} (${wording})`;
          select.appendChild(option);
        });
      });
      label.appendChild(select);
      toolbar.appendChild(label);
      state.sortSelect = select;
      select.addEventListener("change", () => {
        if (!select.value) {
          restoreOriginalOrder(state);
          return;
        }
        const [columnIndex, direction] = select.value.split(":");
        applySort(state, Number(columnIndex), direction);
      });
    }

    const anchor = table.closest(".table-responsive, .kiosk-table__wrapper") ?? table;
    anchor.parentElement.insertBefore(toolbar, anchor);
  }

  document.querySelectorAll("table[data-sortable], table[data-filterable]").forEach(setupTable);
})();
