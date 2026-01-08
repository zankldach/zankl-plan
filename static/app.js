
// static/app.js — Austausch 2026-01-08 (Kleinbaustellen: inkrementelles Editieren)
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
    fourDay: false, // init unten
  };

  // =========================
  // UI-Elemente (tolerant)
  // =========================
  const ui = {
    standort: qs('#wk-standort') || qs('#standortSelect') || qs('select[name="standort"]'),
    kw:       qs('#wk-kw')       || qs('#kwSelect')       || qs('input[name="kw"], select[name="kw"]'),
    year:     qs('#wk-year')     || qs('#yearSelect')     || qs('input[name="year"], select[name="year"]'),
    fourDayToggle: (function findFourDayToggle(){
      return (
        qs('#fourDayToggle') ||
        qs('#four_day_week') ||
        qs('input[type="checkbox"][name="four_day_week"]') ||
        // Fallback über Labeltext
        (function () {
          for (const chk of qsa('input[type="checkbox"]')) {
            const labFor = chk.id ? qs(`label[for="${chk.id}"]`) : null;
            const text =
              (labFor?.textContent || '') +
              (chk.closest('label')?.textContent || '') +
              (chk.parentElement?.textContent || '');
            if (/4.?tage/i.test(text)) return chk;
          }
          return null;
        })()
      );
    })(),
    sjContainer: qs('#sj-list') || qs('#wk-smalljobs') || qs('.wk-sidebar'),
  };

  // =========================
  // Eingaben zwangsweise freischalten
  // =========================
  qsa('input[disabled], select[disabled], textarea[disabled]').forEach(el => el.removeAttribute('disabled'));
  qsa('input[readonly], textarea[readonly]').forEach(el => el.removeAttribute('readonly'));
  // Sidebar Inputs klassifizieren
  function ensureSidebarEditable() {
    const cont = ui.sjContainer || document;
    const inputs = qsa('.wk-sidebar input, .wk-sidebar textarea, #sj-list input, #sj-list textarea, #wk-smalljobs input, #wk-smalljobs textarea', cont);
    inputs.forEach((inp, idx) => {
      inp.removeAttribute('disabled');
      inp.removeAttribute('readonly');
      inp.style.pointerEvents = 'auto';
      inp.classList.add('sj-input');
      if (!inp.dataset.rowIndex) inp.dataset.rowIndex = String(idx);
    });
  }

  // =========================
  // 4‑Tage‑Woche (Freitag sperren/entsperren)
  // =========================
  function applyFridayDisabled(disabled) {
    // Tabellenkopf + Zeilen
    qsa('table').forEach(tbl => {
      const headerRow = qs('thead tr', tbl) || tbl.rows?.[0] || null;
      if (headerRow) {
        const headers = Array.from(headerRow.children);
        let friIdx = headers.findIndex(th => /freitag/i.test(th.textContent || ''));
        if (friIdx < 0 && headers.length >= 6) friIdx = headers.length - 1;
        if (friIdx >= 0 && headers[friIdx]) {
          headers[friIdx].classList.toggle('is-disabled', disabled);
          headers[friIdx].classList.toggle('fri-disabled', disabled);
        }
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
      }
    });

    // Grid (.wk-grid: 1 Label + 5 Tage)
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

  // initialer fourDay-Status
  if (ui.fourDayToggle) {
    state.fourDay = !!ui.fourDayToggle.checked;
  } else if (typeof window.__fourDay !== 'undefined') {
    state.fourDay = !!window.__fourDay;
  } else {
    const anyFridayDisabled =
      qsa('.fri-disabled, .is-disabled').some(el => /freitag/i.test(el.textContent || '') || el.classList.contains('fri-disabled'));
    state.fourDay = anyFridayDisabled;
  }
  applyFridayDisabled(state.fourDay);

  // =========================
  // Zellen speichern (Wochenraster)
  // =========================
  function findRowDayFromDOM(el) {
    const r = el.dataset?.row, d = el.dataset?.day;
    if (r != null && d != null) {
      const rowIdx = parseInt(r, 10), dayIdx = parseInt(d, 10);
      if (Number.isFinite(rowIdx) && Number.isFinite(dayIdx)) return { rowIdx, dayIdx };
    }
    const td = el.closest('td'); const tr = td?.closest('tr');
    if (tr && td) {
      const cells = Array.from(tr.children);
      const dayIdx = cells.indexOf(td) - 1; // 1. Spalte Label
      const rows = Array.from(tr.parentElement.children);
      const rowIdx = rows.indexOf(tr);
      if (dayIdx >= 0) return { rowIdx, dayIdx };
    }
    const cell = el.closest('.wk-cell'); const grid = cell?.closest('.wk-grid');
    if (grid && cell) {
      const all = qsa('.wk-cell', grid);
      const idx = all.indexOf(cell);
      const cols = 6;
      const rIdx = Math.floor(idx / cols);
      const cIdx = idx % cols;
      const dayIdx = cIdx - 1; // 0=Label → Mo..Fr
      if (dayIdx >= 0) return { rowIdx: rIdx, dayIdx };
    }
    return { rowIdx: null, dayIdx: null };
  }

  document.addEventListener('input', (e) => {
    const el = e.target;
    if (!(el.tagName === 'INPUT' || el.tagName === 'TEXTAREA')) return;
    if (el.classList.contains('sj-input') || el.closest('.wk-sidebar')) return; // Sidebar separater Flow
    const { rowIdx, dayIdx } = findRowDayFromDOM(el);
    if (rowIdx == null || dayIdx == null) return;
    if (state.fourDay && dayIdx === 4) return;
    postJSON('/api/week/set-cell', {
      year: state.year, kw: state.kw, standort: state.standort,
      row: rowIdx, day: dayIdx, value: el.value || ''
    }).then(res => {
      if (!res.ok && !res.skipped
