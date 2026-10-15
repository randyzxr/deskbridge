# DeskBridge 0.3.1

新增 Windows 原生托盘：最小化、关闭窗口或点击隐藏按钮后继续共享；双击托盘图标恢复，右键退出停止普通共享。系统托盘不可用时保留普通窗口行为。

精简 Windows 运行包：只保留一份 Tcl/Tk 脚本，依赖按 PyInstaller hooks 收集；不再附带原 Deskflow GUI、翻译、未使用的图片/SVG/样式插件。核心、Qt 主要库、平台及 TLS 插件、许可证和核心对应源代码保留。没有修改普通桌面核心二进制，没有降低 TLS 或双方指纹校验。

提供 Windows 安装器和 Windows、Mac ARM/Intel、Ubuntu 26.04 amd64 的原生构建流程。Windows 无需安装 Python；Mac 包需在对应系统构建，当前仅开发签名，正式分发需开发者签名和 Apple 公证。Ubuntu 原生包通过 APT 安装系统库。

使用方法见随包 `docs/quick-start.md`。

限制：托盘通知区域支持本次针对 Windows；Mac / Ubuntu 仍使用普通 Dock / 任务栏最小化。双机实际输入、Mac 系统权限、Wayland 授权与锁屏效果仍需实机验收。Windows 锁屏接收服务仍为实验功能，安装需管理员且须人工安全评审；GUI 退出不停止独立后台服务。
