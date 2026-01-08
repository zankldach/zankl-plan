
// static/app.js — Austausch 2026-01-08
(function () {
  'use strict';
  console.log('[app.js] boot ✔');

  // =========================
  // Helpers
  // =========================
  const qs  = (sel, root = document) => root.querySelector(sel);
  const qsa = (sel, root = document) => Array.from(root.querySelectorAll(sel));

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
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });
      return await res.json();
    } catch (e) {
      console.error('POST fail', url, e);
      return { ok: false, error: String(e) };
    }
  }

  // =========================
  // State (URL + DOM)
  // =========================
  const state = {
    standort: getParam('standort', 'engelbrechts'),
    kw: toInt(getParam('kw', '1'), 1),
    year: toInt(getParam('year', '2025'), 2025),
    fourDay: false, // initial wird unten ermittelt
  };

  // --- UI-Elemente tolerant finden ---
  const ui = {
    standort:
      qs('#wk-standort') ||
      qs('#standortSelect') ||
      qs('select[name="standort"]') ||
      null,
    kw:
      qs('#wk-kw') ||
      qs('#kwSelect') ||
      qs('input[name="kw"], select[name="kw"]') ||
      null,
    year:
      qs('#wk-year') ||
      qs('#yearSelect') ||
      qs('input[name="year"], select[name="year"]') ||
      null,
    fourDayToggle: findFourDayToggle(),
  };

  function findFourDayToggle() {
    // Bevorzugte IDs/Namen
    let cand =
      qs('#fourDayToggle') ||
      qs('#four_day_week') ||
      qs('input[type="checkbox"][name="four_day_week"]');
    if (cand) return cand;

    // Fallback: Checkbox über Labeltext „4‑Tage“
    const checks = qsa('input[type="checkbox"]');
    for (const chk of checks) {
      const labFor = chk.id ? qs(`label[for="${chk.id}"]`) : null;
      const text =
        (labFor?.textContent || '') +
        (chk.closest('label')?.textContent || '') +
        (chk.parentElement?.textContent || '');
      if (/4.?tage/i.test(text)) return chk;
    }
    return null;
  }

  // Initialen 4‑Tage‑Status bestimmen
  if (ui.fourDayToggle) {
    state.fourDay = !!ui.fourDayToggle.checked;
  } else if (typeof window.__fourDay !== 'undefined') {
    state.fourDay = !!window.__fourDay;
  } else {
    // Heuristik: ist Freitag bereits als disabled gerendert?
    const anyFridayDisabled =
      qsa('.fri-disabled, .is-disabled').some(el => {
        return /freitag/i.test(el.textContent || '') || el.classList.contains('fri-disabled');
      });
    state.fourDay = anyFridayDisabled;
  }

  // =========================
  // Eingaben freischalten (Safety)
  // =========================
  qsa('input[disabled], select[disabled], textarea[disabled]').forEach(el => el.removeAttribute('disabled'));
  qsa('input[readonly], textarea[readonly]').forEach(el => el.removeAttribute('readonly'));

  // =========================
  // Freitag aktiv/deaktiv (Table & Grid)
  // =========================
  function applyFridayDisabled(disabled) {
    // Tabellen-Kopf (TH)
    qsa('table').forEach(tbl => {
      const headerRow = qs('thead tr', tbl) || tbl.rows?.[0] || null;
      if (!headerRow) return;

      const headers = Array.from(headerRow.children);
      let friIdx = headers.findIndex(th => /freitag/i.test(th.textContent || ''));
      if (friIdx < 0 && headers.length >= 6) friIdx = headers.length - 1; // Label + 5 Tage ⇒ letzter = Freitag

      if (friIdx >= 0 && headers[friIdx]) {
        headers[friIdx].classList.toggle('is-disabled', disabled);
        headers[friIdx].classList.toggle('fri-disabled', disabled);
      }

      // Datenzeilen
      qsa('tbody tr', tbl).forEach(tr => {
        const tds = Array.from(tr.children);
        const td = tds[friIdx < 0 ? tds.length - 1 : friIdx];
        if (!td) return;
        td.classList.toggle('is-disabled', disabled);
        td.classList.toggle('fri-disabled', disabled);
        const input = td.querySelector('input, textarea');
        if (input) {
          input.disabled = !!disabled;
          input.readOnly = !!disabled;
          if (disabled) input.blur();
        }
      });
    });

    // Grid (.wk-grid: 1 Label + 5 Tage = 6 Spalten)
    qsa('.wk-grid').forEach(grid => {
      const cells = qsa('.wk-cell', grid);
      const cols = 6; // 0=Label, 1..5=Mo..Fr
      cells.forEach((cell, idx) => {
        const c = idx % cols;
        if (c === 5) {
          cell.classList.toggle('is-disabled', disabled);
          cell.classList.toggle('fri-disabled', disabled);
          const input = cell.querySelector('input, textarea');
          if (input) {
            input.disabled = !!disabled;
            input.readOnly = !!disabled;
            if (disabled) input.blur();
          }
        }
      });
    });
  }

  // initial anwenden
  applyFridayDisabled(state.fourDay);

  // =========================
  // Zellen speichern (input/textarea)
  // =========================
  function findRowDayFromDOM(el) {
    // 1) data-row/data-day
    const r = el.dataset?.row, d = el.dataset?.day;
    if (r != null && d != null) {
      const rowIdx = parseInt(r, 10);
      const dayIdx = parseInt(d, 10);
      if (Number.isFinite(rowIdx) && Number.isFinite(dayIdx)) return { rowIdx, dayIdx };
    }
    // 2) Tabelle: erste Spalte = Label, danach Mo..Fr
    const td = el.closest('td');
    const tr = td?.closest('tr');
    if (tr && td) {
      const cells = Array.from(tr.children);
      const dayIdx = cells.indexOf(td) - 1;         // Label abziehen
      const rows = Array.from(tr.parentElement.children);
      const rowIdx = rows.indexOf(tr);
      if (dayIdx >= 0) return { rowIdx, dayIdx };
    }
    // 3) Grid: .wk-grid (0=Label, 1..5=Mo..Fr)
    const cell = el.closest('.wk-cell');
    const grid = cell?.closest('.wk-grid');
    if (grid && cell) {
      const all = qsa('.wk-cell', grid);
      const idx = all.indexOf(cell);
      const cols = 6;
      const rIdx = Math.floor(idx / cols);
      const cIdx = idx % cols;        // 0=Label → Mo=0 .. Fr=4
      const dayIdx = cIdx - 1;
      if (dayIdx >= 0) return { rowIdx: rIdx, dayIdx };
    }
    return { rowIdx: null, dayIdx: null };
  }

  document.addEventListener('input', (e) => {
    const el = e.target;
    if (!(el.tagName === 'INPUT' || el.tagName === 'TEXTAREA')) return;
    if (el.closest('.wk-sidebar')) return; // Sidebar separat

    const { rowIdx, dayIdx } = findRowDayFromDOM(el);
    if (rowIdx == null || dayIdx == null) return;

    // In 4‑Tage‑Woche Freitag nicht speichern (Server würde ggf. skippen)
    if (state.fourDay && dayIdx === 4) return;

    postJSON('/api/week/set-cell', {
      year: state.year,
      kw: state.kw,
      standort: state.standort,
      row: rowIdx,
      day: dayIdx,
      value: el.value || ''
    }).then(res => {
      if (!res.ok && !res.skipped) {
        console.warn('[set-cell] Speichern fehlgeschlagen', res);
      }
    });
  });

  // =========================
  // Kleinbaustellen speichern
  // =========================
  function saveSmallJob(el) {
    let idx = el.dataset?.rowIndex != null ? parseInt(el.dataset.rowIndex, 10) : NaN;
    if (!Number.isFinite(idx)) {
      const container = el.closest('.wk-sidebar') || document;
      const items = qsa('.sj-input, input, textarea', container)
        .filter(n => n.closest('.wk-sidebar'));
      idx = items.indexOf(el);
    }
    if (!Number.isFinite(idx) || idx < 0) idx = 0;

    postJSON('/api/klein/set', {
      standort: state.standort,
      row_index: idx,
      text: el.value || ''
    }).then(res => {
      if (!res.ok) console.warn('[klein/set] Speichern fehlgeschlagen', res);
    });
  }

  document.addEventListener('input', (e) => {
    const el = e.target;
    if (el.matches('.sj-input') || el.closest('.wk-sidebar')) {
      saveSmallJob(el);
    }
  });
  document.addEventListener('change', (e) => {
    const el = e.target;
    if (el.matches('.sj-input') || el.closest('.wk-sidebar')) {
      saveSmallJob(el);
    }
  });

  // =========================
  // 4‑Tage‑Woche Toggle → API + UI
  // =========================
  async function setFourDay(value) {
    const res = await postJSON('/api/week/set-four-day', {
      standort: state.standort,
      kw: state.kw,
      year: state.year,
      value: !!value
    });
    if (!res.ok) {
      console.warn('[set-four-day] fehlgeschlagen', res);
      return false;
    }
    state.fourDay = !!res.four_day_week;
    applyFridayDisabled(state.fourDay);
    return true;
  }

  if (ui.fourDayToggle) {
    ui.fourDayToggle.addEventListener('change', async (e) => {
      const desired = !!e.target.checked;
      const ok = await setFourDay(desired);
      if (!ok) e.target.checked = !desired; // rollback
    });
  }

  // =========================
  // Navigation: Standort / KW / Jahr
  // =========================
  function navigate(newStandort, newKw, newYear) {
    const params = new URLSearchParams(location.search);
    params.set('standort', newStandort ?? state.standort);
    params.set('kw', String(newKw ?? state.kw));
    params.set('year', String(newYear ?? state.year));
    location.href = '/week?' + params.toString();
  }

  if (ui.standort) ui.standort.addEventListener('change', e => navigate(e.target.value, null, null));
  if (ui.kw)       ui.kw.addEventListener('change',     e => navigate(null, toInt(e.target.value, state.kw), null));
  if (ui.year)     ui.year.addEventListener('change',   e => navigate(null, null, toInt(e.target.value, state.year)));

  // =========================
  // Debug
  // =========================
  window.__zankl_dbg = { ...state };
  console.log('[app.js] state', window.__zankl_dbg);
})();
