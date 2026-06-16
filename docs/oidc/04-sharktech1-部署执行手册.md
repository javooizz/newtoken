# sharktech1 · 多母号 OIDC 部署执行手册

> 配套文档：[01-设计方案](./01-设计方案.md)、[02-实施计划](./02-实施计划.md)、[03-落地部署与运维指南](./03-落地部署与运维指南.md)
>
> 本手册是针对 **sharktech1** 这台服务器的**具体执行 runbook**，参数已全部填实。日期：2026-06-16。

## 一、本次目标与范围

- **只部署 OIDC 服务**（`oidc/`，PHP + MySQL 多母号版，`feat/javoo` 分支）。WebUI（Python）留待后续。
- **验收边界**：服务跑通（discovery / jwks 可访问）、后台 `/admin` 可登录、用 `clients_admin_api_key` 能建母号。真正接入 OpenAI 母号（DNS TXT + Custom OIDC）属后续运维 SOP，不阻塞本次。

## 二、服务器实况（已探查）

| 项 | 值 |
|---|---|
| 主机 | `sharktech1`（ssh），root |
| 系统 | Debian 12 (bookworm) x86_64 |
| 面板 | 宝塔 |
| 配置 | 125G 内存 / 96 核 |
| 公网 IP | `107.167.27.42` |
| 系统盘 `/` | 23G，**剩 ~12G**（紧张） |
| 数据盘 `/home` | **1.8T，剩 ~1.5T** |
| 现有 | 已有 10 个站点（onebool.com / 1bool.com / sut.edu.kg 系）；PHP、MySQL **均未安装** |

## 三、最终部署参数

| 维度 | 值 |
|---|---|
| OIDC 服务域名 (issuer) | `https://oidc.1bool.com` |
| DNS | `oidc.1bool.com` 走 **Cloudflare 代理**（橙云，解析到 CF IP `104.21.x`/`172.67.x`）；源站 `107.167.27.42` |
| SSL | **复用现有 `*.1bool.com` 泛域名证书**（TrustAsia DV，SAN 含 `*.1bool.com`，90天，宝塔+CF DNS API 自动续）；**不走** Let's Encrypt HTTP-01（CF 橙云会挡） |
| 网站目录（代码+storage） | `/home/www/gpt-oidc`（运行目录 `/public`） |
| 数据盘统一根 | `/home/server-data` |
| MySQL 数据目录 | `/home/server-data/mysql` |
| PHP | 8.2（扩展：`intl`、`pdo_mysql`、`openssl`、`fileinfo`） |
| MySQL | 8.0 |
| 数据库 | 库 `gptoidc` / 用户 `gptoidc` / `utf8mb4` / `127.0.0.1:3306` |
| 代码上传方式 | 本地打包 `scp` |

### 数据盘软链布局（关键）

```
/home/server-data/                        数据盘统一数据根（1.5T）
  └─ mysql/                               MySQL datadir
/www/server/server-data  ─软链→  /home/server-data         统一入口（你的约定）
/www/server/data         ─软链→  /home/server-data/mysql   宝塔 MySQL 写死认这个路径
```

> 宝塔把**程序本体**写死装在系统盘 `/www/server`（PHP ~400M、MySQL ~1.5G，均不增长，无害）。能放数据盘的是**会增长的数据**：MySQL 库文件、网站代码、`storage/`，本方案已全部指向 `/home`。

## 四、执行阶段（标注 🧑你做 / 🤖我做）

### 阶段 0 · DNS 解析 〔🧑 你做〕
到 1bool.com 的 DNS 服务商加记录：`A  oidc  107.167.27.42`。
验证：`dig +short oidc.1bool.com` 返回 `107.167.27.42`（我可帮你验）。

### 阶段 0.5 · 数据盘软链 〔🤖 我做，MySQL 安装前置〕
```bash
mkdir -p /home/server-data/mysql
ln -sfn /home/server-data        /www/server/server-data
ln -sfn /home/server-data/mysql  /www/server/data   # 让宝塔 MySQL 数据直接落数据盘
```
验证：`df -h /www/server/data` 显示落在 `/home`（nvme0n1p6）。
⚠️ **必须在你去面板装 MySQL 之前完成。**

