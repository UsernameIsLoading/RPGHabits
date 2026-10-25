"""Motor de progressão, dungeon, loot e combate. Usa apenas a biblioteca padrão."""
from __future__ import annotations
import copy, math, random
from datetime import date, datetime, timezone
from typing import Any
from game_data import (
    ATTRIBUTES, ATTR_BY_CODE, RANKS, RANK_INDEX, RANK_XP, RANK_STAT,
    SKILLS, SKILL_BY_ID, SKILLS_BY_ATTRIBUTE, ITEMS, ITEM_BY_ID,
    MONSTERS, MONSTER_BY_ID, CONSUMABLES,
)

GRID = 6
POTION_START = {"pocao_cura": 2, "pocao_mana": 2}
DAILY_REWARD_PER_TASK = 150
DAILY_REWARD_CAP = 1200
WEEKLY_DUNGEON_LIMIT = 2


def rank_for_xp(xp: int) -> str:
    rank = "F"
    for r in RANKS:
        if xp >= RANK_XP[r]:
            rank = r
    return rank


def rank_summary(xp_by_attr: dict[str, int]) -> dict[str, dict[str, Any]]:
    out = {}
    for attr in ATTRIBUTES:
        code = attr["code"]
        xp = int(xp_by_attr.get(code, 0))
        rank = rank_for_xp(xp)
        next_rank = RANKS[min(RANK_INDEX[rank] + 1, len(RANKS) - 1)]
        threshold = RANK_XP[next_rank] if rank != "S" else RANK_XP["S"]
        out[code] = {"xp": xp, "rank": rank, "rank_index": RANK_INDEX[rank], "next_rank": None if rank == "S" else next_rank,
                     "next_xp": None if rank == "S" else threshold, "progress": 100 if rank == "S" else max(0, min(100, round((xp - RANK_XP[rank]) / (threshold - RANK_XP[rank]) * 100)))}
    return out


def active_equipment(equipped: dict[str, str] | None) -> list[dict]:
    result = []
    for item_id in (equipped or {}).values():
        if item_id in ITEM_BY_ID:
            result.append(ITEM_BY_ID[item_id])
    return result


def effective_skills(xp_by_attr: dict[str, int], equipped: dict[str, str] | None = None,
                     extra_skills: list[dict] | None = None) -> dict[str, dict]:
    """Une skills desbloqueadas e efeitos de equipamento; a mesma skill só conta uma vez.
    Quando duas fontes concedem a mesma skill, fica a versão de maior efeito numérico.
    """
    ranks = rank_summary(xp_by_attr)
    found: dict[str, dict] = {}
    for s in SKILLS:
        if RANK_INDEX[s["rank"]] <= ranks[s["attr"]]["rank_index"]:
            found[s["id"]] = copy.deepcopy(s)
    for item in active_equipment(equipped):
        for eff in item["effects"]:
            base = copy.deepcopy(SKILL_BY_ID[eff["skill"]])
            base.update(copy.deepcopy(eff.get("overrides", {})))
            base["source_item"] = item["id"]
            old = found.get(base["id"])
            if old is None or _skill_power(base) > _skill_power(old):
                found[base["id"]] = base
    for custom in extra_skills or []:
        sid = custom.get("id")
        if sid in SKILL_BY_ID:
            base = copy.deepcopy(SKILL_BY_ID[sid])
            base.update(copy.deepcopy(custom.get("overrides", {})))
            if sid not in found or _skill_power(base) > _skill_power(found[sid]):
                found[sid] = base
    return found


def _skill_power(skill: dict) -> tuple[float, int]:
    amount = skill.get("amount", 0)
    chance = skill.get("chance", 0)
    try: amount = float(amount)
    except (TypeError, ValueError): amount = 0
    try: chance = float(chance)
    except (TypeError, ValueError): chance = 0
    return (max(amount, chance), RANK_INDEX.get(skill.get("rank", "F"), 0))


def compute_player_stats(xp_by_attr: dict[str, int], equipped: dict[str, str] | None = None,
                         current_hp: int | None = None, current_mp: int | None = None,
                         combat: dict | None = None) -> dict[str, Any]:
    ranks = rank_summary(xp_by_attr)
    skills = effective_skills(xp_by_attr, equipped)
    attr_values = {c: RANK_STAT[ranks[c]["rank"]] for c in ("DEF", "ATK", "AGI", "MAG", "RES", "LUC")}
    for skill in skills.values():
        if skill.get("kind") == "passive" and skill.get("action") == "stat_bonus":
            stat = skill.get("stat")
            if stat in attr_values:
                attr_values[stat] += int(skill.get("amount", 0))
    # Postura Firme é condicional e calculada depois do HP máximo.
    hp_max = 10 + 15 * ranks["HP"]["rank_index"]
    mp_max = 10 + 15 * ranks["MP"]["rank_index"]
    for s in skills.values():
        if s.get("kind") == "passive" and s.get("action") == "hp_max": hp_max += int(s.get("amount", 0))
        if s.get("kind") == "passive" and s.get("action") == "mp_max": mp_max += int(s.get("amount", 0))
    hp = hp_max if current_hp is None else max(0, min(int(current_hp), hp_max))
    mp = mp_max if current_mp is None else max(0, min(int(current_mp), mp_max))
    if hp > hp_max * 0.5 and "postura_firme" in skills:
        attr_values["DEF"] += int(skills["postura_firme"].get("amount", 2))
    # Buffs transitórios e guarda existem apenas durante uma luta.
    if combat:
        for buff in combat.get("buffs", []):
            stat = buff.get("stat")
            if stat in attr_values and int(buff.get("remaining", 0)) > 0:
                attr_values[stat] += int(buff.get("amount", 0))
        if combat.get("defensive_agi_once"):
            attr_values["AGI"] += int(combat["defensive_agi_once"].get("amount", 0))
    return {"ranks": ranks, "stats": attr_values, "hp": hp, "hp_max": hp_max, "mp": mp, "mp_max": mp_max, "skills": skills}


