# GPT OIDC PHP 环境配置

## 宝塔 PHP 安装

宝塔面板 -> 软件商店 -> PHP -> 安装 PHP 7.4

## 必装扩展

PHP 设置 -> 安装扩展，勾选：

| 扩展 | 作用 |
|------|------|
| pdo_mysql | 数据库连接 |
| openssl | RSA 密钥生成 / JWT 签名 |

## 需禁用的函数

PHP 设置 -> 禁用函数，确认以下在禁用列表：

| 函数 | 原因 |
|------|------|
| exec | 安全 |
| system | 安全 |
| passthru | 安全 |
| shell_exec | 安全 |
| popen | 安全 |
| proc_open | 安全 |

## 需启用的函数

以下函数必须可用（不在禁用列表中）：

| 函数 | 作用 |
|------|------|
| file_get_contents | 读取密钥/配置/请求体 |
| file_put_contents | 写配置/密钥/卡密JSON |
| mkdir | 创建 storage 目录 |
| json_encode / json_decode | JSON 处理 |
| openssl_pkey_new | 生成 RSA 密钥对 |
| openssl_pkey_export | 导出私钥 |
| openssl_pkey_get_details | 读取公钥详情 |
| openssl_sign | JWT 签名 |
| hash_hmac | HMAC 哈希 |
| hash_equals | 时序安全比较 |
| password_hash / password_verify | bcrypt |
| random_bytes | 安全随机数 |
| bin2hex | 二进制转hex |

## PHP 配置建议

PHP 设置 -> 配置文件：

```ini
max_execution_time = 30
memory_limit = 128M
session.cookie_httponly = 1
session.cookie_samesite = Lax
session.cookie_secure = 1
```

## API 密钥（OIDC + WebUI 共享）

生成密钥（在 SSH 执行）：

```bash
php -r "echo bin2hex(random_bytes(32));"
```

把输出结果填到两个地方：

**OIDC 侧**（`app/config.php`）：
```php
'api_key' => '上面生成的64位hex',
```

**WebUI 侧**（`.env`）：
```ini
SUB2API_OIDC_API_KEY=上面生成的64位hex
SUB2API_OIDC_API_URL=https://oidc.你的域名.com
```

两个系统使用同一个密钥。WebUI 调用 OIDC API 时用 Bearer Token 认证。
