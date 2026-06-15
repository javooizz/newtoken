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

function app_client_redirect_allowed(array $client, string $redirectUri): bool
{
    $list = json_decode($client['redirect_uris'] ?? '[]', true);
    if (!is_array($list)) {
        return false;
    }
    return in_array($redirectUri, $list, true);
}

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
    if (empty($domainsRaw)) {
        throw new RuntimeException('母号至少需要配置一个允许域名。');
    }

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
    $pdo = app_pdo();
    $pdo->beginTransaction();
    try {
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
            if (empty($raw)) {
                throw new RuntimeException('母号至少需要配置一个允许域名。');
            }
            app_db_exec('DELETE FROM oidc_client_domains WHERE client_id = :cid', ['cid' => $clientId]);
            app_client_add_domains($clientId, $raw);
        }
        $pdo->commit();
    } catch (Exception $e) {
        $pdo->rollBack();
        throw $e;
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
