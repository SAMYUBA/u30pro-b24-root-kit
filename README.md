# U30 Pro B24 Root Kit

从一次 **Apple Silicon Mac → ZTE U30 Pro B24 → Magisk 30.7 → 稳定 USB ADB Root** 的实机过程整理而来。

提供 Agent Skill、原创本地适配工具、依赖锁定表和错题本。代码保持小而可读，危险边界由程序校验。没有“一键跳过核验”，也没有随包固件或个人备份。

> **支持边界**：MU5358 / U30ProHW1.0 / U30ProV1.0.0B24、有效 B 槽、与公开基准一致的启动链。现场流程在一台 Mac/一台设备上成功；**此公开重构版完成离线验证，未再次实机刷写**。无法保证救砖。先读 [使用与免责说明](references/legal.md)。

## 给 Codex / Claude Code

在本项目目录中启动 Agent，并交给它：

```text
阅读 SKILL.md 和 README.md。先结合本机环境做离线检查与只读预检，
确认设备版本、备份和恢复边界后，再给出固定分区 Root 操作。
所有设备专属文件放在仓库之外，不上传。
```

也可将整个仓库放到所用 Agent 支持的 skill 目录中，以 `SKILL.md` 为入口。不要只复制入口文件而遗漏 scripts、native、assets 与 references。`AGENTS.md` / `CLAUDE.md` 共用同一操作契约，不依赖专用 MCP。

## 项目导航

| 文件 | 作用 |
|---|---|
| [SKILL.md](SKILL.md) | Agent 的短入口、决策和停止条件 |
| [workflow](references/workflow.md) / [case-study](references/case-study.md) | 完整阶段与现场复盘 |
| [mistakes](references/mistakes.md) / [diagnostics](references/diagnostics.md) | 症状、误判、证据与下一步 |
| [sources.lock.json](sources.lock.json) / [THIRD_PARTY](THIRD_PARTY.md) | 所有固件构建输入的来源、版本、哈希及授权边界 |
| `scripts/u30.py` | 环境检查、下载校验、备份计划、候选、profile、执行和验收 |
| `scripts/native_build.py` / `native/` | Mac USB 适配、事务保护、合成测试和本地编译 |
| `assets/` | 本机身份绑定的启动 helper、可选诊断模板 |
| [privacy](references/privacy.md) / `scripts/privacy_scan.py` | 发布过滤与隐私扫描 |

## 依赖与空间

macOS 原生路径使用 Python **3.11+**、Xcode Command Line Tools/clang、libusb、LZ4、7-Zip、cryptography 和官方 ADB。推荐准备至少 **40 GiB** 空闲空间；完整原作者分卷约 11 GiB，解压、两遍备份和生成候选另占空间，具体以本地计划为准。

```bash
xcode-select --install                     # 已安装则跳过
brew install python@3.13 libusb lz4 pkgconf sevenzip
export U30_WORK="$HOME/u30-private"          # 仓库之外，ASCII 路径、无空格
mkdir -p "$U30_WORK"
chmod 700 "$U30_WORK"
python3.13 -m venv "$U30_WORK/venv"
export U30_PY="$U30_WORK/venv/bin/python"
"$U30_PY" -m pip install -r requirements.txt
"$U30_PY" scripts/u30.py doctor
```

