
/* Zankl Plan – static/app.js (Sidebar Reset: per-Cell Save, Copy DnD)
 * Datum: 2026-01-09
 * Ziel: Kleinbaustellen wie Wochenraster behandeln (per Zelle speichern),
 *       standortweit gültig, robustes DnD (copy, keine Quelle leeren),
 *       immer eine freie Zeile unten, keine Default-"Kleinbaustelle..."-Werte.
 */

(function () {
  // ----------------- Helpers -----------------
  const qs  = (sel, root=document) => root.querySelector(sel);
  const qsa = (sel, root=document) => Array.from(root.querySelectorAll(sel));

  function getCtx() {
    const u = new URLSearchParams(window.location.search);
    const standort = (qs('#standort')?.value ?? qs('select[name="standort"]')?.value ?? u.get('standort') ?? '').trim();
    const year     = parseInt((qs('#year')?.value ?? qs('select[name="year"]')?.value ?? u.get('year') ?? new Date().getFullYear()), 10);
    const kw       = parseInt((qs('#kw')?.value   ?? qs('select[name="kw"]')?.value   ?? u.get('kw')   ?? 1), 10);
    return { standort, year, kw };
  }

  function debounce(fn, delay) {
    let t = null;
    return function (...args) {
      if (t) clearTimeout(t);
      t = setTimeout(() => fn.apply(this, args), delay);
    };
  }

  // ----------------- Kleinbaustellen (per Cell) -----------------
  const SmallJobs = (function () {
    const container =
      qs('#klein-container') ||
      qs('#klein-list') ||
      qs('.kleinbaustellen') ||
      qs('[data-section="klein"]') ||
      qs('aside.klein');

    if (!container) {
      console.warn('Sidebar (Kleinbaustellen) nicht gefunden.');
      return { init(){} };
    }

    function inputs() {
      // Alle Inputs/Textareas in der Sidebar
      return qsa('input, textarea', container);
    }

    function stripDefaults() {
      inputs().forEach(inp => {
        const v = (inp.value || '').trim().toLowerCase();
        if (v.startsWith('kleinbaustelle')) inp.value = '';
      });
    }

    function getRowIndex(inp) {
      // Bevorzugt: data-row-index
      const d = inp.getAttribute('data-row-index') ?? inp.dataset?.rowIndex;
      if (d != null) return parseInt(d, 10);
      // Fallback: Position im Container (nur sichtbare Inputs zählen)
      const list = inputs();
      return list.indexOf(inp);
    }

    async function saveCell(inp) {
      const ctx = getCtx();
      if (!ctx.standort) return;

      const payload = {
        standort: ctx.standort,
        row_index: getRowIndex(inp),
        text: (inp.value || '').trim()
      };

      // Primär: bestehender Endpunkt /api/klein/set (dein „Alt“-Endpoint mit ON CONFLICT)
      // Fallback: /api/klein/set-cell (falls du lieber so benennst)
      try {
        let res = await fetch('/api/klein/set', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        if (!res.ok) {
          // Fallback versuchen
          res = await fetch('/api/klein/set-cell', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
          });
        }
        // Res ignorieren; DB regelt via UPSERT/ON CONFLICT.
      } catch (e) {
        console.warn('Fehler beim Speichern einer Kleinbaustelle:', e);
      }
    }

    const debouncedSave = debounce(saveCell, 300);

    function appendEmptyRow() {
      const row = document.createElement('div');
      row.className = 'klein-row';
      // einfache Struktur mit Handle + Input
      row.innerHTML = `
        <span class="drag-handle" title="Ziehen zum Einfügen in Wochenzelle" draggable="true" style="cursor:grab;user-select:none;">⋮⋮</span>
        <input type="text" class="klein-input form-control" value="" placeholder="" />
      `;
      container.appendChild(row);
      bindRow(row);
    }

    function ensureTrailingEmpty() {
      const list = inputs();
      if (list.length === 0) { appendEmptyRow(); return; }
      const last = list[list.length - 1];
      if ((last.value || '').trim() !== '') appendEmptyRow();

      // Falls mehrere leere am Ende, reduziere auf 1
      const empties = list.filter(i => (i.value || '').trim() === '');
      if (empties.length > 1) {
        // behalte nur die letzte leere
        for (let i = 0; i < empties.length - 1; i++) {
          const r = empties[i].closest('.klein-row') || empties[i].parentElement;
          if (r && container.contains(r)) r.remove();
          else empties[i].remove();
        }
      }
      // data-row-index aktualisieren (damit serverseitig konsistent)
      qsa('.klein-input', container).forEach((inp, idx) => {
        inp.setAttribute('data-row-index', String(idx));
      });
    }

    function bindRow(row) {
      const inp = row.querySelector('input,textarea');
      const handle = row.querySelector('.drag-handle');

      // Eingabe -> per Zelle speichern
      inp.addEventListener('input', () => {
        ensureTrailingEmpty();
        debouncedSave(inp);
      });

      // Enter -> neue freie unten + speichern
      inp.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          ensureTrailingEmpty();
          debouncedSave(inp);
          const list = inputs();
          list[list.length - 1]?.focus();
        }
      });

      // Dragstart: wir kopieren den Text (Quelle bleibt!)
      const startDrag = (ev) => {
        const txt = (inp.value || '').trim();
        if (!txt) { ev.preventDefault(); return; }
        ev.dataTransfer.setData('text/plain', txt);
        ev.dataTransfer.effectAllowed = 'copy'; // wichtig: COPY statt MOVE
      };
      handle?.addEventListener('dragstart', startDrag);
      // auch direkt vom Input ziehen erlauben
      inp.setAttribute('draggable', 'true');
      inp.addEventListener('dragstart', startDrag);
    }

    function bindExisting() {
      const list = inputs();
      list.forEach(inp => {
        // Default-Werte bereinigen
        const v = (inp.value || '').trim().toLowerCase();
        if (v.startsWith('kleinbaustelle')) inp.value = '';

        // falls keine Row-Struktur, minimal ergänzen
        let row = inp.closest('.klein-row');
        if (!row) {
          row = document.createElement('div');
          row.className = 'klein-row';
          const handle = document.createElement('span');
          handle.className = 'drag-handle';
          handle.textContent = '⋮⋮';
          handle.title = 'Ziehen zum Einfügen in Wochenzelle';
          handle.setAttribute('draggable', 'true');
          handle.style.cursor = 'grab';
          inp.replaceWith(row);
          row.appendChild(handle);
          row.appendChild(inp);
        }
        bindRow(row);
      });
    }

    function init() {
      bindExisting();
      ensureTrailingEmpty();

      // Vor Navigation/Reload nichts Besonderes nötig,
      // da wir per Zelle direkt speichern.
    }

    return { init };
  })();

  // ----------------- Wochenraster: DnD Ziele + Live Save -----------------
  const WeekGrid = (function () {
    function weekCells() {
      // Bevorzugt data-Attribute für präzise Zuordnung
      const withData = qsa('[data-day-index][data-row-index]');
      if (withData.length) return withData;

      // Fallback: typische Klassen/Container
      const cands = qsa('.week-cell')
        .concat(qsa('#week-grid textarea, #week-grid input'))
        .concat(qsa('table.week-grid textarea, table.week-grid input'));
      return cands.length ? cands : qsa('textarea, input'); // sehr großzügig
    }

    function getCellPos(el) {
      // data-* (empfohlen)
      const r = el.getAttribute('data-row-index') ?? el.dataset?.rowIndex;
      const d = el.getAttribute('data-day-index') ?? el.dataset?.dayIndex;
      if (r != null && d != null) return { rowIndex: parseInt(r, 10), dayIndex: parseInt(d, 10) };

      // Tabellenfallback (erste Spalte = Namen/Teams, ab Spalte 1 = Mo=0 …)
      const td = el.closest('td') || el;
      const tr = el.closest('tr');
      const rowIndex = Array.from(tr?.parentElement?.children || []).indexOf(tr);
      const dayIndex = Array.from(tr?.children || []).indexOf(td) - 1;
      return { rowIndex, dayIndex };
    }

    async function saveWeekCell(el) {
      const { rowIndex, dayIndex } = getCellPos(el);
      const ctx = getCtx();
      const text = (el.value ?? el.textContent ?? '').trim();

      const payload = {
        standort: ctx.standort,
        year: ctx.year,
        kw: ctx.kw,
        row_index: rowIndex,
        day_index: dayIndex,
        text
      };

      try {
        await fetch('/api/week/set-cell', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
      } catch (e) {
        console.warn('Speichern Wochenzelle fehlgeschlagen:', e);
      }
    }

    function bindDnDTargets() {
      weekCells().forEach(el => {
        el.addEventListener('dragover', (ev) => {
          ev.preventDefault();
          ev.dataTransfer.dropEffect = 'copy';
        });
        el.addEventListener('drop', (ev) => {
          ev.preventDefault();
          const text = (ev.dataTransfer.getData('text/plain') || '').trim();
          if (!text) return;
          // Zelle befüllen – Quelle bleibt unverändert (COPY)
          if ('value' in el) el.value = text; else el.textContent = text;
          saveWeekCell(el);
        });

        // Komfort: direkte Eingabe speichert live (leicht gedrosselt)
        el.addEventListener('input', () => {
          clearTimeout(el.__cellTimer);
          el.__cellTimer = setTimeout(() => saveWeekCell(el), 250);
        });
        el.addEventListener('blur', () => saveWeekCell(el));
      });
    }

    function init() {
      bindDnDTargets();
    }

    return { init };
  })();

  // ----------------- Init -----------------
  document.addEventListener('DOMContentLoaded', () => {
    SmallJobs.init();
    WeekGrid.init();
  });
})();
``