def player_luck_chances(xp_by_attr: dict[str, int], equipped: dict[str, str] | None) -> dict[str, int]:
    skills = effective_skills(xp_by_attr, equipped)
    chances: dict[str, int] = {}
    for s in skills.values():
        if s.get("action") == "luck":
            cat = s.get("category", "extra")
            chances[cat] = max(chances.get(cat, 0), int(s.get("chance", 0)))
    return chances


def _average_rank(xp_by_attr: dict[str, int]) -> int:
    summary = rank_summary(xp_by_attr)
    return round(sum(summary[a["code"]]["rank_index"] for a in ATTRIBUTES) / len(ATTRIBUTES))


def make_enemy(monster_id: str, xp_by_attr: dict[str, int], rng: random.Random | None = None) -> dict:
    rng = rng or random.Random()
    spec = copy.deepcopy(MONSTER_BY_ID[monster_id])
    player_rank = _average_rank(xp_by_attr)
    if spec["tier"] == "common": enemy_rank = player_rank
    else: enemy_rank = min(len(RANKS)-1, player_rank + 1)
    enemy_rank_name = RANKS[enemy_rank]
    scale = RANK_STAT[enemy_rank_name]
    hp_max = 10 + 15 * enemy_rank
    if spec["tier"] == "strong": hp_max += 8
    elif spec["tier"] == "boss": hp_max += 18
    mp_max = 10 + 15 * enemy_rank
    stats = {a: scale for a in ("ATK", "DEF", "AGI", "MAG", "RES", "LUC")}
    for stat, bonus in spec.get("stats", {}).items():
        if stat in stats: stats[stat] += int(bonus)
        elif stat == "HP": hp_max += int(bonus) * 2
        elif stat == "MP": mp_max += int(bonus) * 2
    skills = {}
    for row in spec["skills"]:
        sid = row["id"]
        if sid in SKILL_BY_ID:
            s = copy.deepcopy(SKILL_BY_ID[sid])
            s.update(copy.deepcopy(row.get("overrides", {})))
            skills[sid] = s
            # Passivas da criatura afetam os atributos do inimigo sem duplicar a mesma skill.
            if s.get("kind") == "passive":
                if s.get("action") == "stat_bonus" and s.get("stat") in stats: stats[s["stat"]] += int(s.get("amount", 0))
                elif s.get("action") == "hp_max": hp_max += int(s.get("amount", 0))
                elif s.get("action") == "mp_max": mp_max += int(s.get("amount", 0))
    return {"id": spec["id"], "name": spec["name"], "icon": spec["icon"], "tier": spec["tier"],
            "catalog_rank": spec["rank"], "rank": enemy_rank_name, "style": spec["style"], "stats": stats,
            "hp": hp_max, "hp_max": hp_max, "mp": mp_max, "mp_max": mp_max,
            "skills": list(skills.values()), "cooldowns": {}, "buffs": [], "guard_reduction": 0,
            "defensive_agi_once": None, "next_attack": {"bonus":0,"ignore":0}, "pending": [],
            "last_chance_used": False, "rebirth_used": False, "turn": 0, "weakness_revealed": False}


def new_floor(run: dict, xp_by_attr: dict[str, int], rng: random.Random | None = None) -> dict:
    rng = rng or random.Random()
    n = int(run["floor"])
    total = int(run["floors"])
    objects = []
    stair = {"x": GRID-1, "y": GRID-1}
    occupied = {(0,0), (stair["x"], stair["y"])}
    if n == total:
        boss_id = rng.choice([m["id"] for m in MONSTERS if m["tier"] == "boss"])
        pos = _random_cell(occupied, rng)
        occupied.add((pos["x"], pos["y"]))
        objects.append({"id":f"boss-{n}","type":"monster","monster_id":boss_id,"x":pos["x"],"y":pos["y"],"boss":True})
        run["stair"] = None
    else:
        run["stair"] = stair
        count = rng.randint(3,6)
        for i in range(count):
            pos = _random_cell(occupied, rng); occupied.add((pos["x"],pos["y"]))
            typ = "monster" if rng.random() < (2/3) else "chest"
            if typ == "monster":
                spec = rng.choice([m for m in MONSTERS if m["tier"] != "boss"])
                objects.append({"id":f"mob-{n}-{i}","type":"monster","monster_id":spec["id"],"x":pos["x"],"y":pos["y"]})
            else:
                objects.append({"id":f"chest-{n}-{i}","type":"chest","x":pos["x"],"y":pos["y"]})
    run["objects"] = objects
    run["x"], run["y"] = 0, 0
    run["visited"] = [[0,0]]
    run["combat"] = None
    run["floor_log"] = f"Andar {n}/{total}: explore o mapa e encontre a saída." if n < total else f"Andar final {n}/{total}: o chefe aguarda." 
    return run


def _random_cell(occupied: set[tuple[int,int]], rng: random.Random) -> dict:
    cells = [(x,y) for y in range(GRID) for x in range(GRID) if (x,y) not in occupied]
    x,y = rng.choice(cells)
    return {"x":x,"y":y}


def create_dungeon(xp_by_attr: dict[str, int], rng: random.Random | None = None) -> dict:
    rng = rng or random.Random()
    total = rng.randint(3,7)
    run = {"floor":1,"floors":total,"x":0,"y":0,"objects":[],"stair":{"x":5,"y":5},"visited":[[0,0],],
           "combat":None,"loot":[],"run_potions":{},"mp_savings_credit":0.0,"last_message":"Você entrou na dungeon.","started_at":datetime.now(timezone.utc).isoformat(),"completed":False}
    return new_floor(run, xp_by_attr, rng)


