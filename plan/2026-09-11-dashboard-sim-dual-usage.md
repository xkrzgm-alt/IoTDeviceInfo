# Dashboard SIM 双流量显示实施计划

## 目标
在 HWProgM `/device-search` Dashboard 的 SIM Info 区域同时显示：

- **Current Calendar Month Data**：自然月 1 日 00:00 UTC 至当前，调用 Hologram `/usage/data` 按会话 `bytes` 汇总。
- **Current Billing Period Data**：Hologram `cur_billing_data_used`，并显示由 `whenexpires - 30 days` 推算的周期起止时间。

全部流量按 Hologram 标准使用十进制 GB（`bytes / 1_000_000_000`）。保留现有 `monthly_data_*` API 字段并修正其语义为自然月，以免破坏小程序消费者。

## 实施步骤

1. **扩展 Hologram 客户端**（`hologram_client.py`）
   - 从 cellular link 读取 link ID、`whenexpires`、`cur_billing_data_used`。
   - 新增 `/usage/data` 查询，使用当前 UTC 自然月边界和 `linkid`，跟随分页并汇总全部会话字节数。
   - 返回自然月流量、计费周期流量、计费周期开始/结束时间。
   - 自然月用量查询失败时保留 SIM 其他信息并记录日志，避免整卡查询失败。

2. **扩展 FastAPI 响应模型**
   - `backend/models/schemas.py`：为 `SimInfoOut` 增加 `billing_period_data_bytes`、`billing_period_data_gb`、`billing_period_start`、`billing_period_end`。
   - `backend/routers/query.py`：映射新增字段；现有 `monthly_data_*` 映射自然月用量。

3. **更新 Dashboard SIM Info 展示**（`../HWProgM/dashboard/templates/device_search.html`）
   - 将原单一 `Monthly Data (GB)` 行替换为自然月流量和当前计费周期流量两行。
   - 增加计费周期日期行。
   - 为中英文分别增加清晰标签，满足 Dashboard i18n 规则。

4. **兼容性**
   - 不删除 `monthly_data_bytes/monthly_data_gb`，确保 `miniprogram-1` 现有类型和页面继续工作；其显示值将变为真正的自然月十进制 GB。

## 验证

- 使用 mocked Hologram 响应验证自然月边界、分页求和、十进制 GB 换算、30 天周期推算及用量接口失败时的降级行为。
- 调用本地 FastAPI `/api/query` 查询路由器 `89591025C2700023`，预期约显示自然月 `4.67 GB`、计费周期 `10.10 GB`，周期 `2026-08-20 06:01:42` 至 `2026-09-19 06:01:42`（实时值允许随新会话增长）。
- 在 HWProgM Dashboard 切换中英文，确认 SIM Info 两个流量和周期字段均正确显示，且无 `undefined`。
