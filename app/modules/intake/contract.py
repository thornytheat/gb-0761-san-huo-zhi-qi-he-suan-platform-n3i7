HEADERS = {
    "events": "event_id,kind,time,party",
    "stops": "stop_id,kind,start,end",
    "terms": "version,start,end,priority,wait_min,allow_min,tier1_min,rate1_usd_min,rate2_usd_min",
    "invoice": "tier,minutes,usd",
}

# 可选列：缺失时按默认值补齐，老合同原件无需包含这些列。
OPTIONAL = {
    "terms": {"rain_charge_after_allowance": "false"},
}
