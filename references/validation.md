# 验证范围与重构差异

## 已验证的现场事实

一台 MU5358 / U30ProHW1.0 / B24，Apple Silicon Mac：TrustOS B 与 init_boot B 单分区写入，六个关键分区完整写前/写后校验通过，设备正常启动。内部观察器先证明 root 存在，再发现 USB ADB 被移除；后续全局设置、原厂 USB 选项及重启组合后，ADB 实际 `su` 返回 root，Magisk 30.7，多次采样稳定，用户确认首页与 Wi-Fi 上网正常。

这些是脱敏后的观察摘要，原始数据留在本地。不是来自第二台设备的重复实验，也不说明所有冷启动、任意 USB 线/Hub、Intel Mac 或其他固件可用。

## 公开版实际完成的离线检查

- Python 3.13：30 项测试通过，覆盖 CPIO 结构/替换、密钥输入、USB 参数、boot control CRC/启动资格、定向备份计划、模拟读回报告、dry-run 无设备访问、ADB 验证缺字段拒绝。
- Ruff lint/format 与 mypy 检查通过；离线 AVB 验证使用 cryptography 50.0.2，版本固定在 requirements.txt。
- shell mock：身份与认证校验、settings 异常、保留已有公钥、重复运行备份、USB 失败、Magisk 超时和 policy 失败。
- observer mock：marker 严格匹配、symlink 拒绝、首路径不可写的 fallback、服务未就绪和有界循环。
- macOS native writer 构建：28 项合成/CLI 检查，包括冻结后的候选源文件变化、执行前候选损坏/截断/追加、ACK 失败、前后 hash/尺寸不符及 reset 门禁。
- macOS native reader 构建：38 项合成/CLI 检查，包含 writer 公用检查及 reader 缺失/截断/过长输出等。
- 使用公开包中的 stock 输入与**合成测试身份**执行普通/observer 两种候选构建：TrustOS 固定输出、历史 init_boot 逐字节重建、LZ4 roundtrip、CPIO 非目标条目不变、OEM vbmeta 签名/父子 key 匹配均通过。没有把合成身份候选用于设备。
- 主 CLI 与本地 native manifest 连接后的 read/write dry-run 通过，未触碰 USB。
- Skill 格式校验、独立 Agent 场景阅读检查、公开文件隐私扫描。

本仓库提供完整的本地检查命令，不包含自动下载固件的 CI。原生 CommonCrypto/libusb 构建与状态机测试需在 macOS 上使用本地取得的输入执行。

## 与现场脚本不同的地方

| 项目 | 现场版本 | 公开重构版 |
|---|---|---|
| 设备/路径 | 固定单机序列号、目录、USB bus/port | 本地参数与 profile，仓库不带真实值 |
| 构建依赖 | 已解压本地文件、固定 Homebrew 路径 | hash-pin 后本地导入，pkg-config 或 brew prefix |
| helper | 逐次试验累积，包含调试 resetprop | 原创精简 helper，先校验身份/设置，保留 key，失败明确退出；不再主动 resetprop ro.debuggable |
| 观察器 | 现场日志含上一轮 helper tail | 可选模板，随机本地 marker，当前 boot ID、属性与设置白名单，不复制原始日志 |
| 备份 | 选定分区 + 部分关键项重复读取 | 生成计划内每项重复两遍，NV 差异仍需解释 |
| 测试 fixture | 真实本机备份/候选 | 合成数据；真实输入只用于仓库外离线重建 |

**因此，公开版工具不与现场刷入版本字节相同。** 重新整理减少了个人绑定和隐藏依赖，也引入了需要再次受控实机验证的差异。首个新设备使用者应将它视为已离线验证的实验工具，保持完整门禁与回退材料。

## 未验证

- 救砖/全盘恢复、NV 恢复、回退 TrustOS、厂商 fuse/rollback 状态。
- 多设备、多固件、不同主机与长期稳定性。
- 具体 OEM 组件为何移除 ADB，以及 RNDIS 是否有独立因果作用。
- 清除全部设备配置修改的自动化卸载流程。

不通过再刷已经正常的用户设备来“补一个测试勾”。需要新的实机实验时，应单独说明改变、输入、停止条件和未验证风险。
