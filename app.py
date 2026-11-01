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
import base64
import secrets
import uuid
import mimetypes
from urllib.parse import urlparse
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from zoneinfo import ZoneInfo

from flask import Flask, jsonify, render_template, request, session, redirect, url_for, send_file, make_response
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import UniqueConstraint, func, inspect, text, or_

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
    return {"pocao_cura": 2, "pocao_mana": 2, "equipment": {}, "bracelete_salvacao": 0, "ticket_dungeon": 0, "pena_fenix": 0}


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
    character_config_version = db.Column(db.Integer, nullable=False, default=0)
    reward_site_name = db.Column(db.String(80), nullable=True)
    reward_site_url = db.Column(db.String(600), nullable=True)
    reward_site2_name = db.Column(db.String(80), nullable=True)
    reward_site2_url = db.Column(db.String(600), nullable=True)
    library_day = db.Column(db.String(10), nullable=False, default=today_key)
    library_seconds_today = db.Column(db.Integer, nullable=False, default=0)
    library_last_tick_at = db.Column(db.DateTime, nullable=True)
    library_session_active = db.Column(db.Boolean, nullable=False, default=False)
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


class LibraryDocument(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    filename = db.Column(db.String(180), nullable=False)
    extension = db.Column(db.String(12), nullable=False)
    mimetype = db.Column(db.String(120), nullable=False)
    size_bytes = db.Column(db.Integer, nullable=False)
    content = db.Column(db.LargeBinary, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=local_now)


class DungeonAttempt(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True, index=True)
    started_at = db.Column(db.DateTime, nullable=False, default=local_now)
    outcome = db.Column(db.String(24), nullable=False, default="em_andamento")
    floors = db.Column(db.Integer, nullable=False, default=0)
    ended_at = db.Column(db.DateTime, nullable=True)


class CoopExpedition(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    host_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    guest_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    status = db.Column(db.String(16), nullable=False, default="pending", index=True)
    state = db.Column(db.JSON, nullable=False, default=dict)
    created_at = db.Column(db.DateTime, nullable=False, default=local_now)
    updated_at = db.Column(db.DateTime, nullable=False, default=local_now)


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


def tick_library_session(p: Player, active: bool) -> int:
    """Conta tempo somente durante uma sessão ativa; ticks atrasados não rendem tempo."""
    day = today_key()
    if p.library_day != day:
        p.library_day = day
        p.library_seconds_today = 0
        p.library_session_active = False
        p.library_last_tick_at = None
    now = local_now()
    before = int(p.library_seconds_today or 0)
    if p.library_session_active and p.library_last_tick_at:
        elapsed = max(0, int((now - p.library_last_tick_at).total_seconds()))
        # Um heartbeat atrasado (aba fechada/suspensa) não pode gerar horas retroativas.
        if elapsed <= 90:
            p.library_seconds_today = min(3600, before + elapsed)
    after = int(p.library_seconds_today or 0)
    gained = max(0, after // 60 - before // 60)
    if gained:
        p.coins = int(p.coins or 0) + gained
    p.library_session_active = bool(active)
    p.library_last_tick_at = now if active else None
    return gained


def library_payload(p: Player) -> list[dict]:
    rows = LibraryDocument.query.filter_by(user_id=p.user_id).order_by(LibraryDocument.created_at.desc(), LibraryDocument.id.desc()).all()
    return [{"id": r.id, "filename": r.filename, "extension": r.extension,
             "size_bytes": int(r.size_bytes), "created_at": r.created_at.isoformat(timespec="minutes")}
            for r in rows]


def rank_average_for_player(p: Player) -> str:
    ranks = rank_summary(p.xp_by_attribute or default_xp())
    average = sum(int(ranks[a["code"]]["rank_index"]) for a in ATTRIBUTES) / len(ATTRIBUTES)
    return RANKS[min(len(RANKS) - 1, int(average + 0.5))]


def current_resources(p: Player) -> tuple[int, int, dict]:
    run = p.dungeon_state or {}
    combat = run.get("combat") or {}
    hp = int(combat.get("player_hp", p.current_hp))
    mp = int(combat.get("player_mp", p.current_mp))
    stats = compute_player_stats(p.xp_by_attribute or default_xp(), p.equipped or {}, hp, mp, None, p.class_code)
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
    return {"equipment": equipment, "consumables": consumables, "equipped": equipped, "bracelete_salvacao": int(inv.get("bracelete_salvacao", 0)), "ticket_dungeon": int(inv.get("ticket_dungeon", 0)), "relics": [RELIC_CATALOG[r] for r in (p.relics_owned or []) if r in RELIC_CATALOG], "pingente_deusa_amor": int(inv.get("pingente_deusa_amor", 0)), "pena_fenix": int(inv.get("pena_fenix", 0))}


def _coop_record_for_user(user_id: int):
    return (CoopExpedition.query
            .filter(CoopExpedition.status.in_(["pending", "active"]))
            .filter(or_(CoopExpedition.host_user_id == user_id, CoopExpedition.guest_user_id == user_id))
            .order_by(CoopExpedition.created_at.desc(), CoopExpedition.id.desc()).first())


def _coop_member_state(expedition, user_id: int):
    return (expedition.state or {}).get("members", {}).get(str(user_id), {})


def _coop_payload_for_user(user_id: int) -> dict | None:
    expedition = _coop_record_for_user(user_id)
    if not expedition:
        return None
    role = "host" if expedition.host_user_id == user_id else "guest"
    partner_id = expedition.guest_user_id if role == "host" else expedition.host_user_id
    partner = db.session.get(User, partner_id)
    if expedition.status == "pending":
        if expedition.created_at < local_now() - timedelta(days=1):
            expedition.status = "declined"; expedition.updated_at = local_now(); db.session.commit()
            return None
        return {"status": "pending", "id": expedition.id, "role": role,
                "partner_username": partner.username if partner else "Jogador",
                "created_at": expedition.created_at.isoformat(timespec="minutes")}
    state = clone_json(expedition.state, {})
    run = state.get("run") or {}
    mine = _coop_member_state(expedition, user_id)
    partner_state = _coop_member_state(expedition, partner_id)
    members = []
    for uid in (expedition.host_user_id, expedition.guest_user_id):
        member = state.get("members", {}).get(str(uid), {})
        player = Player.query.filter_by(user_id=uid).first()
        user = db.session.get(User, uid)
        hp = int(member.get("hp", player.current_hp if player else 0))
        mp = int(member.get("mp", player.current_mp if player else 0))
        hpmax = 10
        mpmax = 10
        if player:
            st = compute_player_stats(player.xp_by_attribute or default_xp(), player.equipped or {}, hp, mp, class_code=player.class_code)
            hpmax, mpmax = st["hp_max"], st["mp_max"]
        members.append({"user_id": uid, "username": user.username if user else "Jogador",
                        "alive": bool(member.get("alive", True)), "hp": hp, "mp": mp,
                        "hp_max": hpmax, "mp_max": mpmax, "loot_count": len(member.get("loot", [])),
                        "is_me": uid == user_id})
    combat = run.get("combat") or None
    can_act = bool(combat and int(combat.get("next_actor_id") or 0) == user_id and mine.get("alive", True))
    details = {"status": "active", "id": expedition.id, "role": role,
               "partner_username": partner.username if partner else "Jogador",
               "floor": int(run.get("floor", 1)), "floors": int(run.get("floors", 1)),
               "x": int(run.get("x", 0)), "y": int(run.get("y", 0)),
               "map": visible_map(run), "last_message": run.get("last_message", ""),
               "loot_count": len(mine.get("loot", [])),
               "members": members, "current_actor_id": (combat or {}).get("next_actor_id"),
               "can_act": can_act, "my_alive": bool(mine.get("alive", True)),
               "abandon_requested_by": state.get("abandon_requested_by"),
               "abandon_requested_by_me": state.get("abandon_requested_by") == user_id,
               "my_potions": clone_json(mine.get("run_potions"), {}),
               "my_inventory": inventory_payload(Player.query.filter_by(user_id=user_id).first())}
    if combat:
        e = combat["enemy"]
        details["combat"] = {"enemy": {"id": e["id"], "name": e["name"], "icon": e["icon"],
            "tier": e["tier"], "rank": e["rank"], "hp": e["hp"], "hp_max": e["hp_max"],
            "mp": e["mp"], "mp_max": e["mp_max"], "stats": e["stats"]},
            "log": (combat.get("log") or [])[-12:], "round": int(combat.get("round", 0))}
        if can_act:
            player = Player.query.filter_by(user_id=user_id).first()
            xp = clone_json(player.xp_by_attribute, default_xp())
            skill_rows = effective_skills(xp, player.equipped or {}, class_code=player.class_code)
            actor = clone_json(mine.get("actor"), {})
            actor_mp = int(mine.get("mp", player.current_mp))
            has_efficiency = any(x.get("action") == "mp_efficiency" for x in skill_rows.values())
            skills=[]
            for sid, sk in skill_rows.items():
                if sk.get("kind") != "active":
                    continue
                base_cost=int(sk.get("mp_cost", 0)); cost=base_cost
                if base_cost and has_efficiency:
                    credit=float(actor.get("player_mp_savings_credit", 0.0))+base_cost*0.03
                    cost=max(1, base_cost-int(credit+1e-9))
                cd=int(actor.get("cooldowns", {}).get(sid, 0))
                skills.append({**sk, "current_cost": cost, "cooldown_left": cd,
                               "usable_now": cd == 0 and actor_mp >= cost})
            details["combat"]["skills"] = skills
            details["combat"]["available_items"] = [{**CONSUMABLES[k],
                "quantity": int((player.inventory or {}).get(k, 0)),
                "dungeon_quantity": int(mine.get("run_potions", {}).get(k, 0))} for k in CONSUMABLES]
        else:
            details["combat"]["skills"] = []
            details["combat"]["available_items"] = []
    else:
        details["combat"] = None
    return details


def _coop_active_player_pair(expedition, lock: bool = True):
    ids = sorted([int(expedition.host_user_id), int(expedition.guest_user_id)])
    query = Player.query.filter(Player.user_id.in_(ids)).order_by(Player.user_id.asc())
    if lock:
        query = query.with_for_update()
    players = {row.user_id: row for row in query.all()}
    if len(players) != 2:
        raise ValueError("Um dos personagens desta dupla não está disponível.")
    return players


def _coop_finish(expedition, players: dict, outcome: str, message: str):
    state = clone_json(expedition.state, {})
    run = state.get("run", {})
    members = state.get("members", {})
    now = local_now()
    for uid in (expedition.host_user_id, expedition.guest_user_id):
        player = players[uid]
        member = members.get(str(uid), {})
        inv = clone_json(player.inventory, default_inventory())
        if outcome == "victory":
            equipment = inv.setdefault("equipment", {})
            for item_id in member.get("loot", []):
                equipment[item_id] = int(equipment.get(item_id, 0)) + 1
            for pot, qty in member.get("run_potions", {}).items():
                inv[pot] = int(inv.get(pot, 0)) + int(qty)
            player.inventory = inv
            if member.get("alive", False):
                player.permanent_special_seconds = int(player.permanent_special_seconds or 0) + 40 * 60
            player.last_dungeon_result = (message + (" Você recebeu +40 minutos especiais." if member.get("alive", False) else " Seus itens foram preservados, mas você não recebeu o tempo especial porque terminou derrotado."))
        else:
            player.last_dungeon_result = message + " Itens temporários perdidos; moedas preservadas."
            player.current_hp = 10
            player.current_mp = 10
        attempt = DungeonAttempt.query.filter_by(user_id=uid, outcome="em_andamento").order_by(DungeonAttempt.id.desc()).first()
        if attempt:
            attempt.outcome = outcome if outcome in ("victory", "derrota") else "abandonada"
            attempt.ended_at = now
        player.dungeon_state = None
    state["outcome"] = outcome
    state["finished_message"] = message
    expedition.state = state
    expedition.status = "completed"
    expedition.updated_at = now


def _coop_actor_to_local(member: dict, combat: dict) -> dict:
    actor = clone_json(member.get("actor"), {})
    local = clone_json(combat, {})
    local["cooldowns"] = clone_json(actor.get("cooldowns"), {})
    local["buffs"] = clone_json(actor.get("buffs"), [])
    local["player_hp"] = int(member.get("hp", 10))
    local["player_mp"] = int(member.get("mp", 10))
    local["player_guard_reduction"] = int(actor.get("guard_reduction", 0))
    local["player_defensive_agi_once"] = actor.get("defensive_agi_once")
    local["player_evasion_pp"] = int(actor.get("evasion_pp", 0))
    local["last_chance_used"] = bool(actor.get("last_chance_used", False))
    local["rebirth_used"] = bool(actor.get("rebirth_used", False))
    local["pending"] = clone_json(actor.get("pending"), [])
    local["next_attack"] = clone_json(actor.get("next_attack"), {"bonus": 0, "ignore": 0})
    local["weakness_revealed"] = bool(actor.get("weakness_revealed", False))
    local["player_mp_savings_credit"] = float(actor.get("player_mp_savings_credit", 0.0))
    # Turnos, buffs e recargas do jogador são individuais: o parceiro não os avança.
    local["player_turn"] = int(actor.get("turn", 0))
    return local


def _coop_actor_from_local(member: dict, local: dict):
    member["hp"] = int(local.get("player_hp", member.get("hp", 10)))
    member["mp"] = int(local.get("player_mp", member.get("mp", 10)))
    member["actor"] = {"cooldowns": clone_json(local.get("cooldowns"), {}),
        "buffs": clone_json(local.get("buffs"), []),
        "guard_reduction": int(local.get("player_guard_reduction", 0)),
        "defensive_agi_once": local.get("player_defensive_agi_once"),
        "evasion_pp": int(local.get("player_evasion_pp", 0)),
        "last_chance_used": bool(local.get("last_chance_used", False)),
        "rebirth_used": bool(local.get("rebirth_used", False)),
        "pending": clone_json(local.get("pending"), []),
        "next_attack": clone_json(local.get("next_attack"), {"bonus": 0, "ignore": 0}),
        "weakness_revealed": bool(local.get("weakness_revealed", False)),
        "player_mp_savings_credit": float(local.get("player_mp_savings_credit", 0.0)),
        "turn": int(local.get("player_turn", 0))}


def _coop_next_actor(state: dict, after_user_id: int | None = None):
    ids = [int(state["host_user_id"]), int(state["guest_user_id"])]
    members = state["members"]
    if after_user_id in ids:
        start = (ids.index(int(after_user_id)) + 1) % 2
        order = ids[start:] + ids[:start]
    else:
        order = ids
    for uid in order:
        if members.get(str(uid), {}).get("alive", False):
            return uid
    return None


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
    skill_rows = describe_player_skills(p.xp_by_attribute or default_xp(), p.equipped or {}, p.class_code)
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
            player_skill_rows = effective_skills(p.xp_by_attribute or default_xp(), p.equipped or {}, class_code=p.class_code)
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
                   "reward_site_name": p.reward_site_name or "", "reward_site_url": p.reward_site_url or "",
                   "reward_site2_name": p.reward_site2_name or "", "reward_site2_url": p.reward_site2_url or "",
                   "library_seconds_today": int(p.library_seconds_today or 0),
                   "library_coins_today": min(60, int(p.library_seconds_today or 0) // 60),
                   "library_documents": library_payload(p),
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
        "coop": _coop_payload_for_user(current_user().id),
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
    stats = compute_player_stats(p.xp_by_attribute, p.equipped, p.current_hp, p.current_mp, class_code=p.class_code)
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
            if p and p.setup_complete and int(p.character_config_version or 0) >= 1:
                return render_template("index.html")
            return render_template("setup.html", classes=CLASS_DEFINITIONS,
                                   existing_class=CLASS_DEFINITIONS.get(p.class_code or "") if p else None,
                                   existing_class_code=(p.class_code or "") if p else "",
                                   existing_mapping=(p.task_mapping or default_task_mapping()) if p else default_task_mapping(),
                                   existing_name=(p.reward_site_name or "") if p else "",
                                   existing_url=(p.reward_site_url or "") if p else "",
                                   existing_name2=(p.reward_site2_name or "") if p else "",
                                   existing_url2=(p.reward_site2_url or "") if p else "")
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
                    task_mapping=default_task_mapping(), relics_owned=[], setup_complete=False,
                    character_config_version=0)
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
    p = get_player(lock=True)
    if int(p.character_config_version or 0) >= 1:
        return api_error("A configuração inicial já foi concluída e não pode ser alterada.")

    class_code = str(data.get("class_code", p.class_code or ""))
    if p.setup_complete and p.class_code:
        class_code = p.class_code  # classe de personagens antigos também fica bloqueada
    if class_code not in CLASS_DEFINITIONS:
        return api_error("Escolha uma classe válida.")

    mapping = data.get("task_mapping")
    if not isinstance(mapping, dict):
        return api_error("Defina as oito tarefas do personagem.")
    cleaned = {}
    for code in ATTR_BY_CODE:
        task = str(mapping.get(code, "")).strip()
        if not task or len(task) > 80:
            return api_error("Cada tarefa deve ter entre 1 e 80 caracteres.")
        cleaned[code] = task
    if len({v.casefold() for v in cleaned.values()}) != len(cleaned):
        return api_error("Cada tarefa deve ser diferente e estar associada a um único atributo.")

    def validate_reward_site(name_key, url_key, label):
        site_name = str(data.get(name_key, "")).strip()
        site_url = str(data.get(url_key, "")).strip()
        if not site_name or len(site_name) > 80:
            raise ValueError(f"Informe o nome do {label} (até 80 caracteres).")
        if not site_url:
            raise ValueError(f"Informe o endereço do {label}.")
        if not site_url.startswith(("https://", "http://")):
            site_url = "https://" + site_url
        parsed = urlparse(site_url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError(f"Endereço inválido para {label}. Use http:// ou https://.")
        if len(site_url) > 600:
            raise ValueError(f"O endereço do {label} é muito longo.")
        return site_name, site_url
    try:
        site_name, site_url = validate_reward_site("reward_site_name", "reward_site_url", "primeiro site de recompensa")
        site2_name, site2_url = validate_reward_site("reward_site2_name", "reward_site2_url", "segundo site de recompensa")
    except ValueError as exc:
        return api_error(str(exc))

    p.class_code = class_code
    p.task_mapping = cleaned
    p.task_mapping_version = int(p.task_mapping_version or 0) + 1
    p.reward_site_name = site_name
    p.reward_site_url = site_url
    p.reward_site2_name = site2_name
    p.reward_site2_url = site2_url
    p.setup_complete = True
    p.character_config_version = 1
    db.session.commit()
    return jsonify({"ok": True, "message": "Configuração inicial concluída. Classe, tarefas e site de recompensa foram registrados.", "redirect": "/"})


@app.post("/api/tasks")
@require_auth
def update_tasks():
    return api_error("As tarefas são definidas na criação do personagem e não podem ser alteradas depois.", 403)


@app.get("/api/scoreboard")
@require_auth
def api_scoreboard():
    rows = Player.query.filter(Player.setup_complete.is_(True), Player.character_config_version >= 1).all()
    entries = []
    for player in rows:
        user = db.session.get(User, player.user_id) if player.user_id else None
        if not user:
            continue
        entries.append({"username": user.username, "average_rank": rank_average_for_player(player),
                        "class_name": CLASS_DEFINITIONS.get(player.class_code or "", {}).get("name", "—")})
    entries.sort(key=lambda row: (RANKS.index(row["average_rank"]), row["username"].casefold()), reverse=True)
    return jsonify({"ok": True, "scoreboard": entries})


@app.post("/api/coop/invite")
@require_auth
def api_coop_invite():
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip().lower()
    if not username or username == current_user().username.lower():
        return api_error("Informe o nome de outro jogador.")
    host = get_player(lock=True)
    if not host.setup_complete:
        return api_error("Conclua a criação do personagem antes de convidar alguém.")
    if host.dungeon_state:
        return api_error("Encerre sua dungeon individual antes de convidar alguém.")
    target_user = User.query.filter(func.lower(User.username) == username).first()
    if not target_user:
        return api_error("Jogador não encontrado.")
    if not Player.query.filter_by(user_id=target_user.id, setup_complete=True).first():
        return api_error("Esse jogador ainda não concluiu a criação do personagem.")
    if _coop_record_for_user(current_user().id) or _coop_record_for_user(target_user.id):
        return api_error("Você ou esse jogador já possui um convite ou expedição cooperativa ativa.")
    target_player = Player.query.filter_by(user_id=target_user.id).first()
    if target_player.dungeon_state:
        return api_error("Esse jogador está em uma dungeon individual.")
    invite = CoopExpedition(host_user_id=current_user().id, guest_user_id=target_user.id,
                            status="pending", state={})
    db.session.add(invite); db.session.commit()
    return jsonify({"ok": True, "message": f"Convite enviado para {target_user.username}.", "state": build_state(host)})


@app.post("/api/coop/respond")
@require_auth
def api_coop_respond():
    data = request.get_json(silent=True) or {}
    try: invite_id = int(data.get("invite_id"))
    except (TypeError, ValueError): return api_error("Convite inválido.")
    invite = CoopExpedition.query.filter_by(id=invite_id, guest_user_id=current_user().id, status="pending").with_for_update().first()
    if not invite: return api_error("Esse convite não está mais disponível.")
    if invite.created_at < local_now() - timedelta(days=1):
        invite.status = "declined"; db.session.commit()
        return api_error("O convite expirou.")
    accept = bool(data.get("accept"))
    if not accept:
        invite.status = "declined"; invite.updated_at = local_now(); db.session.commit()
        return jsonify({"ok": True, "message": "Convite recusado.", "state": build_state(get_player())})
    try:
        players = _coop_active_player_pair(invite, lock=True)
        host = players[invite.host_user_id]; guest = players[invite.guest_user_id]
        for player in (host, guest):
            if not player.setup_complete: raise ValueError("Os dois jogadores precisam concluir a criação do personagem.")
            if player.dungeon_state: raise ValueError("Os dois jogadores precisam estar fora de dungeons individuais.")
            inv = clone_json(player.inventory, default_inventory())
            if int(inv.get("ticket_dungeon", 0)) < 2:
                who = User.query.get(player.user_id)
                raise ValueError(f"{who.username if who else 'Um jogador'} precisa ter 2 Tickets de Dungeon.")
        if _coop_record_for_user(invite.host_user_id) or _coop_record_for_user(invite.guest_user_id):
            # This invitation itself is the only active/pending record allowed.
            for uid in (invite.host_user_id, invite.guest_user_id):
                rec = _coop_record_for_user(uid)
                if rec and rec.id != invite.id: raise ValueError("Um dos jogadores já entrou em outra expedição.")
        for player in (host, guest):
            inv = clone_json(player.inventory, default_inventory())
            inv["ticket_dungeon"] = int(inv.get("ticket_dungeon", 0)) - 2
            player.inventory = inv
        attempts=[]
        for uid in (invite.host_user_id, invite.guest_user_id):
            attempts.append(DungeonAttempt(user_id=uid, started_at=local_now(), outcome="em_andamento"))
        xp = clone_json(host.xp_by_attribute, default_xp())
        run = create_dungeon(xp, random.Random())
        for attempt in attempts: attempt.floors = run["floors"]; db.session.add(attempt)
        member_data = {}
        for player in (host, guest):
            hp, mp, stats = current_resources(player)
            member_data[str(player.user_id)] = {"alive": True, "hp": hp, "mp": mp,
                "loot": [], "run_potions": {}, "coins_found": 0,
                "actor": {"cooldowns": {}, "buffs": [], "guard_reduction": 0,
                    "defensive_agi_once": None, "evasion_pp": 0, "last_chance_used": False,
                    "rebirth_used": False, "pending": [], "next_attack": {"bonus": 0, "ignore": 0},
                    "weakness_revealed": False, "player_mp_savings_credit": 0.0, "turn": 0}}
            player.last_dungeon_result = None
        invite.state = {"host_user_id": invite.host_user_id, "guest_user_id": invite.guest_user_id,
            "run": run, "members": member_data, "last_message": "A dupla entrou na dungeon!",
            "started_at": local_now().isoformat()}
        invite.status = "active"; invite.updated_at = local_now()
        db.session.commit()
        player = get_player()
        return jsonify({"ok": True, "message": f"Dungeon cooperativa iniciada! Foram consumidos 2 tickets de cada jogador. {run['floors']} andares.", "state": build_state(player)})
    except ValueError as exc:
        db.session.rollback(); return api_error(str(exc))
    except Exception:
        db.session.rollback(); app.logger.exception("Falha ao aceitar convite cooperativo")
        return api_error("Não foi possível iniciar a expedição cooperativa agora.", 500)


@app.post("/api/coop/move")
@require_auth
def api_coop_move():
    expedition = _coop_record_for_user(current_user().id)
    if not expedition or expedition.status != "active": return api_error("Você não está em uma expedição cooperativa ativa.")
    expedition = CoopExpedition.query.filter_by(id=expedition.id).with_for_update().first()
    if not expedition or expedition.status != "active":
        return api_error("A expedição cooperativa já foi encerrada.")
    try:
        players = _coop_active_player_pair(expedition, lock=True)
        state = clone_json(expedition.state, {}); run = state.get("run") or {}
        if not state.get("members", {}).get(str(current_user().id), {}).get("alive", False): return api_error("Seu personagem está derrotado e não pode mover a dupla.")
        if run.get("combat"): return api_error("Termine o combate antes de se mover.")
        data = request.get_json(silent=True) or {}
        try: dx=int(data.get("dx")); dy=int(data.get("dy"))
        except (TypeError, ValueError): return api_error("Movimento inválido.")
        host = players[expedition.host_user_id]
        potions_before=clone_json(run.get("run_potions"), {})
        try: run, events, status = move_in_dungeon(run, dx, dy, clone_json(host.xp_by_attribute, default_xp()), compute_player_stats(host.xp_by_attribute, host.equipped, host.current_hp, host.current_mp, class_code=host.class_code), random.Random())
        except ValueError as exc: return api_error(str(exc))
        uid=current_user().id; member=state["members"][str(uid)]
        for pot, qty in run.get("run_potions", {}).items():
            found=max(0,int(qty)-int(potions_before.get(pot,0)))
            if found: member.setdefault("run_potions", {})[pot]=int(member.setdefault("run_potions", {}).get(pot,0))+found
        run["run_potions"]={}
        if int(run.get("coins_found",0)) > int(state.get("last_coins_found_total",0)):
            gain=int(run.get("coins_found",0))-int(state.get("last_coins_found_total",0))
            players[uid].coins=int(players[uid].coins)+gain
            member["coins_found"]=int(member.get("coins_found",0))+gain
            state["last_coins_found_total"]=int(run.get("coins_found",0))
        if status == "combat":
            combat=run["combat"]
            combat["log"]=[f"{combat['enemy']['icon']} {combat['enemy']['name']} bloqueia o caminho!"]
            # Iniciativa da dupla: o jogador mais ágil começa; empates são aleatórios.
            stats_by_uid={}
            for uid in (expedition.host_user_id, expedition.guest_user_id):
                pl=players[uid]
                stats_by_uid[uid]=compute_player_stats(pl.xp_by_attribute, pl.equipped, pl.current_hp, pl.current_mp, class_code=pl.class_code)["stats"].get("AGI",1)
            ordered=sorted(stats_by_uid, key=lambda k: stats_by_uid[k], reverse=True)
            if stats_by_uid[ordered[0]] == stats_by_uid[ordered[1]]: random.shuffle(ordered)
            current=next((x for x in ordered if state["members"][str(x)]["alive"]), None)
            combat["next_actor_id"]=current
            combat["log"].append(f"A dupla enfrenta {combat['enemy']['name']}. A iniciativa começa com {User.query.get(current).username}.")
        run["last_message"]=" ".join(events) if events else run.get("last_message", "")
        state["run"]=run; state["last_message"]=run["last_message"]
        expedition.state=state; expedition.updated_at=local_now(); db.session.commit()
        return jsonify({"ok":True,"message":" ".join(events) if events else run["last_message"],"state":build_state(get_player())})
    except ValueError as exc:
        db.session.rollback(); return api_error(str(exc))
    except Exception:
        db.session.rollback(); app.logger.exception("Falha em movimento cooperativo")
        return api_error("Não foi possível mover a dupla agora.",500)


@app.post("/api/coop/action")
@require_auth
def api_coop_action():
    expedition = _coop_record_for_user(current_user().id)
    if not expedition or expedition.status != "active": return api_error("Você não está em uma expedição cooperativa ativa.")
    expedition = CoopExpedition.query.filter_by(id=expedition.id).with_for_update().first()
    if not expedition or expedition.status != "active":
        return api_error("A expedição cooperativa já foi encerrada.")
    try:
        players = _coop_active_player_pair(expedition, lock=True)
        state=clone_json(expedition.state,{}); run=state.get("run") or {}; combat=run.get("combat")
        uid=current_user().id; members=state.get("members",{}); member=members[str(uid)]
        if not combat: return api_error("Não existe combate ativo.")
        if not member.get("alive",False): return api_error("Seu personagem está derrotado. Aguarde o aliado encerrar o combate para usar a Pena da Fênix.")
        if int(combat.get("next_actor_id") or 0) != uid:
            return api_error("Aguarde o turno do seu personagem.")
        player=players[uid]; inventory=clone_json(player.inventory,default_inventory())
        xp=clone_json(player.xp_by_attribute,default_xp())
        snapshot_stats=compute_player_stats(xp,player.equipped,member.get("hp",player.current_hp),member.get("mp",player.current_mp),class_code=player.class_code)
        snapshot={"hp":int(member.get("hp",player.current_hp)),"mp":int(member.get("mp",player.current_mp)),
            "hp_max":snapshot_stats["hp_max"],"mp_max":snapshot_stats["mp_max"],"stats":snapshot_stats["stats"],"class_code":player.class_code}
        local_combat=_coop_actor_to_local(member,combat)
        local_run={"combat":local_combat,"run_potions":clone_json(member.get("run_potions"),{}),
                   "mp_savings_credit":float(member.get("actor",{}).get("player_mp_savings_credit",0.0)),"loot":[]}
        try: result=resolve_player_action(local_run,snapshot,request.get_json(silent=True) or {},inventory,xp,clone_json(player.equipped,{}),random.Random())
        except ValueError as exc: return api_error(str(exc))
        player.inventory=inventory
        _coop_actor_from_local(member,local_combat)
        player.current_hp=int(member["hp"]); player.current_mp=int(member["mp"])
        member["run_potions"]=clone_json(local_run.get("run_potions"),{})
        events=list(result.get("events",[]))
        combat["enemy"]=local_combat["enemy"]
        combat["round"]=int(local_combat.get("round",combat.get("round",0)))
        combat["enemy_mp_savings_credit"]=float(local_combat.get("enemy_mp_savings_credit",combat.get("enemy_mp_savings_credit",0.0)))
        combat["log"]=(combat.get("log",[])+events)[-60:]
        state["run"]=run
        expedition.state=state  # Persist the in-transaction snapshot before any coordinated finalization.
        # A simultaneous kill/death is treated as a defeated character; the enemy remains defeated.
        if int(member.get("hp",0)) <= 0:
            member["alive"]=False; player.current_hp=10; player.current_mp=10
            events.append(f"{User.query.get(uid).username} foi derrotado. O aliado ainda pode continuar.")
        if result["result"] == "enemy_defeated" or int(combat["enemy"].get("hp",0)) <= 0:
            enemy=combat["enemy"]; monster_id=enemy["id"]; spec=MONSTER_BY_ID[monster_id]
            reward=award_monster_rewards(monster_id,xp,clone_json(player.equipped,{}),random.Random())
            player.coins=int(player.coins)+int(reward["coins"])
            member.setdefault("loot",[]).extend(reward["items"])
            member["coins_found"]=int(member.get("coins_found",0))+int(reward["coins"])
            events.append(f"{spec['name']} derrotado por {User.query.get(uid).username}. +{reward['coins']} moedas.")
            for item_id in reward["items"]: events.append(f"Drop individual: {ITEM_BY_ID[item_id]['name']}.")
            events.extend(reward["messages"])
            obj_id=enemy.get("object_id"); obj=next((o for o in run.get("objects",[]) if o.get("id")==obj_id),None)
            if obj:
                run["x"],run["y"]=obj["x"],obj["y"]
                if [run["x"],run["y"]] not in run.get("visited",[]): run.setdefault("visited",[]).append([run["x"],run["y"]])
                run["objects"]=[o for o in run.get("objects",[]) if o.get("id")!=obj_id]
            run["combat"]=None
            boss=spec["tier"]=="boss"
            if boss:
                if _coop_next_actor(state, uid) is None:
                    _coop_finish(expedition,players,"derrota","Ambos os jogadores foram derrotados durante o combate final.")
                    events.append("Os dois personagens foram derrotados. O loot temporário foi perdido.")
                else:
                    message=f"Vitória! A dupla derrotou {spec['name']} e concluiu a dungeon."
                    _coop_finish(expedition,players,"victory",message)
                    events.append("Dungeon concluída! Cada jogador recebeu seu próprio loot.")
            else:
                alive_names=[User.query.get(x).username for x in (expedition.host_user_id,expedition.guest_user_id) if members[str(x)].get("alive")]
                run["last_message"]=f"Vitória contra {spec['name']}! Continue explorando."
                events.append("O combate terminou. " + ("Sobrevivente: "+", ".join(alive_names)+"." if alive_names else "A dupla foi derrotada."))
                next_uid=_coop_next_actor(state,uid)
                if next_uid is None:
                    _coop_finish(expedition,players,"derrota","Ambos os jogadores foram derrotados.")
                state["run"]=run; state["last_message"]=run["last_message"]
        elif result["result"] == "player_defeated" or not member.get("alive",True):
            next_uid=_coop_next_actor(state,uid)
            if next_uid is None:
                _coop_finish(expedition,players,"derrota","Ambos os jogadores foram derrotados.")
            else:
                combat["next_actor_id"]=next_uid
                combat["log"].append(f"Turno de {User.query.get(next_uid).username}.")
                run["combat"]=combat; state["run"]=run
        else:
            next_uid=_coop_next_actor(state,uid)
            combat["next_actor_id"]=next_uid
            if next_uid is not None: combat["log"].append(f"Turno de {User.query.get(next_uid).username}.")
            run["combat"]=combat; state["run"]=run
        if expedition.status == "active":
            expedition.state=state; expedition.updated_at=local_now()
        db.session.commit()
        return jsonify({"ok":True,"message":" ".join(events),"state":build_state(get_player())})
    except ValueError as exc:
        db.session.rollback(); return api_error(str(exc))
    except Exception:
        db.session.rollback(); app.logger.exception("Falha em ação cooperativa")
        return api_error("Não foi possível concluir a ação cooperativa agora.",500)


@app.post("/api/coop/phoenix")
@require_auth
def api_coop_phoenix():
    expedition=_coop_record_for_user(current_user().id)
    if not expedition or expedition.status!="active": return api_error("Não há expedição cooperativa ativa.")
    expedition=CoopExpedition.query.filter_by(id=expedition.id).with_for_update().first()
    if not expedition or expedition.status!="active": return api_error("A expedição cooperativa já foi encerrada.")
    try:
        players=_coop_active_player_pair(expedition,lock=True)
        state=clone_json(expedition.state,{}); run=state.get("run",{})
        if run.get("combat"): return api_error("A Pena da Fênix só pode ser usada depois que o combate terminar.")
        uid=current_user().id; target_id=int((request.get_json(silent=True) or {}).get("target_user_id"))
        if target_id==uid or target_id not in (expedition.host_user_id,expedition.guest_user_id): return api_error("A Pena só pode ser usada no outro jogador da dupla.")
        actor=state["members"][str(uid)]; target=state["members"][str(target_id)]
        if not actor.get("alive",False): return api_error("Seu personagem precisa estar vivo para usar a Pena da Fênix.")
        if target.get("alive",False): return api_error("O aliado não está derrotado.")
        inv=clone_json(players[uid].inventory,default_inventory())
        if int(inv.get("pena_fenix",0))<=0: return api_error("Você não possui uma Pena da Fênix.")
        inv["pena_fenix"]-=1; players[uid].inventory=inv
        target["alive"]=True; target["hp"]=10; target["mp"]=10
        target["actor"]={"cooldowns":{},"buffs":[],"guard_reduction":0,"defensive_agi_once":None,
            "evasion_pp":0,"last_chance_used":False,"rebirth_used":False,"pending":[],
            "next_attack":{"bonus":0,"ignore":0},"weakness_revealed":False,"player_mp_savings_credit":0.0,"turn":0}
        players[target_id].current_hp=10; players[target_id].current_mp=10
        expedition.state=state; expedition.updated_at=local_now(); db.session.commit()
        return jsonify({"ok":True,"message":f"{User.query.get(target_id).username} foi ressuscitado com 10 HP e 10 MP. A Pena da Fênix foi consumida.","state":build_state(get_player())})
    except (ValueError, TypeError) as exc:
        db.session.rollback(); return api_error(str(exc) or "Alvo inválido.")
    except Exception:
        db.session.rollback(); app.logger.exception("Falha ao usar Pena da Fênix na coop")
        return api_error("Não foi possível concluir a ressurreição agora.", 500)


@app.post("/api/coop/abandon")
@require_auth
def api_coop_abandon():
    expedition=_coop_record_for_user(current_user().id)
    if not expedition or expedition.status!="active": return api_error("Não há expedição cooperativa ativa.")
    expedition=CoopExpedition.query.filter_by(id=expedition.id).with_for_update().first()
    if not expedition or expedition.status!="active": return api_error("A expedição cooperativa já foi encerrada.")
    try:
        players=_coop_active_player_pair(expedition,lock=True)
        state=clone_json(expedition.state,{})
        requester=state.get("abandon_requested_by")
        uid=current_user().id
        if requester is None:
            state["abandon_requested_by"]=uid
            expedition.state=state; expedition.updated_at=local_now(); db.session.commit()
            return jsonify({"ok":True,"message":"Pedido de abandono enviado. A dungeon só será encerrada se o aliado confirmar.","state":build_state(get_player())})
        if int(requester)==uid:
            state.pop("abandon_requested_by",None)
            expedition.state=state; expedition.updated_at=local_now(); db.session.commit()
            return jsonify({"ok":True,"message":"Pedido de abandono cancelado. A expedição continua.","state":build_state(get_player())})
        _coop_finish(expedition,players,"abandonada",f"A expedição cooperativa foi encerrada por acordo entre os jogadores.")
        db.session.commit()
        return jsonify({"ok":True,"message":"Expedição abandonada por acordo. Os itens temporários foram perdidos e as moedas preservadas.","state":build_state(get_player())})
    except Exception:
        db.session.rollback(); app.logger.exception("Falha ao abandonar coop")
        return api_error("Não foi possível concluir o pedido de abandono.",500)


@app.get("/api/library")
@require_auth
def api_library_list():
    p = get_player()
    return jsonify({"ok": True, "documents": library_payload(p),
                    "seconds_today": int(p.library_seconds_today or 0),
                    "coins_today": min(60, int(p.library_seconds_today or 0) // 60),
                    "daily_cap_seconds": 3600})


@app.post("/api/library/tick")
@require_auth
def api_library_tick():
    data = request.get_json(silent=True) or {}
    active = bool(data.get("active"))
    p = get_player(lock=True)
    tick_library_session(p, active)
    db.session.commit()
    return jsonify({"ok": True, "seconds_today": int(p.library_seconds_today or 0),
                    "coins_today": min(60, int(p.library_seconds_today or 0) // 60),
                    "coins": int(p.coins or 0), "active": bool(p.library_session_active)})


@app.post("/api/library/upload")
@require_auth
def api_library_upload():
    files = request.files.getlist("files")
    if not files:
        return api_error("Selecione ao menos um arquivo.")
    allowed = {"pdf", "epub", "txt", "md", "doc", "docx", "odt", "rtf", "csv", "xls", "xlsx", "ppt", "pptx"}
    p = get_player(lock=True)
    added = []
    for uploaded in files:
        raw_name = secure_filename(uploaded.filename or "")
        if not raw_name or "." not in raw_name:
            return api_error("Um dos arquivos não possui nome ou extensão válida.")
        ext = raw_name.rsplit(".", 1)[-1].lower()
        if ext not in allowed:
            return api_error(f"Formato .{ext} não permitido. Use PDF, EPUB, DOCX, TXT, planilhas ou apresentações.")
        content = uploaded.read(20 * 1024 * 1024 + 1)
        if not content:
            return api_error(f"O arquivo {raw_name} está vazio.")
        if len(content) > 20 * 1024 * 1024:
            return api_error(f"O arquivo {raw_name} excede 20 MB.")
        mimetype = mimetypes.guess_type(raw_name)[0] or "application/octet-stream"
        # Conteúdo é armazenado como binário no PostgreSQL/SQLite e entregue sempre como arquivo, nunca executado.
        row = LibraryDocument(user_id=current_user().id, filename=raw_name[:180], extension=ext,
                              mimetype=mimetype[:120], size_bytes=len(content), content=content)
        db.session.add(row)
        added.append(raw_name)
    db.session.commit()
    return jsonify({"ok": True, "message": f"{len(added)} arquivo(s) adicionado(s) à Biblioteca.",
                    "state": build_state(p), "documents": library_payload(p)})


@app.get("/library/document/<int:document_id>")
@require_auth
def library_document_download(document_id: int):
    row = LibraryDocument.query.filter_by(id=document_id, user_id=current_user().id).first()
    if not row:
        return api_error("Documento não encontrado.", 404)
    inline = request.args.get("view") == "1" and row.extension == "pdf"
    return send_file(BytesIO(row.content), mimetype=row.mimetype, as_attachment=not inline,
                     download_name=row.filename, max_age=0)


@app.delete("/api/library/document/<int:document_id>")
@require_auth
def api_library_delete(document_id: int):
    row = LibraryDocument.query.filter_by(id=document_id, user_id=current_user().id).first()
    if not row:
        return api_error("Documento não encontrado.", 404)
    db.session.delete(row)
    db.session.commit()
    p = get_player()
    return jsonify({"ok": True, "message": "Documento removido da Biblioteca.", "state": build_state(p)})


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
    if _coop_record_for_user(current_user().id): return api_error("Não é possível trocar equipamentos durante um convite ou expedição cooperativa.")
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
    if _coop_record_for_user(current_user().id): return api_error("Durante a expedição cooperativa, use os itens no seu turno de combate.")
    if item_id not in CONSUMABLES:return api_error("Poção inválida.")
    p=get_player(lock=True); run=clone_json(p.dungeon_state,None)
    if run and run.get("combat"):
        return api_error("Durante o combate, use a poção como sua ação de Item.")
    inv=clone_json(p.inventory,default_inventory()); qty=int(inv.get(item_id,0))
    rqty=int((run or {}).get("run_potions",{}).get(item_id,0))
    if qty<=0 and rqty<=0:return api_error("Você não possui essa poção.")
    stats=compute_player_stats(p.xp_by_attribute,p.equipped,p.current_hp,p.current_mp,class_code=p.class_code)
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
    if _coop_record_for_user(current_user().id): return api_error("Você possui um convite ou expedição cooperativa pendente/ativa.")
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
    snapshot={"hp":hp,"mp":mp,"hp_max":stats["hp_max"],"mp_max":stats["mp_max"],"stats":stats["stats"],"class_code":p.class_code}
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
        if any(s.get("action")=="on_kill_mp" for s in effective_skills(xp,p.equipped,class_code=p.class_code).values()):
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
    prices={"pocao_cura":30,"pocao_mana":30,"bracelete_salvacao":500,"ticket_dungeon":600,"minute":1000,"pena_fenix":100, **{k:v["price"] for k,v in RELIC_CATALOG.items()}}
    labels={"pocao_cura":"Poção de Cura","pocao_mana":"Poção de Mana","bracelete_salvacao":"Bracelete da Salvação","ticket_dungeon":"Ticket de Dungeon","minute":"1 minuto adicional","pena_fenix":"Pena da Fênix", **{k:v["name"] for k,v in RELIC_CATALOG.items()}}
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
                elif isinstance(value, (bytes, bytearray)):
                    value={"__base64__": base64.b64encode(bytes(value)).decode("ascii")}
                values[column.name]=value
            output.append(values)
        return output
    return {"format":"rpg-habitos-backup-v1","created_at":local_now().isoformat(),"database":"logical-json","tables":{
        "user":serialize(User), "player":serialize(Player), "daily_evaluation":serialize(DailyEvaluation),
        "activity":serialize(Activity), "library_document":serialize(LibraryDocument),
        "dungeon_attempt":serialize(DungeonAttempt), "coop_expedition":serialize(CoopExpedition), "idempotency_record":serialize(IdempotencyRecord)
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
    table_models = {"user": User, "player": Player, "daily_evaluation": DailyEvaluation, "activity": Activity, "library_document": LibraryDocument, "dungeon_attempt": DungeonAttempt, "coop_expedition": CoopExpedition, "idempotency_record": IdempotencyRecord}
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
            db.session.execute(text('LOCK TABLE "user", "player", "daily_evaluation", "activity", "library_document", "dungeon_attempt", "coop_expedition", "idempotency_record", "admin_backup" IN ACCESS EXCLUSIVE MODE'))
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
        db.session.query(LibraryDocument).delete(synchronize_session=False)
        db.session.query(DungeonAttempt).delete(synchronize_session=False)
        db.session.query(CoopExpedition).delete(synchronize_session=False)
        db.session.query(Player).delete(synchronize_session=False)
        db.session.query(User).delete(synchronize_session=False)
        for name in ("user", "player", "daily_evaluation", "activity", "library_document", "dungeon_attempt", "coop_expedition", "idempotency_record"):
            if name not in tables: continue  # Compatibility with older logical backups.
            Model = table_models[name]
            for row in tables[name]:
                allowed = {column.name for column in Model.__table__.columns}
                values = {k: v for k, v in row.items() if k in allowed}
                for col in Model.__table__.columns:
                    if col.name in values and isinstance(col.type, db.DateTime) and isinstance(values[col.name], str):
                        values[col.name] = datetime.fromisoformat(values[col.name])
                    if col.name == "content" and isinstance(values.get(col.name), dict) and "__base64__" in values[col.name]:
                        values[col.name] = base64.b64decode(values[col.name]["__base64__"])
                if name == "user" and "password_hash" not in values: raise ValueError("Backup sem hashes de senha; restauração recusada.")
                db.session.add(Model(**values))
        db.session.flush()
        if db.engine.dialect.name == "postgresql":
            # Preserve explicit IDs from the logical backup and advance sequences in the same transaction.
            for model in (User, Player, DailyEvaluation, Activity, LibraryDocument, DungeonAttempt, CoopExpedition, IdempotencyRecord):
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
                    "activities": Activity.query.count(), "library_documents": LibraryDocument.query.count(), "evaluations": DailyEvaluation.query.count(),
                    "dungeon_attempts": DungeonAttempt.query.count(), "coop_expeditions": CoopExpedition.query.count(), "database": "PostgreSQL" if "postgresql" in app.config["SQLALCHEMY_DATABASE_URI"] else "SQLite"})


@app.post("/api/rewards/session")
@require_auth
def api_reward_session():
    data=request.get_json(silent=True) or {}; active=bool(data.get("active"))
    p=get_player(lock=True);tick_reward_timer(p)
    if active:
        if not p.reward_site_url:
            return api_error("Configure seu site de recompensa na criação do personagem.")
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
    # PostgreSQL uses TIMESTAMP; DATETIME is not a valid PostgreSQL column type.
    # SQLite accepts DATETIME, so keep its native declaration there.
    library_timestamp_type = "TIMESTAMP" if db.engine.dialect.name == "postgresql" else "DATETIME"
    additions = {
        # db.create_all() does not add columns to an already-existing table.
        # Upgrade legacy accounts before querying User during admin bootstrap.
        User.__table__.name: {
            "email": "VARCHAR(255)",
            "is_admin": "BOOLEAN NOT NULL DEFAULT FALSE",
            "legacy_progress_imported": "BOOLEAN NOT NULL DEFAULT FALSE",
        },
        Player.__table__.name: {"user_id": "INTEGER", "class_code": "VARCHAR(24)", "task_mapping": "JSON", "task_mapping_version": "INTEGER DEFAULT 0", "setup_complete": "BOOLEAN DEFAULT FALSE", "relics_owned": "JSON", "active_relic_id": "VARCHAR(24)", "manto_xp_remainder": "INTEGER DEFAULT 0", "character_config_version": "INTEGER DEFAULT 0", "reward_site_name": "VARCHAR(80)", "reward_site_url": "VARCHAR(600)", "reward_site2_name": "VARCHAR(80)", "reward_site2_url": "VARCHAR(600)", "library_day": "VARCHAR(10)", "library_seconds_today": "INTEGER DEFAULT 0", "library_last_tick_at": library_timestamp_type, "library_session_active": "BOOLEAN DEFAULT FALSE"},
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
