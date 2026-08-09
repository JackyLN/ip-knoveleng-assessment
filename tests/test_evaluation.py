from evaluation.run import load_scenarios, run_evaluation


def test_evaluation_scenarios_pass() -> None:
    scenarios = load_scenarios()
    assert len(scenarios) >= 5
    results = run_evaluation()
    assert all(result.passed for result in results)
