
// static/app.js — Austausch Jänner 2026
(function () {
  // ----- Utilities -----
  function getParam(name, def) {
    const v = new URLSearchParams(location.search).get(name);
    return v !== null ? v : def;
  }
  function toInt(v, def) {
    const n = parseInt(v, 10);
    return Number.isFinite(n) ? n : def;
  }
  async function postJSON(url, data) {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    try {
      return await res.json();
    } catch {
      return { ok: false, error: "Invalid JSON response" };
    }
  }

  // Standort/KW/Jahr aus URL oder Fallback-Inputs ziehen
  const standort = getParam("standort", (document.getElementById("wk-standort")?.value) || "engelbrechts");
  const kw = toInt(getParam("kw", (document.getElementById("wk-kw")?.value) || "1"), 1);
  const year = toInt(getParam("year", (document.getElementById("wk-year")?.value) || "2025"), 2025);

  // ----- Eingaben wieder aktivieren (falls versehentlich deaktiviert) -----
  document.querySelectorAll('input[readonly], input[disabled], textarea[readonly], textarea[disabled]').forEach(el => {
    el.removeAttribute('readonly');
    el.removeAttribute('disabled');
  });

  // ----- Zellen speichern (Week-Grid) -----
  // Versucht zuerst data-Attribute (data-row, data-day). Fällt sonst auf DOM-Position zurück.
  document.addEventListener("input", function (e) {
    const el = e.target;
    if (el.tagName !== "INPUT" && el.tagName !== "TEXTAREA") return;

    // Ignore inputs aus der Sidebar (Kleinbaustellen) – die werden separat gespeichert
    if (el.closest(".wk-sidebar")) return;

    let rowIdx = el.dataset.row ? parseInt(el.dataset.row, 10) : null;
    let dayIdx = el.dataset.day ? parseInt(el.dataset.day, 10) : null;

    if (rowIdx == null || dayIdx == null) {
      // 1) Tabellenstruktur
      const td = el.closest("td");
      const tr = td?.closest("tr");
      if (tr && td) {
        const cells = Array.from(tr.children);
        const tdIndex = cells.indexOf(td);
        dayIdx = tdIndex - 1; // erste Spalte = Team/Mitarbeiter
        const tbody = tr.parentElement;
        const rows = Array.from(tbody.children);
        rowIdx = rows.indexOf(tr);
      } else {
        // 2) Grid-Struktur (.wk-grid/.wk-cell)
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

    // Nur gültige Mo–Fr speichern
    if (rowIdx != null && dayIdx != null && dayIdx >= 0 && dayIdx <= 4) {
      postJSON("/api/week/set-cell", {
        year,
        kw,
        standort,
        row: rowIdx,
        day: dayIdx,
        value: el.value || "",
      })
        .then((res) => {
          if (!res.ok && !res.skipped) {
            console.warn("Speichern fehlgeschlagen:", res);
          }
        })
        .catch((err) => console.error(err));
    }
  });

  // ----- Kleinbaustellen speichern -----
  // Erwartet inputs mit class .sj-input ODER beliebige inputs in der Sidebar .wk-sidebar
  function saveSmallJob(el) {
    // Index ermitteln (entweder data-row-index oder Position innerhalb der Sidebar)
    let idx = el.dataset.rowIndex ? parseInt(el.dataset.rowIndex, 10) : null;
    if (idx == null) {
      const sidebar = el.closest(".wk-sidebar");
      if (sidebar) {
        const items = Array.from(sidebar.querySelectorAll("input, textarea"));
        idx = items.indexOf(el);
      } else {
        // Fallback: globale Reihenfolge aller .sj-inputs
        const items = Array.from(document.querySelectorAll(".sj-input"));
        idx = items.indexOf(el);
      }
    }
    idx = Number.isFinite(idx) ? idx : 0;

    postJSON("/api/klein/set", {
      standort,
      row_index: idx,
      text: el.value || "",
    })
      .then((res) => {
        if (!res.ok) console.warn("Kleinbaustelle speichern fehlgeschlagen:", res);
      })
      .catch((err) => console.error(err));
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
      // Optional: Live-Speichern beim Tippen (nicht nur bei change)
      saveSmallJob(el);
    }
  });

  // ----- Navigation: Standort / KW / Jahr -----
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

  // ----- Safety: verhindert, dass Overlay/Styles Clicks sperren -----
  // (Falls irgendwo pointer-events:none gesetzt wurde.)
  document.querySelectorAll(".disable-pointer-events").forEach(el => el.classList.remove("disable-pointer-events"));
})();