[Homebrew Python](https://formulae.brew.sh/formula/python@3.13) 与 [sevenzip](https://formulae.brew.sh/formula/sevenzip) 的官方安装入口。Apple 自带 `python3` 可能是 3.9，请看 doctor 的实际输出。ADB 从 [Google 官方 Platform-Tools](https://developer.android.com/tools/releases/platform-tools) 获取，将实际目录加入 PATH；现场版本为 37.0.1，不随本仓库分发。

Linux/Windows 可阅读流程、运行部分离线 Python 检查；本仓库 native 编译使用 CommonCrypto，只支持 macOS。Intel Mac 未实机验证。不要把 Windows VM 的 USB 透传当作已验证恢复通道。

## 1. 获取公开输入

原方案：[qwXZhong/u30pro-b24-root-skill](https://github.com/qwXZhong/u30pro-b24-root-skill)。原作者包及 reader fork 均未声明许可证；本仓库不重新发布它们。以下下载由使用者自行发起，须确认自己有权使用。

```bash
"$U30_PY" scripts/u30.py fetch --directory "$U30_WORK/downloads"             # 只列缺少文件
"$U30_PY" scripts/u30.py fetch --directory "$U30_WORK/downloads" --download  # 显式下载
7zz t "$U30_WORK/downloads/u30pro-b24-skill.7z.001"
7zz x "$U30_WORK/downloads/u30pro-b24-skill.7z.001" "-o$U30_WORK/upstream"
```

将 `U30_PACKAGE` 设置为实际解压后**包含 `assets/continuation` 的目录**：

```bash
export U30_PACKAGE="$U30_WORK/upstream/u30pro_b24_root_AdvancedBackend_skill"
"$U30_PY" scripts/u30.py verify-package --package "$U30_PACKAGE"
```

SHA-256 是本次公开下载的内容固定值，不是作者签名。下载半途失败保留 `.partial`，检查后只处理对应临时文件再重试；不静默接受变化的 release。解压目录应为空且隔离，不执行作者包的自动启动脚本。验证成功后本工具才会调用固定的离线构造/验证函数。

## 2. 识别设备、生成读工具、备份

先从正常首页确认型号、硬件、完整固件版本以及 Wi-Fi 上网；记录在私有工作目录。生成 probe 不联系 USB：

```bash
"$U30_PY" scripts/u30.py read-plan --out "$U30_WORK/probe-plan.json"
"$U30_PY" scripts/native_build.py --package "$U30_PACKAGE" \
  --work "$U30_WORK/probe-native" --read-plan "$U30_WORK/probe-plan.json"
"$U30_WORK/probe-native/build/usb-location"
"$U30_WORK/probe-native/build/usb-interfaces"
```

从 USB 枚举结果确定目标设备的 bus 和物理 port path，记录为 `U30_BUS` / `U30_PORTS`，**不要照抄其他人的数字**。接口 `ff/42/01` 表示 ADB function；PID `19d2:1354` 可能有也可能没有它。USB 枚举受沙箱限制时，需要为这些设备检查提供本地 USB 访问权限。

```bash
export U30_BUS='替换为实际bus'
export U30_PORTS='替换为实际port.path'
"$U30_PY" scripts/u30.py run --read-plan "$U30_WORK/probe-plan.json" \
  --manifest "$U30_WORK/probe-native/build/manifest.json" \
  --bus "$U30_BUS" --ports "$U30_PORTS" --out "$U30_WORK/probes"
```

默认只输出 dry-run。准备执行时：关机、拔线；在同一命令末尾添加 `--execute`；见 `WAITING_FOR_DEVICE` 后，把**关机设备**插回同一物理端口，不手动开机。工具尝试进入已有 AutoD 服务，不上传 host FDL。进入正常首页却没捕获服务时，先检查日志与连接时序，不能自动重复无限尝试。

probe 读取六个关键分区两遍，并获得分区表。查看 `result.json`，将本次实际输出目录赋给 `U30_PROBE`，再从其 `sprdpart.bin` 生成全备份计划：

```bash
export U30_PROBE='替换为本次probe输出绝对目录'
"$U30_PY" scripts/u30.py read-plan --partition-table "$U30_PROBE/sprdpart.bin" \
  --out "$U30_WORK/backup-plan.json"
"$U30_PY" scripts/native_build.py --package "$U30_PACKAGE" \
  --work "$U30_WORK/backup-native" --read-plan "$U30_WORK/backup-plan.json"
"$U30_PY" scripts/u30.py run --read-plan "$U30_WORK/backup-plan.json" \
  --manifest "$U30_WORK/backup-native/build/manifest.json" \
  --bus "$U30_BUS" --ports "$U30_PORTS" --out "$U30_WORK/backups"
```

同样先 dry-run，再显式执行与关机接线。排除 userdata、cache 和大日志分区；**选定分区备份不等于全机镜像**。NV 两次读不同会报告失败，即使设备正常也不得忽略：冷启动后定向复读、保留差异、说明恢复限制。本案例曾遇到易变 NV 差异，未做完整恢复演练。

定向复读使用分区表中的实际名称，例如：

```bash
"$U30_PY" scripts/u30.py read-plan --partition-table "$U30_PROBE/sprdpart.bin" \
  --only nr_runtimenv1 nr_runtimenv2 --out "$U30_WORK/nv-recheck-plan.json"
```

然后用新的 `--read-plan` 编译到独立 work，再 dry-run/执行；每个目标仍读两遍。不存在或被排除的名称会拒绝，不扩大为 NV 写入。

## 3. 本地生成候选

`U30_BACKUP` 指向本机原厂备份目录，至少含 `splloader/sml_b/uboot_b/trustos_b/init_boot_b/vbmeta_b.bin`，与固定公开 B24 基准全部匹配。候选阶段不联系设备，但不代替前一步的备份审查。

```bash
export U30_BACKUP='替换为已验证原厂备份绝对目录'
export U30_SERIAL='替换为本机实际设备序列号'
adb start-server                          # 若尚未有 ADB key，ADB 会本地生成
"$U30_PY" scripts/u30.py candidate --package "$U30_PACKAGE" \
  --backup "$U30_BACKUP" --out "$U30_WORK/candidate" \
  --adb-public-key "$HOME/.android/adbkey.pub" --serial "$U30_SERIAL"
```

只读 `.pub`，不读取私钥。公钥注释在镜像内替换为通用标记，公钥本体仍是私有设备身份，生成镜像不应发布。

构建过程保留原厂 CPIO 元数据与 Magisk payload，替换公钥、helper、rc；保留 OEM vbmeta blob 并验证签名和父子 key，**修改后的 body 不再匹配原厂 descriptor，需要 TrustOS bypass**。启动 helper 设置 authenticated USB ADB、`adb_enabled=1` 和 UID 2000 的 Magisk policy。已有 ADB 授权主机也可能获得 shell Root，应由设备所有者审查。

需要复现有限 SMB 观察器时，先读 [诊断说明](references/diagnostics.md)，再使用可选 `--observer`；稳定设备不需要为了采集日志再次刷写。

## 4. 单分区事务：TrustOS，然后 Root

每次写入前使用最新 probe 的两份读取，不能复用跨多次重启的 `misc` 预期值。先拆分六对读取：

全备份与 probe 都会在读取完成后 reset。**在此处重新运行一次 probe，并将 `U30_PROBE` 改为这次最新输出目录**，不要沿用上面首次探测的变量。重启仍可能改变 misc，native 的实时六分区比对才是最终门槛；比对失败要解释变化，不能只刷新摘要重试。

```bash
"$U30_PY" scripts/u30.py split-reads --directory "$U30_PROBE" --out "$U30_WORK/pre-trustos"
"$U30_PY" scripts/u30.py profile --stage trustos \
  --before "$U30_WORK/pre-trustos/first" --second "$U30_WORK/pre-trustos/second" \
  --candidate "$U30_WORK/candidate/trustos_b.bin" --serial "$U30_SERIAL" \
  --bus "$U30_BUS" --ports "$U30_PORTS" --out "$U30_WORK/trustos-profile.json"
"$U30_PY" scripts/native_build.py --package "$U30_PACKAGE" \
  --work "$U30_WORK/trustos-native" --profile "$U30_WORK/trustos-profile.json"
"$U30_PY" scripts/u30.py run --profile "$U30_WORK/trustos-profile.json" \
  --manifest "$U30_WORK/trustos-native/build/manifest.json" \
  --bus "$U30_BUS" --ports "$U30_PORTS" --out "$U30_WORK/writes"
```

审查 dry-run、备份与恢复限制后才加 `--execute`，按同样的关机拔线/等待/接线顺序执行。写入条件是 **有效 B 槽 + 六份前置完整 hash + 固定候选 + 单目标 ACK + 六份后置 hash**，全部通过才 reset。CLI 不开放任意写入、擦除、NV 写、重分区或 host FDL 上传。

TrustOS 成功后确认首页和 Wi-Fi。重新执行 probe 并拆分到新目录，使用 `--stage root`、`candidate/init_boot_b.bin` 生成**新的** profile，再编译并 dry-run/执行。Root stage 要求当前 init_boot 仍为原厂、TrustOS 已是固定候选；不支持拿旧 profile 无限重试。

工具 native 返回成功只说明读回及 reset ACK，不说明系统可启动或 Root 成功。部分写入/哈希漂移时停止，不自行修改 before hash 或再次 reset。

## 5. 验收与 ADB 消失排查

```bash
adb devices -l
"$U30_PY" scripts/u30.py root-check --serial "$U30_SERIAL" \
  --out "$U30_WORK/root-check.json"
```

默认 7 次、间隔 10 秒，核对 root、Magisk 30.7、boot complete、B 槽、USB ADB 状态、授权开启及 TCP ADB 关闭。应在系统开机几分钟后运行，并让操作者确认首页与 Wi-Fi 上网。该结果是有限时间窗口，不能表述为长期稳定性证明。

本案例：内部 Magisk 已 root，ADB 却被撤销；`adb_enabled=1` 后第一次依旧回退；原厂 Web UI 改为 **RNDIS 并重启**后，Mac 连续取得 root。最终实际 USB 是 **NCM+MTP+ADB**。不要把 RNDIS 当作已证明的单一修复。详见 [错题本](references/mistakes.md)。

## 恢复范围

`profile --stage restore-root` 使用原厂 `init_boot_b.bin`，仍要求最新两份关键读取和当前已知 TrustOS。只能恢复 init_boot；**不会还原 TrustOS、adb_enabled、授权 key、Magisk policy 或用户数据**。需要分别审查恢复这些状态。部分写入会使旧 profile 失效；完整救砖未验证，不提供假装通用的全盘恢复命令。

## 离线验证与贡献

```bash
"$U30_PY" -m pip install -r requirements-dev.txt
"$U30_WORK/venv/bin/ruff" check .
"$U30_WORK/venv/bin/ruff" format --check .
"$U30_WORK/venv/bin/mypy" scripts tests native
"$U30_WORK/venv/bin/pytest"
"$U30_PY" scripts/privacy_scan.py
# 已有 Git 提交后：
"$U30_PY" scripts/privacy_scan.py --history
```

Python 测试使用 mock/synthetic 数据。native 构建自动执行状态机、候选冻结、ACK 失败、截断、错误 hash、CLI 拒绝等测试；输入来自用户本地包，不向云端 CI 上传固件或备份。公开重构与现场实现的差异及验证范围见 [validation](references/validation.md)。

请只提交代码、合成测试和原创说明，不提交真实日志、序列号、ADB keys、NV、firmware、生成的候选或 native binary。新固件需要新的研究，禁止为了“让检查通过”替换 hash。原创部分 [MIT](LICENSE)，第三方边界见 [THIRD_PARTY](THIRD_PARTY.md)。
