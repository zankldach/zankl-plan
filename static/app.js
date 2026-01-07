
// static/app.js — Austausch Jänner 2026
(function () {
  console.log('app.js boot ✔');

  // --- Helpers ---
  function getParam(name, def) {
    const v = new URLSearchParams(location.search).get(name);
    return v !== null ? v : def;
  }
  function toInt(v, def) {
    const n = parseInt(v, 10);
    return Number.isFinite(n) ? n : def;
  }
  async function postJSON(url, data) {
    try {
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
      return await res.json();
    } catch (e) {
      console.error('POST fail', url, e);
      return { ok: false, error: String(e) };
    }
  }

  const standort = getParam("standort", "engelbrechts");
  const kw = toInt(getParam("kw", "1"), 1);
  const year = toInt(getParam("year", "2025"), 2025);
  const fourDay = !!(window.__fourDay);

  // --- Eingaben freischalten ---
  document.querySelectorAll('input[disabled], select[disabled], textarea[disabled]').forEach(el => el.removeAttribute('disabled'));
  document.querySelectorAll('input[readonly], textarea[readonly]').forEach(el => el.removeAttribute('readonly'));

  // --- Freitag grau markieren (ohne Datenverlust) ---
  function markFridayDisabled() {
    if (!fourDay) return;

    // 1) Tabellenlayout (TH/TD)
    document.querySelectorAll('table').forEach(tbl => {
      const headerRow = tbl.querySelector('thead tr') || tbl.querySelector('tr');
      if (!headerRow) return;
      const headers = Array.from(headerRow.children);
      let friIdx = headers.findIndex(th => /freitag/i.test(th.textContent || ''));
      // Fallback: letzter Tag = Freitag (Montag bis Freitag)
      if (friIdx < 0 && headers.length >= 6) friIdx = headers.length - 1;

      if (friIdx >= 0) {
        Array.from(tbl.querySelectorAll('tbody tr')).forEach(tr => {
          const tds = Array.from(tr.children);
          const td = tds[friIdx];
          if (td) {
            td.classList.add('fri-disabled');
            td.querySelectorAll('input, textarea').forEach(inp => {
              inp.setAttribute('readonly', 'readonly');
            });
          }
        });
      }
    });

    // 2) Gridlayout (.wk-grid)
    document.querySelectorAll('.wk-grid').forEach(grid => {
      const cells = Array.from(grid.querySelectorAll('.wk-cell'));
      const cols = 6; // 1 Label + 5 Tage
      cells.forEach((cell, idx) => {
        const c = idx % cols; // 0 = Label, 1..5 = Mo..Fr
        if (c === 5) {
          cell.classList.add('fri-disabled');
          cell.querySelectorAll('input, textarea').forEach(inp => {
            inp.setAttribute('readonly', 'readonly');
          });
        }
      });
    });
  }
  markFridayDisabled();

  // --- Week-Zellen speichern (Mo–Fr; bei 4-Tage Freitag nur anzeigen) ---
  document.addEventListener("input", function (e) {
    const el = e.target;
    if (!(el.tagName === "INPUT" || el.tagName === "TEXTAREA")) return;
    if (el.closest(".wk-sidebar")) return; // Sidebar separat

    // Datenquelle: data-row/data-day oder DOM-Position
    let rowIdx = el.dataset.row ? parseInt(el.dataset.row, 10) : null;
    let dayIdx = el.dataset.day ? parseInt(el.dataset.day, 10) : null;

    if (rowIdx == null || dayIdx == null) {
      // Tabellenstruktur
      const td = el.closest("td");
      const tr = td?.closest("tr");
      if (tr && td) {
        const cells = Array.from(tr.children);
        dayIdx = cells.indexOf(td) - 1; // erste Spalte = Label
        const rows = Array.from(tr.parentElement.children);
        rowIdx = rows.indexOf(tr);
      } else {
        // Grid-Struktur
        const cell = el.closest(".wk-cell");
        const grid = cell?.closest(".wk-grid");
        if (grid && cell) {
          const all = Array.from(grid.querySelectorAll(".wk-cell"));
          const idx = all.indexOf(cell);
          const cols = 6; // 1 Label + 5 Tage
          const r = Math.floor(idx / cols);
          const c = idx % cols;
          rowIdx = r;
          dayIdx = c - 1;
        }
      }
    }

    // In 4-Tage-Woche den Freitag nicht überschreiben
    if (fourDay && dayIdx === 4) {
      // UI lässt Tippen zu (falls kein readonly), aber wir speichern nicht → kein Datenverlust
      return;
    }

    if (rowIdx != null && dayIdx != null && dayIdx >= 0 && dayIdx <= 4) {
      postJSON("/api/week/set-cell", {
        year, kw, standort,
        row: rowIdx, day: dayIdx,
        value: el.value || ""
      }).then(res => {
        if (!res.ok && !res.skipped) console.warn("Speichern fehlgeschlagen", res);
      });
    }
  });

  // --- Kleinbaustellen speichern ---
  function saveSmallJob(el) {
    let idx = el.dataset.rowIndex ? parseInt(el.dataset.rowIndex, 10) : null;
    if (idx == null) {
      const sidebar = el.closest(".wk-sidebar");
      if (sidebar) {
        const items = Array.from(sidebar.querySelectorAll("input, textarea"));
        idx = items.indexOf(el);
      } else {
        const items = Array.from(document.querySelectorAll(".sj-input"));
        idx = items.indexOf(el);
      }
    }
    if (!Number.isFinite(idx)) idx = 0;

    postJSON("/api/klein/set", {
      standort, row_index: idx, text: el.value || ""
    }).then(res => {
      if (!res.ok) console.warn("Kleinbaustelle Speichern fehlgeschlagen", res);
    });
  }
  document.addEventListener("change", function (e) {
    const el = e.target;
    if (el.matches(".sj-input") || el.closest(".wk-sidebar")) {
      saveSmallJob(el);
    }
  });
  document.addEventListener("input", function (e) {
    const el = e.target;
    if (el.matches(".sj-input")) {
      saveSmallJob(el);
    }
  });

  // --- Auto-Navigation: Standort / KW / Jahr ---
  function navigate(newStandort, newKw, newYear) {
    const params = new URLSearchParams(location.search);
    params.set("standort", newStandort ?? standort);
    params.set("kw", newKw ?? kw);
    params.set("year", newYear ?? year);
    window.location.href = "/week?" + params.toString();
  }
  const sSel = document.getElementById("wk-standort") || document.querySelector('select[name="standort"]');
  const kwInput = document.getElementById("wk-kw") || document.querySelector('input[name="kw"]');
  const yearInput = document.getElementById("wk-year") || document.querySelector('input[name="year"]');
  if (sSel) sSel.addEventListener("change", (e) => navigate(e.target.value, null, null));
  if (kwInput) kwInput.addEventListener("change", (e) => navigate(null, e.target.value, null));
  if (yearInput) yearInput.addEventListener("change", (e) => navigate(null, null, e.target.value));

  // --- Debug ---
  window.__zankl_dbg = { standort, kw, year, fourDay };
  console.log('state:', window.__zankl_dbg);
})();
