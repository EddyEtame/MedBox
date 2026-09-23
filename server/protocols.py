"""Deterministic, fail-closed protocol cards for the MedBox demonstration.

This module deliberately sits outside the language-model path.  It matches a
small, reviewed catalogue of French protocol cards, checks every safety gate,
and returns plain JSON-compatible data.  It does not diagnose, prescribe, or
turn a simulated stock record into a real pharmacy inventory.

Medication-like options are hidden unless *all* of these conditions hold:

* the selected card is active and its checked-in SHA-256 integrity signature
  verifies;
* every required screening field is present and safe;
* a recent human validation is scoped to the exact protocol card; and
* the explicitly simulated inventory snapshot is current, unexpired, active,
  and sufficiently stocked.

The SHA-256 signature detects accidental or unreviewed edits in the portable
bundle.  It is not represented as a clinician's electronic signature.  A
future production deployment should replace it with an authenticated signing
service and an authorised clinical governance process.
"""
from __future__ import annotations

import copy
import hashlib
import hmac
import json
import math
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CATALOG_PATH = ROOT / "protocols" / "catalog.json"
DEFAULT_INVENTORY_PATH = ROOT / "protocols" / "inventory.simulated.json"

ALLOWED_SOURCE_HOSTS = frozenset(
    {"www.who.int", "iris.who.int", "www.ameli.fr", "ansm.sante.fr"}
)
ALLOWED_HUMAN_ROLES = frozenset({"clinicien", "medecin_responsable"})
UNKNOWN_VALUES = frozenset({"", "unknown", "inconnu", "inconnue", "non_verifie"})


