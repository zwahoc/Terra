"""Framework-independent errors shared by intake repositories and services."""


class IngestionError(RuntimeError):
    def __init__(self, code: str, message: str, status: int = 409):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status
