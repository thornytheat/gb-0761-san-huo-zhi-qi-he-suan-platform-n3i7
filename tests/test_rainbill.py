from app.modules.evidence.service import certify
from app.manifest import snapshot
from app.pipeline import evaluate
from app.input import sample
from time import perf_counter


def rainbill():
    return sample("rainbill")


def calc(sources):
    return evaluate(sources)


def test_new_contract_rain_charged_after_allowance():
    clock = calc(rainbill())["clock"]
    assert clock["rain_charge_after_allowance"] is True
    assert (clock["counted"], clock["exempt"], clock["missing"]) == (120, 90, 30)
    assert (clock["overtime_min"], clock["overtime_start"]) == (90, "2027-02-10T02:00+00:00")
    charged = [r for r in clock["rows"] if r["reason"] == "RAIN_CHARGED"]
    assert sum(r["minutes"] for r in charged) == 30
    assert all(r["bucket"] == "counted" and r["overtime_min"] == r["minutes"] for r in charged)


def test_holiday_stays_exempt_after_allowance():
    rows = calc(rainbill())["clock"]["rows"]
    holidays = [r for r in rows if r["reason"] == "HOLIDAY"]
    assert sum(r["minutes"] for r in holidays) == 60
    assert all(r["bucket"] == "exempt" for r in holidays)


def test_rain_crossing_holiday_is_split_by_minute():
    rows = calc(rainbill())["clock"]["rows"]
    rain = [r for r in rows if r["winner"] == "RB-RAIN1"]
    holiday = [r for r in rows if r["winner"] == "RB-HOL1"]
    assert [(r["start"], r["end"], r["reason"]) for r in rain] == [
        ("2027-02-10T00:00+00:00", "2027-02-10T00:30+00:00", "RAIN")]
    assert sum(r["minutes"] for r in holiday) == 60


def test_boundary_allowance_exact_then_rain_charged():
    sources = rainbill()
    sources["terms"] = sources["terms"].replace(",0,30,90,", ",0,60,90,")
    clock = calc(sources)["clock"]
    assert not any(r["split"] for r in clock["rows"])
    assert clock["overtime_start"] == "2027-02-10T02:30+00:00"
    rain2 = next(r for r in clock["rows"] if r["winner"] == "RB-RAIN2")
    assert rain2["reason"] == "RAIN_CHARGED" and rain2["overtime_min"] == 30


def test_gap_rain_overlap_flagged_pending():
    clock = calc(rainbill())["clock"]
    assert clock["pending_verification"] == [
        {"start": "2027-02-10T03:00+00:00", "end": "2027-02-10T03:15+00:00", "minutes": 15,
         "winner": "RB-GAP1", "sources": ["RB-GAP1", "RB-RAIN2"]}]


def test_tier_delta_and_basis_on_ledger():
    ledger = calc(rainbill())["ledger"]
    assert (ledger["expected_usd"], ledger["seen_invoice_usd"], ledger["delta_usd"]) == ("270.00", "395.00", "-125.00")
    tier1 = ledger["rows"][0]
    assert [b["reason"] for b in tier1["basis"]] == ["WORKING_CLOCK", "RAIN_CHARGED", "WORKING_CLOCK"]
    assert sum(b["allocated_min"] for b in tier1["basis"]) == 90
    assert tier1["basis"][1]["winner"] == "RB-RAIN2"
    assert ledger["rows"][1]["basis"] == []
    assert [p["minutes"] for p in ledger["pending_verification"]] == [15]


def test_late_stop_moves_exhaustion_and_reprices_tiers():
    sources = rainbill()
    before = calc(sources)["ledger"]
    sources["stops"] += "RB-RAIN3,RAIN,2027-02-10T01:30Z,2027-02-10T02:00Z\n"
    after = calc(sources)
    assert before["expected_usd"] == "270.00"
    assert (after["clock"]["overtime_start"], after["clock"]["overtime_min"]) == (
        "2027-02-10T02:30+00:00", 60)
    assert after["ledger"]["expected_usd"] == "180.00"


def test_legacy_contract_without_clause_keeps_old_rule():
    sources = rainbill()
    sources["terms"] = ("version,start,end,priority,wait_min,allow_min,tier1_min,rate1_usd_min,rate2_usd_min\n"
                        "RB1,2027-02-01T00:00Z,2027-03-01T00:00Z,10,0,30,90,3,5\n")
    clock = calc(sources)["clock"]
    assert clock["rain_charge_after_allowance"] is False
    assert (clock["counted"], clock["exempt"], clock["overtime_min"]) == (90, 120, 60)
    assert not any(r["reason"] == "RAIN_CHARGED" for r in clock["rows"])
    assert clock["pending_verification"] == []
    assert calc(sources)["ledger"]["expected_usd"] == "180.00"


def test_zero_allowance_charges_first_rain_immediately():
    sources = rainbill()
    sources["terms"] = sources["terms"].replace(",0,30,90,", ",0,0,90,")
    clock = calc(sources)["clock"]
    assert clock["overtime_start"] == "2027-02-10T00:00+00:00"
    assert clock["rows"][0]["reason"] == "RAIN_CHARGED"
    assert all(r["reason"] != "HOLIDAY" or r["bucket"] == "exempt" for r in clock["rows"])


def test_settlement_eligibility_recomputed_after_recalculation():
    sources = rainbill()
    blocked = certify(snapshot(sources, calc(sources), perf_counter()))
    assert blocked["can_settle"] is False
    sources["stops"] = "stop_id,kind,start,end\n"
    sources["invoice"] = "tier,minutes,usd\n1,90,270\n2,120,600\n"
    granted = certify(snapshot(sources, calc(sources), perf_counter()))
    assert granted["can_settle"] is True


def test_invalid_boolean_is_quarantined():
    sources = rainbill()
    sources["terms"] = sources["terms"].replace(",true", ",maybe")
    isolated = evaluate(sources, "intake")["intake"]["isolated"]
    assert [row["code"] for row in isolated if row["source"] == "terms"] == ["INVALID_BOOLEAN"]
