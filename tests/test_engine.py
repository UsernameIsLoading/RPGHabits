import random
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import game_data as gd
import game_engine as ge


class ProgressionTests(unittest.TestCase):
    def test_rank_thresholds(self):
        expected = {0: "F", 59: "F", 60: "E", 179: "E", 180: "D",
                    419: "D", 420: "C", 899: "C", 900: "B",
                    1859: "B", 1860: "A", 3779: "A", 3780: "S"}
        for xp, rank in expected.items():
            with self.subTest(xp=xp):
                self.assertEqual(ge.rank_for_xp(xp), rank)

    def test_initial_stats_include_f_rank_passives(self):
        xp = {a["code"]: 0 for a in gd.ATTRIBUTES}
        stats = ge.compute_player_stats(xp)
        self.assertEqual(stats["hp_max"], 25)  # 10 base + Vitalidade +15
        self.assertEqual(stats["mp_max"], 11)  # 10 base + Reserva Espiritual +1
        self.assertEqual(stats["stats"]["ATK"], 2)  # rank F + Punho Reforçado
        self.assertEqual(stats["stats"]["AGI"], 2)  # rank F + Passos Leves

    def test_catalog_sizes_and_drop_invariants(self):
        self.assertEqual(len(gd.SKILLS), 56)
        self.assertEqual(len(gd.ITEMS), 24)
        self.assertEqual(len(gd.MONSTERS), 12)
        all_drops = [i for monster in gd.MONSTERS for i in monster["loot"]]
        self.assertEqual(len(all_drops), len(set(all_drops)))
        for monster in gd.MONSTERS:
            expected = {"common": 1, "strong": 2, "boss": 4}[monster["tier"]]
            self.assertEqual(len(monster["loot"]), expected)
            if monster["tier"] == "boss":
                for item_id in monster["loot"]:
                    self.assertIn(gd.ITEM_BY_ID[item_id]["rank"], "DCBAS")
            if monster["tier"] == "strong":
                for skill in monster["skills"]:
                    self.assertNotEqual(gd.SKILL_BY_ID[skill["id"]]["rank"], "F")


class DungeonTests(unittest.TestCase):
    def test_map_and_field_of_view(self):
        xp = {a["code"]: 0 for a in gd.ATTRIBUTES}
        run = ge.create_dungeon(xp, random.Random(9))
        self.assertGreaterEqual(run["floors"], 3)
        self.assertLessEqual(run["floors"], 7)
        visible = ge.visible_map(run)
        self.assertEqual(len(visible["grid"]), 6)
        self.assertTrue(all(len(row) == 6 for row in visible["grid"]))
        self.assertEqual(visible["visible_count"], 4)  # player starts in a corner
        self.assertEqual(run["x"], 0)
        self.assertEqual(run["y"], 0)

    def test_invalid_move_is_rejected(self):
        xp = {a["code"]: 0 for a in gd.ATTRIBUTES}
        run = ge.create_dungeon(xp, random.Random(4))
        with self.assertRaises(ValueError):
            ge.move_in_dungeon(run, 2, 0, xp, ge.compute_player_stats(xp))
        with self.assertRaises(ValueError):
            ge.move_in_dungeon(run, 0, 0, xp, ge.compute_player_stats(xp))


class PotionTests(unittest.TestCase):
    def test_potions_are_capped_and_inventory_is_consumed(self):
        xp = {a["code"]: 0 for a in gd.ATTRIBUTES}
        stats = ge.compute_player_stats(xp)
        actor = {"hp": 10, "hp_max": stats["hp_max"], "mp": 5,
                 "mp_max": stats["mp_max"]}
        healed = ge._heal(actor, gd.CONSUMABLES["pocao_cura"]["amount"])
        self.assertEqual(healed, 8)
        self.assertEqual(actor["hp"], 18)
        healed = ge._heal(actor, 999)
        self.assertEqual(actor["hp"], stats["hp_max"])
        self.assertEqual(healed, stats["hp_max"] - 18)
        restored = ge._restore_mp(actor, gd.CONSUMABLES["pocao_mana"]["amount"])
        self.assertEqual(restored, 6)
        self.assertEqual(actor["mp"], 11)

    def test_formula_eficiente_accumulates_fractional_credit(self):
        actor = {"skills": [{"action": "mp_efficiency"}]}
        combat = {"player_mp_savings_credit": 0.0}
        skill2 = {"mp_cost": 2}
        skill4 = {"mp_cost": 4}
        skill6 = {"mp_cost": 6}
        for _ in range(2):
            cost, discount = ge._skill_cost(skill2, actor, True, combat)
            self.assertEqual(cost, 2)
            self.assertEqual(discount, 0)
        cost, discount = ge._skill_cost(skill4, actor, True, combat)
        self.assertEqual(cost, 4)
        self.assertEqual(discount, 0)
        self.assertAlmostEqual(combat["player_mp_savings_credit"], 0.24, places=5)
        # Repeated casts eventually turn accumulated fractional saving into an integer discount.
        discounts = []
        for _ in range(40):
            _, discount = ge._skill_cost(skill6, actor, True, combat)
            discounts.append(discount)
        self.assertGreaterEqual(sum(discounts), 1)


