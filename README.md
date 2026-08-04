# E-Ink AI Balance Dashboard

把多个 AI 服务的订阅用量与 API 余额汇总为一张 400 × 300 黑白红图片，并通过
Bluetooth Low Energy（BLE）刷新到兼容 epdiy.cn GR5513 协议的电子墨水屏。

项目面向 macOS 本地运行：凭据保留在用户机器上，账户查询、图片渲染和设备上传
均由本地 Python 进程完成。单个服务不可用时，其余卡片仍会继续更新。

## 功能特性

- 并发查询 Codex、Kimi、DeepSeek，预留 TokenHub 接入位。
- 同时展示套餐总额度、滚动时间窗、API 余额和重置时间。
- 根据内容复杂度自动分配卡片高度，最多展示四个账户。
- 针对 1-bit 墨水屏优化中文小字、硬边进度条和黑白红视觉层级。
- 高用量、低余额、查询失败时使用红色告警；健康状态保留少量红色视觉锚点。
- 支持只查询并生成 PNG，也支持通过 BLE 覆盖指定槽位并立即刷新。
- 看板标题可通过命令行配置，默认显示 `AI Dashboard`。
- 提供 macOS `launchd` 配置，可定时执行完整刷新流程。

## 支持的账户

| 账户 | 展示内容 | 默认凭据来源 | 告警条件 | 状态 |
| --- | --- | --- | --- | --- |
| Codex | 套餐、用量窗口、重置时间、credits | `~/.codex/auth.json` | 用量 > 80%，或 credits < ¥10 | 已接入 |
| Kimi Coding Plan | 套餐用量、5 小时窗口、重置时间 | `~/.cc-switch/cc-switch.db` | 剩余额度 < 20，或用量 > 80% | 已接入 |
| DeepSeek | CNY / USD API 余额及余额构成 | `~/.cc-switch/cc-switch.db` | CNY 余额 < ¥10 | 已接入 |
| Tencent TokenHub | 占位卡片 | 暂无 | — | 待接入 |

Codex 和 Kimi 使用的用量接口、cc-switch 数据库结构均可能随上游变化；相关异常会
显示为错误卡片，不会阻止其他账户渲染。

## 工作流程

```text
本机凭据 ──> 并发查询账户 ──> 标准化 AccountBalance
                                  │
                                  v
                           渲染 400 × 300 PNG
                                  │
                         --dry-run│BLE upload
                                  v
                           电子墨水屏槽位
```

## 运行要求

- macOS（当前渲染器依赖系统内置的 PingFang 和 Helvetica 字体）。
- Python 3.10 或更高版本。
- 支持 BLE 的 Mac，并授予运行 Python 的终端蓝牙权限。
- epdiy.cn GR5513 扩展协议兼容设备，默认蓝牙名称前缀为 `NRF_EPD_`。
- 可访问各账户 API 的网络环境。

其他操作系统可以运行账户查询层，但字体路径、BLE 权限和定时调度尚未做跨平台
适配。

## 快速开始

获取源码并进入项目目录后执行：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.lock
```

先确认程序能找到哪些凭据。该命令只输出凭据名称，不输出凭据值：

```bash
.venv/bin/python config.py
```

然后进行一次安全的离线预览，不连接蓝牙设备：

```bash
.venv/bin/python refresh.py --dry-run
open logs/latest.png
```

确认预览无误后再执行完整刷新：

```bash
.venv/bin/python refresh.py
```

> [!WARNING]
> 完整刷新会连接第一台名称匹配 `NRF_EPD_` 的设备，覆盖槽位 `0` 并发送刷新命令。
> 首次使用前请确认设备和槽位中没有需要保留的内容。

## 凭据配置

凭据解析遵循“显式配置优先、只读发现兜底”：

- 可以通过进程环境变量或项目本地 `.env` 显式提供凭据。
- 未显式配置时，Codex 只读访问 `~/.codex/auth.json`，Kimi 和 DeepSeek 只读访问
  `~/.cc-switch/cc-switch.db`。
- 本项目不会刷新 token，也不会修改 Codex 或 cc-switch 的凭据文件。Codex 返回
  401 / 403 时，需要通过 Codex 自身重新登录。

如果需要覆盖自动发现结果，可以创建本地 `.env`：

```bash
cp .env.example .env
```

支持的覆盖项如下：

```dotenv
DEEPSEEK_API_KEY=sk-xxxx
KIMI_API_KEY=sk-kimi-xxxx
CODEX_ACCESS_TOKEN=your-short-lived-access-token
CODEX_ACCOUNT_ID=your-account-id
```

Codex 凭据文件和 cc-switch 数据库的非默认路径需要通过进程环境变量指定：

```bash
export CODEX_AUTH_JSON=/absolute/path/to/auth.json
export CC_SWITCH_DB=/absolute/path/to/cc-switch.db
```

`.env` 和默认的 `logs/` 运行产物已加入 `.gitignore`；自定义输出到其他目录的图片
需要自行避免提交。不要把真实凭据写入源码、Issue 或提交记录。

定时刷新日志默认只记录 provider 名称、状态和告警标记，不记录余额、套餐或重置
时间。临时排障确实需要详细值时，可以显式传入 `--verbose-balances`；分享日志前仍需
人工检查。`python -m balances` 会输出详细账户摘要，不应直接粘贴到公开 Issue。

## 常用命令

查询全部账户并输出 JSON Lines：

```bash
.venv/bin/python -m balances
```

查询单个账户：

```bash
.venv/bin/python -m balances.codex
.venv/bin/python -m balances.kimi
.venv/bin/python -m balances.deepseek
.venv/bin/python -m balances.tokenhub
```

自定义标题、图片路径、设备前缀、槽位或 BLE 超时：

```bash
.venv/bin/python refresh.py --dry-run --title "Team Dashboard" --out /tmp/e-ink-preview.png
.venv/bin/python refresh.py --slot 1 --name-prefix NRF_EPD_ --ble-timeout 90
.venv/bin/python refresh.py --dry-run --verbose-balances  # 仅本地排障
```

完整参数见：

```bash
.venv/bin/python refresh.py --help
```

## 定时刷新

仓库提供一个每 30 分钟执行一次、加载后立即运行的 macOS LaunchAgent。

[`scheduler/com.eink.printer.refresh.plist`](scheduler/com.eink.printer.refresh.plist)
是无用户路径的模板。安装脚本会根据当前 checkout 自动生成
`~/Library/LaunchAgents/com.eink.printer.refresh.plist`，无需手工替换路径：

```bash
./scheduler/install.sh

