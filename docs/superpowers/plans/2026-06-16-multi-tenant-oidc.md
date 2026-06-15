# 多母号 OIDC（二次开发 oidc/）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有 `oidc/` PHP 服务上二次开发，使一套服务支持多个 OpenAI ChatGPT Business「team 母号」SSO（每母号独立 client + 独立域名，卡密全局共享、不隔离）。

**Architecture:** 新增 `oidc_clients` / `oidc_client_domains` 两表承载多母号；`/authorize`、`/token` 按请求 `client_id` 查表校验并解密 `client_secret`；卡密首次激活必须有 pending client 上下文；母号管理走 admin 后台 + 独立鉴权的 `/api/clients`。复用现有 OIDC 协议、卡密、安全机制。

**Tech Stack:** PHP 7.4+（过程式、`app_*` 全局函数）、MySQL 5.7+（PDO）、openssl（RSA / AES-256-GCM）、intl（`idn_to_ascii` 域名归一化）；零依赖纯 PHP 测试脚本（`oidc/cli/tests/`）。

**参考规格：** `docs/superpowers/specs/2026-06-16-multi-tenant-oidc-design.md`

---

## 文件结构

| 文件 | 创建/修改 | 职责 |
|---|---|---|
| `oidc/cli/tests/_bootstrap.php` | 创建 | 零依赖测试断言（`test`/`assert_eq`/`assert_true`/`assert_throws`） |
| `oidc/cli/tests/run.php` | 创建 | 测试 runner，遍历 `*_test.php` |
| `oidc/cli/tests/*_test.php` | 创建 | 各纯逻辑测试 |
| `oidc/sql/schema.sql` | 修改 | 加 `oidc_clients`、`oidc_client_domains`、`users.origin_client_id` |
| `oidc/app/clients.php` | 创建 | 母号 client model：域名归一化、secret 加解密、CRUD、校验 |
| `oidc/app/bootstrap.php` | 修改 | `require_once clients.php` |
| `oidc/app/oidc.php` | 修改 | `/authorize`、`/token` 改查 `oidc_clients` + 解密 secret |
| `oidc/public/index.php` | 修改 | `/authorize` 注入 pending 域名集合；`/sso` 首次激活需 pending |
| `oidc/app/users.php` | 修改 | `app_activate_user` 域名校验取自母号集合 + 写 `origin_client_id` |
| `oidc/app/api.php` | 修改 | 拆 `cards_api_key` / `clients_admin_api_key`，加 `/api/clients` CRUD |
| `oidc/app/admin.php` | 修改 | 母号管理页数据装配 |
| `oidc/app/views.php` | 修改 | 母号管理页 HTML |
| `oidc/app/config.sample.php` | 修改 | 加 `cards_api_key`/`clients_admin_api_key` 等配置项 |

## 测试约定

- **纯逻辑**（域名归一化、secret 加解密、redirect 白名单、IP allowlist 判断）→ 自动化：`php oidc/cli/tests/run.php`，期望末行 `N passed, 0 failed`、退出码 0。
- **DB / 端点 / UI**（建母号、authorize/token、登录页、后台）→ 每个相关 task 给出 `curl` 或浏览器手工验证清单（用户已确认采用此策略）。
- 每个 task 末尾 `commit`。提交前先跑 `php oidc/cli/tests/run.php` 确保纯逻辑测试全绿。

---

## Task 1: 零依赖测试脚手架

**Files:**
- Create: `oidc/cli/tests/_bootstrap.php`
- Create: `oidc/cli/tests/run.php`
- Create: `oidc/cli/tests/smoke_test.php`（临时冒烟，验证 runner 后删除）

- [ ] **Step 1: 写断言库 `_bootstrap.php`**

```php
<?php

// 零依赖测试脚手架：注册用例 + 断言

$GLOBALS['__tests'] = [];

function test(string $name, callable $fn): void
{
    $GLOBALS['__tests'][$name] = $fn;
}

function assert_eq($expected, $actual, string $msg = ''): void
{
    if ($expected !== $actual) {
        throw new Exception('assert_eq 失败: 期望 ' . var_export($expected, true) . '，实际 ' . var_export($actual, true) . ($msg ? " — $msg" : ''));
    }
}

function assert_true($cond, string $msg = ''): void
{
    if ($cond !== true) {
        throw new Exception('assert_true 失败' . ($msg ? ": $msg" : ''));
    }
}

function assert_throws(callable $fn, string $msg = ''): void
{
    try {
        $fn();
    } catch (Throwable $e) {
        return;
    }
    throw new Exception('assert_throws 失败: 未抛出异常' . ($msg ? " — $msg" : ''));
}
```

- [ ] **Step 2: 写 runner `run.php`**

```php
<?php

require __DIR__ . '/_bootstrap.php';

foreach (glob(__DIR__ . '/*_test.php') as $file) {
    require $file;
}

$pass = 0;
$fail = 0;
foreach ($GLOBALS['__tests'] as $name => $fn) {
    try {
        $fn();
        echo "PASS  $name\n";
        $pass++;
    } catch (Throwable $e) {
        echo "FAIL  $name: " . $e->getMessage() . "\n";
        $fail++;
    }
}
echo "\n$pass passed, $fail failed\n";
exit($fail > 0 ? 1 : 0);
```

- [ ] **Step 3: 写冒烟用例 `smoke_test.php`**

```php
<?php

test('smoke: runner works', function () {
    assert_eq(2, 1 + 1);
    assert_true(true);
    assert_throws(function () { throw new Exception('boom'); });
});
```

- [ ] **Step 4: 运行，确认 runner 工作**

Run: `php oidc/cli/tests/run.php`
Expected: 输出含 `PASS  smoke: runner works`，末行 `1 passed, 0 failed`，退出码 0。

- [ ] **Step 5: 删除冒烟用例**

```bash
rm oidc/cli/tests/smoke_test.php
```

- [ ] **Step 6: Commit**

```bash
git add oidc/cli/tests/_bootstrap.php oidc/cli/tests/run.php
git commit -m "test: add zero-dependency PHP test harness"
```

---

## Task 2: 数据库 schema 扩展

**Files:**
- Modify: `oidc/sql/schema.sql`（在文件末尾追加两张新表 + 给 `users` 加列）

- [ ] **Step 1: 在 `schema.sql` 末尾追加 `oidc_clients` 表**

