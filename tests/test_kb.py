import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("owlready2")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from sppr import kb  # noqa: E402

pytest.importorskip("pulp")
import p5_kb  # noqa: E402


@pytest.fixture(scope="module")
def setup():
    cfg = json.loads((ROOT / "config" / "p5_kb.json").read_text(encoding="utf-8"))
    models, specs = p5_kb.load_models()
    return cfg, models, specs


def run(setup, changes):
    cfg, models, specs = setup
    return p5_kb.run_kb(models, specs, cfg, changes)


def test_every_rule_has_implementation_and_swrl_parses(setup):
    cfg, _, _ = setup
    for rule in cfg["rules"]:
        if rule["kind"] == "closed_world":
            assert rule["swrl"] is None
        else:
            assert rule["id"] in kb.RULE_FUNCS
    onto, *_ = run(setup, {})
    assert len(list(onto.rules())) == sum(1 for r in cfg["rules"] if r.get("swrl"))


def test_base_scenario_conclusions(setup):
    _, _, derived, trace, meta, table = run(setup, {})
    bad = dict(zip(table.loc[~table.admissible, "vendor"], table.loc[~table.admissible, "exclusion_rules"]))
    assert bad == {"Vertiv": "R1", "BONPET": "R2", "MikroTik": "R5"}
    hp = table[table.vendor == "HP"].iloc[0]
    assert "R9" in hp.flag_rules and "R10" in hp.flag_rules
    # R10 срабатывает только после R9 - вывод идёт в несколько шагов
    steps = {t["rule"]: t["step"] for t in trace if t["vendor"] == "HP"}
    assert steps["R10"] > steps["R9"]
    assert set(table.loc[table.recommended, "vendor"]) == {"Piton", "Уралэнерготел", "Aten", "Eltex", "Lenovo"}
    assert meta["expand_suppliers"] == []


def test_scenarios_change_conclusions(setup):
    *_, meta, table = run(setup, {"ats_before_ups": False})
    assert not table.loc[table.vendor == "Уралэнерготел", "admissible"].iloc[0]
    *_, meta, table = run(setup, {"rack_load_w": 2200})
    assert "ИБП" in meta["expand_suppliers"]
    *_, meta, table = run(setup, {"russian_origin_required": True})
    assert set(meta["expand_suppliers"]) == {"КВМ", "ПК и серверы"}


def test_admission_and_owl_roundtrip(setup, tmp_path):
    onto, facts, derived, trace, meta, table = run(setup, {})
    adm = kb.admission(table)
    assert adm.loc[~adm.admissible, "reason"].str.startswith("база знаний").all()
    path = tmp_path / "kb.owl"
    onto.save(file=str(path), format="rdfxml")
    from owlready2 import World
    o2 = World().get_ontology(path.as_uri()).load()
    st1, st2 = kb.stats(onto), kb.stats(o2)
    assert st1 == st2 and st1["models"] == 15
