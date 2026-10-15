# 安装包构建与发布

0.3.1 已生成 Windows 安装版、Mac Apple silicon / Intel DMG、Ubuntu 26.04 amd64 DEB，并通过原生 CI 安装及启动检查。实际日志、范围及未覆盖项目见 [验证记录](validation.md)。

| 目标 | 产物 | 当前构建条件 |
|---|---|---|
| Windows 10/11 x64 | `DeskBridge-0.3.1-windows-x64-setup.exe` | Inno Setup 安装版；自带 Python、Tk、Deskflow 核心 |
| Mac Apple silicon | `DeskBridge-0.3.1-macos-arm64.dmg` | 原生 Mac 构建；内含 `.app` 与官方核心 |
| Mac Intel | `DeskBridge-0.3.1-macos-x86_64.dmg` | 原生 Intel Mac 构建；内含 `.app` 与官方核心 |
| Ubuntu 26.04 amd64 | `DeskBridge-0.3.1-ubuntu-26.04-amd64.deb` | 对应 Ubuntu 构建；包内核心 + APT 安装系统库依赖 |

固定版本输入核心的旧版 Ubuntu 兼容性仍受上游依赖限制。暂不承诺 22.04/24.04 能安装 26.04 的包。Mac 包使用开发用 ad-hoc 签名，没有 Apple Developer ID 公证；对外正式分发前需配置开发者签名和公证，不能关闭 Gatekeeper 来冒充签名通过。

## 本机构建

使用 Python 3.12+；先在独立 venv 安装 `requirements-build.lock`。每个平台先执行：

```sh
python tools/fetch_native.py
python tools/build.py
```

下载器只使用固定的官方 Deskflow 1.27.0 发行地址，校验已固定 SHA-256；没有任意 URL 下载入口。Windows ZIP 解压受目录、链接、文件数和体积限制。来源及原始摘要：[上游发行资产](https://github.com/deskflow/deskflow/releases/expanded_assets/v1.27.0)。

Windows 使用官方 Inno Setup 6.7.3 编译器，校验微软 winget 清单公布的摘要与发布者签名；可用 `tools/bootstrap-inno.ps1` 安装到工作区 `build/tools/inno`。已有编译器时：

```powershell
python tools/package.py
python tools/installers.py --iscc 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe'
python tools/checksums.py
```

macOS 根据 CPU 使用下载的对应 DMG：

```sh
python tools/installers.py --native vendor/cache/deskflow-1.27.0-macos-arm64.dmg
python tools/checksums.py
```

Intel 将 `arm64` 改为 `x86_64`。运行构建前须先安装 Tk；官方 DMG 仅只读挂载，完整保留上游核心的框架路径与符号链接。

Ubuntu 26.04 安装构建所需的 Python venv/Tk 以及已校验原生包的依赖后：

```sh
python tools/installers.py --native vendor/cache/deskflow-1.27.0-ubuntu-resolute-x86_64.deb
python tools/checksums.py
```

最终用户用 `sudo apt install ./DeskBridge-0.3.1-ubuntu-26.04-amd64.deb` 安装。安装器只声明官方核心依赖，不拼接网络返回脚本或关闭系统权限。

## GitHub

GitHub `workflow` 授权已完成，`.github/workflows/installers.yml` 已启用。`platform` 可选 all、unix（Mac + Ubuntu）、macos 或 ubuntu，以便只重建需要的目标。仓库保留 `packaging/installers.yml.example` 作为模板；实际构建结果以对应运行日志和 Release 附件为准。

工作流 `.github/workflows/installers.yml` 仅允许手动运行，使用 Windows、Mac ARM / Intel、Ubuntu 对应 runner。默认内容只读、checkout 不保存凭据；仅发布草稿的 job 有仓库内容写权限。所有 Action 固定提交，输入核心固定摘要。不开启 PR 中有秘密权限的构建。

在 Actions → Build native installers → Run workflow 运行。成功后所选平台的安装包及 SHA-256 清单出现在该次运行的 Artifacts。勾选 `draft_release` 会在所选目标成功后创建或补齐 v0.3.1 草稿 Release，不修改已正式发布版本的附件。Intel Mac 从固定摘要的官方 cryptography 50.0.2 源码构建，Cargo 使用上游锁文件，OpenSSL 静态链接；构建工具 maturin 固定 1.14.1。DMG 完成后额外校验镜像，挂载后复制到独立目录，再验证应用签名、身份持久化及随包核心加载。对外发布前仍需实际键鼠与系统权限验收。Mac Developer ID 签名/公证、实验锁屏服务安全评审仍为后续工作。

不得提交 `.venv`、`build`、`dist`、用户配置、PEM、身份快照或访问令牌。安装包作为 Release 附件上传，不放进 Git 提交。公开仓库前需人工安全评审现有上游 IPC / 原生输入边界以及第三方发布许可材料。
