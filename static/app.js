// Live updates via Server-Sent Events: toast + refresh any [data-live] region on this page.
(function(){
  const box=document.getElementById('toasts');
  function toast(t){const d=document.createElement('div');d.className='toast';d.textContent=t;box.appendChild(d);setTimeout(()=>d.remove(),6000);}
  async function refresh(kind){
    const regions=[...document.querySelectorAll('[data-live]')].filter(el=>el.dataset.live.split(' ').includes(kind));
    if(!regions.length) return;
    const html=await (await fetch(location.href,{cache:'no-store'})).text();
    const doc=new DOMParser().parseFromString(html,'text/html');
    regions.forEach(el=>{const n=doc.getElementById(el.id); if(n) el.innerHTML=n.innerHTML;});
    const nav=doc.querySelector('.nav'); if(nav) document.querySelector('.nav').innerHTML=nav.innerHTML;
  }
  try{
    const es=new EventSource('/events');
    es.onmessage=e=>{const m=JSON.parse(e.data);toast(m.text);refresh(m.kind);};
  }catch(e){}
  // preview chosen file
  document.querySelectorAll('input[type=file][data-preview]').forEach(inp=>{
    inp.addEventListener('change',()=>{const img=document.getElementById(inp.dataset.preview);
      if(inp.files[0]){img.src=URL.createObjectURL(inp.files[0]);img.style.display='block';}});
  });
})();
