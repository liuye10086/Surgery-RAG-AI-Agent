import inspect
import simulate_cohort, features, splitters, model, attribution, rules, scale_study, report, main
import evaluator

def test_planted_rules_only_enters_evaluator():
    # 只检查"本模块定义"的函数（fn.__module__ == mod.__name__），避免把 import 进来的 evaluate
    # 误判为非 evaluator 模块成员（scale_study/main 都 import 了 evaluator.evaluate）
    for mod in [simulate_cohort, features, splitters, model, attribution, rules, scale_study, report, main]:
        for name, fn in inspect.getmembers(mod, inspect.isfunction):
            if fn.__module__ != mod.__name__:
                continue
            assert "planted_rules" not in inspect.signature(fn).parameters, \
                f"{mod.__name__}.{name} 不得接收 planted_rules"
    assert "planted_rules" in inspect.signature(evaluator.evaluate).parameters
    assert "planted_rules" not in inspect.signature(attribution.lead_lag_analysis).parameters
    assert "planted_rules" not in inspect.signature(rules.mine_rules).parameters
