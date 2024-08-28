import inspect
from os import PathLike
from types import NoneType
from typing import Any, Literal, NamedTuple, Type, TypedDict, get_args, get_origin

VALID_TYPES = (
    NoneType
    | bool
    | str
    | int
    | float
    | tuple
    | frozenset
    | list
    | dict
    | set
    | PathLike
)


def is_specifiable_type(annotation: Type | Any) -> bool:
    if annotation in [TypedDict, NamedTuple]:
        return False
    elif inspect.isclass(annotation):  # Is type
        return issubclass(annotation, VALID_TYPES)
    else:
        origin, args = get_origin(annotation), get_args(annotation)
        if origin is Literal:  # Whose args are not typing or types but strings
            return True
        return (origin is None or is_specifiable_type(origin)) and all(
            is_specifiable_type(arg) for arg in args
        )