### 阶段 1 · 宝塔装环境 〔🧑 你做〕
软件商店：
1. **PHP 8.2** → 安装 → 设置→安装扩展，确认勾上 **`intl`**（必须，域名归一化）、`pdo_mysql`、`openssl`、`fileinfo`。
2. **MySQL 8.0** → 安装。
装完 → 🤖 我复查：`php -m`（intl/pdo_mysql/openssl 在列）、MySQL 起来了、且 `df` 确认数据目录在 `/home/server-data/mysql`；并 `chown -R mysql:mysql /home/server-data/mysql`。
> 回退：若某宝塔版本安装时把 `/www/server/data` 重建成真目录、数据写回了系统盘 → 用宝塔面板「数据库目录迁移」挪到 `/home/server-data/mysql`。

### 阶段 2 · 建站 + 库 + SSL 〔🧑 你做〕
1. 网站 → 添加站点（PHP 项目）：
   - 域名 `oidc.1bool.com`
   - 根目录 `/home/www/gpt-oidc`
   - PHP 版本 **8.2**
   - 一起建数据库：库名 `gptoidc`、用户 `gptoidc`、字符集 `utf8mb4`（**记下密码**）
2. 网站设置 → 网站目录 → **运行目录设为 `/public`** ⚠️（让 `app/ sql/ storage/` 落在 web 根之外）。
3. SSL：**复用现有 `*.1bool.com` 泛域名证书**（建完站把该证书部署到本站 → 开**强制 HTTPS**）。**不要走 Let's Encrypt HTTP-01**——域名在 CF 橙云后会被挡。

### 阶段 3 · 传码 + 初始化 〔🤖 我做〕
```bash
# 本地打包 oidc/（排除 storage 运行时与 config.php）→ scp → 解压到 /home/www/gpt-oidc
mkdir -p /home/www/gpt-oidc/storage/{keys,exports,ratelimits}
chown -R www:www /home/www/gpt-oidc
chmod -R 750 /home/www/gpt-oidc/storage
# 伪静态（宝塔 rewrite/oidc.1bool.com.conf）
#   location / { try_files $uri $uri/ /index.php?$query_string; }
#   location ~* ^/(app|sql|storage)/ { return 403; }
php /home/www/gpt-oidc/cli/tests/run.php   # 期望 11/11
```

### 阶段 4 · 安装向导 〔🧑 你点浏览器〕
打开 `https://oidc.1bool.com/install`，**只填**：
- 应用地址 `https://oidc.1bool.com`
- MySQL：`127.0.0.1` / `3306` / `gptoidc` / `gptoidc` / 阶段2密码
- 首个管理员：用户名 / 邮箱 / 密码（**≥10 位**）
- **其余旧字段（client_id/secret/redirect/api_key/允许域名）全部留空**（新逻辑忽略，两个 api_key 会自动生成）

提交后自动：建表、生成 `app_key`/`app_pepper`/`cards_api_key`/`clients_admin_api_key`、生成 RSA 密钥、建管理员并登录。
然后 `/admin` → 点一次「**公开文件补救**」生成真实 discovery/jwks 文件。

### 阶段 5 · 验证 + 交付 〔🤖 我做〕
```bash
curl -s https://oidc.1bool.com/.well-known/openid-configuration | head
curl -s https://oidc.1bool.com/jwks.json | head
# 从 /home/www/gpt-oidc/app/config.php 读出两个 api_key
curl -s https://oidc.1bool.com/api/status -H "Authorization: Bearer <cards_api_key>"
curl -s https://oidc.1bool.com/api/clients -X POST \
  -H "Authorization: Bearer <clients_admin_api_key>" -H "Content-Type: application/json" \
  -d '{"name":"测试母号","allowed_domains":["test.example.com"],"redirect_uris":[]}'
```
**达标** = discovery/jwks 正常 + `/admin` 可登录 + 建母号成功 → 整理「交付卡」（issuer / 各 endpoint / 两个 api_key / 后台地址）。

