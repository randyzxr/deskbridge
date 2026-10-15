# 验证记录

日期：2026-10-13（Asia/Shanghai）。主机：Windows，Python 3.12.14。

0.3.0 新增修复：33 项单元测试通过，覆盖单一已配对共享端默认选择、保留多设备明确选择、接收端服务快照身份不变、服务导出限制和固定核心单字节权限修改/未知构建拒绝。C# 服务已编译；`tests/service_snapshot.py` 验证实际编译产物的快照、身份/名称/端口和引擎摘要拒绝。SYSTEM 服务、锁屏/解锁、用户切换、Mac 实机权限尚未验证，详见 lock-screen.md。

当前本机旧版核心正在用户共享；`tests/private_ipc.py` 检测到现有核心后跳过原生受限令牌与 TLS 回归。实际服务启动、SYSTEM IPC ACL 和锁屏输入仍待接收端验收。没有通过改变原生单实例保护来制造通过结论。

服务专用核心 IPC 修改的静态证据：REA/Ghidra `ev_2a03309df140c707efb94f4bd904c30693f53229857effeb5a181c94b63ecd48` 确认 `0x14002dd2e` 为 `MOV EDX,0x7`；随后 CALL 间接引用 IAT `0x14008df00`，PE 导入表该项是 `QLocalServer::setSocketOptions`。固定源 SHA 与字节条件见 tools/private_ipc.py；原文件保持不变。完整两条指令证据见 rea-ipc-evidence.json。静态观察不等同 SYSTEM 下的权限或锁屏运行验证。

## 已通过

- `python -m unittest discover -s tests -v`：29 项。覆盖配置和身份安全、日志生命周期、文件锁和 Windows 显式 ACL、自动模式不保存 DHCP 地址、发现元数据校验、同子网选择、网卡变化重建广播和受污染 DLL 环境的恢复；新增无组播的电脑名寻址、慢 DNS 截止时间、全部地址验证、角色/身份冲突、首次查询超时重试和按指纹主动查询。
- `python app.py --doctor`：官方 portable 核心文件与 `deskflow-core.exe v1.27.0, protocol v1.8` 版本契约通过。
- `python tests/integration_core.py`：真实 Windows 核心，在 127.0.0.1 随机非特权端口运行。验证未知证书拒绝、已信任证书取得 TLS 内的 Barrier hello、清空本应用 trusted-clients 后原已信任证书拒绝。实际错误日志显示读取应用私有信任库。
- `python tools/gui_smoke.py`：真实 Tk 窗口，设备列表与表单读取、配置控件锁定/解锁、应用窗口预览。
- PyInstaller Windows onedir 0.2.1 构建成功，完整核心及 DLL 单独位于 `engine/`。构建时逐文件核对原生核心副本；构建日志位于 `build/pyinstaller-0.2.1.log`。
- `tools/frozen-smoke.ps1`：最终 Windows EXE 在不调用项目 Python 的情况下启动，创建独立身份并退出；打包后启动验证通过。
- `tests/frozen_core.py`：从打包 EXE 实际启动核心，版本探测、TLS 白名单允许/拒绝/撤销通过；控制器结束后原生子核心监听关闭。这覆盖之前仅检查 GUI 启动遗漏的子核心加载链路。
- `tests/mdns_transport.py`：两个回环 mDNS 实例验证广播与地址替换，保持同一公开设备身份；未修改实际网卡或 DHCP 租约。
- `tests/lan_discovery_transport.py`：生产 LanDiscovery 类在回环组播上主动解析配对服务，并观察对端角色变更。没有依赖替代浏览器来证明管理层行为。
- `tests/dhcp_reconnect.py`：生产电脑名解析工作线程与真实原生接收核心连接回环 TLS 端点；模拟系统解析结果变化后连接第二个端点，保留同一证书 pin。测试服务未发送输入协议事件。

## 本机故障定位（0.2.1）

用户现有配对名称可由本机系统解析，所配置 TCP 端口的连接探测成功，本机和目标地址位于不同网段。旧版在没有匹配的 mDNS 缓存项时直接拒绝启动，与截图错误一致；未证明具体网关丢弃位置。修复后的生产 resolve 在禁用组播的诊断模式中，已解析该已配对电脑的当前私有地址和端口。诊断没有读取私钥、发送输入事件或更改真实用户配置；没有据此声称真实双机输入已经验收。

上述回环测试没有发送键盘、鼠标或剪贴板事件，没有连接外部电脑。验证证明集成及配对路径可运行，不能替代两台机器之间的输入效果验证。

## 分析身份

| 对象 | 固定身份 |
|---|---|
| Synergy 源码 | 9bf510d048be9a73ee113cdc80563e1ec5b82b42 |
| Deskflow 1.27.0 源码 | 081f6478e654a112168879e67a41ce7d7e4ae3af |
| Windows 官方 portable ZIP SHA-256 | 8d19004cc3625623489d96580c1b58fd13ee78185689907fd4478595f93fab9a |
| deskflow-core.exe SHA-256 | 8e533ece67eeebe70469abc9580b683960e260102cc3997d1b5a16a49c380951 |

官方核心发行：https://github.com/deskflow/deskflow/releases/tag/v1.27.0

REA 包结构证据：`ev_cc9482dfdda2ae092c47e7bbb762ba7b2cb53fca1e5d71d987198f0464c121ae`，原始记录见 `rea-archive-evidence.json`。静态 ZIP 中央目录清单不能证明执行行为或签名可信。

REA PE 资源证据：`ev_0f85a285821770ae9be00de3bb801dced3e96660759c37045f90e08d21ddc318`，见 `rea-evidence.json`。完整检查 20 个资源项、8 个资源载荷；没有反编译或用资源名推断运行逻辑。

## 未验证与验收入口

macOS、Ubuntu Xorg/Wayland 的实际安装与权限；Win↔Mac↔Ubuntu 双机/三机联动；实体键鼠的多屏切换、中文输入、DPI、热键、拖动、断线释放；剪贴板跨平台与大小限制；长期稳定性、网络中断、休眠恢复；签名、公证和安装器。对应矩阵见 design.md。

发行状态是开发 MVP，采用开源输入核心；不是独立重写核心或经过三平台验收的正式版本。
# 0.3.1 新增验证

2026-10-15，Windows 本机：

- 33 项单元回归通过。
- 原生托盘在真实 Windows 桌面测试通过：创建、隐藏窗口而不停核心、双击动作对应的恢复路径、有界操作缓冲、图标故障时恢复窗口、等待启停完成后退出和清理线程。测试调用本应用的回调/窗口方法，没有自动点击其他应用或注入键鼠。
- 精简版实际冻结 EXE：GUI 启动并生成独立身份；重复运行保留相同证书；`--doctor` 成功加载真实 1.27.0 核心。
- 原生 DLL 导入闭包检查未引用被裁剪的附带 DLL；保留文件与原文件 SHA-256 一致。
- 重新编译服务通过快照/指纹/注入/端口/清单摘要/额外 DLL 拒绝测试，无服务安装或 SYSTEM 输入。
- Windows 安装器安装到工作区临时目录，安装后的程序完成身份/核心探测，确认附带快速说明，再卸载并移除测试卸载项。未替换旧安装、未启动共享、未安装服务。

Mac / Ubuntu 的安装包构建与双机实际输入未在此 Windows 环境运行，后续以 GitHub 对应 runner 的真实日志和目标电脑验收为准。当前旧版核心仍在用户共享，不停止它来运行互斥核心的输入测试。
