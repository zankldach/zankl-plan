
/* Zankl Plan – static/app.js (Austauschdatei)
 * Stand: 2026-01-09
 * Fixes: Persistenz Kleinbaustellen, trailing leere Zeile, Entfernen Default-Text,
 *        Drag & Drop von Sidebar in Wochenzellen.
 */

(function () {
  // ---------- Selektor-Helfer ----------
  const qs  = (sel) => document.querySelector(sel);
  const qsa = (sel) => Array.from(document.querySelectorAll(sel));

  // Robuste Selektoren (falls IDs/Klassen im Template variieren):
  const SEL = {
    // Sidebar-Container:
    kleinContainer:
      '#klein-container, .kleinbaustellen, [data-section="klein"], aside.klein, #klein',
    // Eingabe-Felder in der Sidebar (Inputs/Textareas):
    kleinInputs:
      '.klein-input, #klein-container input, #klein-container textarea, .kleinbaustellen input, .kleinbaustellen textarea',
    // Wochenzellen (Inputs/Textareas im Raster):
    weekCells:
      '.week-cell, #week-grid textarea, #week-grid input, table.week-grid textarea, table.week-grid input',
    // Navigations-/Kontextinputs:
    standort: '#standort, select[name="standort"]',
    year: '#year, select[name="year"]',
    kw: '#kw, select[name="kw"]',
    fourDayCheckbox: '#four-day-checkbox',
    saveAllBtn: '#saveAllBtn, button#saveAll, .save-all'
  };

  // ---------- Kontext (Standort/KW/Jahr) ----------
  function getCtx() {
    const u = new URLSearchParams(window.location.search);
    const standortEl = qs(SEL.standort);
    const yearEl     = qs(SEL.year);
    const kwEl       = qs(SEL.kw);

    return {
      standort: (standortEl?.value ?? u.get('standort') ?? '').trim(),
      year: parseInt((yearEl?.value ?? u.get('year') ?? new Date().getFullYear()), 10),
      kw: parseInt((kwEl?.value ?? u.get('kw') ?? 1), 10),
      fourDayWeek: !!qs(SEL.fourDayCheckbox)?.checked
    };
  }

  // ---------- Utils ----------
  function escapeHtml(s) {
    return (s ?? '').replace(/[&<>"']/g, (c) =>
      ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;', "'":'&#39;' }[c])
    );
  }

  // ---------- Kleinbaustellen: Logik ----------
  const smallJobs = (function () {
    const container = qs(SEL.kleinContainer);
    if (!container) return { init(){} }; // Wenn Sidebar nicht vorhanden, nix tun.

    const state = {
      saveTimer: null
    };

    function kleinInputNodes() {
      return qsa(SEL.kleinInputs).filter(el => container.contains(el));
    }

    // Default-Texte („Kleinbaustelle…“) entfernen
    function stripDefaults() {
      kleinInputNodes().forEach(i => {
        const v = (i.value || '').trim().toLowerCase();
        if (v.startsWith('kleinbaustelle')) i.value = '';
      });
    }

    // Liste aus DOM lesen
    function readListFromDOM() {
      return kleinInputNodes().map(i => (i.value || '').trim());
    }

    // Normalisieren: Nur nicht-leere Einträge, Reihenfolge stabil
    function normalize(list) {
      return list.map(t => t.trim()).filter(t => t.length > 0);
    }

    // Unten immer eine freie Zeile sicherstellen
    function ensureTrailingEmptyRow() {
      const inputs = kleinInputNodes();
      if (inputs.length === 0) { appendRow(''); return; }
      const last = inputs[inputs.length - 1];
      if ((last.value || '').trim().length > 0) appendRow('');
    }

    // Eine neue Zeile anhängen (optisch neutral)
    function appendRow(text) {
      const row = document.createElement('div');
      row.className = 'klein-row';
      row.innerHTML = `
        <button class="drag-handle" title="In Wochenzelle ziehen" draggable="true">⋮⋮</button>
        <input type="text" class="klein-input form-control" value="${escapeHtml(text)}" placeholder="" />
        <button class="clear-row" title="Zeile leeren">🗑</button>
      `;
      container.appendChild(row);
      bindRowEvents(row);
    }

    // Zeilen-Ereignisse binden
    function bindRowEvents(row) {
      const input   = row.querySelector('.klein-input');
      const handle  = row.querySelector('.drag-handle');
      const clearBtn= row.querySelector('.clear-row');

      input.addEventListener('input', () => {
        ensureTrailingEmptyRow();
        scheduleSave();
      });

      input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          ensureTrailingEmptyRow();
          scheduleSave();
          const inputs = kleinInputNodes();
          inputs[inputs.length - 1]?.focus();
        }
      });

      clearBtn.addEventListener('click', (e) => {
        e.preventDefault();
        input.value = '';
        scheduleSave();
      });

      // Drag vom Handle -> Text in Wochenzelle droppen
      handle.addEventListener('dragstart', (ev) => {
        const text = (input.value || '').trim();
        if (!text) { ev.preventDefault(); return; }
        ev.dataTransfer.setData('text/plain', text);
        ev.dataTransfer.effectAllowed = 'copy';
      });
    }

    function bindExistingRows() {
      // Bestehende Inputs: Defaults entfernen, Events setzen
      qsa(SEL.kleinInputs).forEach(i => {
        if (!container.contains(i)) return;
        const v = (i.value || '').trim();
        if (v.toLowerCase().includes('kleinbaustelle')) i.value = '';
        const row = i.closest('.klein-row') || i.parentElement;
        // Ergänze Handle/🗑 wenn nicht vorhanden
        if (!row.querySelector('.drag-handle')) {
          const btn = document.createElement('button');
          btn.className = 'drag-handle';
          btn.textContent = '⋮⋮';
          btn.title = 'In Wochenzelle ziehen';
          btn.setAttribute('draggable', 'true');
          row.insertBefore(btn, i);
        }
        if (!row.querySelector('.clear-row')) {
          const del = document.createElement('button');
          del.className = 'clear-row';
          del.textContent = '🗑';
          del.title = 'Zeile leeren';
          row.appendChild(del);
        }
        bindRowEvents(row);
      });
    }

    function scheduleSave() {
      clearTimeout(state.saveTimer);
      state.saveTimer = setTimeout(() => saveList(false), 400);
    }

    async function saveList(useBeacon) {
      const ctx = getCtx();
      const raw   = readListFromDOM();
      const items = normalize(raw);
      const body  = JSON.stringify({ standort: ctx.standort, items });

      // /api/klein/save-list: löscht für standort und setzt INSERT normalisiert
      if (useBeacon && navigator.sendBeacon) {
        const blob = new Blob([body], { type: 'application/json' });
        navigator.sendBeacon('/api/klein/save-list', blob);
        return;
      }

      try {
        await fetch('/api/klein/save-list', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body,
          keepalive: true
        });
      } catch (e) {
        console.warn('Save Kleinbaustellen fehlgeschlagen:', e);
      }
    }

    function init() {
      stripDefaults();
      bindExistingRows();
      ensureTrailingEmptyRow();

      // Vor Navigation (Wechsel KW/Jahr/Standort) synchron speichern
      window.addEventListener('beforeunload', () => saveList(true));

      // Optional: „Alles speichern“-Button falls vorhanden
      const saveBtn = qs(SEL.saveAllBtn);
      if (saveBtn) saveBtn.addEventListener('click', (e) => {
        e.preventDefault();
        saveList(false);
      });
    }

    return { init, saveList };
  })();

  // ---------- Wochenzellen: DnD Ziel + Live-Save ----------
  const weekGrid = (function () {
    function cellNodes() {
      return qsa(SEL.weekCells);
    }

    function getCellPosition(el) {
      // Versuche data-* zuerst (empfohlen!)
      const rowIdx = el.dataset.rowIndex || el.closest('[data-row-index]')?.dataset.rowIndex;
      const dayIdx = el.dataset.dayIndex || el.closest('[data-day-index]')?.dataset.dayIndex;
      if (rowIdx !== undefined && dayIdx !== undefined) {
        return { rowIndex: parseInt(rowIdx, 10), dayIndex: parseInt(dayIdx, 10) };
      }

      // Fallback: aus Tabellenstruktur ableiten (erste Spalte = Name, ab 1 -> Mo=0, Di=1, …)
      const td = el.closest('td') || el;
      const tr = el.closest('tr');
      const rowIndex = Array.from(tr?.parentElement?.children || []).indexOf(tr);
      const dayIndex = Array.from(tr?.children || []).indexOf(td) - 1;
      return { rowIndex, dayIndex };
    }

    async function saveCell(el) {
      const { rowIndex, dayIndex } = getCellPosition(el);
      const ctx = getCtx();
      const text = (el.value ?? el.textContent ?? '').trim();

      // Serverseitiger Freitag-Check (four_day_week): der Endpoint skippt Freitag, wenn aktiv.
      const body = JSON.stringify({
        standort: ctx.standort,
        year: ctx.year,
        kw: ctx.kw,
        row_index: rowIndex,
        day_index: dayIndex,
        text
      });

      try {
        const res = await fetch('/api/week/set-cell', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body
        });
        const j = await res.json().catch(() => ({}));
        if (j?.skipped) {
          // Optional: UI-Hinweis, dass Freitag bei 4‑Tage‑Woche gesperrt ist
          el.classList.add('friday-skipped');
          setTimeout(() => el.classList.remove('friday-skipped'), 1200);
        }
      } catch (e) {
        console.warn('Save Wochenzelle fehlgeschlagen:', e);
      }
    }

    function bindDnDTargets() {
      cellNodes().forEach(el => {
        el.addEventListener('dragover', (ev) => {
          ev.preventDefault();
          ev.dataTransfer.dropEffect = 'copy';
        });
        el.addEventListener('drop', (ev) => {
          ev.preventDefault();
          const text = (ev.dataTransfer.getData('text/plain') || '').trim();
          if (!text) return;
          if ('value' in el) el.value = text;
          else el.textContent = text;
          saveCell(el);
        });

        // Optional: direktes Tippen speichert live
        el.addEventListener('input', () => saveCell(el));
        el.addEventListener('blur',  () => saveCell(el));
      });
    }

    function init() {
      bindDnDTargets();
    }

    return { init, saveCell };
  })();

  // ---------- Init ----------
  document.addEventListener('DOMContentLoaded', () => {
    smallJobs.init();
    weekGrid.init();
  });
})();
