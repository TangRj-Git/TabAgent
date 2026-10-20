import ast
import math
import operator
from collections.abc import Callable
from typing import TypeAlias

from tabagent.core.exceptions import (
    ToolArgumentsError,
    ToolExecutionError,
)

Number: TypeAlias = int | float

# 限制表达式规模和整数大小，避免一次计算消耗过多资源。
_MAX_LENGTH = 2000
_MAX_NODES = 200
_MAX_INTEGER_BITS = 4096


def _power(base: Number, exponent: Number) -> Number:
    """计算乘方，并限制计算规模。"""
    if abs(exponent) > 1000:
        raise ToolArgumentsError(
            "The absolute exponent must not exceed 1000."
        )

    if (
            isinstance(base, int)
            and isinstance(exponent, int)
            and exponent > 0
            and abs(base) > 1
            and abs(base).bit_length() * exponent > _MAX_INTEGER_BITS
    ):
        raise ToolArgumentsError(
            "The requested power exceeds the integer size limit."
        )

    return operator.pow(base, exponent)


def _factorial(value: Number) -> int:
    """计算非负整数的阶乘。"""
    if type(value) is not int or not 0 <= value <= 500:
        raise ToolArgumentsError(
            "factorial() requires an integer between 0 and 500."
        )

    return math.factorial(value)


def _round(
        value: Number,
        ndigits: int | None = None,
) -> Number:
    """对数值进行舍入，并限制保留位数的范围。"""

    # 未指定 ndigits 时，保留 round(value) 返回整数的行为。
    if ndigits is None:
        return round(value)

    if type(ndigits) is not int:
        raise ToolArgumentsError(
            "round() requires an integer digit count."
        )

    # 负数表示对整数部分进行舍入，例如 -2 表示舍入到百位。
    # 限制范围，避免内置 round() 在处理整数时生成过大的中间值。
    if abs(ndigits) > 1000:
        raise ToolArgumentsError(
            "The digit count for round() must be between -1000 and 1000."
        )

    return round(value, ndigits)


# 可以直接在公式中使用的常量。
_CONSTANTS: dict[str, Number] = {
    "pi": math.pi,
    "e": math.e,
    "tau": math.tau,
}

# 支持的二元运算符。
_BINARY_OPERATORS: dict[
    type[ast.operator],
    Callable[..., Number],
] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: _power,
}

# 函数定义：(可执行函数，最少参数数量，最多参数数量)。
# 最多参数数量为 None，表示不单独限制；仍受表达式规模限制。
_FUNCTIONS: dict[
    str,
    tuple[Callable[..., Number], int, int | None],
] = {
    "abs": (abs, 1, 1),
    "round": (_round, 1, 2),
    "min": (min, 2, None),
    "max": (max, 2, None),
    "sqrt": (math.sqrt, 1, 1),
    "exp": (math.exp, 1, 1),
    "log": (math.log, 1, 2),
    "log10": (math.log10, 1, 1),
    "log2": (math.log2, 1, 1),
    "sin": (math.sin, 1, 1),
    "cos": (math.cos, 1, 1),
    "tan": (math.tan, 1, 1),
    "asin": (math.asin, 1, 1),
    "acos": (math.acos, 1, 1),
    "atan": (math.atan, 1, 1),
    "atan2": (math.atan2, 2, 2),
    "radians": (math.radians, 1, 1),
    "degrees": (math.degrees, 1, 1),
    "floor": (math.floor, 1, 1),
    "ceil": (math.ceil, 1, 1),
    "pow": (_power, 2, 2),
    "factorial": (_factorial, 1, 1),
}


def _validate_function_arguments(
        name: str,
        arguments: list[Number],
) -> None:
    """检查函数参数数量，以及已知的数学定义域。"""
    _, minimum, maximum = _FUNCTIONS[name]
    count = len(arguments)

    if count < minimum or (maximum is not None and count > maximum):
        if maximum is None:
            expected = f"at least {minimum}"
        elif minimum == maximum:
            expected = f"exactly {minimum}"
        else:
            expected = f"{minimum} or {maximum}"

        noun = "argument" if minimum == maximum == 1 else "arguments"

        raise ToolArgumentsError(
            f"{name}() requires {expected} numeric {noun}; "
            f"received {count}."
        )

    if name == "sqrt" and arguments[0] < 0:
        raise ToolArgumentsError(
            "sqrt() requires a non-negative argument."
        )

    if name in ("log", "log10", "log2"):
        if arguments[0] <= 0:
            raise ToolArgumentsError(
                f"{name}() requires a positive argument."
            )

        if name == "log" and count == 2:
            base = arguments[1]

            if base <= 0 or base == 1:
                raise ToolArgumentsError(
                    "The logarithm base must be positive "
                    "and must not equal 1."
                )

    if name in ("asin", "acos") and not -1 <= arguments[0] <= 1:
        raise ToolArgumentsError(
            f"{name}() requires an argument between -1 and 1."
        )


