(() => {
  'use strict';
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
  const esc = (v = '') => String(v).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const ATTR_CODES = ['HP','DEF','ATK','AGI','MP','MAG','RES','LUC'];
  const state = { data:null, tab:'attributes', selectedAttr:'HP', site:'youtube', chart:null, chartSettings:{a:'HP',b:'',days:'30',group:'day'}, toastTimer:null, rewardInterval:null, rewardExternalWindow:null, storyUrl:'https://novelmania.com.br/novels/necromante-da-estacao-de-seul' };
  const sites = {
    youtube:{title:'YouTube',url:'https://www.youtube.com',icon:'▶',desc:'Vídeos, aulas e conteúdos selecionados.'},
    wikipedia:{title:'Wikipedia',url:'https://pt.wikipedia.org/wiki/P%C3%A1gina_principal',icon:'◎',desc:'Pesquisa e leitura de conhecimento.'},
    webtoon:{title:'WEBTOON',url:'https://www.webtoons.com/pt/',icon:'▤',desc:'Leitura de quadrinhos e histórias.'},
    chatgpt:{title:'ChatGPT',url:'https://chatgpt.com/',icon:'✧',desc:'Ferramenta de estudo e conversa.'}
  };
  function toast(message, error=false) {
    const el=$('#toast'); if(!el) return;
    el.textContent=message; el.classList.toggle('error',error); el.classList.add('show');
    clearTimeout(state.toastTimer); state.toastTimer=setTimeout(()=>el.classList.remove('show'),3500);
  }
  async function api(url, options={}) {
    const headers={...(options.headers||{})};
    if(options.body && typeof options.body!=='string'){headers['Content-Type']='application/json';options.body=JSON.stringify(options.body);}
    const res=await fetch(url,{...options,headers,credentials:'same-origin'});
    let data; try{data=await res.json()}catch{data={ok:false,error:'Resposta inesperada do servidor.'}}
    if(res.status===401){location.href='/'; throw new Error('Sua sessão expirou. Entre novamente.');}
    if(!res.ok || data.ok===false) throw new Error(data.error||'Não foi possível concluir a ação.');
    if(data.state) state.data=data.state;
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
    $('#dungeon-nav-dot').classList.toggle('hidden',!state.data.dungeon);
  }
  async function refresh(keepScroll=true){
    const scroll=window.scrollY;
    try{const d=await api('/api/state');state.data=d;topbar();render();if(keepScroll)window.scrollTo({top:scroll,behavior:'instant'});}catch(e){toast(e.message,true);}
  }
  function setTab(tab){state.tab=tab;$$('.nav-link').forEach(b=>b.classList.toggle('active',b.dataset.tab===tab));render();window.scrollTo({top:0,behavior:'smooth'});}
  function render(){
    if(!state.data)return;
    topbar();
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
    const evaluation=done?`<div class="eval-complete">✓ Autoavaliação concluída hoje: ${done.xp} XP. Você só pode avaliar este atributo uma vez por dia.</div>`:`<div class="eval-buttons">${[{s:0,t:'Não fiz',d:'0 XP'},{s:3,t:'Fácil',d:'+3 XP'},{s:6,t:'Médio',d:'+6 XP'},{s:9,t:'Difícil',d:'+9 XP'}].map(o=>`<button class="eval-option" data-eval="${o.s}" data-code="${a.code}"><strong>${o.s}</strong><span>${o.t}</span><small>${o.d}</small></button>`).join('')}</div><p class="muted" style="font-size:10px;margin:10px 0 0">0 XP conta como avaliação feita. Máximo total: 72 XP por dia.</p>`;
    const records=activities.length?activities.map(r=>`<article class="activity-row"><span class="activity-mark">↗</span><div class="activity-copy"><strong>${esc(r.title)}</strong>${r.note?`<p>${esc(r.note)}</p>`:''}<time>${esc(r.created_at.replace('T',' '))}</time></div>${r.value!==null&&r.value!==undefined?`<span class="activity-value">${esc(r.value)}</span>`:''}<div class="activity-actions"><button class="tiny-icon" title="Editar" data-edit-activity="${r.id}">✎</button><button class="tiny-icon" title="Excluir" data-delete-activity="${r.id}">×</button></div></article>`).join(''):`<div class="empty-state"><strong>Nenhum registro ainda.</strong>Use o formulário para registrar uma atividade ou medida. Isso não concede XP.</div>`;
    const equipment=inv.equipment;
    return `${renderHeading('Atributos','Transforme hábitos reais em progressão persistente.',`<span class="badge red">${p.today_xp} XP HOJE</span><span class="badge">F → S</span>`)}
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
      </section>`;
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
    const p=state.data.player;
    const products=[
      {id:'pocao_cura',icon:'🧪',name:'Poção de Cura',desc:'Recupera até 8 HP.',price:30,qty:p.inventory.consumables.find(x=>x.id==='pocao_cura')?.quantity||0},
      {id:'pocao_mana',icon:'🔮',name:'Poção de Mana',desc:'Recupera até 6 MP.',price:30,qty:p.inventory.consumables.find(x=>x.id==='pocao_mana')?.quantity||0},
      {id:'bracelete_salvacao',icon:'🛡️',name:'Bracelete da Salvação',desc:'Uso único: preserva equipamentos do loot se você morrer na dungeon.',price:500,qty:p.inventory.bracelete_salvacao||0},
      {id:'ticket_dungeon',icon:'🎟️',name:'Ticket de Dungeon',desc:'Permite iniciar uma exploração extra além do limite semanal.',price:600,qty:p.inventory.ticket_dungeon||0},
      {id:'minute',icon:'⏱️',name:'1 minuto adicional',desc:'Adiciona 60 segundos ao saldo especial permanente.',price:1000,qty:null}
    ];
    return `${renderHeading('Loja','Gaste suas moedas em consumíveis, segurança e tempo extra.',`<span class="badge red">◉ ${Number(p.coins).toLocaleString('pt-BR')} MOEDAS</span>`)}
      <div class="site-grid">${products.map(it=>`<article class="card site-card"><span class="site-icon">${it.icon}</span><h3>${esc(it.name)}</h3><p>${esc(it.desc)}</p>${it.qty!==null?`<small class="muted">No inventário: ${it.qty}</small>`:''}<button class="primary" data-buy-item="${it.id}" ${Number(p.coins)<it.price?'disabled':''}>Comprar · ${it.price.toLocaleString('pt-BR')} moedas</button></article>`).join('')}</div>
      <p class="muted" style="margin-top:16px">As compras são descontadas imediatamente. O bracelete só é consumido quando salva o loot de uma derrota; o ticket só é consumido ao entrar além do limite semanal.</p>`;
  }
  function renderRewards(){
    const p=state.data.player;const story=p.story;
    const daily=p.daily_reward_seconds||0;const special=p.special_reward_seconds||0;
    const sitesHtml=Object.entries(sites).map(([key,s])=>`<article class="card site-card"><span class="site-icon">${esc(s.icon)}</span><h3>${esc(s.title)}</h3><p>${esc(s.desc)}</p><button class="primary" data-open-site="${key}">Abrir janela ↗</button></article>`).join('');
    const oddUnlocked=story.physical_chapters>0?Array.from({length:Math.min(story.physical_chapters,30)},(_,i)=>2*(i+1)-1):[];
    const evenUnlocked=story.study_chapters>0?Array.from({length:Math.min(story.study_chapters,30)},(_,i)=>2*(i+1)):[];
    const storyTiles=(oddUnlocked.map(n=>({n,type:'physical',label:'Treino físico'})).concat(evenUnlocked.map(n=>({n,type:'study',label:'Estudos'}))).sort((a,b)=>a.n-b.n));
    return `${renderHeading('Recompensas','Desbloqueie tempo de lazer com tarefas cumpridas e chefes derrotados.',`<span class="badge red">${humanDuration(daily)} DIÁRIO</span>`)}
      <section class="card reward-balance"><span class="reward-balance-icon">◷</span><div class="reward-balance-copy"><p class="eyebrow">TEMPO DISPONÍVEL</p><strong id="reward-daily-display">${humanDuration(daily)}</strong><small>Saldo diário · até 20 minutos gerados hoje</small></div><div class="reward-balance-special"><small>SALDO ESPECIAL PERMANENTE</small><strong id="reward-special-display">${humanDuration(special)}</strong><small>Chefes derrotados</small></div></section>
      <div class="sub-section-title" style="margin-top:23px"><h3>Janelas de recompensa</h3><span class="badge">O TEMPO CONTA COM A JANELA ABERTA</span></div><div class="site-grid">${sitesHtml}</div><p class="muted" style="font-size:10px;margin:0 0 25px">Os sites abrem numa janela dentro do jogo. Alguns serviços bloqueiam incorporação; nesse caso, o botão de nova aba serve como alternativa. O cronômetro continua enquanto a janela está aberta.</p>
      <section class="card story-card"><div><p class="eyebrow">RECOMPENSA DE HISTÓRIA</p><h2>Necromante da Estação de Seul</h2><p>Treino físico desbloqueia capítulos ímpares; estudos para concurso desbloqueiam capítulos pares. O jogo guarda o progresso, mas a leitura é feita diretamente na fonte oficial.</p><div class="chapter-tile ${story.physical_chapters?'':'locked'}"><span class="chapter-num">${story.physical_chapters?2*story.physical_chapters-1:'—'}</span><div><strong>Trilha de treinamento</strong><small>${story.physical_chapters?`${story.physical_chapters} capítulo(s) ímpar(es) desbloqueado(s)`:'Conclua uma tarefa física para desbloquear o capítulo 1'}</small></div>${story.physical_chapters?`<button class="secondary small-btn" data-open-story="${2*story.physical_chapters-1}">Ler ↗</button>`:''}</div><div class="chapter-tile ${story.study_chapters?'':'locked'}"><span class="chapter-num">${story.study_chapters?2*story.study_chapters:'—'}</span><div><strong>Trilha de estudos</strong><small>${story.study_chapters?`${story.study_chapters} capítulo(s) par(es) desbloqueado(s)`:'Conclua Estudos para concurso para desbloquear o capítulo 2'}</small></div>${story.study_chapters?`<button class="secondary small-btn" data-open-story="${2*story.study_chapters}">Ler ↗</button>`:''}</div></div>
        <div><p class="eyebrow">CAPÍTULOS DISPONÍVEIS</p>${storyTiles.length?storyTiles.slice(-12).map(ch=>`<div class="chapter-tile"><span class="chapter-num">${ch.n}</span><div><strong>Capítulo ${ch.n}</strong><small>Desbloqueado por ${ch.type==='physical'?'treinamento físico':'estudos'}</small></div><button class="ghost small-btn" data-open-story="${ch.n}">Abrir ↗</button></div>`).join(''):`<div class="empty-state"><strong>Nenhum capítulo desbloqueado.</strong>Conclua uma avaliação positiva de treino ou de estudos.</div>`}<div style="margin-top:12px"><button class="secondary full" data-open-story="0">Abrir página oficial da novel ↗</button></div></div></section>
      <section class="card content-card sub-section"><div class="card-head"><div><h2>Como o tempo é conquistado</h2><p>Regras de recompensa.</p></div></div><div class="grid grid-3"><div class="dungeon-state-card"><small>TAREFA POSITIVA</small><strong>+2m30s</strong><p class="muted" style="font-size:10px">Cada atributo cumprido pode conceder tempo, até 20 min por dia.</p></div><div class="dungeon-state-card"><small>CHEFE DERROTADO</small><strong>+40 min</strong><p class="muted" style="font-size:10px">Saldo especial persistente, consumido depois do saldo diário.</p></div><div class="dungeon-state-card"><small>ORDEM DE CONSUMO</small><strong>Diário → Especial</strong><p class="muted" style="font-size:10px">O saldo diário não usado expira na virada do dia.</p></div></div></section>`;
  }
  function bindPageEvents(){
    $$('[data-attribute]').forEach(b=>b.addEventListener('click',()=>{state.selectedAttr=b.dataset.attribute;render()}));
    $$('[data-eval]').forEach(b=>b.addEventListener('click',async()=>{
      try{const d=await api('/api/evaluations',{method:'POST',body:{attribute:b.dataset.code,score:Number(b.dataset.eval)}});state.data=d.state;render();toast(d.message||'Autoavaliação registrada.');}catch(e){toast(e.message,true)}
    }));
    const activityForm=$('#activity-form');if(activityForm)activityForm.addEventListener('submit',async e=>{
      e.preventDefault();const fd=new FormData(activityForm);const body={attribute:activityForm.dataset.activityAttr,title:fd.get('title'),value:fd.get('value'),note:fd.get('note')};
      try{const d=await api('/api/activities',{method:'POST',body});state.data=d.state;render();toast(d.message);}catch(err){toast(err.message,true)}
    });
    $$('[data-delete-activity]').forEach(b=>b.addEventListener('click',async()=>{
      if(!confirm('Excluir este registro? O XP não será alterado.'))return;
      try{const d=await api(`/api/activities/${b.dataset.deleteActivity}`,{method:'DELETE'});state.data=d.state;render();toast(d.message);}catch(e){toast(e.message,true)}
    }));
    $$('[data-edit-activity]').forEach(b=>b.addEventListener('click',async()=>{
      const r=state.data.activities.find(x=>x.id===Number(b.dataset.editActivity));if(!r)return;
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
    $$('[data-open-story]').forEach(b=>b.addEventListener('click',()=>openStory(Number(b.dataset.openStory))));
  }
  async function combatAction(action){
    try{const d=await api('/api/dungeon/action',{method:'POST',body:action});state.data=d.state;render();toast(d.message||'Ação realizada.');}catch(e){toast(e.message,true)}
  }
  async function loadChart(){
    if(state.tab!=='dashboard')return;
    const a=$('#chart-a')?.value||state.chartSettings.a;
    const b=$('#chart-b')?.value??state.chartSettings.b;
    const days=$('#chart-days')?.value||state.chartSettings.days;
    const group=$('#chart-group')?.value||state.chartSettings.group;
    state.chartSettings={a,b,days,group};
    try{
      const d=await api(`/api/charts?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}&days=${encodeURIComponent(days)}&group=${group}`);
      const labels=d.data.map(x=>x.label);
      const sets=[{
        label:`${a} · média`,data:d.data.map(x=>x[a]),borderColor:'#f35b6b',
        backgroundColor:'#f35b6b22',spanGaps:true,tension:.25,pointRadius:3
      }];
      if(b)sets.push({
        label:`${b} · média`,data:d.data.map(x=>x[b]),borderColor:'#b7a0ff',
        backgroundColor:'#b7a0ff22',spanGaps:true,tension:.25,pointRadius:3
      });
      const hasValues=d.data.some(row=>row[a]!==null||(b&&row[b]!==null));
      $('#chart-placeholder')?.classList.toggle('hidden',hasValues);
      $('#performance-chart')?.classList.toggle('hidden',!hasValues);
      if(window.Chart&&$('#performance-chart')){
        if(state.chart){state.chart.destroy();state.chart=null;}
        state.chart=new Chart($('#performance-chart'),{
          type:'line',data:{labels,datasets:sets},
          options:{responsive:true,maintainAspectRatio:false,interaction:{mode:'index',intersect:false},
            plugins:{legend:{labels:{color:'#aeb4c3',usePointStyle:true,boxWidth:7,font:{size:10}}}},
            scales:{
              x:{ticks:{color:'#7e8595',font:{size:10}},grid:{color:'#292d38'}},
              y:{beginAtZero:false,ticks:{color:'#7e8595',font:{size:10}},grid:{color:'#292d38'}}
            }
          }
        });
      }else if($('#chart-placeholder')){
        $('#chart-placeholder').classList.remove('hidden');
        $('#chart-placeholder').textContent=hasValues?`Chart.js não carregou. ${d.data.length} intervalos disponíveis.`:'Ainda não há medidas numéricas neste período.';
      }
      const summary=$('#chart-summary');
      if(summary)summary.textContent=`${d.data.length} intervalo(s) · agrupamento por ${group==='day'?'dia':group==='week'?'semana':'mês'} · médias dos registros numéricos.`;
    }catch(e){toast(e.message,true)}
  }
  async function openSite(key){
    if(!sites[key])return;
    try{const d=await api('/api/rewards/session',{method:'POST',body:{active:true}});state.data=d.state||state.data;state.site=key;$('#site-modal-title').textContent=sites[key].title;$('#site-frame').src=sites[key].url;$('#site-external').href=sites[key].url;$('#site-modal').classList.remove('hidden');updateModalTimer();$$('#site-switcher button').forEach(b=>b.classList.toggle('active',b.dataset.site===key));startRewardPings();}catch(e){toast(e.message,true)}
  }
  function switchSite(key){
    if(!sites[key])return;state.site=key;$('#site-modal-title').textContent=sites[key].title;$('#site-frame').src=sites[key].url;$('#site-external').href=sites[key].url;$$('#site-switcher button').forEach(b=>b.classList.toggle('active',b.dataset.site===key));
  }
  function openStory(chapter){
    const base=state.data?.player?.story?.novel_url||state.storyUrl;
    const url=chapter>0?`${base}/capitulos/volume-1-capitulo-${chapter}`:base;
    $('#story-modal-title').textContent=chapter>0?`Necromante da Estação de Seul · Capítulo ${chapter}`:'Necromante da Estação de Seul';
    $('#story-frame').src=url;$('#story-external').href=url;$('#story-modal').classList.remove('hidden');
    if(chapter>0)toast(`Abrindo o capítulo ${chapter} na fonte oficial.`);
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
    }else{$('#story-frame').src='about:blank';}
  }
  document.addEventListener('click',e=>{
    const nav=e.target.closest('[data-tab]');if(nav){setTab(nav.dataset.tab);return;}
    const close=e.target.closest('[data-close-modal]');if(close){closeModal(close.dataset.closeModal);return;}
    const switcher=e.target.closest('[data-site]');if(switcher){switchSite(switcher.dataset.site);return;}
  });
  $('#site-modal')?.addEventListener('click',e=>{if(e.target.id==='site-modal')closeModal('site-modal')});
  $('#story-modal')?.addEventListener('click',e=>{if(e.target.id==='story-modal')closeModal('story-modal')});
  $('#logout-btn')?.addEventListener('click',async()=>{try{await api('/api/logout',{method:'POST',body:{}})}catch{}location.href='/'});
  document.addEventListener('visibilitychange',()=>{
    // Não interrompe ao trocar de site dentro da janela do jogo; ao esconder o app, pausa o saldo para não drenar em segundo plano.
    if(document.hidden && !$('#site-modal').classList.contains('hidden'))return;
  });
  refresh(false);
})();
