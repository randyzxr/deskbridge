# DeskBridge 简要使用说明

Windows 安装版：双击 `DeskBridge-0.3.1-windows-x64-setup.exe`，按向导完成安装，从开始菜单启动。安装器自带 Python 环境和输入核心，无需安装 Python。

1. 两台电脑分别启动 DeskBridge，保持本机名称不同。
2. 互相添加电脑并核对对端屏幕显示的完整 SHA-256 指纹。只传公开指纹，不复制私钥和配置目录。
3. 键盘鼠标所在电脑选择“共享键鼠”；另一台选择“接收键鼠”并选中共享端。
4. 在共享端拖动电脑卡片，使相邻边缘与真实摆放一致。保存配置，先启动共享端，再连接接收端。
5. 鼠标移过对应边缘切换电脑；`Ctrl+Alt+F12` 返回共享端。使用电脑名自动寻址，无需固定 DHCP 地址。组播被隔离时还需要局域网 DNS 能解析对端电脑名。

## 隐藏到任务栏通知区域（Windows）

- 点击“隐藏到托盘”、最小化或关闭窗口，都保留应用及当前共享。
- 双击通知区域的 DeskBridge 图标恢复窗口；右键菜单也可以显示窗口。
- 选择“退出并停止共享”结束普通共享并退出。Windows 有时把图标收进任务栏右下角的上箭头中。
- 系统托盘不可用时保留普通最小化和关闭行为，避免窗口隐藏后无法找回。
- 实验锁屏服务独立于普通窗口运行；退出窗口不会停止该后台服务，按 `lock-screen.md` 管理。

macOS / Ubuntu 当前保留普通 Dock / 任务栏最小化；本次通知区域实现仅针对 Windows。

## macOS / Ubuntu

Mac：Apple silicon 选择 `macos-arm64.dmg`，Intel 选择 `macos-x86_64.dmg`。打开镜像，将 DeskBridge.app 拖入 Applications，再从应用程序启动。包内已附运行环境和 Deskflow 核心，无需安装 Python。当前为开发签名，未做 Apple 公证；如果系统阻止首次打开，可按系统设置“隐私与安全性”提供的“仍要打开”流程核对后打开，保持 Gatekeeper 开启。[Apple 官方说明](https://support.apple.com/zh-cn/102445)

Ubuntu 26.04 amd64：打开终端，切换到下载目录，执行：

```sh
sudo apt install ./DeskBridge-0.3.1-ubuntu-26.04-amd64.deb
```

随后从应用列表启动 DeskBridge。APT 会安装所需系统库，无需安装 Python；该包不能用于 Ubuntu 22.04/24.04。卸载用 `sudo apt remove deskbridge`，用户配对配置保留。

macOS 需授予实际输入核心“辅助功能”和“输入监控”权限；随包核心位于 `/Applications/DeskBridge.app/Contents/Resources/engine/Deskflow.app/Contents/MacOS/deskflow-core`。Ubuntu Wayland 需桌面 portal 授权，Xorg 需 XTest。应用停止或关闭后结束普通共享。系统权限和双机实际键鼠效果需在使用的电脑上确认，构建机器的启动探测不能替代这些授权。

## 更新与卸载

先从托盘退出旧版，再安装新版。已有配对与本机身份保存在用户配置目录，普通安装/卸载保留这些数据。已安装实验锁屏服务的电脑，先按锁屏文档停止并卸载服务，再更新程序。

锁屏服务仍属实验功能，真实安全桌面/解锁未验收，不保证可在所有 Windows 策略下输入。不要为此关闭系统登录保护。
