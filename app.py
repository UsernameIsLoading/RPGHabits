from __future__ import annotations
import copy
import os
import random
from datetime import date, datetime, timedelta
from functools import wraps
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import Flask, jsonify, render_template, request, session
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import UniqueConstraint, func

from game_data import (
    ATTRIBUTES, ATTR_BY_CODE, RANKS, RANK_INDEX, RANK_XP, SKILLS, SKILL_BY_ID,
    SKILLS_BY_ATTRIBUTE, ITEMS, ITEM_BY_ID, MONSTERS, MONSTER_BY_ID, CONSUMABLES,
)
from game_engine import (
    rank_summary, compute_player_stats, describe_player_skills, effective_skills,
    create_dungeon, visible_map, move_in_dungeon, resolve_player_action,
    award_monster_rewards, DAILY_REWARD_PER_TASK, DAILY_REWARD_CAP,
    WEEKLY_DUNGEON_LIMIT,
)

TZ = ZoneInfo("America/Bahia")

def local_now() -> datetime:
    return datetime.now(TZ).replace(tzinfo=None)

def today_key() -> str:
    return datetime.now(TZ).date().isoformat()


def make_database_url() -> str:
    url = os.getenv("DATABASE_URL", "").strip()
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    if url:
        return url
    instance_dir = Path(__file__).resolve().parent / "instance"
    instance_dir.mkdir(parents=True, exist_ok=True)
    return "sqlite:///" + str(instance_dir / "rpg_habitos.db")

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.getenv("SECRET_KEY", "dev-only-change-this-secret"),
    SQLALCHEMY_DATABASE_URI=make_database_url(),
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    SQLALCHEMY_ENGINE_OPTIONS={"pool_pre_ping": True},
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=bool(os.getenv("RENDER")),
    JSON_SORT_KEYS=False,
)
db = SQLAlchemy(app)


def default_xp() -> dict[str, int]:
    return {a["code"]: 0 for a in ATTRIBUTES}


def default_inventory() -> dict:
    return {"pocao_cura": 2, "pocao_mana": 2, "equipment": {}, "bracelete_salvacao": 0, "ticket_dungeon": 0}


class Player(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    xp_by_attribute = db.Column(db.JSON, nullable=False, default=default_xp)
    inventory = db.Column(db.JSON, nullable=False, default=default_inventory)
    equipped = db.Column(db.JSON, nullable=False, default=dict)
    coins = db.Column(db.Integer, nullable=False, default=0)
    current_hp = db.Column(db.Integer, nullable=False, default=25)
    current_mp = db.Column(db.Integer, nullable=False, default=11)
    dungeon_state = db.Column(db.JSON, nullable=True)
    last_dungeon_result = db.Column(db.String(240), nullable=True)
    permanent_special_seconds = db.Column(db.Integer, nullable=False, default=0)
    daily_reward_date = db.Column(db.String(10), nullable=False, default=today_key)
    daily_reward_seconds = db.Column(db.Integer, nullable=False, default=0)
    reward_session_active = db.Column(db.Boolean, nullable=False, default=False)
    reward_last_tick_at = db.Column(db.DateTime, nullable=True)
    physical_chapters = db.Column(db.Integer, nullable=False, default=0)
    study_chapters = db.Column(db.Integer, nullable=False, default=0)
    physical_unlock_date = db.Column(db.String(10), nullable=True)
    study_unlock_date = db.Column(db.String(10), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=local_now)


class DailyEvaluation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    attribute = db.Column(db.String(8), nullable=False)
    day = db.Column(db.String(10), nullable=False)
    score = db.Column(db.Integer, nullable=False)
    xp = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=local_now)
    __table_args__ = (UniqueConstraint("attribute", "day", name="uq_daily_attribute_day"),)


