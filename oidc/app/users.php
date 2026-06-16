<?php

function app_find_user_by_email($email)
{
    return app_db_one('SELECT * FROM users WHERE email = :email LIMIT 1', ['email' => strtolower($email)]);
}

function app_find_admin_by_username($username)
{
    return app_db_one('SELECT * FROM admins WHERE username = :username LIMIT 1', ['username' => $username]);
}

function app_activate_user($plainCard, $email, $fullName)
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

    if (!app_allowed_email($email)) {
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
    $domain = substr(strrchr($email, '@'), 1);
    $subject = 'usr_' . app_random_hex(16);
    $pdo = app_pdo();
    $pdo->beginTransaction();

    try {
        app_db_exec('INSERT INTO users (oidc_subject, email, email_domain, full_name, given_name, family_name, password_hash, status, activated_by_card_id, activated_at, created_at, updated_at) VALUES (:oidc_subject, :email, :email_domain, :full_name, :given_name, :family_name, :password_hash, :status, :activated_by_card_id, :activated_at, :created_at, :updated_at)', [
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
    app_audit('user', (int) $user['id'], 'user_activated', 'card', (string) $card['id'], ['email' => $email]);

    return $user;
}

function app_user_for_card(array $card)
{
    if (empty($card['used_by_user_id'])) {
        return null;
    }

    return app_db_one('SELECT * FROM users WHERE id = :id LIMIT 1', ['id' => (int) $card['used_by_user_id']]);
}

function app_touch_user_login($userId)
{
    app_db_exec('UPDATE users SET last_login_at = :last_login_at, updated_at = :updated_at WHERE id = :id', [
        'last_login_at' => app_now(),
        'updated_at' => app_now(),
        'id' => (int) $userId,
    ]);
}

function app_authenticate_admin($username, $password)
{
    $admin = app_find_admin_by_username($username);
    if (!$admin || $admin['status'] !== 'active') {
        return null;
    }

    if (!app_password_verify_value($password, $admin['password_hash'])) {
        return null;
    }

    app_db_exec('UPDATE admins SET last_login_at = :last_login_at, updated_at = :updated_at WHERE id = :id', [
        'last_login_at' => app_now(),
        'updated_at' => app_now(),
        'id' => (int) $admin['id'],
    ]);

    return $admin;
}


function app_internal_provision_user($email, $fullName = '')
{
    $email = strtolower(trim((string) $email));
    $fullName = trim((string) $fullName);
    if (!app_allowed_email($email)) {
        throw new RuntimeException('当前邮箱后缀不允许自动直通登录。');
    }
    $user = app_find_user_by_email($email);
    if ($user) {
        if ($user['status'] !== 'active') {
            app_db_exec('UPDATE users SET status = :status, updated_at = :updated_at WHERE id = :id', [
                'status' => 'active',
                'updated_at' => app_now(),
                'id' => (int) $user['id'],
            ]);
            $user = app_find_user_by_email($email);
        }
        return $user;
    }
    if ($fullName === '') {
        $emailParts = explode('@', $email, 2);
        $fullName = $emailParts[0];
    }
    $nameParts = preg_split('/\s+/', $fullName);
    $givenName = isset($nameParts[0]) ? $nameParts[0] : $fullName;
    $familyName = count($nameParts) > 1 ? $nameParts[count($nameParts) - 1] : $givenName;
    $domain = substr(strrchr($email, '@'), 1);
    $subject = 'usr_' . app_random_hex(16);
    app_db_exec('INSERT INTO users (oidc_subject, email, email_domain, full_name, given_name, family_name, password_hash, status, activated_by_card_id, activated_at, created_at, updated_at) VALUES (:oidc_subject, :email, :email_domain, :full_name, :given_name, :family_name, :password_hash, :status, :activated_by_card_id, :activated_at, :created_at, :updated_at)', [
        'oidc_subject' => $subject,
        'email' => $email,
        'email_domain' => $domain,
        'full_name' => $fullName,
        'given_name' => $givenName,
        'family_name' => $familyName,
        'password_hash' => app_password_hash_value(app_random_hex(32)),
        'status' => 'active',
        'activated_by_card_id' => null,
        'activated_at' => app_now(),
        'created_at' => app_now(),
        'updated_at' => app_now(),
    ]);
    $user = app_find_user_by_email($email);
    app_audit('system', null, 'internal_user_provisioned', 'user', (string) $user['id'], ['email' => $email]);
    return $user;
}
