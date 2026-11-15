"""Typed application errors. Routes translate these to HTTP; services never raise HTTP exceptions."""
from __future__ import annotations


class AppError(Exception):
    status = 400
    code = "bad_request"

    def __init__(self, message: str = "", *, code: str | None = None):
        super().__init__(message or self.code)
        if code:
            self.code = code


class ValidationFailed(AppError):
    status, code = 422, "validation_failed"


class AuthRequired(AppError):
    status, code = 401, "auth_required"


class InvalidCredentials(AppError):
    status, code = 401, "invalid_credentials"


class Forbidden(AppError):
    status, code = 403, "forbidden"


class CsrfFailed(Forbidden):
    code = "csrf_failed"


class NotFound(AppError):
    status, code = 404, "not_found"


class Conflict(AppError):
    status, code = 409, "conflict"


class QuotaExceeded(AppError):
    status, code = 429, "quota_exceeded"


class TooManyAttempts(AppError):
    status, code = 429, "too_many_attempts"
