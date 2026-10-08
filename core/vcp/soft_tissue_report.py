"""Stable report shape for iterative and direct tissue evaluations."""


def solve_report(values=None):
    report = dict(status="NOT_APPLICABLE", iterations=0, final_change=0.0, max_displacement=0.0,
                  relative_volume_error=0.0, max_fixed_error=0.0, solve_ms=0.0)
    report.update(values or {})
    return report
