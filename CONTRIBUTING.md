# 参与贡献

欢迎通过 [Issues](https://github.com/randyzxr/deskbridge/issues) 反馈问题或提出建议，通过 Fork 和 Pull Request 提交修改。当前版本是开发预览版，平台支持与已知限制见 README 和 `docs/security-review.md`。

反馈问题时请提供系统版本、CPU 架构、DeskBridge 版本、共享端/接收端角色、复现步骤与已脱敏的错误信息。不要上传私钥 PEM、配对配置、访问令牌、实际键鼠或剪贴板内容。

源码运行需要 Python 3.12+ 和 Tk，步骤见 README。提交前运行：

```sh
python -m unittest discover -s tests -v
```

涉及系统输入、托盘或打包的修改，还应在对应系统验证；请在 PR 中说明实际验证的系统与尚未验证的部分。认证、TLS、指纹核对及系统权限检查须保留。

DeskBridge 独立控制器采用 MIT 许可证。提交贡献前请确认你有权提供相应内容；第三方核心、补丁及依赖继续遵循 `THIRD_PARTY_NOTICES.md` 中列出的许可证与对应源码要求。
