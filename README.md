# DeskBridge

独立桌面控制器 + 固定版本 Deskflow 1.27.0 输入核心，实现局域网 Windows / macOS / Ubuntu 键盘鼠标共享。提供 Windows 安装版、Mac ARM / Intel DMG 和 Ubuntu 26.04 amd64 DEB 的原生构建；安装与启动检查见 [验证记录](docs/validation.md)。系统输入权限与双机实际键鼠效果仍需在使用的电脑上验收。

这不是仅展示连接效果的网页：点击启动后会运行真实的原生输入核心。Synergy 商业界面与授权机制未被复制，详细分析见 [报告](docs/synergy-analysis.md)，产品与开发方案见 [设计](docs/design.md)。

## 快速运行

Windows 0.3.1 提供安装版 `DeskBridge-0.3.1-windows-x64-setup.exe` 与精简便携版；便携版解压后运行 `DeskBridge.exe`。新增原生托盘，隐藏/最小化/关闭窗口保留共享，双击托盘图标恢复，托盘菜单退出停止普通共享。简要使用见 [快速说明](docs/quick-start.md)，各端安装包构建与状态见 [安装包说明](docs/installers.md)。也可在项目目录运行：

```powershell
.\launch-local.ps1
```

macOS / Ubuntu 使用 Python 3.12+ 和 Tk。先确认 `python3` 版本，Python 2.7 没有 `venv` 模块：

```sh
python3 --version
python3 -c "import sys; assert sys.version_info >= (3, 12), 'DeskBridge requires Python 3.12+'"
python3 -m venv .venv
.venv/bin/python -m pip install --only-binary=:all: -r requirements.txt
.venv/bin/python -m tkinter
.venv/bin/python app.py
```

