
// static/app.js — Austausch 2026-01-08 (Small Jobs fix + DnD + Persistenz)
(function () {
  'use strict';
  console.log('[app.js] boot ✔');

  // Helpers
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

  // State
  const state = {
    standort: getParam('standort', 'engelbrechts'),
    kw: toInt(getParam('kw', '1'), 1),
    year: toInt(getParam('year', '2025'), 2025),
    fourDay: false, // unten ermittelt
  };

  // UI (tolerant)
  const ui = {
    standort: qs('#wk-standort') || qs('#standortSelect') || qs('select[name="standort"]'),
    kw:       qs('#wk-kw')       || qs('#kwSelect')       || qs('input[name="kw"], select[name="kw"]'),
    year:     qs('#wk-year')     || qs('#yearSelect')     || qs('input[name="year"], select[name="year"]'),
    fourDayToggle: (function findFourDayToggle(){
      return (
        qs('#fourDayToggle') ||
        qs('#four_day_week') ||
        qs('input[type="checkbox"][name="four_day_week"]') ||
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

  // Eingaben freischalten
  qsa('input[disabled], select[disabled], textarea[disabled]').forEach(el => el.removeAttribute('disabled'));
  qsa('input[readonly], textarea[readonly]').forEach(el => el.removeAttribute('readonly'));

  // 4‑Tage‑Woche: Freitag sperren/entsperren
  function applyFridayDisabled(disabled) {
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
  if (ui.fourDayToggle) {
    state.fourDay = !!ui.fourDayToggle.checked;
  } else if (typeof window.__fourDay !== 'undefined') {
    state.fourDay = !!window.__fourDay;
  }
  applyFridayDisabled(state.fourDay);

  // Week-Zellen speichern
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
    if (el.classList.contains('sj-input') || el.closest('.wk-sidebar')) return; // Sidebar separat
    const { rowIdx, dayIdx } = findRowDayFromDOM(el);
    if (rowIdx == null || dayIdx == null) return;
    if (state.fourDay && dayIdx === 4) return;
    postJSON('/api/week/set-cell', {
      year: state.year, kw: state.kw, standort: state.standort,
      row: rowIdx, day: dayIdx, value: el.value || ''
    }).then(res => {
      if (!res.ok && !res.skipped) console.warn('[set-cell] speichern fehlgeschlagen', res);
    });
  });

  // Kleinbaustellen – inkrementell + persistent
  const cont = ui.sjContainer || qs('#sj-list') || qs('.wk-sidebar');
  if (cont) {
    // vorhandene Inputs sicher editierbar
    qsa('input, textarea', cont).forEach((inp, idx) => {
      inp.removeAttribute('disabled');
      inp.removeAttribute('readonly');
      inp.style.pointerEvents = 'auto';
      inp.classList.add('sj-input');
      if (!inp.dataset.rowIndex) inp.dataset.rowIndex = String(idx);
      // kein sichtbarer Platzhaltertext
      if (inp.placeholder) inp.placeholder = '';
    });

    const SJ_MAX = 200;
    function readList() {
      return qsa('.sj-input', cont).map(i => (i.value || '').trim());
    }
    function normalize(items) {
      const filled = items.filter(t => t.length > 0);
      const out = filled.slice(0, SJ_MAX);
      out.push(''); // genau eine leere unten
      return out;
    }

    // Speichern (debounced) – bei Eingabe, damit Wechsel die Daten nicht verliert
    let sjSaveTimer = null;
    function scheduleSaveDebounced() {
      if (sjSaveTimer) clearTimeout(sjSaveTimer);
      const items = readList();
      sjSaveTimer = setTimeout(() => {
        postJSON('/api/klein/save-list', {
          standort: state.standort,
          items: normalize(items)
        }).then(res => {
          if (!res.ok) console.warn('[klein/save-list] fehlgeschlagen', res);
        });
      }, 250);
    }

    // Beim Eingeben nur speichern (debounced) – KEIN Neuaufbau, KEIN Focus-Verlust
    cont.addEventListener('input', (e) => {
      const el = e.target;
      if (!el.classList.contains('sj-input')) return;
      scheduleSaveDebounced();
    });

    // Bei Enter / Blur / Change: Liste komprimieren + **danach** speichern
    function compressAndRenderKeepFocus() {
      const items = normalize(readList());
      const listEl = qs('#sj-list', cont) || cont;

      // Fokus & Caret merken
      const active = document.activeElement;
      let focusIdx = -1, caretS = null, caretE = null;
      const currInputs = qsa('.sj-input', listEl);
      if (active && active.classList.contains('sj-input')) {
        focusIdx = currInputs.indexOf(active);
        try { caretS = active.selectionStart; caretE = active.selectionEnd; } catch (_) {}
      }

      // Neu aufbauen
      listEl.innerHTML = '';
      items.forEach((text, idx) => {
        const row = document.createElement('div');
        row.className = 'sj-row';
        row.setAttribute('draggable', 'true');          // ← DnD
        const input = document.createElement('input');
        input.type = 'text';
        input.className = 'sj-input';
        input.dataset.rowIndex = String(idx);
        input.value = text;
        input.placeholder = '';
        row.appendChild(input);
        listEl.appendChild(row);
      });

      // Fokus wiederherstellen (sofern sinnvoll)
      const newInputs = qsa('.sj-input', listEl);
      const target = newInputs[focusIdx] || newInputs[newInputs.length - 1];
      if (target) {
        target.focus();
        if (caretS != null) {
          try { target.setSelectionRange(caretS, caretE ?? caretS); } catch (_) {}
        }
      }
    }

    cont.addEventListener('keydown', (e) => {
      const el = e.target;
      if (!el.classList.contains('sj-input')) return;
      if (e.key === 'Enter') {
        e.preventDefault();
        compressAndRenderKeepFocus();
        scheduleSaveDebounced();
      }
    });
    cont.addEventListener('change', (e) => {
      const el = e.target;
      if (!el.classList.contains('sj-input')) return;
      compressAndRenderKeepFocus();
      scheduleSaveDebounced();
    });
    cont.addEventListener('blur', (e) => {
      const el = e.target;
      if (!el.classList.contains('sj-input')) return;
      compressAndRenderKeepFocus();
      scheduleSaveDebounced();
    }, true);

    // Vor dem Verlassen der Seite sicher speichern
    window.addEventListener('beforeunload', () => {
      const items = normalize(readList());
      navigator.sendBeacon?.('/api/klein/save-list', JSON.stringify({ standort: state.standort, items }));
    });

    // --------------- Drag & Drop ---------------
    // Sidebar-Zeilen: draggable + Text mitgeben
    cont.addEventListener('dragstart', (e) => {
      const row = e.target.closest('.sj-row');
      const inp = row?.querySelector('.sj-input');
      if (!inp) return;
      const text = (inp.value || '').trim();
      if (!text) { e.preventDefault(); return; }
      e.dataTransfer.effectAllowed = 'copy';
      e.dataTransfer.setData('text/plain', text);
    });

    // Ziel: Wochenzellen (TD / .wk-cell) droppable machen
    function attachDropTargets() {
      // Tabellenzellen (ohne Labelspalte)
      qsa('tbody tr').forEach(tr => {
        const cells = Array.from(tr.children);
        cells.forEach((td, idx) => {
          if (idx === 0) return; // Labelspalte überspringen
          td.addEventListener('dragover', ev => { ev.preventDefault(); td.classList.add('drop-hover'); });
          td.addEventListener('dragleave', () => td.classList.remove('drop-hover'));
          td.addEventListener('drop', ev => {
            ev.preventDefault(); td.classList.remove('drop-hover');
            const text = ev.dataTransfer.getData('text/plain');
            if (!text) return;
            const input = td.querySelector('input, textarea');
            if (input) {
              input.value = text;
              // Row/Day bestimmen und speichern
              const trEl = td.closest('tr');
              const cells2 = Array.from(trEl.children);
              const dayIdx = cells2.indexOf(td) - 1;      // 0=Label
              const rows = Array.from(trEl.parentElement.children);
              const rowIdx = rows.indexOf(trEl);
              postJSON('/api/week/set-cell', {
                year: state.year, kw: state.kw, standort: state.standort,
                row: rowIdx, day: dayIdx, value: text
              }).then(res => {
                if (!res.ok && !res.skipped) console.warn('[DnD set-cell] fehlgeschlagen', res);
              });
            }
          });
        });
      });

      // Grid (.wk-cell) – 0=Label, 1..5=Mo..Fr
      qsa('.wk-grid').forEach(grid => {
        const cells = qsa('.wk-cell', grid);
        const cols = 6;
        cells.forEach((cell, idx) => {
          const c = idx % cols;
          if (c === 0) return; // Labelspalte überspringen
          cell.addEventListener('dragover', ev => { ev.preventDefault(); cell.classList.add('drop-hover'); });
          cell.addEventListener('dragleave', () => cell.classList.remove('drop-hover'));
          cell.addEventListener('drop', ev => {
            ev.preventDefault(); cell.classList.remove('drop-hover');
            const text = ev.dataTransfer.getData('text/plain');
            if (!text) return;
            const input = cell.querySelector('input, textarea');
            if (input) {
              input.value = text;
              const all = qsa('.wk-cell', grid);
              const idx2 = all.indexOf(cell);
              const rowIdx = Math.floor(idx2 / cols);
              const dayIdx = (idx2 % cols) - 1;
              postJSON('/api/week/set-cell', {
                year: state.year, kw: state.kw, standort: state.standort,
                row: rowIdx, day: dayIdx, value: text
              }).then(res => {
                if (!res.ok && !res.skipped) console.warn('[DnD set-cell] fehlgeschlagen', res);
              });
            }
          });
        });
      });
    }
    // beim Laden einmal aktivieren
    attachDropTargets();
  }

  // 4‑Tage‑Toggle
  async function setFourDay(value) {
    const res = await postJSON('/api/week/set-four-day', {
      standort: state.standort, kw: state.kw, year: state.year, value: !!value
    });
    if (!res.ok) { console.warn('[set-four-day] fehlgeschlagen', res); return false; }
    state.fourDay = !!res.four_day_week;
    applyFridayDisabled(state.fourDay);
    return true;
  }
  if (ui.fourDayToggle) {
    ui.fourDayToggle.addEventListener('change', async (e) => {
      const desired = !!e.target.checked;
      const ok = await setFourDay(desired);
      if (!ok) e.target.checked = !desired;
    });
  }

  // Navigation
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

  window.__zankl_dbg = { ...state };
  console.log('[app.js] state', window.__zankl_dbg);
})();
