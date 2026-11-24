from decimal import Decimal

from .rates import tier_costs


def _overtime_basis(clock):
    """把超时（滞期）分钟按时间顺序摊到各档，并保留每档的停工依据。"""
    allocations = []
    for row in clock["rows"]:
        if row["overtime_min"] <= 0:
            continue
        allocations.append({"minutes": row["overtime_min"], "reason": row["reason"], "winner": row["winner"],
                            "start": row["start"], "end": row["end"],
                            "sources": [source["id"] for source in row["sources"]],
                            "rain_treatment": row["rain_treatment"],
                            "pending_verification": row["pending_verification"]})
    return allocations


def compare(notice, clock, invoice, quarantined):
    actuals = {item["tier"]: item for item in invoice}
    basis = _overtime_basis(clock)
    rows = []
    for tier in tier_costs(notice["term"], clock["overtime_min"]):
        actual = actuals.get(tier["tier"])
        disputed = [q["line"] for q in quarantined if q["source"] == "invoice" and q["code"] == "KEY_CONFLICT"
                    and q["key"] == tier["tier"]]
        remaining = tier["minutes"]
        supports = []
        for entry in basis:
            if remaining <= 0:
                break
            used = min(entry["minutes"], remaining)
            supports.append({**entry, "allocated_min": used})
            remaining -= used
        if actual is None:
            code = "INVOICE_CONFLICT" if disputed else "INVOICE_MISSING"
            rows.append({**tier, "code": code, "invoice_line": None, "conflict_lines": disputed,
                         "actual_usd": None, "actual_minutes": None, "delta_usd": None, "basis": supports})
            continue
        delta = Decimal(tier["expected_usd"]) - Decimal(actual["usd"])
        code = "MATCH" if not delta and tier["minutes"] == actual["minutes"] else "TIER_DIFFERENCE"
        rows.append({**tier, "code": code, "invoice_line": actual["line"], "actual_usd": actual["usd"],
                     "actual_minutes": actual["minutes"], "delta_usd": f"{delta:.2f}", "basis": supports})
    complete = all(r["delta_usd"] is not None for r in rows)
    expected = sum(Decimal(r["expected_usd"]) for r in rows)
    seen = sum(Decimal(r["actual_usd"]) for r in rows if r["actual_usd"] is not None)
    return {"expected_usd": f"{expected:.2f}", "seen_invoice_usd": f"{seen:.2f}",
            "delta_usd": f"{expected - seen:.2f}" if complete else None,
            "complete": complete, "differences": sum(r["code"] != "MATCH" for r in rows),
            "pending_verification": clock.get("pending_verification", []),
            "rain_charge_after_allowance": clock.get("rain_charge_after_allowance", False), "rows": rows}
