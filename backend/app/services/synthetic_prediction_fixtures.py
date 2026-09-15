"""Fixed synthetic counterexamples; offline expectations are literal test oracles.

The current API request deliberately omits disease_id, which belongs to the
isolated consumer's local disease catalog. Future observations stay separate.
"""

from __future__ import annotations

from copy import deepcopy


SOURCE = {
    "is_synthetic": True,
    "source_kind": "synthetic",
    "generator_version": "synthetic-prediction.v1",
}


def build_fixed_fixtures() -> tuple[list[dict], list[dict]]:
    fixtures: list[dict] = []
    expected: list[dict] = []

    for disease, indicator, unit, stage, anchor_value in (
        ("ad", "mmse", "分", "mci", 22),
        ("fatty_liver", "alt", "U/L", "pre_cirrhosis", 60),
    ):
        history_value = 24 if disease == "ad" else 63
        targets = (21, 19) if disease == "ad" else (55, 70)

        def add(scenario: int, variant: str = "base", *, history=None, anchor=None,
                followups=None, api=True, stage_override=None, diagnosis="confirmed",
                coverage="complete", extra_patients=None, offline=None,
                values=None, counts=None, api_status="accept", api_reason=None,
                request_visits=None):
            key = f"S{scenario:02d}"
            fixture_id = f"{key}-{disease}-{variant}"
            subject = f"syn-{key}-{disease}"
            group = f"group-{key}-{disease}"
            patient = {
                "subject_id": subject, "dependency_group_id": group,
                "disease": disease, "age": 68, "sex": "female",
                "baseline_stage": stage_override or stage,
                "diagnosis_status": diagnosis, "anchor_date": (anchor or ("2024-01-31", anchor_value))[0],
                "diagnosis_known_on": (anchor or ("2024-01-31", anchor_value))[0] if diagnosis != "unknown" else None,
                "history_coverage": coverage, "source": dict(SOURCE),
            }
            observations = []

            def observation(entry, role, index):
                day, value, *options = entry
                options = options[0] if options else {}
                horizon = options.get("horizon_months", {"history": None, "anchor": None, "followup": 6 if index == 0 else 12}[role])
                status = options.get("status", "observed")
                return {
                    "observation_id": f"{key}-{disease}-{role}-{index}",
                    "subject_id": options.get("subject_id", subject),
                    "indicator": indicator, "measured_on": day,
                    "known_on": options.get("known_on", day if status == "observed" else None),
                    "value": value, "unit": options.get("unit", unit),
                    "method": options.get("method", "synthetic_fixture"),
                    "observation_kind": options.get("kind", "actual"), "role": role,
                    "horizon_months": horizon, "observation_status": status,
                    "source": dict(SOURCE),
                }

            for index, entry in enumerate(history if history is not None else [("2023-07-31", history_value)]):
                observations.append(observation(entry, "history", index))
            observations.append(observation(anchor or ("2024-01-31", anchor_value), "anchor", 0))
            for index, entry in enumerate(followups if followups is not None else [
                ("2024-07-31", targets[0]), ("2025-01-31", targets[1])
            ]):
                observations.append(observation(entry, "followup", index))

            patients = [patient, *(extra_patients or [])]
            visits = []
            for obs in observations:
                if (obs["role"] == "followup" or obs["observation_kind"] == "planned"
                        or not obs["known_on"] or obs["known_on"] > patient["anchor_date"]):
                    continue
                visits.append({
                    "visit_date": obs["measured_on"],
                    "indicators": [{"name": obs["indicator"], "value": obs["value"], "unit": obs["unit"]}],
                    "visit_context": {"method": obs["method"], "is_baseline": obs["role"] == "anchor"},
                })
            request = ({"age": patient["age"], "sex": patient["sex"],
                        "baseline_stage": patient["baseline_stage"],
                        "notes": "合成软件验收样例；非真实患者资料。",
                        "visits": request_visits if request_visits is not None else visits} if api else None)
            if scenario == 18 and variant == "source_copy":
                # Two source rows refer to one original observation, not two measurements.
                observations.append(deepcopy(observations[0]))
            if scenario == 18 and variant == "related":
                sibling_observation = deepcopy(observations[1])
                sibling_observation["observation_id"] = f"{fixture_id}-sibling-anchor"
                sibling_observation["subject_id"] = patients[1]["subject_id"]
                sibling_observation["value"] = anchor_value - 1 if disease == "ad" else anchor_value + 3
                observations.append(sibling_observation)
            fixtures.append({"fixture_id": fixture_id, "scenario_id": key,
                             "disease": disease, "variant": variant,
                             "patients": patients, "observations": observations,
                             "api_request": request})
            expected.append({"fixture_id": fixture_id,
                             "current_api": {"status": api_status if api else "not_run", "reason": api_reason},
                             "offline": offline or {"6m": "fixture_observed_at_nominal", "12m": "fixture_observed_at_nominal"},
                             "expected_values": values or {}, "expected_counts": counts or {}})

        add(1, history=[("2023-01-31", 25 if disease == "ad" else 58),
                        ("2023-07-31", history_value)],
            values={"anchor": anchor_value, "targets": list(targets),
                    "baseline_absolute_errors": [1, 3] if disease == "ad" else [5, 10],
                    "target_dates": ["2024-07-31", "2025-01-31"]})
        add(1, "irregular", history=[("2023-03-03", 25 if disease == "ad" else 58),
                                       ("2023-11-14", history_value)])
        add(2, history=[], offline={"6m": "fixture_observed_at_nominal", "12m": "fixture_observed_at_nominal",
                                      "d03_history_count": 0, "d03_history_span_days": 0,
                                      "history_trend": "not_applicable", "old_report": "insufficient_visits"})
        add(3, history=[], coverage="unknown", offline={"6m": "fixture_observed_at_nominal",
                    "12m": "fixture_observed_at_nominal", "d03_history_count": None,
                    "d03_history_span_days": None, "history_trend": "not_applicable"})
        add(4, history=[("2023-07-31", history_value)],
            offline={"history_trend": "eligible", "old_report": "insufficient_visits",
                     "6m": "fixture_observed_at_nominal", "12m": "fixture_observed_at_nominal"},
            values={"history_interval_days": 184})
        add(5, "null_anchor", anchor=("2024-01-31", None), api_status="reject",
            api_reason="indicator_value_missing", offline={"6m": "ineligible_anchor", "12m": "ineligible_anchor"})
        add(5, "nonfinite_anchor", anchor=("2024-01-31", "NaN"), api_status="reject",
            api_reason="schema_nonfinite_value", offline={"6m": "ineligible_anchor", "12m": "ineligible_anchor"})
        add(6, followups=[("2024-07-31", None, {"status": "confirmed_unobserved"}),
                          ("2025-01-31", targets[1])],
            offline={"6m": "confirmed_unobserved", "12m": "fixture_observed_at_nominal",
                     "prediction_eligibility": "eligible"})
        add(7, followups=[("2024-07-31", None, {"status": "pending_observation", "kind": "planned"}),
                          ("2025-01-31", targets[1])],
            offline={"6m": "pending_observation", "12m": "fixture_observed_at_nominal",
                     "prediction_eligibility": "eligible"})
        add(8, "early", followups=[("2024-07-24", targets[0]), ("2025-01-31", targets[1])],
            offline={"6m": "pending_window", "12m": "fixture_observed_at_nominal"},
            values={"6m_target_date": "2024-07-31", "6m_offset_days": -7})
        add(8, "late", followups=[("2024-08-21", targets[0]), ("2025-01-31", targets[1])],
            offline={"6m": "pending_window", "12m": "fixture_observed_at_nominal"},
            values={"6m_target_date": "2024-07-31", "6m_offset_days": 21})
        add(8, "leap_day", anchor=("2024-02-29", anchor_value), history=[],
            followups=[("2024-08-29", targets[0]), ("2025-02-28", targets[1])],
            values={"6m_target_date": "2024-08-29", "12m_target_date": "2025-02-28"})
        add(9, history=[("2023-01-31", history_value, {"method": "synthetic_fixture_earlier"})],
            request_visits=[
                {"visit_date": "2024-01-31", "indicators": [{"name": indicator, "value": anchor_value, "unit": unit}], "visit_context": {"method": "synthetic_fixture_anchor"}},
                {"visit_date": "2023-01-31", "indicators": [{"name": indicator, "value": history_value, "unit": unit}], "visit_context": {"method": "synthetic_fixture_earlier"}},
            ], offline={"normalization": "date_sorted_context_preserved", "input_identity": "order_invariant"})
        add(10, "duplicate_day", history=[("2024-01-31", history_value)],
            api_status="reject", api_reason="duplicate_visit_date", offline={"conflict": "preserve_no_averaging"})
        add(10, "duplicate_indicator", request_visits=[{"visit_date": "2024-01-31",
            "indicators": [{"name": indicator, "value": anchor_value, "unit": unit},
                           {"name": indicator, "value": history_value, "unit": unit}]}],
            api_status="reject", api_reason="invalid_indicators", offline={"conflict": "preserve_no_averaging"})
        add(11, "late_known", history=[("2023-07-31", history_value, {"known_on": "2024-02-07"})],
            coverage="unknown", offline={"usable_history_count": 0, "d03_history_count": None,
                     "6m": "fixture_observed_at_nominal", "12m": "fixture_observed_at_nominal"})
        add(11, "unknown_known", history=[("2023-07-31", history_value, {"known_on": None})],
            coverage="unknown", offline={"usable_history_count": 0, "d03_history_count": None,
                     "6m": "fixture_observed_at_nominal", "12m": "fixture_observed_at_nominal"})
        add(12, history=[("2023-07-31", history_value)],
            offline={"input_equivalent_to": f"S12-{disease}-future_changed"})
        add(12, "future_changed", history=[("2023-07-31", history_value)],
            followups=[("2024-07-31", targets[0] - 1 if disease == "ad" else targets[0] + 8),
                       ("2025-01-31", targets[1]),
                       ("2025-04-30", None, {"kind": "planned", "status": "pending_observation", "horizon_months": 12, "method": "future_treatment_planned"})],
            offline={"input_equivalent_to": f"S12-{disease}-base",
                     "allowed_changes": ["future_value", "future_treatment", "extra_future_visit"],
                     "12m_input": "unchanged"})
        add(13, anchor=("2024-01-31", anchor_value, {"unit": ""}),
            api_status="reject", api_reason="schema_missing_unit", offline={"anchor_unit": "missing"})
        add(14, "unsupported_unit", anchor=("2024-01-31", anchor_value, {"unit": "mg/dL"}),
            api_status="reject", api_reason="invalid_indicators", offline={"unit": "incomparable"})
        add(14, "approved_alias", anchor=("2024-01-31", anchor_value, {"unit": "u/l" if disease == "fatty_liver" else " 分 "}),
            offline={"unit": "normalized_to_canonical"}, values={"canonical_unit": unit})
        for boundary in ((0, 30) if disease == "ad" else (0,)):
            add(15, f"boundary_{boundary}", anchor=("2024-01-31", boundary),
                values={"accepted_anchor": boundary})
        for invalid in ((-1, 31) if disease == "ad" else (-1,)):
            add(16, f"out_of_range_{invalid}", anchor=("2024-01-31", invalid),
                api_status="reject", api_reason="invalid_indicators", offline={"anchor": "ineligible"})
        add(17, "method_unknown", followups=[("2024-07-31", targets[0], {"method": None}),
                                                    ("2025-01-31", targets[1])],
            offline={"6m": "pending_comparability", "12m": "fixture_observed_at_nominal"})
        add(17, "method_incompatible", followups=[("2024-07-31", targets[0], {"method": "confirmed_incompatible_method"}),
                                                         ("2025-01-31", targets[1])],
            offline={"6m": "incomparable", "12m": "fixture_observed_at_nominal"})
        add(18, "base", counts={"patients": 1, "source_records": 1, "dependency_groups": 1})
        add(18, "source_copy", counts={"patients": 1, "source_records": 2, "dependency_groups": 1},
            offline={"deduplicated_patient_count": 1, "deduplicated_measurement_count": 4})
        sibling = {"subject_id": f"syn-S18-{disease}-sibling", "dependency_group_id": f"group-S18-{disease}",
                   "disease": disease, "age": 71, "sex": "male", "baseline_stage": stage,
                   "diagnosis_status": "confirmed", "anchor_date": "2024-01-31",
                   "diagnosis_known_on": "2024-01-31", "history_coverage": "complete", "source": dict(SOURCE)}
        add(18, "related", extra_patients=[sibling], counts={"patients": 2, "source_records": 2, "dependency_groups": 1})
        add(19, stage_override="dementia" if disease == "ad" else "cirrhosis",
            offline={"new_task": "eligible", "old_route": "task_not_applicable_terminal_stage" if disease == "ad" else "explicit_stage"})
        add(20, "diagnosis_unknown", diagnosis="unknown", offline={"population": "pending"})
        add(20, "diagnosis_excluded", diagnosis="excluded", offline={"population": "excluded"})

    return fixtures, expected
