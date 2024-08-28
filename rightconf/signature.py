import ast
import inspect
import textwrap
import typing
from dataclasses import dataclass
from inspect import Parameter
from typing import Callable, Literal, Optional, Type


class Parser:
    def resolve_signature(
        self,
        fn: Callable,
        cls: Optional[Type] = None,
        modules_dict: Optional[dict[str, Type]] = None,
    ) -> dict[str, Parameter]:
        self.modules_dict = modules_dict
        parameters = self._resolve_signature(fn, cls=cls)
        output = {
            key: param
            for key, param in parameters.items()
            if param.kind != param.VAR_POSITIONAL
        }
        delattr(self, "modules_dict")  # Assure pickle dumpable
        return output

    def _resolve_signature(
        self, fn: Callable, cls: Optional[Type] = None
    ) -> dict[str, Parameter]:
        # Identify the function interface and implementation
        fn, fn_impl = fn, fn
        fns = typing.get_overloads(fn)
        if fns:
            _msg = f"There are {len(fns)} overloaded, we don't know which one is actaully used."
            assert len(fns) == 2, _msg
            fn, fn_impl = fns

        # Identify bounded class
        if cls:
            pass
        elif hasattr(fn, "__self__"):
            cls = fn.__self__
        elif "." in fn.__qualname__:
            cls = fn.__qualname__.replace(f".{fn.__name__}", "")
            cls = f"{fn.__module__}.{cls}"
            cls = eval(cls, self.modules_dict)

        # Get parameters of the function
        signature = inspect.signature(fn)
        parameters: dict[str, Parameter] = dict()
        first_arg_name, kwarg_name = None, None
        for i, (name, param) in enumerate(signature.parameters.items()):
            if param.kind == param.VAR_KEYWORD:
                kwarg_name = name
                continue
            elif i == 0:
                first_arg_name = name
                if cls:
                    continue  # exclude `self`
            parameters[name] = param

        # If there's no kwargs to be resolved, then return.
        if not kwarg_name:
            return parameters

        # Get function calls where kwargs expands. If there is not, then return.
        call_infos: list[CallInfo] = get_calls_expand_kwargs(
            fn_impl,
            kwarg_name=kwarg_name,
            first_arg_name=first_arg_name,
        )
        if not call_infos:
            return parameters

        # Since we only collect calls that directly expands kwargs without modification, kwargs in all calls should correspond to the same arguments
        call_info = call_infos[0]

        # Realize the call
        if call_info.bound:
            match call_info.bound:
                case "SELF":
                    bound = cls
                case "PARENT":
                    bound = cls.__base__
                case _:
                    bound = [p for p in cls.__bases__ if p.__name__ == call_info.bound][
                        0
                    ]
            call: Callable = getattr(bound, call_info.name)
        else:
            call = eval(call_info.name, self.modules_dict)
            bound = None

        # Identify arguments corresponding to expanded kwargs
        parameters_call: dict[str, Parameter] = self._resolve_signature(call, cls=bound)
        is_variable_args_touched = False
        parameters_tgt: dict[str, Parameter] = dict()
        for i, (name, param) in enumerate(parameters_call.items()):
            if param.kind == param.VAR_POSITIONAL:  # *args
                is_variable_args_touched = True
                continue
            elif (
                not is_variable_args_touched and i < call_info.num_assigned_positionals
            ):
                continue  # remove argument assigned by position
            elif name in call_info.assigned_keywords:
                continue  # Remove argument directly assigned by keyword
            # The rest are assigned by kwargs expansion
            parameters_tgt[name] = param

        # Expand parameter by parameters corresponding to the expanded kwargs
        parameters.update(parameters_tgt)

        return parameters


@dataclass
class CallInfo:
    bound: Optional[str | Literal["PARENT", "SELF"]]
    name: str
    num_assigned_positionals: int
    assigned_keywords: list[str]


def get_calls_expand_kwargs(fn, kwarg_name: str, first_arg_name: str) -> list[CallInfo]:
    code = textwrap.dedent(inspect.getsource(fn))
    tree = ast.parse(code)
    visitor = CallWithKwargsVisitor(kwarg_name, first_arg_name)
    visitor.visit(tree)
    return visitor.call_infos


class CallWithKwargsVisitor(ast.NodeVisitor):
    def __init__(self, kwarg_name: str, first_arg_name: str):
        self.call_infos: list[CallInfo] = []
        self.kwarg_name = kwarg_name
        self.first_arg_name = first_arg_name

    def visit_Call(self, node):  # Visit all function calls
        # There is **<kwarg_name> in the calling
        has_kwargs_expansion = any(
            keyword.arg is None and keyword.value.id == self.kwarg_name
            for keyword in node.keywords
        )
        if has_kwargs_expansion:
            # Normal funciton
            if isinstance(node.func, ast.Name):
                bound = None
                name = node.func.id
            # Super call
            elif (
                isinstance(node.func.value, ast.Call)
                and node.func.value.func.id == "super"
            ):
                if node.func.value.args:  # super(ParentClass, self)...
                    bound = node.func.value.args[0].id
                else:  # super()
                    bound = "PARENT"
                name = node.func.attr
            # Nested attribute. Since we can't access instance attribute with class, ignore it.  e.g., self._wandb_init.update
            elif isinstance(node.func, ast.Attribute) and isinstance(
                node.func.value, ast.Attribute
            ):
                return
            # This class's method (including class method)
            elif (
                isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == ["self", "cls"]
            ):
                bound = "SELF"
                name = node.func.attr
            else:  # Ignore
                return

            call_info = CallInfo(
                bound=bound,
                name=name,
                num_assigned_positionals=len(node.args),
                assigned_keywords=[
                    kw.arg for kw in node.keywords if kw.arg is not None
                ],
            )
            self.call_infos.append(call_info)

        self.generic_visit(node)
