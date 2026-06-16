<?php

require_once __DIR__ . '/db.php';
require_once __DIR__ . '/http.php';
require_once __DIR__ . '/security.php';
require_once __DIR__ . '/session.php';
require_once __DIR__ . '/cards.php';
require_once __DIR__ . '/users.php';
require_once __DIR__ . '/admin.php';
require_once __DIR__ . '/oidc.php';
require_once __DIR__ . '/api.php';
require_once __DIR__ . '/views.php';

function app_parse_env_value($rawValue)
{
    $value = trim((string) $rawValue);
    if ($value === '') {
        return '';
    }
    if ((str_starts_with($value, '"') && str_ends_with($value, '"')) || (str_starts_with($value, "'") && str_ends_with($value, "'"))) {
        return substr($value, 1, -1);
    }
    return $value;
}

function app_load_env_file($path)
{
    $values = [];
    if (!is_file($path) || !is_readable($path)) {
        return $values;
    }
    $lines = file($path, FILE_IGNORE_NEW_LINES);
    if (!is_array($lines)) {
        return $values;
    }
    foreach ($lines as $rawLine) {
        $line = trim((string) $rawLine);
        if ($line === '' || str_starts_with($line, '#') || !str_contains($line, '=')) {
            continue;
        }
        [$key, $rawValue] = explode('=', $line, 2);
        $key = trim((string) $key);
        if ($key === '') {
            continue;
        }
        $value = app_parse_env_value($rawValue);
        $values[$key] = $value;
        putenv($key . '=' . $value);
        $_ENV[$key] = $value;
        $_SERVER[$key] = $value;
    }
    return $values;
}

function app_env_csv($rawValue)
{
    $items = preg_split('/[,\n\r]+/', (string) $rawValue);
    $values = [];
    foreach ($items as $item) {
        $text = trim((string) $item);
        if ($text !== '') {
            $values[] = $text;
        }
    }
    return $values;
}

function app_apply_env_overrides(array $config, array $envValues)
{
    $simpleMap = [
        'GPTOIDC_APP_ENV' => 'app_env',
        'GPTOIDC_APP_URL' => 'app_url',
        'GPTOIDC_APP_NAME' => 'app_name',
        'GPTOIDC_APP_KEY' => 'app_key',
        'GPTOIDC_APP_PEPPER' => 'app_pepper',
        'GPTOIDC_API_KEY' => 'api_key',
        'GPTOIDC_DB_HOST' => 'db_host',
        'GPTOIDC_DB_PORT' => 'db_port',
        'GPTOIDC_DB_NAME' => 'db_name',
        'GPTOIDC_DB_USER' => 'db_user',
        'GPTOIDC_DB_PASS' => 'db_pass',
        'GPTOIDC_SESSION_NAME' => 'session_name',
        'GPTOIDC_OIDC_ISSUER' => 'oidc_issuer',
        'GPTOIDC_OIDC_LEGACY_PREFIX' => 'oidc_legacy_prefix',
        'GPTOIDC_OIDC_CLIENT_ID' => 'oidc_client_id',
        'GPTOIDC_OIDC_CLIENT_SECRET' => 'oidc_client_secret',
        'GPTOIDC_OIDC_ACCESS_TOKEN_TTL' => 'oidc_access_token_ttl',
        'GPTOIDC_OIDC_ID_TOKEN_TTL' => 'oidc_id_token_ttl',
        'GPTOIDC_OIDC_AUTH_CODE_TTL' => 'oidc_auth_code_ttl',
        'GPTOIDC_JWT_PRIVATE_KEY_PATH' => 'jwt_private_key_path',
        'GPTOIDC_JWT_PUBLIC_KEY_PATH' => 'jwt_public_key_path',
    ];
    foreach ($simpleMap as $envKey => $configKey) {
        if (array_key_exists($envKey, $envValues) && $envValues[$envKey] !== '') {
            $config[$configKey] = $envValues[$envKey];
        }
    }
    if (array_key_exists('GPTOIDC_APP_DEBUG', $envValues) && $envValues['GPTOIDC_APP_DEBUG'] !== '') {
        $config['app_debug'] = in_array(strtolower((string) $envValues['GPTOIDC_APP_DEBUG']), ['1', 'true', 'yes', 'on'], true);
    }
    if (array_key_exists('GPTOIDC_ALLOWED_EMAIL_DOMAINS', $envValues) && trim((string) $envValues['GPTOIDC_ALLOWED_EMAIL_DOMAINS']) !== '') {
        $config['allowed_email_domains'] = app_env_csv($envValues['GPTOIDC_ALLOWED_EMAIL_DOMAINS']);
    }
    if (array_key_exists('GPTOIDC_OIDC_ALLOWED_REDIRECT_URIS', $envValues) && trim((string) $envValues['GPTOIDC_OIDC_ALLOWED_REDIRECT_URIS']) !== '') {
        $config['oidc_allowed_redirect_uris'] = app_env_csv($envValues['GPTOIDC_OIDC_ALLOWED_REDIRECT_URIS']);
    }
    return $config;
}

$configFile = __DIR__ . '/config.php';
$sampleFile = __DIR__ . '/config.sample.php';
$envFile = dirname(__DIR__) . '/.env';

$GLOBALS['app_env_values'] = app_load_env_file($envFile);

$GLOBALS['app_config_missing'] = !is_file($configFile);
$GLOBALS['app_config'] = app_apply_env_overrides(
    require $GLOBALS['app_config_missing'] ? $sampleFile : $configFile,
    $GLOBALS['app_env_values']
);

$requestPath = app_path();
$statelessPaths = [
    '/.well-known/openid-configuration',
    '/jwks.json',
    '/token',
    '/userinfo',
];

if (!in_array($requestPath, $statelessPaths, true)) {
    app_start_session();
}

date_default_timezone_set('UTC');

function app_config($key, $default = null)
{
    return array_key_exists($key, $GLOBALS['app_config']) ? $GLOBALS['app_config'][$key] : $default;
}

function app_config_path()
{
    return __DIR__ . '/config.php';
}

function app_is_configured()
{
    return empty($GLOBALS['app_config_missing']);
}

function app_set_runtime_config(array $config)
{
    $GLOBALS['app_config'] = $config;
    $GLOBALS['app_config_missing'] = false;
}

function app_write_config(array $config)
{
    $sampleConfig = require __DIR__ . '/config.sample.php';
    $envManagedSecretMap = [
        'GPTOIDC_APP_KEY' => 'app_key',
        'GPTOIDC_APP_PEPPER' => 'app_pepper',
        'GPTOIDC_API_KEY' => 'api_key',
        'GPTOIDC_DB_PASS' => 'db_pass',
        'GPTOIDC_OIDC_CLIENT_SECRET' => 'oidc_client_secret',
    ];
    foreach ($envManagedSecretMap as $envKey => $configKey) {
        if (!empty($GLOBALS['app_env_values'][$envKey] ?? '')) {
            $config[$configKey] = $sampleConfig[$configKey] ?? '';
        }
    }
    $content = "<?php\n\nreturn " . var_export($config, true) . ";\n";
    $written = file_put_contents(app_config_path(), $content);
    if ($written === false) {
        throw new RuntimeException('无法写入 app/config.php，请检查目录写权限。');
    }
    app_set_runtime_config($config);
}

function app_require_configured()
{
    if (empty($GLOBALS['app_config_missing'])) {
        return;
    }

    app_render_page('需要先完成安装', '<div class="notice error"><strong>系统尚未配置。</strong> 请先打开 <code>/install</code> 完成安装，或手动创建 <code>app/config.php</code> 后再使用。</div>');
    exit;
}
