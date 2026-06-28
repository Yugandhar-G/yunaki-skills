from status import validation_error_status


def test_validation_errors_use_422_not_400():
    assert validation_error_status() == 422
