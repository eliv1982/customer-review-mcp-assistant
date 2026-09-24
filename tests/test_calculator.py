import pytest

from tools import calculate


@pytest.mark.parametrize(
    "expression, expected",
    [
        ("1200 * 0.15", 180),
        ("2 + 3 * 4", 14),
        ("(1 + 2) * 3", 9),
        ("-5 + 2", -3),
        ("10 / 4", 2.5),
        ("7 // 2", 3),
        ("7 % 4", 3),
        ("2 ** 10", 1024),
    ],
)
def test_arithmetic(expression, expected):
    assert calculate(expression) == {"expression": expression, "result": expected}


@pytest.mark.parametrize("expression", ["1 / 0", "5 // 0", "5 % 0"])
def test_division_by_zero_is_a_controlled_error(expression):
    assert calculate(expression) == {
        "expression": expression,
        "error": "Деление на ноль",
    }


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os').system('echo hi')",  # call
        "abs(-1)",  # call
        "x + 1",  # name
        "'a' * 3",  # string constant
        "[1, 2]",  # list
        "(1).real",  # attribute
        "1 if 1 else 2",  # conditional
    ],
)
def test_disallowed_expressions_are_rejected(expression):
    result = calculate(expression)
    assert "result" not in result
    assert "Недопустимое выражение" in result["error"]


@pytest.mark.parametrize(
    "expression",
    ["True", "False", "True + 1", "1 + False", "-True", "2 ** True", "(True)"],
)
def test_boolean_constants_are_not_numbers(expression):
    # bool is an int subclass, so a loose isinstance check would evaluate True as 1.
    assert calculate(expression) == {
        "expression": expression,
        "error": "Ошибка вычисления: Недопустимое выражение",
    }


def test_syntax_error_is_a_controlled_error():
    result = calculate("1 +")
    assert "result" not in result
    assert result["error"].startswith("Ошибка вычисления")


@pytest.mark.parametrize("expression", ["-" * 5000 + "1", "+".join(["1"] * 5000)])
def test_deeply_nested_expression_is_a_controlled_error(expression):
    result = calculate(expression)
    assert "result" not in result
    assert result["error"] == "Выражение слишком сложное"


@pytest.mark.parametrize(
    "expression",
    [
        "10 ** 400",  # float pow overflow
        "9 ** 9 ** 9",
        "1e308 * 10",  # overflows to inf without raising
        "1" + "0" * 400,  # int literal too large for float()
    ],
)
def test_overflow_is_a_controlled_error(expression):
    result = calculate(expression)
    assert "result" not in result
    assert result["error"] == "Результат слишком велик"
