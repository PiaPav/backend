class HarnessError(Exception):
    def __init__(self, message: str, details: dict | None = None, *args, **kwargs):
        self.error = {"message": message, "details": details}
        super().__init__(message)

    @property
    def name(self) -> str:
        return self.__class__.__name__

    def __str__(self):
        return f"{self.name}: {self.error}"


class InvalidHarnessInput(HarnessError):
    """Permanent public input error for which redelivery cannot help."""


__all__ = ["HarnessError", "InvalidHarnessInput"]
