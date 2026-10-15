# 锁屏与 Mac 连接修复（0.3.0）

## Mac 截图错误

“接收端必须指定另一台电脑作为共享端”是接收端共享端选择为空。0.3.0 在只有一个已核对指纹的对端时自动选择；多个对端仍须明确选择，不从未配对广播自动授信。

截图的输入核心路径也为空。安装官方 **Deskflow 1.27.0** 到 `/Applications`，再重新打开 DeskBridge；也会检查 `~/Applications`、Homebrew 的常用目录。可选择 `/Applications/Deskflow.app/Contents/MacOS/deskflow-core`，或选择 `Deskflow.app` 由程序定位核心。实际输入核心须拥有 macOS 的“辅助功能”和“输入监控”权限；更新核心后有时需要在系统设置重新授权。[官方权限说明](https://github.com/deskflow/deskflow/wiki/Workarounds)

Mac 使用源码包更新项目文件并保留既有 `.venv` 和用户身份目录：

```sh
.venv/bin/python app.py
```

当前交付没有从 Windows 构建 macOS `.app`；Mac 权限、锁屏和实体输入仍需在 Mac 实测。

## Windows 接收端锁屏

Windows 锁屏/UAC 会切换到保护桌面。普通桌面进程没有对应输入权限，恢复网络并不能提供该权限；官方 Deskflow 用后台服务处理此场景。[微软桌面权限](https://learn.microsoft.com/en-us/windows/win32/winstation/desktops)、[官方服务说明](https://github.com/deskflow/deskflow/discussions/9035)

0.3.0 附带**实验性、仅接收端**的 `DeskBridgeLockReceiver` 服务实现。它使用 SYSTEM 身份，在管理员批准的用户控制台会话运行固定的输入核心；未复用可由本地 IPC 更改配置的上游 daemon。服务当前只按系统可解析的共享端电脑名自动寻址，端口须与共享端一致；不要求填写 IP。核心指纹校验一直开启。服务关闭剪贴板。原有 GUI 接收核心不能同时运行。

### 安装步骤（在 Windows 接收端）

先阅读下方“验收与安全评审”。这不是已经验收的生产服务。管理员安装后会增加锁屏界面的输入能力。

1. 用 0.3.0 DeskBridge 完成双方配对，选择“接收键鼠”及共享端，保存，保持普通共享停止。
2. 点击“生成锁屏服务配置”。私有快照通常位于 `%LOCALAPPDATA%\DeskBridge\lock-service`；不要发送或上传其中的 PEM。
3. 关闭 DeskBridge。在该接收端打开**管理员 PowerShell**，切换到完整解压包的 `DeskBridge\service` 目录，运行：

```powershell
.\Install-LockReceiver.ps1 -Snapshot "$env:LOCALAPPDATA\DeskBridge\lock-service"
```

自定义 profile 时使用界面显示的实际快照路径。安装需要 Windows 管理员权限；公司设备受脚本/安装策略限制时，由 IT 管理员审核安装，不更改执行策略。

4. 共享端保持正常运行，测试接收端正常输入 → `Win+L` → 用共享键鼠显示登录界面并输入本机账号密码 → 解锁继续共享。若组织策略要求 Ctrl+Alt+Del 安全注意序列，服务没有实现软件 SAS；该步骤需本机键盘。服务没有自动解锁、保存密码或跳过认证。
5. 服务仅在快照所属用户已登录控制台后运行；不支持开机未登录、其他用户登录、RDP 会话或 Windows 共享端服务模式。更改配对/身份/端口，先卸载服务再重新生成并由管理员安装新快照；GUI 在服务已安装时禁用普通共享和配对编辑，避免界面改动与服务实际授权不一致。服务每 15 秒尝试解析新地址；未知证书不会被接受。

服务日志：事件查看器 → Windows 日志 → 应用程序 → 来源 `DeskBridgeLockReceiver`。连续失败达到有限次数后停止服务，由管理员检查再启动。也可查询：

```powershell
Get-Service DeskBridgeLockReceiver
Stop-Service DeskBridgeLockReceiver
Start-Service DeskBridgeLockReceiver
```

### 移除

在完整包 `service` 目录，用管理员 PowerShell 执行：

```powershell
.\Uninstall-LockReceiver.ps1
```

移除服务会停止其自有子核心；原 DeskBridge 配对不变。脚本保留 Program Files / ProgramData 下的 `DeskBridgeLockReceiver` 目录，不自动递归删除身份。重新安装前由管理员核对并明确清理这两个目录；不要删除原用户 DeskBridge 身份。

### 验收与安全评审

- 已实现：管理员保护的固定程序/配置目录、固定核心清单摘要和逐文件验证、私有身份快照、SCM 系统鉴权、服务所属 SID 与当前控制台 SID 检查、启动前后重新检查所属会话、固定程序和参数、SYSTEM 子核心 Job Object 约束、关闭 TLS 绕过和屏幕进入/退出命令、关闭剪贴板、有界恢复。
- 已验证：C# 编译；快照允许/拒绝、身份匹配、名称注入、端口、清单摘要和额外 DLL 拒绝；普通核心的真实 TLS 路径。**未在 SYSTEM 服务、实际锁屏/解锁或其他用户切换中运行验收，不能据编译成功声称已修好实体锁屏输入。**
- 服务专用核心在创建 IPC 前将 Qt `WorldAccessOption` 收紧为 `UserAccessOption`，每个管道实例仅允许核心的进程用户；SYSTEM 服务下对应 SYSTEM。普通桌面核心保持原版。修改仅针对已核对 SHA-256 的 Windows 1.27.0 固定二进制：`tools/private_ipc.py` 校验完整原文件摘要及指令字节，修改单字节选项，并提供等价源代码补丁和摘要记录；其他核心版本拒绝处理。Qt 规定该选项限制到创建者用户。[Qt 权限定义](https://doc.qt.io/qt-6/qlocalserver.html#SocketOption-enum)
- **需人工安全评审**：新增 SYSTEM 运行边界、用户/桌面切换竞态和 token 权限；上游原生输入/解析路径；服务专用核心单字节修改及 GPL 对应源代码补丁；SYSTEM 和实际锁屏环境的原生 IPC 权限。没有复用上游 daemon 的 `configFile` 控制通道，不能将普通桌面测试描述为服务或锁屏验收。
- Mac / Ubuntu 锁屏权限与休眠恢复没有凭 Windows 服务实现就宣布支持。FileVault 启动前认证、关闭上盖/系统休眠和登出也不等同已登录会话锁屏。
