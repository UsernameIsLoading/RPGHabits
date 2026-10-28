from __future__ import annotations
import copy
import os
import random
from datetime import date, datetime, timedelta
from functools import wraps
from pathlib import Path
from io import BytesIO
import json
import gzip
import secrets
import uuid
from werkzeug.security import generate_password_hash, check_password_hash
from zoneinfo import ZoneInfo

from flask import Flask, jsonify, render_template, request, session, redirect, url_for, send_file, make_response
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import UniqueConstraint, func, inspect, text

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
    SESSION_COOKIE_SECURE=os.getenv("SESSION_COOKIE_SECURE", "true" if os.getenv("RENDER") else "false").strip().lower() in ("1", "true", "yes"),
    JSON_SORT_KEYS=False,
    MAX_CONTENT_LENGTH=50 * 1024 * 1024,
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
)
db = SQLAlchemy(app)


def default_xp() -> dict[str, int]:
    return {a["code"]: 0 for a in ATTRIBUTES}


def default_inventory() -> dict:
    return {"pocao_cura": 2, "pocao_mana": 2, "equipment": {}, "bracelete_salvacao": 0, "ticket_dungeon": 0}


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(48), unique=True, nullable=False, index=True)
    # Some older deployed databases require email even though the current UI uses usernames.
    # Keep it mapped so inserts satisfy both old and new schemas.
    email = db.Column(db.String(255), nullable=True)
    password_hash = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, nullable=False, default=False)
    # Idempotency marker: prevents a legacy single-player profile being imported twice.
    legacy_progress_imported = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=local_now)


class Player(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True, unique=True, index=True)
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
    class_code = db.Column(db.String(24), nullable=True)
    task_mapping = db.Column(db.JSON, nullable=False, default=dict)
    task_mapping_version = db.Column(db.Integer, nullable=False, default=0)
    setup_complete = db.Column(db.Boolean, nullable=False, default=False)
    relics_owned = db.Column(db.JSON, nullable=False, default=list)
    active_relic_id = db.Column(db.String(24), nullable=True)
    manto_xp_remainder = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=local_now)


class DailyEvaluation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True, index=True)
    attribute = db.Column(db.String(8), nullable=False)
    day = db.Column(db.String(10), nullable=False)
    score = db.Column(db.Integer, nullable=False)
    xp = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=local_now)
    __table_args__ = (UniqueConstraint("user_id", "attribute", "day", name="uq_user_daily_attribute_day"),)


class Activity(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True, index=True)
    attribute = db.Column(db.String(8), nullable=False)
    title = db.Column(db.String(160), nullable=False)
    value = db.Column(db.Float, nullable=True)
    note = db.Column(db.String(600), nullable=True)
    client_ref = db.Column(db.String(80), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=local_now)
    __table_args__ = (UniqueConstraint("user_id", "client_ref", name="uq_user_activity_client_ref"),)


class DungeonAttempt(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True, index=True)
    started_at = db.Column(db.DateTime, nullable=False, default=local_now)
    outcome = db.Column(db.String(24), nullable=False, default="em_andamento")
    floors = db.Column(db.Integer, nullable=False, default=0)
    ended_at = db.Column(db.DateTime, nullable=True)


class AdminBackup(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    created_by_username = db.Column(db.String(48), nullable=False)
    filename = db.Column(db.String(140), nullable=False)
    content_gzip = db.Column(db.LargeBinary, nullable=False)
    size_bytes = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=local_now)


class IdempotencyRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    operation_id = db.Column(db.String(80), nullable=False)
    response_json = db.Column(db.JSON, nullable=False)
    status_code = db.Column(db.Integer, nullable=False, default=200)
    created_at = db.Column(db.DateTime, nullable=False, default=local_now)
    __table_args__ = (UniqueConstraint("user_id", "operation_id", name="uq_user_operation_id"),)


CLASS_DEFINITIONS = {
    "guardiao": {"sprite_url": "/static/sprites/guardiao.svg", "name": "Guardião", "dominant": "HP", "sprite": "🛡️", "description": "Sobrevivência e resistência."},
    "sentinela": {"sprite_url": "/static/sprites/sentinela.svg", "name": "Sentinela", "dominant": "DEF", "sprite": "🏰", "description": "Proteção e defesa."},
    "lutador": {"sprite_url": "/static/sprites/lutador.svg", "name": "Lutador", "dominant": "ATK", "sprite": "🥊", "description": "Força ofensiva."},
    "duelista": {"sprite_url": "/static/sprites/duelista.svg", "name": "Duelista", "dominant": "AGI", "sprite": "⚔️", "description": "Velocidade e mobilidade."},
    "invocador": {"sprite_url": "/static/sprites/invocador.svg", "name": "Invocador", "dominant": "MP", "sprite": "🔮", "description": "Reserva espiritual."},
    "arcanista": {"sprite_url": "/static/sprites/arcanista.svg", "name": "Arcanista", "dominant": "MAG", "sprite": "🧙", "description": "Poder mágico."},
    "monge": {"sprite_url": "/static/sprites/monge.svg", "name": "Monge", "dominant": "RES", "sprite": "🥋", "description": "Resistência e constância."},
    "explorador": {"sprite_url": "/static/sprites/explorador.svg", "name": "Explorador", "dominant": "LUC", "sprite": "🧭", "description": "Sorte e descoberta."},
}
DEFAULT_TASKS = {a["code"]: a["activity"] for a in ATTRIBUTES}
RELIC_CATALOG = {
    "manto_heroi_esquecido": {"id": "manto_heroi_esquecido", "name": "Manto do Herói Esquecido", "icon": "🧥", "price": 2500, "kind": "passive", "description": "A cada 10 XP obtidos, concede 1 XP adicional ao atributo que gerou a experiência."},
    "anel_investidor_nato": {"id": "anel_investidor_nato", "name": "Anel do Investidor Nato", "icon": "💍", "price": 1500, "kind": "utility", "description": "Converte tempo diário de recompensa em moedas: 1 moeda por segundo vendido."},
    "pingente_deusa_amor": {"id": "pingente_deusa_amor", "name": "Pingente da Deusa do Amor", "icon": "💗", "price": 500, "kind": "consumable", "description": "Uso único: transfere 10 XP de um atributo para outro, sem criar XP."},
}


def api_error(message: str, status: int = 400):
    return jsonify({"ok": False, "error": message}), status