def _check_number(value: object) -> Number:
    """检查每一步的计算结果，只允许有限实数。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ToolArgumentsError(
            "Only real numbers are supported."
        )

    if isinstance(value, float) and not math.isfinite(value):
        raise ToolArgumentsError(
            "The calculation produced a non-finite number."
        )

    if isinstance(value, int) and value.bit_length() > _MAX_INTEGER_BITS:
        raise ToolArgumentsError(
            "The integer size limit was exceeded."
        )

    return value


def _evaluate(node: ast.AST) -> Number:
    """递归计算表达式，仅处理允许的语法节点。"""

    # 数字，例如 12、3.14、1e3。
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        result = node.value

    # 常量，例如 pi、e。
    elif isinstance(node, ast.Name):
        if node.id not in _CONSTANTS:
            raise ToolArgumentsError(
                f"Unknown constant: {node.id!r}."
            )

        result = _CONSTANTS[node.id]

    # 正负号，例如 +3、-5。
    elif isinstance(node, ast.UnaryOp) and isinstance(
            node.op,
            (ast.UAdd, ast.USub),
    ):
        operand = _evaluate(node.operand)
        result = operand if isinstance(node.op, ast.UAdd) else -operand

    # 二元运算，例如 1 + 2、3 * 4、2 ** 8。
    elif (
            isinstance(node, ast.BinOp)
            and type(node.op) in _BINARY_OPERATORS
    ):
        left = _evaluate(node.left)
        right = _evaluate(node.right)

        result = _BINARY_OPERATORS[type(node.op)](
            left,
            right,
        )

    # 函数调用，例如 sqrt(81)、log(100, 10)。
    elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        name = node.func.id

        if name not in _FUNCTIONS:
            raise ToolArgumentsError(
                f"Unknown function: {name!r}."
            )

        if node.keywords:
            raise ToolArgumentsError(
                f"{name}() accepts positional arguments only."
            )

        arguments = [
            _evaluate(argument)
            for argument in node.args
        ]

        _validate_function_arguments(name, arguments)

        function, _, _ = _FUNCTIONS[name]
        result = function(*arguments)

    else:
        raise ToolArgumentsError(
            "Unsupported syntax. Use numbers, arithmetic operators, "
            "constants, and supported function calls."
        )

    return _check_number(result)


PARAMETERS = {
    "type": "object",
    "properties": {
        "expression": {
            "type": "string",
            "minLength": 1,
            "maxLength": _MAX_LENGTH,
            "description": (
                "Mathematical expression to evaluate, "
                "for example '(12 + 8) * 4'."
            )
        }
    },
    "required": ["expression"],
    "additionalProperties": False
}


def calculate(expression: str) -> Number:
    """
    Evaluate a real-valued mathematical expression.

    Operators: +, -, *, /, //, %, **. The ^ symbol also means exponentiation.
    Parentheses and scientific notation are supported.
    Constants: pi, e, tau.
    Functions: abs, round, min, max, sqrt, exp, log, log10, log2,
    sin, cos, tan, asin, acos, atan, atan2, radians, degrees,
    floor, ceil, pow, factorial.

    log(x) is the natural logarithm; log(x, base) specifies the base.
    Trigonometric angles use radians. Use sin(radians(30)) for degrees.
    Multiplication must be explicit: use 2 * pi instead of 2pi.
    The % operator means remainder, not percentage.
    Functions accept positional arguments only.
    min() and max() require at least two numeric arguments.
    pow(base, exponent) accepts exactly two arguments.
    Use round(value) or round(value, digits).
    round() follows Python rounding rules, including ties to even.
    Floating-point representation can affect rounding results.
    Some math functions convert inputs to floats and may overflow
    even when an integer is within the allowed bit limit.

    Limits: 2000 characters, 200 AST nodes, absolute exponents up to 1000,
    round() digits from -1000 to 1000, a conservative 4096-bit integer limit,
    and factorial inputs from 0 to 500.
    No variables, equations, complex numbers, differentiation, or integration.
    Floating-point calculations may have rounding errors.

    Examples: (12 + 8) * 4, sqrt(81) + 2^3, log(100, 10).
    """
    if not isinstance(expression, str) or not expression.strip():
        raise ToolArgumentsError(
            "expression must be a non-empty string."
        )

    if len(expression) > _MAX_LENGTH:
        raise ToolArgumentsError(
            "expression must not exceed 2000 characters."
        )

    # 在本工具中，^ 表示乘方。
    # 先转换为 **，再解析，确保按乘方的优先级计算。
    expression = expression.strip().replace("^", "**")

    try:
        tree = ast.parse(expression, mode="eval")

    except (SyntaxError, ValueError, RecursionError) as exc:
        raise ToolArgumentsError(
            "The expression has invalid syntax."
        ) from exc

    if sum(1 for _ in ast.walk(tree)) > _MAX_NODES:
        raise ToolArgumentsError(
            "The expression is too complex."
        )

    try:
        return _evaluate(tree.body)

    except ZeroDivisionError as exc:
        raise ToolExecutionError(
            "Division by zero is undefined. "
            "Check divisors and negative powers of zero."
        ) from exc

    except OverflowError as exc:
        raise ToolExecutionError(
            "The calculation exceeds the supported floating-point range. "
            "Use smaller input values."
        ) from exc

    except ValueError as exc:
        raise ToolExecutionError(
            "The calculation is undefined for the supplied arguments."
        ) from exc

    except (ArithmeticError, TypeError) as exc:
        raise ToolExecutionError(
            "The calculation could not be completed "
            "with the supplied arguments."
        ) from exc
