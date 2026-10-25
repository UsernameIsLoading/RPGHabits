"""Catálogo declarativo do RPG de hábitos. Sem lógica de aplicação/web aqui."""
RANKS = ["F", "E", "D", "C", "B", "A", "S"]
RANK_XP = {"F": 0, "E": 60, "D": 180, "C": 420, "B": 900, "A": 1860, "S": 3780}
RANK_INDEX = {r: i for i, r in enumerate(RANKS)}
RANK_STAT = {r: i + 1 for i, r in enumerate(RANKS)}

ATTRIBUTES = [
    {"code": "HP", "name": "Vida", "activity": "Dieta", "icon": "♥", "color": "red"},
    {"code": "DEF", "name": "Defesa", "activity": "Calistenia", "icon": "⬟", "color": "orange"},
    {"code": "ATK", "name": "Ataque", "activity": "Boxe", "icon": "✦", "color": "red"},
    {"code": "AGI", "name": "Agilidade", "activity": "Pular corda", "icon": "➤", "color": "cyan"},
    {"code": "MP", "name": "Mana", "activity": "Leitura da Bíblia", "icon": "◈", "color": "purple"},
    {"code": "MAG", "name": "Magia", "activity": "Estudos para concurso", "icon": "✧", "color": "violet"},
    {"code": "RES", "name": "Resistência", "activity": "Prancha", "icon": "◆", "color": "green"},
    {"code": "LUC", "name": "Sorte", "activity": "Tarefa secreta", "icon": "☘", "color": "gold"},
]
ATTR_BY_CODE = {a["code"]: a for a in ATTRIBUTES}

