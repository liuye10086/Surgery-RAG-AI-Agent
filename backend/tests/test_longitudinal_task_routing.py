import pytest


@pytest.mark.parametrize(
    ("stage", "task"),
    [
        ("pre_cirrhosis", "fatty_liver.pre_cirrhosis_to_progression"),
        ("未肝硬化", "fatty_liver.pre_cirrhosis_to_progression"),
        ("cirrhosis", "fatty_liver.cirrhosis_to_hcc"),
        ("肝硬化", "fatty_liver.cirrhosis_to_hcc"),
    ],
)
def test_fatty_liver_routes_by_confirmed_baseline(stage, task):
    from app.services.longitudinal_task_routing import route_outcome_task

    result = route_outcome_task("fatty_liver", stage)
    assert result.routing_status == "selected"
    assert result.task == task
    assert result.reason_code == "task_selected"


def test_suspected_cirrhosis_is_recognized_but_not_guessed():
    from app.services.longitudinal_task_routing import route_outcome_task

    result = route_outcome_task("fatty_liver", "疑似肝硬化")
    assert result.routing_status == "not_estimable"
    assert result.normalized_stage == "suspected_cirrhosis"
    assert result.reason_code == "baseline_stage_uncertain"
    assert result.task is None


@pytest.mark.parametrize(
    "stage", ["normal", "mci", "pre_dementia", "认知正常", "轻度认知障碍"]
)
def test_ad_pre_dementia_stages_route_to_one_task(stage):
    from app.services.longitudinal_task_routing import route_outcome_task

    assert route_outcome_task("ad", stage).task == "ad.pre_dementia_to_dementia"


@pytest.mark.parametrize(
    ("dataset", "stage", "reason"),
    [
        ("fatty_liver", None, "baseline_stage_missing"),
        ("fatty_liver", "S1", "baseline_stage_unknown"),
        ("fatty_liver", "hcc", "task_not_applicable_terminal_stage"),
        ("ad", "dementia", "task_not_applicable_terminal_stage"),
        ("ad", "肝硬化", "baseline_stage_disease_conflict"),
        ("fatty_liver", "未肝硬化/肝硬化", "baseline_stage_conflict"),
    ],
)
def test_non_routable_baselines_have_stable_reasons(dataset, stage, reason):
    from app.services.longitudinal_task_routing import route_outcome_task

    result = route_outcome_task(dataset, stage)
    assert result.routing_status == "not_estimable"
    assert result.reason_code == reason
    assert result.task is None


def test_normalization_is_explicit_and_does_not_use_substring_guessing():
    from app.services.longitudinal_task_routing import normalize_baseline_stage

    assert normalize_baseline_stage("fatty_liver", "可能接近肝硬化").reason_code == "baseline_stage_unknown"
    assert normalize_baseline_stage("ad", "CDR 0.5").reason_code == "baseline_stage_unknown"


def test_unknown_dataset_is_not_estimable_without_echoing_raw_stage():
    from app.services.longitudinal_task_routing import route_outcome_task

    result = route_outcome_task("unknown", "private patient note")
    assert result.reason_code == "dataset_unsupported"
    assert result.normalized_stage is None
