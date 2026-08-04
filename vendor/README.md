# GR5513 BLE 显示工具

`epdiy_display.py` 是本项目用于兼容 epdiy.cn GR5513 扩展协议的主机端工具，支持
400 × 300 UC8176 黑白红图片转换、BLE 设备检查、槽位上传和日历模式恢复。

## 来源与许可证

- 本目录代码随整个项目按 [GPL-3.0-only](../LICENSE) 发布。
- 协议兼容行为参考了 [epdiy.cn](https://epdiy.cn/) 的公开 Web Bluetooth 实现，以及
  [tsl0922/EPD-nRF5](https://github.com/tsl0922/EPD-nRF5) 在提交
  `56d70ce65ac12b663def010455a3d19ea63bd9df` 时的公开实现；后者同样采用 GPL-3.0。
- 本仓库不分发 epdiy.cn 的网页资源、设备固件或 EPD-nRF5 源码副本，仅包含为本项目
  维护的 Python 主机端实现。
- 本项目与 epdiy.cn、设备厂商及 EPD-nRF5 维护者没有隶属或背书关系。

如果后续从其他上游复制或改写代码，必须在本节补充来源、提交版本和许可证，不能只
依赖根目录许可证覆盖来源不明的实现。

## 安全工作流

先运行不连接设备的编码自检：

```bash
.venv/bin/python vendor/epdiy_display.py self-test
```

只读检查设备能力：

```bash
.venv/bin/python vendor/epdiy_display.py inspect
```

上传前先离线渲染并检查输出：

```bash
.venv/bin/python vendor/epdiy_display.py render /absolute/path/image.png \
  --output-dir /absolute/path/output
```

上传会覆盖目标槽位，必须显式确认槽位：

```bash
.venv/bin/python vendor/epdiy_display.py upload /absolute/path/image.png \
  --slot 0 --overwrite-slot
```

需要切回固件日历模式时：

```bash
.venv/bin/python vendor/epdiy_display.py restore-calendar
```

## 判定成功

- 检查结果中的固件版本、型号、`mtu`、`rle` 和槽位数量必须来自本次连接。
- 上传前必须通过 RLE 编解码逐字节往返检查。
- 上传后设备通知的 `used_mask` 必须包含目标槽位，且 `refresh_sent` 为 `true`。
- 最终仍需肉眼或照片确认方向、颜色和完整性；协议成功不等于视觉正确。

## 安全边界

- 设备通知中的 `sid` 会被替换为 `<redacted>`，不得写入日志、文档或 Issue。
- 不自动清屏；完整双图层上传不需要预清屏，清屏还会增加一次全刷损耗。
- 不发送 `CFG_ERASE`、`FREE_SLOT`、裸 EPD 命令或未知命令。
- 不实现或执行 DFU 写入；固件升级应先准备可验证的原始固件和硬件恢复路径。
- 上传失败且尚未刷新时才尝试恢复日历；刷新已发送后不自动覆盖结果。

脚本依赖 Python 3、`bleak` 和 `Pillow`。完整安装与看板工作流见项目根目录
[README](../README.md)。
