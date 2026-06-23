# Python 3.14 Compatibility Fix

## Issue
The server was crashing with this error:
```
AttributeError: 'typing.Union' object has no attribute '__module__' and no __dict__ for setting new attributes.
```

## Root Cause
Python 3.14 introduced changes to the `typing` module that break compatibility with `httpcore 1.0.9`. The library tries to set `__module__` on `typing.Union` objects, which is no longer allowed in Python 3.14.

## Fix Applied
A patch was applied to `venv/Lib/site-packages/httpcore/__init__.py` to handle this gracefully:

```python
__locals = locals()
for __name in __all__:
    if not __name.startswith("__"):
        try:
            # Python 3.14 compatibility: check if object supports __module__ attribute
            obj = __locals[__name]
            if hasattr(obj, "__dict__") or hasattr(type(obj), "__module__"):
                setattr(obj, "__module__", "httpcore")  # noqa
        except (AttributeError, TypeError):
            # Skip if object doesn't support __module__ (e.g., typing.Union in Python 3.14)
            pass
```

## Note
This is a temporary workaround. When `httpcore` releases a Python 3.14-compatible version, you should:
1. Remove this patch
2. Upgrade `httpcore` to the new version
3. Reinstall dependencies

## Alternative Solution
If you encounter issues, consider using Python 3.13 or 3.12, which have better package compatibility.
