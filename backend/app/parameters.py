import ast
import math
import operator

from .design_schema import Design, Value

BINARY = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
          ast.Div: operator.truediv, ast.Pow: operator.pow}
FUNCTIONS = {"sin": math.sin, "cos": math.cos, "tan": math.tan,
             "sqrt": math.sqrt, "abs": abs, "min": min, "max": max}
RESERVED = set(FUNCTIONS) | {"pi"}


class DesignError(ValueError):
    pass


class Parameters:
    """Resolve a bounded arithmetic language; never execute model-generated code."""

    def __init__(self, design: Design):
        self.raw = {f"shared.{key}": value for key, value in design.parameters.items()}
        for part in design.components:
            if part.id in RESERVED | {"shared"}:
                raise DesignError(f"The component ID '{part.id}' is reserved.")
            for key, value in part.parameters.items():
                self.raw[f"{part.id}.{key}"] = value
        for key in self.raw:
            if key.split(".")[1] in RESERVED:
                raise DesignError(f"{key}: this parameter name is reserved.")
        self.resolved: dict[str, float] = {}
        self.active: set[str] = set()
        self.dependencies: dict[str, set[str]] = {}
        self.geometry_references: set[str] = set()
        for key in self.raw:
            self.resolve(key)

    def resolve(self, key: str) -> float:
        if key in self.resolved:
            return self.resolved[key]
        if key not in self.raw:
            raise DesignError(f"Unknown parameter '{key}'.")
        if key in self.active:
            raise DesignError(f"Circular parameter dependency involving '{key}'.")
        self.active.add(key)
        self.dependencies[key] = set()
        value = self.value(self.raw[key], key.split(".")[0], owner=key)
        self.active.remove(key)
        self.resolved[key] = value
        return value

    def value(self, value: Value, component: str, owner: str | None = None) -> float:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return self.finite(value)
        if not isinstance(value, str) or len(value) > 256:
            raise DesignError("A parameter must be a number or a short arithmetic expression.")
        try:
            tree = ast.parse(value, mode="eval")
            if sum(1 for _ in ast.walk(tree)) > 80:
                raise DesignError("The parameter expression is too complex.")
            return self.finite(self._node(tree.body, component, owner))
        except (SyntaxError, ZeroDivisionError, OverflowError, TypeError, ValueError) as error:
            if isinstance(error, DesignError):
                raise
            raise DesignError(f"Invalid expression '{value}': {error}") from error

    @staticmethod
    def finite(value):
        if not isinstance(value, (float, int)) or not math.isfinite(value) or abs(value) > 1_000_000:
            raise DesignError("Parameter values must be finite and within +/-1,000,000.")
        return float(value)

    def _reference(self, key, owner):
        if owner:
            self.dependencies[owner].add(key)
        else:
            self.geometry_references.add(key)
        return self.resolve(key)

    def used_parameters(self):
        result = set(self.geometry_references)
        pending = list(result)
        while pending:
            for dependency in self.dependencies.get(pending.pop(), set()):
                if dependency not in result:
                    result.add(dependency)
                    pending.append(dependency)
        return result

    def _node(self, node, component, owner):
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return self.finite(node.value)
        if isinstance(node, ast.Name):
            if node.id == "pi":
                return math.pi
            local = f"{component}.{node.id}"
            key = local if local in self.raw else f"shared.{node.id}"
            return self._reference(key, owner)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            return self._reference(f"{node.value.id}.{node.attr}", owner)
        if isinstance(node, ast.BinOp) and type(node.op) in BINARY:
            left, right = self._node(node.left, component, owner), self._node(node.right, component, owner)
            if isinstance(node.op, ast.Pow) and abs(right) > 8:
                raise DesignError("Expression exponents are limited to +/-8.")
            return self.finite(BINARY[type(node.op)](left, right))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            result = self._node(node.operand, component, owner)
            return result if isinstance(node.op, ast.UAdd) else -result
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FUNCTIONS:
            if node.keywords or not 1 <= len(node.args) <= 8:
                raise DesignError("Arithmetic functions accept one to eight positional arguments.")
            return self.finite(FUNCTIONS[node.func.id](*(self._node(arg, component, owner) for arg in node.args)))
        raise DesignError("Expressions only support arithmetic, parameters and sin/cos/tan/sqrt/abs/min/max.")

    def vector(self, values, component):
        return tuple(self.value(value, component) for value in values)

    def for_component(self, component):
        prefix = f"{component}."
        return {key[len(prefix):]: value for key, value in self.resolved.items() if key.startswith(prefix)}