class CombatTests(unittest.TestCase):
    def _combat_fixture(self, xp=None, hp=10, mp=5):
        xp = xp or {a["code"]: 0 for a in gd.ATTRIBUTES}
        stats = ge.compute_player_stats(xp)
        enemy = {
            "id": "goblin_saqueador", "name": "Goblin de teste", "icon": "👺",
            "tier": "common", "rank": "F", "hp": 100, "hp_max": 100,
            "mp": 10, "mp_max": 10,
            "stats": {"ATK": 1, "DEF": 1, "AGI": 1, "MAG": 1, "RES": 1, "LUC": 1},
            "skills": [], "cooldowns": {}, "buffs": [], "guard_reduction": 0,
            "defensive_agi_once": None, "evasion_pp": 0,
            "next_attack": {"bonus": 0, "ignore": 0}, "pending": [],
            "last_chance_used": False, "rebirth_used": False, "turn": 0,
        }
        combat = {
            "enemy": enemy, "player_hp": hp, "player_mp": mp, "player_turn": 0,
            "round": 0, "cooldowns": {}, "buffs": [], "guard_reduction": 0,
            "player_guard_reduction": 0, "defensive_agi_once": None,
            "player_defensive_agi_once": None, "evasion_pp": 0,
            "player_evasion_pp": 0, "next_attack": {"bonus": 0, "ignore": 0},
            "pending": [], "last_chance_used": False, "rebirth_used": False,
            "weakness_revealed": False, "player_mp_savings_credit": 0.0,
            "enemy_mp_savings_credit": 0.0, "log": [],
        }
        run = {"combat": combat, "run_potions": {"pocao_cura": 0, "pocao_mana": 0},
               "loot": [], "mp_savings_credit": 0.0}
        snapshot = {"hp": hp, "mp": mp, "hp_max": stats["hp_max"],
                    "mp_max": stats["mp_max"], "stats": stats["stats"]}
        return xp, stats, run, snapshot

    def test_potion_spends_one_and_enemy_replies(self):
        xp, _, run, snapshot = self._combat_fixture(hp=10)
        inv = {"pocao_cura": 2, "pocao_mana": 2, "equipment": {}}
        result = ge.resolve_player_action(run, snapshot, {"type": "item", "item_id": "pocao_cura"},
                                          inv, xp, {}, random.Random(3))
        self.assertEqual(result["result"], "continue")
        self.assertEqual(inv["pocao_cura"], 1)
        self.assertTrue(any("Poção de Cura" in e for e in result["events"]))
        self.assertEqual(run["combat"]["player_hp"], 17)

    def test_insufficient_mp_rejects_magic_skill(self):
        xp = {a["code"]: 0 for a in gd.ATTRIBUTES}
        xp["MAG"] = 60  # libera Projétil Arcano (E)
        xp, _, run, snapshot = self._combat_fixture(xp=xp, mp=1)
        with self.assertRaisesRegex(ValueError, "MP insuficiente"):
            ge.resolve_player_action(run, snapshot, {"type": "skill", "skill_id": "projetil_arcano"},
                                     {"pocao_cura": 2, "pocao_mana": 2, "equipment": {}}, xp, {}, random.Random(2))

    def test_two_turn_buff_and_cooldown_tick_after_full_turns(self):
        xp = {a["code"]: 0 for a in gd.ATTRIBUTES}
        xp["DEF"] = 180  # libera Pele de Pedra (D)
        xp, _, run, snapshot = self._combat_fixture(xp=xp, hp=25)
        inv = {"pocao_cura": 2, "pocao_mana": 2, "equipment": {}}
        ge.resolve_player_action(run, snapshot, {"type": "skill", "skill_id": "pele_de_pedra"}, inv, xp, {}, random.Random(1))
        combat = run["combat"]
        self.assertEqual(combat["cooldowns"]["pele_de_pedra"], 4)
        self.assertEqual(combat["buffs"][0]["remaining"], 2)
        snapshot2 = {"hp": combat["player_hp"], "mp": combat["player_mp"],
                     "hp_max": 25, "mp_max": 11, "stats": ge.compute_player_stats(xp)["stats"]}
        ge.resolve_player_action(run, snapshot2, {"type": "attack"}, inv, xp, {}, random.Random(2))
        self.assertEqual(run["combat"]["cooldowns"]["pele_de_pedra"], 3)
        self.assertEqual(run["combat"]["buffs"][0]["remaining"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