def visible_map(run: dict) -> dict:
    px, py = int(run.get("x",0)), int(run.get("y",0))
    visible = {(x,y) for x in range(max(0,px-1), min(GRID,px+2)) for y in range(max(0,py-1), min(GRID,py+2))}
    explored = {tuple(p) for p in run.get("visited", [])}
    # Informa o tipo de tile somente na área visível ou já explorada; fog fora da visão.
    grid = []
    for y in range(GRID):
        row=[]
        for x in range(GRID):
            if (x,y) not in visible and (x,y) not in explored:
                row.append({"x":x,"y":y,"state":"fog","icon":"?"}); continue
            if (x,y)==(px,py):
                row.append({"x":x,"y":y,"state":"player","icon":"🧙","label":"Você"}); continue
            obj = next((o for o in run.get("objects",[]) if o["x"]==x and o["y"]==y),None)
            if obj:
                if obj["type"]=="monster":
                    spec = MONSTER_BY_ID[obj["monster_id"]]
                    row.append({"x":x,"y":y,"state":"boss" if spec["tier"]=="boss" else "monster","icon":spec["icon"],"label":spec["name"]})
                elif obj.get("opened"):
                    row.append({"x":x,"y":y,"state":"opened","icon":"◌","label":"Baú aberto"})
                else: row.append({"x":x,"y":y,"state":"chest","icon":"▣","label":"Baú"})
            elif run.get("stair") and (x,y)==(run["stair"]["x"],run["stair"]["y"]):
                row.append({"x":x,"y":y,"state":"stair","icon":"⇩","label":"Próximo andar"})
            else: row.append({"x":x,"y":y,"state":"floor","icon":"·","label":"Piso"})
        grid.append(row)
    return {"grid":grid,"visible_count":len(visible)}


def _pos_adjacent(a: dict, x: int, y: int) -> bool:
    return max(abs(int(a.get("x",0))-x),abs(int(a.get("y",0))-y)) <= 1 and not (int(a.get("x",0))==x and int(a.get("y",0))==y)


def move_in_dungeon(run: dict, dx: int, dy: int, xp_by_attr: dict[str,int], player_stats: dict,
                    rng: random.Random | None = None) -> tuple[dict, list[str], str]:
    rng = rng or random.Random()
    if not run or run.get("completed"): raise ValueError("Não há dungeon ativa.")
    if run.get("combat"): raise ValueError("Termine o combate antes de se mover.")
    if max(abs(dx),abs(dy)) != 1: raise ValueError("Você só pode mover para uma casa adjacente, incluindo diagonais.")
    nx,ny=int(run["x"])+dx,int(run["y"])+dy
    if not (0<=nx<GRID and 0<=ny<GRID): raise ValueError("Essa casa fica fora do mapa.")
    events=[]
    obj=next((o for o in run.get("objects",[]) if o["x"]==nx and o["y"]==ny and not o.get("opened")),None)
    if obj and obj["type"]=="monster":
        enemy=make_enemy(obj["monster_id"],xp_by_attr,rng)
        enemy["object_id"]=obj["id"]
        run["combat"]={"enemy":enemy,"round":0,"player_turn":0,"buffs":[],"cooldowns":{},"guard_reduction":0,
                       "defensive_agi_once":None,"next_attack":{"bonus":0,"ignore":0},"pending":[],"last_chance_used":False,
                       "rebirth_used":False,"weakness_revealed":False,"player_mp_savings_credit":float(run.get("mp_savings_credit",0.0)),"enemy_mp_savings_credit":0.0,"log":[f"{enemy['icon']} {enemy['name']} bloqueia o caminho!"],"enemy_first":False}
        # A ordem de iniciativa é resolvida no primeiro comando de combate.
        run["last_message"]=f"Combate iniciado contra {enemy['name']}."
        return run,events,"combat"
    run["x"],run["y"]=nx,ny
    if [nx,ny] not in run.get("visited",[]): run.setdefault("visited",[]).append([nx,ny])
    if obj and obj["type"]=="chest":
        obj["opened"]=True
        coins=rng.randint(5,12)
        events.append(f"Baú aberto: +{coins} moedas.")
        run["coins_found"]=int(run.get("coins_found",0))+coins
        # Baús têm poções, não equipamentos; cada equipamento mantém a sua única fonte de drop.
        if rng.random()<0.62:
            pot=rng.choice(["pocao_cura","pocao_mana"])
            amount=1 if rng.random()<0.8 else 2
            run.setdefault("run_potions",{})[pot]=int(run.setdefault("run_potions",{}).get(pot,0))+amount
            events.append(f"Você encontrou {amount}× {CONSUMABLES[pot]['name']}.")
        run["last_message"]="Baú saqueado. Continue explorando."
    elif run.get("stair") and (nx,ny)==(run["stair"]["x"],run["stair"]["y"]):
        run["floor"]+=1
        new_floor(run,xp_by_attr,rng)
        events.append(run["floor_log"])
        run["last_message"]=run["floor_log"]
    else:
        run["last_message"]="Você avançou uma casa."
    return run,events,"moved"


def _luck_rolls(xp_by_attr: dict[str,int], equipped: dict[str,str], rng: random.Random) -> dict[str, bool]:
    chances=player_luck_chances(xp_by_attr,equipped)
    rolls={cat:rng.random()<chance/100 for cat,chance in chances.items() if cat!="miracle"}
    if chances.get("miracle",0) and rng.random()<chances["miracle"]/100:
        rolls["miracle"]=True
    else: rolls["miracle"]=False
    return rolls


def _resolve_loot(monster_id: str, tier: str, xp_by_attr: dict[str,int], equipped: dict[str,str], rng: random.Random) -> tuple[list[str], int, list[str]]:
    spec=MONSTER_BY_ID[monster_id]
    chance={"common":0.45,"strong":0.45,"boss":0.45}[tier]
    drops=[item_id for item_id in spec["loot"] if rng.random()<chance]
    rolls=_luck_rolls(xp_by_attr,equipped,rng)
    messages=[]
    # Os efeitos de LUC são verificações independentes por categoria, sem somar chances.
    if rolls.get("extra_item") and spec["loot"]:
        drops.append(rng.choice(spec["loot"])); messages.append("A sua sorte encontrou um item extra!")
    if rolls.get("extra"):
        messages.append("Sorte: recompensa em moedas extra!")
        extra_coins=rng.randint(4,10)
    else: extra_coins=0
    if rolls.get("bonus"):
        messages.append("Boa Estrela: recompensa bônus!")
        extra_coins+=rng.randint(3,8)
    if rolls.get("rarity"):
        messages.append("Caçador de Relíquias: chance de raridade aprimorada ativada.")
        # Os 24 equipamentos são entradas fixas; aqui o efeito agrega moedas adicionais sem inventar um novo rank.
        extra_coins+=rng.randint(4,10)
    if rolls.get("miracle"):
        messages.append("Milagre ativado!")
        if rng.random()<0.5: extra_coins+=rng.randint(6,14)
        elif spec["loot"]: drops.append(rng.choice(spec["loot"])); messages.append("Milagre encontrou outro item.")
    return drops,extra_coins,messages


