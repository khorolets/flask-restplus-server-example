"""
Restplus (Patched) utils
------------------------
"""

def bulk_decorate(decorators):
    """
    Simple decorator to apply list of decorator to function

    Args:
      decorators (list) - list of decorators

    Example:
    >>> decorators_list = [api.response(code=422), api.response(code=204)]
    ... func = bulk_decorate(decorators_list)(func)
    """
    def decorator(func):
        for d in reversed(decorators):
            func = d(func)
        return func
    return decorator
