"""Safety and determinism checks for the local protocol-card engine."""
from __future__ import annotations

import copy
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.protocols import (  # noqa: E402
    DEFAULT_CATALOG_PATH,
    DEFAULT_INVENTORY_PATH,
    ProtocolDataError,
    ProtocolEngine,
    card_integrity_digest,
)


NOW = datetime(2026, 9, 23, 12, 50, tzinfo=timezone.utc)
EXPECTED_CARDS = {
    "AUDIO-TOUX-01",
    "RHUME-SIMPLE-01",
    "PSEUDO-GRIPPE-01",
    "DESHYDRATATION-01",
    "ALERTE-RESP-01",
    "FIEVRE-DOULEUR-01",
}
EXPECTED_SOURCES = {
    "https://www.who.int/news/item/28-06-2021-who-issues-first-global-report-on-ai-in-health-and-six-guiding-principles-for-its-design-and-use",
    "https://www.who.int/publications/i/item/9789240084759/",
    "https://iris.who.int/server/api/core/bitstreams/ad62580f-540f-4e36-b957-e7f2946ae1fb/content",
    "https://www.ameli.fr/assure/sante/themes/rhinopharyngite-adulte/que-faire-quand-consulter",
    "https://ansm.sante.fr/actualites/en-cas-de-rhume-evitez-les-medicaments-vasoconstricteurs-par-voie-orale",
    "https://ansm.sante.fr/dossiers-thematiques/medicaments-de-la-douleur/le-paracetamol",
    "https://ansm.sante.fr/dossiers-thematiques/les-anti-inflammatoires-non-steroidiens-ains-ibuprofene-ketoprofene-acide-acetylsalicylique",
    "https://www.who.int/publications/i/item/9789240097759",
    "https://www.ameli.fr/assure/sante/themes/toux/diagnostic-traitement",
    "https://www.who.int/publications/i/item/WHO-HIS-SDS-2019.5",
}


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _engine() -> ProtocolEngine:
    return ProtocolEngine.load()


def _screening() -> dict:
    return {
        "patient_identity_confirmed": True,
        "age_years": 34,
        "allergies_reviewed": True,
        "allergic_item_ids": [],
        "current_medications_reviewed": True,
        "contraindications_reviewed": True,
        "contraindicated_item_ids": [],
        "red_flags_reviewed": True,
        "red_flags": [],
        "pregnancy_status": "non_applicable",
    }


def _validation(protocol_id: str) -> dict:
    return {
        "validated": True,
        "protocol_id": protocol_id,
        "role": "clinicien",
        "validator_id": "demo-clinicien-01",
        "validated_at": "2026-09-23T12:49:00Z",
    }


def _write_pair(tmp_path: Path, catalog: dict, inventory: dict) -> tuple[Path, Path]:
    catalog_path = tmp_path / "catalog.json"
    inventory_path = tmp_path / "inventory.json"
    catalog_path.write_text(json.dumps(catalog, ensure_ascii=False), encoding="utf-8")
    inventory_path.write_text(json.dumps(inventory, ensure_ascii=False), encoding="utf-8")
    return catalog_path, inventory_path


def _resign(card: dict) -> None:
    card["signature"]["digest"] = card_integrity_digest(card)


def test_catalogue_contains_exact_cards_and_researched_official_sources():
    engine = _engine()

    assert set(engine.card_ids) == EXPECTED_CARDS
    assert set(engine.source_urls) == EXPECTED_SOURCES


def test_matching_is_accent_insensitive_deterministic_and_does_not_echo_raw_text():
    engine = _engine()
    observations = {
        "utterance": "Identité très privée ZXQ-991 : J’ai de la FIÈVRE et mal de tête."
    }

    first = engine.evaluate_json(observations, now=NOW)
    second = engine.evaluate_json(observations, now=NOW)
    decoded = json.loads(first)

    assert first == second
    assert decoded["card"]["id"] == "FIEVRE-DOULEUR-01"
    assert decoded["diagnostic"] is False
    assert "ZXQ-991" not in first


def test_respiratory_alert_always_outranks_a_fever_match():
    result = _engine().evaluate(
        {"utterance": "J'ai de la fièvre", "vitals": {"spo2": 90, "respiration": 17}},
        now=NOW,
    )

    assert result["card"]["id"] == "ALERTE-RESP-01"
    assert result["card"]["escalation"] == "urgence_humaine_immediate"
    assert result["medication_options"] == []


def test_audio_cough_is_only_a_signal_to_confirm_and_never_a_diagnosis():
    result = _engine().evaluate({"audio_events": ["cough"]}, now=NOW)

    assert result["card"]["id"] == "AUDIO-TOUX-01"
    assert "confirmer" in result["card"]["classification_fr"].casefold()
    assert result["diagnostic"] is False
    assert result["medication_options"] == []


@pytest.mark.parametrize(
    ("screening", "validation", "reason"),
    [
        (None, None, "depistage_absent"),
        (_screening(), None, "validation_humaine_absente"),
        (
            {**_screening(), "red_flags": ["aggravation rapide"]},
            _validation("FIEVRE-DOULEUR-01"),
            "drapeau_rouge_present",
        ),
        (
            {**_screening(), "allergic_item_ids": ["MED-PARACETAMOL-DEMO-01"]},
            _validation("FIEVRE-DOULEUR-01"),
            "allergie_signalee",
        ),
        (
            _screening(),
            _validation("PSEUDO-GRIPPE-01"),
            "validation_humaine_hors_perimetre",
        ),
    ],
)
def test_medication_option_is_withheld_when_any_gate_fails(screening, validation, reason):
    result = _engine().evaluate(
        {"utterance": "J'ai de la fièvre"},
        screening=screening,
        human_validation=validation,
        now=NOW,
    )

    assert result["medication_options"] == []
    assert result["medication_gate"]["eligible"] is False
    assert reason in result["medication_gate"]["reasons"]