def require_auth(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return api_error("Sessão encerrada. Entre novamente.", 401)
        user = db.session.get(User, int(session["user_id"]))
        if not user:
            session.clear()
            return api_error("Conta não encontrada. Entre novamente.", 401)
        return fn(*args, **kwargs)
    return wrapped


def current_user() -> User:
    uid = session.get("user_id")
    user = db.session.get(User, int(uid)) if uid else None
    if not user:
        raise RuntimeError("Usuário autenticado não encontrado.")
    return user


def default_task_mapping() -> dict[str, str]:
    return dict(DEFAULT_TASKS)


def clone_json(value, fallback):
    return copy.deepcopy(value) if value is not None else copy.deepcopy(fallback)


def get_player(lock: bool = False) -> Player:
    user = current_user()
    query = Player.query.filter_by(user_id=user.id)
    # Serialize mutations for the same account on PostgreSQL, preventing two devices
    # from overwriting each other's coin, XP, inventory, or dungeon updates.
    if lock:
        query = query.with_for_update()
    p = query.first()
    if p is None:
        p = Player(user_id=user.id, xp_by_attribute=default_xp(), inventory=default_inventory(), equipped={},
                   coins=0, current_hp=25, current_mp=11, daily_reward_date=today_key(),
                   task_mapping=default_task_mapping(), relics_owned=[])
        db.session.add(p)
        db.session.flush()
    if not p.xp_by_attribute:
        p.xp_by_attribute = default_xp()
    if not p.inventory:
        p.inventory = default_inventory()
    inv = clone_json(p.inventory, default_inventory())
    for key, value in default_inventory().items():
        if key not in inv:
            inv[key] = copy.deepcopy(value)
    if "equipment" not in inv or not isinstance(inv.get("equipment"), dict): inv["equipment"] = {}
    p.inventory = inv
    if p.equipped is None: p.equipped = {}
    if not p.task_mapping:
        p.task_mapping = default_task_mapping()
    else:
        mapping = default_task_mapping(); mapping.update(p.task_mapping); p.task_mapping = mapping
    if p.relics_owned is None: p.relics_owned = []
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
    return {"equipment": equipment, "consumables": consumables, "equipped": equipped, "bracelete_salvacao": int(inv.get("bracelete_salvacao", 0)), "ticket_dungeon": int(inv.get("ticket_dungeon", 0)), "relics": [RELIC_CATALOG[r] for r in (p.relics_owned or []) if r in RELIC_CATALOG], "pingente_deusa_amor": int(inv.get("pingente_deusa_amor", 0))}


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
        attrs.append({**attr, "activity": (p.task_mapping or DEFAULT_TASKS).get(code, attr["activity"]), **r, "today_evaluation": None})
    daily = {e.attribute: {"score": e.score, "xp": e.xp} for e in DailyEvaluation.query.filter_by(user_id=p.user_id, day=today_key()).all()}
    for attr in attrs: attr["today_evaluation"] = daily.get(attr["code"])
    activities = Activity.query.filter_by(user_id=p.user_id).order_by(Activity.created_at.desc()).limit(150).all()
    skill_rows = describe_player_skills(p.xp_by_attribute or default_xp(), p.equipped or {})
    skills = []
    combat_for_skills = (run or {}).get("combat") or {}
    for s in skill_rows:
        cooldown = int(combat_for_skills.get("cooldowns", {}).get(s["id"], 0))
        skills.append({**s, "cooldown_left": cooldown, "usable_now": bool(s["unlocked"] and s["kind"] == "active" and cooldown == 0)})
    weekly_count = DungeonAttempt.query.filter_by(user_id=p.user_id).filter(DungeonAttempt.started_at >= local_now() - timedelta(days=7)).count()
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
    today_xp = db.session.query(func.coalesce(func.sum(DailyEvaluation.xp), 0)).filter_by(user_id=p.user_id, day=today_key()).scalar() or 0
    return {
        "ok": True,
        "player": {"coins": int(p.coins), "hp": hp, "hp_max": stats["hp_max"], "mp": mp, "mp_max": stats["mp_max"],
                   "stats": stats["stats"], "attributes": attrs, "today_xp": int(today_xp), "weekly_dungeons": weekly_count,
                   "weekly_limit": WEEKLY_DUNGEON_LIMIT, "inventory": inventory_payload(p), "equipped": p.equipped or {},
                   "daily_reward_seconds": int(p.daily_reward_seconds), "special_reward_seconds": int(p.permanent_special_seconds),
                   "reward_session_active": bool(p.reward_session_active),
                   "last_dungeon_result": p.last_dungeon_result,
                   "username": current_user().username, "account_id": int(current_user().id), "is_admin": bool(current_user().is_admin),
                   "class_code": p.class_code, "class": CLASS_DEFINITIONS.get(p.class_code or ""),
                   "setup_complete": bool(p.setup_complete), "task_mapping": p.task_mapping or default_task_mapping(),
                   "task_mapping_version": int(p.task_mapping_version or 0),
                   "relics_owned": [RELIC_CATALOG[r] for r in (p.relics_owned or []) if r in RELIC_CATALOG],
                   "active_relic_id": p.active_relic_id,
                   "manto_xp_remainder": int(p.manto_xp_remainder or 0)},
        "skills": skills,
        "items": ITEMS,
        "consumables": list(CONSUMABLES.values()),
        "daily_evaluations": daily,
        "activities": [{"id":a.id,"client_ref":a.client_ref,"attribute":a.attribute,"title":a.title,"value":a.value,"note":a.note,
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


@app.get("/service-worker.js")
def service_worker_script():
    # A root-level URL is required so the worker can control the entire app, not only /static/.
    response = send_file(Path(__file__).resolve().parent / "static" / "service-worker.js",
                         mimetype="application/javascript", conditional=True)
    response.headers["Cache-Control"] = "no-cache"
    response.headers["Service-Worker-Allowed"] = "/"
    return response


@app.get("/")
def index():
    if session.get("user_id"):
        user = db.session.get(User, int(session["user_id"]))
        if user:
            if user.is_admin and request.args.get("admin") == "1":
                return redirect(url_for("admin_page"))
            p = Player.query.filter_by(user_id=user.id).first()
            if p and p.setup_complete:
                return render_template("index.html")
            return render_template("setup.html", classes=CLASS_DEFINITIONS)
    return render_template("login.html")


@app.post("/api/register")
def register():
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip().lower()
    password = str(data.get("password", ""))
    if not (3 <= len(username) <= 48) or not all(c.isalnum() or c in "_.-" for c in username):
        return api_error("O usuário deve ter 3–48 caracteres: letras, números, ponto, hífen ou sublinhado.")
    if len(password) < 10 or len(password) > 128:
        return api_error("A senha deve ter entre 10 e 128 caracteres.")
    if User.query.filter_by(username=username).first():
        return api_error("Esse nome de usuário já está em uso.")
    user = User(
        username=username,
        email=f"{username}@users.rpg-habitos.invalid",
        password_hash=generate_password_hash(password),
        is_admin=False,
    )
    db.session.add(user); db.session.flush()
    player = Player(user_id=user.id, xp_by_attribute=default_xp(), inventory=default_inventory(), equipped={},
                    coins=0, current_hp=25, current_mp=11, daily_reward_date=today_key(),
                    task_mapping=default_task_mapping(), relics_owned=[], setup_complete=False)
    db.session.add(player); db.session.commit()
    session.clear(); session["user_id"] = user.id; session["is_admin"] = False; session.permanent = True
    return jsonify({"ok": True, "message": "Conta criada. Escolha a classe do personagem."})


@app.post("/api/login")
def login():
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip().lower()
    supplied = str(data.get("password", ""))
    user = User.query.filter_by(username=username).first() if username else None
    if not user or not check_password_hash(user.password_hash, supplied):
        return api_error("Usuário ou senha incorretos.", 401)
    session.clear(); session["user_id"] = user.id; session["is_admin"] = bool(user.is_admin); session.permanent = True
    return jsonify({"ok": True, "admin": bool(user.is_admin)})


@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify({"ok": True})


@app.post("/api/setup")
@require_auth
def setup_character():
    data = request.get_json(silent=True) or {}
    class_code = str(data.get("class_code", ""))
    if class_code not in CLASS_DEFINITIONS:
        return api_error("Escolha uma classe válida.")
    p = get_player(lock=True)
    if p.setup_complete:
        return api_error("A criação do personagem já foi concluída. A classe não pode ser alterada aqui.")
    p.class_code = class_code
    p.setup_complete = True
    # Tasks are initialized to the default mappings and can be edited afterward.
    if not p.task_mapping: p.task_mapping = default_task_mapping()
    db.session.commit()
    return jsonify({"ok": True, "message": f"Personagem criado: {CLASS_DEFINITIONS[class_code]['name']}.", "redirect": "/"})


@app.post("/api/tasks")
@require_auth
def update_tasks():
    data = request.get_json(silent=True) or {}
    mapping = data.get("mapping")
    if not isinstance(mapping, dict): return api_error("Configuração de tarefas inválida.")
    p = get_player(lock=True)
    base_version = data.get("base_version")
    if base_version is not None:
        try: base_version = int(base_version)
        except (TypeError, ValueError): return api_error("Versão de configuração inválida.")
        if base_version != int(p.task_mapping_version or 0):
            return jsonify({"ok": False, "conflict": True, "error": "As tarefas também foram alteradas em outro dispositivo.",
                            "current_mapping": p.task_mapping or default_task_mapping(),
                            "current_version": int(p.task_mapping_version or 0)}), 409
    allowed = set(ATTR_BY_CODE)
    cleaned = {}
    for code in allowed:
        task = str(mapping.get(code, (p.task_mapping or DEFAULT_TASKS).get(code, DEFAULT_TASKS[code]))).strip()
        if not task or len(task) > 80: return api_error("Cada tarefa deve ter entre 1 e 80 caracteres.")
        cleaned[code] = task
    norm = [x.casefold() for x in cleaned.values()]
    if len(set(norm)) != len(norm): return api_error("Cada tarefa deve estar associada a um único atributo.")
    p.task_mapping = cleaned
    p.task_mapping_version = int(p.task_mapping_version or 0) + 1
    db.session.commit()
    return jsonify({"ok": True, "message": "Tarefas atualizadas.", "state": build_state(p)})


@app.get("/admin")
@require_auth
def admin_page():
    if not current_user().is_admin: return api_error("Acesso administrativo necessário.", 403)
    return render_template("admin.html")


@app.get("/api/state")
@require_auth
def api_state():
    p=get_player(lock=True); tick_reward_timer(p)
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
    day = str(data.get("day") or today_key())
    try:
        day_date = date.fromisoformat(day)
        if day_date > datetime.now(TZ).date(): return api_error("A data da avaliação não pode estar no futuro.")
    except ValueError:
        return api_error("Data da avaliação inválida.")
    user = current_user()
    p = get_player(lock=True)
    existing_eval = DailyEvaluation.query.filter_by(user_id=user.id, attribute=code, day=day).first()
    if existing_eval:
        return jsonify({"ok": False, "conflict": True, "conflict_type": "daily_evaluation",
                        "error": "Esse atributo já recebeu autoavaliação nessa data.",
                        "server_evaluation": {"attribute": existing_eval.attribute, "day": existing_eval.day,
                                              "score": existing_eval.score, "xp": existing_eval.xp}}), 409
    xp=clone_json(p.xp_by_attribute,default_xp())
    base_xp = score
    class_data = CLASS_DEFINITIONS.get(p.class_code or "", {})
    gained = score * 2 if class_data.get("dominant") == code else score
    relics = list(p.relics_owned or [])
    bonus = 0
    if p.active_relic_id == "manto_heroi_esquecido" and "manto_heroi_esquecido" in relics and gained > 0:
        total = int(p.manto_xp_remainder or 0) + gained
        bonus = total // 10
        p.manto_xp_remainder = total % 10
    xp[code]=int(xp.get(code,0))+gained+bonus; p.xp_by_attribute=xp
    db.session.add(DailyEvaluation(user_id=user.id,attribute=code,day=day,score=score,xp=gained+bonus))
    reward_message=""
    if score>0:
        if day == today_key():
            ensure_daily_reset(p)
            before=int(p.daily_reward_seconds)
            p.daily_reward_seconds=min(DAILY_REWARD_CAP,before+DAILY_REWARD_PER_TASK)
            reward_seconds_gained=p.daily_reward_seconds-before
            reward_message=f"+{reward_seconds_gained//60}m{reward_seconds_gained%60:02d}s de recompensa." if reward_seconds_gained else "Limite de recompensa diária já atingido."
        else:
            reward_message="A avaliação offline foi sincronizada; o saldo diário antigo já expirou."
    db.session.commit()
    return jsonify({"ok":True,"message":f"Autoavaliação registrada: +{gained} XP" + (f" e +{bonus} XP do Manto." if bonus else ".") + (" " + reward_message if reward_message else ""),"state":build_state(p)})


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
    client_ref = str(data.get("client_ref", "")).strip()[:80] or None
    if client_ref:
        existing = Activity.query.filter_by(user_id=current_user().id, client_ref=client_ref).first()
        if existing:
            return jsonify({"ok": True, "message": "Registro já sincronizado.", "state": build_state(get_player())})
    rec=Activity(user_id=current_user().id,attribute=code,title=title,value=value,note=note or None,client_ref=client_ref)
    db.session.add(rec); db.session.commit()
    return jsonify({"ok":True,"message":"Registro salvo. Anotações não concedem XP.","state":build_state(get_player())})


@app.put("/api/activities/<path:activity_id>")
@require_auth
def update_activity(activity_id: str):
    q = Activity.query.filter_by(user_id=current_user().id)
    rec = q.filter_by(id=int(activity_id)).first() if str(activity_id).isdigit() else q.filter_by(client_ref=str(activity_id)).first()
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


@app.delete("/api/activities/<path:activity_id>")
@require_auth
def delete_activity(activity_id: int):
    q = Activity.query.filter_by(user_id=current_user().id)
    rec = q.filter_by(id=int(activity_id)).first() if str(activity_id).isdigit() else q.filter_by(client_ref=str(activity_id)).first()
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
    query=Activity.query.filter_by(user_id=current_user().id)
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
    p=get_player(lock=True)
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
    p=get_player(lock=True); run=clone_json(p.dungeon_state,None)
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
    p=get_player(lock=True)
    if p.dungeon_state:return api_error("Você já está explorando uma dungeon.")
    since=local_now()-timedelta(days=7)
    attempts=DungeonAttempt.query.filter_by(user_id=current_user().id).filter(DungeonAttempt.started_at>=since).count()
    inv=clone_json(p.inventory,default_inventory())
    ticket_count=int(inv.get("ticket_dungeon",0))
    if attempts>=WEEKLY_DUNGEON_LIMIT and ticket_count<=0:return api_error("Limite atingido: são no máximo 2 explorações a cada 7 dias. Compre um Ticket de Dungeon na loja para entrar novamente.")
    if attempts>=WEEKLY_DUNGEON_LIMIT and ticket_count>0:
        inv["ticket_dungeon"]=ticket_count-1;p.inventory=inv
    xp=clone_json(p.xp_by_attribute,default_xp())
    run=create_dungeon(xp,random.Random())
    attempt=DungeonAttempt(user_id=current_user().id,started_at=local_now(),outcome="em_andamento",floors=run["floors"])
    db.session.add(attempt);db.session.flush()
    run["attempt_id"]=attempt.id
    p.last_dungeon_result=None
    persist_run(p,run);db.session.commit()
    return jsonify({"ok":True,"message":f"Dungeon iniciada: {run['floors']} andares.","state":build_state(p)})


@app.post("/api/dungeon/move")
@require_auth
def api_dungeon_move():
    p=get_player(lock=True);run=clone_json(p.dungeon_state,None)
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
    attempt=DungeonAttempt.query.filter_by(id=int(attempt_id),user_id=p.user_id).first() if attempt_id else None
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
    p=get_player(lock=True);run=clone_json(p.dungeon_state,None)
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
    p=get_player(lock=True);run=p.dungeon_state
    if not run:return api_error("Não há dungeon ativa.")
    p.current_hp=10;p.current_mp=10
    _finalize_run(p,clone_json(run,{}),"abandonada","Dungeon abandonada; itens temporários foram perdidos e moedas foram preservadas. HP/MP voltaram para 10.")
    db.session.commit()
    return jsonify({"ok":True,"message":p.last_dungeon_result,"state":build_state(p)})


@app.post("/api/shop/buy")
@require_auth
def api_shop_buy():
    data=request.get_json(silent=True) or {}; item_id=str(data.get("item_id", ""))
    prices={"pocao_cura":30,"pocao_mana":30,"bracelete_salvacao":500,"ticket_dungeon":600,"minute":1000, **{k:v["price"] for k,v in RELIC_CATALOG.items()}}
    labels={"pocao_cura":"Poção de Cura","pocao_mana":"Poção de Mana","bracelete_salvacao":"Bracelete da Salvação","ticket_dungeon":"Ticket de Dungeon","minute":"1 minuto adicional", **{k:v["name"] for k,v in RELIC_CATALOG.items()}}
    if item_id not in prices:return api_error("Item não encontrado na loja.")
    p=get_player(lock=True);price=prices[item_id]
    if int(p.coins)<price:return api_error(f"Moedas insuficientes. Você precisa de {price} moedas.")
    p.coins-=price
    if item_id=="minute":p.permanent_special_seconds=int(p.permanent_special_seconds)+60
    elif item_id in RELIC_CATALOG:
        owned = list(p.relics_owned or [])
        if item_id == "pingente_deusa_amor":
            # Consumíveis podem ser comprados em múltiplas unidades; store count in inventory.
            inv=clone_json(p.inventory,default_inventory()); inv.setdefault("pingente_deusa_amor",0); inv["pingente_deusa_amor"] += 1; p.inventory=inv
        elif item_id not in owned:
            owned.append(item_id); p.relics_owned=owned
            if p.active_relic_id is None: p.active_relic_id = item_id
        else:
            p.coins += price
            db.session.rollback()
            return api_error("Você já possui esta relíquia permanente.")
    else:
        inv=clone_json(p.inventory,default_inventory());inv[item_id]=int(inv.get(item_id,0))+1;p.inventory=inv
    db.session.commit()
    return jsonify({"ok":True,"message":f"Compra realizada: {labels[item_id]}.","state":build_state(p)})


@app.post("/api/relics/activate")
@require_auth
def activate_relic():
    data = request.get_json(silent=True) or {}
    relic_id = str(data.get("relic_id", ""))
    if relic_id not in ("manto_heroi_esquecido", "anel_investidor_nato"):
        return api_error("Escolha uma relíquia passiva válida.")
    p = get_player(lock=True)
    if relic_id not in (p.relics_owned or []):
        return api_error("Você ainda não possui essa relíquia.")
    # Compare-and-swap: concurrent devices must be asked before replacing a different selection.
    if "base_active_relic_id" in data and data.get("base_active_relic_id") != p.active_relic_id:
        return jsonify({"ok": False, "conflict": True,
                        "error": "A relíquia ativa foi alterada em outro dispositivo.",
                        "current_active_relic_id": p.active_relic_id}), 409
    p.active_relic_id = relic_id
    db.session.commit()
    return jsonify({"ok": True, "message": f"{RELIC_CATALOG[relic_id]['name']} está ativa.", "state": build_state(p)})


@app.post("/api/relics/sell-time")
@require_auth
def sell_reward_time():
    data = request.get_json(silent=True) or {}
    try: seconds = int(data.get("seconds", 0))
    except (TypeError, ValueError): return api_error("Informe os segundos que deseja vender.")
    if seconds <= 0: return api_error("A venda precisa ser de pelo menos 1 segundo.")
    p = get_player(lock=True)
    if p.active_relic_id != "anel_investidor_nato" or "anel_investidor_nato" not in (p.relics_owned or []): return api_error("Ative o Anel do Investidor Nato para converter tempo em moedas.")
    tick_reward_timer(p)
    if seconds > int(p.daily_reward_seconds): return api_error("Você só pode vender o saldo diário normal; tempo especial não pode ser vendido.")
    p.daily_reward_seconds -= seconds
    p.coins += seconds
    db.session.commit()
    return jsonify({"ok": True, "message": f"{seconds} segundos convertidos em {seconds} moedas.", "state": build_state(p)})


@app.post("/api/relics/transfer")
@require_auth
def transfer_relic_xp():
    data = request.get_json(silent=True) or {}
    source = str(data.get("source", "")); target = str(data.get("target", ""))
    if source not in ATTR_BY_CODE or target not in ATTR_BY_CODE or source == target:
        return api_error("Escolha dois atributos diferentes.")
    p = get_player(lock=True)
    inv = clone_json(p.inventory, default_inventory())
    if int(inv.get("pingente_deusa_amor", 0)) <= 0: return api_error("Você não possui o Pingente da Deusa do Amor.")
    xp = clone_json(p.xp_by_attribute, default_xp())
    if int(xp.get(source, 0)) < 10: return api_error("O atributo de origem precisa ter pelo menos 10 XP.")
    xp[source] -= 10; xp[target] = int(xp.get(target, 0)) + 10
    p.xp_by_attribute = xp
    inv["pingente_deusa_amor"] = int(inv.get("pingente_deusa_amor", 0)) - 1; p.inventory = inv
    hp, mp, stats = current_resources(p)
    p.current_hp = min(hp, stats["hp_max"]); p.current_mp = min(mp, stats["mp_max"])
    db.session.commit()
    return jsonify({"ok": True, "message": f"10 XP transferidos de {source} para {target}. O Pingente foi consumido.", "state": build_state(p)})


def logical_backup_payload():
    def serialize(model):
        rows = model.query.order_by(model.id.asc()).all()
        output=[]
        for row in rows:
            values={}
            for column in model.__table__.columns:
                value=getattr(row,column.name)
                if isinstance(value, datetime): value=value.isoformat()
                values[column.name]=value
            output.append(values)
        return output
    return {"format":"rpg-habitos-backup-v1","created_at":local_now().isoformat(),"database":"logical-json","tables":{
        "user":serialize(User), "player":serialize(Player), "daily_evaluation":serialize(DailyEvaluation),
        "activity":serialize(Activity), "dungeon_attempt":serialize(DungeonAttempt),
        "idempotency_record":serialize(IdempotencyRecord)
    }}


@app.get("/api/admin/backups")
@require_auth
def admin_list_backups():
    if not current_user().is_admin: return api_error("Acesso administrativo necessário.", 403)
    rows=AdminBackup.query.order_by(AdminBackup.created_at.desc()).limit(10).all()
    return jsonify({"ok":True,"backups":[{"id":r.id,"filename":r.filename,"size_bytes":r.size_bytes,
        "created_at":r.created_at.isoformat(timespec="seconds"),"created_by":r.created_by_username} for r in rows]})


@app.get("/api/admin/backups/<int:backup_id>/download")
@require_auth
def admin_download_pre_restore_backup(backup_id: int):
    if not current_user().is_admin: return api_error("Acesso administrativo necessário.", 403)
    row=db.session.get(AdminBackup, backup_id)
    if not row: return api_error("Backup automático não encontrado.", 404)
    try: content=gzip.decompress(row.content_gzip)
    except Exception: return api_error("O backup automático está danificado.", 500)
    response=make_response(content)
    response.headers["Content-Type"]="application/json; charset=utf-8"
    response.headers["Content-Disposition"]=f'attachment; filename="{row.filename}"'
    response.headers["Cache-Control"]="no-store, private"
    return response


@app.post("/api/admin/backup/restore")
@require_auth
def admin_restore_backup():
    if not current_user().is_admin: return api_error("Acesso administrativo necessário.", 403)
    uploaded = request.files.get("backup")
    if not uploaded: return api_error("Selecione um arquivo JSON de backup.")
    if uploaded.content_length and uploaded.content_length > 50 * 1024 * 1024: return api_error("O backup excede 50 MB.")
    try:
        backup = json.load(uploaded.stream)
    except Exception: return api_error("Arquivo JSON inválido.")
    if not isinstance(backup, dict) or backup.get("format") != "rpg-habitos-backup-v1" or not isinstance(backup.get("tables"), dict):
        return api_error("Formato de backup não reconhecido.")
    # O backup JSON restaura as tabelas de domínio sem executar SQL arbitrário.
    table_models = {"user": User, "player": Player, "daily_evaluation": DailyEvaluation, "activity": Activity, "dungeon_attempt": DungeonAttempt, "idempotency_record": IdempotencyRecord}
    try:
        tables = backup["tables"]
        required = {"user", "player", "daily_evaluation", "activity", "dungeon_attempt"}
        if not required.issubset(tables): return api_error("O backup não contém todas as tabelas obrigatórias.")
        # A restauração precisa manter ao menos uma conta administrativa para evitar bloquear o painel.
        if not isinstance(tables.get("user"), list) or not any(isinstance(row, dict) and row.get("is_admin") and row.get("username") and row.get("password_hash") for row in tables["user"]):
            return api_error("O backup precisa conter uma conta administrativa válida para evitar bloqueio de acesso.")
        # Validar toda a estrutura antes de remover dados. Restaurar dados da conta atual é permitido.
        for name, rows in tables.items():
            if name in table_models and (not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows)):
                return api_error(f"Tabela inválida no backup: {name}.")
        # Lock the PostgreSQL domain tables before snapshotting so other accounts cannot
        # mutate them mid-backup/mid-restore. The entire operation remains one transaction.
        db.session.rollback()
        if db.engine.dialect.name == "postgresql":
            db.session.execute(text('LOCK TABLE "user", "player", "daily_evaluation", "activity", "dungeon_attempt", "idempotency_record", "admin_backup" IN ACCESS EXCLUSIVE MODE'))
        # Save a compressed pre-restore snapshot in the same database, outside the domain tables
        # being restored. This survives a successful restore and can be downloaded afterward.
        current_bytes=json.dumps(logical_backup_payload(),ensure_ascii=False,indent=2).encode("utf-8")
        if len(current_bytes) > 100 * 1024 * 1024:
            return api_error("O banco atual excede 100 MB descompactado; baixe um backup manual e reduza o volume antes de restaurar.")
        # Detach session-loaded users before replacing rows with the same primary keys.
        db.session.expunge_all()
        actor = str(session.get("user_id", "admin"))
        actor_user = db.session.get(User, int(actor)) if str(actor).isdigit() else None
        actor_name = actor_user.username if actor_user else "admin"
        db.session.expunge_all()  # Avoid identity-map collisions when restoring users with the same IDs.
        prebackup=AdminBackup(created_by_username=actor_name,
            filename=f"rpg-habitos-pre-restauracao-{today_key()}-{uuid.uuid4().hex[:8]}.json",
            content_gzip=gzip.compress(current_bytes, compresslevel=6),size_bytes=len(current_bytes))
        db.session.add(prebackup); db.session.flush()
        # Keep the newest ten automatic pre-restore backups.
        old_backups=AdminBackup.query.order_by(AdminBackup.created_at.desc(),AdminBackup.id.desc()).offset(10).all()
        for old_backup in old_backups: db.session.delete(old_backup)
        db.session.query(IdempotencyRecord).delete(synchronize_session=False)
        db.session.query(DailyEvaluation).delete(synchronize_session=False)
        db.session.query(Activity).delete(synchronize_session=False)
        db.session.query(DungeonAttempt).delete(synchronize_session=False)
        db.session.query(Player).delete(synchronize_session=False)
        db.session.query(User).delete(synchronize_session=False)
        for name in ("user", "player", "daily_evaluation", "activity", "dungeon_attempt", "idempotency_record"):
            if name not in tables: continue  # Compatibility with older logical backups.
            Model = table_models[name]
            for row in tables[name]:
                allowed = {column.name for column in Model.__table__.columns}
                values = {k: v for k, v in row.items() if k in allowed}
                for col in Model.__table__.columns:
                    if col.name in values and isinstance(col.type, db.DateTime) and isinstance(values[col.name], str):
                        values[col.name] = datetime.fromisoformat(values[col.name])
                if name == "user" and "password_hash" not in values: raise ValueError("Backup sem hashes de senha; restauração recusada.")
                db.session.add(Model(**values))
        db.session.flush()
        if db.engine.dialect.name == "postgresql":
            # Preserve explicit IDs from the logical backup and advance sequences in the same transaction.
            for model in (User, Player, DailyEvaluation, Activity, DungeonAttempt, IdempotencyRecord):
                table = model.__table__.name
                max_id = db.session.execute(text(f'SELECT MAX(id) FROM "{table}"')).scalar()
                sequence = db.session.execute(
                    text("SELECT pg_get_serial_sequence(:table_name, 'id')"),
                    {"table_name": f'"{table}"'},
                ).scalar()
                if sequence:
                    db.session.execute(
                        text("SELECT setval(CAST(:sequence AS regclass), :value, :called)"),
                        {"sequence": sequence, "value": int(max_id or 1), "called": max_id is not None},
                    )
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        return api_error(f"Falha ao restaurar o backup; alterações revertidas. Detalhe: {str(exc)[:180]}", 400)
    session.clear()
    return jsonify({"ok": True, "message": "Backup restaurado. Por segurança, entre novamente."})


@app.get("/api/admin/backup/export")
@require_auth
def admin_export_backup():
    if not current_user().is_admin: return api_error("Acesso administrativo necessário.", 403)
    content=json.dumps(logical_backup_payload(),ensure_ascii=False,indent=2).encode("utf-8")
    response=make_response(content); response.headers["Content-Type"]="application/json; charset=utf-8"
    response.headers["Content-Disposition"]=f'attachment; filename="rpg-habitos-backup-{today_key()}.json"'
    response.headers["Cache-Control"]="no-store, private"
    return response


@app.get("/api/admin/summary")
@require_auth
def admin_summary():
    if not current_user().is_admin: return api_error("Acesso administrativo necessário.", 403)
    return jsonify({"ok": True, "users": User.query.count(), "players": Player.query.count(),
                    "activities": Activity.query.count(), "evaluations": DailyEvaluation.query.count(),
                    "dungeon_attempts": DungeonAttempt.query.count(), "database": "PostgreSQL" if "postgresql" in app.config["SQLALCHEMY_DATABASE_URI"] else "SQLite"})


@app.post("/api/rewards/session")
@require_auth
def api_reward_session():
    data=request.get_json(silent=True) or {}; active=bool(data.get("active"))
    p=get_player(lock=True);tick_reward_timer(p)
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
    p=get_player(lock=True);tick_reward_timer(p);db.session.commit()
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


@app.errorhandler(413)
def upload_too_large(_):
    if request.path.startswith("/api/"):
        return api_error("O arquivo excede o limite de 50 MB.", 413)
    return "Arquivo excede o limite de 50 MB.", 413


@app.before_request
def idempotency_replay():
    key = request.headers.get("X-Operation-ID", "").strip()
    if request.method not in ("POST", "PUT", "PATCH", "DELETE") or not key or not session.get("user_id"):
        return None
    if len(key) > 80: return api_error("Identificador de operação inválido.")
    row = IdempotencyRecord.query.filter_by(user_id=int(session["user_id"]), operation_id=key).first()
    if row:
        return jsonify(row.response_json), int(row.status_code)
    return None


@app.after_request
def idempotency_store(response):
    key = request.headers.get("X-Operation-ID", "").strip()
    if request.method in ("POST", "PUT", "PATCH", "DELETE") and key and session.get("user_id") and response.status_code < 400 and request.path.startswith("/api/"):
        try:
            data = response.get_json(silent=True)
            if isinstance(data, dict):
                exists = IdempotencyRecord.query.filter_by(user_id=int(session["user_id"]), operation_id=key).first()
                if not exists:
                    db.session.add(IdempotencyRecord(user_id=int(session["user_id"]), operation_id=key, response_json=data, status_code=response.status_code))
                    db.session.commit()
        except Exception:
            db.session.rollback()
            app.logger.exception("Falha ao salvar chave idempotente")
    return response


def _merge_inventory(source_inventory, target_inventory):
    """Merge stackable items while preserving every key from both inventories."""
    src = clone_json(source_inventory, {}) or {}
    dst = clone_json(target_inventory, {}) or {}
    merged = dict(src)
    merged.update(dst)
    equipment = {}
    for data in (src.get("equipment") or {}, dst.get("equipment") or {}):
        if isinstance(data, dict):
            for key, value in data.items():
                try:
                    equipment[key] = int(equipment.get(key, 0)) + int(value or 0)
                except (TypeError, ValueError):
                    equipment.setdefault(key, value)
    merged["equipment"] = equipment
    for key in set(src) | set(dst):
        if key == "equipment":
            continue
        a, b = src.get(key), dst.get(key)
        if isinstance(a, (int, float)) and not isinstance(a, bool) and isinstance(b, (int, float)) and not isinstance(b, bool):
            merged[key] = a + b
        elif key not in dst:
            merged[key] = a
        else:
            merged[key] = b
    return merged


def _transfer_legacy_progress_to_account(source_user, target_user):
    """Move the old anonymous/admin profile to the chosen account once, without destroying records."""
    if not source_user or not target_user or source_user.id == target_user.id:
        return False
    if bool(getattr(target_user, "legacy_progress_imported", False)):
        return False

    source_player = Player.query.filter_by(user_id=source_user.id).first()
    target_player = Player.query.filter_by(user_id=target_user.id).first()
    daily_rows = DailyEvaluation.query.filter_by(user_id=source_user.id).all()
    activity_rows = Activity.query.filter_by(user_id=source_user.id).all()
    dungeon_rows = DungeonAttempt.query.filter_by(user_id=source_user.id).all()
    idempotency_rows = IdempotencyRecord.query.filter_by(user_id=source_user.id).all()
    if not (source_player or daily_rows or activity_rows or dungeon_rows or idempotency_rows):
        return False

    today = today_key()
    if source_player:
        src_xp = clone_json(source_player.xp_by_attribute, default_xp()) or default_xp()
        # The legacy game had no class bonus. Apply Monge's double RES bonus retroactively.
        try:
            src_xp["RES"] = int(src_xp.get("RES", 0) or 0) * 2
        except (TypeError, ValueError):
            src_xp["RES"] = 0
        source_player.xp_by_attribute = src_xp

        if target_player is None:
            source_player.user_id = target_user.id
            target_player = source_player
            # A daily balance expires at midnight; do not resurrect an old day's time.
            if source_player.daily_reward_date != today:
                source_player.daily_reward_date = today
                source_player.daily_reward_seconds = 0
            else:
                source_player.daily_reward_seconds = min(DAILY_REWARD_CAP, int(source_player.daily_reward_seconds or 0))
            source_player.reward_session_active = False
            source_player.reward_last_tick_at = None
        else:
            dst_xp = clone_json(target_player.xp_by_attribute, default_xp()) or default_xp()
            for code in set(src_xp) | set(dst_xp):
                try:
                    dst_xp[code] = int(dst_xp.get(code, 0) or 0) + int(src_xp.get(code, 0) or 0)
                except (TypeError, ValueError):
                    dst_xp[code] = int(dst_xp.get(code, 0) or 0)
            target_player.xp_by_attribute = dst_xp
            target_player.inventory = _merge_inventory(source_player.inventory, target_player.inventory)
            target_player.coins = int(target_player.coins or 0) + int(source_player.coins or 0)
            target_player.equipped = {**(source_player.equipped or {}), **(target_player.equipped or {})}
            target_player.current_hp = max(int(target_player.current_hp or 0), int(source_player.current_hp or 0))
            target_player.current_mp = max(int(target_player.current_mp or 0), int(source_player.current_mp or 0))
            if not target_player.dungeon_state:
                target_player.dungeon_state = clone_json(source_player.dungeon_state, None)
            target_player.last_dungeon_result = target_player.last_dungeon_result or source_player.last_dungeon_result
            target_player.permanent_special_seconds = int(target_player.permanent_special_seconds or 0) + int(source_player.permanent_special_seconds or 0)
            # Only merge daily time if both balances still belong to today.
            dst_daily = int(target_player.daily_reward_seconds or 0) if target_player.daily_reward_date == today else 0
            src_daily = int(source_player.daily_reward_seconds or 0) if source_player.daily_reward_date == today else 0
            target_player.daily_reward_date = today
            target_player.daily_reward_seconds = min(DAILY_REWARD_CAP, dst_daily + src_daily)
            target_player.reward_session_active = False
            target_player.reward_last_tick_at = None
            if not target_player.class_code:
                target_player.class_code = source_player.class_code
            if not target_player.task_mapping:
                target_player.task_mapping = clone_json(source_player.task_mapping, default_task_mapping())
            target_player.task_mapping_version = max(int(target_player.task_mapping_version or 0), int(source_player.task_mapping_version or 0))
            target_player.setup_complete = bool(target_player.setup_complete or source_player.setup_complete or target_player.class_code)
            target_player.relics_owned = list(dict.fromkeys((source_player.relics_owned or []) + (target_player.relics_owned or [])))
            if target_player.active_relic_id not in (target_player.relics_owned or []):
                target_player.active_relic_id = source_player.active_relic_id if source_player.active_relic_id in (target_player.relics_owned or []) else None
            target_player.manto_xp_remainder = (int(target_player.manto_xp_remainder or 0) + int(source_player.manto_xp_remainder or 0)) % 10
            # The story reward was retired; do not carry forward or expose its unlock counters.
            db.session.delete(source_player)

    # Move evaluations, doubling historical RES evaluation XP. If both accounts have the same
    # attribute/day, combine them into one row to respect the per-account uniqueness constraint.
    for row in daily_rows:
        factor = 2 if row.attribute == "RES" else 1
        row.xp = int(row.xp or 0) * factor
        existing = DailyEvaluation.query.filter_by(user_id=target_user.id, attribute=row.attribute, day=row.day).first()
        if existing and existing.id != row.id:
            existing.xp = int(existing.xp or 0) + int(row.xp or 0)
            existing.score = max(int(existing.score or 0), int(row.score or 0))
            db.session.delete(row)
        else:
            row.user_id = target_user.id

    # Preserve activity records even if client-side idempotency refs happen to collide.
    target_refs = {r.client_ref for r in Activity.query.filter_by(user_id=target_user.id).all() if r.client_ref}
    for row in activity_rows:
        if row.client_ref and row.client_ref in target_refs:
            row.client_ref = None
        row.user_id = target_user.id
        if row.client_ref:
            target_refs.add(row.client_ref)
    for row in dungeon_rows:
        row.user_id = target_user.id
    target_operation_ids = {r.operation_id for r in IdempotencyRecord.query.filter_by(user_id=target_user.id).all()}
    for row in idempotency_rows:
        if row.operation_id in target_operation_ids:
            db.session.delete(row)
        else:
            row.user_id = target_user.id
            target_operation_ids.add(row.operation_id)

    target_user.legacy_progress_imported = True
    db.session.flush()
    app.logger.info("Legacy progress migrated from user %s to %s; historical RES XP doubled once.", source_user.username, target_user.username)
    return True


def migrate_schema():
    """Additive migration for legacy single-player databases; existing progress is kept."""
    db.create_all()
    inspector = inspect(db.engine)
    existing_tables = set(inspector.get_table_names())
    # Use the actual SQLAlchemy table names (singular snake_case), not guessed plural names.
    additions = {
        # db.create_all() does not add columns to an already-existing table.
        # Upgrade legacy accounts before querying User during admin bootstrap.
        User.__table__.name: {
            "email": "VARCHAR(255)",
            "is_admin": "BOOLEAN NOT NULL DEFAULT FALSE",
            "legacy_progress_imported": "BOOLEAN NOT NULL DEFAULT FALSE",
        },
        Player.__table__.name: {"user_id": "INTEGER", "class_code": "VARCHAR(24)", "task_mapping": "JSON", "task_mapping_version": "INTEGER DEFAULT 0", "setup_complete": "BOOLEAN DEFAULT FALSE", "relics_owned": "JSON", "active_relic_id": "VARCHAR(24)", "manto_xp_remainder": "INTEGER DEFAULT 0"},
        DailyEvaluation.__table__.name: {"user_id": "INTEGER"},
        Activity.__table__.name: {"user_id": "INTEGER", "client_ref": "VARCHAR(80)"},
        DungeonAttempt.__table__.name: {"user_id": "INTEGER"},
    }
    for table, columns in additions.items():
        if table not in existing_tables: continue
        present = {c["name"] for c in inspect(db.engine).get_columns(table)}
        for col, declaration in columns.items():
            if col not in present:
                with db.engine.begin() as conn:
                    conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{col}" {declaration}'))
    # Remove legacy global daily uniqueness so different accounts can evaluate the same attribute/day.
    # A previous build may have imposed UNIQUE(attribute, day); each account now needs its own key.
    daily_table = DailyEvaluation.__table__.name
    try:
        if daily_table in existing_tables and db.engine.dialect.name == "postgresql":
            constraints = inspect(db.engine).get_unique_constraints(daily_table)
            for c in constraints:
                if c.get("name") == "uq_daily_attribute_day" or set(c.get("column_names") or []) == {"attribute", "day"}:
                    constraint_name = c.get("name")
                    if constraint_name:
                        with db.engine.begin() as conn:
                            conn.execute(text(f'ALTER TABLE "{daily_table}" DROP CONSTRAINT "{constraint_name}"'))
        elif daily_table in existing_tables and db.engine.dialect.name == "sqlite":
            indexes = inspect(db.engine).get_indexes(daily_table)
            uniques = inspect(db.engine).get_unique_constraints(daily_table)
            has_old = any(x.get("name") == "uq_daily_attribute_day" and x.get("unique") for x in indexes) or any(x.get("name") == "uq_daily_attribute_day" for x in uniques) or any(set(x.get("column_names") or []) == {"attribute", "day"} for x in uniques)
            if has_old:
                # Rebuild with a temporary table, preserving every existing row and primary key.
                with db.engine.begin() as conn:
                    conn.execute(text(f'CREATE TABLE "{daily_table}_new" (id INTEGER PRIMARY KEY, user_id INTEGER, attribute VARCHAR(8) NOT NULL, day VARCHAR(10) NOT NULL, score INTEGER NOT NULL, xp INTEGER NOT NULL, created_at DATETIME NOT NULL)'))
                    conn.execute(text(f'INSERT INTO "{daily_table}_new" (id,user_id,attribute,day,score,xp,created_at) SELECT id,user_id,attribute,day,score,xp,created_at FROM "{daily_table}"'))
                    conn.execute(text(f'DROP TABLE "{daily_table}"'))
                    conn.execute(text(f'ALTER TABLE "{daily_table}_new" RENAME TO "{daily_table}"'))
    except Exception:
        # Migration will be re-attempted; existing player data remains intact on failed DDL.
        app.logger.exception("Falha ao ajustar a constraint antiga de avaliações")

    # Add account-scoped indexes on upgraded databases too; NULL user IDs remain allowed for legacy rows.
    try:
        with db.engine.begin() as conn:
            conn.execute(text(f'CREATE UNIQUE INDEX IF NOT EXISTS uq_user_daily_attribute_day ON "{daily_table}"(user_id, attribute, day)'))
            player_table = Player.__table__.name
            activity_table = Activity.__table__.name
            conn.execute(text(f'CREATE UNIQUE INDEX IF NOT EXISTS uq_player_user_id ON "{player_table}"(user_id)'))
            conn.execute(text(f'CREATE UNIQUE INDEX IF NOT EXISTS uq_user_activity_client_ref ON "{activity_table}"(user_id, client_ref)'))
    except Exception:
        app.logger.exception("Não foi possível criar os índices por conta")

    admin_name = os.getenv("ADMIN_USERNAME", "admin").strip().lower() or "admin"
    admin_password = os.getenv("ADMIN_PASSWORD") or os.getenv("SITE_PASSWORD", "12345678")
    admin = User.query.filter_by(username=admin_name).first()
    if admin is None:
        admin = User(
            username=admin_name,
            email=os.getenv("ADMIN_EMAIL", f"{admin_name}@users.rpg-habitos.invalid").strip().lower(),
            password_hash=generate_password_hash(admin_password),
            is_admin=True,
        )
        db.session.add(admin); db.session.flush()
    else:
        admin.is_admin = True
        # Do not reset a password hash at every startup; ADMIN_PASSWORD is only a bootstrap default.

    # Adopt rows from the previous single-player version for the bootstrap administrator.
    players = Player.query.order_by(Player.id.asc()).all()
    old_player = next((row for row in players if row.user_id is None), None)
    if old_player:
        old_player.user_id = admin.id
        if not old_player.task_mapping: old_player.task_mapping = default_task_mapping()
        if old_player.relics_owned is None: old_player.relics_owned = []
        # Existing player has to complete class selection once in the new build.
        old_player.setup_complete = bool(old_player.class_code)
        for model in (DailyEvaluation, Activity, DungeonAttempt):
            for row in model.query.filter_by(user_id=None).all(): row.user_id = admin.id
    # Any migrated empty/new admin profile is prepared but does not inherit another user's data.
    for row in Player.query.filter_by(user_id=admin.id).all():
        if not row.task_mapping: row.task_mapping = default_task_mapping()
        if row.task_mapping_version is None: row.task_mapping_version = 0
        if row.relics_owned is None: row.relics_owned = []
        if row.active_relic_id and row.active_relic_id not in (row.relics_owned or []): row.active_relic_id = None
        if row.active_relic_id is None and row.relics_owned: row.active_relic_id = row.relics_owned[0]
        if row.manto_xp_remainder is None: row.manto_xp_remainder = 0

    # The user used to play without an account; the old build attached that profile to the
    # bootstrap admin. Import it into the explicitly requested account, exactly once.
    target_name = os.getenv("LEGACY_PROGRESS_TARGET_USERNAME", "shiksz").strip().lower() or "shiksz"
    target_user = User.query.filter_by(username=target_name).first()
    if target_user and target_user.id != admin.id:
        _transfer_legacy_progress_to_account(admin, target_user)

    db.session.commit()


with app.app_context():
    migrate_schema()

if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG") == "1", host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