关闭 Tk 测试窗口后运行最后一条命令。可以在创建环境成功后执行 `source .venv/bin/activate`，但以上命令不依赖激活或修改系统 `python`。若 `python3` 不存在或版本低于 3.12，macOS 请先安装 [Python 官方 macOS 安装包](https://www.python.org/downloads/macos/)，重新打开终端。Ubuntu 须安装匹配版本的 `python3-venv python3-tk`。Windows 源码运行使用 `py -3 -m venv .venv`，随后 `.venv\Scripts\python.exe` 安装依赖和运行 app.py。本工作区的 `launch-local.ps1` 使用 `.local` 独立目录；普通运行使用当前用户 DeskBridge 配置目录。

## 两台电脑联机

1. 在双方安装或放置 **Deskflow 1.27.0** 官方输入核心；在 DeskBridge 选择 `deskflow-core`。Windows 只能用官方 portable 包且保留 `settings/Deskflow.conf`；本次 Windows 交付已附核心。macOS 路径通常为 `/Applications/Deskflow.app/Contents/MacOS/deskflow-core`，Ubuntu 原生包通常为 `/usr/bin/deskflow-core`。
2. 每台电脑启动 DeskBridge，使用不同的本机名称。分别复制各自的**公开指纹**；在另一台电脑屏幕核对完整 SHA-256，然后添加对端设备。不要复制 `.local`、私钥 PEM 或整个配置目录。
3. 键鼠连接所在电脑选择“共享键鼠”，其他电脑选择“接收键鼠”并选择已配对的共享端。**无需输入或固定 IP**；mDNS 按设备名称和配对身份发现当前地址。共享端端口默认 24800，mDNS 可自动获取；跨网段走电脑名寻址时，双方端口须相同，配对名称须与对端可由系统解析的电脑名一致。
4. 双方布局都包含已配对电脑；共享端的布局决定切换关系。拖动卡片，使电脑边缘相邻。首次进入 macOS / Wayland 后端须在系统弹窗授予核心权限。
5. 保存配置，启动共享端，再连接接收端。移动鼠标跨越所配置边缘切换。`Ctrl+Alt+F12` 返回共享端（Wayland 取决于 portal 热键支持）。停止或关闭应用结束共享。

DHCP 地址变化后会重新建立发现接口、更新服务地址；接收端发现已配对共享端地址变化时会重连。mDNS 需要同一组播网络并允许 UDP 5353。0.2.1 新增已配对电脑名的系统 DNS 备用寻址：不同网段或组播不可用时，只要系统能解析电脑名且 TCP 端口可达，就可尝试连接。备用路径每隔约 3 秒重新解析，仅接受私有局域网地址，连接仍须通过原有双向证书指纹校验。自定义名称若无法由系统解析，须依赖 mDNS。网络完全隔离时仍无法连接；应用不会自动新增防火墙规则。

自动共享模式监听本机网络接口，所有连接仍须通过双向 TLS 指纹校验。网络发现结果不自动授信；“添加并信任”前必须核对对端显示的完整指纹。已配对设备属于同一信任域。

## 平台支持边界

| 平台 | 实现后端 | 本次验证 / 条件 |
|---|---|---|
| Windows | 官方核心 Win32 输入捕获与注入 | 真实核心与界面可本机验证；普通用户模式，UAC 安全桌面不支持 |
| macOS Intel / Apple silicon | 官方核心 Quartz / 辅助功能 | 接口与发行包已确认，需对应 Mac 实测并授予实际核心输入权限 |
| Ubuntu Xorg | 官方核心 X11 / XTest | 需原生图形会话与 libXTest；尚未实机测试 |
| Ubuntu Wayland | 官方核心 libei + desktop portals | 条件性支持 GNOME/KDE；库版本及用户授权决定可用能力，剪贴板尤其受 libportal 版本限制 |

固定 1.27.0 官方 Ubuntu 原生包包括 26.04/26.10；Ubuntu 24.04/22.04 不能直接混装这些 deb，也不能换用旧核心冒充验证。旧版 Ubuntu 需在匹配依赖环境构建同版本或完成 Flatpak 适配；首版控制器尚未提供 Flatpak 沙箱启动适配。参见 [官方发行](https://github.com/deskflow/deskflow/releases/tag/v1.27.0)。

支持最多 8 台电脑、一个键鼠共享端、固定网格相邻切换、mDNS / 电脑名自动寻址与 DHCP 地址更新、双向证书指纹白名单、可选剪贴板（1 MiB）。0.3.1 新增 Windows 托盘与安装器。文件传输、自启动、IPv6、账号云同步与更新器仍未实现。

0.2.0 修复打包后启动核心时 Qt/ICU DLL 搜索路径冲突。请完整解压新包到新目录，保留 `engine` 和 `_internal`，不要混拷旧版 DLL。已保存的设备配对与本机身份可继续使用；无需删除用户配置目录。

0.2.1 修复“未发现已配对电脑”导致无法启动：增加电脑名备用寻址、按配对身份主动查询服务、首次查询超时后的重试，并在角色切换时立即更新广播。错误提示分别指出名称变化、对端接收模式或指纹不一致。原有配对与身份沿用，无需重新配对。

0.3.0 修复 Mac 接收端未选择共享端的配置错误：只有一台已配对设备时默认选中；多台仍须明确选择。扩展 Mac 核心安装路径检测，支持选择 Deskflow.app。新增 Windows 接收端的实验性锁屏服务安装工具，普通 GUI 不自动安装服务；管理员安装前阅读 [锁屏说明与安全评审](docs/lock-screen.md)。服务须在接收端实机验收，不能将普通进程测试当作锁屏成功。

## 命令行与构建

```sh
python app.py --doctor
python app.py --fingerprint
python app.py --profile /path/to/deskbridge-profile --prepare
python app.py --run
python -m unittest discover -s tests -v
```

`--prepare` 和 `--run` 使用先前由界面保存的配置。诊断只检查核心版本，不替代系统输入权限与双机效果验证。

```sh
python -m pip install --only-binary=:all: -r requirements-build.txt
python tools/build.py
```

须分别在目标系统构建，PyInstaller 不跨系统生成二进制。Windows 精简包包含未修改的官方核心及所需运行库；macOS / Ubuntu 的 `tools/installers.py` 将对应已校验的官方核心纳入原生安装包，仍须在对应系统构建并验收。源码直接运行时需单独安装核心。GitHub 手动构建工作流已提供，未运行的 job 不能视为通过。发布前阅读 THIRD_PARTY_NOTICES.md。

## 安全约束

TLS 与双方指纹白名单强制启用，没有“不安全连接”选项。首次配对须人工核对完整指纹，不自动信任网络发现值。配置路径隔离，POSIX 目录权限 0700 / 文件 0600，Windows 使用当前用户及 SYSTEM ACL；日志使用 INFO，只保留有限行数，不记录键值或剪贴板内容。配置生成拒绝注入字符，进程启动使用参数数组、不经过 shell。

继承核心的指纹集合不绑定设备名称，不能用于多租户授权；另有本地 IPC 边界需人工安全评审。详细交付自查见 [安全说明](docs/security-review.md)。