def test_only_a_complete_screen_and_recent_scoped_human_validation_reveal_an_option():
    result = _engine().evaluate(
        {"utterance": "J'ai de la fièvre"},
        screening=_screening(),
        human_validation=_validation("FIEVRE-DOULEUR-01"),
        now=NOW,
    )

    assert result["medication_gate"] == {
        "eligible": True,
        "screening_complete": True,
        "human_validation_verified": True,
        "protocol_integrity_verified": True,
        "reasons": [],
    }
    assert len(result["medication_options"]) == 1
    option = result["medication_options"][0]
    assert option["inventory"]["simulated"] is True
    assert option["inventory"]["quantity"] == 24
    assert "simul" in option["inventory"]["location_label"].casefold()
    assert "dose" not in json.dumps(option, ensure_ascii=False).casefold()
    assert "administration automatique" in option["status_fr"]


def test_pseudoephedrine_and_nsaids_are_never_inventory_options():
    payload = _engine().evaluate_json(
        {"utterance": "J'ai la grippe et des frissons"},
        screening=_screening(),
        human_validation=_validation("PSEUDO-GRIPPE-01"),
        now=NOW,
    ).casefold()

    assert "pseudoéphédrine" not in payload
    assert "ibuprofène" not in payload
    assert "kétoprofène" not in payload


@pytest.mark.parametrize(
    ("mutate", "expected_reason"),
    [
        (lambda inventory: inventory.update({"as_of": "2026-09-01T00:00:00Z"}), "inventaire_perime_ou_obsolete"),
        (
            lambda inventory: inventory["items"].__setitem__(
                slice(None),
                [item for item in inventory["items"] if item["id"] != "MED-PARACETAMOL-DEMO-01"],
            ),
            "article_absent",
        ),
        (
            lambda inventory: next(
                item for item in inventory["items"] if item["id"] == "MED-PARACETAMOL-DEMO-01"
            ).update({"quantity": 0}),
            "stock_simule_insuffisant",
        ),
        (
            lambda inventory: next(
                item for item in inventory["items"] if item["id"] == "MED-PARACETAMOL-DEMO-01"
            ).update({"expires_on": "2025-01-01"}),
            "article_expire",
        ),
    ],
)
def test_inventory_missing_stale_expired_or_insufficient_fails_closed(
    tmp_path, mutate, expected_reason
):
    catalog = _json(DEFAULT_CATALOG_PATH)
    inventory = _json(DEFAULT_INVENTORY_PATH)
    mutate(inventory)
    catalog_path, inventory_path = _write_pair(tmp_path, catalog, inventory)
    engine = ProtocolEngine.load(catalog_path, inventory_path)

    result = engine.evaluate(
        {"utterance": "J'ai de la fièvre"},
        screening=_screening(),
        human_validation=_validation("FIEVRE-DOULEUR-01"),
        now=NOW,
    )

    assert result["medication_options"] == []
    assert expected_reason in result["medication_gate"]["reasons"]


def test_unreviewed_card_edit_invalidates_the_integrity_signature(tmp_path):
    catalog = _json(DEFAULT_CATALOG_PATH)
    inventory = _json(DEFAULT_INVENTORY_PATH)
    catalog["cards"][0]["title_fr"] = "Texte modifié sans nouvelle signature"
    catalog_path, inventory_path = _write_pair(tmp_path, catalog, inventory)

    with pytest.raises(ProtocolDataError, match="signature d'intégrité invalide"):
        ProtocolEngine.load(catalog_path, inventory_path)


def test_inactive_but_correctly_resigned_card_cannot_match(tmp_path):
    catalog = _json(DEFAULT_CATALOG_PATH)
    inventory = _json(DEFAULT_INVENTORY_PATH)
    fever = next(card for card in catalog["cards"] if card["id"] == "FIEVRE-DOULEUR-01")
    fever["status"] = "inactive"
    _resign(fever)
    catalog_path, inventory_path = _write_pair(tmp_path, catalog, inventory)
    result = ProtocolEngine.load(catalog_path, inventory_path).evaluate(
        {"utterance": "fièvre"}, now=NOW
    )

    assert result["card"] is None
    assert result["medication_options"] == []


def test_future_or_naive_timestamps_fail_closed():
    engine = _engine()
    future_validation = _validation("FIEVRE-DOULEUR-01")
    future_validation["validated_at"] = "2026-09-23T12:51:00Z"
    result = engine.evaluate(
        {"utterance": "fièvre"},
        screening=_screening(),
        human_validation=future_validation,
        now=NOW,
    )
    assert result["medication_options"] == []
    assert "validation_humaine_obsolete" in result["medication_gate"]["reasons"]

    with pytest.raises(ProtocolDataError, match="fuseau horaire"):
        engine.evaluate({"utterance": "fièvre"}, now=datetime(2026, 9, 23, 12, 50))


def test_common_word_fragments_do_not_trigger_a_protocol():
    result = _engine().evaluate(
        {"utterance": "Mon copain apporte du pain pour le repas."}, now=NOW
    )

    assert result["card"] is None
    assert result["medication_options"] == []