# `action` descreve a execução mecânica no motor de combate. Os textos vêm do catálogo aprovado,
# com as duas adaptações de stamina para RES confirmadas pelo usuário.
SKILLS = [
    # HP
    {"id":"vitalidade","name":"Vitalidade","attr":"HP","rank":"F","kind":"passive","desc":"+15 HP máximo.","action":"hp_max","amount":15},
    {"id":"regeneracao","name":"Regeneração","attr":"HP","rank":"E","kind":"passive","desc":"Recupera 2 HP ao final de cada turno de combate.","action":"regen","amount":2},
    {"id":"ultima_chance","name":"Última Chance","attr":"HP","rank":"D","kind":"passive","desc":"Uma vez por combate, abaixo de 20% do HP máximo, recupera 3 HP.","action":"last_chance","amount":3},
    {"id":"pulso_vital","name":"Pulso Vital","attr":"HP","rank":"C","kind":"active","desc":"Recupera 4 HP.","action":"heal","amount":4,"cooldown":3},
    {"id":"corpo_resiliente","name":"Corpo Resiliente","attr":"HP","rank":"B","kind":"passive","desc":"+60 HP máximo.","action":"hp_max","amount":60},
    {"id":"renascimento","name":"Renascimento","attr":"HP","rank":"A","kind":"passive","desc":"Uma vez por combate, sobrevive a um golpe fatal com 1 HP.","action":"rebirth"},
    {"id":"coracao_imortal","name":"Coração Imortal","attr":"HP","rank":"S","kind":"passive","desc":"+90 HP máximo.","action":"hp_max","amount":90},
    # DEF
    {"id":"guarda_basica","name":"Guarda Básica","attr":"DEF","rank":"F","kind":"active","desc":"Reduz o próximo golpe recebido em 1.","action":"guard","amount":1},
    {"id":"postura_firme","name":"Postura Firme","attr":"DEF","rank":"E","kind":"passive","desc":"+2 DEF enquanto estiver acima de 50% do HP.","action":"conditional_def","amount":2},
    {"id":"pele_de_pedra","name":"Pele de Pedra","attr":"DEF","rank":"D","kind":"active","desc":"+3 DEF por 2 turnos.","action":"buff_def","amount":3,"duration":2,"cooldown":4},
    {"id":"barreira","name":"Barreira","attr":"DEF","rank":"C","kind":"active","desc":"Reduz o próximo ataque recebido em 4.","action":"guard","amount":4},
    {"id":"armadura_arcana","name":"Armadura Arcana","attr":"DEF","rank":"B","kind":"passive","desc":"+5 DEF.","action":"stat_bonus","stat":"DEF","amount":5},
    {"id":"fortaleza_viva","name":"Fortaleza Viva","attr":"DEF","rank":"A","kind":"active","desc":"+6 DEF por 2 turnos.","action":"buff_def","amount":6,"duration":2,"cooldown":5},
    {"id":"defesa_absoluta","name":"Defesa Absoluta","attr":"DEF","rank":"S","kind":"active","desc":"+7 DEF por 3 turnos.","action":"buff_def","amount":7,"duration":3,"cooldown":6},
    # ATK
    {"id":"punho_reforcado","name":"Punho Reforçado","attr":"ATK","rank":"F","kind":"passive","desc":"+1 ATK.","action":"stat_bonus","stat":"ATK","amount":1},
    {"id":"golpe_direto","name":"Golpe Direto","attr":"ATK","rank":"E","kind":"active","desc":"O próximo ataque causa +2 de dano.","action":"next_attack","amount":2},
    {"id":"uppercut","name":"Uppercut","attr":"ATK","rank":"D","kind":"active","desc":"O próximo ataque causa +3 de dano.","action":"next_attack","amount":3,"cooldown":2},
    {"id":"combo_rapido","name":"Combo Rápido","attr":"ATK","rank":"C","kind":"active","desc":"Dois ataques, cada um com metade do dano básico.","action":"combo","cooldown":3},
    {"id":"quebra_guarda","name":"Quebra-Guarda","attr":"ATK","rank":"B","kind":"active","desc":"O próximo ataque ignora 5 DEF.","action":"next_ignore","amount":5,"cooldown":3},
    {"id":"punho_demolicao","name":"Punho de Demolição","attr":"ATK","rank":"A","kind":"active","desc":"O próximo ataque causa +6 de dano.","action":"next_attack","amount":6,"cooldown":4},
    {"id":"golpe_devastador","name":"Golpe Devastador","attr":"ATK","rank":"S","kind":"active","desc":"O próximo ataque causa +7 de dano e ignora 3 DEF.","action":"next_attack","amount":7,"ignore":3,"cooldown":5},
    # AGI
    {"id":"passos_leves","name":"Passos Leves","attr":"AGI","rank":"F","kind":"passive","desc":"+1 AGI.","action":"stat_bonus","stat":"AGI","amount":1},
    {"id":"arranque","name":"Arranque","attr":"AGI","rank":"E","kind":"active","desc":"+2 AGI por 1 turno.","action":"buff_agi","amount":2,"duration":1,"cooldown":3},
    {"id":"esquiva","name":"Esquiva","attr":"AGI","rank":"D","kind":"active","desc":"+3 AGI defensiva contra o próximo ataque.","action":"evasion_once","amount":3,"cooldown":3},
    {"id":"passo_fantasma","name":"Passo Fantasma","attr":"AGI","rank":"C","kind":"active","desc":"+4 AGI por 2 turnos.","action":"buff_agi","amount":4,"duration":2,"cooldown":4},
    {"id":"pos_imagem","name":"Pós-imagem","attr":"AGI","rank":"B","kind":"active","desc":"+5 AGI por 1 turno e aumenta a chance de evitar ataque.","action":"afterimage","amount":5,"duration":1,"evasion_pp":20,"cooldown":4},
    {"id":"velocidade_relampago","name":"Velocidade Relâmpago","attr":"AGI","rank":"A","kind":"active","desc":"+6 AGI por 2 turnos.","action":"buff_agi","amount":6,"duration":2,"cooldown":5},
    {"id":"movimento_absoluto","name":"Movimento Absoluto","attr":"AGI","rank":"S","kind":"active","desc":"+7 AGI por 2 turnos e age antes de inimigos mais lentos.","action":"absolute_movement","amount":7,"duration":2,"cooldown":6},
    # MP
    {"id":"reserva_espiritual","name":"Reserva Espiritual","attr":"MP","rank":"F","kind":"passive","desc":"+1 MP máximo.","action":"mp_max","amount":1},
    {"id":"meditacao","name":"Meditação","attr":"MP","rank":"E","kind":"active","desc":"Recupera 2 MP.","action":"restore_mp","amount":2,"cooldown":3},
    {"id":"conversao_energia","name":"Conversão de Energia","attr":"MP","rank":"D","kind":"active","desc":"Converte 3 MP em 3 HP.","action":"conversion","amount":3,"mp_cost":3,"cooldown":4},
    {"id":"fonte_mana","name":"Fonte de Mana","attr":"MP","rank":"C","kind":"passive","desc":"+4 MP máximo.","action":"mp_max","amount":4},
    {"id":"absorcao","name":"Absorção","attr":"MP","rank":"B","kind":"passive","desc":"Recupera 5 MP ao derrotar um inimigo.","action":"on_kill_mp","amount":5},
    {"id":"sobrecarga_espiritual","name":"Sobrecarga Espiritual","attr":"MP","rank":"A","kind":"active","desc":"A próxima habilidade recebe +6 de efeito mágico, quando aplicável.","action":"prepare_magic","amount":6,"mp_cost":6,"cooldown":4},
    {"id":"oceano_mana","name":"Oceano de Mana","attr":"MP","rank":"S","kind":"passive","desc":"+7 MP máximo.","action":"mp_max","amount":7},
    # MAG
    {"id":"intelecto","name":"Intelecto","attr":"MAG","rank":"F","kind":"passive","desc":"+1 MAG.","action":"stat_bonus","stat":"MAG","amount":1},
    {"id":"projetil_arcano","name":"Projétil Arcano","attr":"MAG","rank":"E","kind":"active","desc":"Causa dano mágico adicional de +2.","action":"magic_attack","amount":2,"mp_cost":2,"cooldown":2},
    {"id":"formula_eficiente","name":"Fórmula Eficiente","attr":"MAG","rank":"D","kind":"passive","desc":"Reduz custos de MP em 3%, acumulando a economia fracionária até 1 MP.","action":"mp_efficiency","amount":0.03},
    {"id":"circulo_arcano","name":"Círculo Arcano","attr":"MAG","rank":"C","kind":"active","desc":"A próxima magia recebe +4 MAG.","action":"prepare_mag","amount":4,"mp_cost":4,"cooldown":3},
    {"id":"analise_fraquezas","name":"Análise de Fraquezas","attr":"MAG","rank":"B","kind":"active","desc":"Revela fraqueza; o próximo ataque contra ela causa +5 de dano.","action":"weakness","amount":5,"cooldown":4},
    {"id":"amplificacao","name":"Amplificação","attr":"MAG","rank":"A","kind":"active","desc":"A próxima habilidade recebe +6 MAG.","action":"prepare_mag_any","amount":6,"mp_cost":6,"cooldown":4},
    {"id":"mente_transcendente","name":"Mente Transcendente","attr":"MAG","rank":"S","kind":"passive","desc":"+7 MAG.","action":"stat_bonus","stat":"MAG","amount":7},
    # RES — stamina foi removida e convertida em RES conforme aprovação.
    {"id":"folego","name":"Fôlego","attr":"RES","rank":"F","kind":"passive","desc":"+1 RES.","action":"stat_bonus","stat":"RES","amount":1},
    {"id":"ritmo_constante","name":"Ritmo Constante","attr":"RES","rank":"E","kind":"passive","desc":"+2 RES.","action":"stat_bonus","stat":"RES","amount":2},
    {"id":"persistencia","name":"Persistência","attr":"RES","rank":"D","kind":"passive","desc":"+3 RES.","action":"stat_bonus","stat":"RES","amount":3},
    {"id":"reserva_energia","name":"Reserva de Energia","attr":"RES","rank":"C","kind":"passive","desc":"+4 RES.","action":"stat_bonus","stat":"RES","amount":4},
    {"id":"recuperacao_folego","name":"Recuperação de Fôlego","attr":"RES","rank":"B","kind":"active","desc":"+5 RES por 2 turnos.","action":"buff_res","amount":5,"duration":2,"cooldown":4},
    {"id":"tenacidade","name":"Tenacidade","attr":"RES","rank":"A","kind":"passive","desc":"+6 RES.","action":"stat_bonus","stat":"RES","amount":6},
    {"id":"resistencia_absoluta","name":"Resistência Absoluta","attr":"RES","rank":"S","kind":"passive","desc":"+7 RES.","action":"stat_bonus","stat":"RES","amount":7},
    # LUC
    {"id":"sorte_inicial","name":"Sorte Inicial","attr":"LUC","rank":"F","kind":"passive","desc":"7% de chance de recompensa extra simples.","action":"luck","category":"extra","chance":7},
    {"id":"moeda_fortuna","name":"Moeda da Fortuna","attr":"LUC","rank":"E","kind":"passive","desc":"10% de chance de pequena recompensa extra.","action":"luck","category":"extra","chance":10},
    {"id":"olho_tesouros","name":"Olho para Tesouros","attr":"LUC","rank":"D","kind":"passive","desc":"13% de chance de item extra após a batalha.","action":"luck","category":"extra_item","chance":13},
    {"id":"boa_estrela","name":"Boa Estrela","attr":"LUC","rank":"C","kind":"passive","desc":"16% de chance de recompensa bônus.","action":"luck","category":"bonus","chance":16},
    {"id":"cacador_reliquias","name":"Caçador de Relíquias","attr":"LUC","rank":"B","kind":"passive","desc":"19% de chance de melhorar a raridade da recompensa.","action":"luck","category":"rarity","chance":19},
    {"id":"destino_favoravel","name":"Destino Favorável","attr":"LUC","rank":"A","kind":"passive","desc":"22% de chance de recompensa extra.","action":"luck","category":"extra","chance":22},
    {"id":"milagre","name":"Milagre","attr":"LUC","rank":"S","kind":"passive","desc":"25% de chance de um efeito de sorte, como recompensa extra ou melhoria de raridade.","action":"luck","category":"miracle","chance":25},
]
SKILL_BY_ID = {s["id"]: s for s in SKILLS}
SKILLS_BY_ATTRIBUTE = {a["code"]: [s for s in SKILLS if s["attr"] == a["code"]] for a in ATTRIBUTES}

