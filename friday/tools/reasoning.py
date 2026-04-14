"""
Reasoning tools — mathematical computation, symbolic reasoning, data analysis, and visualization.
"""

import json
import math
import statistics
import re
from typing import Dict, List, Any, Optional, Union
from dataclasses import dataclass, asdict
from enum import Enum


class OperationType(Enum):
    """Types of mathematical operations supported."""
    BASIC_ARITHMETIC = "basic_arithmetic"
    STATISTICAL = "statistical"
    ALGEBRAIC = "algebraic"
    TRIGONOMETRIC = "trigonometric"
    LOGARITHMIC = "logarithmic"
    CALCULUS = "calculus"


@dataclass
class CalculationResult:
    """Result of a mathematical calculation."""
    operation: str
    input_values: List[Any]
    result: Any
    operation_type: OperationType
    explanation: Optional[str] = None
    step_by_step: Optional[List[str]] = None


@dataclass
class DataAnalysisResult:
    """Result of data analysis operations."""
    dataset_info: Dict[str, Any]
    statistical_summary: Dict[str, Any]
    insights: List[str]
    visualizations: List[Dict[str, str]]  # Contains chart descriptions and data


def register(mcp):

    @mcp.tool()
    def evaluate_math_expression(expression: str) -> str:
        """Safely evaluate a mathematical expression from a string."""
        import ast
        import operator
        
        # Supported operators
        operators = {
            ast.Add: operator.add,
            ast.Sub: operator.sub,
            ast.Mult: operator.mul,
            ast.Div: operator.truediv,
            ast.Pow: operator.pow,
            ast.BitXor: operator.xor,
            ast.USub: operator.neg
        }
        
        # Supported math functions
        math_funcs = {
            'sin': math.sin, 'cos': math.cos, 'tan': math.tan,
            'sqrt': math.sqrt, 'log': math.log, 'log10': math.log10,
            'pi': math.pi, 'e': math.e, 'pow': math.pow, 'abs': abs,
            'mean': statistics.mean, 'median': statistics.median,
            'stdev': statistics.stdev
        }
        
        def eval_expr(node):
            if isinstance(node, ast.Num): # <number>
                return node.n
            elif isinstance(node, ast.BinOp): # <left> <operator> <right>
                return operators[type(node.op)](eval_expr(node.left), eval_expr(node.right))
            elif isinstance(node, ast.UnaryOp): # <operator> <operand> e.g., -1
                return operators[type(node.op)](eval_expr(node.operand))
            elif isinstance(node, ast.Call): # Function call
                func_name = node.func.id
                if func_name in math_funcs:
                    args = [eval_expr(arg) for arg in node.args]
                    return math_funcs[func_name](*args)
            elif isinstance(node, ast.Name):
                if node.id in math_funcs:
                    return math_funcs[node.id]
            elif isinstance(node, ast.Constant):
                return node.value
            elif isinstance(node, ast.List):
                return [eval_expr(elt) for elt in node.elts]
            raise TypeError(f"Unsupported mathematical operation: {ast.dump(node)}")
            
        try:
            # Parse the expression safely
            result = eval_expr(ast.parse(expression, mode='eval').body)
            return json.dumps({"expression": expression, "result": result})
        except Exception as e:
            return json.dumps({"error": f"Failed to evaluate expression: {str(e)}"})

    @mcp.tool()
    def profile_dataset(file_path: str) -> str:
        """Quickly profile a CSV or JSON dataset without loading it into the LLM context. Returns headers, row count, and sample."""
        try:
            if not file_path.endswith('.csv') and not file_path.endswith('.json'):
                return "Only CSV and JSON datasets are supported for basic profiling."
                
            import os
            if not os.path.exists(file_path):
                return f"File does not exist: {file_path}"
                
            if file_path.endswith('.csv'):
                import csv
                with open(file_path, 'r', encoding='utf-8') as f:
                    reader = csv.reader(f)
                    try:
                        headers = next(reader)
                        sample_rows = [next(reader) for _ in range(3)]
                        row_count = 1 + len(sample_rows) + sum(1 for _ in reader)
                        return json.dumps({
                            "type": "csv",
                            "columns": headers,
                            "total_rows": row_count,
                            "sample_rows": sample_rows
                        }, indent=2)
                    except StopIteration:
                        return "CSV file appears to be empty."
            
            elif file_path.endswith('.json'):
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        sample = data[:3]
                        keys = list(data[0].keys()) if len(data) > 0 and isinstance(data[0], dict) else []
                        return json.dumps({
                            "type": "json_array",
                            "total_elements": len(data),
                            "keys": keys,
                            "sample": sample
                        }, indent=2)
                    elif isinstance(data, dict):
                        return json.dumps({
                            "type": "json_object",
                            "keys": list(data.keys()),
                            "key_count": len(data.keys()),
                            "sample_keys": {k: data[k] for k in list(data.keys())[:3]}
                        }, indent=2)
                        
        except Exception as e:
            return f"Error profiling dataset: {str(e)}"