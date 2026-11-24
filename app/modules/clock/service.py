from datetime import datetime, timedelta

from app.modules.exceptions.precedence import adjudicate_overtime

from .minutes import minutes


def _stamp(start, offset):
    return (datetime.fromisoformat(start) + timedelta(minutes=offset)).isoformat(timespec="minutes")


def _pending(verdict):
    kinds = {source["kind"] for source in verdict["sources"]}
    return "GAP" in kinds and len(kinds) > 1


def _active_stops(segment):
    return [{"stop_id": source["id"], "kind": source["kind"], "line": source["line"],
             "start": source["start"], "end": source["end"]} for source in segment["sources"]]


def _build(segment, head, part, verdict, phase, totals):
    exhausted = phase == "OVERTIME"
    bucket = verdict["bucket"]
    totals[bucket] += part
    return {"start": _stamp(segment["start"], head), "end": _stamp(segment["start"], head + part),
            "bucket": bucket, "reason": verdict["reason"], "winner": verdict["winner"],
            "sources": verdict["sources"], "minutes": part,
            "allowance_min": part if bucket == "counted" and not exhausted else 0,
            "overtime_min": part if bucket == "counted" and exhausted else 0,
            "phase": phase, "split": False,
            "rain_treatment": ("CHARGED" if verdict["reason"] == "RAIN_CHARGED"
                               else "EXEMPT" if verdict["reason"] in {"RAIN", "HOLIDAY"} else "NONE"),
            "pending_verification": _pending(verdict),
            "cumulative_counted_min": totals["counted"]}


def replay(notice, segments):
    limit = notice["term"]["allow_min"]
    rain_charged = bool(notice["term"].get("rain_charge_after_allowance", False))
    totals = {"counted": 0, "exempt": 0, "missing": 0}
    rows, crossed, pending = [], None, []
    for segment in segments:
        duration = minutes(segment["start"], segment["end"])
        exhausted = totals["counted"] >= limit
        # 可计段内部耗尽额度就在耗尽点切两刀，保证耗尽点精确；老合同两段裁决相同。
        cut = (not exhausted and segment["bucket"] == "counted"
               and totals["counted"] + duration > limit)
        produced = []
        if not cut:
            if exhausted and rain_charged:
                verdict = adjudicate_overtime(_active_stops(segment), True)
            else:
                verdict = {key: segment[key] for key in ("bucket", "reason", "winner", "sources")}
            produced.append(_build(segment, 0, duration, verdict,
                                   "OVERTIME" if exhausted else "ALLOWANCE", totals))
        else:
            head_part = limit - totals["counted"]
            first = _build(segment, 0, head_part,
                           {key: segment[key] for key in ("bucket", "reason", "winner", "sources")},
                           "ALLOWANCE", totals)
            first["split"] = True
            second = _build(segment, head_part, duration - head_part,
                            adjudicate_overtime(_active_stops(segment), True), "OVERTIME", totals)
            second["split"] = True
            produced.extend((first, second))
        rows.extend(produced)
        if crossed is None:
            overtime_row = next((row for row in produced if row["overtime_min"] > 0), None)
            if overtime_row is not None:
                if overtime_row["allowance_min"] > 0:
                    # 额度在本段内部耗尽：耗尽点 = 段起点 + 进入本段前剩余的额度。
                    crossed = _stamp(segment["start"], limit - (totals["counted"] - overtime_row["allowance_min"]))
                else:
                    crossed = overtime_row["start"]
        for row in produced:
            if row["pending_verification"] and rain_charged:
                pending.append({"start": row["start"], "end": row["end"], "minutes": row["minutes"],
                                "winner": row["winner"],
                                "sources": [source["id"] for source in row["sources"]]})
    elapsed = minutes(notice["start"], notice["end"])
    return {"elapsed_min": elapsed, **totals, "allowance_min": limit,
            "overtime_min": max(0, totals["counted"] - limit), "overtime_start": crossed,
            "rain_charge_after_allowance": rain_charged,
            "balanced": elapsed == sum(totals.values()),
            "pending_verification": pending, "rows": rows}