# Cada efeito de item aponta para uma habilidade do catálogo. `overrides` representa apenas as
# reduções de efeito já registradas no documento (por exemplo, Círculo Arcano no item D).
ITEMS = [
    {"id":"amuleto_coracao","name":"Amuleto do Coração Vivo","rank":"F","attr":"HP","icon":"♥","desc":"Vitalidade +15 HP máximo; Regeneração cura 2 HP ao fim do turno.","effects":[{"skill":"vitalidade"},{"skill":"regeneracao"}]},
    {"id":"couraca_sobrevivente","name":"Couraça do Sobrevivente","rank":"D","attr":"HP","icon":"▰","desc":"Última Chance: recupera 3 HP abaixo de 20%, uma vez por combate; Vitalidade +15 HP máximo.","effects":[{"skill":"ultima_chance"},{"skill":"vitalidade"}]},
    {"id":"broche_fenix","name":"Broche da Fênix","rank":"B","attr":"HP","icon":"♨","desc":"Corpo Resiliente +60 HP máximo; Pulso Vital cura 4 HP, recarga 3 turnos.","effects":[{"skill":"corpo_resiliente"},{"skill":"pulso_vital"}]},
    {"id":"bracelete_guardiao","name":"Braçadeira do Guardião","rank":"F","attr":"DEF","icon":"⬟","desc":"Guarda Básica reduz o próximo golpe em 1; Postura Firme +2 DEF acima de 50% HP.","effects":[{"skill":"guarda_basica"},{"skill":"postura_firme"}]},
    {"id":"escudo_runas","name":"Escudo das Runas","rank":"D","attr":"DEF","icon":"⛨","desc":"Pele de Pedra +3 DEF por 2 turnos; Barreira reduz o próximo ataque em 4.","effects":[{"skill":"pele_de_pedra"},{"skill":"barreira"}]},
    {"id":"armadura_fortaleza","name":"Armadura da Fortaleza","rank":"B","attr":"DEF","icon":"▣","desc":"Armadura Arcana +5 DEF; Fortaleza Viva +5 DEF por 2 turnos.","effects":[{"skill":"armadura_arcana"},{"skill":"fortaleza_viva","overrides":{"amount":5}}]},
    {"id":"luvas_lutador","name":"Luvas do Lutador","rank":"F","attr":"ATK","icon":"✊","desc":"Punho Reforçado +1 ATK; Golpe Direto causa +2 dano no próximo ataque.","effects":[{"skill":"punho_reforcado"},{"skill":"golpe_direto"}]},
    {"id":"manoplas_ruptura","name":"Manoplas da Ruptura","rank":"D","attr":"ATK","icon":"✧","desc":"Uppercut +3 dano; Quebra-Guarda ignora 3 DEF no próximo ataque.","effects":[{"skill":"uppercut"},{"skill":"quebra_guarda","overrides":{"ignore":3}}]},
    {"id":"manoplas_devastacao","name":"Manoplas da Devastação","rank":"B","attr":"ATK","icon":"✹","desc":"Combo Rápido; Punho de Demolição causa +5 dano no próximo ataque.","effects":[{"skill":"combo_rapido"},{"skill":"punho_demolicao","overrides":{"amount":5}}]},
    {"id":"botas_vento","name":"Botas do Vento","rank":"F","attr":"AGI","icon":"➤","desc":"Passos Leves +1 AGI; Arranque +2 AGI por 1 turno.","effects":[{"skill":"passos_leves"},{"skill":"arranque"}]},
    {"id":"botas_espectro","name":"Botas do Espectro","rank":"D","attr":"AGI","icon":"◌","desc":"Esquiva +3 AGI defensiva; Passo Fantasma +3 AGI por 2 turnos.","effects":[{"skill":"esquiva"},{"skill":"passo_fantasma","overrides":{"amount":3}}]},
    {"id":"grevas_relampago","name":"Grevas do Relâmpago","rank":"B","attr":"AGI","icon":"ϟ","desc":"Pós-imagem +5 AGI por 1 turno; Velocidade Relâmpago +5 AGI por 2 turnos.","effects":[{"skill":"pos_imagem"},{"skill":"velocidade_relampago","overrides":{"amount":5}}]},
    {"id":"pingente_reserva","name":"Pingente da Reserva","rank":"F","attr":"MP","icon":"◈","desc":"Reserva Espiritual +1 MP máximo; Meditação recupera 2 MP.","effects":[{"skill":"reserva_espiritual"},{"skill":"meditacao"}]},
    {"id":"calice_conversao","name":"Cálice da Conversão","rank":"D","attr":"MP","icon":"♜","desc":"Conversão de Energia: 3 MP por 3 HP; Fonte de Mana +3 MP máximo.","effects":[{"skill":"conversao_energia"},{"skill":"fonte_mana","overrides":{"amount":3}}]},
    {"id":"cajado_fluxo","name":"Cajado do Fluxo Infinito","rank":"B","attr":"MP","icon":"╋","desc":"Absorção recupera 5 MP por inimigo derrotado; Sobrecarga Espiritual +5 efeito mágico.","effects":[{"skill":"absorcao"},{"skill":"sobrecarga_espiritual","overrides":{"amount":5}}]},
    {"id":"anel_aprendiz","name":"Anel do Aprendiz","rank":"F","attr":"MAG","icon":"✧","desc":"Intelecto +1 MAG; Projétil Arcano +2 dano mágico.","effects":[{"skill":"intelecto"},{"skill":"projetil_arcano"}]},
    {"id":"grimorio_eficiencia","name":"Grimório da Eficiência","rank":"D","attr":"MAG","icon":"▤","desc":"Fórmula Eficiente reduz custo de MP em 3%; Círculo Arcano recebe +3 MAG.","effects":[{"skill":"formula_eficiente"},{"skill":"circulo_arcano","overrides":{"amount":3}}]},
    {"id":"bastao_analise","name":"Bastão da Análise","rank":"B","attr":"MAG","icon":"⌁","desc":"Análise de Fraquezas +5 dano; Amplificação +5 MAG na próxima habilidade.","effects":[{"skill":"analise_fraquezas"},{"skill":"amplificacao","overrides":{"amount":5}}]},
    {"id":"faixa_resistencia","name":"Faixa da Resistência","rank":"F","attr":"RES","icon":"≈","desc":"Fôlego +1 RES; Ritmo Constante +2 RES.","effects":[{"skill":"folego"},{"skill":"ritmo_constante"}]},
    {"id":"peitoral_persistencia","name":"Peitoral da Persistência","rank":"D","attr":"RES","icon":"▣","desc":"Persistência +3 RES; Reserva de Energia ajustada para +3 RES.","effects":[{"skill":"persistencia"},{"skill":"reserva_energia","overrides":{"amount":3}}]},
    {"id":"grevas_tenacidade","name":"Grevas da Tenacidade","rank":"B","attr":"RES","icon":"⬟","desc":"Recuperação de Fôlego +5 RES por 2 turnos; Tenacidade ajustada para +5 RES.","effects":[{"skill":"recuperacao_folego"},{"skill":"tenacidade","overrides":{"amount":5}}]},
    {"id":"moeda_acaso","name":"Moeda do Acaso","rank":"F","attr":"LUC","icon":"●","desc":"Sorte Inicial 7%; Moeda da Fortuna 10%. Usar a maior chance aplicável.","effects":[{"skill":"sorte_inicial"},{"skill":"moeda_fortuna"}]},
    {"id":"bussola_cacador","name":"Bússola do Caçador","rank":"D","attr":"LUC","icon":"⌖","desc":"Olho para Tesouros 13%; Boa Estrela 16%. Verificações por categoria.","effects":[{"skill":"olho_tesouros"},{"skill":"boa_estrela"}]},
    {"id":"anel_fortuna","name":"Anel da Fortuna","rank":"B","attr":"LUC","icon":"☘","desc":"Caçador de Relíquias 19%; Destino Favorável ajustado a 19%.","effects":[{"skill":"cacador_reliquias"},{"skill":"destino_favoravel","overrides":{"chance":19}}]},
]
ITEM_BY_ID = {i["id"]: i for i in ITEMS}

