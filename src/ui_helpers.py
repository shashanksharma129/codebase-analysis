from src.models import DomainAnalysis


def _collect_endpoints(domains: list[DomainAnalysis]) -> list[dict]:
    rows = []
    for domain in domains:
        for m in domain.methods:
            if m.http_method:
                rows.append({
                    "Verb": m.http_method,
                    "Path": m.endpoint or "",
                    "Method": m.method_name,
                    "Domain": domain.name,
                    "Description": m.description,
                    "Complexity": m.complexity,
                })
    return sorted(rows, key=lambda r: (r["Domain"], r["Path"]))
