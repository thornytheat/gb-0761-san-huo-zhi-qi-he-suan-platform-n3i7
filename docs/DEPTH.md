# 深度登记 散货滞期核算台

- 规模：中型
- 核心规则：通知裁决后按合同优先级切片并集，复算滞期并逐档核账。

## 功能模块

| 模块 | 使用者动作 | 入口 | 核心文件 | 测试 |
|---|---|---|---|---|
| M1 公证装卸事件采信 | 检查原件与隔离原因 | POST /api/intake | `app/modules/intake/service.py` `app/modules/intake/reader.py` | `tests/test_intake.py` |
| M2 准备通知裁决 | 复核通知与合同选版 | POST /api/notice | `app/modules/notice/service.py` | `tests/test_notice.py` |
| M3 例外区间切片 | 查看重叠停工依据 | POST /api/exceptions | `app/modules/exceptions/service.py` | `tests/test_exceptions.py` |
| M4 免计边界复算 | 复核分段占额 | POST /api/clock | `app/modules/clock/service.py` | `tests/test_clock.py` |
| M5 滞期费与账单对照 | 核对到账分钟和金额 | POST /api/ledger | `app/modules/ledger/service.py` | `tests/test_ledger.py` |
| M6 批次留档复跑 | 固化计算并重跑 | POST /api/runs | `app/modules/runs/storage.py` | `tests/test_runs.py` |
| M7 证据包签发 | 查验资格、下载证据 | GET /api/evidence/<run_id> | `app/modules/evidence/service.py` | `tests/test_evidence.py` |

## 陷阱登记

| TRAP | 现象 | 朴素错误 | 处理 | 位置 | 测试 |
|---|---|---|---|---|---|
| TRAP-02 | 航次首列 BOM | 找不到事件键 | 去首 BOM | `app/modules/intake/reader.py` | `tests/test_intake.py::test_bom_and_repeated_header` |
| TRAP-04 | 分段表头 | 误计事件 | 单独登记分段 | `app/modules/intake/reader.py` | `tests/test_intake.py::test_bom_and_repeated_header` |
| TRAP-05 | E10 多一列 | 列错位 | 隔离原行 | `app/modules/intake/reader.py` | `tests/test_intake.py::test_column_count_isolated` |
| TRAP-07 | E09 空值哨兵 | 计入时钟 | 记录哨兵原值 | `app/modules/intake/values.py` | `tests/test_intake.py::test_sentinel_kept_as_evidence` |
| TRAP-11 | E03 两种偏移 | 双重通知 | UTC 时间去重 | `app/modules/intake/values.py` | `tests/test_intake.py::test_offsets_dedupe_by_instant` |
| TRAP-14 | E11 同键异时 | 后写覆盖 | 全组隔离 | `app/modules/intake/service.py` | `tests/test_intake.py::test_conflicting_key_is_withdrawn` |
| TRAP-19 | S01/S02 重叠 | 双免或随行序 | 明确优先级并列依据 | `app/modules/exceptions/precedence.py` | `tests/test_exceptions.py::test_precedence_permutation` |
| TRAP-23 | S04/S05 贴窗 | 交界重算 | 半开并裁边 | `app/modules/exceptions/service.py` | `tests/test_exceptions.py::test_touching_window_is_outside` |
| TRAP-25 | R1/R2 同时有效 | 随顺序定档 | 以最高优先级裁决 | `app/modules/notice/versions.py` | `tests/test_notice.py::test_notice_picks_active_priority` |

## 对账规则

- 每源正文行数 = 采信 + 隔离 + 空行 + 重复表头。
- 150 min = 75 min 合同计时 + 60 min 免计 + 15 min 缺证。75−35=40 min 超额。
- 应计 20×3 + 20×5 = 160.00 USD，船方 60+95=155.00 USD，相差 5.00 USD。

### 新合同雨停照计（rainbill 样例）

- 条款 `rain_charge_after_allowance=true`：额度（30 min）耗尽后雨停按可计分钟计费、假日仍免计；耗尽点 02:00，切分正常计时段 01:30–02:30。
- 240 min = 120 计时 + 90 免计（雨 30 + 假日 60）+ 30 缺证；超额 90 min，全落第一档（tier1_min=90），应计 270.00 USD，船方列账 395.00 USD，差额 −125.00 USD。
- 同一次雨停跨进假日按分钟切片：RAIN1 的 00:30–01:00 让给假日免计，不整段计也不整段免。
- GAP 与 RAIN2 重叠的 03:00–03:15 登记 `pending_verification`，裁决暂按缺证。
- 晚到雨停（01:30–02:00）把耗尽点推到 02:30，超额由 90 降为 60 min，分档与差额整体重算。
- 9 列老表头缺省 false，老合同（dirty/clean）输出规则不变，仅在耗尽点多一行边界切片。

按航次整窗计算，输入须提供确定偏移，未实现 IANA 时区名称、装卸多舱并行额度、非美元计价或电子签章。
