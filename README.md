# Sub2API 独立工具
全部教程 在 https://app.notion.com/p/48-ChatGPT-Team-23-6-25-37f435e8d42d803f8a13dfea1c765c10
只保留 `Sub2API + ACC 席位管理` 的单页工具公开版。

## 功能

- Sub2API 远程账号统计、刷新、启停、删死号、一键隐私
- OpenAI OAuth 一键授权建号
- ACC 成员席位管理
- `recover-state -> refresh token -> 查额度 -> 开/关调度` 自动联动
- 单文件 exe 首次启动自动生成 `.env`
- GitHub Release 自动挂 exe，客户端可直接点“一键更新”

## 本地运行

```powershell
py .\sub2api_standalone_tool.py
```

或直接双击：

```text
启动Sub2API独立工具.bat
```

## 打包 exe

```powershell
py .\build_sub2api_standalone_exe.py --onefile
```

输出文件：

- `dist\Sub2API独立工具.exe`

## 隐私说明

- `.env`
- `*.har`
- 本地缓存文件

这些都已在本目录 `.gitignore` 中忽略，不应该上传。

## 自动 Release

- 推送到 `main`：自动更新 `latest` Release，并重新挂载最新 exe
- 推送 `v*` 标签：自动创建对应版本 Release，并挂载 exe

默认更新仓库：

- [DZenner/newtoken](https://github.com/DZenner/newtoken)
