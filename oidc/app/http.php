<?php

function app_method()
{
    return isset($_SERVER['REQUEST_METHOD']) ? strtoupper($_SERVER['REQUEST_METHOD']) : 'GET';
}

function app_path()
{
    $uri = isset($_SERVER['REQUEST_URI']) ? $_SERVER['REQUEST_URI'] : '/';
    $path = parse_url($uri, PHP_URL_PATH);

    return $path ?: '/';
}

function app_query($key, $default = null)
{
    return isset($_GET[$key]) ? trim((string) $_GET[$key]) : $default;
}

function app_post($key, $default = null)
{
    return isset($_POST[$key]) ? trim((string) $_POST[$key]) : $default;
}

function app_post_raw()
{
    return file_get_contents('php://input');
}

function app_base_url()
{
    return rtrim((string) app_config('app_url', ''), '/');
}

function app_is_https()
{
    if (!empty($_SERVER['HTTPS']) && strtolower((string) $_SERVER['HTTPS']) !== 'off') {
        return true;
    }

    if (isset($_SERVER['SERVER_PORT']) && (string) $_SERVER['SERVER_PORT'] === '443') {
        return true;
    }

    return stripos((string) app_config('app_url', ''), 'https://') === 0;
}

function app_redirect($location, $status = 302)
{
    if (function_exists('app_close_session')) {
        app_close_session();
    }
    header('Location: ' . $location, true, $status);
    exit;
}

function app_json(array $payload, $status = 200)
{
    if (function_exists('app_close_session')) {
        app_close_session();
    }
    http_response_code($status);
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode($payload, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    exit;
}

function app_h($value)
{
    return htmlspecialchars((string) $value, ENT_QUOTES, 'UTF-8');
}

function app_ip()
{
    $candidates = [];

    if (!empty($_SERVER['HTTP_CF_CONNECTING_IP'])) {
        $candidates[] = $_SERVER['HTTP_CF_CONNECTING_IP'];
    }

    if (!empty($_SERVER['HTTP_X_FORWARDED_FOR'])) {
        $forwarded = explode(',', (string) $_SERVER['HTTP_X_FORWARDED_FOR']);
        foreach ($forwarded as $item) {
            $candidates[] = trim($item);
        }
    }

    if (!empty($_SERVER['REMOTE_ADDR'])) {
        $candidates[] = $_SERVER['REMOTE_ADDR'];
    }

    foreach ($candidates as $candidate) {
        $candidate = trim((string) $candidate);
        if ($candidate !== '' && filter_var($candidate, FILTER_VALIDATE_IP)) {
            return substr($candidate, 0, 64);
        }
    }

    return '0.0.0.0';
}

function app_is_post()
{
    return app_method() === 'POST';
}

function app_now()
{
    return gmdate('Y-m-d H:i:s');
}
