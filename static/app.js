(() => {
  'use strict';
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
  const esc = (v = '') => String(v).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const ATTR_CODES = ['HP','DEF','ATK','AGI','MP','MAG','RES','LUC'];
  const state = { data:null, tab:'attributes', selectedAttr:'HP', site:'youtube', chart:null, chartSettings:{a:'HP',b:'',days:'30',group:'day'}, toastTimer:null, rewardInterval:null, rewardExternalWindow:null };
  const sites = {
    youtube:{title:'YouTube',url:'https://www.youtube.com',icon:'▶',desc:'Vídeos, aulas e conteúdos selecionados.'},
    wikipedia:{title:'Wikipedia',url:'https://pt.wikipedia.org/wiki/P%C3%A1gina_principal',icon:'◎',desc:'Pesquisa e leitura de conhecimento.'},
    webtoon:{title:'WEBTOON',url:'https://www.webtoons.com/pt/',icon:'▤',desc:'Leitura de quadrinhos e histórias.'},
    chatgpt:{title:'ChatGPT',url:'https://chatgpt.com/',icon:'✧',desc:'Ferramenta de estudo e conversa.'}
  };
  const DB_NAME='rpg-habitos-local-v2', DB_STORE='kv';
  let idbPromise=null, syncing=false, syncConflict=null;
  const rankThresholds=[['F',0],['E',60],['D',180],['C',420],['B',900],['A',1860],['S',3780]];
  function uuid(){return (crypto?.randomUUID?.()||`op-${Date.now()}-${Math.random().toString(16).slice(2)}`);}
  function openLocalDB(){
    if(!('indexedDB' in window))return Promise.resolve(null);
    if(!idbPromise)idbPromise=new Promise(resolve=>{const req=indexedDB.open(DB_NAME,1);req.onupgradeneeded=()=>{if(!req.result.objectStoreNames.contains(DB_STORE))req.result.createObjectStore(DB_STORE,{keyPath:'key'});};req.onsuccess=()=>resolve(req.result);req.onerror=()=>resolve(null);});
    return idbPromise;
  }
  async function localGet(key){const db=await openLocalDB();if(!db){try{return JSON.parse(localStorage.getItem(`rpg:${key}`)||'null')}catch{return null;}}return new Promise(resolve=>{const tx=db.transaction(DB_STORE,'readonly'),r=tx.objectStore(DB_STORE).get(key);r.onsuccess=()=>resolve(r.result?.value??null);r.onerror=()=>resolve(null);});}
  async function localSet(key,value){const db=await openLocalDB();if(!db){try{localStorage.setItem(`rpg:${key}`,JSON.stringify(value));}catch{}return;}return new Promise(resolve=>{const tx=db.transaction(DB_STORE,'readwrite');tx.objectStore(DB_STORE).put({key,value});tx.oncomplete=()=>resolve();tx.onerror=()=>resolve();});}
  let activeCacheUser=null;
  async function resolveCacheUser(){if(state.data?.player?.account_id){activeCacheUser=`account:${state.data.player.account_id}`;return activeCacheUser;}const accountId=document.body.dataset.accountId;if(accountId){activeCacheUser=`account:${accountId}`;return activeCacheUser;}if(activeCacheUser)return activeCacheUser;activeCacheUser=await localGet('active_user');return activeCacheUser;}
  async function getQueue(){const user=await resolveCacheUser();return (await localGet(user?`queue:${user}`:'queue'))||[];}
  async function setQueue(q){const user=await resolveCacheUser();await localSet(user?`queue:${user}`:'queue',q);updateConnectionStatus();}
  async function cacheState(data){if(data?.ok&&data?.player?.username){activeCacheUser=data.player.account_id?`account:${data.player.account_id}`:data.player.username;data.player._offline_evaluation_day=data.player._offline_evaluation_day||todayKey();await localSet('active_user',activeCacheUser);await localSet(`state:${activeCacheUser}`,data);}}
  async function cachedState(){const user=await resolveCacheUser();return user?await localGet(`state:${user}`):null;}
  function todayKey(){const parts=new Intl.DateTimeFormat('en-CA',{timeZone:'America/Bahia',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date());const v=Object.fromEntries(parts.map(p=>[p.type,p.value]));return `${v.year}-${v.month}-${v.day}`;}
  function updateConnectionStatus(){
    const el=$('#connection-status');if(!el)return;
    const offline=!navigator.onLine;el.classList.toggle('offline',offline);el.classList.toggle('online',!offline);el.classList.toggle('pending',syncing);
    const span=el.querySelector('span');if(span)span.textContent=offline?'OFFLINE':syncing?'SINCRONIZANDO':'ONLINE';
    const banner=$('#offline-banner');if(banner){banner.classList.toggle('hidden',!offline&&!syncConflict);banner.classList.toggle('has-conflict',!!syncConflict);banner.title=syncConflict?'Toque para revisar o conflito de sincronização':'';banner.textContent=syncConflict?'Há uma alteração aguardando sua decisão de sincronização — toque para revisar.':offline?'Modo offline: hábitos, registros e configurações salvos localmente. Dungeon e combate exigem conexão nesta versão.':'';}
  }
  function taskName(code){return state.data?.player?.task_mapping?.[code]||state.data?.player?.attributes?.find(a=>a.code===code)?.activity||code;}
  function updateLocalRank(attr){
    const xp=Math.max(0,Number(attr.xp)||0);let index=0;for(let i=0;i<rankThresholds.length;i++){if(xp>=rankThresholds[i][1])index=i;}
    const current=rankThresholds[index],next=rankThresholds[Math.min(index+1,rankThresholds.length-1)];attr.rank=current[0];attr.rank_index=index;attr.next_rank=index===6?null:next[0];attr.next_xp=index===6?null:next[1];attr.progress=index===6?100:Math.max(0,Math.min(100,Math.round((xp-current[1])/(next[1]-current[1])*100)));
  }
  function ensureLocalDay(data=state.data){
    const p=data?.player;if(!p)return;
    const today=todayKey();
    if(p._offline_evaluation_day!==today){
      p._offline_evaluation_day=today;p._offline_chapter_day=today;p._physical_today=false;p._study_today=false;
      p.today_xp=0;p.daily_reward_seconds=0;data.daily_evaluations={};
      (p.attributes||[]).forEach(a=>a.today_evaluation=null);
    }
  }
  function localXP(code,amount){
    const p=state.data.player, a=p.attributes.find(x=>x.code===code);if(!a)return;
    a.xp=Math.max(0,Number(a.xp)||0)+amount;updateLocalRank(a);
    for(const sk of state.data.skills||[]){const at=p.attributes.find(x=>x.code===sk.attr);sk.unlocked=!!at&&rankThresholds.findIndex(x=>x[0]===at.rank)>=rankThresholds.findIndex(x=>x[0]===sk.rank);}
  }
  async function addPending(url,method,body,operationId,kind='request'){
    const q=await getQueue();q.push({url,method,body,operationId,kind,createdAt:new Date().toISOString()});await setQueue(q);
  }
  async function offlineMutation(url,method,body,operationId){
    const d=state.data;if(!d?.player)throw new Error('Este dispositivo ainda não tem um estado salvo. Conecte-se uma vez antes de jogar offline.');
    ensureLocalDay(d);const p=d.player, path=url.split('?')[0];let message='Alteração salva neste dispositivo. Será sincronizada quando a conexão voltar.';
    if(path==='/api/evaluations'&&method==='POST'){
      const code=String(body.attribute||''),score=Number(body.score),a=p.attributes.find(x=>x.code===code),day=body.day||todayKey();
      // Reset the local view when the Bahia calendar day changes, without deleting queued operations from prior days.
      if(p._offline_evaluation_day!==day){p._offline_evaluation_day=day;p._offline_chapter_day=day;p._physical_today=false;p._study_today=false;p.today_xp=0;p.daily_reward_seconds=0;d.daily_evaluations={};p.attributes.forEach(x=>x.today_evaluation=null);}
      if(!a||![0,3,6,9].includes(score))throw new Error('Avaliação inválida.');
      if(a.today_evaluation||d.daily_evaluations?.[code])throw new Error('Este atributo já foi avaliado hoje neste dispositivo.');
      body.day=day;const gained=(p.class?.dominant===code?score*2:score);let bonus=0;
      if(p.active_relic_id==='manto_heroi_esquecido'&&(p.relics_owned||[]).some(r=>r.id==='manto_heroi_esquecido')&&gained>0){const total=(p.manto_xp_remainder||0)+gained;bonus=Math.floor(total/10);p.manto_xp_remainder=total%10;}
      localXP(code,gained+bonus);a.today_evaluation={score,xp:gained+bonus};d.daily_evaluations=d.daily_evaluations||{};d.daily_evaluations[code]={score,xp:gained+bonus};p.today_xp=(p.today_xp||0)+gained+bonus;
      if(score>0&&day===todayKey())p.daily_reward_seconds=Math.min(1200,(p.daily_reward_seconds||0)+150);
      message=`Avaliação salva offline: +${gained} XP${bonus?` e +${bonus} XP do Manto`:''}.`;
    }else if(path==='/api/activities'&&method==='POST'){
      const clientRef=`local-${uuid()}`;body.client_ref=clientRef;
      const record={id:clientRef,client_ref:clientRef,attribute:body.attribute,title:String(body.title||'').trim(),value:body.value===''||body.value==null?null:Number(body.value),note:String(body.note||'').trim(),created_at:new Date().toISOString().slice(0,16)};
      if(!record.title)throw new Error('Informe a descrição do registro.');d.activities.unshift(record);message='Registro criado offline; edição e exclusão também serão sincronizadas.';
    }else if(path.startsWith('/api/activities/')&&(method==='PUT'||method==='DELETE')){
      const id=decodeURIComponent(path.split('/').pop()),index=(d.activities||[]).findIndex(a=>String(a.id)===id||String(a.client_ref)===id);
      if(index<0)throw new Error('Registro local não encontrado.');
      if(method==='DELETE'){d.activities.splice(index,1);message='Registro excluído localmente; exclusão pendente de sincronização.';}
      else{const r=d.activities[index];r.title=String(body.title||r.title);r.value=body.value===''||body.value==null?null:Number(body.value);r.note=String(body.note||'');message='Registro atualizado offline; alteração pendente de sincronização.';}
    }else if(path==='/api/tasks'&&method==='POST'){
      const mapping=body.mapping||{};const names=Object.values(mapping).map(x=>String(x||'').trim().toLocaleLowerCase());if(names.some(x=>!x)||names.length!==8||new Set(names).size!==8)throw new Error('Use oito tarefas diferentes e não vazias.');
      body.base_version=Number(p.task_mapping_version||0);p.task_mapping_version=body.base_version+1;p.task_mapping={...p.task_mapping,...mapping};p.attributes.forEach(a=>a.activity=p.task_mapping[a.code]||a.activity);message='Tarefas atualizadas offline.';
    }else if(path==='/api/shop/buy'&&method==='POST'){
      const catalog={pocao_cura:30,pocao_mana:30,bracelete_salvacao:500,ticket_dungeon:600,minute:1000,manto_heroi_esquecido:2500,anel_investidor_nato:1500,pingente_deusa_amor:500};const id=body.item_id,price=catalog[id];if(price==null)throw new Error('Item desconhecido.');if(p.coins<price)throw new Error('Moedas insuficientes.');
      const owned=(p.relics_owned||[]).map(r=>r.id);if(['manto_heroi_esquecido','anel_investidor_nato'].includes(id)&&owned.includes(id))throw new Error('Você já possui esta relíquia permanente.');p.coins-=price;
      if(id==='minute')p.special_reward_seconds=(p.special_reward_seconds||0)+60;
      else if(id==='manto_heroi_esquecido'||id==='anel_investidor_nato'){p.relics_owned=[...(p.relics_owned||[]),{id,...({manto_heroi_esquecido:{name:'Manto do Herói Esquecido',icon:'🧥'},anel_investidor_nato:{name:'Anel do Investidor Nato',icon:'💍'}}[id]),price,kind:'passive'}];p.inventory.relics=p.relics_owned;if(!p.active_relic_id)p.active_relic_id=id;}
      else if(id==='pingente_deusa_amor'){p.inventory.pingente_deusa_amor=(p.inventory.pingente_deusa_amor||0)+1;}
      else if(['pocao_cura','pocao_mana'].includes(id)){const it=p.inventory.consumables.find(x=>x.id===id);if(it)it.quantity++;}
      else p.inventory[id]=(p.inventory[id]||0)+1;message=`Compra salva offline: ${id}.`;
    }else if(path==='/api/relics/activate'&&method==='POST'){
      const id=body.relic_id;if(!['manto_heroi_esquecido','anel_investidor_nato'].includes(id)||(p.relics_owned||[]).every(r=>r.id!==id))throw new Error('Você não possui essa relíquia passiva.');if(body.base_active_relic_id!==undefined&&body.base_active_relic_id!==(p.active_relic_id||null))throw new Error('Outra sessão pode ter alterado a relíquia ativa; sincronize antes de tentar novamente.');p.active_relic_id=id;message=`${id==='manto_heroi_esquecido'?'Manto do Herói Esquecido':'Anel do Investidor Nato'} ativado offline.`;
    }else if(path==='/api/relics/sell-time'&&method==='POST'){
      if(p.active_relic_id!=='anel_investidor_nato'||!(p.relics_owned||[]).some(r=>r.id==='anel_investidor_nato'))throw new Error('Ative o Anel do Investidor Nato para converter tempo em moedas.');const seconds=Math.floor(Number(body.seconds)||0);if(seconds<=0||seconds>(p.daily_reward_seconds||0))throw new Error('Informe um valor válido dentro do saldo diário.');p.daily_reward_seconds-=seconds;p.coins+=seconds;message=`Convertidos ${seconds} segundos em ${seconds} moedas offline.`;
    }else if(path==='/api/relics/transfer'&&method==='POST'){
      if((p.inventory.pingente_deusa_amor||0)<=0)throw new Error('Você não possui o Pingente da Deusa do Amor.');const src=p.attributes.find(a=>a.code===body.source),dst=p.attributes.find(a=>a.code===body.target);if(!src||!dst||src===dst||src.xp<10)throw new Error('Selecione atributos diferentes; a origem precisa de pelo menos 10 XP.');src.xp-=10;dst.xp+=10;updateLocalRank(src);updateLocalRank(dst);p.inventory.pingente_deusa_amor--;message=`10 XP transferidos de ${src.code} para ${dst.code}.`;
    }else if(path==='/api/rewards/session'&&method==='POST'){
      p.reward_session_active=!!body.active;p._offlineRewardTick=Date.now();message=body.active?'Cronômetro local iniciado.':'Cronômetro local pausado.';
    }else if(path==='/api/rewards/tick'&&method==='POST'){
      const now=Date.now(),last=Number(p._offlineRewardTick)||now;let elapsed=Math.max(0,Math.floor((now-last)/1000));if(elapsed>0&&p.reward_session_active){const daily=Math.min(elapsed,p.daily_reward_seconds||0);p.daily_reward_seconds=Math.max(0,(p.daily_reward_seconds||0)-daily);elapsed-=daily;p.special_reward_seconds=Math.max(0,(p.special_reward_seconds||0)-elapsed);}p._offlineRewardTick=now;await cacheState(d);return {ok:true,daily:p.daily_reward_seconds,special:p.special_reward_seconds,active:!!p.reward_session_active};
    }else if(path==='/api/equipment/equip'&&method==='POST'){
      if(d.dungeon)throw new Error('Não é possível trocar equipamentos durante uma dungeon.');const itemId=body.item_id;if(!p.inventory.equipment)throw new Error('Inventário indisponível.');if(!p.equipped)p.equipped={};if(!itemId){delete p.equipped[body.attribute];}else{const it=p.inventory.equipment.find(x=>x.id===itemId);if(!it||it.quantity<=0)throw new Error('Equipamento não obtido.');p.equipped[it.attr]=itemId;}p.inventory.equipment.forEach(it=>it.equipped=Object.values(p.equipped).includes(it.id));message='Equipamento alterado offline.';
    }else if(path==='/api/items/use'&&method==='POST'){
      if(d.dungeon?.combat)throw new Error('Durante o combate, poções são uma ação de turno e exigem conexão nesta versão.');const id=body.item_id, it=p.inventory.consumables.find(x=>x.id===id);if(!it||it.quantity<=0)throw new Error('Poção indisponível.');if(id==='pocao_cura'){const n=Math.min(8,p.hp_max-p.hp);if(n<=0)throw new Error('HP já está cheio.');p.hp+=n;}else{const n=Math.min(6,p.mp_max-p.mp);if(n<=0)throw new Error('MP já está cheio.');p.mp+=n;}it.quantity--;message='Poção usada offline.';
    }else if(path==='/api/charts'){
      return {ok:true,data:[]};
    }else{
      throw new Error('Esta ação exige conexão nesta versão. A ação não foi alterada nem colocada na fila.');
    }
    await addPending(url,method,body,operationId);
    await cacheState(d);updateConnectionStatus();
    return {ok:true,message,state:d,offline:true};
  }
  async function syncQueuedOperations(){
    if(syncing||!navigator.onLine||syncConflict)return;await resolveCacheUser();let q=await getQueue();if(!q.length){updateConnectionStatus();return;}syncing=true;updateConnectionStatus();
    try{
      while(q.length&&navigator.onLine){const op=q[0];let response,data;
        try{response=await fetch(op.url,{method:op.method,headers:{'Content-Type':'application/json','X-Operation-ID':op.operationId},body:op.method==='GET'?undefined:JSON.stringify(op.body||{}),credentials:'same-origin'});data=await response.json();}
        catch{break;}
        if(response.status===401){break;}
        if(!response.ok||data.ok===false){syncConflict={op,error:data.error||'O servidor recusou uma alteração local.',server:data};const taskConflict=op.url==='/api/tasks'&&data.conflict;const relicConflict=op.url==='/api/relics/activate'&&data.conflict;const evalConflict=op.url==='/api/evaluations'&&data.conflict_type==='daily_evaluation';$('#sync-conflict-message').textContent=taskConflict?`Outro dispositivo salvou tarefas diferentes. Se escolher suas alterações locais, elas substituirão a configuração concorrente; se escolher a versão do servidor, a fila local será descartada.`:relicConflict?`Outro dispositivo ativou uma relíquia diferente. Você pode ativar a relíquia escolhida neste dispositivo ou manter a escolha atual do servidor.`:evalConflict?`O atributo ${data.server_evaluation?.attribute||''} já tem uma avaliação no dia ${data.server_evaluation?.day||''} no servidor. Não é seguro conceder XP duas vezes. Você pode manter o registro já confirmado no servidor ou adiar a decisão; a avaliação deste dispositivo não será sincronizada enquanto o conflito estiver pendente.`:`A operação “${op.url}” não foi sincronizada: ${syncConflict.error} Você pode manter a alteração pendente ou descartá-la do dispositivo.`;$('#sync-retry').textContent=taskConflict?'Usar tarefas deste dispositivo':relicConflict?'Ativar esta relíquia':evalConflict?'Usar avaliação do servidor':'Adiar e tentar depois';$('#sync-discard').textContent=(taskConflict||relicConflict||evalConflict)?(evalConflict?'Adiar decisão':'Manter versão do servidor'):'Descartar esta alteração local';$('#sync-conflict-modal').classList.remove('hidden');break;}
        const confirmedState=data.state||null;
        q.shift();await setQueue(q);
        // Keep the optimistic local view while other queued operations remain. The final server response
        // is authoritative after the queue drains; this avoids hiding unsynced work on an intermediate response.
        if(!q.length&&confirmedState){state.data=confirmedState;await cacheState(confirmedState);topbar();render();}
      }
    }finally{syncing=false;updateConnectionStatus();if(!syncConflict&&state.data)render();}
  }
  function toast(message, error=false) {
    const el=$('#toast'); if(!el) return;
    el.textContent=message; el.classList.toggle('error',error); el.classList.add('show');
    clearTimeout(state.toastTimer); state.toastTimer=setTimeout(()=>el.classList.remove('show'),3500);
  }
  async function api(url, options={}) {
    const method=(options.method||'GET').toUpperCase(),headers={...(options.headers||{})};
    let body=options.body;
    if(body&&typeof body!=='string'){headers['Content-Type']='application/json';body=JSON.stringify(body);}
    const parsedBody=typeof body==='string'&&body?(()=>{try{return JSON.parse(body)}catch{return {}}})():{};
    const operationId=method==='GET'?null:uuid();if(operationId)headers['X-Operation-ID']=operationId;
    if(!navigator.onLine){
      if(method==='GET'&&url.split('?')[0]==='/api/state'){const cache=await cachedState();if(cache){state.data=cache;return cache;}throw new Error('Abra o jogo uma vez com internet para preparar os dados offline.');}
      if(method==='GET'&&url.startsWith('/api/charts'))return {ok:true,data:[]};
      return await offlineMutation(url,method,parsedBody,operationId);
    }
    let res,data;
    try{res=await fetch(url,{...options,method,body,headers,credentials:'same-origin'});data=await res.json();}
    catch(error){
      if(method==='GET'&&url.split('?')[0]==='/api/state'){const cache=await cachedState();if(cache){state.data=cache;return cache;}}
      if(method!=='GET')return await offlineMutation(url,method,parsedBody,operationId);
      throw new Error('Falha de conexão.');
    }
    if(res.status===401){location.href='/';throw new Error('Sua sessão expirou. Entre novamente.');}
    if(!res.ok||data.ok===false){const error=new Error(data.error||'Não foi possível concluir a ação.');error.status=res.status;error.data=data;throw error;}
    if(data.state)state.data=data.state;
    if(data.ok&&data.player)state.data=data;
    if(data.state)await cacheState(data.state);else if(data.ok&&data.player)await cacheState(data);
    return data;
  }
  function rankColor(rank){return ({F:'#969ca9',E:'#7ed4be',D:'#75b6fb',C:'#ba9aff',B:'#ecb95d',A:'#ff8a6a',S:'#ff6879'})[rank]||'#ff6879';}
  function fmtTime(sec){sec=Math.max(0,Math.floor(Number(sec)||0));return `${String(Math.floor(sec/60)).padStart(2,'0')}:${String(sec%60).padStart(2,'0')}`;}
  function humanDuration(sec){sec=Math.max(0,Math.floor(Number(sec)||0));return `${Math.floor(sec/60)}m ${String(sec%60).padStart(2,'0')}s`;}
  function topbar(){
    const p=state.data?.player;if(!p)return;
    $('#top-hp').textContent=`${p.hp} / ${p.hp_max}`;$('#top-mp').textContent=`${p.mp} / ${p.mp_max}`;$('#top-coins').textContent=Number(p.coins).toLocaleString('pt-BR');
    $('#top-hp-bar').style.width=`${Math.max(0,Math.min(100,p.hp/p.hp_max*100))}%`;
    $('#top-mp-bar').style.width=`${Math.max(0,Math.min(100,p.mp/p.mp_max*100))}%`;
    $('#dungeon-nav-dot').classList.toggle('hidden',!state.data.dungeon);const admin=$('#admin-link');if(admin)admin.classList.toggle('hidden',!p.is_admin);const avatar=$('#class-avatar');if(avatar&&p.class)avatar.innerHTML=`<img class="avatar-img" src="${esc(p.class.sprite_url)}" alt="${esc(p.class.name)}">`;
  }
  async function refresh(keepScroll=true){
    const scroll=window.scrollY;
    try{const d=await api('/api/state');state.data=d;topbar();render();if(keepScroll)window.scrollTo({top:scroll,behavior:'instant'});}catch(e){toast(e.message,true);}
  }
  function setTab(tab){state.tab=tab;$$('.nav-link').forEach(b=>b.classList.toggle('active',b.dataset.tab===tab));render();window.scrollTo({top:0,behavior:'smooth'});}
  function render(){
    if(!state.data)return;
    topbar();updateConnectionStatus();
    const root=$('#main-content');
    if(state.tab==='attributes')root.innerHTML=renderAttributes();
    else if(state.tab==='dungeon')root.innerHTML=renderDungeon();
    else if(state.tab==='dashboard')root.innerHTML=renderDashboard();
    else if(state.tab==='shop')root.innerHTML=renderShop();
    else root.innerHTML=renderRewards();
    bindPageEvents();
    if(state.tab==='dashboard')loadChart();
  }
  function renderHeading(title,subtitle,extra=''){
    return `<div class="page-heading"><div><p class="eyebrow">SISTEMA DE PROGRESSÃO</p><h1>${title}</h1><p>${subtitle}</p></div><div class="heading-right">${extra}</div></div>`;
  }
  function renderAttributeRail(p){
    return `<aside class="card attribute-rail"><div class="attribute-rail-head"><strong>Seus atributos</strong><small>8 trilhas · progressão independente</small></div>${p.attributes.map(a=>`<button class="attribute-select ${state.selectedAttr===a.code?'active':''}" data-attribute="${a.code}"><span class="attr-icon">${esc(a.icon)}</span><span class="attr-meta"><strong>${esc(a.name)}</strong><small>${esc(a.activity)} · ${a.xp} XP</small></span><span class="attr-rank">${a.rank}</span></button>`).join('')}</aside>`;
  }
  function renderAttributes(){
    const p=state.data.player;const a=p.attributes.find(x=>x.code===state.selectedAttr)||p.attributes[0];
    const done=a.today_evaluation;const skills=state.data.skills.filter(s=>s.attr===a.code);
    const activities=state.data.activities.filter(x=>x.attribute===a.code);
    const inv=p.inventory;const potions=inv.consumables;
    const statValue=a.code==='HP'?`${p.hp_max}`:a.code==='MP'?`${p.mp_max}`:p.stats[a.code]??a.rank_index+1;
    const skillHtml=skills.map(s=>`<article class="skill-card ${s.unlocked?'':'locked'}"><div class="skill-top"><span class="skill-rank" style="color:${rankColor(s.rank)};border-color:${rankColor(s.rank)}55">${s.rank}</span><strong>${esc(s.name)}</strong><span class="skill-type">${s.kind==='active'?'ATIVA':'PASSIVA'}</span></div><p>${s.unlocked?'':`🔒 Desbloqueia em ${s.rank} · `}${esc(s.desc)}</p></article>`).join('');
    const evaluation=done?`<div class="eval-complete">✓ Autoavaliação concluída hoje: ${done.xp} XP. Você só pode avaliar este atributo uma vez por dia.</div>`:`<div class="eval-buttons">${[{s:0,t:'Não fiz',d:'0 XP'},{s:3,t:'Fácil',d:'+3 XP'},{s:6,t:'Médio',d:'+6 XP'},{s:9,t:'Difícil',d:'+9 XP'}].map(o=>`<button class="eval-option" data-eval="${o.s}" data-code="${a.code}"><strong>${o.s}</strong><span>${o.t}</span><small>${p.class?.dominant===a.code?`+${o.s*2} XP`:`${o.d}`}</small></button>`).join('')}</div><p class="muted" style="font-size:10px;margin:10px 0 0">0 XP conta como avaliação feita. Máximo teórico: 81 XP por dia com o bônus de classe.</p>`;
    const records=activities.length?activities.map(r=>`<article class="activity-row"><span class="activity-mark">↗</span><div class="activity-copy"><strong>${esc(r.title)}</strong>${r.note?`<p>${esc(r.note)}</p>`:''}<time>${esc(r.created_at.replace('T',' '))}</time></div>${r.value!==null&&r.value!==undefined?`<span class="activity-value">${esc(r.value)}</span>`:''}<div class="activity-actions"><button class="tiny-icon" title="Editar" data-edit-activity="${r.id}">✎</button><button class="tiny-icon" title="Excluir" data-delete-activity="${r.id}">×</button></div></article>`).join(''):`<div class="empty-state"><strong>Nenhum registro ainda.</strong>Use o formulário para registrar uma atividade ou medida. Isso não concede XP.</div>`;
    const equipment=inv.equipment;
    return `${renderHeading('Atributos','Transforme hábitos reais em progressão persistente.',`<span class="badge red">${p.today_xp} XP HOJE</span><span class="badge">F → S</span>`)}
      <div class="class-identity"><span class="avatar">${p.class?.sprite_url?`<img class="avatar-img" src="${esc(p.class.sprite_url)}" alt="">`:esc(p.class?.sprite||'◇')}</span><div><strong>${esc(p.class?.name||'Classe')}</strong><small>Dominante: ${esc(p.class?.dominant||'—')} · XP ×2 nesta trilha</small></div></div>
      <div class="grid grid-4" style="margin-bottom:16px">
        <div class="card stat-card"><div class="label">Vida atual</div><div class="stat-value" style="color:#ff7384">${p.hp}<span style="font-size:16px;color:#858b9a"> / ${p.hp_max}</span></div><div class="progress"><span style="width:${p.hp/p.hp_max*100}%"></span></div></div>
        <div class="card stat-card"><div class="label">Mana atual</div><div class="stat-value" style="color:#b8a1ff">${p.mp}<span style="font-size:16px;color:#858b9a"> / ${p.mp_max}</span></div><div class="progress purple"><span style="width:${p.mp/p.mp_max*100}%"></span></div></div>
        <div class="card stat-card"><div class="label">Moedas</div><div class="stat-value" style="color:#f1ca73">${Number(p.coins).toLocaleString('pt-BR')}</div><div class="stat-sub">Moedas persistem após derrota.</div></div>
        <div class="card stat-card"><div class="label">Dungeon nesta semana</div><div class="stat-value">${p.weekly_dungeons}<span style="font-size:17px;color:#858b9a"> / ${p.weekly_limit}</span></div><div class="stat-sub">Limite móvel de 7 dias.</div></div>
      </div>
      <div class="attribute-layout">${renderAttributeRail(p)}<section class="card attribute-detail">
        <div class="attribute-hero"><span class="attr-icon">${esc(a.icon)}</span><div><p class="eyebrow">${esc(a.activity)}</p><h2>${esc(a.name)}</h2><p>Seu rank evolui independentemente dos outros atributos.</p></div><div class="rank-pill"><strong>${a.rank}</strong><small>RANK ATUAL</small></div></div>
        <div class="attribute-progress"><div class="xp-line"><span>XP ACUMULADO</span><strong>${a.xp} XP ${a.next_rank?`/ ${a.next_xp} XP`:''}</strong></div><div class="progress"><span style="width:${a.progress}%"></span></div><div class="xp-line" style="margin-top:7px"><span>${a.rank==='S'?'RANK MÁXIMO ALCANÇADO':`Próximo rank: ${a.next_rank}`}</span><span>${a.progress}%</span></div></div>
        <div class="eval-panel"><div class="card-head"><div><h3>Autoavaliação diária</h3><p>Registre como foi cumprir esta atividade hoje.</p></div><span class="badge">1× / DIA</span></div>${evaluation}</div>
      </section></div>
      <div class="below-grid">
        <section class="card content-card"><div class="card-head"><div><h2>Registro de atividade</h2><p>Texto + número são apenas anotações; não concedem XP.</p></div></div>
          <form id="activity-form" data-activity-attr="${a.code}"><div class="form-control"><label for="activity-title">Descrição</label><input id="activity-title" name="title" class="input" maxlength="160" placeholder="Ex.: 3 séries de flexões" required></div><div class="field-row" style="margin-top:11px"><div class="form-control"><label for="activity-note">Observação (opcional)</label><textarea id="activity-note" name="note" maxlength="600" placeholder="Como foi? Alguma observação..."></textarea></div><div class="form-control"><label for="activity-value">Número (opcional)</label><input id="activity-value" name="value" class="input" type="number" step="any" placeholder="Ex.: 12,5"></div></div><button type="submit" class="primary" style="margin-top:12px">＋ Salvar registro</button></form>
          <div class="sub-section"><div class="sub-section-title"><h3>Histórico recente</h3><span class="badge">${activities.length} REG.</span></div><div class="activity-list">${records}</div></div>
        </section>
        <section class="card content-card"><div class="card-head"><div><h2>Habilidades da trilha</h2><p>Habilidades anteriores ao seu rank ficam desbloqueadas.</p></div><span class="badge red">${skills.filter(s=>s.unlocked).length} / 7</span></div><div class="skills-wrap">${skillHtml}</div></section>
      </div>
      <section class="card content-card sub-section"><div class="card-head"><div><h2>Poções e consumíveis</h2><p>Uso fora do combate não gasta turno. No combate, use a ação Item.</p></div><span class="badge">USO ÚNICO</span></div><div class="potion-row">${potions.map(it=>`<div class="potion-card"><span class="potion-icon">${esc(it.icon)}</span><div class="potion-details"><strong>${esc(it.name)}</strong><small>${esc(it.desc)}</small><small>Em expedição: ${it.dungeon_quantity||0}</small></div><span class="potion-qty">×${it.quantity}</span><button class="secondary small-btn" data-use-potion="${it.id}" ${it.quantity+(it.dungeon_quantity||0)<=0?'disabled':''}>Usar</button></div>`).join('')}</div>
        <details class="sub-section"><summary class="field-label" style="cursor:pointer;padding:8px 0">Inventário de equipamentos · ${equipment.length} itens no catálogo</summary><div class="equipment-grid" style="margin-top:12px">${equipment.map(it=>`<article class="equipment-card"><span class="equipment-icon">${esc(it.icon)}</span><h4>${esc(it.name)}</h4><p>${esc(it.desc)}</p><div class="equipment-footer"><span class="item-rank">${it.rank} · ${esc(it.attr)}</span>${it.equipped?`<button class="danger small-btn" data-unequip="${it.attr}">Tirar</button>`:`<button class="secondary small-btn" data-equip="${it.id}" ${it.quantity<=0?'disabled':''}>${it.quantity>0?`Equipar · ×${it.quantity}`:'Não obtido'}</button>`}</div></article>`).join('')}</div></details>
      </section>
      <section class="card content-card sub-section"><div class="card-head"><div><h2>Configurar tarefas</h2><p>Você escolhe qual hábito representa cada atributo. Cada tarefa deve ficar vinculada a um único atributo.</p></div><span class="badge">EDITÁVEL</span></div><form id="task-mapping-form"><div class="task-config-grid">${p.attributes.map(item=>`<div class="form-control"><label for="task-${item.code}">${esc(item.code)} · ${esc(item.name)}</label><input class="input" id="task-${item.code}" data-task-code="${item.code}" maxlength="80" value="${esc(item.activity)}" required></div>`).join('')}</div><button class="primary" type="submit" style="margin-top:14px">Salvar tarefas</button></form></section>`;
  }
  function renderDungeon(){
    const p=state.data.player;const d=state.data.dungeon;
    if(!d){
      return `${renderHeading('Dungeon','Explore mapas 6×6, enfrente monstros e volte com recompensas.',`<span class="badge">LIMITE ${p.weekly_dungeons}/${p.weekly_limit} NA SEMANA</span>`)}
        <div class="card dungeon-intro"><div><p class="eyebrow">PORTAL DETECTADO</p><h2>Desça. <span>Enfrente.</span><br>Conquiste.</h2><p>Mapas gerados proceduralmente, movimento para oito direções, monstros estacionários, baús e combate por turnos. A dungeon tem de 3 a 7 andares; o último guarda um chefe.</p><div class="grid grid-3" style="margin:18px 0"><div class="dungeon-state-card"><small>MAPA</small><strong>6 × 6</strong></div><div class="dungeon-state-card"><small>VISÃO</small><strong>3 × 3</strong></div><div class="dungeon-state-card"><small>RECOMPENSA</small><strong>+40 min</strong></div></div><button id="start-dungeon" class="primary">⚔ Entrar na dungeon</button></div><div class="dungeon-symbol">⛧</div></div>
        ${p.last_dungeon_result?`<div class="run-summary">${esc(p.last_dungeon_result)}</div>`:''}
        <div class="grid grid-3" style="margin-top:16px"><div class="card stat-card"><div class="label">Regras de morte</div><div class="stat-value" style="font-size:22px">HP 10 · MP 10</div><div class="stat-sub">Moedas preservadas; itens temporários perdidos.</div></div><div class="card stat-card"><div class="label">Inventário de poções</div><div class="stat-value" style="font-size:22px">🧪 ×${p.inventory.consumables.find(x=>x.id==='pocao_cura')?.quantity||0} · 🔮 ×${p.inventory.consumables.find(x=>x.id==='pocao_mana')?.quantity||0}</div><div class="stat-sub">Cura 8 HP · Mana 6 MP.</div></div><div class="card stat-card"><div class="label">Tentativas</div><div class="stat-value" style="font-size:22px">${Math.max(0,p.weekly_limit-p.weekly_dungeons)} restantes</div><div class="stat-sub">Contagem nos últimos 7 dias.</div></div></div>`;
    }
    const c=d.combat;
    const grid=d.map.grid.map(row=>row.map(t=>{
      const dx=t.x-d.x,dy=t.y-d.y;const isAdj=Math.max(Math.abs(dx),Math.abs(dy))===1;const canMove=!c&&isAdj&&t.state!=='fog';
      return `<button class="map-tile ${t.state} ${canMove?'adjacent':''}" data-move-x="${dx}" data-move-y="${dy}" title="${esc(t.label||'Área desconhecida')}" ${canMove?'':'disabled'}>${esc(t.icon)}</button>`;
    }).join('')).join('');
    const runPotions=d.run_potions||{};
    let encounter='';
    if(c){
      const e=c.enemy;
      const availableSkills=c.skills.map(s=>`<option value="${esc(s.id)}" data-cost="${s.current_cost}" ${s.cooldown_left>0?'disabled':''}>${esc(s.name)}${s.current_cost?` · ${s.current_cost} MP`:''}${s.cooldown_left>0?` · recarga ${s.cooldown_left}`:''}</option>`).join('');
      encounter=`<section class="card encounter-card"><div class="enemy-portrait"><div class="enemy-icon">${esc(e.icon)}</div><div class="enemy-name"><h3>${esc(e.name)}</h3><small>${e.tier==='boss'?'CHEFE':e.tier==='strong'?'MONSTRO FORTE':'MONSTRO COMUM'} · RANK ${e.rank}</small></div></div>
        <div class="meter"><div class="meter-line"><span>HP DO INIMIGO</span><strong>${e.hp} / ${e.hp_max}</strong></div><div class="meter-bar"><span style="width:${Math.max(0,e.hp/e.hp_max*100)}%"></span></div></div>
        <div class="meter mana"><div class="meter-line"><span>MP DO INIMIGO</span><strong>${e.mp} / ${e.mp_max}</strong></div><div class="meter-bar"><span style="width:${Math.max(0,e.mp/e.mp_max*100)}%"></span></div></div>
        <div class="enemy-stat-grid">${['ATK','DEF','AGI','MAG','RES','LUC'].map(k=>`<div class="enemy-stat"><small>${k}</small><strong>${e.stats[k]}</strong></div>`).join('')}</div>
        <div class="combat-actions"><button class="primary" data-combat-action="attack">⚔ Ataque básico</button><button class="secondary" data-combat-action="defend">⛨ Defender</button></div>
        <div class="combat-skill-row"><select id="combat-skill" aria-label="Habilidade ativa"><option value="">Escolher habilidade ativa…</option>${availableSkills}</select><button class="primary" data-use-skill>Usar skill</button></div>
        <div class="combat-items">${state.data.consumables.map(it=>{const qty=Number(state.data.player.inventory.consumables.find(x=>x.id===it.id)?.quantity||0);const temp=Number(runPotions[it.id]||0);return `<button class="secondary small-btn" data-combat-item="${it.id}" ${qty+temp<=0?'disabled':''}>${esc(it.icon)} ${esc(it.name)} (${qty+temp})</button>`}).join('')}</div>
        <div class="combat-log"><p class="eyebrow">REGISTRO DE COMBATE · RODADA ${c.round+1}</p>${(c.log||[]).slice(-8).map(line=>`<p>› ${esc(line)}</p>`).join('')||'<p>O combate começou. Escolha sua ação.</p>'}</div>
        <p class="muted" style="font-size:10px;margin:12px 0 0">O inimigo mais ágil pode agir primeiro. Bônus de dano são aplicados depois do cálculo básico.</p>
      </section>`;
    }else{
      encounter=`<section class="card encounter-card"><div class="card-head"><div><h2>Exploração</h2><p>Encontre monstros, abra baús e alcance a saída.</p></div><span class="badge red">EM ANDAMENTO</span></div><div class="run-summary">${esc(d.last_message||'Escolha uma casa adjacente para se mover.')}<br><br>Itens de equipamento encontrados ficam em uma bolsa temporária até a vitória final. Se morrer, eles serão perdidos; moedas e poções consumidas não voltam.</div><div class="dungeon-state-cards" style="margin-top:14px"><div class="dungeon-state-card"><small>LOOT</small><strong>${d.loot_count}</strong></div><div class="dungeon-state-card"><small>MOEDAS ACHADAS</small><strong>${d.coins_found}</strong></div><div class="dungeon-state-card"><small>POÇÕES NA BOLSA</small><strong>${Number(runPotions.pocao_cura||0)+Number(runPotions.pocao_mana||0)}</strong></div></div><div style="display:flex;gap:8px;margin-top:12px"><button class="secondary" data-use-outside-potion="pocao_cura">🧪 Poção de Cura</button><button class="secondary" data-use-outside-potion="pocao_mana">🔮 Poção de Mana</button></div><button class="danger small-btn" id="abandon-dungeon" style="margin-top:14px">Abandonar exploração</button></section>`;
    }
    return `${renderHeading('Dungeon','Um passo de cada vez. O mapa só revela o que está perto.',`<span class="badge red">ANDAR ${d.floor}/${d.floors}</span><span class="badge">${d.loot_count} LOOT TEMP.</span>`)}
      <div class="dungeon-running"><section class="card map-card"><div class="map-top"><h2>Mapa de exploração</h2><span class="floor-chip">${d.floor===d.floors?'⚠ ANDAR DO CHEFE':'⌖ ANDAR '+d.floor}</span></div><div class="dungeon-map">${grid}</div><div class="map-legend"><span><i>🧙</i> Você</span><span><i>👹</i> Monstro</span><span><i>▣</i> Baú</span><span><i>⇩</i> Saída</span><span><i>?</i> Não revelado</span></div><p class="map-instructions">Clique numa das 8 casas adjacentes iluminadas para mover. Monstros não se deslocam.</p></section><div class="dungeon-side">${encounter}</div></div>`;
  }
  function renderDashboard(){
    const p=state.data.player;const attrs=p.attributes;
    return `${renderHeading('Painel de desempenho','Compare medidas registradas e acompanhe tendências.',`<span class="badge">${p.today_xp} XP HOJE</span>`)}
      <div class="dashboard-attrs">${attrs.map(a=>`<div class="dashboard-attr" data-dashboard-attr="${a.code}"><strong>${esc(a.name)} <span>${a.rank}</span></strong><small>${a.xp} XP · ${esc(a.activity)}</small><div class="progress"><span style="width:${a.progress}%"></span></div></div>`).join('')}</div>
      <section class="card chart-card"><div class="card-head"><div><h2>Comparação de variáveis</h2><p>Média dos valores numéricos dos registros em cada intervalo. Registros sem número não entram no gráfico.</p></div><span class="badge">HISTÓRICO</span></div>
        <div class="chart-controls"><div class="form-control"><label for="chart-a">Variável principal</label><select id="chart-a">${attrs.map(a=>`<option value="${a.code}" ${state.chartSettings.a===a.code?'selected':''}>${a.code} · ${esc(a.name)}</option>`).join('')}</select></div><div class="form-control"><label for="chart-b">Comparar com</label><select id="chart-b"><option value="">Sem comparação</option>${attrs.map(a=>`<option value="${a.code}" ${state.chartSettings.b===a.code?'selected':''}>${a.code} · ${esc(a.name)}</option>`).join('')}</select></div><div class="form-control"><label for="chart-days">Período</label><select id="chart-days"><option value="7" ${state.chartSettings.days==='7'?'selected':''}>7 dias</option><option value="30" ${state.chartSettings.days==='30'?'selected':''}>30 dias</option><option value="90" ${state.chartSettings.days==='90'?'selected':''}>90 dias</option><option value="365" ${state.chartSettings.days==='365'?'selected':''}>1 ano</option><option value="all" ${state.chartSettings.days==='all'?'selected':''}>Tudo</option></select></div><div class="form-control"><label for="chart-group">Agrupar por</label><select id="chart-group"><option value="day" ${state.chartSettings.group==='day'?'selected':''}>Dia</option><option value="week" ${state.chartSettings.group==='week'?'selected':''}>Semana</option><option value="month" ${state.chartSettings.group==='month'?'selected':''}>Mês</option></select></div><button id="chart-update" class="primary">Atualizar ↻</button></div>
        <div class="chart-container"><canvas id="performance-chart" aria-label="Gráfico de desempenho"></canvas><div id="chart-placeholder" class="chart-empty hidden">Ainda não há medidas numéricas neste período.</div></div><div id="chart-summary" class="muted" style="font-size:10px;margin-top:9px"></div>
      </section>
      <section class="card content-card sub-section"><div class="card-head"><div><h2>Como ler o painel</h2><p>Os registros são pessoais e independentes da pontuação de XP.</p></div></div><div class="grid grid-3"><div class="dungeon-state-card"><small>AGRUPAMENTO DIÁRIO</small><strong>Um ponto por data</strong><p class="muted" style="font-size:10px">Mostra a média das medições naquele dia.</p></div><div class="dungeon-state-card"><small>AGRUPAMENTO SEMANAL</small><strong>Semana a semana</strong><p class="muted" style="font-size:10px">Usa a segunda-feira como início de semana.</p></div><div class="dungeon-state-card"><small>AGRUPAMENTO MENSAL</small><strong>Mês a mês</strong><p class="muted" style="font-size:10px">Ajuda a observar tendências de longo prazo.</p></div></div></section>`;
  }
  function renderShop(){
    const p=state.data.player, owned=new Set((p.relics_owned||[]).map(r=>r.id));
    const products=[
      {id:'pocao_cura',icon:'🧪',name:'Poção de Cura',desc:'Recupera até 8 HP.',price:30,qty:p.inventory.consumables.find(x=>x.id==='pocao_cura')?.quantity||0},
      {id:'pocao_mana',icon:'🔮',name:'Poção de Mana',desc:'Recupera até 6 MP.',price:30,qty:p.inventory.consumables.find(x=>x.id==='pocao_mana')?.quantity||0},
      {id:'ticket_dungeon',icon:'🎟️',name:'Ticket de Dungeon',desc:'Permite iniciar uma exploração extra além do limite semanal.',price:600,qty:p.inventory.ticket_dungeon||0},
      {id:'minute',icon:'⏱️',name:'1 minuto adicional',desc:'Adiciona 60 segundos ao saldo especial permanente.',price:1000,qty:null}
    ];
    const relics=[
      {id:'manto_heroi_esquecido',icon:'🧥',name:'Manto do Herói Esquecido',desc:'A cada 10 XP recebidos, ganhe 1 XP adicional. O bônus não gera novos bônus.',price:2500,owned:owned.has('manto_heroi_esquecido'),passive:true},
      {id:'anel_investidor_nato',icon:'💍',name:'Anel do Investidor Nato',desc:'Venda tempo do saldo diário por 1 moeda por segundo. O saldo especial não pode ser vendido.',price:1500,owned:owned.has('anel_investidor_nato'),passive:true},
      {id:'pingente_deusa_amor',icon:'💗',name:'Pingente da Deusa do Amor',desc:'Uso único: transfira 10 XP de um atributo para outro, sem criar XP.',price:500,owned:false,qty:p.inventory.pingente_deusa_amor||0}
    ];
    const maxDaily=Math.max(0,p.daily_reward_seconds||0);
    return `${renderHeading('Loja','Consumíveis, segurança, tempo e relíquias vinculadas.',`<span class="badge red">◉ ${Number(p.coins).toLocaleString('pt-BR')} MOEDAS</span>`)}
      <div class="site-grid">${products.map(it=>`<article class="card site-card"><span class="site-icon">${it.icon}</span><h3>${esc(it.name)}</h3><p>${esc(it.desc)}</p>${it.qty!==null?`<small class="muted">No inventário: ${it.qty}</small>`:''}<button class="primary" data-buy-item="${it.id}" ${Number(p.coins)<it.price?'disabled':''}>Comprar · ${it.price.toLocaleString('pt-BR')} moedas</button></article>`).join('')}</div>
      <div class="sub-section-title" style="margin-top:25px"><h2>Espaço de utilidade</h2><span class="badge">ITENS DE APOIO</span></div><p class="muted">Itens de uso especial ficam aqui, separados dos consumíveis comuns e das relíquias vinculadas.</p>
      <div class="site-grid"><article class="card site-card"><span class="site-icon">🛡️</span><h3>Bracelete da Salvação</h3><p>Uso único: preserva equipamentos do loot se você morrer na dungeon.</p><small class="muted">No inventário: ${Number(p.inventory.bracelete_salvacao||0)}</small><button class="primary" data-buy-item="bracelete_salvacao" ${Number(p.coins)<500?'disabled':''}>Comprar · 500 moedas</button></article></div>
      <div class="sub-section-title" style="margin-top:25px"><h2>Relíquias Vinculadas</h2><span class="badge">NÃO PODEM SER ROUBADAS</span></div><p class="muted">Relíquias acompanham sua conta e não são perdidas ao morrer na dungeon. As duas primeiras são permanentes; o Pingente é consumível.</p>
      <section class="card content-card sub-section relic-slot"><div class="card-head"><div><h2>Espaço de relíquias</h2><p>Você pode possuir as duas relíquias permanentes, mas apenas uma fica ativa por vez.</p></div><span class="badge">${p.active_relic_id?esc(relics.find(it=>it.id===p.active_relic_id)?.name||'ATIVA'):'VAZIO'}</span></div></section>
      <div class="site-grid">${relics.map(it=>{const active=p.active_relic_id===it.id;return `<article class="card site-card relic-card"><span class="site-icon">${it.icon}</span><h3>${esc(it.name)}</h3><p>${esc(it.desc)}</p>${it.owned?(active?'<small class="owned-label">Ativa · vinculada à conta</small>':'<small class="owned-label">Possuída · inativa</small>'):it.qty?`<small class="owned-label">No inventário: ${it.qty}</small>`:''}${it.passive&&it.owned?`<button class="${active?'secondary':'primary'}" data-activate-relic="${it.id}" ${active?'disabled':''}>${active?'Relíquia ativa':'Ativar relíquia'}</button>`:`<button class="primary" data-buy-item="${it.id}" ${Number(p.coins)<it.price?'disabled':''}>Comprar · ${it.price.toLocaleString('pt-BR')} moedas</button>`}</article>`;}).join('')}</div>
      ${p.active_relic_id==='anel_investidor_nato'?`<section class="card content-card sub-section"><div class="card-head"><div><h2>Converter tempo em moedas</h2><p>Taxa: 1 segundo vendido = 1 moeda. Apenas o saldo diário pode ser convertido.</p></div><span class="badge">${humanDuration(maxDaily)} DISPONÍVEIS</span></div><form id="sell-time-form" class="relic-form"><div class="form-control"><label for="sell-seconds">Segundos para vender</label><input class="input" id="sell-seconds" type="number" min="1" max="${maxDaily}" value="${maxDaily}" required></div><div class="form-control"><label>Você recebe</label><input class="input" id="sell-coins-preview" value="${maxDaily} moedas" readonly></div><button class="primary" type="submit" ${maxDaily<=0?'disabled':''}>Vender tempo</button></form></section>`:''}
      ${(p.inventory.pingente_deusa_amor||0)>0?`<section class="card content-card sub-section"><div class="card-head"><div><h2>Usar Pingente da Deusa do Amor</h2><p>Transfere exatamente 10 XP. O rank é recalculado nos dois atributos.</p></div><span class="badge">×${p.inventory.pingente_deusa_amor} DISPONÍVEL</span></div><form id="transfer-xp-form" class="relic-form"><div class="form-control"><label for="transfer-source">Retirar de</label><select id="transfer-source" required>${p.attributes.filter(a=>a.xp>=10).map(a=>`<option value="${a.code}">${a.code} · ${esc(a.name)} (${a.xp} XP)</option>`).join('')}</select></div><div class="form-control"><label for="transfer-target">Adicionar a</label><select id="transfer-target" required>${p.attributes.map(a=>`<option value="${a.code}">${a.code} · ${esc(a.name)} (${a.xp} XP)</option>`).join('')}</select></div><button class="primary" type="submit">Transferir 10 XP</button></form></section>`:''}
      <p class="muted" style="margin-top:16px">As compras são descontadas imediatamente. O bracelete só é consumido quando salva o loot de uma derrota; o ticket só é consumido ao entrar além do limite semanal.</p>`;
  }
  function renderRewards(){
    const p=state.data.player;
    const daily=p.daily_reward_seconds||0;const special=p.special_reward_seconds||0;
    const sitesHtml=Object.entries(sites).map(([key,s])=>`<article class="card site-card"><span class="site-icon">${esc(s.icon)}</span><h3>${esc(s.title)}</h3><p>${esc(s.desc)}</p><button class="primary" data-open-site="${key}">Abrir janela ↗</button></article>`).join('');
    return `${renderHeading('Recompensas','Desbloqueie tempo de lazer com tarefas cumpridas e chefes derrotados.',`<span class="badge red">${humanDuration(daily)} DIÁRIO</span>`)}
      <section class="card reward-balance"><span class="reward-balance-icon">◷</span><div class="reward-balance-copy"><p class="eyebrow">TEMPO DISPONÍVEL</p><strong id="reward-daily-display">${humanDuration(daily)}</strong><small>Saldo diário · até 20 minutos gerados hoje</small></div><div class="reward-balance-special"><small>SALDO ESPECIAL PERMANENTE</small><strong id="reward-special-display">${humanDuration(special)}</strong><small>Chefes derrotados</small></div></section>
      <div class="sub-section-title" style="margin-top:23px"><h3>Janelas de recompensa</h3><span class="badge">O TEMPO CONTA COM A JANELA ABERTA</span></div><div class="site-grid">${sitesHtml}</div><p class="muted" style="font-size:10px;margin:0 0 25px">Os sites abrem numa janela dentro do jogo. Alguns serviços bloqueiam incorporação; nesse caso, o botão de nova aba serve como alternativa. O cronômetro continua enquanto a janela está aberta.</p>
      <section class="card content-card sub-section"><div class="card-head"><div><h2>Como o tempo é conquistado</h2><p>Regras de recompensa.</p></div></div><div class="grid grid-3"><div class="dungeon-state-card"><small>TAREFA POSITIVA</small><strong>+2m30s</strong><p class="muted" style="font-size:10px">Cada atributo cumprido pode conceder tempo, até 20 min por dia.</p></div><div class="dungeon-state-card"><small>CHEFE DERROTADO</small><strong>+40 min</strong><p class="muted" style="font-size:10px">Saldo especial persistente, consumido depois do saldo diário.</p></div><div class="dungeon-state-card"><small>ORDEM DE CONSUMO</small><strong>Diário → Especial</strong><p class="muted" style="font-size:10px">O saldo diário não usado expira na virada do dia.</p></div></div></section>`;
  }
  function bindPageEvents(){
    $$('[data-attribute]').forEach(b=>b.addEventListener('click',()=>{state.selectedAttr=b.dataset.attribute;render()}));
    $$('[data-eval]').forEach(b=>b.addEventListener('click',async()=>{
      try{const d=await api('/api/evaluations',{method:'POST',body:{attribute:b.dataset.code,score:Number(b.dataset.eval),day:todayKey()}});state.data=d.state;render();toast(d.message||'Autoavaliação registrada.');}catch(e){toast(e.message,true)}
    }));
    const activityForm=$('#activity-form');if(activityForm)activityForm.addEventListener('submit',async e=>{
      e.preventDefault();const fd=new FormData(activityForm);const body={attribute:activityForm.dataset.activityAttr,title:fd.get('title'),value:fd.get('value'),note:fd.get('note')};
      try{const d=await api('/api/activities',{method:'POST',body});state.data=d.state;render();toast(d.message);}catch(err){toast(err.message,true)}
    });
    const taskForm=$('#task-mapping-form');if(taskForm)taskForm.addEventListener('submit',async e=>{
      e.preventDefault();const mapping={};$$('[data-task-code]',taskForm).forEach(input=>mapping[input.dataset.taskCode]=input.value.trim());
      try{const d=await api('/api/tasks',{method:'POST',body:{mapping,base_version:Number(state.data.player.task_mapping_version||0)}});state.data=d.state||state.data;render();toast(d.message||'Tarefas atualizadas.');}
      catch(err){
        if(/alteradas em outro dispositivo/i.test(err.message)&&navigator.onLine){
          try{const server=await api('/api/state');state.data=server;const useLocal=confirm('Outro dispositivo alterou as tarefas desde a última sincronização. OK = aplicar as alterações que você acabou de editar por cima da versão do servidor. Cancelar = manter a versão do servidor.');if(useLocal){const saved=await api('/api/tasks',{method:'POST',body:{mapping,base_version:Number(server.player.task_mapping_version||0)}});state.data=saved.state||state.data;toast(saved.message||'Tarefas locais aplicadas.');}else toast('Mantida a versão de tarefas do servidor.');render();}
          catch(second){toast(second.message||'Não foi possível resolver o conflito de tarefas.',true);}
        }else toast(err.message,true);
      }
    });
    $$('[data-activate-relic]').forEach(btn=>btn.addEventListener('click',async()=>{const relicId=btn.dataset.activateRelic;const label=relicId==='manto_heroi_esquecido'?'Manto do Herói Esquecido':'Anel do Investidor Nato';if(!confirm(`Ativar ${label}? A outra relíquia de utilidade ficará inativa.`))return;const base=state.data.player.active_relic_id||null;try{const d=await api('/api/relics/activate',{method:'POST',body:{relic_id:relicId,base_active_relic_id:base}});state.data=d.state||state.data;render();toast(d.message||`${label} ativado.`);}catch(err){if(err.data?.conflict&&navigator.onLine){try{const server=await api('/api/state');state.data=server;const useLocal=confirm(`Outro dispositivo ativou outra relíquia. OK = ativar ${label} mesmo assim; Cancelar = manter a escolha do servidor.`);if(useLocal){const d=await api('/api/relics/activate',{method:'POST',body:{relic_id:relicId,base_active_relic_id:server.player.active_relic_id||null}});state.data=d.state||server;}render();}catch(second){toast(second.message||'Não foi possível resolver o conflito.',true);}}else toast(err.message,true);}}));
    const sellForm=$('#sell-time-form');if(sellForm){const sec=$('#sell-seconds'),preview=$('#sell-coins-preview');sec.addEventListener('input',()=>{preview.value=`${Math.max(0,Number(sec.value)||0)} moedas`;});sellForm.addEventListener('submit',async e=>{e.preventDefault();const seconds=Number(sec.value);if(!confirm(`Vender ${seconds} segundos por ${seconds} moedas? Esse tempo não poderá ser recuperado.`))return;try{const d=await api('/api/relics/sell-time',{method:'POST',body:{seconds}});state.data=d.state;render();toast(d.message);}catch(err){toast(err.message,true);}});}
    const transferForm=$('#transfer-xp-form');if(transferForm)transferForm.addEventListener('submit',async e=>{e.preventDefault();const source=$('#transfer-source').value,target=$('#transfer-target').value;if(source===target){toast('Escolha dois atributos diferentes.',true);return;}if(!confirm(`Transferir 10 XP de ${source} para ${target}? O Pingente será consumido.`))return;try{const d=await api('/api/relics/transfer',{method:'POST',body:{source,target}});state.data=d.state;render();toast(d.message);}catch(err){toast(err.message,true);}});
    $$('[data-delete-activity]').forEach(b=>b.addEventListener('click',async()=>{
      if(!confirm('Excluir este registro? O XP não será alterado.'))return;
      try{const d=await api(`/api/activities/${b.dataset.deleteActivity}`,{method:'DELETE'});state.data=d.state;render();toast(d.message);}catch(e){toast(e.message,true)}
    }));
    $$('[data-edit-activity]').forEach(b=>b.addEventListener('click',async()=>{
      const r=state.data.activities.find(x=>String(x.id)===String(b.dataset.editActivity)||String(x.client_ref)===String(b.dataset.editActivity));if(!r)return;
      const title=prompt('Descrição:',r.title);if(title===null)return;
      const value=prompt('Valor numérico (deixe vazio para apagar):',r.value??'');if(value===null)return;
      const note=prompt('Observação:',r.note||'');if(note===null)return;
      try{const d=await api(`/api/activities/${r.id}`,{method:'PUT',body:{title,value,note}});state.data=d.state;render();toast(d.message);}catch(e){toast(e.message,true)}
    }));
    $$('[data-equip]').forEach(b=>b.addEventListener('click',async()=>{try{const d=await api('/api/equipment/equip',{method:'POST',body:{item_id:b.dataset.equip}});state.data=d.state;render();toast(d.message);}catch(e){toast(e.message,true)}}));
    $$('[data-unequip]').forEach(b=>b.addEventListener('click',async()=>{try{const d=await api('/api/equipment/equip',{method:'POST',body:{item_id:null,attribute:b.dataset.unequip}});state.data=d.state;render();toast(d.message);}catch(e){toast(e.message,true)}}));
    $$('[data-use-potion]').forEach(b=>b.addEventListener('click',async()=>{try{const d=await api('/api/items/use',{method:'POST',body:{item_id:b.dataset.usePotion}});state.data=d.state;render();toast(d.message);}catch(e){toast(e.message,true)}}));
    const start=$('#start-dungeon');if(start)start.addEventListener('click',async()=>{try{const d=await api('/api/dungeon/start',{method:'POST',body:{}});state.data=d.state;render();toast(d.message);setTab('dungeon');}catch(e){toast(e.message,true)}});
    $$('[data-move-x]').forEach(b=>b.addEventListener('click',async()=>{try{const d=await api('/api/dungeon/move',{method:'POST',body:{dx:Number(b.dataset.moveX),dy:Number(b.dataset.moveY)}});state.data=d.state;render();toast(d.message||'Movimento realizado.');}catch(e){toast(e.message,true)}}));
    $$('[data-combat-action]').forEach(b=>b.addEventListener('click',()=>combatAction({type:b.dataset.combatAction})));
    const skillBtn=$('[data-use-skill]');if(skillBtn)skillBtn.addEventListener('click',()=>{const sid=$('#combat-skill')?.value;if(!sid){toast('Escolha uma habilidade.',true);return}combatAction({type:'skill',skill_id:sid})});
    $$('[data-combat-item]').forEach(b=>b.addEventListener('click',()=>combatAction({type:'item',item_id:b.dataset.combatItem})));
    $$('[data-use-outside-potion]').forEach(b=>b.addEventListener('click',async()=>{try{const d=await api('/api/items/use',{method:'POST',body:{item_id:b.dataset.useOutsidePotion}});state.data=d.state;render();toast(d.message);}catch(e){toast(e.message,true)}}));
    const abandon=$('#abandon-dungeon');if(abandon)abandon.addEventListener('click',async()=>{if(!confirm('Abandonar agora? O loot temporário será perdido.'))return;try{const d=await api('/api/dungeon/abandon',{method:'POST',body:{}});state.data=d.state;render();toast(d.message,true)}catch(e){toast(e.message,true)}});
    $$('[data-dashboard-attr]').forEach(b=>b.addEventListener('click',()=>{state.chartSettings.a=b.dataset.dashboardAttr;state.chartSettings.b='';const a=$('#chart-a');if(a)a.value=state.chartSettings.a;const s=$('#chart-b');if(s)s.value='';loadChart()}));
    $('#chart-update')?.addEventListener('click',()=>{state.chartSettings.a=$('#chart-a').value;state.chartSettings.b=$('#chart-b').value;state.chartSettings.days=$('#chart-days').value;state.chartSettings.group=$('#chart-group').value;loadChart()});
    $$('[data-buy-item]').forEach(b=>b.addEventListener('click',async()=>{try{const d=await api('/api/shop/buy',{method:'POST',body:{item_id:b.dataset.buyItem}});state.data=d.state;render();toast(d.message);}catch(e){toast(e.message,true)}}));
    $$('[data-open-site]').forEach(b=>b.addEventListener('click',()=>openSite(b.dataset.openSite)));
  }
  async function combatAction(action){
    try{const d=await api('/api/dungeon/action',{method:'POST',body:action});state.data=d.state;render();toast(d.message||'Ação realizada.');}catch(e){toast(e.message,true)}
  }
  function localChartData(a,b,days,group){
    const all=state.data?.activities||[];
    let cutoff=null;
    if(days!=='all'){
      const n=Math.max(1,Number(days)||30),base=new Date(`${todayKey()}T00:00:00Z`);
      base.setUTCDate(base.getUTCDate()-n);cutoff=base.toISOString().slice(0,10);
    }
    const buckets=new Map();
    for(const rec of all){
      if(![a,b].filter(Boolean).includes(rec.attribute)||rec.value===null||rec.value===''||!Number.isFinite(Number(rec.value)))continue;
      const raw=String(rec.created_at||'').slice(0,10);if(!/^\d{4}-\d{2}-\d{2}$/.test(raw)||(cutoff&&raw<cutoff))continue;
      let key=raw,label=raw.slice(8,10)+'/'+raw.slice(5,7);
      if(group==='month'){key=raw.slice(0,7);label=key.slice(5,7)+'/'+key.slice(0,4);}
      else if(group==='week'){
        const dt=new Date(`${raw}T00:00:00Z`),weekday=dt.getUTCDay()||7;dt.setUTCDate(dt.getUTCDate()-weekday+1);key=dt.toISOString().slice(0,10);label='Sem. '+key.slice(8,10)+'/'+key.slice(5,7);
      }
      if(!buckets.has(key))buckets.set(key,{label,[a]:[],...(b?{[b]:[]}:{}),count_a:0,count_b:0});
      const bucket=buckets.get(key);bucket[rec.attribute].push(Number(rec.value));
      if(rec.attribute===a)bucket.count_a++;if(b&&rec.attribute===b)bucket.count_b++;
    }
    return [...buckets.entries()].sort((x,y)=>x[0].localeCompare(y[0])).map(([key,v])=>{
      const row={label:v.label,[a]:v[a].length?Math.round(v[a].reduce((s,n)=>s+n,0)/v[a].length*100)/100:null,count_a:v.count_a};
      if(b){row[b]=v[b].length?Math.round(v[b].reduce((s,n)=>s+n,0)/v[b].length*100)/100:null;row.count_b=v.count_b;}
      return row;
    });
  }
  function drawFallbackChart(rows,a,b){
    const canvas=$('#performance-chart');if(!canvas)return;
    const width=Math.max(280,canvas.clientWidth||520),height=Math.max(220,canvas.clientHeight||300),dpr=Math.max(1,window.devicePixelRatio||1);
    canvas.width=Math.round(width*dpr);canvas.height=Math.round(height*dpr);
    const ctx=canvas.getContext('2d');if(!ctx)return;ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,width,height);
    const series=[{key:a,label:`${a} · média`,color:'#f35b6b'},...(b?[{key:b,label:`${b} · média`,color:'#b7a0ff'}]:[])];
    const values=rows.flatMap(r=>series.map(s=>r[s.key])).filter(v=>v!==null&&v!==undefined&&Number.isFinite(Number(v))).map(Number);
    if(!values.length)return;
    let min=Math.min(...values),max=Math.max(...values);if(min===max){min-=1;max+=1;}else{const pad=(max-min)*.12;min-=pad;max+=pad;}
    const left=44,right=14,top=34,bottom=38,plotW=width-left-right,plotH=height-top-bottom;
    ctx.font='10px monospace';ctx.textBaseline='middle';ctx.strokeStyle='#292d38';ctx.fillStyle='#7e8595';ctx.lineWidth=1;
    for(let i=0;i<5;i++){const value=max-(max-min)*i/4,y=top+plotH*i/4;ctx.beginPath();ctx.moveTo(left,y);ctx.lineTo(width-right,y);ctx.stroke();ctx.textAlign='right';ctx.fillText(Number(value.toFixed(2)).toLocaleString('pt-BR'),left-7,y);}
    const xAt=i=>rows.length<=1?left+plotW/2:left+plotW*i/(rows.length-1);
    const labelStep=Math.max(1,Math.ceil(rows.length/7));ctx.fillStyle='#7e8595';ctx.textAlign='center';ctx.textBaseline='top';
    rows.forEach((r,i)=>{if(i%labelStep===0||i===rows.length-1)ctx.fillText(String(r.label).slice(0,10),xAt(i),top+plotH+10);});
    series.forEach((s,si)=>{
      ctx.strokeStyle=s.color;ctx.fillStyle=s.color;ctx.lineWidth=2;ctx.beginPath();let drawing=false;
      rows.forEach((r,i)=>{const value=r[s.key];if(value===null||value===undefined||!Number.isFinite(Number(value))){drawing=false;return;}const x=xAt(i),y=top+(max-Number(value))/(max-min)*plotH;if(!drawing){ctx.moveTo(x,y);drawing=true;}else ctx.lineTo(x,y);});ctx.stroke();
      rows.forEach((r,i)=>{const value=r[s.key];if(value===null||value===undefined||!Number.isFinite(Number(value)))return;const x=xAt(i),y=top+(max-Number(value))/(max-min)*plotH;ctx.beginPath();ctx.arc(x,y,2.5,0,Math.PI*2);ctx.fill();});
      const legendX=left+si*112;ctx.fillRect(legendX,9,12,3);ctx.fillStyle='#aeb4c3';ctx.textAlign='left';ctx.textBaseline='middle';ctx.fillText(s.label,legendX+17,11);ctx.fillStyle=s.color;
    });
  }
  async function loadChart(){
    if(state.tab!=='dashboard')return;
    const a=$('#chart-a')?.value||state.chartSettings.a;
    let b=$('#chart-b')?.value??state.chartSettings.b; if(b===a)b='';
    const days=$('#chart-days')?.value||state.chartSettings.days;
    const group=$('#chart-group')?.value||state.chartSettings.group;
    state.chartSettings={a,b,days,group};
    try{
      const rows=navigator.onLine
        ?(await api(`/api/charts?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}&days=${encodeURIComponent(days)}&group=${group}`)).data
        :localChartData(a,b,days,group);
      const hasValues=rows.some(row=>row[a]!==null||(b&&row[b]!==null));
      $('#chart-placeholder')?.classList.toggle('hidden',hasValues);
      $('#performance-chart')?.classList.toggle('hidden',!hasValues);
      if(!hasValues&&$('#chart-placeholder'))$('#chart-placeholder').textContent='Ainda não há medidas numéricas neste período.';
      if(hasValues&&$('#performance-chart')){
        if(window.Chart){
          const labels=rows.map(x=>x.label),sets=[{label:`${a} · média`,data:rows.map(x=>x[a]),borderColor:'#f35b6b',backgroundColor:'#f35b6b22',spanGaps:true,tension:.25,pointRadius:3}];
          if(b)sets.push({label:`${b} · média`,data:rows.map(x=>x[b]),borderColor:'#b7a0ff',backgroundColor:'#b7a0ff22',spanGaps:true,tension:.25,pointRadius:3});
          if(state.chart){state.chart.destroy();state.chart=null;}
          state.chart=new Chart($('#performance-chart'),{type:'line',data:{labels,datasets:sets},options:{responsive:true,maintainAspectRatio:false,interaction:{mode:'index',intersect:false},plugins:{legend:{labels:{color:'#aeb4c3',usePointStyle:true,boxWidth:7,font:{size:10}}}},scales:{x:{ticks:{color:'#7e8595',font:{size:10}},grid:{color:'#292d38'}},y:{beginAtZero:false,ticks:{color:'#7e8595',font:{size:10}},grid:{color:'#292d38'}}}}});
        }else drawFallbackChart(rows,a,b);
      }
      const summary=$('#chart-summary');if(summary)summary.textContent=`${rows.length} intervalo(s) · agrupamento por ${group==='day'?'dia':group==='week'?'semana':'mês'} · médias dos registros numéricos${!navigator.onLine?' · dados locais deste dispositivo':''}.`;
    }catch(e){toast(e.message,true)}
  }
  async function openSite(key){
    if(!sites[key])return;
    if(!navigator.onLine){toast('Sites de recompensa são externos e precisam de internet. Seu saldo não foi consumido.',true);return;}
    try{const d=await api('/api/rewards/session',{method:'POST',body:{active:true}});state.data=d.state||state.data;state.site=key;$('#site-modal-title').textContent=sites[key].title;$('#site-frame').src=sites[key].url;$('#site-external').href=sites[key].url;$('#site-modal').classList.remove('hidden');updateModalTimer();$$('#site-switcher button').forEach(b=>b.classList.toggle('active',b.dataset.site===key));startRewardPings();}catch(e){toast(e.message,true)}
  }
  function switchSite(key){
    if(!sites[key])return;state.site=key;$('#site-modal-title').textContent=sites[key].title;$('#site-frame').src=sites[key].url;$('#site-external').href=sites[key].url;$$('#site-switcher button').forEach(b=>b.classList.toggle('active',b.dataset.site===key));
  }
  function updateModalTimer(){
    const p=state.data?.player;if(!p)return;const remaining=(p.daily_reward_seconds||0)+(p.special_reward_seconds||0);$('#modal-timer').textContent=fmtTime(remaining);$('#reward-daily-display')&&($('#reward-daily-display').textContent=humanDuration(p.daily_reward_seconds||0));$('#reward-special-display')&&($('#reward-special-display').textContent=humanDuration(p.special_reward_seconds||0));
  }
  function startRewardPings(){stopRewardPings();state.rewardInterval=setInterval(async()=>{
    try{const d=await api('/api/rewards/tick',{method:'POST',body:{}});if(state.data){state.data.player.daily_reward_seconds=d.daily;state.data.player.special_reward_seconds=d.special;state.data.player.reward_session_active=d.active;}updateModalTimer();if(!d.active){stopRewardPings();$('#site-modal').classList.add('hidden');$('#site-frame').src='about:blank';if(state.rewardExternalWindow&&!state.rewardExternalWindow.closed){try{state.rewardExternalWindow.close()}catch{}}state.rewardExternalWindow=null;toast('O tempo de recompensa acabou.');}}catch(e){stopRewardPings();toast(e.message,true)}
  },1000);}
  $('#site-external')?.addEventListener('click',e=>{e.preventDefault();const url=sites[state.site]?.url;if(!url)return;state.rewardExternalWindow=window.open(url,'questhubRewardSite');if(!state.rewardExternalWindow){toast('O navegador bloqueou a nova aba. Permita pop-ups para fechar a aba automaticamente ao acabar o tempo.',true);return;} });
  function stopRewardPings(){if(state.rewardInterval){clearInterval(state.rewardInterval);state.rewardInterval=null;}}
  async function closeModal(id){
    const el=$(`#${id}`);if(!el)return;el.classList.add('hidden');
    if(id==='site-modal'){
      stopRewardPings();$('#site-frame').src='about:blank';if(state.rewardExternalWindow&&!state.rewardExternalWindow.closed){try{state.rewardExternalWindow.close()}catch{}}state.rewardExternalWindow=null;
      try{const d=await api('/api/rewards/session',{method:'POST',body:{active:false}});state.data=d.state||state.data;updateModalTimer();}catch(e){toast(e.message,true)}
    }
  }
  document.addEventListener('click',e=>{
    const nav=e.target.closest('[data-tab]');if(nav){setTab(nav.dataset.tab);return;}
    const close=e.target.closest('[data-close-modal]');if(close){closeModal(close.dataset.closeModal);return;}
    const switcher=e.target.closest('[data-site]');if(switcher){switchSite(switcher.dataset.site);return;}
  });
  $('#site-modal')?.addEventListener('click',e=>{if(e.target.id==='site-modal')closeModal('site-modal')});
  $('#logout-btn')?.addEventListener('click',async()=>{
    if(!navigator.onLine){toast('Para sair ou trocar de conta, conecte-se primeiro. O progresso offline continuará salvo.');return;}
    try{await api('/api/logout',{method:'POST',body:{}});location.href='/';}
    catch(e){toast(e.message||'Não foi possível encerrar a sessão.',true);}
  });
  document.addEventListener('visibilitychange',()=>{
    // Não interrompe ao trocar de site dentro da janela do jogo; ao esconder o app, pausa o saldo para não drenar em segundo plano.
    if(document.hidden && !$('#site-modal').classList.contains('hidden'))return;
  });
  $('#offline-banner')?.addEventListener('click',()=>{if(syncConflict)$('#sync-conflict-modal').classList.remove('hidden');});
  $('#sync-retry')?.addEventListener('click',async()=>{if(!syncConflict)return;if(syncConflict.server?.conflict_type==='daily_evaluation'){const q=await getQueue(),idx=q.findIndex(x=>x.operationId===syncConflict.op.operationId);if(idx>=0)q.splice(idx,1);await setQueue(q);syncConflict=null;$('#sync-conflict-modal').classList.add('hidden');if(navigator.onLine){try{const r=await fetch('/api/state',{credentials:'same-origin'});if(r.ok){state.data=await r.json();await cacheState(state.data);topbar();render();}}catch{}}toast('Mantida a avaliação já confirmada no servidor.');syncQueuedOperations();updateConnectionStatus();return;}if(syncConflict.server?.conflict){const q=await getQueue(),op=q.find(x=>x.operationId===syncConflict.op.operationId);if(op){if(op.url==='/api/tasks')op.body.base_version=syncConflict.server.current_version;if(op.url==='/api/relics/activate')op.body.base_active_relic_id=syncConflict.server.current_active_relic_id??null;}await setQueue(q);$('#sync-conflict-modal').classList.add('hidden');syncConflict=null;syncQueuedOperations();updateConnectionStatus();return;}$('#sync-conflict-modal').classList.add('hidden');toast('Alteração mantida na fila. Toque no aviso para tentar novamente quando estiver pronto.');updateConnectionStatus();});
  $('#sync-discard')?.addEventListener('click',async()=>{if(!syncConflict)return;if(syncConflict.server?.conflict_type==='daily_evaluation'){ $('#sync-conflict-modal').classList.add('hidden');toast('A sincronização ficará pausada até você escolher como resolver a avaliação duplicada.');updateConnectionStatus();return;}if(!confirm('Descartar esta alteração local é irreversível. Confirmar?'))return;const q=await getQueue();const idx=q.findIndex(x=>x.operationId===syncConflict.op.operationId);if(idx>=0)q.splice(idx,1);await setQueue(q);syncConflict=null;$('#sync-conflict-modal').classList.add('hidden');if(navigator.onLine){try{const res=await fetch('/api/state',{credentials:'same-origin'});if(res.ok){state.data=await res.json();await cacheState(state.data);topbar();render();}}catch{}}toast('A alteração local foi descartada; as demais continuam na fila.');syncQueuedOperations();updateConnectionStatus();});
  window.addEventListener('online',()=>{updateConnectionStatus();syncQueuedOperations();});window.addEventListener('offline',updateConnectionStatus);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden&&navigator.onLine)syncQueuedOperations();});
  updateConnectionStatus();
  (async()=>{const cached=await cachedState();if(!navigator.onLine&&cached){state.data=cached;ensureLocalDay(state.data);await cacheState(state.data);topbar();render();}await refresh(false);if(navigator.onLine)syncQueuedOperations();})();
})();
