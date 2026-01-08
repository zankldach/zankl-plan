
// static/app.js — Austausch 2026-01-08 (Focus-Fix + Persistenz + DnD-Handle)
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
    kw:       toInt(getParam('kw', '1'), 1),
    year:     toInt(getParam('year', '2025'), 2025),
    fourDay:  false, // unten ermittelt
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

  // Eingaben zwangsweise freischalten
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

  // ---------- Kleinbaustellen: inkrementell + persistent + kein Focus-Trap ----------
  const cont = ui.sjContainer || qs('#sj-list') || qs('.wk-sidebar');
  if (cont) {
    // vorhandene Inputs sicher editierbar
    qsa('input, textarea', cont).forEach((inp, idx) => {
      inp.removeAttribute('disabled');
      inp.removeAttribute('readonly');
      inp.style.pointerEvents = 'auto';
      inp.classList.add('sj-input');
      if (!inp.dataset.rowIndex) inp.dataset.rowIndex = String(idx);
      if (inp.placeholder) inp.placeholder = ''; // keine sichtbaren Placeholder
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

    // Persistenz beim Tippen (debounced) – kein Neuaufbau → kein Focus-Verlust
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

    cont.addEventListener('input', (e) => {
      const el = e.target;
      if (!el.classList.contains('sj-input')) return;
      scheduleSaveDebounced();
    });

    // Geplanter nächster Fokus (für Click-Wechsel)
    let pendingFocusIndex = null;
    cont.addEventListener('pointerdown', (e) => {
      const targetInput = e.target.closest('.sj-input');
      if (targetInput) {
        pendingFocusIndex = parseInt(targetInput.dataset.rowIndex || '0', 10);
      }
    });
    cont.addEventListener('focusin', (e) => {
      const targetInput = e.target.closest('.sj-input');
      if (targetInput) {
        pendingFocusIndex = parseInt(targetInput.dataset.rowIndex || '0', 10);
      }
    });

    // Zusammenrücken nur auf ENTER (nicht auf blur/change)
    function compressAndRenderRespectNextFocus() {
      const items = normalize(readList());
      const listEl = qs('#sj-list', cont) || cont;

      // Neu aufbauen
      listEl.innerHTML = '';
      items.forEach((text, idx) => {
        const row  = document.createElement('div');
        row.className = 'sj-row';
        // Drag-Handle
        const handle = document.createElement('span');
        handle.className = 'sj-handle';
        handle.textContent = '⋮⋮';
        handle.title = 'Ziehen zum Einfügen ins Wochenplan';
        row.appendChild(handle);
        // Input
        const input = document.createElement('input');
        input.type = 'text';
        input.className = 'sj-input';
        input.dataset.rowIndex = String(idx);
        input.value = text;
        input.placeholder = '';
        row.appendChild(input);

        listEl.appendChild(row);
      });

      // Nächsten Fokus respektieren
      if (pendingFocusIndex != null) {
        const target = listEl.querySelector(`.sj-input[data-row-index="${pendingFocusIndex}"]`)
                      || listEl.querySelector('.sj-input:last-of-type');
        if (target) {
          target.focus();
        }
      }
      // Reset
      pendingFocusIndex = null;

      // Drag aktivieren (nur am Handle)
      enableSidebarDnD();
    }

    cont.addEventListener('keydown', (e) => {
      const el = e.target;
      if (!el.classList.contains('sj-input')) return;
      if (e.key === 'Enter') {
        e.preventDefault();
        compressAndRenderRespectNextFocus();
        scheduleSaveDebounced();
      }
    });

    // Vor dem Verlassen der Seite sicher speichern
    window.addEventListener('beforeunload', () => {
      const items = normalize(readList());
      navigator.sendBeacon?.('/api/klein/save-list', JSON.stringify({ standort: state.standort, items }));
    });

    // ---------- Drag & Drop mit Handle ----------
    function enableSidebarDnD() {
      // DragStart vom Handle: Text aus der zugehörigen Zeile übertragen
      qsa('.sj-row', cont).forEach(row => {
        const handle = row.querySelector('.sj-handle');
        const inp    = row.querySelector('.sj-input');
        if (!handle || !inp) return;

        handle.setAttribute('draggable', 'true');

        handle.addEventListener('dragstart', (e) => {
          const text = (inp.value || '').trim();
          if (!text) { e.preventDefault(); return; }
          e.dataTransfer.effectAllowed = 'copy';
          e.dataTransfer.setData('text/plain', text);
        });
      });

      // Ziel: Wochenzellen (TD / .wk-cell) droppable machen
      attachDropTargets();
    }

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

    // Beim ersten Laden die Drop-Ziele aktivieren
    enableSidebarDnD();
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

 
// --- Navigation: Standort / KW / Jahr ---
// 1) Helfer: aktuelle Small-Job-Liste lesen & normalisieren
function readSmallJobList(container) {
  const cont = container || document.querySelector('#sj-list') || document.querySelector('.wk-sidebar');
  if (!cont) return [];
  const inputs = Array.from(cont.querySelectorAll('.sj-input'));
  const items  = inputs.map(i => (i.value || '').trim());
  const filled = items.filter(t => t.length > 0);
  // genau eine leere unten
  filled.push('');
  return filled;
}

// 2) Vor Navigation speichern
async function saveSmallJobsBeforeNavigate() {
  try {
    const items = readSmallJobList(); // aus DOM holen
    const payload = { standort: state.standort, items };
    const res = await fetch('/api/klein/save-list', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      keepalive: true // erlaubt Background-Commit
    });
    const data = await res.json().catch(() => ({ ok: false }));
    if (!data.ok) console.warn('[navigate] Save-list fehlgeschlagen', data);
  } catch (err) {
    console.warn('[navigate] Save-list error', err);
  }
}

// 3) Navigieren – erst speichern, dann Redirect
async function navigate(newStandort, newKw, newYear) {
  await saveSmallJobsBeforeNavigate(); // <- WICHTIG
  const params = new URLSearchParams(location.search);
  params.set('standort', newStandort ?? state.standort);
  params.set('kw', String(newKw ?? state.kw));
  params.set('year', String(newYear ?? state.year));
  location.href = '/week?' + params.toString();
}

// 4) Events
if (ui.standort) ui.standort.addEventListener('change', e => navigate(e.target.value, null, null));
if (ui.kw)       ui.kw.addEventListener('change',     e => navigate(null, toInt(e.target.value, state.kw), null));
if (ui.year)     ui.year.addEventListener('change',   e => navigate(null, null, toInt(e.target.value, state.year)));

// 5) Zusätzlich beim Tab-/Fenster-Verlassen sicher speichern
window.addEventListener('beforeunload', () => {
  const items = readSmallJobList();
  // sendBeacon als Fallback – kein await
  try {
    navigator.sendBeacon('/api/klein/save-list', JSON.stringify({ standort: state.standort, items }));
  } catch (_) {}
});