def start_combat(run: dict, player: dict) -> dict:
    if not run or not run.get("combat"): raise ValueError("Não há combate ativo.")
    combat=run["combat"]
    combat.setdefault("player_state",{})
    return combat


def _target_def(target: dict) -> int:
    return max(0, int(target.get("stats",{}).get("DEF",1)) + sum(int(b.get("amount",0)) for b in target.get("buffs",[]) if b.get("stat")=="DEF" and b.get("remaining",0)>0))


def _actor_stats(actor: dict) -> dict:
    stats=dict(actor.get("stats",{}))
    for buff in actor.get("buffs",[]):
        if buff.get("remaining",0)>0 and buff.get("stat") in stats:
            stats[buff["stat"]]=stats.get(buff["stat"],0)+int(buff.get("amount",0))
    if actor.get("defensive_agi_once"):
        stats["AGI"]=stats.get("AGI",1)+int(actor["defensive_agi_once"].get("amount",0))
    return stats


def _misses(target: dict, attacker: dict, rng: random.Random, extra_pp: int = 0) -> bool:
    tstats=_actor_stats(target); astats=_actor_stats(attacker)
    # Fórmula provisória explícita: AGI igual dá 5%; cada ponto de vantagem defensiva +5 p.p.; teto 60%.
    chance=max(0.05,min(0.60,0.05+0.05*(tstats.get("AGI",1)-astats.get("AGI",1))))
    chance=min(0.80,chance+extra_pp/100)
    return rng.random()<chance


def _apply_incoming_damage(actor: dict, enemy: dict, damage: int, combat: dict, rng: random.Random, attacker: dict | None = None) -> list[str]:
    events=[]
    actor_guard=int(actor.get("guard_reduction",0))
    if actor_guard:
        damage=max(0,damage-actor_guard)
        actor["guard_reduction"]=0
    # Defesa reduz o ataque básico; reduções diretas foram aplicadas depois do dano-base.
    damage=max(0,int(damage))
    if attacker and _misses(actor,attacker,rng, int(actor.get("evasion_pp",0))):
        events.append("Esquiva! O ataque passou no vazio.")
        actor["defensive_agi_once"]=None
        actor["evasion_pp"]=0
        return events
    actor["defensive_agi_once"]=None
    actor["evasion_pp"]=0
    actor["hp"]=max(0,int(actor.get("hp",0))-damage)
    events.append(f"Você recebeu {damage} de dano." if actor is combat.get("player") else f"{actor.get('name','O inimigo')} recebeu {damage} de dano.")
    if actor["hp"]<=0:
        if not actor.get("rebirth_used") and any(s.get("action")=="rebirth" for s in actor.get("skills",[])):
            actor["hp"]=1; actor["rebirth_used"]=True; events.append(f"{actor.get('name','Você')} ativou Renascimento e ficou com 1 HP!")
    if actor.get("hp",0)>0 and not actor.get("last_chance_used") and actor.get("hp_max",1)>0 and actor["hp"] < actor["hp_max"]*0.20:
        if any(s.get("action")=="last_chance" for s in actor.get("skills",[])):
            actor["hp"]=min(actor["hp_max"],actor["hp"]+3); actor["last_chance_used"]=True
            events.append(f"{actor.get('name','Você')} ativou Última Chance (+3 HP).")
    return events


def _heal(actor: dict, amount: int) -> int:
    before=int(actor.get("hp",0)); actor["hp"]=min(int(actor.get("hp_max",before)),before+max(0,int(amount)))
    return actor["hp"]-before


def _restore_mp(actor: dict, amount: int) -> int:
    before=int(actor.get("mp",0)); actor["mp"]=min(int(actor.get("mp_max",before)),before+max(0,int(amount)))
    return actor["mp"]-before


def _consume_preparations(actor: dict, skill: dict, is_magic: bool, is_attack: bool = False) -> tuple[int,int,int]:
    """Retorna bônus de MAG, bônus mágico e dano adicional e consome apenas as preparações válidas."""
    mag_bonus=magic_bonus=damage_bonus=0
    kept=[]
    for prep in actor.get("pending",[]):
        action=prep.get("action")
        if action=="prepare_mag" and is_magic:
            mag_bonus+=int(prep.get("amount",0))
        elif action=="prepare_mag_any" and is_magic:
            mag_bonus+=int(prep.get("amount",0))
        elif action=="prepare_magic" and is_magic:
            magic_bonus+=int(prep.get("amount",0))
        elif action=="weakness" and is_attack and actor.get("weakness_revealed"):
            damage_bonus+=int(prep.get("amount",0))
        else: kept.append(prep)
    actor["pending"]=kept
    return mag_bonus,magic_bonus,damage_bonus


def _skill_cost(skill: dict, actor: dict, is_player: bool, combat: dict) -> tuple[int, int]:
    base=int(skill.get("mp_cost",0))
    if not base: return 0,0
    efficient=any(s.get("action")=="mp_efficiency" for s in actor.get("skills",[]))
    if efficient:
        credit_key="player_mp_savings_credit" if is_player else "enemy_mp_savings_credit"
        credit=float(combat.get(credit_key,0.0)) + base*0.03
        discount=int(credit + 1e-9)
        effective=max(1,base-discount)
        credit-=discount
        combat[credit_key]=round(credit,6)
        return effective,discount
    return base,0


