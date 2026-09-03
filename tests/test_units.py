def mgdl_to_mmoll(value):
    return round(float(value) / 18.0, 3)

def test_glucose_conversion():
    assert mgdl_to_mmoll(180) == 10.0
    assert mgdl_to_mmoll(90) == 5.0
