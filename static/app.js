// static/app.js — FINAL STABIL 2026-01-08
(function () {
  'use strict';
  console.log('[app.js] boot ✔');

  /* ---------------- Helpers ---------------- */
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
  const toInt=(v,d)=>Number.isFinite(+v)?+v:d;

  /* ---------------- State ---------------- */
  const state = {
    standort: getParam('standort','engelbrechts'),
    kw:   toInt(getParam('kw',1),1),
    year: toInt(getParam('year',2025),2025),
    fourDay:false
  };

  /* ---------------- 4-Tage-Woche ---------------- */
  const fourDayToggle =
    qs('#fourDayToggle') ||
    qs('input[name="four_day_week"]');

  function applyFriday(disabled){
    qsa('td,th').forEach(el=>{
      if (/fr/i.test(el.textContent||'')){
        el.classList.toggle('fri-disabled',disabled);
        const i=el.querySelector('input,textarea');
        if(i){ i.disabled=disabled; i.readOnly=disabled; }
      }
    });
  }

  if(fourDayToggle){
    state.fourDay=!!fourDayToggle.checked;
    applyFriday(state.fourDay);
    fourDayToggle.addEventListener('change',async e=>{
      const want=!!e.target.checked;
      const r=await postJSON('/api/week/set-four-day',{
        standort:state.standort,kw:state.kw,year:state.year,value:want
      });
      if(r.ok){
        state.fourDay=!!r.four_day_week;
        applyFriday(state.fourDay);
      }else{
        e.target.checked=!want;
      }
    });
  }

  /* ---------------- Week-Cells ---------------- */
  document.addEventListener('input',e=>{
    const el=e.target;
    if(!el.matches('input,textarea'))return;
    if(el.closest('.wk-sidebar'))return;

    const td=el.closest('td,.wk-cell');
    if(!td)return;

    const tr=td.closest('tr');
    let row,day;

    if(tr){
      row=[...tr.parentElement.children].indexOf(tr);
      day=[...tr.children].indexOf(td)-1;
    }else{
      const grid=td.closest('.wk-grid');
      const cells=qsa('.wk-cell',grid);
      const idx=cells.indexOf(td);
      row=Math.floor(idx/6);
      day=(idx%6)-1;
    }

    if(day<0 || (state.fourDay && day===4))return;

    postJSON('/api/week/set-cell',{
      standort:state.standort,
      kw:state.kw,
      year:state.year,
      row,day,
      value:String(el.value||'')
    });
  });

  /* ---------------- Kleinbaustellen ---------------- */
  const cont = qs('#sj-list') || qs('.wk-sidebar');
  if(!cont)return;

  const SJ_MAX=200;
  let smallJobState = [];

  function normalizeState(){
    smallJobState = smallJobState
      .map(t => (t||'').trim())
      .filter(t => t.length > 0)
      .slice(0, SJ_MAX);
    smallJobState.push('');
  }

  function render(){
    cont.innerHTML='';
    smallJobState.forEach((text,idx)=>{
      const row=document.createElement('div');
      row.className='sj-row';

      const handle=document.createElement('span');
      handle.className='sj-handle';
      handle.textContent='⋮⋮';
      handle.draggable=true;

      const inp=document.createElement('input');
      inp.className='sj-input';
      inp.value=text;
      inp.dataset.idx=idx;

      inp.addEventListener('input',()=>{
        smallJobState[idx]=inp.value;
        normalizeState();
        render();
        scheduleSave();
      });

      row.append(handle,inp);
      cont.appendChild(row);
    });
    enableDnD();
  }

  let saveTimer=null;
  function scheduleSave(){
    clearTimeout(saveTimer);
    saveTimer=setTimeout(()=>{
      postJSON('/api/klein/save-list',{
        standort:state.standort,
        items:smallJobState
      });
    },300);
  }

  // Initial State aus DOM übernehmen
  smallJobState = qsa('.sj-input',cont).map(i=>i.value||'');
  normalizeState();
  render();

  /* ---------------- Drag & Drop ---------------- */
  function enableDnD(){
    qsa('.sj-handle',cont).forEach(h=>{
      h.addEventListener('dragstart',e=>{
        const t=h.nextSibling.value.trim();
        if(!t){ e.preventDefault(); return; }
        e.dataTransfer.setData('text/plain',t);
        e.dataTransfer.effectAllowed='copy';
      });
    });

    qsa('td,.wk-cell').forEach(cell=>{
      cell.addEventListener('dragover',e=>e.preventDefault());
      cell.addEventListener('drop',e=>{
        e.preventDefault();
        const text = String(e.dataTransfer.getData('text/plain')||'');
        if(!text) return;

        const inp=cell.querySelector('input,textarea');
        if(!inp) return;

        inp.value=text;

        // Zielposition bestimmen
        const tr=cell.closest('tr');
        let row,day;

        if(tr){
          row=[...tr.parentElement.children].indexOf(tr);
          day=[...tr.children].indexOf(cell)-1;
        }else{
          const grid=cell.closest('.wk-grid');
          const cells=qsa('.wk-cell',grid);
          const idx=cells.indexOf(cell);
          row=Math.floor(idx/6);
          day=(idx%6)-1;
        }

        if(day<0 || (state.fourDay && day===4)) return;

        postJSON('/api/week/set-cell',{
          standort:state.standort,
          kw:state.kw,
          year:state.year,
          row,day,
          value:text
        });
      });
    });
  }

  /* ---------------- Navigation ---------------- */
  async function navigate(params){
    await postJSON('/api/klein/save-list',{
      standort:state.standort,
      items:smallJobState
    });
    location.href='/week?'+new URLSearchParams(params).toString();
  }

  qs('#wk-standort')?.addEventListener('change',e=>navigate({
    standort:e.target.value,kw:state.kw,year:state.year
  }));
  qs('#wk-kw')?.addEventListener('change',e=>navigate({
    standort:state.standort,kw:e.target.value,year:state.year
  }));
  qs('#wk-year')?.addEventListener('change',e=>navigate({
    standort:state.standort,kw:state.kw,year:e.target.value
  }));

})();
