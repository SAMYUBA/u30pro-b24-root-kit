---
name: u30pro-b24-root-kit
description: Use when preparing, auditing or debugging root on an owned ZTE U30 Pro MU5358 with U30ProHW1.0 and B24 firmware, especially from an Apple Silicon Mac. Covers local dependencies, backup, fixed B-slot writes and disappearing USB ADB. Other hardware and firmware need separate research.
---

# U30 Pro B24 root

先读 [README](README.md) 的支持矩阵与 CLI，再根据阶段读 [workflow](references/workflow.md)。本仓库是已成功单机流程的公开化重构，离线测试不等于此版本已经重新实机刷写。

## 决策与执行

1. 核对授权、MU5358 / U30ProHW1.0 / U30ProV1.0.0B24、Mac 环境与正常上网基线。已有会话授权继续有效；改动设备前需明确用户意图。导入 Skill 本身不授权刷机。
2. `u30.py doctor` 不接触设备。读 [THIRD_PARTY](THIRD_PARTY.md)，按 `sources.lock.json` 获取公开输入，运行 `verify-package`；未许可上游仅在用户本地使用，不转发到新仓库。
3. 所有下载、密钥、profile、backup、candidate、日志置于仓库外。只读取本机 ADB **公钥**；候选绑定本机公钥和当前设备序列号，绝不用作者的授权身份。
4. 按 README 执行 probe → 备份 → 重复读取 → candidate → profile → native build → dry-run。每阶段检查真实输出，不根据退出码或界面截图推断 Root。USB bus/port 由本地枚举确定。
5. 先 TrustOS B，验收正常启动，再用最新两份关键分区读取生成 Root profile。B 槽、CRC、六分区前置摘要或读回不符就停止。写入只允许固定单目标；禁止为了重试而更新摘要、上传未知 FDL、擦除、写 NV 或换槽。
6. ADB 缺失先读 [mistakes](references/mistakes.md) 与 [diagnostics](references/diagnostics.md)：USB PID 不代表接口；Root 可存在而 ADB 被框架移除。检查 `adb_enabled` 与 USB 时间线，不反复换刷镜像。RNDIS+重启只是成功序列的一部分，最终实际为 NCM+MTP+ADB。
7. `root-check` 验证已启动系统上的多次 Root/版本/ADB状态；随后由操作者确认首页和 Wi-Fi 上网。写入 ACK、短暂 su、Magisk 进程三者均不能替代最终验收。

## 恢复与报告

遇到部分写入、连接丢失或哈希漂移，保留本地证据，停止自动 reset/retry。`restore-root` 仅匹配当前状态时还原 init_boot，不还原 TrustOS、ADB 设置或用户数据；完整救砖没有被证明。易变 NV 重读一致也不等于恢复验证。

报告按“已验证 / 推断 / 未验证 / 下一步”给出简短证据，区分现场案例与当前新工具。对外分享先执行 `privacy_scan.py` 并人工审阅，禁止发布真实 dump/key/log。法律与使用边界见 [legal](references/legal.md)；完整案例见 [case-study](references/case-study.md)。