def _activate_skill(actor: dict, target: dict, skill: dict, combat: dict, is_player: bool,
                    rng: random.Random, player_stats: dict | None = None) -> list[str]:
    action=skill.get("action"); name=skill.get("name","Habilidade")
    events=[]
    base_cd=int(skill.get("cooldown",0))
    cooldowns=actor.setdefault("cooldowns",{})
    if base_cd and int(cooldowns.get(skill["id"],0))>0:
        raise ValueError(f"{name} está em recarga por mais {cooldowns[skill['id']]} turno(s).")
    is_magic=action in ("magic_attack","prepare_mag","prepare_magic")
    credit_key="player_mp_savings_credit" if is_player else "enemy_mp_savings_credit"
    previous_credit=float(combat.get(credit_key,0.0))
    cost,discount=_skill_cost(skill,actor,is_player,combat)
    if int(actor.get("mp",0))<cost:
        combat[credit_key]=previous_credit
        raise ValueError(f"MP insuficiente para {name}: precisa de {cost} MP.")
    if cost:
        actor["mp"]-=cost
        events.append(f"-{cost} MP por {name}." + (f" (economia de {discount} MP acumulada)" if discount else ""))
    # As preparações ficam em espera até a próxima habilidade válida; não são consumidas por outra preparação.
    mag_bonus=magic_bonus=prep_damage=0
    if action not in ("prepare_mag","prepare_mag_any","prepare_magic","weakness"):
        mag_bonus,magic_bonus,prep_damage=_consume_preparations(actor,skill,is_magic, action in ("magic_attack","combo"))
    amount=int(skill.get("amount",0))
    amount += magic_bonus
    if base_cd:
        cooldowns[skill["id"]]=base_cd
        actor.setdefault("used_skills_this_turn", []).append(skill["id"])
    if action=="guard":
        actor["guard_reduction"]=max(int(actor.get("guard_reduction",0)),amount)
        events.append(f"{name}: próximo golpe reduzido em {amount}.")
    elif action=="buff_def":
        actor.setdefault("buffs",[]).append({"stat":"DEF","amount":amount,"remaining":int(skill.get("duration",1)),"created_turn":int(actor.get("turn",0))})
        events.append(f"{name}: +{amount} DEF por {skill.get('duration',1)} turno(s).")
    elif action in ("buff_agi","absolute_movement"):
        actor.setdefault("buffs",[]).append({"stat":"AGI","amount":amount,"remaining":int(skill.get("duration",1)),"created_turn":int(actor.get("turn",0))})
        events.append(f"{name}: +{amount} AGI por {skill.get('duration',1)} turno(s).")
    elif action=="afterimage":
        actor.setdefault("buffs",[]).append({"stat":"AGI","amount":amount,"remaining":int(skill.get("duration",1)),"created_turn":int(actor.get("turn",0))})
        actor["evasion_pp"]=max(int(actor.get("evasion_pp",0)),int(skill.get("evasion_pp",20)))
        events.append(f"{name}: +{amount} AGI e esquiva aprimorada.")
    elif action=="buff_res":
        actor.setdefault("buffs",[]).append({"stat":"RES","amount":amount,"remaining":int(skill.get("duration",1)),"created_turn":int(actor.get("turn",0))})
        events.append(f"{name}: +{amount} RES por {skill.get('duration',1)} turnos.")
    elif action=="evasion_once":
        actor["defensive_agi_once"]={"amount":amount}
        events.append(f"{name}: +{amount} AGI defensiva contra o próximo ataque.")
    elif action=="next_attack":
        pending=actor.setdefault("next_attack",{"bonus":0,"ignore":0})
        pending["bonus"]+=amount; pending["ignore"]+=int(skill.get("ignore",0))
        events.append(f"{name}: próximo ataque recebe +{amount} dano" + (f" e ignora {skill['ignore']} DEF." if skill.get("ignore") else "."))
    elif action=="next_ignore":
        actor.setdefault("next_attack",{"bonus":0,"ignore":0})["ignore"]+=amount
        events.append(f"{name}: próximo ataque ignora {amount} DEF.")
    elif action=="heal":
        healed=_heal(actor,amount)
        events.append(f"{name}: recuperou {healed} HP.")
    elif action=="restore_mp":
        restored=_restore_mp(actor,amount)
        events.append(f"{name}: recuperou {restored} MP.")
    elif action=="conversion":
        if int(actor.get("mp",0))+cost < 3:
            raise ValueError("Conversão de Energia exige 3 MP disponíveis antes da conversão.")
        # Custo de 3 MP é o próprio recurso convertido, sem pagar duas vezes.
        actor["hp"] = min(int(actor.get("hp_max",0)), int(actor.get("hp",0)) + 3)
        events.append("Conversão de Energia: +3 HP por 3 MP.")
    elif action=="magic_attack":
        astats=_actor_stats(actor); tstats=_actor_stats(target)
        mag=astats.get("MAG",1)+mag_bonus
        # Dano mágico base com mínimo 1; bônus explícitos de skill vêm depois.
        damage=max(1,mag-tstats.get("RES",1))+amount+prep_damage
        events.extend(_apply_enemy_damage(target,damage,actor,combat,rng,ignore=0))
        events.append(f"{name}: ataque mágico com {damage} de dano calculado.")
    elif action=="prepare_mag":
        actor.setdefault("pending",[]).append({"action":"prepare_mag","amount":amount,"source":skill["id"]})
        events.append(f"{name}: bônus de +{amount} MAG guardado para a próxima magia válida.")
    elif action=="prepare_mag_any":
        actor.setdefault("pending",[]).append({"action":"prepare_mag_any","amount":amount,"source":skill["id"]})
        events.append(f"{name}: bônus de +{amount} MAG guardado para a próxima habilidade.")
    elif action=="prepare_magic":
        actor.setdefault("pending",[]).append({"action":"prepare_magic","amount":amount,"source":skill["id"]})
        events.append(f"{name}: +{amount} efeito mágico guardado para a próxima habilidade mágica válida.")
    elif action=="weakness":
        actor["weakness_revealed"]=True
        actor.setdefault("pending",[]).append({"action":"weakness","amount":amount,"source":skill["id"]})
        events.append(f"{name}: fraqueza revelada; próximo ataque recebe +{amount} dano.")
    elif action=="combo":
        astats=_actor_stats(actor); tstats=_actor_stats(target)
        attack=actor.setdefault("next_attack",{"bonus":0,"ignore":0})
        ignore=int(attack.get("ignore",0)); bonus=int(attack.get("bonus",0))
        dmg_base=max(1,astats.get("ATK",1)-max(0,tstats.get("DEF",1)-ignore))
        hit=max(1,math.ceil(dmg_base/2))+bonus+prep_damage
        events.extend(_apply_enemy_damage(target,hit,actor,combat,rng,ignore=ignore))
        hits_done=1
        if target.get("hp",0)>0:
            events.extend(_apply_enemy_damage(target,hit,actor,combat,rng,ignore=ignore))
            hits_done=2
        actor["next_attack"]={"bonus":0,"ignore":0}
        events.append(f"{name}: {hits_done} golpe(s) calculado(s) em {hit} dano cada (bônus completos por golpe).")
    else:
        events.append(f"{name} ativada.")
    return events


