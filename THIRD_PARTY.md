# 来源与授权边界

本仓库 LICENSE 仅适用于本仓库原创代码与文档。不授权原作者固件、Magisk、Google Platform-Tools、外部脚本或本地构建产生的混合代码。所有外部文件保存在仓库之外，**不随 Git、Release 或 Actions artifact 分发**。

| 依赖 | 官方/原始入口 | 用途与分发处理 |
|---|---|---|
| qwXZhong U30 B24 v0.1 | https://github.com/qwXZhong/u30pro-b24-root-skill/releases/tag/v0.1 | 原方案、Magisk ramdisk、TrustOS 构造器和验证器；未声明许可证，使用者自行取得并确认有权使用；不重新分发 |
| TomKing spreadtrum_flash | https://github.com/TomKing062/spreadtrum_flash/tree/23c5ab211ca1e58e2fb8c70108d2bccfd0110925 | 原包 reader 的上游；未声明许可证，不复制整文件；native/adapt.py 仅提供本地互操作转换 |
| spreadtrum_flash 原始项目 | https://github.com/ilyakurdyukov/spreadtrum_flash | Unlicense 原始代码；该授权不能替后续 fork 的新增代码作保证 |
| Magisk 30.7 | https://github.com/topjohnwu/Magisk/releases/tag/v30.7 | GPL-3.0；原包 ramdisk 已含载荷，保持其字节；无本仓库二进制再分发 |
| Android Platform-Tools | https://developer.android.com/tools/releases/platform-tools | Mac ADB；遵守 Google 下载条款，用户自行获取 |
| AOSP avbtool | https://android.googlesource.com/platform/external/avb/ | 上游 Apache-2.0；本流程调用原包固定版本，来源和字节均列入 lock，不 vendoring |
| libusb | https://libusb.info/ | LGPL-2.1-or-later；由系统包管理器安装，本地链接 |
| LZ4 | https://github.com/lz4/lz4 | CLI GPL-2.0-or-later、library BSD-2-Clause，具体见上游 LICENSE；只调用本地 CLI |
| cryptography | https://github.com/pyca/cryptography | Apache-2.0 或 BSD-3-Clause；用于本地 AVB RSA 验证 |
| 7-Zip | https://www.7-zip.org/ | 解包原作者分卷；遵守上游具体组件许可，不随附 |

`sources.lock.json` 包含 12 个分卷的 URL、大小与 SHA-256，以及构建实际使用的内部文件摘要。摘要来自公开 v0.1 下载内容的本地计算，不是作者签名，也不能证明获得了版权许可。输入变化必须重新审计，不能直接刷新 lock。

所有对上游方案的描述为原创复盘，感谢原作者及上述工具维护者。厂商名称和商标归原权利人所有，本项目未获 ZTE、Google 或原作者背书。

没有许可证不等于开源授权，参见 [GitHub Choose a License 的说明](https://choosealicense.com/no-permission/)。如果需要重新发布未明确授权的输入，请先取得相应权利人的许可。
