"""Erros públicos estáveis sem dados sensíveis."""


class ApiError(Exception):
    def __init__(self, status: int, code: str, detail: str, **extensions):
        super().__init__(detail)
        self.status = status
        self.code = code
        self.detail = detail
        self.extensions = extensions

    def public_extensions(self) -> dict:
        """Only documented scalar diagnostics may cross the HTTP boundary."""
        return {key: value for key, value in self.extensions.items()
                if key in {'xmlPath', 'reason'} and isinstance(value, str)}
