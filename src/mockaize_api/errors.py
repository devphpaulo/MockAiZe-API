"""Erros públicos estáveis sem dados sensíveis."""


class ApiError(Exception):
    def __init__(self, status: int, code: str, detail: str, **extensions):
        super().__init__(detail)
        self.status = status
        self.code = code
        self.detail = detail
        self.extensions = extensions
