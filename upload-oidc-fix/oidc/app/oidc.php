<?php

function app_oidc_discovery_document()
{
    $issuer = app_config('oidc_issuer', app_base_url());

    return [
        'issuer' => $issuer,
        'authorization_endpoint' => $issuer . '/authorize',
        'token_endpoint' => $issuer . '/token',
        'userinfo_endpoint' => $issuer . '/userinfo',
        'jwks_uri' => $issuer . '/jwks.json',
        'response_types_supported' => ['code'],
        'response_modes_supported' => ['query'],
        'grant_types_supported' => ['authorization_code'],
        'subject_types_supported' => ['public'],
        'id_token_signing_alg_values_supported' => ['RS256'],
        'scopes_supported' => ['openid', 'profile', 'email'],
        'token_endpoint_auth_methods_supported' => ['client_secret_post'],
        'code_challenge_methods_supported' => ['S256'],
        'claims_supported' => ['sub', 'iss', 'aud', 'exp', 'iat', 'auth_time', 'nonce', 'email', 'email_verified', 'name', 'given_name', 'family_name'],
    ];
}

function app_oidc_public_jwk()
{
    $keyPath = app_config('jwt_public_key_path');
    if (!is_file($keyPath)) {
        throw new RuntimeException('没有找到公钥文件。');
    }

    $contents = file_get_contents($keyPath);
    $resource = openssl_pkey_get_public($contents);
    if (!$resource) {
        throw new RuntimeException('公钥内容无效。');
    }
    $details = openssl_pkey_get_details($resource);
    if (empty($details['rsa']['n']) || empty($details['rsa']['e'])) {
        throw new RuntimeException('公钥解析结果无效。');
    }
    $n = app_b64url_encode($details['rsa']['n']);
    $e = app_b64url_encode($details['rsa']['e']);

    return [
        'keys' => [[
            'kty' => 'RSA',
            'use' => 'sig',
            'alg' => 'RS256',
            'kid' => substr(app_hash_secret($contents), 0, 16),
            'n' => $n,
            'e' => $e,
        ]],
    ];
}

function app_oidc_generate_keys($privatePath, $publicPath)
{
    $resource = openssl_pkey_new([
        'private_key_bits' => 2048,
        'private_key_type' => OPENSSL_KEYTYPE_RSA,
    ]);

    if (!$resource) {
        throw new RuntimeException('生成 RSA 密钥对失败。');
    }

    openssl_pkey_export($resource, $privateKey);
    $details = openssl_pkey_get_details($resource);
    $publicKey = $details['key'];

    if (!is_dir(dirname($privatePath))) {
        mkdir(dirname($privatePath), 0770, true);
    }

    if (file_put_contents($privatePath, $privateKey) === false || file_put_contents($publicPath, $publicKey) === false) {
        throw new RuntimeException('无法写入 OIDC 签名密钥，请检查 storage/keys 目录权限。');
    }
}