### 阶段 6 · 接入真实母号 〔后续 SOP，不在本次〕
见 [03-落地部署与运维指南](./03-落地部署与运维指南.md) 第六节：OpenAI 验证母号域名 DNS TXT → 后台建母号 → OpenAI 配 Custom OIDC → 回填 callback → 测试沙箱 → 发卡。

## 五、风险点与卡控

1. **`intl` 扩展**别漏（阶段1）——缺了 `idn_to_ascii` 域名归一化 fatal。
2. **运行目录必须 `/public`**（阶段2）——否则 `app/ sql/ storage/` 暴露。
3. **安装向导旧字段留空**（阶段4）。
4. **MySQL 数据落盘**（阶段0.5/1）——我装完会 `df` 实测确认在 `/home`，不在再迁移。

### Cloudflare 注意（本站走 CF 橙云代理）
- **SSL 模式**：CF 侧用 **Full / Full(strict)**（源站已有真证书 `*.1bool.com`）。
- **真实 IP**：源站 `REMOTE_ADDR` 是 CF 的 IP，真实客户端在 `CF-Connecting-IP` 头。影响 OIDC 的**限流**（`app_ip()`）与**审计日志 IP**；`clients_admin_ip_allowlist` 在 CF 后不可靠（本期默认不启用）。后续可在 nginx/PHP 还原真实 IP。
- **接 OpenAI 时**：`/token`、`/userinfo` 是 OpenAI **服务端**调用，CF 的 Bot Fight Mode / 严格 WAF 可能拦截——接母号若回调异常，先查 CF 是否拦了这些路径。
- **缓存**：别让 CF 缓存动态路径（`/authorize`、`/token`、`/userinfo`、`/api/*`、`/sso`、`/admin`）；`/.well-known/openid-configuration`、`/jwks.json` 缓存无害。

## 六、谁做什么（总览）

- 🧑 你：阶段 0（DNS）、阶段 1（装 PHP/MySQL）、阶段 2（建站/库/SSL）、阶段 4（点安装向导）
- 🤖 我：阶段 0.5（数据盘软链）、阶段 3（传码/权限/伪静态/自测）、阶段 5（验证/交付）

## 七、实际部署完成记录（2026-06-16）

✅ 全部完成，验收通过。

**实际落地确认**：
- 服务 `https://oidc.1bool.com`（经 Cloudflare，源站 107.167.27.42）；代码 `/home/www/gpt-oidc`，运行目录 `public`
- MySQL 数据 `/home/server-data/mysql`（数据盘，实测 4.2G 全在 /home，系统盘零占用）
- PHP **8.2.31** + MySQL **8.0.45**；`intl`/`openssl`/`pdo_mysql` 实测可用
- SSL 复用 `*.1bool.com` 泛域名证书；安装向导完成，两个 api_key 自动生成、RSA 密钥生成、管理员建立；公开文件补救已执行（discovery/jwks 真实静态文件已生成）

**验收结果**：纯逻辑自测 11/11；discovery/jwks 正常（源站+外部CF+真实文件三路）；`/admin` 可登录；`/api/status`(cards key)、`/api/clients`(clients_admin key) 均通；建母号完整写链路验证通过（测试母号已删，库干净）。

**部署中发现并修复（⚠️ 建议提交 git）**：
- `app/bootstrap.php`：新增按 `app_debug` 控制 `display_errors`/`error_reporting`，生产隐藏 PHP warning，避免污染 JSON 端点。
- `app/views.php`：`app_settings_form_html` 旧字段（`allowed_email_domains`/`oidc_allowed_redirect_uris`/`oidc_client_id`/`oidc_client_secret`）读取加 `?? ` 兜底，消除多母号架构下的 `Undefined array key` warning。
- 根因：新版 config 已移除旧单-client 字段，但 settings 表单仍读取它们，叠加宝塔 PHP 默认 `display_errors=On`。

**敏感交付信息**（api_key / 密码 / 管理员）不写入本文档，见部署会话交付卡。**后续**接入真实母号见第六节 SOP。
