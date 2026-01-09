// static/app.js — CLEAN & STABIL
(function () {
  'use strict';
  console.log('[app.js] clean boot ✔');

  const qs  = (s, r=document)=>r.querySelector(s);
  const qsa = (s, r=document)=>Array.from(r.querySelectorAll(s));

  async function postJSON(url, data) {
    try {
      const r = await fetch(url, {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify(data),
        keepalive:true
      });
      return await r.json();
    } catch(e){
      console.warn('[POST]', url, e);
      return {ok:false};
    }
  }

  const getParam=(n,d)=>new URLSearchParams(location.search).get(n) ?? d;

  const state = {
    standort: getParam('standort','engelbrechts')
  };

  /* ================================
     Kleinbaustellen – NUR SIDEBAR
     ================================ */

  const cont = qs('#sj-list');
  if (!cont) return;

  let saveTimer = null;

  function scheduleSave(){
    clearTimeout(saveTimer);
    saveTimer = setTimeout(()=>{
      const items = qsa('.sj-input', cont)
        .map(i => (i.value || '').trim())
        .filter(Boolean);

      postJSON('/api/klein/save-list', {
        standort: state.standort,
        items
      });
    }, 400);
  }

  cont.addEventListener('input', e => {
    if (!e.target.classList.contains('sj-input')) return;
    scheduleSave();
  });

  /* ================================
     Drag START nur Sidebar → Week
     ================================ */
  qsa('.sj-input', cont).forEach(inp => {
    inp.setAttribute('draggable', 'true');
    inp.addEventListener('dragstart', e => {
      const text = (inp.value || '').trim();
      if (!text) {
        e.preventDefault();
        return;
      }
      e.dataTransfer.setData('text/plain', text); // ⚠️ NUR TEXT
      e.dataTransfer.effectAllowed = 'copy';
    });
  });

  /* ================================
     Navigation (Standort / KW / Jahr)
     ================================ */

  async function navigate(params){
    const items = qsa('.sj-input', cont)
      .map(i => (i.value || '').trim())
      .filter(Boolean);

    await postJSON('/api/klein/save-list', {
      standort: state.standort,
      items
    });

    location.href = '/week?' + new URLSearchParams(params).toString();
  }

  qs('#wk-standort')?.addEventListener('change', e =>
    navigate({ standort:e.target.value })
  );
  qs('#wk-kw')?.addEventListener('change', e =>
    navigate({ standort:state.standort, kw:e.target.value })
  );
  qs('#wk-year')?.addEventListener('change', e =>
    navigate({ standort:state.standort, year:e.target.value })
  );

})();
