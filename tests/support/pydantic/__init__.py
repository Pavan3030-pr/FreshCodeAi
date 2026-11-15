"""MINIMAL pydantic-v2 stand-in used ONLY when real pydantic is not installed (offline sandbox). Real runs use the real package."""
import re
import typing

_MISSING = Ellipsis


class ValidationError(Exception):
    def __init__(self, errors):
        super().__init__(str(errors))
        self._errors = errors

    def errors(self):
        return self._errors


class _FieldInfo:
    def __init__(self, default=_MISSING, default_factory=None, **kw):
        self.default, self.default_factory, self.kw = default, default_factory, kw


def Field(default=_MISSING, *, default_factory=None, **kw):
    return _FieldInfo(default, default_factory, **kw)


def _check(name, value, hint, kw):
    origin, args = typing.get_origin(hint), typing.get_args(hint)
    if origin is typing.Union and type(None) in args:
        if value is None:
            return None
        hint = [a for a in args if a is not type(None)][0]
        origin, args = typing.get_origin(hint), typing.get_args(hint)
    if hint is str:
        if not isinstance(value, str):
            raise ValidationError([{"loc": [name], "msg": "Input should be a valid string"}])
        if "min_length" in kw and len(value) < kw["min_length"]:
            raise ValidationError([{"loc": [name], "msg": f"String should have at least {kw['min_length']} characters"}])
        if "max_length" in kw and len(value) > kw["max_length"]:
            raise ValidationError([{"loc": [name], "msg": f"String should have at most {kw['max_length']} characters"}])
        if "pattern" in kw and not re.search(kw["pattern"], value):
            raise ValidationError([{"loc": [name], "msg": f"String should match pattern '{kw['pattern']}'"}])
    elif hint is int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValidationError([{"loc": [name], "msg": "Input should be a valid integer"}])
        if "ge" in kw and value < kw["ge"]:
            raise ValidationError([{"loc": [name], "msg": f"Input should be greater than or equal to {kw['ge']}"}])
        if "le" in kw and value > kw["le"]:
            raise ValidationError([{"loc": [name], "msg": f"Input should be less than or equal to {kw['le']}"}])
    elif hint is bool:
        if not isinstance(value, bool):
            raise ValidationError([{"loc": [name], "msg": "Input should be a valid boolean"}])
    elif origin in (list, typing.List):
        if not isinstance(value, list):
            raise ValidationError([{"loc": [name], "msg": "Input should be a valid list"}])
        if "max_length" in kw and len(value) > kw["max_length"]:
            raise ValidationError([{"loc": [name], "msg": f"List should have at most {kw['max_length']} items"}])
        for item in value:
            _check(name, item, args[0], {}) if args else None
    return value


class BaseModel:
    def __init__(self, **data):
        hints = typing.get_type_hints(type(self))
        for name, hint in hints.items():
            attr = getattr(type(self), name, _MISSING)
            info = attr if isinstance(attr, _FieldInfo) else None
            if name in data:
                value = _check(name, data[name], hint, info.kw if info else {})
            elif info is not None and info.default_factory is not None:
                value = info.default_factory()
            elif info is not None and info.default is not _MISSING:
                value = info.default
            elif info is None and attr is not _MISSING:
                value = attr
            else:
                raise ValidationError([{"loc": [name], "msg": "Field required"}])
            setattr(self, name, value)