MONSTERS = [
    {"id":"goblin_saqueador","name":"Goblin Saqueador","tier":"common","rank":"F","icon":"👺","style":"Apressado e oportunista.","stats":{"ATK":2,"AGI":1},"skills":[{"id":"golpe_direto"}],"loot":["moeda_acaso"]},
    {"id":"esqueleto_vigia","name":"Esqueleto Vigia","tier":"common","rank":"F","icon":"💀","style":"Resistente, segura a posição.","stats":{"DEF":2,"RES":1},"skills":[{"id":"guarda_basica"}],"loot":["amuleto_coracao"]},
    {"id":"aranha_venenosa","name":"Aranha Venenosa","tier":"common","rank":"F","icon":"🕷️","style":"Ágil e evasiva.","stats":{"AGI":2,"MAG":1},"skills":[{"id":"esquiva"}],"loot":["botas_vento"]},
    {"id":"javali_pedra","name":"Javali de Pedra","tier":"common","rank":"F","icon":"🐗","style":"Investidas pesadas.","stats":{"ATK":2,"DEF":1},"skills":[{"id":"uppercut"}],"loot":["faixa_resistencia"]},
    {"id":"fagulha_espectral","name":"Fagulha Espectral","tier":"common","rank":"F","icon":"🔥","style":"Ataques mágicos.","stats":{"MAG":2,"MP":2,"RES":1},"skills":[{"id":"projetil_arcano"}],"loot":["pingente_reserva"]},
    {"id":"diabrete_catador","name":"Diabrete Catador","tier":"common","rank":"F","icon":"😈","style":"Persistente; explora aberturas.","stats":{"AGI":1,"LUC":2,"RES":1},"skills":[{"id":"ritmo_constante"}],"loot":["anel_aprendiz"]},
    {"id":"orc_quebra_cranios","name":"Orc Quebra-Crânios","tier":"strong","rank":"C","icon":"👹","style":"Pressão física e quebra de defesa.","stats":{"ATK":2,"DEF":1,"HP":1},"skills":[{"id":"quebra_guarda"},{"id":"punho_demolicao"}],"loot":["armadura_fortaleza","peitoral_persistencia"]},
    {"id":"assassina_veu","name":"Assassina do Véu","tier":"strong","rank":"C","icon":"🗡️","style":"Velocidade e ataques em sequência.","stats":{"AGI":2,"ATK":1,"LUC":1},"skills":[{"id":"passo_fantasma"},{"id":"combo_rapido"}],"loot":["escudo_runas","bussola_cacador"]},
    {"id":"arqui_esqueleto","name":"Arqui-esqueleto","tier":"strong","rank":"B","icon":"☠️","style":"Estratégico, explora fraquezas.","stats":{"MAG":2,"RES":2,"MP":1},"skills":[{"id":"formula_eficiente"},{"id":"analise_fraquezas"}],"loot":["calice_conversao","cajado_fluxo"]},
    {"id":"colosso_jade","name":"Colosso de Jade","tier":"strong","rank":"B","icon":"🗿","style":"Defensivo e difícil de derrubar.","stats":{"HP":1,"DEF":2,"RES":2},"skills":[{"id":"fortaleza_viva","overrides":{"amount":5}},{"id":"recuperacao_folego"}],"loot":["botas_espectro","grevas_relampago"]},
    {"id":"rei_carmesim","name":"Rei Carmesim","tier":"boss","rank":"A","icon":"👑","style":"Chefe versátil com cura, velocidade e magia.","stats":{"HP":2,"ATK":1,"AGI":1,"MAG":1},"skills":[{"id":"pulso_vital"},{"id":"pos_imagem"},{"id":"circulo_arcano","overrides":{"amount":5}},{"id":"boa_estrela"}],"loot":["couraca_sobrevivente","manoplas_ruptura","grevas_tenacidade","bastao_analise"]},
    {"id":"dragao_eclipse","name":"Dragão do Eclipse","tier":"boss","rank":"S","icon":"🐉","style":"Poder bruto, quebra de defesa e magia amplificada.","stats":{"HP":2,"ATK":2,"MAG":2,"DEF":1},"skills":[{"id":"barreira"},{"id":"quebra_guarda"},{"id":"velocidade_relampago","overrides":{"amount":5}},{"id":"amplificacao","overrides":{"amount":5}}],"loot":["broche_fenix","manoplas_devastacao","grimorio_eficiencia","anel_fortuna"]},
]
MONSTER_BY_ID = {m["id"]: m for m in MONSTERS}

CONSUMABLES = {
    "pocao_cura": {"id":"pocao_cura","name":"Poção de Cura","icon":"🧪","desc":"Recupera 8 HP, sem ultrapassar o HP máximo.","effect":"heal","amount":8},
    "pocao_mana": {"id":"pocao_mana","name":"Poção de Mana","icon":"🔮","desc":"Recupera 6 MP, sem ultrapassar o MP máximo.","effect":"mana","amount":6},
}

# Cada equipamento tem uma única fonte de drop entre os monstros. Dois itens F do catálogo
# permanecem disponíveis para serem obtidos em atualizações/mercado futuro, sem duplicar fontes.
assert len(ITEMS) == 24
assert len(SKILLS) == 56
assert all(len(m["loot"]) == {"common":1,"strong":2,"boss":4}[m["tier"]] for m in MONSTERS)
assert len({item_id for m in MONSTERS for item_id in m["loot"]}) == sum(len(m["loot"]) for m in MONSTERS)
assert all(ITEM_BY_ID[item_id]["rank"] not in ("F", "E") for m in MONSTERS if m["tier"] == "boss" for item_id in m["loot"])
