"""Domain errors shared by the API and the CLI."""


class InventoryError(Exception):
    """A rejected inventory operation with a stable machine code."""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        details: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


def exit_code_for(error: InventoryError) -> int:
    """Map a domain error to a CLI exit code.

    2 usage/validation, 3 not found, 4 ambiguous, 5 conflict, 1 anything else.
    """

    if error.code == "ambiguous":
        return 4
    if error.code == "not_found" or error.status_code == 404:
        return 3
    if error.code == "validation_error" or error.status_code == 422:
        return 2
    if error.status_code == 409 or error.code in {
        "negative_stock",
        "conflict",
        "not_empty",
        "history_exists",
        "archived",
    }:
        return 5
    return 1
