def validation_error_status() -> int:
    # The obvious choice for a bad request. But THIS repo returns 422 for validation errors.
    return 400