def _apply_enemy_damage(target: dict, raw_damage: int, attacker: dict, combat: dict, rng: random.Random, ignore: int = 0) -> list[str]:
    events=[]
    # Defesa total primeiro, depois redução direta, que pode levar o dano final a zero.
    tstats=_actor_stats(target); astats=_actor_stats(attacker)
    defense=max(0,tstats.get("DEF",1)-int(ignore))
    damage=max(1,astats.get("ATK",1)-defense) if raw_damage is None else max(0,int(raw_damage))
    # Habilidades explícitas de dano chegam já com dano-base + bônus, por isso não subtraímos DEF outra vez.
    direct=int(target.get("guard_reduction",0))
    damage=max(0,damage-direct); target["guard_reduction"]=0
    if _misses(target,attacker,rng,int(target.get("evasion_pp",0))):
        events.append("O ataque foi esquivado.")
        target["defensive_agi_once"]=None; target["evasion_pp"]=0
        return events
    target["defensive_agi_once"]=None; target["evasion_pp"]=0
    target["hp"]=max(0,int(target.get("hp",0))-damage)
    if target.get("name")=="Jogador": events.append(f"Você recebeu {damage} dano.")
    else: events.append(f"{target.get('name','Alvo')} recebeu {damage} dano.")
    if target["hp"]<=0:
        _try_rebirth_last_chance(target,events)
    else: _try_last_chance(target,events)
    return events


def _try_rebirth_last_chance(target: dict, events: list[str]) -> None:
    if not target.get("rebirth_used") and any(s.get("action")=="rebirth" for s in target.get("skills",[])):
        target["hp"]=1; target["rebirth_used"]=True; events.append("Renascimento ativado: sobreviveu com 1 HP!")
    if target.get("hp",0)>0: _try_last_chance(target,events)


def _try_last_chance(target: dict, events: list[str]) -> None:
    if target.get("hp",0)>0 and not target.get("last_chance_used") and target.get("hp_max",0)>0 and target["hp"] < target["hp_max"]*0.20 and any(s.get("action")=="last_chance" for s in target.get("skills",[])):
        target["hp"]=min(target["hp_max"],target["hp"]+3); target["last_chance_used"]=True; events.append("Última Chance: +3 HP.")


def _enemy_turn(combat: dict, player_stats: dict, rng: random.Random) -> list[str]:
    enemy=combat.get("enemy")
    if not enemy or enemy.get("hp",0)<=0 or player_stats.get("hp",0)<=0: return []
    events=[]
    enemy["turn"]=int(enemy.get("turn",0))+1
    actions=[None]
    for s in enemy.get("skills",[]):
        if s.get("kind")=="active" and s.get("id") not in () and int(enemy.get("cooldowns",{}).get(s["id"],0))<=0:
            cost=int(s.get("mp_cost",0))
            if enemy.get("mp",0)>=cost: actions.append(s)
    chosen=rng.choice(actions) # ataque básico e cada técnica têm peso igual
    player_actor={"name":"Jogador","hp":player_stats["hp"],"hp_max":player_stats["hp_max"],"mp":player_stats["mp"],"mp_max":player_stats["mp_max"],
                  "stats":player_stats["stats"],"skills":list(player_stats["skills"].values()),"buffs":combat.get("buffs",[]),
                  "guard_reduction":combat.get("player_guard_reduction",0),"defensive_agi_once":combat.get("player_defensive_agi_once"),
                  "evasion_pp":combat.get("player_evasion_pp",0),"last_chance_used":combat.get("last_chance_used",False),"rebirth_used":combat.get("rebirth_used",False)}
    if chosen is None:
        astats=_actor_stats(enemy); tstats=_actor_stats(player_actor)
        damage=max(1,astats.get("ATK",1)-tstats.get("DEF",1))
        events += _apply_enemy_damage(player_actor,damage,enemy,combat,rng)
        events.insert(0,f"{enemy['icon']} {enemy['name']} usa Ataque básico.")
    else:
        try:
            events.insert(0,f"{enemy['icon']} {enemy['name']} usa {chosen['name']}.")
            events += _activate_skill(enemy,player_actor,chosen,combat,False,rng,player_stats)
        except ValueError as exc:
            events.append(str(exc))
    # Copia os recursos/flags do ator temporário para o combate do jogador.
    combat["player_hp"]=int(player_actor.get("hp",player_stats["hp"]))
    combat["player_mp"]=int(player_actor.get("mp",player_stats["mp"]))
    combat["player_guard_reduction"]=int(player_actor.get("guard_reduction",0))
    combat["player_defensive_agi_once"]=player_actor.get("defensive_agi_once")
    combat["player_evasion_pp"]=int(player_actor.get("evasion_pp",0))
    combat["last_chance_used"]=bool(player_actor.get("last_chance_used",False))
    combat["rebirth_used"]=bool(player_actor.get("rebirth_used",False))
    # Uma habilidade usada neste turno não perde um turno de recarga imediatamente.
    _tick_actor(enemy)
    return events


