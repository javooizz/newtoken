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
require_once __DIR__ . '/clients.php';

$configFile = __DIR__ . '/config.php';
$sampleFile = __DIR__ . '/config.sample.php';

$GLOBALS['app_config_missing'] = !is_file($configFile);
$GLOBALS['app_config'] = require $GLOBALS['app_config_missing'] ? $sampleFile : $configFile;

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
