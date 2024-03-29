import random

from promptflow.tracing import trace


@trace
def get_y(x: float) -> float:
    """
    Return Y value based on input x value.

    :param x: x value
    :type x: float
    """
    print(f"Get the Y value for x={x}")
    return x * 2