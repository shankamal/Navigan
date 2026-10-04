from scripts.seed_dev_customers_data_api import SAMPLES, VALID_STATUSES, validate_samples


def test_seed_samples_are_safe_and_representative():
    validate_samples()
    assert len(SAMPLES) == 16
    assert {sample.status for sample in SAMPLES} == VALID_STATUSES
    assert sum(sample.status == "ACTIVE" for sample in SAMPLES) == 4
    assert all("AWS" in sample.providers for sample in SAMPLES)