# 只生成配置并检查，不加载或触发任务
./scheduler/install.sh --no-load

# 手动触发
launchctl kickstart -k "gui/$(id -u)/com.eink.printer.refresh"

# 查看应用日志
tail -f logs/refresh.log

# 卸载
./scheduler/uninstall.sh
```

如果任务没有启动，先用 `plutil -lint` 检查生成后的 plist，再查看
`logs/launchd.log`。

## 项目结构

```text
.
├── balances/                 # 账户数据模型、并发聚合与 provider 实现
├── scheduler/                # macOS LaunchAgent 安装与卸载脚本
├── tests/                    # 渲染布局和视觉语义回归测试
├── vendor/                   # GR5513 BLE 上传与图片转换工具
├── LICENSE                   # GPL-3.0-only 完整许可证
├── THIRD_PARTY_NOTICES.md    # 协议实现来源与第三方声明
├── config.py                 # 本机凭据发现与 .env 覆盖
├── refresh.py                # 查询、渲染、上传的主入口
├── render.py                 # 400 × 300 黑白红看板渲染器
├── requirements.txt          # Python 直接运行依赖范围
└── requirements.lock         # 已验证的 macOS 可复现依赖版本
```

BLE 协议、离线渲染和设备恢复说明见
[`vendor/README.md`](vendor/README.md)。

## 开发与测试

运行全部测试：

```bash
.venv/bin/python -m unittest discover -s tests -v
```

提交前建议同时检查语法和 diff：

```bash
.venv/bin/python -m compileall -q balances config.py refresh.py render.py tests vendor/epdiy_display.py
bash -n scheduler/install.sh scheduler/uninstall.sh
plutil -lint scheduler/com.eink.printer.refresh.plist
git diff --check
```

接入新账户时：

1. 在 `balances/` 新增 provider，并实现返回 `AccountBalance` 的 `fetch()`。
2. 在 `balances/__init__.py` 的 `PROVIDERS` 中注册 provider。
3. 为正常、告警、错误和超长文本状态补充测试。
4. 用 `--dry-run` 检查最终图片；当前画布最多展示前四个 provider。

TokenHub 网关目前没有已确认可用的余额 REST 接口。后续可以基于腾讯云 API 3.0
的 `DescribeTokenPlan` 接入，但需要由用户提供 SecretId、SecretKey 和 TeamId，并
实现 TC3 签名。

## 故障排查

- **卡片显示查询异常**：先运行对应的 `python -m balances.<provider>`，确认凭据和
  网络是否可用。
- **找不到 BLE 设备**：确认设备已唤醒、系统蓝牙已开启、终端拥有蓝牙权限，并按需
  增大 `--ble-timeout`。
- **预览正常但实屏文字发虚**：主流程已使用无抖动二值化和较高黑色阈值；先确认
  设备型号、分辨率与协议是否匹配。
- **上传进程成功但屏幕未更新**：命令成功只表示协议交互完成，仍需核对目标设备、
  槽位以及实屏结果。设备检查与恢复流程见 `vendor/README.md`。

## 贡献

欢迎通过 Issue 报告新的 provider、接口变化、设备兼容问题或渲染缺陷。提交 Pull
Request 时请说明复现方式、硬件/系统环境和验证结果，并确保现有测试通过。涉及 BLE
写入、槽位覆盖或凭据处理的变更，请在描述中明确安全边界。

贡献约定见 [CONTRIBUTING.md](CONTRIBUTING.md)，安全问题报告方式见
[SECURITY.md](SECURITY.md)。不要在公开 Issue 中附加 `.env`、`auth.json`、cc-switch
数据库、未脱敏日志或设备 `sid`。

## 许可证

本项目按 [GPL-3.0-only](LICENSE) 发布。`vendor/` 中 GR5513
兼容实现的来源、上游版本和授权说明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
与 [vendor/README.md](vendor/README.md)。