```sql
CREATE TABLE IF NOT EXISTS oidc_clients (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    client_id VARCHAR(128) NOT NULL,
    client_secret_enc TEXT NOT NULL,
    name VARCHAR(190) NOT NULL,
    redirect_uris TEXT NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    note VARCHAR(255) NULL,
    created_by_admin_id BIGINT UNSIGNED NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    UNIQUE KEY uq_oidc_clients_client_id (client_id),
    KEY idx_oidc_clients_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

- [ ] **Step 2: 追加 `oidc_client_domains` 表**

```sql
CREATE TABLE IF NOT EXISTS oidc_client_domains (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    client_id VARCHAR(128) NOT NULL,
    domain_normalized VARCHAR(255) NOT NULL,
    domain_raw VARCHAR(255) NOT NULL,
    created_at DATETIME NOT NULL,
    UNIQUE KEY uq_client_domains_norm (domain_normalized),
    KEY idx_client_domains_client (client_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

- [ ] **Step 3: 给 `users` 表加 `origin_client_id` 列**

在 `users` 表的 `CREATE TABLE` 中，`activated_by_card_id` 行之后加入一行：

```sql
    origin_client_id VARCHAR(128) NULL,
```

（仅记录首次激活来自哪个母号，不加外键、不加约束。）

- [ ] **Step 4: 导入测试库验证结构**

Run:
```bash
mysql -uroot -p -e "CREATE DATABASE IF NOT EXISTS gptoidc_test CHARACTER SET utf8mb4;"
mysql -uroot -p gptoidc_test < oidc/sql/schema.sql
mysql -uroot -p gptoidc_test -e "SHOW TABLES; DESCRIBE oidc_clients; DESCRIBE oidc_client_domains; SHOW COLUMNS FROM users LIKE 'origin_client_id';"
```
Expected: `SHOW TABLES` 含 `oidc_clients`、`oidc_client_domains`；`uq_client_domains_norm` 唯一键存在；`users` 含 `origin_client_id`。

- [ ] **Step 5: Commit**

```bash
git add oidc/sql/schema.sql
git commit -m "feat(db): add oidc_clients, oidc_client_domains, users.origin_client_id"
```

---

## Task 3: 域名归一化纯函数（TDD）

**Files:**
- Create: `oidc/app/clients.php`（仅本任务先放归一化函数）
- Create: `oidc/cli/tests/domain_test.php`

- [ ] **Step 1: 写失败测试 `domain_test.php`**

```php
<?php

require_once __DIR__ . '/../../app/clients.php';

test('domain: lowercase + trim', function () {
    assert_eq('example.com', app_normalize_domain('  EXAMPLE.com  '));
});

test('domain: strip trailing dot', function () {
    assert_eq('example.com', app_normalize_domain('example.com.'));
});

test('domain: subdomain preserved + lowercased', function () {
    assert_eq('m1.example.com', app_normalize_domain('M1.Example.COM'));
});

test('domain: empty rejected', function () {
    assert_throws(function () { app_normalize_domain('   '); });
});

test('domain: spaces inside rejected', function () {
    assert_throws(function () { app_normalize_domain('bad domain.com'); });
});
```

- [ ] **Step 2: 运行确认失败**

Run: `php oidc/cli/tests/run.php`
Expected: FAIL，报 `app_normalize_domain()` 未定义（function not found）。

- [ ] **Step 3: 创建 `app/clients.php` 并实现归一化**

```php
<?php

/**
 * 母号 client model：域名归一化、secret 加解密、CRUD、校验。
 */

function app_normalize_domain(string $raw): string
{
    $d = strtolower(trim($raw));
    $d = rtrim($d, '.');
    if ($d === '') {
        throw new RuntimeException('域名不能为空。');
    }
    if (function_exists('idn_to_ascii')) {
        $ascii = idn_to_ascii($d, IDNA_DEFAULT, INTL_IDNA_VARIANT_UTS46);
        if ($ascii !== false) {
            $d = $ascii;
        }
    }
    if (!preg_match('/^[a-z0-9-]+(\.[a-z0-9-]+)+$/', $d)) {
        throw new RuntimeException('域名格式非法：' . $raw);
    }
    return $d;
}
```

- [ ] **Step 4: 运行确认通过**

Run: `php oidc/cli/tests/run.php`
Expected: 5 条 domain 用例 PASS，末行 `5 passed, 0 failed`。

- [ ] **Step 5: Commit**

```bash
git add oidc/app/clients.php oidc/cli/tests/domain_test.php
git commit -m "feat(clients): domain normalization with tests"
```

---

## Task 4: client_secret 加解密纯函数（TDD）

**Files:**
- Modify: `oidc/app/clients.php`（追加加解密函数）
- Create: `oidc/cli/tests/secret_test.php`

- [ ] **Step 1: 写失败测试 `secret_test.php`**

```php
<?php

require_once __DIR__ . '/../../app/clients.php';

test('secret: encrypt/decrypt round-trip', function () {
    $key = 'test-app-key-1234567890';
    $plain = 'csk_abcdef0123456789';
    $enc = app_secret_encrypt($plain, $key);
    assert_true($enc !== $plain, '密文不应等于明文');
    assert_eq($plain, app_secret_decrypt($enc, $key));
});

test('secret: wrong key fails', function () {
    $enc = app_secret_encrypt('hello', 'key-A');
    assert_throws(function () use ($enc) { app_secret_decrypt($enc, 'key-B'); });
});

test('secret: tampered ciphertext fails', function () {
    $enc = app_secret_encrypt('hello', 'key-A');
    $bad = $enc . 'XX';
    assert_throws(function () use ($bad) { app_secret_decrypt($bad, 'key-A'); });
});
```

- [ ] **Step 2: 运行确认失败**

Run: `php oidc/cli/tests/run.php`
Expected: FAIL，`app_secret_encrypt()` 未定义。

- [ ] **Step 3: 在 `app/clients.php` 追加加解密**

```php
function app_secret_encrypt(string $plain, string $key): string
{
    $k = substr(hash('sha256', $key, true), 0, 32);
    $iv = random_bytes(12);
    $tag = '';
    $cipher = openssl_encrypt($plain, 'aes-256-gcm', $k, OPENSSL_RAW_DATA, $iv, $tag);
    if ($cipher === false) {
        throw new RuntimeException('secret 加密失败。');
    }
    return base64_encode($iv . $tag . $cipher);
}

function app_secret_decrypt(string $enc, string $key): string
{
    $k = substr(hash('sha256', $key, true), 0, 32);
    $raw = base64_decode($enc, true);
    if ($raw === false || strlen($raw) < 28) {
        throw new RuntimeException('secret 密文非法。');
    }
    $iv = substr($raw, 0, 12);
    $tag = substr($raw, 12, 16);
    $cipher = substr($raw, 28);
    $plain = openssl_decrypt($cipher, 'aes-256-gcm', $k, OPENSSL_RAW_DATA, $iv, $tag);
    if ($plain === false) {
        throw new RuntimeException('secret 解密失败。');
    }
    return $plain;
}
```

- [ ] **Step 4: 运行确认通过**

Run: `php oidc/cli/tests/run.php`
Expected: secret 3 条 PASS，全部 `8 passed, 0 failed`。

- [ ] **Step 5: Commit**

```bash
git add oidc/app/clients.php oidc/cli/tests/secret_test.php
git commit -m "feat(clients): AES-256-GCM secret encrypt/decrypt with tests"
```

---

## Task 5: redirect_uri 白名单纯函数（TDD）

**Files:**
- Modify: `oidc/app/clients.php`（追加 `app_client_redirect_allowed`）
- Create: `oidc/cli/tests/redirect_test.php`

- [ ] **Step 1: 写失败测试 `redirect_test.php`**

```php
<?php

require_once __DIR__ . '/../../app/clients.php';

test('redirect: exact match allowed', function () {
    $client = ['redirect_uris' => json_encode(['https://external.auth.openai.com/sso/oidc/AAA/callback'])];
    assert_true(app_client_redirect_allowed($client, 'https://external.auth.openai.com/sso/oidc/AAA/callback'));
});

test('redirect: non-listed rejected', function () {
    $client = ['redirect_uris' => json_encode(['https://a/cb'])];
    assert_eq(false, app_client_redirect_allowed($client, 'https://evil/cb'));
});

test('redirect: empty/invalid json rejected', function () {
    assert_eq(false, app_client_redirect_allowed(['redirect_uris' => ''], 'https://a/cb'));
});
```

- [ ] **Step 2: 运行确认失败**

Run: `php oidc/cli/tests/run.php`
Expected: FAIL，`app_client_redirect_allowed()` 未定义。

- [ ] **Step 3: 在 `app/clients.php` 追加**

```php
function app_client_redirect_allowed(array $client, string $redirectUri): bool
{
    $list = json_decode($client['redirect_uris'] ?? '[]', true);
    if (!is_array($list)) {
        return false;
    }
    return in_array($redirectUri, $list, true);
}
```

- [ ] **Step 4: 运行确认通过**

Run: `php oidc/cli/tests/run.php`
Expected: `11 passed, 0 failed`。

- [ ] **Step 5: Commit**

```bash
git add oidc/app/clients.php oidc/cli/tests/redirect_test.php
git commit -m "feat(clients): redirect_uri allowlist check with tests"
```

---

## Task 6: 母号 client model（DB 层）

**Files:**
- Modify: `oidc/app/clients.php`（追加 DB model 函数）
- Modify: `oidc/app/bootstrap.php`（引入 `clients.php`）
- Create: `oidc/cli/tmp_client_check.php`（临时验证，跑完即删）

依赖现有 helper：`app_db_one`/`app_db_all`/`app_db_exec`/`app_pdo`（db.php）、`app_random_hex`（security.php）、`app_now`（http/其他）、`app_config`、`app_audit`。

- [ ] **Step 1: 在 `app/clients.php` 末尾追加 model 函数**

```php
function app_client_secret_key(): string
{
    return (string) app_config('app_key', '');
}

function app_client_find(string $clientId): ?array
{
    $row = app_db_one('SELECT * FROM oidc_clients WHERE client_id = :cid LIMIT 1', ['cid' => $clientId]);
    return $row ?: null;
}

function app_client_find_by_domain(string $domainNorm): ?array
{
    $row = app_db_one(
        'SELECT c.* FROM oidc_client_domains d JOIN oidc_clients c ON c.client_id = d.client_id WHERE d.domain_normalized = :n LIMIT 1',
        ['n' => $domainNorm]
    );
    return $row ?: null;
}

function app_client_domains(string $clientId): array
{
    $rows = app_db_all('SELECT domain_normalized FROM oidc_client_domains WHERE client_id = :cid ORDER BY domain_normalized', ['cid' => $clientId]);
    return array_map(function ($r) { return $r['domain_normalized']; }, $rows);
}

function app_client_add_domains(string $clientId, array $rawDomains): void
{
    foreach ($rawDomains as $raw) {
        $norm = app_normalize_domain($raw);
        $existing = app_client_find_by_domain($norm);
        if ($existing && $existing['client_id'] !== $clientId) {
            throw new RuntimeException('域名 ' . $norm . ' 已被母号「' . $existing['name'] . '」占用。');
        }
        if ($existing && $existing['client_id'] === $clientId) {
            continue;
        }
        app_db_exec('INSERT INTO oidc_client_domains (client_id, domain_normalized, domain_raw, created_at) VALUES (:cid, :norm, :raw, :c)', [
            'cid' => $clientId, 'norm' => $norm, 'raw' => $raw, 'c' => app_now(),
        ]);
    }
}

function app_client_openai_config(string $clientId): array
{
    $issuer = rtrim((string) app_config('oidc_issuer', app_config('app_url', '')), '/');
    return [
        'issuer' => $issuer,
        'discovery_url' => $issuer . '/.well-known/openid-configuration',
        'authorization_endpoint' => $issuer . '/authorize',
        'token_endpoint' => $issuer . '/token',
        'userinfo_endpoint' => $issuer . '/userinfo',
        'jwks_uri' => $issuer . '/jwks.json',
        'scopes' => 'openid profile email',
        'client_id' => $clientId,
    ];
}

function app_client_create(array $in, ?int $adminId): array
{
    $name = trim((string) ($in['name'] ?? ''));
    if ($name === '') {
        throw new RuntimeException('母号名称不能为空。');
    }
    $redirects = array_values(array_unique(array_filter(array_map('trim', (array) ($in['redirect_uris'] ?? [])))));
    $domainsRaw = array_values(array_unique(array_filter(array_map('trim', (array) ($in['allowed_domains'] ?? [])))));

    $clientId = 'cid_' . app_random_hex(16);
    $secretPlain = 'csk_' . app_random_hex(32);
    $secretEnc = app_secret_encrypt($secretPlain, app_client_secret_key());

    $pdo = app_pdo();
    $pdo->beginTransaction();
    try {
        app_db_exec('INSERT INTO oidc_clients (client_id, client_secret_enc, name, redirect_uris, status, note, created_by_admin_id, created_at, updated_at) VALUES (:cid, :sec, :name, :ru, :status, :note, :admin, :c, :u)', [
            'cid' => $clientId,
            'sec' => $secretEnc,
            'name' => $name,
            'ru' => json_encode($redirects),
            'status' => 'active',
            'note' => isset($in['note']) ? (string) $in['note'] : null,
            'admin' => $adminId,
            'c' => app_now(),
            'u' => app_now(),
        ]);
        app_client_add_domains($clientId, $domainsRaw);
        $pdo->commit();
    } catch (Exception $e) {
        $pdo->rollBack();
        throw $e;
    }

    app_audit($adminId ? 'admin' : 'system', $adminId, 'client_created', 'client', $clientId, ['name' => $name, 'domains' => $domainsRaw]);

    return [
        'client_id' => $clientId,
        'client_secret' => $secretPlain,
        'name' => $name,
        'redirect_uris' => $redirects,
        'allowed_domains' => app_client_domains($clientId),
        'openai_config' => app_client_openai_config($clientId),
    ];
}

function app_client_authenticate(string $clientId, string $clientSecret): bool
{
    $client = app_client_find($clientId);
    if (!$client || $client['status'] !== 'active') {
        return false;
    }
    try {
        $plain = app_secret_decrypt($client['client_secret_enc'], app_client_secret_key());
    } catch (Exception $e) {
        return false;
    }
    return hash_equals($plain, (string) $clientSecret);
}

function app_client_list(): array
{
    $clients = app_db_all('SELECT * FROM oidc_clients ORDER BY id DESC');
    foreach ($clients as &$c) {
        $c['domains'] = app_client_domains($c['client_id']);
    }
    unset($c);
    return $clients;
}

function app_client_update(string $clientId, array $changes, ?int $adminId): void
{
    if (!app_client_find($clientId)) {
        throw new RuntimeException('母号不存在。');
    }
    $fields = [];
    $params = ['cid' => $clientId, 'u' => app_now()];
    if (isset($changes['name'])) {
        $name = trim((string) $changes['name']);
        if ($name === '') { throw new RuntimeException('母号名称不能为空。'); }
        $fields[] = 'name = :name'; $params['name'] = $name;
    }
    if (isset($changes['redirect_uris'])) {
        $ru = array_values(array_unique(array_filter(array_map('trim', (array) $changes['redirect_uris']))));
        $fields[] = 'redirect_uris = :ru'; $params['ru'] = json_encode($ru);
    }
    if (isset($changes['status'])) {
        $fields[] = 'status = :st'; $params['st'] = $changes['status'] === 'disabled' ? 'disabled' : 'active';
    }
    if ($fields) {
        $fields[] = 'updated_at = :u';
        app_db_exec('UPDATE oidc_clients SET ' . implode(', ', $fields) . ' WHERE client_id = :cid', $params);
    }
    if (isset($changes['allowed_domains'])) {
        $raw = array_values(array_unique(array_filter(array_map('trim', (array) $changes['allowed_domains']))));
        app_db_exec('DELETE FROM oidc_client_domains WHERE client_id = :cid', ['cid' => $clientId]);
        app_client_add_domains($clientId, $raw);
    }
    app_audit($adminId ? 'admin' : 'system', $adminId, 'client_updated', 'client', $clientId, array_keys($changes));
}

function app_client_rotate_secret(string $clientId, ?int $adminId): string
{
    if (!app_client_find($clientId)) {
        throw new RuntimeException('母号不存在。');
    }
    $secretPlain = 'csk_' . app_random_hex(32);
    app_db_exec('UPDATE oidc_clients SET client_secret_enc = :sec, updated_at = :u WHERE client_id = :cid', [
        'sec' => app_secret_encrypt($secretPlain, app_client_secret_key()), 'u' => app_now(), 'cid' => $clientId,
    ]);
    app_audit($adminId ? 'admin' : 'system', $adminId, 'client_secret_rotated', 'client', $clientId, []);
    return $secretPlain;
}

function app_client_reveal_secret(string $clientId): string
{
    $client = app_client_find($clientId);
    if (!$client) { throw new RuntimeException('母号不存在。'); }
    return app_secret_decrypt($client['client_secret_enc'], app_client_secret_key());
}
```

- [ ] **Step 2: 在 `app/bootstrap.php` 引入 `clients.php`**

在 `require_once __DIR__ . '/views.php';`（第 12 行）之后追加一行：

```php
require_once __DIR__ . '/clients.php';
```

- [ ] **Step 3: 写临时验证脚本 `cli/tmp_client_check.php`**

> 前提：`oidc/app/config.php` 已指向一个可写测试/开发 MySQL，且已导入 `sql/schema.sql`（即 Task 2 的库）。脚本顶部把请求路径伪装成无 session 的 `/token`，避免 CLI 下 `session_start` 干扰。

```php
<?php

$_SERVER['REQUEST_URI'] = '/token';
require __DIR__ . '/../app/bootstrap.php';

$a = app_client_create([
    'name' => '母号A',
    'redirect_uris' => ['https://external.auth.openai.com/sso/oidc/AAA/callback'],
    'allowed_domains' => ['A.Example.com'],
], null);
echo "created client_id={$a['client_id']} secret_len=" . strlen($a['client_secret']) . "\n";
echo 'domains=' . json_encode($a['allowed_domains']) . "\n";          // 期望 ["a.example.com"]

echo 'auth_ok=' . var_export(app_client_authenticate($a['client_id'], $a['client_secret']), true) . "\n";   // true
echo 'auth_bad=' . var_export(app_client_authenticate($a['client_id'], 'wrong'), true) . "\n";              // false

$byDom = app_client_find_by_domain('a.example.com');
echo 'find_by_domain=' . ($byDom['client_id'] ?? 'NULL') . "\n";       // 同 a.client_id

try {
    app_client_create(['name' => '母号B', 'redirect_uris' => ['https://b/cb'], 'allowed_domains' => ['a.example.com']], null);
    echo "DUP-NOT-CAUGHT (BUG)\n";
} catch (Exception $e) {
    echo 'dup_rejected=' . $e->getMessage() . "\n";                    // 域名 a.example.com 已被母号「母号A」占用。
}
```

- [ ] **Step 4: 运行验证**

Run: `php oidc/cli/tmp_client_check.php`
Expected:
- `domains=["a.example.com"]`（大小写归一化生效）
- `auth_ok=true`、`auth_bad=false`
- `find_by_domain=` 等于创建的 client_id
- `dup_rejected=域名 a.example.com 已被母号「母号A」占用。`（唯一索引 + 友好报错）

- [ ] **Step 5: 删除临时脚本**

```bash
rm oidc/cli/tmp_client_check.php
```

- [ ] **Step 6: Commit**

```bash
git add oidc/app/clients.php oidc/app/bootstrap.php
git commit -m "feat(clients): client model CRUD, domain uniqueness, secret auth"
```

---

## Task 7: `/authorize`、`/token` 改为按 client_id 查表

**Files:**
- Modify: `oidc/app/oidc.php`（替换两个函数）

- [ ] **Step 1: 替换 `app_oidc_validate_authorize_request`**

把 `app/oidc.php` 中现有的 `app_oidc_validate_authorize_request` 函数整体替换为：

```php
function app_oidc_validate_authorize_request(array $params)
{
    $client = app_client_find($params['client_id'] ?? '');
    if (!$client || $client['status'] !== 'active') {
        throw new RuntimeException('client_id 无效。');
    }
    if (($params['response_type'] ?? '') !== 'code') {
        throw new RuntimeException('当前只支持 response_type=code。');
    }
    if (empty($params['redirect_uri']) || !app_client_redirect_allowed($client, $params['redirect_uri'])) {
        throw new RuntimeException('redirect_uri 无效。');
    }
    if (empty($params['scope']) || strpos($params['scope'], 'openid') === false) {
        throw new RuntimeException('scope 必须包含 openid。');
    }
    if (empty($params['state']) || empty($params['nonce'])) {
        throw new RuntimeException('state 和 nonce 都是必填项。');
    }
    $hasCodeChallenge = !empty($params['code_challenge']);
    $hasCodeChallengeMethod = !empty($params['code_challenge_method']);
    if ($hasCodeChallenge || $hasCodeChallengeMethod) {
        if (!$hasCodeChallenge || ($params['code_challenge_method'] ?? '') !== 'S256') {
            throw new RuntimeException('如果启用 PKCE，则必须使用 S256。');
        }
    }
}
```

- [ ] **Step 2: 替换 `app_oidc_client_authenticated`**

把 `app/oidc.php` 中现有的 `app_oidc_client_authenticated` 函数整体替换为（委托给 client model，`app_oidc_exchange_code` 无需改动）：

```php
function app_oidc_client_authenticated($clientId, $clientSecret)
{
    return app_client_authenticate((string) $clientId, (string) $clientSecret);
}
```

- [ ] **Step 3: 语法检查**

Run: `php -l oidc/app/oidc.php`
Expected: `No syntax errors detected in oidc/app/oidc.php`

- [ ] **Step 4: curl 验证 token 端点的 client 认证（用 Task 6 建的母号 client_id）**

错误 secret → `invalid_client`：
```bash
curl -s -o /dev/null -w "%{http_code} " https://你的域名/token \
  -d 'grant_type=authorization_code&code=x&redirect_uri=https://external.auth.openai.com/sso/oidc/AAA/callback&client_id=cid_你的&client_secret=WRONG'
```
Expected: `401`，响应体 `{"error":"invalid_client"}`。

正确 client_id+secret 但无效 code → `invalid_grant`（证明 client 认证已通过，进入 code 校验）：
```bash
curl -s https://你的域名/token \
  -d 'grant_type=authorization_code&code=NOPE&redirect_uri=https://external.auth.openai.com/sso/oidc/AAA/callback&client_id=cid_你的&client_secret=csk_你的'
```
Expected: `{"error":"invalid_grant"}`

- [ ] **Step 5: Commit**

```bash
git add oidc/app/oidc.php
git commit -m "feat(oidc): authorize/token validate against oidc_clients table"
```

---

## Task 8: `/authorize` 把母号域名集合写入 pending

**Files:**
- Modify: `oidc/public/index.php`（`/authorize` 路由的非 resume 分支）

- [ ] **Step 1: 注入域名集合**

在 `public/index.php` 的 `/authorize` 块中，找到这两行（仅此一处）：

```php
            app_oidc_validate_authorize_request($params);
            app_oidc_store_pending_authorize($params);
```

替换为（在校验通过后、存 pending 前，把该母号域名集合并入 pending）：

```php
            app_oidc_validate_authorize_request($params);
            $params['allowed_domains'] = app_client_domains($params['client_id']);
            app_oidc_store_pending_authorize($params);
```

- [ ] **Step 2: 语法检查**

Run: `php -l oidc/public/index.php`
Expected: `No syntax errors detected`

- [ ] **Step 3: Commit**

```bash
git add oidc/public/index.php
git commit -m "feat(authorize): carry client's allowed domains into pending"
```

> 端到端效果与 Task 9 一起验证（登录页需读取 pending 域名）。

---

## Task 9: `/sso` 首次激活需 pending + `users` 域名校验

**Files:**
- Modify: `oidc/app/users.php`（替换 `app_activate_user`）
- Modify: `oidc/public/index.php`（替换整个 `/sso` 路由块）

- [ ] **Step 1: 替换 `app/users.php` 的 `app_activate_user`**

把现有 `app_activate_user` 函数整体替换为（新增 `$allowedDomains` / `$originClientId` 参数；域名校验改用母号集合 + 归一化；写入 `origin_client_id`）：

```php
function app_activate_user($plainCard, $email, $fullName, array $allowedDomains, ?string $originClientId)
{
    $plainCard = app_normalize_card_value($plainCard);
    $email = strtolower(trim($email));
    $fullName = trim($fullName);
    $card = app_find_card_by_plain($plainCard);

    if (!$card || !app_card_is_usable($card)) {
        throw new RuntimeException('卡密无效、已过期，或不可使用。');
    }
    if ($card['status'] !== 'unused' || !empty($card['used_by_user_id'])) {
        throw new RuntimeException('这张卡已经绑定到其他账号。');
    }
    if (!filter_var($email, FILTER_VALIDATE_EMAIL)) {
        throw new RuntimeException('邮箱格式不正确。');
    }
    $domain = app_normalize_domain(substr(strrchr($email, '@'), 1));
    if (!in_array($domain, $allowedDomains, true)) {
        throw new RuntimeException('当前邮箱后缀不允许登录。');
    }
    if (app_find_user_by_email($email)) {
        throw new RuntimeException('这个邮箱已经存在绑定账号。');
    }

    if ($fullName === '') {
        $emailParts = explode('@', $email, 2);
        $fullName = $emailParts[0];
    }
    $nameParts = preg_split('/\s+/', $fullName);
    $givenName = isset($nameParts[0]) ? $nameParts[0] : $fullName;
    $familyName = count($nameParts) > 1 ? $nameParts[count($nameParts) - 1] : $givenName;
    $subject = 'usr_' . app_random_hex(16);
    $pdo = app_pdo();
    $pdo->beginTransaction();

    try {
        app_db_exec('INSERT INTO users (oidc_subject, email, email_domain, full_name, given_name, family_name, password_hash, status, activated_by_card_id, activated_at, origin_client_id, created_at, updated_at) VALUES (:oidc_subject, :email, :email_domain, :full_name, :given_name, :family_name, :password_hash, :status, :activated_by_card_id, :activated_at, :origin_client_id, :created_at, :updated_at)', [
            'oidc_subject' => $subject,
            'email' => $email,
            'email_domain' => $domain,
            'full_name' => $fullName,
            'given_name' => $givenName,
            'family_name' => $familyName,
            'password_hash' => app_password_hash_value(app_random_hex(32)),
            'status' => 'active',
            'activated_by_card_id' => (int) $card['id'],
            'activated_at' => app_now(),
            'origin_client_id' => $originClientId,
            'created_at' => app_now(),
            'updated_at' => app_now(),
        ]);

        $userId = app_pdo()->lastInsertId();

        app_db_exec('UPDATE card_keys SET status = :status, used_by_user_id = :used_by_user_id, used_at = :used_at, updated_at = :updated_at WHERE id = :id', [
            'status' => 'used',
            'used_by_user_id' => $userId,
            'used_at' => app_now(),
            'updated_at' => app_now(),
            'id' => (int) $card['id'],
        ]);

        $pdo->commit();
    } catch (Exception $e) {
        $pdo->rollBack();
        throw $e;
    }

    $user = app_find_user_by_email($email);
    app_audit('user', (int) $user['id'], 'user_activated', 'card', (string) $card['id'], ['email' => $email, 'origin_client_id' => $originClientId]);

    return $user;
}
```

- [ ] **Step 2: 替换 `public/index.php` 的整个 `/sso` 路由块**

把现有 `if ($path === '/sso') { ... }` 整块替换为：

```php
if ($path === '/sso') {
    $pending = app_oidc_pending_authorize();
    $hasPending = $pending !== null;
    $allowedDomains = ($hasPending && !empty($pending['allowed_domains'])) ? array_values((array) $pending['allowed_domains']) : [];
    $hintEmail = app_login_hint_email();
    list($hintPrefix, $hintDomain) = app_split_email_parts($hintEmail);
    $userRateBucket = 'user_login_' . app_ip();

    if (app_is_post()) {
        if (!app_validate_csrf_token('user_login', app_post('csrf_token'))) {
            app_flash_set('error', 'CSRF 校验失败。');
            app_redirect('/sso');
        }
        if (app_rate_limit_exceeded($userRateBucket, 20, 300)) {
            app_flash_set('error', '尝试次数过多，请稍后再试。');
            app_redirect('/sso');
        }

        $plainCard = app_normalize_card_value(app_post('card_key'));
        $fullName = app_post('full_name');
        $emailPrefix = strtolower(trim((string) app_post('email_prefix')));
        $emailDomainInput = strtolower(trim((string) app_post('email_domain')));
        $loginEmail = $emailPrefix . '@' . $emailDomainInput;

        if ($emailPrefix === '' || $emailDomainInput === '' || !filter_var($loginEmail, FILTER_VALIDATE_EMAIL)) {
            app_rate_limit_record($userRateBucket, 300);
            app_flash_set('error', '邮箱前缀和后缀不能为空，且需合法。');
            app_redirect('/sso');
        }
        if ($hintEmail !== '' && !hash_equals(strtolower($hintEmail), strtolower($loginEmail))) {
            app_rate_limit_record($userRateBucket, 300);
            app_flash_set('error', '邮箱必须与 OpenAI 登录时输入的邮箱一致。');
            app_redirect('/sso');
        }

        app_close_session();

        $card = app_find_card_by_plain($plainCard);
        if (!$card || !app_card_is_usable($card)) {
            app_audit('system', null, 'card_login_failed', 'card', null, ['input' => $plainCard]);
            app_rate_limit_record($userRateBucket, 300);
            app_flash_set('error', '卡密无效或已过期。');
            app_redirect('/sso');
        }

        $user = app_user_for_card($card);
        if ($user) {
            if (!hash_equals(strtolower($user['email']), strtolower($loginEmail))) {
                app_rate_limit_record($userRateBucket, 300);
                app_flash_set('error', '邮箱与这张卡绑定的账号不一致。');
                app_redirect('/sso');
            }
            if ($user['status'] !== 'active') {
                app_rate_limit_record($userRateBucket, 300);
                app_flash_set('error', '这张卡绑定的账号已被禁用。');
                app_redirect('/sso');
            }
            app_touch_user_login($user['id']);
            app_login_user($user);
            app_rate_limit_clear($userRateBucket);
            app_audit('user', (int) $user['id'], 'card_login_success', 'user', (string) $user['id'], []);
            $redirect = !empty($_SESSION['post_login_redirect']) ? $_SESSION['post_login_redirect'] : '/';
            unset($_SESSION['post_login_redirect']);
            app_redirect($redirect);
        }

        // 卡未绑定 → 首次激活，必须有 pending client 上下文（审查档 2）
        if (!$hasPending) {
            app_rate_limit_record($userRateBucket, 300);
            app_flash_set('error', '这张卡尚未激活，请从 ChatGPT 发起登录以完成首次绑定。');
            app_redirect('/sso');
        }
        try {
            $originClientId = isset($pending['client_id']) ? (string) $pending['client_id'] : null;
            $user = app_activate_user($plainCard, $loginEmail, $fullName, $allowedDomains, $originClientId);
        } catch (Exception $e) {
            app_rate_limit_record($userRateBucket, 300);
            app_flash_set('error', $e->getMessage());
            app_redirect('/sso');
        }

        app_touch_user_login($user['id']);
        app_login_user($user);
        app_rate_limit_clear($userRateBucket);
        app_flash_set('success', '卡密绑定成功。');
        $redirect = !empty($_SESSION['post_login_redirect']) ? $_SESSION['post_login_redirect'] : '/';
        unset($_SESSION['post_login_redirect']);
        app_redirect($redirect);
    }

    if ($hasPending && !empty($allowedDomains)) {
        if ($hintDomain && in_array(app_normalize_domain($hintDomain), $allowedDomains, true)) {
            $suffixField = '<div class="field"><label>邮箱后缀</label><input type="text" value="' . app_h($hintDomain) . '" readonly><input type="hidden" name="email_domain" value="' . app_h($hintDomain) . '"></div>';
        } else {
            $options = '';
            foreach ($allowedDomains as $domain) {
                $options .= '<option value="' . app_h($domain) . '">' . app_h($domain) . '</option>';
            }
            $suffixField = '<div class="field"><label>邮箱后缀</label><select name="email_domain" required>' . $options . '</select></div>';
        }
        $intro = '用户先在 ChatGPT 里输入完整受控邮箱，OpenAI 跳转到这里后，再输入卡密和邮箱前缀即可。新卡会在第一次使用时自动绑定。';
    } else {
        $suffixField = '<div class="field"><label>邮箱后缀</label><input type="text" name="email_domain" placeholder="example.com" required></div>';
        $intro = '直接访问只能用<strong>已激活</strong>的卡密登录。新卡首次绑定请从 ChatGPT 发起。';
    }
    $prefixValue = $hintPrefix ? ' value="' . app_h($hintPrefix) . '"' : '';
    $body = '<section class="hero"><span class="pill">单页 SSO 卡密登录</span><h1>使用卡密和邮箱前缀登录</h1><p>' . $intro . '</p></section><section class="split"><div class="card"><div class="section-title"><h3>SSO 卡密登录</h3></div><form method="post" class="stack"><input type="hidden" name="csrf_token" value="' . app_h(app_issue_csrf_token('user_login')) . '"><div class="form-grid"><div class="field"><label>邮箱前缀</label><input type="text" name="email_prefix"' . $prefixValue . ' required></div>' . $suffixField . '</div><div class="field"><label>卡密</label><input class="mono" type="text" name="card_key" required></div><div class="field"><label>显示名（可选）</label><input type="text" name="full_name"></div><div class="actions"><button type="submit">继续</button></div></form></div><div class="card"><div class="section-title"><h3>接下来会发生什么</h3></div><div class="steps"><div class="step"><div>如果卡密已经绑定，邮箱前缀必须与绑定账号一致。</div></div><div class="step"><div>如果是新卡，需从 ChatGPT 发起登录以完成首次绑定。</div></div><div class="step"><div>如果这次登录是从 OpenAI 发起的，系统会自动继续走 OIDC 回跳。</div></div></div></div></section>';
    app_render_page('SSO 卡密登录', $body);
}
```

- [ ] **Step 3: 语法检查 + 纯逻辑回归**

Run:
```bash
php -l oidc/app/users.php && php -l oidc/public/index.php && php oidc/cli/tests/run.php
```
Expected: 两个 `No syntax errors detected`；测试 `11 passed, 0 failed`。

- [ ] **Step 4: 端到端验证（浏览器，覆盖 Task 8+9）**

前置：已用 Task 6 建一个母号（拿到 `cid_xxx`、其域名如 `a.example.com`、其回调 `https://external.auth.openai.com/sso/oidc/AAA/callback`），并生成一张未绑定卡密。

1. **首次激活护栏**：直接访问 `https://你的域名/sso`，输入「未绑定卡 + 任意邮箱」→ 期望红字「这张卡尚未激活，请从 ChatGPT 发起登录以完成首次绑定。」
2. **从 authorize 进入并激活**：浏览器打开
   `https://你的域名/authorize?client_id=cid_xxx&response_type=code&redirect_uri=https%3A%2F%2Fexternal.auth.openai.com%2Fsso%2Foidc%2FAAA%2Fcallback&scope=openid%20profile%20email&state=s1&nonce=n1`
   → 跳 `/sso`，邮箱后缀显示 `a.example.com` → 输入前缀（如 `alice`）+ 卡密 → 期望成功，桥接页跳回 `...callback?code=...&state=s1`。
3. **已绑定卡登录**：直接 `/sso`，用步骤 2 的卡 + `alice@a.example.com` → 成功；换 `bob@a.example.com` → 期望「邮箱与这张卡绑定的账号不一致」。

- [ ] **Step 5: Commit**

```bash
git add oidc/app/users.php oidc/public/index.php
git commit -m "feat(sso): first-activation requires pending client; domain check from client set"
```

---

## Task 10: 管理 API 拆分鉴权 + `/api/clients`

**Files:**
- Modify: `oidc/app/api.php`（拆鉴权 + 新增 clients handler）
- Modify: `oidc/public/index.php`（加 `/api/clients` 路由）

- [ ] **Step 1: 替换 `app/api.php` 的 `app_api_auth` 为分权鉴权**

把现有 `app_api_auth()` 函数整体替换为以下三个函数：

```php
function app_api_check_bearer(string $key): void
{
    $header = $_SERVER['HTTP_AUTHORIZATION'] ?? $_SERVER['REDIRECT_HTTP_AUTHORIZATION'] ?? '';
    $bearer = (stripos($header, 'Bearer ') === 0) ? substr($header, 7) : '';
    $xkey = $_SERVER['HTTP_X_API_KEY'] ?? '';
    $provided = trim($bearer ?: $xkey);
    if (!$provided || !hash_equals($key, $provided)) {
        app_json(['ok' => false, 'error' => 'invalid api key'], 401);
    }
}

function app_api_auth_cards(): bool
{
    $key = (string) (app_config('cards_api_key') ?: app_config('api_key'));
    if ($key === '') {
        app_json(['ok' => false, 'error' => 'API not configured'], 503);
    }
    app_api_check_bearer($key);
    return true;
}

function app_api_auth_clients(): bool
{
    $key = (string) app_config('clients_admin_api_key', '');
    if ($key === '') {
        app_json(['ok' => false, 'error' => 'clients API disabled'], 503);
    }
    $allow = (array) app_config('clients_admin_ip_allowlist', []);
    if (!empty($allow) && !in_array(app_ip(), $allow, true)) {
        app_audit('system', null, 'clients_api_ip_blocked', 'ip', app_ip(), []);
        app_json(['ok' => false, 'error' => 'ip not allowed'], 403);
    }
    app_api_check_bearer($key);
    return true;
}
```

- [ ] **Step 2: 把现有发卡接口改用 `app_api_auth_cards()`**

在 `app/api.php` 中，把 `app_api_cards_generate()`、`app_api_card_lookup()`、`app_api_status()` 三个函数体内的 `app_api_auth();` 调用都改为 `app_api_auth_cards();`（共 3 处）。

- [ ] **Step 3: 在 `app/api.php` 末尾追加母号管理 handler**

```php
function app_api_clients_create(): void
{
    app_api_auth_clients();
    $body = json_decode(file_get_contents('php://input'), true) ?: [];
    try {
        $res = app_client_create([
            'name' => (string) ($body['name'] ?? ''),
            'redirect_uris' => (array) ($body['redirect_uris'] ?? []),
            'allowed_domains' => (array) ($body['allowed_domains'] ?? []),
            'note' => (string) ($body['note'] ?? ''),
        ], null);
        app_json(['ok' => true, 'client' => $res]);
    } catch (Exception $e) {
        app_json(['ok' => false, 'error' => $e->getMessage()], 400);
    }
}

function app_api_clients_list(): void
{
    app_api_auth_clients();
    $clients = app_client_list();
    foreach ($clients as &$c) { unset($c['client_secret_enc']); }
    unset($c);
    app_json(['ok' => true, 'clients' => $clients]);
}

function app_api_clients_get(string $clientId): void
{
    app_api_auth_clients();
    $client = app_client_find($clientId);
    if (!$client) { app_json(['ok' => false, 'error' => 'not found'], 404); }
    unset($client['client_secret_enc']);
    $client['domains'] = app_client_domains($clientId);
    if (app_query('reveal') === '1') {
        if (!app_config('clients_secret_reveal_enabled', false)) {
            app_json(['ok' => false, 'error' => 'reveal disabled'], 403);
        }
        app_audit('system', null, 'client_secret_revealed', 'client', $clientId, ['via' => 'api']);
        $client['client_secret'] = app_client_reveal_secret($clientId);
    }
    app_json(['ok' => true, 'client' => $client]);
}

function app_api_clients_update(string $clientId): void
{
    app_api_auth_clients();
    $body = json_decode(file_get_contents('php://input'), true) ?: [];
    try {
        if (!empty($body['rotate_secret'])) {
            app_json(['ok' => true, 'client_secret' => app_client_rotate_secret($clientId, null)]);
        }
        $changes = [];
        foreach (['name', 'redirect_uris', 'allowed_domains', 'status'] as $k) {
            if (array_key_exists($k, $body)) { $changes[$k] = $body[$k]; }
        }
        app_client_update($clientId, $changes, null);
        app_json(['ok' => true]);
    } catch (Exception $e) {
        app_json(['ok' => false, 'error' => $e->getMessage()], 400);
    }
}
```

- [ ] **Step 4: 在 `public/index.php` 加 `/api/clients` 路由**

找到这三行（现有 cards API 路由，仅此一处）：

```php
if ($path === '/api/status') { app_api_status(); }
if ($path === '/api/cards/generate' && app_method() === 'POST') { app_api_cards_generate(); }
if ($path === '/api/cards/lookup' && app_method() === 'POST') { app_api_card_lookup(); }
```

在其后追加：

```php
if ($path === '/api/clients' && app_method() === 'POST') { app_api_clients_create(); }
if ($path === '/api/clients' && app_method() === 'GET') { app_api_clients_list(); }
if (preg_match('#^/api/clients/([A-Za-z0-9_]+)$#', $path, $m) && app_method() === 'GET') { app_api_clients_get($m[1]); }
if (preg_match('#^/api/clients/([A-Za-z0-9_]+)$#', $path, $m) && app_method() === 'PATCH') { app_api_clients_update($m[1]); }
```

- [ ] **Step 5: 语法检查**

Run: `php -l oidc/app/api.php && php -l oidc/public/index.php`
Expected: 两个 `No syntax errors detected`

- [ ] **Step 6: curl 验证分权（前置：在 `app/config.php` 临时加 `'clients_admin_api_key' => 'testclients123'`，Task 12 会纳入安装向导）**

发卡 key 不能建母号：
```bash
curl -s -o /dev/null -w "%{http_code}\n" -X POST https://你的域名/api/clients \
  -H "Authorization: Bearer <cards_api_key 或旧 api_key>" -d '{}'
```
Expected: `401`（key 与 clients_admin_api_key 不匹配）。

clients key 建母号：
```bash
curl -s -X POST https://你的域名/api/clients \
  -H "Authorization: Bearer testclients123" -H "Content-Type: application/json" \
  -d '{"name":"母号C","redirect_uris":["https://external.auth.openai.com/sso/oidc/CCC/callback"],"allowed_domains":["c.example.com"]}'
```
Expected: `{"ok":true,"client":{... "client_id":"cid_...","client_secret":"csk_...","openai_config":{...}}}`

reveal 默认禁用：
```bash
curl -s "https://你的域名/api/clients/<cid>?reveal=1" -H "Authorization: Bearer testclients123"
```
Expected: `{"ok":false,"error":"reveal disabled"}`（403）。

- [ ] **Step 7: Commit**

```bash
git add oidc/app/api.php oidc/public/index.php
git commit -m "feat(api): split cards/clients auth keys, add /api/clients CRUD"
```

---

## Task 11: admin 母号管理页

**Files:**
- Modify: `oidc/app/views.php`（追加 `app_admin_clients_html`）
- Modify: `oidc/app/admin.php`（追加 `app_admin_clients`）
- Modify: `oidc/public/index.php`（加 `/admin/clients*` 路由 + `/admin` 页入口链接）

- [ ] **Step 1: 在 `app/views.php` 末尾追加母号管理页 HTML**

```php
function app_admin_clients_html(array $clients, $created, $revealed, string $csrf): string
{
    $createdHtml = '';
    if ($created) {
        $cfg = $created['openai_config'];
        $createdHtml = '<section class="card"><div class="section-title"><h3>新建成功 — 请立刻复制</h3><span class="badge">Secret 仅展示一次</span></div><div class="code-panel mono">client_id: ' . app_h($created['client_id']) . '<br>client_secret: ' . app_h($created['client_secret']) . '<br>issuer: ' . app_h($cfg['issuer']) . '<br>discovery: ' . app_h($cfg['discovery_url']) . '<br>scopes: ' . app_h($cfg['scopes']) . '</div></section>';
    }
    if ($revealed) {
        $createdHtml .= '<section class="card"><div class="section-title"><h3>Secret（' . app_h($revealed['client_id']) . '）</h3></div><div class="code-panel mono">' . app_h($revealed['client_secret']) . '</div></section>';
    }

    $rows = '';
    foreach ($clients as $c) {
        $domains = implode(', ', $c['domains']);
        $ru = json_decode($c['redirect_uris'] ?? '[]', true) ?: [];
        $ruText = implode("\n", $ru);
        $domText = implode("\n", $c['domains']);
        $statusLabel = $c['status'] === 'active' ? '启用' : '停用';
        $toggle = $c['status'] === 'active' ? 'disabled' : 'active';
        $toggleLabel = $c['status'] === 'active' ? '停用' : '启用';
        $rows .= '<tr><td>' . app_h($c['name']) . '</td><td class="mono">' . app_h($c['client_id']) . '</td><td>' . app_h($domains) . '</td><td>' . app_h($statusLabel) . '</td><td>'
            . '<div class="actions">'
            . '<form method="post" action="/admin/clients/reveal"><input type="hidden" name="csrf_token" value="' . app_h($csrf) . '"><input type="hidden" name="client_id" value="' . app_h($c['client_id']) . '"><button class="inline secondary" type="submit">显示 Secret</button></form>'
            . '<form method="post" action="/admin/clients/rotate" onsubmit="return confirm(\'确认轮换 Secret？旧值立即失效。\')"><input type="hidden" name="csrf_token" value="' . app_h($csrf) . '"><input type="hidden" name="client_id" value="' . app_h($c['client_id']) . '"><button class="inline warn" type="submit">轮换 Secret</button></form>'
            . '<form method="post" action="/admin/clients/status"><input type="hidden" name="csrf_token" value="' . app_h($csrf) . '"><input type="hidden" name="client_id" value="' . app_h($c['client_id']) . '"><input type="hidden" name="status" value="' . $toggle . '"><button class="inline secondary" type="submit">' . $toggleLabel . '</button></form>'
            . '</div>'
            . '<details><summary>编辑回调/域名</summary><form method="post" action="/admin/clients/update" class="stack"><input type="hidden" name="csrf_token" value="' . app_h($csrf) . '"><input type="hidden" name="client_id" value="' . app_h($c['client_id']) . '"><div class="field"><label>名称</label><input type="text" name="name" value="' . app_h($c['name']) . '"></div><div class="field"><label>回调白名单（每行一个）</label><textarea name="redirect_uris">' . app_h($ruText) . '</textarea></div><div class="field"><label>允许域名（每行一个）</label><textarea name="allowed_domains">' . app_h($domText) . '</textarea></div><div class="actions"><button type="submit">保存</button></div></form></details>'
            . '</td></tr>';
    }

    $body = '<section class="hero"><span class="pill">母号管理</span><h1>OpenAI team 母号</h1><p>每个母号一对独立 Client ID/Secret + 独立域名。新增后到 OpenAI 后台填 issuer/discovery + 这里的 client_id/secret，再把 OpenAI 回调填回回调白名单。</p><div class="actions" style="margin-top:12px"><a class="button-link inline secondary" href="/admin">返回后台</a></div></section>';
    $body .= $createdHtml;
    $body .= '<section class="card"><div class="section-title"><h3>新建母号</h3></div><form method="post" action="/admin/clients/create" class="stack"><input type="hidden" name="csrf_token" value="' . app_h($csrf) . '"><div class="form-grid"><div class="field"><label>母号名称</label><input type="text" name="name" placeholder="母号A-1bool.com" required></div><div class="field"><label>备注</label><input type="text" name="note"></div></div><div class="field"><label>OpenAI 回调白名单（每行一个，OpenAI 创建连接后回填）</label><textarea name="redirect_uris" placeholder="https://external.auth.openai.com/sso/oidc/XXXX/callback"></textarea></div><div class="field"><label>允许邮箱域名（每行一个）</label><textarea name="allowed_domains" placeholder="1bool.com" required></textarea></div><div class="actions"><button type="submit">创建母号</button></div></form></section>';
    $body .= '<section class="card"><div class="section-title"><h3>母号列表</h3></div><div class="table-wrap"><table><tr><th>名称</th><th>Client ID</th><th>域名</th><th>状态</th><th>操作</th></tr>' . $rows . '</table></div></section>';
    return $body;
}
```

- [ ] **Step 2: 在 `app/admin.php` 末尾追加数据封装**

```php
function app_admin_clients()
{
    return app_client_list();
}
```

- [ ] **Step 3: 在 `public/index.php` 加 `/admin/clients*` 路由**

找到这一行（仅此一处，精确匹配）：

```php
if ($path === '/admin') {
```

在它**之前**插入以下整段路由：

```php
if ($path === '/admin/clients') {
    $admin = app_require_admin();
    $created = $_SESSION['__client_created'] ?? null;
    unset($_SESSION['__client_created']);
    $revealed = $_SESSION['__client_revealed'] ?? null;
    unset($_SESSION['__client_revealed']);
    app_render_page('母号管理', app_admin_clients_html(app_admin_clients(), $created, $revealed, app_issue_csrf_token('admin_clients')));
}

if ($path === '/admin/clients/create' && app_is_post()) {
    $admin = app_require_admin();
    if (!app_validate_csrf_token('admin_clients', app_post('csrf_token'))) { app_flash_set('error', 'CSRF 校验失败。'); app_redirect('/admin/clients'); }
    try {
        $res = app_client_create([
            'name' => app_post('name'),
            'redirect_uris' => app_parse_csvish(app_post('redirect_uris')),
            'allowed_domains' => app_parse_csvish(app_post('allowed_domains')),
            'note' => app_post('note'),
        ], (int) $admin['id']);
        $_SESSION['__client_created'] = $res;
        app_flash_set('success', '母号已创建：' . $res['client_id'] . '。请立刻复制 Client Secret，仅展示一次。');
    } catch (Exception $e) {
        app_flash_set('error', $e->getMessage());
    }
    app_redirect('/admin/clients');
}

if ($path === '/admin/clients/update' && app_is_post()) {
    $admin = app_require_admin();
    if (!app_validate_csrf_token('admin_clients', app_post('csrf_token'))) { app_flash_set('error', 'CSRF 校验失败。'); app_redirect('/admin/clients'); }
    try {
        app_client_update(app_post('client_id'), [
            'name' => app_post('name'),
            'redirect_uris' => app_parse_csvish(app_post('redirect_uris')),
            'allowed_domains' => app_parse_csvish(app_post('allowed_domains')),
        ], (int) $admin['id']);
        app_flash_set('success', '母号已更新。');
    } catch (Exception $e) {
        app_flash_set('error', $e->getMessage());
    }
    app_redirect('/admin/clients');
}

if ($path === '/admin/clients/status' && app_is_post()) {
    $admin = app_require_admin();
    if (!app_validate_csrf_token('admin_clients', app_post('csrf_token'))) { app_flash_set('error', 'CSRF 校验失败。'); app_redirect('/admin/clients'); }
    try {
        app_client_update(app_post('client_id'), ['status' => app_post('status') === 'disabled' ? 'disabled' : 'active'], (int) $admin['id']);
        app_flash_set('success', '母号状态已更新。');
    } catch (Exception $e) {
        app_flash_set('error', $e->getMessage());
    }
    app_redirect('/admin/clients');
}

if ($path === '/admin/clients/rotate' && app_is_post()) {
    $admin = app_require_admin();
    if (!app_validate_csrf_token('admin_clients', app_post('csrf_token'))) { app_flash_set('error', 'CSRF 校验失败。'); app_redirect('/admin/clients'); }
    try {
        $secret = app_client_rotate_secret(app_post('client_id'), (int) $admin['id']);
        $_SESSION['__client_revealed'] = ['client_id' => app_post('client_id'), 'client_secret' => $secret];
        app_flash_set('success', '已轮换 Secret，请立刻复制。');
    } catch (Exception $e) {
        app_flash_set('error', $e->getMessage());
    }
    app_redirect('/admin/clients');
}

if ($path === '/admin/clients/reveal' && app_is_post()) {
    $admin = app_require_admin();
    if (!app_validate_csrf_token('admin_clients', app_post('csrf_token'))) { app_flash_set('error', 'CSRF 校验失败。'); app_redirect('/admin/clients'); }
    try {
        $secret = app_client_reveal_secret(app_post('client_id'));
        app_audit('admin', (int) $admin['id'], 'client_secret_revealed', 'client', app_post('client_id'), ['via' => 'admin']);
        $_SESSION['__client_revealed'] = ['client_id' => app_post('client_id'), 'client_secret' => $secret];
    } catch (Exception $e) {
        app_flash_set('error', $e->getMessage());
    }
    app_redirect('/admin/clients');
}
```

- [ ] **Step 4: 在 `/admin` 页加母号管理入口链接**

在 `public/index.php` 中找到（仅此一处）：

```php
<div class="actions" style="margin-top:16px"><form method="post" action="/admin/logout">
```

替换为：

```php
<div class="actions" style="margin-top:16px"><a class="button-link inline secondary" href="/admin/clients">母号管理</a><form method="post" action="/admin/logout">
```

- [ ] **Step 5: 语法检查**

Run: `php -l oidc/app/views.php && php -l oidc/app/admin.php && php -l oidc/public/index.php`
Expected: 三个 `No syntax errors detected`

- [ ] **Step 6: 浏览器验证**

1. 管理员登录后台 → `/admin` 页点「母号管理」→ 进入 `/admin/clients`。
2. 新建母号（名称 + 一个回调 + 域名 `d.example.com`）→ 顶部出现 client_id / client_secret / openai_config，列表新增该母号。
3. 再建一个用相同域名 `d.example.com` 的母号 → 红字「域名 d.example.com 已被母号「…」占用。」。
4. 列表里点「显示 Secret」→ 顶部显示明文；点「轮换 Secret」→ 显示新明文。
5. 点「停用」→ 状态变停用；用该母号 client 走 `/authorize` → 被拒（`client_id 无效`）。

- [ ] **Step 7: Commit**

```bash
git add oidc/app/views.php oidc/app/admin.php oidc/public/index.php
git commit -m "feat(admin): mother-account management page"
```

---

## Task 12: 安装/配置接入新配置项

**Files:**
- Modify: `oidc/app/config.sample.php`（移除单 client，加 4 个新配置项）
- Modify: `oidc/public/index.php`（`app_build_config_from_request`、`app_pick_key`、两个 validate 函数）

- [ ] **Step 1: 用以下内容整体替换 `app/config.sample.php`**

```php
<?php

return [
    'app_env' => 'production',
    'app_debug' => false,
    'app_url' => 'https://your-oidc-domain.com',
    'app_name' => 'GPT OIDC',

    // 32-byte random hex; 用于 secret 加密与 hash 派生
    'app_key' => 'replace-with-32-byte-random-hex-string',
    'app_pepper' => 'replace-with-another-32-byte-random-hex-string',

    // 发卡/查询 API（WebUI 用）
    'cards_api_key' => '',
    // 母号管理 API（高权限，独立 key）
    'clients_admin_api_key' => '',
    // 母号管理 API 可选 IP 白名单（空数组=不限制）
    'clients_admin_ip_allowlist' => [],
    // 是否允许经 API 解密回显 client_secret（默认禁用）
    'clients_secret_reveal_enabled' => false,

    'db_host' => '127.0.0.1',
    'db_port' => 3306,
    'db_name' => 'gptoidc',
    'db_user' => 'gptoidc',
    'db_pass' => 'change-me',

    'session_name' => 'GPTOIDCSESSID',

    // Sub2API 集成（可选，沿用）
    'sub2api_base_url' => '',
    'sub2api_admin_api_key' => '',
    'sub2api_proxy_id' => '',

    // OIDC：母号 client 由 oidc_clients 表管理，这里不再写死单 client
    'oidc_issuer' => 'https://your-oidc-domain.com',
    'oidc_access_token_ttl' => 600,
    'oidc_id_token_ttl' => 600,
    'oidc_auth_code_ttl' => 90,

    'jwt_private_key_path' => __DIR__ . '/../storage/keys/private.pem',
    'jwt_public_key_path' => __DIR__ . '/../storage/keys/public.pem',
];
```

- [ ] **Step 2: 替换 `public/index.php` 的 `app_build_config_from_request`，并在其后新增 `app_pick_key`**

```php
function app_build_config_from_request(array $source, array $existing = [])
{
    $appUrl = rtrim(trim((string) $source['app_url']), '/');

    return [
        'app_env' => $existing['app_env'] ?? 'production',
        'app_debug' => $existing['app_debug'] ?? false,
        'app_url' => $appUrl,
        'app_name' => $existing['app_name'] ?? 'GPT OIDC',
        'app_key' => $existing['app_key'] ?? bin2hex(random_bytes(32)),
        'app_pepper' => $existing['app_pepper'] ?? bin2hex(random_bytes(32)),
        'cards_api_key' => app_pick_key($source['cards_api_key'] ?? '', $existing['cards_api_key'] ?? ($existing['api_key'] ?? '')),
        'clients_admin_api_key' => app_pick_key($source['clients_admin_api_key'] ?? '', $existing['clients_admin_api_key'] ?? ''),
        'clients_admin_ip_allowlist' => $existing['clients_admin_ip_allowlist'] ?? [],
        'clients_secret_reveal_enabled' => $existing['clients_secret_reveal_enabled'] ?? false,
        'db_host' => trim((string) $source['db_host']),
        'db_port' => (int) $source['db_port'],
        'db_name' => trim((string) $source['db_name']),
        'db_user' => trim((string) $source['db_user']),
        'db_pass' => (string) $source['db_pass'],
        'session_name' => $existing['session_name'] ?? 'GPTOIDCSESSID',
        'oidc_issuer' => !empty($source['oidc_issuer']) ? rtrim(trim((string) $source['oidc_issuer']), '/') : $appUrl,
        'oidc_access_token_ttl' => !empty($source['oidc_access_token_ttl']) ? (int) $source['oidc_access_token_ttl'] : 600,
        'oidc_id_token_ttl' => !empty($source['oidc_id_token_ttl']) ? (int) $source['oidc_id_token_ttl'] : 600,
        'oidc_auth_code_ttl' => !empty($source['oidc_auth_code_ttl']) ? (int) $source['oidc_auth_code_ttl'] : 90,
        'jwt_private_key_path' => $existing['jwt_private_key_path'] ?? dirname(__DIR__) . '/storage/keys/private.pem',
        'jwt_public_key_path' => $existing['jwt_public_key_path'] ?? dirname(__DIR__) . '/storage/keys/public.pem',
    ];
}

function app_pick_key($provided, $existing)
{
    $provided = trim((string) $provided);
    if ($provided !== '') {
        return $provided;
    }
    if (trim((string) $existing) !== '') {
        return (string) $existing;
    }
    return bin2hex(random_bytes(32));
}
```

- [ ] **Step 3: 替换 `app_validate_install_payload`（移除 allowed_email_domains 必填）**

```php
function app_validate_install_payload(array $source)
{
    if (trim((string) $source['app_url']) === '' || trim((string) $source['db_name']) === '' || trim((string) $source['db_user']) === '' || trim((string) $source['admin_username']) === '' || trim((string) $source['admin_email']) === '' || (string) $source['admin_password'] === '') {
        throw new RuntimeException('请填写所有必填安装项。');
    }
    if (!filter_var((string) $source['admin_email'], FILTER_VALIDATE_EMAIL)) {
        throw new RuntimeException('管理员邮箱格式不正确。');
    }
    if (strlen((string) $source['admin_password']) < 10) {
        throw new RuntimeException('管理员密码至少需要 10 位。');
    }
}
```

- [ ] **Step 4: 替换 `app_validate_config_payload`（移除单 client / 域名校验）**

```php
function app_validate_config_payload(array $config)
{
    if (trim((string) $config['app_url']) === '' || trim((string) $config['oidc_issuer']) === '') {
        throw new RuntimeException('应用地址和 OIDC Issuer 不能为空。');
    }
}
```

- [ ] **Step 5: 范围说明（无需改动，记录在案）**

安装/设置表单（`app/views.php` 的 `app_install_html`、`app_settings_form_html`）里残留的 `oidc_client_id` / `oidc_client_secret` / `oidc_redirect_uris` / `allowed_email_domains` 输入框**不影响功能**——`app_build_config_from_request` 新版已不再读取它们，提交后被静默忽略。本期不清理这些 UI 残留（功能不依赖）；如需美化，后续单独处理。

- [ ] **Step 6: 语法检查**

Run: `php -l oidc/app/config.sample.php && php -l oidc/public/index.php`
Expected: 两个 `No syntax errors detected`

- [ ] **Step 7: 全新安装验证（测试环境，勿在生产）**

```bash
# 备份并移除现有 config 走全新安装
[ -f oidc/app/config.php ] && mv oidc/app/config.php oidc/app/config.php.bak
```
浏览器访问 `https://测试域名/install`，填写并提交安装表单。完成后：
```bash
grep -E "'cards_api_key'|'clients_admin_api_key'" oidc/app/config.php
```
Expected: 两个键都存在且为非空随机值。验证完如需恢复：`mv oidc/app/config.php.bak oidc/app/config.php`。

- [ ] **Step 8: Commit**

```bash
git add oidc/app/config.sample.php oidc/public/index.php
git commit -m "feat(install): add cards/clients api keys, drop single-client config"
```

---

## 验收清单（全部 task 完成后整体回归）

- [ ] `php oidc/cli/tests/run.php` → `11 passed, 0 failed`
- [ ] 两个母号各自 `authorize`→`token` 走通；母号 A 的 code 用母号 B 的 client 兑换 → `invalid_grant`
- [ ] 直接 `/sso` + 未绑定卡 → 拒绝首次激活；已绑定卡 + 正确邮箱 → 登录成功
- [ ] 域名唯一：相同域名建第二个母号 → API 与后台均拒绝
- [ ] `cards_api_key` 不能调用 `/api/clients`；`reveal` 默认禁用（API 返回 403）
- [ ] 停用母号后 `authorize` / `token` 均被拒
- [ ] 全新安装生成的 `config.php` 含 `cards_api_key` 与 `clients_admin_api_key`
- [ ] 浏览器端到端：从 OpenAI 测试沙箱发起 → `/authorize` → `/sso` 卡密绑定 → 回跳 callback（带 `code`）

---

## 实施顺序与依赖

1 → 2 → (3,4,5 可并行) → 6 → 7 → 8 → 9 → 10 → 11 → 12。Task 3-5 是纯逻辑 TDD，互不依赖；其余按序。每个 task 自带 commit。