def _combat_player_actor(combat: dict, stats: dict) -> dict:
    return {"name":"Jogador","hp":int(combat.get("player_hp",stats["hp"])),"hp_max":stats["hp_max"],
            "mp":int(combat.get("player_mp",stats["mp"])),"mp_max":stats["mp_max"],"stats":stats["stats"],
            "skills":list(stats["skills"].values()),"cooldowns":combat.setdefault("cooldowns",{}),"buffs":combat.setdefault("buffs",[]),
            "guard_reduction":int(combat.get("player_guard_reduction",combat.get("guard_reduction",0))),
            "defensive_agi_once":combat.get("player_defensive_agi_once",combat.get("defensive_agi_once")),
            "evasion_pp":int(combat.get("player_evasion_pp",0)),"pending":combat.setdefault("pending",[]),
            "next_attack":combat.setdefault("next_attack",{"bonus":0,"ignore":0}),"last_chance_used":combat.get("last_chance_used",False),
            "rebirth_used":combat.get("rebirth_used",False),"weakness_revealed":combat.get("weakness_revealed",False),
            "used_skills_this_turn":[],"turn":int(combat.get("player_turn",0))}


def _sync_player_actor(combat: dict, actor: dict) -> None:
    combat["player_hp"]=int(actor.get("hp",0)); combat["player_mp"]=int(actor.get("mp",0))
    for key in ("guard_reduction","defensive_agi_once","evasion_pp","last_chance_used","rebirth_used","weakness_revealed"):
        combat[{"guard_reduction":"player_guard_reduction","defensive_agi_once":"player_defensive_agi_once","evasion_pp":"player_evasion_pp"}.get(key,key)]=actor.get(key)
    combat["cooldowns"]=actor.get("cooldowns",{})
    combat["buffs"]=actor.get("buffs",[])
    combat["pending"]=actor.get("pending",[])
    combat["next_attack"]=actor.get("next_attack",{"bonus":0,"ignore":0})


def _tick_actor(actor: dict) -> None:
    turn=int(actor.get("turn",0))
    # A duração só começa a contar nos turnos completos posteriores à ativação.
    for buff in actor.get("buffs",[]):
        if int(buff.get("created_turn",-1)) < turn:
            buff["remaining"]=max(0,int(buff.get("remaining",0))-1)
    actor["buffs"]=[b for b in actor.get("buffs",[]) if int(b.get("remaining",0))>0]
    used=set(actor.get("used_skills_this_turn", []))
    for sid in list(actor.get("cooldowns",{})):
        if sid not in used and int(actor["cooldowns"][sid])>0:
            actor["cooldowns"][sid]=max(0,int(actor["cooldowns"][sid])-1)
    actor["used_skills_this_turn"]=[]


def _passive_end_turn(actor: dict, events: list[str]) -> None:
    if actor.get("hp",0)<=0: return
    heal=0
    for s in actor.get("skills",[]):
        if s.get("action")=="regen": heal=max(heal,int(s.get("amount",2)))
    if heal:
        actual=_heal(actor,heal)
        if actual: events.append(f"Regeneração: +{actual} HP no fim do turno.")


