import math
from collections import Counter
from numbers import Number
from typing import Any

from scipy import stats


def _is_numeric_column(values: list[Any]) -> bool:
    filtered = [value for value in values if value is not None]
    return bool(filtered) and all(isinstance(value, Number) and not isinstance(value, bool) for value in filtered)


def _to_builtin(value: Any) -> Any:
    if isinstance(value, Number):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
        return float(value) if isinstance(value, float) else value
    return value


MIN_SAMPLE_SIZE = 5


def validate_results(rows: list[dict]) -> dict:
    row_count = len(rows)
    if row_count < MIN_SAMPLE_SIZE:
        return {
            "skipped": True,
            "reason": f"Insufficient data variance (N < {MIN_SAMPLE_SIZE}) to perform statistical correlation. Returning raw data only.",
            "row_count": row_count,
            "numeric_summaries": {},
            "categorical_summaries": {},
        }

    columns = list(rows[0].keys()) if rows else []
    numeric_summaries: dict[str, dict] = {}
    categorical_summaries: dict[str, dict] = {}

    for column in columns:
        values = [row.get(column) for row in rows]
        filtered = [value for value in values if value is not None]
        if not filtered:
            continue

        if _is_numeric_column(filtered):
            description = stats.describe(filtered)
            numeric_summaries[column] = {
                "count": int(description.nobs),
                "min": _to_builtin(description.minmax[0]),
                "max": _to_builtin(description.minmax[1]),
                "mean": _to_builtin(description.mean),
                "variance": _to_builtin(description.variance),
            }
        else:
            counts = Counter(str(value) for value in filtered)
            top_values = counts.most_common(5)
            categorical_summaries[column] = {
                "count": len(filtered),
                "top_values": [
                    {
                        "value": label,
                        "count": count,
                        "percentage": round((count / len(filtered)) * 100, 2),
                    }
                    for label, count in top_values
                ],
            }

    return {
        "skipped": False,
        "reason": "",
        "row_count": row_count,
        "numeric_summaries": numeric_summaries,
        "categorical_summaries": categorical_summaries,
    }