class ProtocolDataError(ValueError):
    """Raised when checked-in protocol or inventory data cannot be trusted."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_datetime(value: Any, *, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ProtocolDataError(f"{field}: horodatage absent")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProtocolDataError(f"{field}: horodatage invalide") from exc
    if parsed.tzinfo is None:
        raise ProtocolDataError(f"{field}: fuseau horaire obligatoire")
    return parsed.astimezone(timezone.utc)


def _parse_date(value: Any, *, field: str) -> date:
    if not isinstance(value, str) or not value.strip():
        raise ProtocolDataError(f"{field}: date absente")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ProtocolDataError(f"{field}: date invalide") from exc


def _normalise_text(value: str) -> str:
    ascii_text = "".join(
        ch
        for ch in unicodedata.normalize("NFKD", value.casefold())
        if not unicodedata.combining(ch)
    )
    return " ".join(re.findall(r"[a-z0-9]+", ascii_text))


def _canonical_card(card: Mapping[str, Any]) -> bytes:
    unsigned = {key: value for key, value in card.items() if key != "signature"}
    return json.dumps(
        unsigned,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def card_integrity_digest(card: Mapping[str, Any]) -> str:
    """Return the reproducible digest used by the checked-in card signature."""

    return hashlib.sha256(_canonical_card(card)).hexdigest()


def _verify_card_signature(card: Mapping[str, Any]) -> bool:
    signature = card.get("signature")
    if not isinstance(signature, Mapping):
        return False
    if signature.get("algorithm") != "sha256":
        return False
    if signature.get("scope") != "simulation_pedagogique_non_clinique":
        return False
    if not isinstance(signature.get("signed_by"), str) or not signature["signed_by"].strip():
        return False
    try:
        _parse_datetime(signature.get("signed_at"), field="signature.signed_at")
    except ProtocolDataError:
        return False
    expected = signature.get("digest")
    return isinstance(expected, str) and hmac.compare_digest(
        expected.lower(), card_integrity_digest(card)
    )


def _read_json(path: Path) -> dict[str, Any]:
    try:
        decoded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProtocolDataError(f"Données de protocole illisibles: {path.name}") from exc
    if not isinstance(decoded, dict):
        raise ProtocolDataError(f"{path.name}: objet JSON attendu")
    return decoded


def _safe_source(source: Mapping[str, Any]) -> None:
    if not isinstance(source.get("id"), str) or not source["id"].strip():
        raise ProtocolDataError("source sans identifiant")
    url = source.get("url")
    if not isinstance(url, str):
        raise ProtocolDataError(f"source {source['id']}: URL absente")
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_SOURCE_HOSTS:
        raise ProtocolDataError(f"source {source['id']}: domaine officiel non autorisé")


def _lookup(mapping: Mapping[str, Any], dotted: str) -> Any:
    value: Any = mapping
    for part in dotted.split("."):
        if not isinstance(value, Mapping) or part not in value:
            return None
        value = value[part]
    return value


def _condition_matches(observations: Mapping[str, Any], condition: Mapping[str, Any]) -> bool:
    value = _lookup(observations, str(condition.get("field", "")))
    target = condition.get("value")
    operator = condition.get("operator")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    if not math.isfinite(float(value)) or not isinstance(target, (int, float)):
        return False
    if operator == "lt":
        return value < target
    if operator == "lte":
        return value <= target
    if operator == "gt":
        return value > target
    if operator == "gte":
        return value >= target
    if operator == "eq":
        return value == target
    return False


def _observation_text(observations: Mapping[str, Any]) -> str:
    parts: list[str] = []
    for key in ("utterance", "symptoms", "audio_events", "complaint"):
        value = observations.get(key)
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            parts.extend(str(item) for item in value if isinstance(item, str))
    return _normalise_text(" ".join(parts))


@dataclass(frozen=True)
class _InventoryCheck:
    usable: bool
    code: str
    item: Mapping[str, Any] | None = None


class ProtocolEngine:
    """Load, match, and safely serialize the reviewed local protocol catalogue."""

    def __init__(self, catalog: Mapping[str, Any], inventory: Mapping[str, Any]):
        self._catalog = copy.deepcopy(dict(catalog))
        self._inventory = copy.deepcopy(dict(inventory))
        self._sources: dict[str, Mapping[str, Any]] = {}
        self._cards: tuple[Mapping[str, Any], ...] = ()
        self._items: dict[str, Mapping[str, Any]] = {}
        self._validate()

    @classmethod
    def load(
        cls,
        catalog_path: Path | str = DEFAULT_CATALOG_PATH,
        inventory_path: Path | str = DEFAULT_INVENTORY_PATH,
    ) -> "ProtocolEngine":
        return cls(_read_json(Path(catalog_path)), _read_json(Path(inventory_path)))

    @property
    def card_ids(self) -> tuple[str, ...]:
        return tuple(card["id"] for card in self._cards)

    @property
    def source_urls(self) -> tuple[str, ...]:
        return tuple(source["url"] for source in self._sources.values())

    def _validate(self) -> None:
        if self._catalog.get("schema_version") != 1:
            raise ProtocolDataError("catalogue: version de schéma non prise en charge")
        if self._inventory.get("schema_version") != 1:
            raise ProtocolDataError("inventaire: version de schéma non prise en charge")
        if self._inventory.get("simulated") is not True:
            raise ProtocolDataError("inventaire: le marqueur simulé est obligatoire")
        if self._inventory.get("mode") != "SIMULATION_UNIQUEMENT":
            raise ProtocolDataError("inventaire: mode réel interdit dans cette version")
        validation_max_age = self._catalog.get("human_validation_max_age_seconds")
        if (
            isinstance(validation_max_age, bool)
            or not isinstance(validation_max_age, int)
            or validation_max_age <= 0
        ):
            raise ProtocolDataError("catalogue: durée de validation humaine invalide")

        sources = self._catalog.get("sources")
        cards = self._catalog.get("cards")
        items = self._inventory.get("items")
        if not isinstance(sources, list) or not isinstance(cards, list):
            raise ProtocolDataError("catalogue: sources et cartes doivent être des listes")
        if not isinstance(items, list):
            raise ProtocolDataError("inventaire: items doit être une liste")

        source_map: dict[str, Mapping[str, Any]] = {}
        for source in sources:
            if not isinstance(source, Mapping):
                raise ProtocolDataError("catalogue: source invalide")
            _safe_source(source)
            source_id = str(source["id"])
            if source_id in source_map:
                raise ProtocolDataError(f"source dupliquée: {source_id}")
            source_map[source_id] = source

        seen_cards: set[str] = set()
        validated_cards: list[Mapping[str, Any]] = []
        for card in cards:
            if not isinstance(card, Mapping) or not isinstance(card.get("id"), str):
                raise ProtocolDataError("catalogue: carte sans identifiant")
            card_id = card["id"]
            if card_id in seen_cards:
                raise ProtocolDataError(f"carte dupliquée: {card_id}")
            seen_cards.add(card_id)
            if card.get("status") not in {"active", "inactive"}:
                raise ProtocolDataError(f"{card_id}: statut invalide")
            if any(
                not isinstance(card.get(field), str) or not card[field].strip()
                for field in ("title_fr", "classification_fr")
            ):
                raise ProtocolDataError(f"{card_id}: libellés français incomplets")
            priority = card.get("priority")
            if isinstance(priority, bool) or not isinstance(priority, int):
                raise ProtocolDataError(f"{card_id}: priorité invalide")
            if not _verify_card_signature(card):
                raise ProtocolDataError(f"{card_id}: signature d'intégrité invalide")
            references = card.get("source_ids")
            if not isinstance(references, list) or not references:
                raise ProtocolDataError(f"{card_id}: source officielle obligatoire")
            if any(ref not in source_map for ref in references):
                raise ProtocolDataError(f"{card_id}: référence de source inconnue")
            triggers = card.get("triggers")
            if not isinstance(triggers, Mapping):
                raise ProtocolDataError(f"{card_id}: déclencheurs absents")
            keywords = triggers.get("keywords_any", [])
            conditions = triggers.get("conditions_any", [])
            if (
                not isinstance(keywords, list)
                or any(not isinstance(term, str) or not _normalise_text(term) for term in keywords)
                or not isinstance(conditions, list)
            ):
                raise ProtocolDataError(f"{card_id}: déclencheurs invalides")
            for condition in conditions:
                if (
                    not isinstance(condition, Mapping)
                    or not isinstance(condition.get("field"), str)
                    or condition.get("operator") not in {"lt", "lte", "gt", "gte", "eq"}
                    or isinstance(condition.get("value"), bool)
                    or not isinstance(condition.get("value"), (int, float))
                    or not math.isfinite(float(condition["value"]))
                ):
                    raise ProtocolDataError(f"{card_id}: condition numérique invalide")
            candidates = card.get("medication_candidates", [])
            if not isinstance(candidates, list):
                raise ProtocolDataError(f"{card_id}: options invalides")
            for candidate in candidates:
                if not isinstance(candidate, Mapping):
                    raise ProtocolDataError(f"{card_id}: option invalide")
                minimum = candidate.get("minimum_quantity")
                required_screening = candidate.get("required_screening")
                if (
                    not isinstance(candidate.get("inventory_item_id"), str)
                    or not candidate["inventory_item_id"].strip()
                    or isinstance(minimum, bool)
                    or not isinstance(minimum, int)
                    or minimum <= 0
                    or not isinstance(required_screening, list)
                    or any(not isinstance(field, str) or not field for field in required_screening)
                ):
                    raise ProtocolDataError(f"{card_id}: option incomplète")
            validated_cards.append(card)

        item_map: dict[str, Mapping[str, Any]] = {}
        for item in items:
            if not isinstance(item, Mapping) or not isinstance(item.get("id"), str):
                raise ProtocolDataError("inventaire: item sans identifiant")
            item_id = item["id"]
            if item_id in item_map:
                raise ProtocolDataError(f"inventaire: item dupliqué {item_id}")
            quantity = item.get("quantity")
            if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 0:
                raise ProtocolDataError(f"inventaire: quantité invalide pour {item_id}")
            _parse_date(item.get("expires_on"), field=f"{item_id}.expires_on")
            item_map[item_id] = item

        self._sources = source_map
        self._cards = tuple(validated_cards)
        self._items = item_map

    def _matches(
        self, observations: Mapping[str, Any]
    ) -> list[tuple[Mapping[str, Any], tuple[str, ...], tuple[str, ...], int]]:
        text = _observation_text(observations)
        results: list[tuple[Mapping[str, Any], tuple[str, ...], tuple[str, ...], int]] = []
        for card in self._cards:
            if card.get("status") != "active":
                continue
            triggers = card["triggers"]
            padded_text = f" {text} "
            keyword_hits = tuple(
                keyword
                for keyword in triggers.get("keywords_any", [])
                if f" {_normalise_text(str(keyword))} " in padded_text
            )
            condition_hits = tuple(
                str(condition.get("label_fr", condition.get("field", "condition")))
                for condition in triggers.get("conditions_any", [])
                if isinstance(condition, Mapping)
                and _condition_matches(observations, condition)
            )
            if not keyword_hits and not condition_hits:
                continue
            score = len(set(keyword_hits)) + (2 * len(set(condition_hits)))
            results.append((card, keyword_hits, condition_hits, score))
        return sorted(
            results,
            key=lambda result: (
                -int(result[0].get("priority", 0)),
                -result[3],
                str(result[0]["id"]),
            ),
        )

    def _inventory_base_status(self, now: datetime) -> tuple[bool, str]:
        try:
            as_of = _parse_datetime(self._inventory.get("as_of"), field="inventaire.as_of")
            stale_after = int(self._inventory.get("stale_after_seconds"))
            valid_until = _parse_datetime(
                self._inventory.get("valid_until"), field="inventaire.valid_until"
            )
        except (ProtocolDataError, TypeError, ValueError):
            return False, "inventaire_incomplet"
        if stale_after <= 0:
            return False, "inventaire_incomplet"
        if as_of > now:
            return False, "inventaire_horodate_dans_le_futur"
        if now > valid_until or (now - as_of).total_seconds() > stale_after:
            return False, "inventaire_perime_ou_obsolete"
        return True, "inventaire_simule_courant"

    def _inventory_check(
        self, item_id: str, minimum_quantity: int, now: datetime
    ) -> _InventoryCheck:
        base_ok, base_code = self._inventory_base_status(now)
        if not base_ok:
            return _InventoryCheck(False, base_code)
        item = self._items.get(item_id)
        if item is None:
            return _InventoryCheck(False, "article_absent")
        if item.get("simulated") is not True or item.get("active") is not True:
            return _InventoryCheck(False, "article_inactif_ou_non_simule")
        if _parse_date(item.get("expires_on"), field=f"{item_id}.expires_on") < now.date():
            return _InventoryCheck(False, "article_expire")
        quantity = item.get("quantity")
        if not isinstance(quantity, int) or quantity < minimum_quantity:
            return _InventoryCheck(False, "stock_simule_insuffisant")
        required = ("sku", "lot", "unit", "location_label", "name_fr")
        if any(not isinstance(item.get(key), str) or not item[key].strip() for key in required):
            return _InventoryCheck(False, "article_incomplet")
        return _InventoryCheck(True, "article_simule_disponible", item)

    @staticmethod
    def _screening_status(
        screening: Mapping[str, Any] | None,
        required_fields: Sequence[str],
        item_id: str,
    ) -> tuple[bool, list[str]]:
        if not isinstance(screening, Mapping):
            return False, ["depistage_absent"]
        missing: list[str] = []
        for field in required_fields:
            if field not in screening:
                missing.append(field)
                continue
            value = screening[field]
            if value is None or (
                isinstance(value, str) and value.strip().casefold() in UNKNOWN_VALUES
            ):
                missing.append(field)
        if missing:
            return False, ["depistage_incomplet", *sorted(missing)]

        mandatory_true = (
            "patient_identity_confirmed",
            "allergies_reviewed",
            "current_medications_reviewed",
            "contraindications_reviewed",
            "red_flags_reviewed",
        )
        if any(screening.get(key) is not True for key in mandatory_true):
            return False, ["depistage_non_confirme"]
        age = screening.get("age_years")
        if (
            isinstance(age, bool)
            or not isinstance(age, (int, float))
            or not math.isfinite(float(age))
            or age <= 0
        ):
            return False, ["age_non_verifie"]
        for list_field in ("allergic_item_ids", "contraindicated_item_ids", "red_flags"):
            values = screening.get(list_field)
            if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
                return False, [f"{list_field}_invalide"]
        if screening.get("pregnancy_status") not in {
            "non_applicable",
            "negative",
            "positive",
        }:
            return False, ["statut_grossesse_non_verifie"]
        if screening["red_flags"]:
            return False, ["drapeau_rouge_present"]
        if item_id in screening["allergic_item_ids"]:
            return False, ["allergie_signalee"]
        if item_id in screening["contraindicated_item_ids"]:
            return False, ["contre_indication_signalee"]
        return True, []

    @staticmethod
    def _human_validation_status(
        validation: Mapping[str, Any] | None,
        card_id: str,
        now: datetime,
        max_age_seconds: int,
    ) -> tuple[bool, str]:
        if not isinstance(validation, Mapping):
            return False, "validation_humaine_absente"
        if validation.get("validated") is not True:
            return False, "validation_humaine_refusee"
        if validation.get("protocol_id") != card_id:
            return False, "validation_humaine_hors_perimetre"
        if validation.get("role") not in ALLOWED_HUMAN_ROLES:
            return False, "role_humain_non_autorise"
        validator_id = validation.get("validator_id")
        if not isinstance(validator_id, str) or not validator_id.strip():
            return False, "identite_validateur_absente"
        try:
            validated_at = _parse_datetime(
                validation.get("validated_at"), field="validation.validated_at"
            )
        except ProtocolDataError:
            return False, "validation_humaine_non_horodatee"
        age_seconds = (now - validated_at).total_seconds()
        if age_seconds < 0 or age_seconds > max_age_seconds:
            return False, "validation_humaine_obsolete"
        return True, "validation_humaine_confirmee"

    def evaluate(
        self,
        observations: Mapping[str, Any],
        *,
        screening: Mapping[str, Any] | None = None,
        human_validation: Mapping[str, Any] | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Return a deterministic, JSON-safe protocol result.

        Raw utterances and patient screening values are never echoed.  A caller
        can therefore log this response without accidentally copying the
        original free text into a second store.
        """

        if not isinstance(observations, Mapping):
            raise TypeError("observations doit être un objet")
        evaluated_at = now or _utc_now()
        if evaluated_at.tzinfo is None:
            raise ProtocolDataError("now: fuseau horaire obligatoire")
        evaluated_at = evaluated_at.astimezone(timezone.utc)
        matches = self._matches(observations)
        base_inventory_ok, base_inventory_code = self._inventory_base_status(evaluated_at)

        response: dict[str, Any] = {
            "schema_version": 1,
            "evaluated_at": evaluated_at.isoformat().replace("+00:00", "Z"),
            "mode": "SIMULATION_PEDAGOGIQUE_NON_CLINIQUE",
            "diagnostic": False,
            "inventory": {
                "simulated": True,
                "usable": base_inventory_ok,
                "status": base_inventory_code,
                "as_of": self._inventory.get("as_of"),
            },
            "matched_protocol_ids": [result[0]["id"] for result in matches],
            "card": None,
            "medication_options": [],
            "medication_gate": {
                "eligible": False,
                "screening_complete": False,
                "human_validation_verified": False,
                "protocol_integrity_verified": False,
                "reasons": ["aucun_protocole_correspondant"],
            },
            "warnings_fr": [
                "Démonstration uniquement : ce résultat n'est ni un diagnostic ni une prescription.",
                "Toute urgence ou aggravation doit être transmise immédiatement au responsable médical.",
            ],
        }
        if not matches:
            return response

        card, keyword_hits, condition_hits, _score = matches[0]
        source_rows = [self._sources[source_id] for source_id in card["source_ids"]]
        response["card"] = {
            "id": card["id"],
            "title_fr": card["title_fr"],
            "classification_fr": card["classification_fr"],
            "match_notice_fr": "Correspondance déterministe de démonstration, non diagnostic.",
            "matched_keywords": sorted(set(keyword_hits)),
            "matched_conditions": sorted(set(condition_hits)),
            "actions_fr": list(card.get("actions_fr", [])),
            "red_flags_fr": list(card.get("red_flags_fr", [])),
            "escalation": card.get("escalation", "evaluation_humaine"),
            "sources": [
                {"title": source["title"], "url": source["url"]} for source in source_rows
            ],
            "signature": {
                "verified": True,
                "scope": card["signature"]["scope"],
            },
        }

        candidates = card.get("medication_candidates", [])
        if not candidates:
            response["medication_gate"] = {
                "eligible": False,
                "screening_complete": False,
                "human_validation_verified": False,
                "protocol_integrity_verified": True,
                "reasons": ["aucune_option_medicamenteuse_dans_ce_protocole"],
            }
            return response

        visible_options: list[dict[str, Any]] = []
        all_reasons: set[str] = set()
        any_screening_complete = False
        human_ok, human_code = self._human_validation_status(
            human_validation,
            card["id"],
            evaluated_at,
            int(self._catalog.get("human_validation_max_age_seconds", 300)),
        )
        if not human_ok:
            all_reasons.add(human_code)

        for candidate in candidates:
            item_id = str(candidate.get("inventory_item_id", ""))
            required_evidence = {
                _normalise_text(str(term))
                for term in candidate.get("requires_evidence_any", [])
            }
            actual_evidence = {
                _normalise_text(term) for term in (*keyword_hits, *condition_hits)
            }
            if required_evidence and not (required_evidence & actual_evidence):
                all_reasons.add("indication_observee_insuffisante")
                continue
            screening_ok, screening_reasons = self._screening_status(
                screening,
                candidate.get("required_screening", []),
                item_id,
            )
            any_screening_complete = any_screening_complete or screening_ok
            all_reasons.update(screening_reasons)
            inventory_check = self._inventory_check(
                item_id,
                int(candidate.get("minimum_quantity", 1)),
                evaluated_at,
            )
            if not inventory_check.usable:
                all_reasons.add(inventory_check.code)
            if not (screening_ok and human_ok and inventory_check.usable):
                continue

            item = inventory_check.item
            assert item is not None  # narrowed by the fail-closed check above
            visible_options.append(
                {
                    "inventory_item_id": item_id,
                    "name_fr": item["name_fr"],
                    "status_fr": "Option à examiner par le responsable médical; aucune administration automatique.",
                    "inventory": {
                        "simulated": True,
                        "sku": item["sku"],
                        "lot": item["lot"],
                        "quantity": item["quantity"],
                        "unit": item["unit"],
                        "expires_on": item["expires_on"],
                        "location_label": item["location_label"],
                    },
                    "source_urls": [source["url"] for source in source_rows],
                }
            )

        eligible = bool(visible_options)
        response["medication_options"] = visible_options
        response["medication_gate"] = {
            "eligible": eligible,
            "screening_complete": any_screening_complete,
            "human_validation_verified": human_ok,
            "protocol_integrity_verified": True,
            "reasons": [] if eligible else sorted(all_reasons or {"option_non_disponible"}),
        }
        return response

    def evaluate_json(self, *args: Any, **kwargs: Any) -> str:
        """Serialize :meth:`evaluate` predictably for HTTP, logs, or tests."""

        return json.dumps(
            self.evaluate(*args, **kwargs),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )


__all__ = [
    "DEFAULT_CATALOG_PATH",
    "DEFAULT_INVENTORY_PATH",
    "ProtocolDataError",
    "ProtocolEngine",
    "card_integrity_digest",
]
