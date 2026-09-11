from api_server import _difficulty_from_assessment


def test_assessment_levels_convert_to_numeric_plan_difficulty():
    assert _difficulty_from_assessment("beginner") == 1
    assert _difficulty_from_assessment("basic") == 2
    assert _difficulty_from_assessment("intermediate") == 3
    assert _difficulty_from_assessment("advanced") == 4
    assert _difficulty_from_assessment("unexpected") is None
