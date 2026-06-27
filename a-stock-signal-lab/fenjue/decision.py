from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any
from uuid import uuid4

from .execution import FillAssessment
from .ledger import RiskPrecheck
from .v2db import FenjueV2Database


@dataclass(frozen=True)
class DecisionContext:
    decision_id: str | None
    decision_at_ms: int
    account_id: str
    code: str
    logic_cluster_id: str
    user_intent: str
    requested_action: str
    position_mode: str
    position_snapshot_id: str
    feature_snapshot_id: str
    data_manifest_id: str
    exchange_status: str
    event_freezes: list[dict[str, Any]]
    logic_gate: dict[str, Any]
    market_regime: str
    market_features: dict[str, Any] | None
    market_microstructure: dict[str, Any] | None
    execution: FillAssessment | None
    risk_precheck: RiskPrecheck | None
    probability_status: str
    source_selection_policy_version: str
    context_contract_version: str = "fenjue-context-v2"
    model_version: str = "fenjue-family-v2"
    policy_version: str = "fenjue-policy-v2"
    estimated_probability_ratio: float | None = None


@dataclass(frozen=True)
class DecisionResult:
    decision_id: str
    strategy_family: str
    action: str
    reason_codes: tuple[str, ...]
    max_incremental_exposure_ratio: float | None
    probability_ratio: float | None
    confidence: str
    next_checkpoint_ms: int | None