function app_oidc_validate_authorize_request(array $params)
{
    $allowedRedirects = (array) app_config('oidc_allowed_redirect_uris', []);
    if (($params['client_id'] ?? '') !== app_config('oidc_client_id')) {
        throw new RuntimeException('client_id 无效。');
    }
    if (($params['response_type'] ?? '') !== 'code') {
        throw new RuntimeException('当前只支持 response_type=code。');
    }
    if (empty($params['redirect_uri']) || !in_array($params['redirect_uri'], $allowedRedirects, true)) {
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

function app_oidc_store_pending_authorize(array $params)
{
    app_start_session();
    $_SESSION['pending_authorize'] = [
        'params' => $params,
        'created_at' => time(),
    ];
}

function app_oidc_pending_authorize()
{
    app_start_session();
    if (empty($_SESSION['pending_authorize']) || !is_array($_SESSION['pending_authorize'])) {
        return null;
    }

    $record = $_SESSION['pending_authorize'];
    if (empty($record['params']) || empty($record['created_at'])) {
        unset($_SESSION['pending_authorize']);
        return null;
    }

    if ((int) $record['created_at'] < (time() - 600)) {
        unset($_SESSION['pending_authorize']);
        return null;
    }

    return $record['params'];
}

function app_oidc_clear_pending_authorize()
{
    app_start_session();
    unset($_SESSION['pending_authorize']);
}

function app_oidc_issue_code(array $user, array $params)
{
    $plainCode = app_random_hex(24);
    app_db_exec('INSERT INTO auth_codes (user_id, client_id, code_hash, redirect_uri, scope, nonce, code_challenge, code_challenge_method, expires_at, ip_address, user_agent_hash, created_at) VALUES (:user_id, :client_id, :code_hash, :redirect_uri, :scope, :nonce, :code_challenge, :code_challenge_method, :expires_at, :ip_address, :user_agent_hash, :created_at)', [
        'user_id' => (int) $user['id'],
        'client_id' => $params['client_id'],
        'code_hash' => app_hash_secret($plainCode),
        'redirect_uri' => $params['redirect_uri'],
        'scope' => $params['scope'],
        'nonce' => $params['nonce'],
        'code_challenge' => !empty($params['code_challenge']) ? $params['code_challenge'] : '',
        'code_challenge_method' => !empty($params['code_challenge_method']) ? $params['code_challenge_method'] : '',
        'expires_at' => gmdate('Y-m-d H:i:s', time() + (int) app_config('oidc_auth_code_ttl', 90)),
        'ip_address' => app_ip(),
        'user_agent_hash' => app_hash_secret(isset($_SERVER['HTTP_USER_AGENT']) ? $_SERVER['HTTP_USER_AGENT'] : ''),
        'created_at' => app_now(),
    ]);

    app_audit('user', (int) $user['id'], 'oidc_authorize_success', 'client', $params['client_id'], ['redirect_uri' => $params['redirect_uri']]);

    return $plainCode;
}

function app_oidc_client_authenticated($clientId, $clientSecret)
{
    return hash_equals((string) app_config('oidc_client_id', ''), (string) $clientId) && hash_equals((string) app_config('oidc_client_secret', ''), (string) $clientSecret);
}

function app_oidc_parse_basic_auth()
{
    if (!empty($_SERVER['PHP_AUTH_USER']) || !empty($_SERVER['PHP_AUTH_PW'])) {
        return [isset($_SERVER['PHP_AUTH_USER']) ? $_SERVER['PHP_AUTH_USER'] : null, isset($_SERVER['PHP_AUTH_PW']) ? $_SERVER['PHP_AUTH_PW'] : null];
    }

    $header = isset($_SERVER['HTTP_AUTHORIZATION']) ? $_SERVER['HTTP_AUTHORIZATION'] : '';
    if ($header === '' && isset($_SERVER['REDIRECT_HTTP_AUTHORIZATION'])) {
        $header = $_SERVER['REDIRECT_HTTP_AUTHORIZATION'];
    }
    if (stripos($header, 'Basic ') !== 0) {
        return [null, null];
    }

    $decoded = base64_decode(substr($header, 6));
    if (strpos($decoded, ':') === false) {
        return [null, null];
    }

    list($user, $pass) = explode(':', $decoded, 2);

    return [$user, $pass];
}

function app_oidc_issue_token_response(array $user, $clientId, $scope, $nonce)
{
    $accessToken = 'atk_' . app_random_hex(24);
    app_db_exec('INSERT INTO access_tokens (user_id, client_id, token_hash, scope, expires_at, ip_address, user_agent_hash, created_at) VALUES (:user_id, :client_id, :token_hash, :scope, :expires_at, :ip_address, :user_agent_hash, :created_at)', [
        'user_id' => (int) $user['id'],
        'client_id' => $clientId,
        'token_hash' => app_hash_secret($accessToken),
        'scope' => $scope,
        'expires_at' => gmdate('Y-m-d H:i:s', time() + (int) app_config('oidc_access_token_ttl', 600)),
        'ip_address' => app_ip(),
        'user_agent_hash' => app_hash_secret(isset($_SERVER['HTTP_USER_AGENT']) ? $_SERVER['HTTP_USER_AGENT'] : ''),
        'created_at' => app_now(),
    ]);

    $idToken = app_oidc_create_id_token($user, $clientId, $nonce);
    app_audit('system', null, 'oidc_token_issued', 'user', (string) $user['id'], ['client_id' => $clientId]);

    app_json([
        'access_token' => $accessToken,
        'token_type' => 'Bearer',
        'expires_in' => (int) app_config('oidc_access_token_ttl', 600),
        'scope' => $scope,
        'id_token' => $idToken,
    ]);
}

function app_oidc_exchange_code(array $input)
{
    list($basicId, $basicSecret) = app_oidc_parse_basic_auth();
    $clientId = !empty($input['client_id']) ? $input['client_id'] : $basicId;
    $clientSecret = !empty($input['client_secret']) ? $input['client_secret'] : $basicSecret;

    if (!app_oidc_client_authenticated($clientId, $clientSecret)) {
        app_audit('system', null, 'oidc_token_failed', 'client', (string) $clientId, ['reason' => 'invalid_client']);
        app_json(['error' => 'invalid_client'], 401);
    }

    if (($input['grant_type'] ?? '') !== 'authorization_code') {
        app_audit('system', null, 'oidc_token_failed', 'client', (string) $clientId, ['reason' => 'unsupported_grant_type']);
        app_json(['error' => 'unsupported_grant_type'], 400);
    }

    $row = app_db_one('SELECT * FROM auth_codes WHERE code_hash = :code_hash LIMIT 1', ['code_hash' => app_hash_secret((string) ($input['code'] ?? ''))]);
    if (!$row || strtotime($row['expires_at']) < time()) {
        app_audit('system', null, 'oidc_token_failed', 'client', (string) $clientId, ['reason' => 'invalid_grant_code']);
        app_json(['error' => 'invalid_grant'], 400);
    }

    if ($row['client_id'] !== $clientId) {
        app_audit('system', null, 'oidc_token_failed', 'client', (string) $clientId, ['reason' => 'client_mismatch']);
        app_json(['error' => 'invalid_grant'], 400);
    }

    if (($input['redirect_uri'] ?? '') !== $row['redirect_uri']) {
        app_audit('system', null, 'oidc_token_failed', 'client', (string) $clientId, ['reason' => 'redirect_uri_mismatch']);
        app_json(['error' => 'invalid_grant'], 400);
    }

    if ($row['code_challenge'] !== '') {
        $codeVerifier = (string) ($input['code_verifier'] ?? '');
        if ($codeVerifier === '') {
            app_audit('system', null, 'oidc_token_failed', 'client', (string) $clientId, ['reason' => 'missing_code_verifier']);
            app_json(['error' => 'invalid_grant'], 400);
        }

        $expectedChallenge = app_b64url_encode(hash('sha256', $codeVerifier, true));
        if (!hash_equals($row['code_challenge'], $expectedChallenge)) {
            app_audit('system', null, 'oidc_token_failed', 'client', (string) $clientId, ['reason' => 'pkce_mismatch']);
            app_json(['error' => 'invalid_grant'], 400);
        }
    }

    $user = app_db_one('SELECT * FROM users WHERE id = :id LIMIT 1', ['id' => (int) $row['user_id']]);
    if (!$user || $user['status'] !== 'active') {
        app_audit('system', null, 'oidc_token_failed', 'client', (string) $clientId, ['reason' => 'user_inactive']);
        app_json(['error' => 'invalid_grant'], 400);
    }

    if (!empty($row['used_at'])) {
        $usedAtTs = strtotime($row['used_at']);
        if ($usedAtTs !== false && $usedAtTs >= (time() - 30)) {
            app_audit('system', null, 'oidc_token_retry', 'user', (string) $user['id'], ['client_id' => $clientId]);
            app_oidc_issue_token_response($user, $clientId, $row['scope'], $row['nonce']);
        }

        app_audit('system', null, 'oidc_token_failed', 'client', (string) $clientId, ['reason' => 'code_already_used']);
        app_json(['error' => 'invalid_grant'], 400);
    }

    app_db_exec('UPDATE auth_codes SET used_at = :used_at WHERE id = :id', ['used_at' => app_now(), 'id' => (int) $row['id']]);
    app_oidc_issue_token_response($user, $clientId, $row['scope'], $row['nonce']);
}

function app_oidc_create_id_token(array $user, $clientId, $nonce)
{
    $issuer = app_config('oidc_issuer', app_base_url());
    $now = time();
    $keyPath = app_config('jwt_private_key_path');
    if (!is_file($keyPath)) {
        throw new RuntimeException('没有找到私钥文件。');
    }

    $privateKey = file_get_contents($keyPath);
    $kid = substr(app_hash_secret(file_get_contents(app_config('jwt_public_key_path'))), 0, 16);
    $fullName = !empty($user['full_name']) ? $user['full_name'] : $user['email'];
    $givenName = !empty($user['given_name']) ? $user['given_name'] : $fullName;
    $familyName = !empty($user['family_name']) ? $user['family_name'] : $givenName;
    $header = ['typ' => 'JWT', 'alg' => 'RS256', 'kid' => $kid];
    $payload = [
        'iss' => $issuer,
        'sub' => $user['oidc_subject'],
        'aud' => $clientId,
        'exp' => $now + (int) app_config('oidc_id_token_ttl', 600),
        'iat' => $now,
        'auth_time' => $now,
        'nonce' => $nonce,
        'email' => $user['email'],
        'email_verified' => true,
        'name' => $fullName,
        'given_name' => $givenName,
        'family_name' => $familyName,
    ];

    $segments = [app_b64url_encode(json_encode($header)), app_b64url_encode(json_encode($payload))];
    $signingInput = implode('.', $segments);
    if (!openssl_sign($signingInput, $signature, $privateKey, OPENSSL_ALGO_SHA256)) {
        throw new RuntimeException('签发 ID Token 失败。');
    }
    $segments[] = app_b64url_encode($signature);

    return implode('.', $segments);
}

function app_oidc_bearer_user()
{
    $header = isset($_SERVER['HTTP_AUTHORIZATION']) ? $_SERVER['HTTP_AUTHORIZATION'] : '';
    if (stripos($header, 'Bearer ') !== 0) {
        return null;
    }

    $token = substr($header, 7);
    $row = app_db_one('SELECT * FROM access_tokens WHERE token_hash = :token_hash LIMIT 1', ['token_hash' => app_hash_secret($token)]);
    if (!$row || !empty($row['revoked_at']) || strtotime($row['expires_at']) < time()) {
        return null;
    }

    $user = app_db_one('SELECT * FROM users WHERE id = :id LIMIT 1', ['id' => (int) $row['user_id']]);

    return ($user && $user['status'] === 'active') ? $user : null;
}

function app_oidc_public_metadata_dir()
{
    return dirname(__DIR__) . '/public/.well-known';
}

function app_oidc_public_discovery_path()
{
    return app_oidc_public_metadata_dir() . '/openid-configuration';
}

function app_oidc_public_jwks_path()
{
    return dirname(__DIR__) . '/public/jwks.json';
}

function app_oidc_write_json_file($path, array $payload)
{
    $directory = dirname($path);
    if (!is_dir($directory) && !mkdir($directory, 0775, true) && !is_dir($directory)) {
        throw new RuntimeException('Failed to create OIDC public metadata directory.');
    }

    $json = json_encode($payload, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    if ($json === false) {
        throw new RuntimeException('Failed to encode OIDC public metadata.');
    }
    $json .= "\n";

    $current = is_file($path) ? (string) file_get_contents($path) : '';
    if ($current === $json) {
        return false;
    }

    $tempPath = $path . '.tmp';
    if (file_put_contents($tempPath, $json, LOCK_EX) === false) {
        throw new RuntimeException('Failed to write OIDC public metadata file.');
    }

    if (!@rename($tempPath, $path)) {
        @unlink($tempPath);
        if (file_put_contents($path, $json, LOCK_EX) === false) {
            throw new RuntimeException('Failed to replace OIDC public metadata file.');
        }
    }

    return true;
}

function app_oidc_sync_public_files()
{
    app_oidc_write_json_file(app_oidc_public_discovery_path(), app_oidc_discovery_document());
    app_oidc_write_json_file(app_oidc_public_jwks_path(), app_oidc_public_jwk());

    return [
        'discovery_path' => app_oidc_public_discovery_path(),
        'jwks_path' => app_oidc_public_jwks_path(),
    ];
}
