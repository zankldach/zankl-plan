
<!-- Pfad: static/app.js -->
<script>
/**
 * Zankl Plan – Frontend Logik (Kleinbaustellen + Drag&Drop + Save Hooks)
 * Austauschdatei Stand: 08.01.2026
 *
 * Features:
 * - Kleinbaustellen: Debounced Save beim Tippen + synchrones Save vor Navigation (keepalive/sendBeacon)
 * - Immer eine freie Zeile unten (auto-append)
 * - Entfernt Vorbesetzung "Kleinbaustelle..."
 * - Drag & Drop: von Kleinbaustellen in Wochenzellen (Grid) inkl. sofortigem Speichern
 *
 * Hinweise zur DOM-Struktur (flexible Fallbacks):
 * - Container der Kleinbaustellenliste: #klein-list ODER [data-section="klein"] ODER .kleinbaustellen
 * - Inputs in der Kleinliste: <input> oder <textarea> (egal); wir nehmen alles innerhalb des Containers
 * - Wochenzellen: Elemente mit data-row-index und data-day-index (empfohlen), andernfalls Fallback über Name-Muster
 * - Standort/KW/Jahr: aus Selects (#standort, #kw, #year) oder URL-Query
 */

(function () {
  // ---------------------------
  // Hilfsfunktionen / Kontext
  // ---------------------------
  function qs(selector) {
    return document.querySelector(selector);
  }
  function qsa(selector) {
    return Array.from(document.querySelectorAll(selector));
  }

  function getCtx() {
    const urlParams = new URLSearchParams(window.location.search);
    const standort =
      (qs('#standort') && qs('#standort').value) ||
      (qs('select[name="standort"]') && qs('select[name="standort"]').value) ||
      urlParams.get('standort') ||
      '';
    const kw =
      parseInt(
        (qs('#kw') && qs('#kw').value) ||
          (qs('select[name="kw"]') && qs('select[name="kw"]').value) ||
          urlParams.get('kw') ||
          '0',
        10
      ) || 0;
    const year =
      parseInt(
        (qs('#year') && qs('#year').value) ||
          (qs('select[name="year"]') && qs('select[name="year"]').value) ||
          urlParams.get('year') ||
          (new Date()).getFullYear().toString(),
        10
      ) || (new Date()).getFullYear();

    return { standort, kw, year };
  }

  // ---------------------------
  // Kleinbaustellen – DOM Hooks
  // ---------------------------
  const kleinListEl =
    qs('#klein-list') ||
    qs('[data-section="klein"]') ||
    qs('.kleinbaustellen');

  function kleinInputs() {
    if (!kleinListEl) return [];
    // Alle Eingabefelder innerhalb der Kleinbaustellen-Liste
    return Array.from(kleinListEl.querySelectorAll('input, textarea'));
  }

  // Entferne Vorbesetzung "Kleinbaustelle..."
  function clearDefaultKleinTexts() {
    kleinInputs().forEach((inp) => {
      const v = (inp.value || '').trim();
      if (/^kleinbaustelle/i.test(v)) {
        inp.value = '';
      }
    });
  }

  // Normalisierung: Nur gefüllte oben; immer EINE leere unten (DOM)
  function ensureTrailingEmptyRow() {
    if (!kleinListEl) return;
    const inputs = kleinInputs();
    const nonEmpty = inputs.filter((i) => (i.value || '').trim() !== '');
    const last = inputs[inputs.length - 1];

    // Falls es keine Inputs gibt (Template leer o.ä.), lege eins an
    if (inputs.length === 0) {
      appendKleinRow('');
      return;
    }

    // Wenn der letzte nicht leer ist, hänge eine freie Zeile an
    if (last && (last.value || '').trim() !== '') {
      appendKleinRow('');
    }

    // Optional: Entferne überzählige leere Zeilen (lasse nur eine leere am Ende)
    const empties = inputs.filter((i) => (i.value || '').trim() === '');
    if (empties.length > 1) {
      // Behalte nur die letzte leere; entferne die anderen
      empties.slice(0, empties.length - 1).forEach((i) => {
        // Nur entfernen, wenn kein Placeholder-Row aus Template
        if (i.parentElement && kleinListEl.contains(i.parentElement)) {
          i.parentElement.remove();
        } else {
          i.remove();
        }
      });
    }
  }

  // Eine neue Zeile in der Kleinliste anhängen (neutraler Stil)
  function appendKleinRow(initialText = '') {
    const row = document.createElement('div');
    row.className = 'klein-row'; // optional, falls CSS vorhanden

    // Drag-Handle (einfacher Text, funktioniert ohne CSS)
    const handle = document.createElement('span');
    handle.className = 'drag-handle';
    handle.textContent = '⋮⋮';
    handle.title = 'Ziehen zum Einfügen in Wochenraster';
    handle.style.cursor = 'grab';
    handle.draggable = true;

    const inp = document.createElement('input');
    inp.type = 'text';
    inp.className = 'klein-input form-control'; // form-control für Bootstrap-artigen Stil
    inp.placeholder = ''; // kein Vordruck
    inp.value = initialText;

    // Events
    inp.addEventListener('input', () => {
      scheduleSaveSmallJobs();
      ensureTrailingEmptyRow();
    });
    inp.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        // Enter: neue freie Zeile sicherstellen
        ensureTrailingEmptyRow();
        scheduleSaveSmallJobs();
        e.preventDefault();
      }
    });
    // Drag von der Zeile (Input oder Handle löst Drag aus)
    [handle, inp].forEach((draggableEl) => {
      draggableEl.addEventListener('dragstart', (ev) => {
        const text = (inp.value || '').trim();
        if (!text) {
          ev.preventDefault();
          return;
        }
        ev.dataTransfer.setData('text/plain', text);
        // optional: kleiner visueller Marker
        ev.dataTransfer.effectAllowed = 'copyMove';
      });
    });

    row.appendChild(handle);
    row.appendChild(inp);
    kleinListEl.appendChild(row);
  }

  // ---------------------------
  // Speichern der Kleinliste
  // ---------------------------
  let kleinSaveTimer = null;
  let pendingBeacon = false;

  function readKleinListNormalized() {
    const inputs = kleinInputs();
    const texts = inputs.map((i) => (i.value || '').trim());
    // Filter: nur gefüllte behalten, eine leere unten
    const filled = texts.filter((t) => t !== '');
    // Normalisierte Liste: gefüllte oben; leere unten
    return [...filled, ''];
  }

  async function saveSmallJobs({ keepalive = false } = {}) {
    const ctx = getCtx();
    if (!ctx.standort) {
      // Ohne Standort keine Speicherung
      return;
    }
    const normalized = readKleinListNormalized();
    const payload = {
      standort: ctx.standort,
      items: normalized.map((text, idx) => ({ row_index: idx, text })),
    };

    try {
      if (keepalive && navigator.sendBeacon) {
        // Fallback via sendBeacon (synchron bei Navigation)
        const blob = new Blob([JSON.stringify(payload)], {
          type: 'application/json',
        });
        pendingBeacon = navigator.sendBeacon('/api/klein/save-list', blob);
      } else {
        await fetch('/api/klein/save-list', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
          keepalive: keepalive, // für Chrome beim beforeunload
        });
      }
    } catch (e) {
      // Fehler bewusst leise, um Navigation nicht zu blockieren
      console.warn('Fehler beim Speichern der Kleinliste:', e);
    }
  }

  function scheduleSaveSmallJobs() {
    // Debounce 350ms
    if (kleinSaveTimer) clearTimeout(kleinSaveTimer);
    kleinSaveTimer = setTimeout(() => saveSmallJobs({ keepalive: false }), 350);
  }

  // Vor Navigation / Reload: synchron speichern
  window.addEventListener('beforeunload', () => {
    // Versuche, synchron zu senden
    saveSmallJobs({ keepalive: true });
  });

  // Zusätzlich: Wenn Standort/KW/Jahr geändert wird, sofort save + dann Navigation
  ['#standort', '#kw', '#year', 'select[name="standort"]', 'select[name="kw"]', 'select[name="year"]'].forEach((sel) => {
    const el = qs(sel);
    if (el) {
      el.addEventListener('change', () => {
        // sofort speichern (keepalive), Navigation kann durch Template erfolgen
        saveSmallJobs({ keepalive: true });
      });
    }
  });

  // ---------------------------
  // Drag & Drop in Wochenzellen
  // ---------------------------
  function weekCells() {
    // Bevorzugt mit data-Attributen; Fallback: typische Raster-Selektoren
    const withData = qsa('[data-day-index][data-row-index]');
    if (withData.length > 0) return withData;

    const gridInputs = qsa('.week-grid textarea, .week-grid input, table.week-grid textarea, table.week-grid input');
    return gridInputs.length > 0 ? gridInputs : qsa('textarea.week-cell, input.week-cell');
  }

  function parseRowDayFromEl(el) {
    // Erst data-Attribute probieren
    const row = parseInt(el.dataset.rowIndex || el.getAttribute('data-row-index') || '', 10);
    const day = parseInt(el.dataset.dayIndex || el.getAttribute('data-day-index') || '', 10);
    if (!Number.isNaN(row) && !Number.isNaN(day)) {
      return { rowIndex: row, dayIndex: day };
    }
    // Fallback über name="cell[rX][dY]" o.ä.
    const name = el.getAttribute('name') || '';
    const matchR = name.match(/r(\d+)/i);
    const matchD = name.match(/d(\d+)/i);
    const r = matchR ? parseInt(matchR[1], 10) : NaN;
    const d = matchD ? parseInt(matchD[1], 10) : NaN;
    if (!Number.isNaN(r) && !Number.isNaN(d)) {
      return { rowIndex: r, dayIndex: d };
    }
    // Not found
    return { rowIndex: null, dayIndex: null };
  }

  async function saveWeekCell(el, text) {
    const ctx = getCtx();
    const { rowIndex, dayIndex } = parseRowDayFromEl(el);
    if (rowIndex == null || dayIndex == null) return;

    const payload = {
      standort: ctx.standort,
      year: ctx.year,
      kw: ctx.kw,
      row_index: rowIndex,
      day_index: dayIndex,
      text: text,
    };
    try {
      const res = await fetch('/api/week/set-cell', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      // Server kann {ok:true, skipped:true} liefern (bei 4-Tage-Woche für Freitag)
      // Bei skipped machen wir nichts weiter.
    } catch (e) {
      console.warn('Fehler beim Speichern der Wochenzelle:', e);
    }
  }

  function initWeekDropTargets() {
    weekCells().forEach((cellEl) => {
      // Drop aktivieren
      cellEl.addEventListener('dragover', (ev) => {
        ev.preventDefault(); // nötig damit drop funktioniert
        ev.dataTransfer.dropEffect = 'copy';
      });
      cellEl.addEventListener('drop', (ev) => {
        ev.preventDefault();
        const text = ev.dataTransfer.getData('text/plain');
        if (!text) return;

        // Zelle befüllen (Input/textarea)
        if ('value' in cellEl) {
          cellEl.value = text;
        } else {
          cellEl.textContent = text;
        }
        // Sofort speichern
        saveWeekCell(cellEl, text);
      });

      // Optional: Direkte Eingabe in Zellen auch sofort speichern (Komfort)
      if ('addEventListener' in cellEl) {
        cellEl.addEventListener('input', () => {
          const val = 'value' in cellEl ? cellEl.value : (cellEl.textContent || '');
          // Debounce leichte Eingaben in Zellen
          if (cellEl.__cellTimer) clearTimeout(cellEl.__cellTimer);
          cellEl.__cellTimer = setTimeout(() => saveWeekCell(cellEl, val), 300);
        });
      }
    });
  }

  // ---------------------------
  // Initialisierung
  // ---------------------------
  function initKleinList() {
    if (!kleinListEl) return;

    clearDefaultKleinTexts();
    ensureTrailingEmptyRow();

    // Events an existierenden Inputs
    kleinInputs().forEach((inp) => {
      inp.addEventListener('input', () => {
        scheduleSaveSmallJobs();
        ensureTrailingEmptyRow();
      });
      inp.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
          ensureTrailingEmptyRow();
          scheduleSaveSmallJobs();
          e.preventDefault();
        }
      });
      // Input selbst als Drag-Quelle
      inp.draggable = true;
      inp.addEventListener('dragstart', (ev) => {
        const text = (inp.value || '').trim();
        if (!text) {
          ev.preventDefault();
          return;
        }
        ev.dataTransfer.setData('text/plain', text);
        ev.dataTransfer.effectAllowed = 'copyMove';
      });
    });

    // Optional: Button "Alles speichern" (falls vorhanden)
    const saveAllBtn = qs('#save-all-klein') || qs('[data-action="save-klein"]');
    if (saveAllBtn) {
      saveAllBtn.addEventListener('click', () => {
        saveSmallJobs();
      });
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    initKleinList();
    initWeekDropTargets();
  });
})();
</script>