class DecisionEngine:
    def __init__(self, db: FenjueV2Database):
        self.db = db

    @staticmethod
    def _select_family(context: DecisionContext) -> str:
        if context.position_mode == "RISK":
            return "RISK"
        if context.requested_action in {"ADD", "NEW_ENTRY"}:
            return "NEW_ENTRY"
        if context.requested_action in {"TACTICAL_BUY", "TACTICAL_SELL"}:
            return "TACTICAL_T"
        if context.position_mode == "CORE_HOLD":
            return "CORE_HOLD"
        return "OBSERVE"

    @staticmethod
    def _input_complete(context: DecisionContext) -> bool:
        required_strings = (
            context.account_id,
            context.code,
            context.logic_cluster_id,
            context.user_intent,
            context.requested_action,
            context.position_mode,
            context.position_snapshot_id,
            context.feature_snapshot_id,
            context.data_manifest_id,
            context.exchange_status,
            context.market_regime,
            context.probability_status,
            context.source_selection_policy_version,
        )
        return bool(
            all(required_strings)
            and context.market_features is not None
            and context.market_microstructure is not None
            and context.logic_gate is not None
        )

    @staticmethod
    def _freeze_blocks(context: DecisionContext) -> bool:
        requested_scope = {
            "ADD": "add",
            "NEW_ENTRY": "new_entry",
            "TACTICAL_BUY": "tactical_t",
            "TACTICAL_SELL": "tactical_t",
        }.get(context.requested_action)
        return any(
            freeze.get("freeze_scope") in {"all_scoring", requested_scope}
            for freeze in context.event_freezes
        )

    def decide(self, context: DecisionContext) -> DecisionResult:
        decision_id = context.decision_id or f"decision-{uuid4().hex}"
        next_checkpoint_ms = context.decision_at_ms + 30 * 60 * 1000

        if not self._input_complete(context):
            return self._persist(
                context, decision_id, "OBSERVE", "OBSERVE",
                ("INPUT_CONTRACT_INCOMPLETE",), None, None, "LOW",
                next_checkpoint_ms,
            )
        if context.exchange_status == "SUSPENDED":
            return self._persist(
                context, decision_id, "RISK", "NOT_TRADABLE",
                ("NOT_TRADABLE_SUSPENDED",), None, None, "HIGH", None,
            )
        if self._freeze_blocks(context):
            return self._persist(
                context, decision_id, "RISK", "RISK_REVIEW",
                ("EVENT_FREEZE_ACTIVE",), None, None, "HIGH",
                next_checkpoint_ms,
            )

        family = self._select_family(context)
        if context.logic_gate.get("logic_invalidated"):
            return self._persist(
                context, decision_id, "RISK", "RISK_REVIEW",
                ("LOGIC_INVALIDATED",), None, None, "HIGH",
                next_checkpoint_ms,
            )
        if family == "NEW_ENTRY" and not context.logic_gate.get(
            "eligible_for_new_entry", False
        ):
            return self._persist(
                context, decision_id, family, "REJECT",
                ("LOGIC_GATE_REJECTED",), None, None, "MEDIUM",
                next_checkpoint_ms,
            )
        if family == "CORE_HOLD" and not context.logic_gate.get(
            "eligible_for_core_hold", False
        ):
            return self._persist(
                context, decision_id, "RISK", "RISK_REVIEW",
                ("CORE_LOGIC_NOT_ELIGIBLE",), None, None, "MEDIUM",
                next_checkpoint_ms,
            )

        if family == "CORE_HOLD" and context.requested_action == "HOLD":
            action = (
                "HOLD_CORE_NO_ADD"
                if context.market_regime == "RETREAT"
                else "HOLD_CORE"
            )
            reasons = (
                ("THESIS_NOT_INVALIDATED", "MARKET_RETREAT")
                if context.market_regime == "RETREAT"
                else ("THESIS_NOT_INVALIDATED",)
            )
            return self._persist(
                context, decision_id, family, action, reasons, 0.0, None,
                "MEDIUM", next_checkpoint_ms,
            )

        if family == "NEW_ENTRY" and context.market_regime == "RETREAT":
            return self._persist(
                context, decision_id, family, "REJECT",
                ("MARKET_RETREAT",), None, None, "HIGH",
                next_checkpoint_ms,
            )

        if family in {"NEW_ENTRY", "TACTICAL_T"}:
            if context.risk_precheck is None or not context.risk_precheck.max_incremental_exposure_ratio:
                return self._persist(
                    context, decision_id, family, "REJECT",
                    ("RISK_BUDGET_ZERO",), None, None, "HIGH",
                    next_checkpoint_ms,
                )
            if context.execution is None or context.execution.fill_status != "fillable":
                reason = (
                    context.execution.reason_code
                    if context.execution else "EXECUTION_DATA_MISSING"
                )
                return self._persist(
                    context, decision_id, family, "REJECT",
                    (reason,), None, None, "HIGH", next_checkpoint_ms,
                )
            if context.probability_status != "probability_ready":
                return self._persist(
                    context, decision_id, family, "REJECT",
                    ("PROBABILITY_NOT_READY",), None, None, "MEDIUM",
                    next_checkpoint_ms,
                )
            action = (
                "ALLOW_NEW_ENTRY_RESEARCH"
                if family == "NEW_ENTRY"
                else f"ALLOW_{context.requested_action}_RESEARCH"
            )
            probability = context.estimated_probability_ratio
            confidence = "MEDIUM" if context.execution.data_quality == "C" else "HIGH"
            return self._persist(
                context, decision_id, family, action, ("ALL_GATES_PASSED",),
                context.risk_precheck.max_incremental_exposure_ratio,
                probability, confidence, next_checkpoint_ms,
            )

        return self._persist(
            context, decision_id, "OBSERVE", "OBSERVE",
            ("NO_ACTIONABLE_STRATEGY_FAMILY",), None, None, "LOW",
            next_checkpoint_ms,
        )

    def _persist(
        self,
        context: DecisionContext,
        decision_id: str,
        family: str,
        action: str,
        reasons: tuple[str, ...],
        max_exposure_ratio: float | None,
        probability_ratio: float | None,
        confidence: str,
        next_checkpoint_ms: int | None,
    ) -> DecisionResult:
        human_reason = "; ".join(reasons)
        with self.db.transaction() as connection:
            connection.execute(
                """
                INSERT INTO decision_snapshots
                    (decision_id,code,account_id,logic_cluster_id,strategy_family,
                     requested_action,exchange_status,decision_at_ms,feature_snapshot_id,
                     position_snapshot_id,data_manifest_id,context_contract_version,
                     model_version,policy_version,probability_status,action,
                     reason_codes_json,human_readable_reason,next_checkpoint_ms,created_at_ms)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    decision_id, context.code, context.account_id,
                    context.logic_cluster_id, family, context.requested_action,
                    context.exchange_status, context.decision_at_ms,
                    context.feature_snapshot_id, context.position_snapshot_id,
                    context.data_manifest_id, context.context_contract_version,
                    context.model_version, context.policy_version,
                    context.probability_status, action, json.dumps(reasons),
                    human_reason, next_checkpoint_ms, context.decision_at_ms,
                ),
            )
            score_name = {
                "CORE_HOLD": "core_hold_score",
                "TACTICAL_T": "tactical_t_score",
                "NEW_ENTRY": "new_entry_score",
                "RISK": "risk_freeze_score",
                "OBSERVE": "no_trade_score",
            }[family]
            connection.execute(
                """
                INSERT INTO strategy_family_scores
                    (decision_id,logic_cluster_id,strategy_family,score_name,
                     score_value,score_status,model_version,feature_snapshot_id,
                     reason_codes_json,calculated_at_ms)
                VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    decision_id, context.logic_cluster_id, family, score_name,
                    100.0 if action in {"REJECT", "RISK_REVIEW", "OBSERVE"} else None,
                    "blocked" if action == "REJECT" else "valid",
                    context.model_version, context.feature_snapshot_id,
                    json.dumps(reasons), context.decision_at_ms,
                ),
            )
            if action == "REJECT":
                for reason in reasons:
                    connection.execute(
                        """
                        INSERT INTO rejection_audits
                            (rejection_id,decision_id,logic_cluster_id,strategy_family,
                             requested_action,rejected_action,gate_name,reason_code,
                             evidence_snapshot_ids_json,next_checkpoint_ms,
                             policy_version,created_at_ms)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            f"rejection-{uuid4().hex}", decision_id,
                            context.logic_cluster_id, family, context.requested_action,
                            action, self._gate_for_reason(reason), reason,
                            json.dumps([
                                context.position_snapshot_id,
                                context.feature_snapshot_id,
                            ]),
                            next_checkpoint_ms, context.policy_version,
                            context.decision_at_ms,
                        ),
                    )
        return DecisionResult(
            decision_id, family, action, reasons, max_exposure_ratio,
            probability_ratio, confidence, next_checkpoint_ms,
        )

    @staticmethod
    def _gate_for_reason(reason: str) -> str:
        if reason.startswith("MARKET_"):
            return "market_gate"
        if reason.startswith("RISK_"):
            return "risk_budget_gate"
        if reason.startswith("PROBABILITY_"):
            return "probability_release_gate"
        if reason.startswith("LOGIC_"):
            return "logic_gate"
        return "execution_or_contract_gate"