class Activity(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    attribute = db.Column(db.String(8), nullable=False)
    title = db.Column(db.String(160), nullable=False)
    value = db.Column(db.Float, nullable=True)
    note = db.Column(db.String(600), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=local_now)


class DungeonAttempt(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    started_at = db.Column(db.DateTime, nullable=False, default=local_now)
    outcome = db.Column(db.String(24), nullable=False, default="em_andamento")
    floors = db.Column(db.Integer, nullable=False, default=0)
    ended_at = db.Column(db.DateTime, nullable=True)


def api_error(message: str, status: int = 400):
    return jsonify({"ok": False, "error": message}), status


def require_auth(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get("authenticated"):
            return api_error("Sessão encerrada. Entre novamente.", 401)
        return fn(*args, **kwargs)
    return wrapped


def clone_json(value, fallback):
    return copy.deepcopy(value) if value is not None else copy.deepcopy(fallback)


def get_player() -> Player:
    p = db.session.get(Player, 1)
    if p is None:
        p = Player(id=1, xp_by_attribute=default_xp(), inventory=default_inventory(), equipped={},
                   coins=0, current_hp=25, current_mp=11, daily_reward_date=today_key())
        db.session.add(p)
        db.session.flush()
    if not p.xp_by_attribute:
        p.xp_by_attribute = default_xp()
    if not p.inventory:
        p.inventory = default_inventory()
    if "equipment" not in p.inventory or "bracelete_salvacao" not in p.inventory or "ticket_dungeon" not in p.inventory:
        inv = clone_json(p.inventory, default_inventory()); inv.setdefault("equipment", {}); inv.setdefault("bracelete_salvacao", 0); inv.setdefault("ticket_dungeon", 0); p.inventory = inv
    if p.equipped is None: p.equipped = {}
    if p.dungeon_state is not None and "loot" not in p.dungeon_state:
        run = clone_json(p.dungeon_state, {}); run["loot"] = []; p.dungeon_state = run
    return p


def ensure_daily_reset(p: Player):
    day = today_key()
    if p.daily_reward_date != day:
        p.daily_reward_date = day
        p.daily_reward_seconds = 0  # saldo diário expira; saldo especial permanece.


def tick_reward_timer(p: Player):
    ensure_daily_reset(p)
    now = local_now()
    if p.reward_session_active and p.reward_last_tick_at:
        elapsed = max(0, int((now - p.reward_last_tick_at).total_seconds()))
        from_daily = min(elapsed, max(0, int(p.daily_reward_seconds)))
        p.daily_reward_seconds = max(0, int(p.daily_reward_seconds) - from_daily)
        leftover = elapsed - from_daily
        if leftover:
            p.permanent_special_seconds = max(0, int(p.permanent_special_seconds) - leftover)
        if p.daily_reward_seconds <= 0 and p.permanent_special_seconds <= 0:
            p.reward_session_active = False
            p.reward_last_tick_at = None
        else:
            p.reward_last_tick_at = now
    elif p.reward_session_active:
        p.reward_last_tick_at = now


def current_resources(p: Player) -> tuple[int, int, dict]:
    run = p.dungeon_state or {}
    combat = run.get("combat") or {}
    hp = int(combat.get("player_hp", p.current_hp))
    mp = int(combat.get("player_mp", p.current_mp))
    stats = compute_player_stats(p.xp_by_attribute or default_xp(), p.equipped or {}, hp, mp, None)
    hp = min(hp, stats["hp_max"]); mp = min(mp, stats["mp_max"])
    return hp, mp, stats


def inventory_payload(p: Player) -> dict:
    inv = clone_json(p.inventory, default_inventory())
    equip_counts = inv.setdefault("equipment", {})
    equipment = []
    equipped = p.equipped or {}
    for item in ITEMS:
        qty = int(equip_counts.get(item["id"], 0))
        equipment.append({**item, "quantity": qty, "equipped": item["id"] in equipped.values()})
    consumables = []
    for item in CONSUMABLES.values():
        consumables.append({**item, "quantity": int(inv.get(item["id"], 0)),
                            "dungeon_quantity": int((p.dungeon_state or {}).get("run_potions", {}).get(item["id"], 0))})
    return {"equipment": equipment, "consumables": consumables, "equipped": equipped, "bracelete_salvacao": int(inv.get("bracelete_salvacao", 0)), "ticket_dungeon": int(inv.get("ticket_dungeon", 0))}


def build_state(p: Player) -> dict:
    ensure_daily_reset(p)
    run = clone_json(p.dungeon_state, None)
    hp, mp, stats = current_resources(p)
    p.current_hp, p.current_mp = hp, mp
    rankdata = stats["ranks"]
    attrs = []
    for attr in ATTRIBUTES:
        code = attr["code"]
        r = rankdata[code]
        attrs.append({**attr, **r, "today_evaluation": None})
    daily = {e.attribute: {"score": e.score, "xp": e.xp} for e in DailyEvaluation.query.filter_by(day=today_key()).all()}
    for attr in attrs: attr["today_evaluation"] = daily.get(attr["code"])
    activities = Activity.query.order_by(Activity.created_at.desc()).limit(150).all()
    skill_rows = describe_player_skills(p.xp_by_attribute or default_xp(), p.equipped or {})
    skills = []
    combat_for_skills = (run or {}).get("combat") or {}
    for s in skill_rows:
        cooldown = int(combat_for_skills.get("cooldowns", {}).get(s["id"], 0))
        skills.append({**s, "cooldown_left": cooldown, "usable_now": bool(s["unlocked"] and s["kind"] == "active" and cooldown == 0)})
    weekly_count = DungeonAttempt.query.filter(DungeonAttempt.started_at >= local_now() - timedelta(days=7)).count()
    active_run = None
    if run:
        active_run = {"floor": run["floor"], "floors": run["floors"], "x": run["x"], "y": run["y"],
                      "map": visible_map(run), "combat": None, "last_message": run.get("last_message", ""),
                      "loot_count": len(run.get("loot", [])), "coins_found": int(run.get("coins_found",0)),
                      "run_potions": run.get("run_potions", {})}
        if run.get("combat"):
            c = run["combat"]; e = c["enemy"]
            player_skill_rows = effective_skills(p.xp_by_attribute or default_xp(), p.equipped or {})
            combat_skills = []
            player_mp = int(c.get("player_mp", p.current_mp))
            has_efficiency = any(x.get("action") == "mp_efficiency" for x in player_skill_rows.values())
            for sid, s in player_skill_rows.items():
                if s.get("kind") == "active":
                    base_cost = int(s.get("mp_cost",0))
                    cost = base_cost
                    if base_cost and has_efficiency:
                        credit = float(c.get("player_mp_savings_credit",run.get("mp_savings_credit",0.0))) + base_cost*0.03
                        cost = max(1, base_cost-int(credit+1e-9))
                    cooldown_left = int(c.get("cooldowns", {}).get(sid,0))
                    combat_skills.append({**s, "cooldown_left": cooldown_left,
                                          "usable_now": cooldown_left == 0 and player_mp >= cost,
                                          "current_cost": cost})
            active_run["combat"] = {"enemy": {"id":e["id"],"name":e["name"],"icon":e["icon"],"tier":e["tier"],"rank":e["rank"],
                                                 "hp":e["hp"],"hp_max":e["hp_max"],"mp":e["mp"],"mp_max":e["mp_max"],"style":e["style"],"stats":e["stats"]},
                                    "log": c.get("log", [])[-12:], "round": c.get("round",0),
                                    "cooldowns":c.get("cooldowns",{}), "skills":combat_skills,
                                    "mp_savings_credit":c.get("player_mp_savings_credit",run.get("mp_savings_credit",0)),
                                    "available_items":[{**CONSUMABLES[k],"quantity":int((p.inventory or {}).get(k,0)),"dungeon_quantity":int(run.get("run_potions",{}).get(k,0))} for k in CONSUMABLES]}
    today_xp = db.session.query(func.coalesce(func.sum(DailyEvaluation.xp), 0)).filter_by(day=today_key()).scalar() or 0
    story = {"physical_chapters": int(p.physical_chapters), "study_chapters": int(p.study_chapters),
             "unlocked_odd": (int(p.physical_chapters)*2 - 1) if p.physical_chapters else None,
             "unlocked_even": (int(p.study_chapters)*2) if p.study_chapters else None,
             "next_odd": int(p.physical_chapters)*2 + 1,
             "next_even": int(p.study_chapters)*2 + 2,
             "novel_url":"https://novelmania.com.br/novels/necromante-da-estacao-de-seul"}
    return {
        "ok": True,
        "player": {"coins": int(p.coins), "hp": hp, "hp_max": stats["hp_max"], "mp": mp, "mp_max": stats["mp_max"],
                   "stats": stats["stats"], "attributes": attrs, "today_xp": int(today_xp), "weekly_dungeons": weekly_count,
                   "weekly_limit": WEEKLY_DUNGEON_LIMIT, "inventory": inventory_payload(p), "equipped": p.equipped or {},
                   "daily_reward_seconds": int(p.daily_reward_seconds), "special_reward_seconds": int(p.permanent_special_seconds),
                   "reward_session_active": bool(p.reward_session_active), "story": story,
                   "last_dungeon_result": p.last_dungeon_result},
        "skills": skills,
        "items": ITEMS,
        "consumables": list(CONSUMABLES.values()),
        "daily_evaluations": daily,
        "activities": [{"id":a.id,"attribute":a.attribute,"title":a.title,"value":a.value,"note":a.note,
                        "created_at":a.created_at.isoformat(timespec="minutes")} for a in activities],
        "dungeon": active_run,
        "resources": {"chartjs": True},
    }


def persist_run(p: Player, run: dict | None):
    p.dungeon_state = clone_json(run, None)


def equip_item(p: Player, item_id: str | None):
    equipped = clone_json(p.equipped, {})
    inv = clone_json(p.inventory, default_inventory())
    owned = inv.setdefault("equipment", {})
    if item_id is None or item_id == "":
        body = request.get_json(silent=True) or {}
        slot = body.get("attribute")
        if slot not in ATTR_BY_CODE: raise ValueError("Slot inválido.")
        equipped.pop(slot, None)
    else:
        item = ITEM_BY_ID.get(item_id)
        if not item: raise ValueError("Equipamento inexistente.")
        if int(owned.get(item_id,0)) <= 0: raise ValueError("Você ainda não possui esse equipamento.")
        equipped[item["attr"]] = item_id
    p.equipped = equipped
    db.session.flush()
    # Equipar não cura, mas o HP/MP atual não pode superar o novo máximo.
    stats = compute_player_stats(p.xp_by_attribute, p.equipped, p.current_hp, p.current_mp)
    p.current_hp = min(p.current_hp, stats["hp_max"]); p.current_mp=min(p.current_mp,stats["mp_max"])


@app.get("/")
def index():
    if session.get("authenticated"):
        return render_template("index.html")
    return render_template("login.html")


@app.post("/api/login")
def login():
    data=request.get_json(silent=True) or {}
    supplied=str(data.get("password", ""))
    expected=os.getenv("SITE_PASSWORD", "12345678")
    if supplied != expected:
        return api_error("Código incorreto.",401)
    session.clear(); session["authenticated"]=True; session.permanent=True
    return jsonify({"ok":True})


@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify({"ok":True})


@app.get("/api/state")
@require_auth
def api_state():
    p=get_player(); tick_reward_timer(p)
    db.session.commit()
    return jsonify(build_state(p))


@app.post("/api/evaluations")
@require_auth
def evaluate_attribute():
    data=request.get_json(silent=True) or {}
    code=str(data.get("attribute", "")); score=data.get("score")
    if code not in ATTR_BY_CODE: return api_error("Atributo inválido.")
    try: score=int(score)
    except (TypeError,ValueError): return api_error("Escolha uma pontuação válida.")
    if score not in (0,3,6,9): return api_error("A pontuação deve ser 0, 3, 6 ou 9 XP.")
    day=today_key()
    if DailyEvaluation.query.filter_by(attribute=code,day=day).first():
        return api_error("Esse atributo já recebeu autoavaliação hoje.")
    p=get_player(); xp=clone_json(p.xp_by_attribute,default_xp()); xp[code]=int(xp.get(code,0))+score; p.xp_by_attribute=xp
    db.session.add(DailyEvaluation(attribute=code,day=day,score=score,xp=score))
    reward_message=""
    if score>0:
        ensure_daily_reset(p)
        before=int(p.daily_reward_seconds)
        p.daily_reward_seconds=min(DAILY_REWARD_CAP,before+DAILY_REWARD_PER_TASK)
        gained=p.daily_reward_seconds-before
        reward_message=f"+{gained//60}m{gained%60:02d}s de recompensa." if gained else "Limite de recompensa diária já atingido."
        physical_codes={"DEF","ATK","AGI","RES"}
        if code in physical_codes and p.physical_unlock_date != day:
            p.physical_chapters=int(p.physical_chapters)+1; p.physical_unlock_date=day
            reward_message += f" Capítulo ímpar {p.physical_chapters*2-1} desbloqueado!"
        if code=="MAG" and p.study_unlock_date != day:
            p.study_chapters=int(p.study_chapters)+1; p.study_unlock_date=day
            reward_message += f" Capítulo par {p.study_chapters*2} desbloqueado!"
    db.session.commit()
    return jsonify({"ok":True,"message":f"Autoavaliação registrada: +{score} XP. {reward_message}".strip(),"state":build_state(p)})


@app.post("/api/activities")
@require_auth
def create_activity():
    data=request.get_json(silent=True) or {}
    code=str(data.get("attribute", "")); title=str(data.get("title", "")).strip(); note=str(data.get("note", "")).strip()
    if code not in ATTR_BY_CODE: return api_error("Atributo inválido.")
    if not title or len(title)>160: return api_error("Informe uma descrição com até 160 caracteres.")
    raw=data.get("value", None)
    value=None
    if raw not in (None, ""):
        try: value=float(raw)
        except (TypeError,ValueError): return api_error("O valor precisa ser numérico.")
        if abs(value)>1e12: return api_error("Valor fora do limite.")
    if len(note)>600: return api_error("A observação aceita até 600 caracteres.")
    rec=Activity(attribute=code,title=title,value=value,note=note or None)
    db.session.add(rec); db.session.commit()
    return jsonify({"ok":True,"message":"Registro salvo. Anotações não concedem XP.","state":build_state(get_player())})


@app.put("/api/activities/<int:activity_id>")
@require_auth
def update_activity(activity_id: int):
    rec=db.session.get(Activity,activity_id)
    if not rec: return api_error("Registro não encontrado.",404)
    data=request.get_json(silent=True) or {}
    title=str(data.get("title",rec.title)).strip(); note=str(data.get("note",rec.note or "")).strip()
    if not title or len(title)>160: return api_error("Informe uma descrição com até 160 caracteres.")
    raw=data.get("value",rec.value); value=None
    if raw not in (None,""):
        try:value=float(raw)
        except (TypeError,ValueError):return api_error("Valor precisa ser numérico.")
    rec.title=title;rec.note=note or None;rec.value=value;db.session.commit()
    return jsonify({"ok":True,"message":"Registro atualizado sem alterar XP.","state":build_state(get_player())})


@app.delete("/api/activities/<int:activity_id>")
@require_auth
def delete_activity(activity_id: int):
    rec=db.session.get(Activity,activity_id)
    if not rec:return api_error("Registro não encontrado.",404)
    db.session.delete(rec);db.session.commit()
    return jsonify({"ok":True,"message":"Registro excluído.","state":build_state(get_player())})


@app.get("/api/charts")
@require_auth
def api_charts():
    a=request.args.get("a","HP"); b=request.args.get("b",""); group=request.args.get("group","day")
    days=request.args.get("days","30")
    if a not in ATTR_BY_CODE: return api_error("Atributo principal inválido.")
    if b and b not in ATTR_BY_CODE:return api_error("Segundo atributo inválido.")
    if group not in ("day","week","month"):return api_error("Agrupamento inválido.")
    try: horizon=None if days=="all" else max(1,min(3650,int(days)))
    except ValueError: horizon=30
    cutoff=local_now()-timedelta(days=horizon) if horizon else None
    query=Activity.query
    if cutoff: query=query.filter(Activity.created_at>=cutoff)
    records=query.filter(Activity.attribute.in_([a]+([b] if b else []))).order_by(Activity.created_at.asc()).all()
    groups={}
    for r in records:
        if r.value is None: continue
        d=r.created_at.date()
        if group=="week":
            d=d-timedelta(days=d.weekday()); key=d.isoformat(); label="Sem. "+d.strftime("%d/%m")
        elif group=="month": key=d.strftime("%Y-%m"); label=d.strftime("%m/%Y")
        else:key=d.isoformat();label=d.strftime("%d/%m")
        bucket=groups.setdefault(key,{"label":label,a:[],"count_a":0})
        if r.attribute==a: bucket[a].append(float(r.value));bucket["count_a"]+=1
        if b:
            bucket.setdefault(b,[])
            bucket["count_b"]=bucket.get("count_b",0)
            if r.attribute==b:bucket[b].append(float(r.value));bucket["count_b"]+=1
    data=[]
    for key in sorted(groups):
        bucket=groups[key]
        row={"label":bucket["label"],a:(round(sum(bucket[a])/len(bucket[a]),2) if bucket[a] else None),"count_a":bucket["count_a"]}
        if b: row[b]=(round(sum(bucket[b])/len(bucket[b]),2) if bucket.get(b) else None);row["count_b"]=bucket.get("count_b",0)
        data.append(row)
    return jsonify({"ok":True,"a":a,"b":b,"group":group,"days":days,"data":data})


@app.post("/api/equipment/equip")
@require_auth
def api_equip():
    data=request.get_json(silent=True) or {}
    p=get_player()
    if p.dungeon_state:
        return api_error("Equipe ou troque itens antes de iniciar a dungeon.")
    try: equip_item(p, data.get("item_id"))
    except ValueError as exc:return api_error(str(exc))
    db.session.commit()
    return jsonify({"ok":True,"message":"Equipamento atualizado.","state":build_state(get_player())})


@app.post("/api/items/use")
@require_auth
def api_use_item():
    data=request.get_json(silent=True) or {}; item_id=data.get("item_id")
    if item_id not in CONSUMABLES:return api_error("Poção inválida.")
    p=get_player(); run=clone_json(p.dungeon_state,None)
    if run and run.get("combat"):
        return api_error("Durante o combate, use a poção como sua ação de Item.")
    inv=clone_json(p.inventory,default_inventory()); qty=int(inv.get(item_id,0))
    rqty=int((run or {}).get("run_potions",{}).get(item_id,0))
    if qty<=0 and rqty<=0:return api_error("Você não possui essa poção.")
    stats=compute_player_stats(p.xp_by_attribute,p.equipped,p.current_hp,p.current_mp)
    item=CONSUMABLES[item_id]
    if item["effect"]=="heal":
        if p.current_hp>=stats["hp_max"]:return api_error("Seu HP já está cheio.")
        healed=min(item["amount"],stats["hp_max"]-p.current_hp);p.current_hp+=healed;msg=f"Poção de Cura: +{healed} HP."
    else:
        if p.current_mp>=stats["mp_max"]:return api_error("Seu MP já está cheio.")
        restored=min(item["amount"],stats["mp_max"]-p.current_mp);p.current_mp+=restored;msg=f"Poção de Mana: +{restored} MP."
    if rqty>0:
        run["run_potions"][item_id]=rqty-1;persist_run(p,run)
    else:
        inv[item_id]=qty-1;p.inventory=inv
    db.session.commit()
    return jsonify({"ok":True,"message":msg,"state":build_state(p)})


@app.post("/api/dungeon/start")
@require_auth
def api_dungeon_start():
    p=get_player()
    if p.dungeon_state:return api_error("Você já está explorando uma dungeon.")
    since=local_now()-timedelta(days=7)
    attempts=DungeonAttempt.query.filter(DungeonAttempt.started_at>=since).count()
    inv=clone_json(p.inventory,default_inventory())
    ticket_count=int(inv.get("ticket_dungeon",0))
    if attempts>=WEEKLY_DUNGEON_LIMIT and ticket_count<=0:return api_error("Limite atingido: são no máximo 2 explorações a cada 7 dias. Compre um Ticket de Dungeon na loja para entrar novamente.")
    if attempts>=WEEKLY_DUNGEON_LIMIT and ticket_count>0:
        inv["ticket_dungeon"]=ticket_count-1;p.inventory=inv
    xp=clone_json(p.xp_by_attribute,default_xp())
    run=create_dungeon(xp,random.Random())
    attempt=DungeonAttempt(started_at=local_now(),outcome="em_andamento",floors=run["floors"])
    db.session.add(attempt);db.session.flush()
    run["attempt_id"]=attempt.id
    p.last_dungeon_result=None
    persist_run(p,run);db.session.commit()
    return jsonify({"ok":True,"message":f"Dungeon iniciada: {run['floors']} andares.","state":build_state(p)})


@app.post("/api/dungeon/move")
@require_auth
def api_dungeon_move():
    p=get_player();run=clone_json(p.dungeon_state,None)
    if not run:return api_error("Inicie uma dungeon primeiro.")
    data=request.get_json(silent=True) or {}
    try: dx=int(data.get("dx"));dy=int(data.get("dy"))
    except (TypeError,ValueError):return api_error("Movimento inválido.")
    xp=clone_json(p.xp_by_attribute,default_xp())
    hp,mp,stats=current_resources(p)
    before=int(run.get("coins_found",0))
    try:run,events,status=move_in_dungeon(run,dx,dy,xp,stats,random.Random())
    except ValueError as exc:return api_error(str(exc))
    coin_diff=int(run.get("coins_found",0))-before
    if coin_diff>0:p.coins+=coin_diff
    if run.get("combat"):
        run["combat"]["player_hp"]=hp;run["combat"]["player_mp"]=mp
        enemy=run["combat"]["enemy"]
        run["combat"]["log"]=[f"{enemy['icon']} {enemy['name']} bloqueia o caminho!"]
    run["last_message"]=" ".join(events) if events else run.get("last_message","")
    persist_run(p,run);db.session.commit()
    return jsonify({"ok":True,"message":" ".join(events) if events else run["last_message"],"state":build_state(p)})


def _finalize_run(p: Player, run: dict, outcome: str, message: str):
    attempt_id=run.get("attempt_id")
    attempt=db.session.get(DungeonAttempt,int(attempt_id)) if attempt_id else None
    if attempt:
        attempt.outcome=outcome;attempt.ended_at=local_now()
    p.last_dungeon_result=message
    inv=clone_json(p.inventory,default_inventory())
    if outcome=="victory":
        equipment=inv.setdefault("equipment",{})
        for item_id in run.get("loot",[]):equipment[item_id]=int(equipment.get(item_id,0))+1
        for pot,qty in run.get("run_potions",{}).items():inv[pot]=int(inv.get(pot,0))+int(qty)
        # Vitória final concede 40 minutos especiais permanentes.
        p.permanent_special_seconds=int(p.permanent_special_seconds)+40*60
    elif outcome=="derrota" and run.get("loot") and int(inv.get("bracelete_salvacao",0))>0:
        equipment=inv.setdefault("equipment",{})
        for item_id in run.get("loot",[]):equipment[item_id]=int(equipment.get(item_id,0))+1
        inv["bracelete_salvacao"]-=1
        p.last_dungeon_result=message+" O Bracelete da Salvação foi consumido e preservou os equipamentos encontrados."
    p.inventory=inv
    p.dungeon_state=None


@app.post("/api/dungeon/action")
@require_auth
def api_dungeon_action():
    p=get_player();run=clone_json(p.dungeon_state,None)
    if not run or not run.get("combat"):return api_error("Não existe combate ativo.")
    data=request.get_json(silent=True) or {}
    inventory=clone_json(p.inventory,default_inventory())
    xp=clone_json(p.xp_by_attribute,default_xp())
    hp,mp,stats=current_resources(p)
    snapshot={"hp":hp,"mp":mp,"hp_max":stats["hp_max"],"mp_max":stats["mp_max"],"stats":stats["stats"]}
    try:result=resolve_player_action(run,snapshot,data,inventory,xp,clone_json(p.equipped,{}),random.Random())
    except ValueError as exc:return api_error(str(exc))
    p.inventory=inventory
    events=result["events"]
    if result["result"]=="enemy_defeated":
        enemy=run["combat"]["enemy"]; monster_id=enemy["id"]
        spec=MONSTER_BY_ID[monster_id]
        reward=award_monster_rewards(monster_id,xp,clone_json(p.equipped,{}),random.Random())
        p.coins=int(p.coins)+int(reward["coins"])
        run.setdefault("loot",[]).extend(reward["items"])
        if any(s.get("action")=="on_kill_mp" for s in effective_skills(xp,p.equipped).values()):
            livehp=int(run["combat"].get("player_hp",p.current_hp)); livemp=int(run["combat"].get("player_mp",p.current_mp))
            p.current_mp=min(stats["mp_max"],livemp+5);run["combat"]["player_mp"]=p.current_mp
            events.append("Absorção: +5 MP por derrotar o inimigo.")
        events.append(f"{spec['name']} derrotado. +{reward['coins']} moedas.")
        for item_id in reward["items"]:events.append(f"Drop: {ITEM_BY_ID[item_id]['name']}.")
        events.extend(reward["messages"])
        obj_id=enemy.get("object_id")
        obj=next((o for o in run.get("objects",[]) if o.get("id")==obj_id),None)
        if obj:
            run["x"],run["y"]=obj["x"],obj["y"]
            if [run["x"],run["y"]] not in run.get("visited",[]):run.setdefault("visited",[]).append([run["x"],run["y"]])
            run["objects"]=[o for o in run["objects"] if o.get("id")!=obj_id]
        p.current_hp=int(run["combat"].get("player_hp",p.current_hp));p.current_mp=int(run["combat"].get("player_mp",p.current_mp))
        boss=spec["tier"]=="boss"
        run["combat"]=None
        if boss:
            _finalize_run(p,run,"victory",f"Vitória! Você derrotou {spec['name']} e concluiu a dungeon. +40 minutos especiais.")
            events.append("Dungeon concluída! Seu loot foi guardado no inventário.")
        else:
            run["last_message"]=f"Vitória contra {spec['name']}! Continue explorando."
            persist_run(p,run)
    elif result["result"]=="player_defeated":
        p.current_hp=10;p.current_mp=10
        enemy=run["combat"]["enemy"]
        _finalize_run(p,run,"derrota",f"Você foi derrotado por {enemy['name']}. O loot desta exploração foi perdido; moedas preservadas. HP/MP voltaram para 10.")
        events.append("Derrota: itens da dungeon perdidos. Moedas preservadas. HP=10, MP=10.")
    else:
        p.current_hp=int(run["combat"].get("player_hp",p.current_hp));p.current_mp=int(run["combat"].get("player_mp",p.current_mp))
        run["last_message"]=" ".join(events[-2:])
        persist_run(p,run)
    db.session.commit()
    return jsonify({"ok":True,"message":" ".join(events),"events":events,"state":build_state(p)})


@app.post("/api/dungeon/abandon")
@require_auth
def api_dungeon_abandon():
    p=get_player();run=p.dungeon_state
    if not run:return api_error("Não há dungeon ativa.")
    p.current_hp=10;p.current_mp=10
    _finalize_run(p,clone_json(run,{}),"abandonada","Dungeon abandonada; itens temporários foram perdidos e moedas foram preservadas. HP/MP voltaram para 10.")
    db.session.commit()
    return jsonify({"ok":True,"message":p.last_dungeon_result,"state":build_state(p)})


@app.post("/api/shop/buy")
@require_auth
def api_shop_buy():
    data=request.get_json(silent=True) or {}; item_id=str(data.get("item_id", ""))
    prices={"pocao_cura":30,"pocao_mana":30,"bracelete_salvacao":500,"ticket_dungeon":600,"minute":1000}
    labels={"pocao_cura":"Poção de Cura","pocao_mana":"Poção de Mana","bracelete_salvacao":"Bracelete da Salvação","ticket_dungeon":"Ticket de Dungeon","minute":"1 minuto adicional"}
    if item_id not in prices:return api_error("Item não encontrado na loja.")
    p=get_player();price=prices[item_id]
    if int(p.coins)<price:return api_error(f"Moedas insuficientes. Você precisa de {price} moedas.")
    p.coins-=price
    if item_id=="minute":p.permanent_special_seconds=int(p.permanent_special_seconds)+60
    else:
        inv=clone_json(p.inventory,default_inventory());inv[item_id]=int(inv.get(item_id,0))+1;p.inventory=inv
    db.session.commit()
    return jsonify({"ok":True,"message":f"Compra realizada: {labels[item_id]}.","state":build_state(p)})


@app.post("/api/rewards/session")
@require_auth
def api_reward_session():
    data=request.get_json(silent=True) or {}; active=bool(data.get("active"))
    p=get_player();tick_reward_timer(p)
    if active:
        if int(p.daily_reward_seconds)<=0 and int(p.permanent_special_seconds)<=0:
            db.session.commit();return api_error("Sem saldo de tempo. Complete tarefas ou derrote um chefe.")
        p.reward_session_active=True;p.reward_last_tick_at=local_now()
    else:
        p.reward_session_active=False;p.reward_last_tick_at=None
    db.session.commit()
    return jsonify({"ok":True,"message":"Sessão de recompensa iniciada." if active else "Sessão de recompensa pausada.","state":build_state(p)})


@app.post("/api/rewards/tick")
@require_auth
def api_reward_tick():
    p=get_player();tick_reward_timer(p);db.session.commit()
    return jsonify({"ok":True,"daily":int(p.daily_reward_seconds),"special":int(p.permanent_special_seconds),"active":bool(p.reward_session_active)})


@app.errorhandler(404)
def not_found(_):
    if request.path.startswith("/api/"):return api_error("Rota não encontrada.",404)
    return render_template("login.html"),404

@app.errorhandler(500)
def server_error(_):
    db.session.rollback()
    if request.path.startswith("/api/"):return api_error("Erro interno. Verifique os logs do servidor.",500)
    return "Erro interno do servidor.",500


with app.app_context():
    db.create_all()
    player=db.session.get(Player,1)
    if player is None:
        player=Player(id=1,xp_by_attribute=default_xp(),inventory=default_inventory(),equipped={},coins=0,current_hp=25,current_mp=11,daily_reward_date=today_key())
        db.session.add(player);db.session.commit()
    else:
        if player.inventory is None:player.inventory=default_inventory()
        if "pocao_cura" not in player.inventory:
            inv=clone_json(player.inventory,default_inventory());inv.setdefault("pocao_cura",2);inv.setdefault("pocao_mana",2);inv.setdefault("equipment",{});player.inventory=inv
        if not player.xp_by_attribute:player.xp_by_attribute=default_xp()
        db.session.commit()

if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG") == "1", host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
