# 白熊TT自用空调控制系统

这是一个基于 `sususweet/midea_auto_cloud` 核心云端代码做出来的 Windows 桌面控制端。

当前主方案是：

```text
Electron 桌面壳
  -> HTML/CSS/JS 前端卡片界面
  -> 本地 Python HTTP 后端
  -> midea_auto_cloud 云端登录与控制逻辑
  -> 美的美居 / MSmartHome 云
```

## 功能

- 登录美的美居 / MSmartHome 账号
- 自动读取空调设备
- 开关机
- 调温
- 切换模式
- 切换风速
- 显示运行日志

## 本地开发运行

先启动 Python 后端：

```bash
python -m venv .venv
.venv/bin/pip install -r midea_ac_controller/requirements.txt
python -m midea_ac_controller.server
```

再打开前端：

```bash
open midea_ac_controller/web/index.html
```

## 打包 Electron 版 exe

在 Windows 上运行：

```powershell
.\build_electron_windows.ps1
```

生成文件在 `midea_ac_controller/electron/dist/` 下。

## 备用 Tkinter 版

项目里仍保留了旧的 Tkinter 版本，可用：

```powershell
.\midea_ac_controller\build_windows.ps1
```

## 说明

- 当前桌面程序只保留了云端控制链路。
- 只展示空调类型设备：`0xAC`、`0xCC`、`0x21`。
- 登录使用美的美居或 MSmartHome 账号，不需要官方 IoT 开发者平台密钥。
- 由于本环境不是 Windows，当前只能完成源码和打包配置，不能直接生成 `.exe`。
