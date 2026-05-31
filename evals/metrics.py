from src.models import MethodInfo


def _normalize(name: str) -> str:
    return name.lower().replace("_", "").replace(" ", "")


def method_recall(expected_names: list[str], found_names: list[str]) -> float:
    if not expected_names:
        return 1.0
    exp = {_normalize(n) for n in expected_names}
    fnd = {_normalize(n) for n in found_names}
    return len(exp & fnd) / len(exp)


def method_precision(expected_names: list[str], found_names: list[str]) -> float:
    if not found_names:
        return 1.0
    exp = {_normalize(n) for n in expected_names}
    fnd = {_normalize(n) for n in found_names}
    return len(exp & fnd) / len(fnd)


def http_accuracy(
    expected_methods: list[MethodInfo],
    found_methods: list[MethodInfo],
) -> float | None:
    expected_http = [m for m in expected_methods if m.http_method]
    if not expected_http:
        return None
    found_by_name = {_normalize(m.method_name): m for m in found_methods}
    matches = 0
    for exp in expected_http:
        found = found_by_name.get(_normalize(exp.method_name))
        if found is None:
            continue
        verb_ok = found.http_method == exp.http_method
        endpoint_ok = (
            (found.endpoint or "").rstrip("/").lower()
            == (exp.endpoint or "").rstrip("/").lower()
        )
        if verb_ok and endpoint_ok:
            matches += 1
    return matches / len(expected_http)