def resolve_player_action(run: dict, player_snapshot: dict, action: dict, inventory: dict,
                          xp_by_attr: dict[str,int], equipped: dict[str,str], rng: random.Random | None = None) -> dict:
    """Executa uma ação de combate e a resposta inimiga conforme AGI. Devolve mutações e eventos."""
    rng=rng or random.Random()
    combat=run.get("combat")
    if not combat: raise ValueError("Não há combate ativo.")
    enemy=combat["enemy"]
    pstats=compute_player_stats(xp_by_attr,equipped,combat.get("player_hp",player_snapshot["hp"]),combat.get("player_mp",player_snapshot["mp"]),None)
    actor=_combat_player_actor(combat,pstats)
    # A cada rodada, se o inimigo for mais ágil, ele age antes do jogador.
    if enemy.get("hp",0)<=0: return {"events":[],"result":"enemy_defeated","inventory":inventory}
    events=[]
    enemy_agi = int(_actor_stats(enemy).get("AGI",1))
    player_agi = int(_actor_stats(actor).get("AGI",1))
    enemy_first = enemy_agi > player_agi or (enemy_agi == player_agi and rng.choice([True, False]))
    if enemy_first:
        player_stats_for_enemy={"hp":actor["hp"],"hp_max":actor["hp_max"],"mp":actor["mp"],"mp_max":actor["mp_max"],"stats":actor["stats"],"skills":pstats["skills"]}
        events+=_enemy_turn(combat,player_stats_for_enemy,rng)
        actor["hp"]=combat.get("player_hp",actor["hp"]); actor["mp"]=combat.get("player_mp",actor["mp"])
        actor["guard_reduction"]=combat.get("player_guard_reduction",actor.get("guard_reduction",0))
        actor["defensive_agi_once"]=combat.get("player_defensive_agi_once",actor.get("defensive_agi_once"))
        actor["evasion_pp"]=combat.get("player_evasion_pp",0)
        actor["last_chance_used"]=combat.get("last_chance_used",actor.get("last_chance_used",False))
        actor["rebirth_used"]=combat.get("rebirth_used",actor.get("rebirth_used",False))
        if actor["hp"]<=0:
            _sync_player_actor(combat,actor)
            return {"events":events,"result":"player_defeated","inventory":inventory}
        # Recalcula passivas condicionais, como Postura Firme, após o golpe de iniciativa.
        pstats=compute_player_stats(xp_by_attr,equipped,actor["hp"],actor["mp"],None)
        actor["stats"]=pstats["stats"]
        actor["hp_max"]=pstats["hp_max"]
        actor["mp_max"]=pstats["mp_max"]
        actor["skills"]=list(pstats["skills"].values())
    # Refresca os skills efetivos e calcula MP antes da ação.
    skills=pstats["skills"]
    typ=action.get("type")
    actor["turn"]=int(combat.get("player_turn",0))+1
    combat["player_turn"]=actor["turn"]
    if typ=="attack":
        astats=_actor_stats(actor); tstats=_actor_stats(enemy)
        attack=actor.setdefault("next_attack",{"bonus":0,"ignore":0})
        prep_damage=0
        pending=[]
        for prep in actor.get("pending",[]):
            if prep.get("action")=="weakness" and actor.get("weakness_revealed"):
                prep_damage += int(prep.get("amount",0))
            else:
                pending.append(prep)
        actor["pending"]=pending
        ignore=int(attack.get("ignore",0))
        damage=max(1,astats.get("ATK",1)-max(0,tstats.get("DEF",1)-ignore))+int(attack.get("bonus",0))+prep_damage
        hit_events=_apply_enemy_damage(enemy,damage,actor,combat,rng,ignore=ignore)
        events.append(f"Ataque básico: {damage} de dano calculado.")
        events+=hit_events
        actor["next_attack"]={"bonus":0,"ignore":0}
        if actor.get("weakness_revealed"): actor["weakness_revealed"]=False
    elif typ=="defend":
        # Ação defensiva de base adotada para dar utilidade à opção: reduz o próximo golpe em 50%.
        actor["guard_reduction"]=max(int(actor.get("guard_reduction",0)),max(1,math.ceil(_actor_stats(enemy).get("ATK",1)/2)))
        events.append("Você assume posição defensiva; o próximo golpe é reduzido.")
    elif typ=="skill":
        skill_id=action.get("skill_id")
        skill=skills.get(skill_id)
        if not skill or skill.get("kind")!="active": raise ValueError("Habilidade não desbloqueada nem concedida por equipamento.")
        ev=_activate_skill(actor,enemy,skill,combat,True,rng,pstats)
        events+=ev
    elif typ=="item":
        item_id=action.get("item_id")
        if item_id not in CONSUMABLES: raise ValueError("Consumível inválido.")
        qty=int(inventory.get(item_id,0))
        run_qty=int(run.get("run_potions",{}).get(item_id,0))
        if qty<=0 and run_qty<=0: raise ValueError("Você não tem essa poção.")
        item=CONSUMABLES[item_id]
        if item["effect"]=="heal":
            if actor["hp"]>=actor["hp_max"]: raise ValueError("Seu HP já está cheio; a poção não foi consumida.")
            healed=_heal(actor,item["amount"]); events.append(f"Poção de Cura: +{healed} HP.")
        else:
            if actor["mp"]>=actor["mp_max"]: raise ValueError("Seu MP já está cheio; a poção não foi consumida.")
            restored=_restore_mp(actor,item["amount"]); events.append(f"Poção de Mana: +{restored} MP.")
        if run_qty>0: run["run_potions"][item_id]=run_qty-1
        else: inventory[item_id]=qty-1
    else:
        raise ValueError("Ação de combate inválida.")
    # Sincroniza buffs/guardas antes do turno inimigo, para efeitos recém-ativados já valerem.
    _sync_player_actor(combat,actor)
    # Enemy's faster-turn was already used before player. Otherwise enemy responds after this action.
    if enemy.get("hp",0)>0 and actor.get("hp",0)>0 and not enemy_first:
        pstats_for_enemy={"hp":actor["hp"],"hp_max":actor["hp_max"],"mp":actor["mp"],"mp_max":actor["mp_max"],"stats":actor["stats"],"skills":pstats["skills"]}
        events+=_enemy_turn(combat,pstats_for_enemy,rng)
        actor["hp"]=combat.get("player_hp",actor["hp"]); actor["mp"]=combat.get("player_mp",actor["mp"])
        actor["guard_reduction"]=combat.get("player_guard_reduction",actor.get("guard_reduction",0))
        actor["defensive_agi_once"]=combat.get("player_defensive_agi_once",actor.get("defensive_agi_once"))
        actor["evasion_pp"]=combat.get("player_evasion_pp",actor.get("evasion_pp",0))
        actor["last_chance_used"]=combat.get("last_chance_used",actor.get("last_chance_used",False))
        actor["rebirth_used"]=combat.get("rebirth_used",actor.get("rebirth_used",False))
    # Regeneração acontece no encerramento do turno de combate, após a resposta inimiga.
    _passive_end_turn(actor,events)
    # Durações e recargas contam após um turno completo, incluindo a resposta inimiga.
    _tick_actor(actor)
    # Recursos, preparações e flags são transferidos para o encontro persistente.
    _sync_player_actor(combat,actor)
    run["mp_savings_credit"] = float(combat.get("player_mp_savings_credit", run.get("mp_savings_credit", 0.0)))
    combat["log"]=(combat.get("log",[])+events)[-60:]
    combat["round"]=int(combat.get("round",0))+1
    if enemy.get("hp",0)<=0:
        return {"events":events,"result":"enemy_defeated","inventory":inventory}
    if actor.get("hp",0)<=0:
        return {"events":events,"result":"player_defeated","inventory":inventory}
    return {"events":events,"result":"continue","inventory":inventory}


def award_monster_rewards(monster_id: str, xp_by_attr: dict[str,int], equipped: dict[str,str], rng: random.Random | None = None) -> dict:
    rng=rng or random.Random()
    spec=MONSTER_BY_ID[monster_id]
    drops,extra_coins,luck_messages=_resolve_loot(monster_id,spec["tier"],xp_by_attr,equipped,rng)
    base_ranges={"common":(4,10),"strong":(12,24),"boss":(30,50)}
    lo,hi=base_ranges[spec["tier"]]
    multiplier={"F":0.85,"E":0.95,"D":1.0,"C":1.12,"B":1.25,"A":1.4,"S":1.55}[spec["rank"]]
    coins=int(rng.randint(lo,hi)*multiplier)+extra_coins
    return {"items":drops,"coins":coins,"messages":luck_messages}


def describe_player_skills(xp_by_attr: dict[str,int], equipped: dict[str,str] | None = None) -> list[dict]:
    available=effective_skills(xp_by_attr,equipped)
    result=[]
    for skill in SKILLS:
        unlocked=skill["id"] in available
        result.append({**skill,"unlocked":unlocked,"source_item":available.get(skill["id"],{}).get("source_item")})
    return result
