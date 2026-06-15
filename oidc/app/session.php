<?php

function app_start_session()
{
    if (session_status() === PHP_SESSION_ACTIVE) {
        return;
    }

    session_name((string) app_config('session_name', 'GPTOIDCSESSID'));
    ini_set('session.use_only_cookies', '1');
    ini_set('session.use_strict_mode', '1');
    ini_set('session.cookie_httponly', '1');
    ini_set('session.cookie_secure', app_is_https() ? '1' : '0');
    session_set_cookie_params([
        'lifetime' => 0,
        'path' => '/',
        'domain' => '',
        'secure' => app_is_https(),
        'httponly' => true,
        'samesite' => 'Lax',
    ]);
    session_start();
}

function app_close_session()
{
    if (session_status() === PHP_SESSION_ACTIVE) {
        session_write_close();
    }
}

function app_login_user(array $user)
{
    app_start_session();
    session_regenerate_id(true);
    $_SESSION['user_id'] = (int) $user['id'];
}

function app_login_admin(array $admin)
{
    app_start_session();
    session_regenerate_id(true);
    $_SESSION['admin_id'] = (int) $admin['id'];
}

function app_logout_user()
{
    app_start_session();
    unset($_SESSION['user_id']);
}

function app_logout_admin()
{
    app_start_session();
    unset($_SESSION['admin_id']);
}

function app_current_user()
{
    app_start_session();
    if (empty($_SESSION['user_id'])) {
        return null;
    }

    $user = app_db_one('SELECT * FROM users WHERE id = :id LIMIT 1', ['id' => (int) $_SESSION['user_id']]);
    if (!$user || $user['status'] !== 'active') {
        unset($_SESSION['user_id']);
        return null;
    }

    return $user;
}

function app_current_admin()
{
    app_start_session();
    if (empty($_SESSION['admin_id'])) {
        return null;
    }

    $admin = app_db_one('SELECT * FROM admins WHERE id = :id LIMIT 1', ['id' => (int) $_SESSION['admin_id']]);
    if (!$admin || $admin['status'] !== 'active') {
        unset($_SESSION['admin_id']);
        return null;
    }

    return $admin;
}

function app_require_user()
{
    $user = app_current_user();
    if (!$user) {
        $_SESSION['post_login_redirect'] = isset($_SERVER['REQUEST_URI']) ? $_SERVER['REQUEST_URI'] : '/';
        app_redirect('/sso');
    }

    return $user;
}

function app_require_admin()
{
    $admin = app_current_admin();
    if (!$admin) {
        app_redirect('/admin/login');
    }

    return $admin;
}

function app_flash_set($type, $message)
{
    app_start_session();
    $_SESSION['flash'] = ['type' => $type, 'message' => $message];
}

function app_flash_get()
{
    app_start_session();
    if (empty($_SESSION['flash'])) {
        return null;
    }

    $flash = $_SESSION['flash'];
    unset($_SESSION['flash']);

    return $flash;
}
