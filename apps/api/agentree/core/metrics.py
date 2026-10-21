"""In-process counters for monitoring, rendered in the Prometheus text format.

Counters are per API process and reset on restart; a scraper sums processes and uses rates.
Label values must be low-cardinality enums (provider, slot, outcome) — never ids or content.
"""

from collections import Counter

_counters: Counter[tuple[str, tuple[tuple[str, str], ...]]] = Counter()

HELP = {
    "agentree_llm_calls_total": "Model calls by provider, key slot and outcome (ok or error kind).",
    "agentree_breaker_transitions_total": "Circuit breaker transitions of stored provider keys.",
}


def inc(name: str, **labels: str) -> None:
    _counters[(name, tuple(sorted(labels.items())))] += 1


def value(name: str, **labels: str) -> int:
    return _counters[(name, tuple(sorted(labels.items())))]


def _line(name: str, labels: tuple[tuple[str, str], ...], number: int) -> str:
    if not labels:
        return f"{name} {number}"
    inner = ",".join(f'{k}="{v}"' for k, v in labels)
    return f"{name}{{{inner}}} {number}"


def render(gauges: dict[str, tuple[str, list[tuple[dict[str, str], int]]]]) -> str:
    """Counters plus `gauges` ({name: (help, [(labels, value)])}) as Prometheus text."""
    lines: list[str] = []
    for name, help_text in HELP.items():
        lines += [f"# HELP {name} {help_text}", f"# TYPE {name} counter"]
        for (n, labels), number in sorted(_counters.items()):
            if n == name:
                lines.append(_line(name, labels, number))
    for name, (help_text, samples) in gauges.items():
        lines += [f"# HELP {name} {help_text}", f"# TYPE {name} gauge"]
        for labels_dict, number in samples:
            lines.append(_line(name, tuple(sorted(labels_dict.items())), number))
    return "\n".join(lines) + "\n"
