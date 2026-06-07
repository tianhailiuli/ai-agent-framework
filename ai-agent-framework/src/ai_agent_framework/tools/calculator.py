"""Calculator tool with safe expression evaluation."""

import ast
import operator
import re

from .base import Tool


class CalculatorTool(Tool):
    """Tool for performing mathematical calculations safely."""

    @property
    def name(self) -> str:
        return "calculator"

    @property
    def description(self) -> str:
        return (
            "Perform mathematical calculations. "
            'Input: {"expression": "mathematical expression"}. '
            "Supports +, -, *, /, //, %, **, and basic math functions."
        )

    @property
    def hidden(self) -> bool:
        return True

    @property
    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": "Perform mathematical calculations safely. Supports +, -, *, /, //, %, **.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "expression": {
                            "type": "string",
                            "description": "A mathematical expression like '2+2*3' or '(15+23)*2'"
                        }
                    },
                    "required": ["expression"]
                }
            }
        }

    def run(self, params: dict) -> dict:
        expression = params.get("expression", "")
        if not expression:
            return {
                "status": "error",
                "result": None,
                "message": "No expression provided.",
            }

        try:
            result = self._safe_eval(expression)
            return {
                "status": "success",
                "result": result,
                "message": f"Result of '{expression}' is {result}",
            }
        except Exception as e:
            return {
                "status": "error",
                "result": None,
                "message": f"Calculation error: {str(e)}",
            }

    def _safe_eval(self, expression: str):
        """Safely evaluate a mathematical expression using AST."""
        # Remove whitespace for validation
        expr = expression.strip()
        # Allow only safe characters
        if not re.match(r'^[\d\+\-\*\/\(\)\.\,\%\^\s//\\\*\*]+$', expr.replace("**", "")):
            # More permissive: let AST parser catch bad syntax
            pass

        # Parse AST
        node = ast.parse(expr, mode="eval")

        def _eval(node):
            if isinstance(node, ast.Expression):
                return _eval(node.body)
            elif isinstance(node, ast.Constant):
                return node.value
            # ast.Num is deprecated since Python 3.8 and removed in 3.14
            # ast.Constant already handled above
            elif isinstance(node, ast.BinOp):
                left = _eval(node.left)
                right = _eval(node.right)
                if isinstance(node.op, ast.Add):
                    return left + right
                elif isinstance(node.op, ast.Sub):
                    return left - right
                elif isinstance(node.op, ast.Mult):
                    return left * right
                elif isinstance(node.op, ast.Div):
                    return left / right
                elif isinstance(node.op, ast.FloorDiv):
                    return left // right
                elif isinstance(node.op, ast.Mod):
                    return left % right
                elif isinstance(node.op, ast.Pow):
                    return left ** right
                else:
                    raise ValueError(f"Unsupported binary operator: {type(node.op)}")
            elif isinstance(node, ast.UnaryOp):
                operand = _eval(node.operand)
                if isinstance(node.op, ast.UAdd):
                    return +operand
                elif isinstance(node.op, ast.USub):
                    return -operand
                else:
                    raise ValueError(f"Unsupported unary operator: {type(node.op)}")
            else:
                raise ValueError(f"Unsupported expression type: {type(node)}")

        return _eval(node)
