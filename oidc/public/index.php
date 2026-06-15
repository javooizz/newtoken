<?php

require_once __DIR__ . '/../app/bootstrap.php';

function app_parse_csvish($value)
{
    $value = str_replace(["\r\n", "\r"], "\n", (string) $value);
    $value = str_replace(',', "\n", $value);
    $items = [];
    foreach (explode("\n", $value) as $line) {
        $line = trim($line);
        if ($line !== '') {
            $items[] = $line;
        }
    }

    return array_values(array_unique($items));
}

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

function app_validate_config_payload(array $config)
{
    if (trim((string) $config['app_url']) === '' || trim((string) $config['oidc_issuer']) === '') {
        throw new RuntimeException('应用地址和 OIDC Issuer 不能为空。');
    }
}

function app_split_email_parts($email)
{
    $email = strtolower(trim((string) $email));
    if (!filter_var($email, FILTER_VALIDATE_EMAIL)) {
        return [null, null];
    }

    $parts = explode('@', $email, 2);

    return [$parts[0], $parts[1]];
}

function app_login_hint_email()
{
    $pending = app_oidc_pending_authorize();
    if (!$pending || empty($pending['login_hint'])) {
        return '';
    }

    $hint = strtolower(trim((string) $pending['login_hint']));

    return filter_var($hint, FILTER_VALIDATE_EMAIL) ? $hint : '';
}

function app_build_login_email_from_request()
{
    $prefix = strtolower(trim((string) app_post('email_prefix')));
    $domain = strtolower(trim((string) app_post('email_domain')));
    if ($prefix === '' || $domain === '') {
        throw new RuntimeException('邮箱前缀和邮箱后缀不能为空。');
    }

    $email = $prefix . '@' . $domain;
    if (!app_allowed_email($email)) {
        throw new RuntimeException('当前邮箱后缀不允许登录。');
    }

    $hint = app_login_hint_email();
    if ($hint !== '' && !hash_equals($hint, $email)) {
        throw new RuntimeException('邮箱必须与 OpenAI 登录时输入的邮箱一致。');
    }

    return $email;
}

$path = app_path();
$schemaReady = app_is_configured() ? app_schema_ready() : false;
$installRecovery = app_is_configured() && $schemaReady && !app_admin_exists();

if ($path === '/install') {
    if (app_is_configured() && $schemaReady && !$installRecovery) {
        app_flash_set('info', '系统已经安装完成，如需修改配置请进入管理后台。');
        app_redirect('/admin');
    }

    if (app_is_post()) {
        if (!app_validate_csrf_token('install', app_post('csrf_token'))) {
            app_flash_set('error', 'CSRF 校验失败。');
            app_redirect('/install');
        }

        try {
            $payload = [
                'app_url' => app_post('app_url'),
                'allowed_email_domains' => app_post('allowed_email_domains'),
                'db_host' => app_post('db_host'),
                'db_port' => app_post('db_port'),
                'db_name' => app_post('db_name'),
                'db_user' => app_post('db_user'),
                'db_pass' => isset($_POST['db_pass']) ? (string) $_POST['db_pass'] : '',
                'oidc_client_id' => app_post('oidc_client_id'),
                'oidc_client_secret' => app_post('oidc_client_secret'),
                'oidc_redirect_uris' => app_post('oidc_redirect_uris'),
                'api_key' => app_post('api_key'),
                'admin_username' => app_post('admin_username'),
                'admin_email' => app_post('admin_email'),
                'admin_password' => isset($_POST['admin_password']) ? (string) $_POST['admin_password'] : '',
            ];

            if ($installRecovery) {
                if (trim((string) $payload['admin_username']) === '' || trim((string) $payload['admin_email']) === '' || (string) $payload['admin_password'] === '') {
                    throw new RuntimeException('恢复管理员时必须填写管理员信息。');
                }
                if (!is_file(app_config('jwt_private_key_path')) || !is_file(app_config('jwt_public_key_path'))) {
                    app_oidc_generate_keys(app_config('jwt_private_key_path'), app_config('jwt_public_key_path'));
                }
            } else {
                app_validate_install_payload($payload);
                $config = app_build_config_from_request($payload);
                app_validate_config_payload($config);
                app_ensure_database_exists($config);
                $pdo = app_make_pdo_from_config($config);
                app_import_schema($pdo, dirname(__DIR__) . '/sql/schema.sql');
                app_write_config($config);
                app_oidc_generate_keys($config['jwt_private_key_path'], $config['jwt_public_key_path']);
            }

            $admin = app_create_admin($payload['admin_username'], $payload['admin_email'], $payload['admin_password'], 'owner');
            app_login_admin($admin);
            app_flash_set('success', $installRecovery ? '管理员恢复完成。' : '安装完成，请先生成卡密，再去 OpenAI 配置 Custom OIDC。');
            app_redirect('/admin');
        } catch (Exception $e) {
            app_flash_set('error', $e->getMessage());
            app_redirect('/install');
        }
    }

    app_render_page('安装', app_install_html(app_issue_csrf_token('install'), $installRecovery, $GLOBALS['app_config']), ['show_nav' => false]);
}

if ((!app_is_configured() || !$schemaReady || $installRecovery) && $path !== '/install') {
    app_redirect('/install');
}

if ($path === '/.well-known/openid-configuration') {
    app_json(app_oidc_discovery_document());
}

if ($path === '/jwks.json') {
    app_json(app_oidc_public_jwk());
}

if ($path === '/token') {
    if (!app_is_post()) {
        app_json(['error' => 'invalid_request'], 405);
    }
    app_oidc_exchange_code($_POST);
}

if ($path === '/userinfo') {
    $user = app_oidc_bearer_user();
    if (!$user) {
        app_json(['error' => 'invalid_token'], 401);
    }
    $fullName = !empty($user['full_name']) ? $user['full_name'] : $user['email'];
    $givenName = !empty($user['given_name']) ? $user['given_name'] : $fullName;
    $familyName = !empty($user['family_name']) ? $user['family_name'] : $givenName;
    app_json([
        'sub' => $user['oidc_subject'],
        'email' => $user['email'],
        'email_verified' => true,
        'name' => $fullName,
        'given_name' => $givenName,
        'family_name' => $familyName,
    ]);
}

if ($path === '/api/status') { app_api_status(); }
if ($path === '/api/cards/generate' && app_method() === 'POST') { app_api_cards_generate(); }
if ($path === '/api/cards/lookup' && app_method() === 'POST') { app_api_card_lookup(); }
if ($path === '/api/clients' && app_method() === 'POST') { app_api_clients_create(); }
if ($path === '/api/clients' && app_method() === 'GET') { app_api_clients_list(); }
if (preg_match('#^/api/clients/([A-Za-z0-9_]+)$#', $path, $m) && app_method() === 'GET') { app_api_clients_get($m[1]); }
if (preg_match('#^/api/clients/([A-Za-z0-9_]+)$#', $path, $m) && app_method() === 'PATCH') { app_api_clients_update($m[1]); }

if ($path === '/') {
    $lookup = [];
    if (app_query('lookup') === '1') {
        $plainCard = app_normalize_card_value(app_query('card_key'));
        $lookup = [
            'card_key' => $plainCard,
            'email' => app_lookup_card_bound_email($plainCard),
        ];
    }

    app_render_page('总览', app_home_html($lookup));
}

if ($path === '/flow-demo') {
    app_render_page('OIDC 流程演示', app_flow_demo_html());
}

if ($path === '/ui-kit') {
    app_render_page('界面参考', app_ui_kit_html());
}

if ($path === '/logout' && app_is_post()) {
    if (!app_validate_csrf_token('user_logout', app_post('csrf_token'))) {
        app_flash_set('error', 'CSRF 校验失败。');
        app_redirect('/');
    }
    app_logout_user();
    app_flash_set('success', '已退出登录。');
    app_redirect('/sso');
}

if ($path === '/admin/logout' && app_is_post()) {
    if (!app_validate_csrf_token('admin_logout', app_post('csrf_token'))) {
        app_flash_set('error', 'CSRF 校验失败。');
        app_redirect('/admin');
    }
    app_logout_admin();
    app_flash_set('success', '管理员已退出登录。');
    app_redirect('/admin/login');
}

if ($path === '/login') {
    app_redirect('/sso');
}

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

if ($path === '/activate') {
    app_redirect('/sso');
}

if ($path === '/admin/login') {
    $adminRateBucket = 'admin_login_' . app_ip();
    if (app_is_post()) {
        if (!app_validate_csrf_token('admin_login', app_post('csrf_token'))) {
            app_flash_set('error', 'CSRF 校验失败。');
            app_redirect('/admin/login');
        }
        if (app_rate_limit_exceeded($adminRateBucket, 10, 300)) {
            app_flash_set('error', '尝试次数过多，请稍后再试。');
            app_redirect('/admin/login');
        }

        $admin = app_authenticate_admin(app_post('username'), app_post('password'));
        if (!$admin) {
            app_audit('system', null, 'admin_login_failed', 'username', (string) app_post('username'), []);
            app_rate_limit_record($adminRateBucket, 300);
            app_flash_set('error', '管理员账号或密码错误。');
            app_redirect('/admin/login');
        }

        app_login_admin($admin);
        app_rate_limit_clear($adminRateBucket);
        app_audit('admin', (int) $admin['id'], 'admin_login_success', 'admin', (string) $admin['id'], []);
        app_redirect('/admin');
    }

    $body = '<div class="center-shell"><section class="install-hero"><span class="pill">管理员入口</span><h1>管理后台登录</h1><p>这里用于生成卡密、一次性导出、管理用户、查看审计日志，以及修改运行配置。</p></section><section class="card"><form method="post" class="stack"><input type="hidden" name="csrf_token" value="' . app_h(app_issue_csrf_token('admin_login')) . '"><div class="form-grid"><div class="field"><label>管理员用户名</label><input type="text" name="username" required></div><div class="field"><label>管理员密码</label><input type="password" name="password" required></div></div><div class="actions"><button type="submit">进入后台</button></div></form></section></div>';
    app_render_page('管理员登录', $body, ['show_nav' => false]);
}

if ($path === '/admin/cards/export' && app_is_post()) {
    $admin = app_require_admin();
    if (!app_validate_csrf_token('admin_cards_export', app_post('csrf_token'))) {
        app_flash_set('error', 'CSRF 校验失败。');
        app_redirect('/admin');
    }
    $batchNo = app_post('batch_no');
    $cards = app_export_batch_csv($batchNo);
    if (!$cards) {
        app_flash_set('error', '这个批次已经不能再导出明文卡密了。');
        app_redirect('/admin');
    }

    app_audit('admin', (int) $admin['id'], 'card_exported', 'batch', $batchNo, ['count' => count($cards)]);
    header('Content-Type: text/csv; charset=utf-8');
    header('Content-Disposition: attachment; filename="cards-' . preg_replace('/[^A-Za-z0-9_-]/', '', $batchNo) . '.csv"');
    echo "batch_no,card_key\n";
    foreach ($cards as $card) {
        echo $batchNo . ',' . $card . "\n";
    }
    exit;
}

if ($path === '/admin/cards/generate' && app_is_post()) {
    $admin = app_require_admin();
    if (!app_validate_csrf_token('admin_cards', app_post('csrf_token'))) {
        app_flash_set('error', 'CSRF 校验失败。');
        app_redirect('/admin');
    }

    try {
        $days = (int) app_post('expires_in_days');
        $expiresAt = $days > 0 ? gmdate('Y-m-d H:i:s', time() + ($days * 86400)) : null;
        $batchNo = app_create_card_batch($admin['id'], (int) app_post('count'), $expiresAt, app_post('note'));
        app_flash_set('success', '批次已创建：' . $batchNo . '。请立刻导出，因为明文卡密只会保留一次。');
    } catch (Exception $e) {
        app_flash_set('error', $e->getMessage());
    }
    app_redirect('/admin');
}

if ($path === '/admin/cards/revoke' && app_is_post()) {
    $admin = app_require_admin();
    if (!app_validate_csrf_token('admin_cards', app_post('csrf_token'))) {
        app_flash_set('error', 'CSRF 校验失败。');
        app_redirect('/admin');
    }
    try {
        app_admin_revoke_card($admin['id'], app_post('card_id'));
        app_flash_set('success', '卡密已吊销。');
    } catch (Exception $e) {
        app_flash_set('error', $e->getMessage());
    }
    app_redirect('/admin');
}

if ($path === '/admin/cards/delete-plain' && app_is_post()) {
    $admin = app_require_admin();
    if (!app_validate_csrf_token('admin_cards', app_post('csrf_token'))) {
        app_flash_set('error', 'CSRF 校验失败。');
        app_redirect('/admin');
    }
    try {
        $result = app_admin_delete_plain_cards($admin['id'], app_parse_csvish(app_post('card_keys_plain')));
        $type = $result['deleted_count'] > 0 ? 'success' : 'info';
        $message = $result['deleted_count'] > 0 ? '已删除 ' . $result['deleted_count'] . ' 张卡密' : '未删除任何卡密';
        if ($result['missing_count'] > 0 || $result['deleted_count'] === 0) {
            $message .= '，未找到 ' . $result['missing_count'] . ' 张';
        }
        if ($result['export_sync_failed_count'] > 0) {
            $message .= '，其中 ' . $result['export_sync_failed_count'] . ' 张未能同步更新导出文件';
        }
        $message .= '。';
        app_flash_set($type, $message);
    } catch (Exception $e) {
        app_flash_set('error', $e->getMessage());
    }
    app_redirect('/admin');
}

if ($path === '/admin/cards/reissue-user' && app_is_post()) {
    $admin = app_require_admin();
    if (!app_validate_csrf_token('admin_cards', app_post('csrf_token'))) {
        app_flash_set('error', 'CSRF 校验失败。');
        app_redirect('/admin');
    }
    try {
        $days = (int) app_post('expires_in_days');
        $expiresAt = $days > 0 ? gmdate('Y-m-d H:i:s', time() + ($days * 86400)) : null;
        $result = app_admin_issue_existing_user_card($admin['id'], app_post('user_email'), $expiresAt, app_post('note'));
        app_flash_set('success', '已为 ' . $result['user']['email'] . ' 生成可用卡密：' . $result['card_key']);
    } catch (Exception $e) {
        app_flash_set('error', $e->getMessage());
    }
    app_redirect('/admin');
}

if ($path === '/admin/users/disable' && app_is_post()) {
    $admin = app_require_admin();
    if (!app_validate_csrf_token('admin_users', app_post('csrf_token'))) {
        app_flash_set('error', 'CSRF 校验失败。');
        app_redirect('/admin');
    }
    app_admin_disable_user($admin['id'], app_post('user_id'));
    app_flash_set('success', '用户已禁用。');
    app_redirect('/admin');
}

if ($path === '/admin/users/enable' && app_is_post()) {
    $admin = app_require_admin();
    if (!app_validate_csrf_token('admin_users', app_post('csrf_token'))) {
        app_flash_set('error', 'CSRF 校验失败。');
        app_redirect('/admin');
    }
    app_admin_enable_user($admin['id'], app_post('user_id'));
    app_flash_set('success', '用户已恢复启用。');
    app_redirect('/admin');
}

if ($path === '/admin/settings/save' && app_is_post()) {
    $admin = app_require_admin();
    if (!app_validate_csrf_token('admin_settings', app_post('csrf_token'))) {
        app_flash_set('error', 'CSRF 校验失败。');
        app_redirect('/admin');
    }

    try {
        $config = app_build_config_from_request([
            'app_url' => app_post('app_url'),
            'allowed_email_domains' => app_post('allowed_email_domains'),
            'db_host' => app_config('db_host'),
            'db_port' => app_config('db_port'),
            'db_name' => app_config('db_name'),
            'db_user' => app_config('db_user'),
            'db_pass' => app_config('db_pass'),
            'oidc_issuer' => app_post('oidc_issuer'),
            'oidc_client_id' => app_post('oidc_client_id'),
            'oidc_client_secret' => app_post('oidc_client_secret'),
            'oidc_redirect_uris' => app_post('oidc_redirect_uris'),
            'api_key' => app_post('api_key'),
            'oidc_access_token_ttl' => app_post('oidc_access_token_ttl'),
            'oidc_id_token_ttl' => app_post('oidc_id_token_ttl'),
            'oidc_auth_code_ttl' => app_post('oidc_auth_code_ttl'),
        ], $GLOBALS['app_config']);

        app_validate_config_payload($config);
        app_write_config($config);
        app_audit('admin', (int) $admin['id'], 'settings_updated', 'config', 'app', []);
        app_flash_set('success', '设置已保存到 app/config.php。');
    } catch (Exception $e) {
        app_flash_set('error', $e->getMessage());
    }

    app_redirect('/admin');
}

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

if ($path === '/admin') {
    $admin = app_require_admin();
    $batchRows = app_admin_batches();
    $cardsRows = app_admin_cards();
    $usersRows = app_admin_users();
    $logsRows = app_admin_logs();
    $config = $GLOBALS['app_config'];
    $cardLookupInput = app_normalize_card_value(app_query('card_key'));
    $cardLookupResult = app_query('card_lookup') === '1' && $cardLookupInput !== '' ? app_admin_find_card_by_plain($cardLookupInput) : null;
    $unusedCount = app_db_one("SELECT COUNT(*) AS c FROM card_keys WHERE status = 'unused'");
    $activeUsers = app_db_one("SELECT COUNT(*) AS c FROM users WHERE status = 'active'");
    $body = '<section class="hero"><span class="pill">管理工作区</span><h1>管理后台</h1><p>当前登录管理员：<strong>' . app_h($admin['username']) . '</strong>。用户侧现在是纯卡密登录，卡密本身就是用户凭证。</p><div class="actions" style="margin-top:16px"><a class="button-link inline secondary" href="/admin/clients">母号管理</a><form method="post" action="/admin/logout"><input type="hidden" name="csrf_token" value="' . app_h(app_issue_csrf_token('admin_logout')) . '"><button class="inline secondary" type="submit">退出后台</button></form></div></section>';
    $body .= '<section class="grid"><div class="card"><div class="small">未绑定卡密</div><div class="metric">' . app_h(isset($unusedCount['c']) ? $unusedCount['c'] : 0) . '</div></div><div class="card"><div class="small">启用用户</div><div class="metric">' . app_h(isset($activeUsers['c']) ? $activeUsers['c'] : 0) . '</div></div><div class="card"><div class="small">OIDC 标识地址</div><div class="metric mono" style="font-size:18px">' . app_h($config['oidc_issuer']) . '</div></div></section>';
    $body .= '<section class="split"><div>';
    $body .= '<div class="card"><div class="section-title"><h3>创建卡密批次</h3><span class="badge">一次性导出</span></div><form method="post" action="/admin/cards/generate" class="stack"><input type="hidden" name="csrf_token" value="' . app_h(app_issue_csrf_token('admin_cards')) . '"><div class="form-grid"><div class="field"><label>数量</label><input type="number" name="count" min="1" max="500" value="10" required></div><div class="field"><label>有效天数（0 表示不过期）</label><input type="number" name="expires_in_days" min="0" value="30"></div></div><div class="field"><label>批次备注</label><textarea name="note" placeholder="例如：2026-Q2 社区发卡"></textarea></div><div class="actions"><button type="submit">生成批次</button></div></form></div>';
    $body .= '<div class="card"><div class="section-title"><h3>按明文删除卡密</h3><span class="badge">每行一张</span></div><p class="small">支持一次删除多张卡密。删除后这张卡将无法再登录；如果只是给老用户补发新卡，请使用下面的补发功能。</p><form method="post" action="/admin/cards/delete-plain" class="stack"><input type="hidden" name="csrf_token" value="' . app_h(app_issue_csrf_token('admin_cards')) . '"><div class="field"><label>完整卡密列表</label><textarea name="card_keys_plain" placeholder="AB12CD-EF34GH-IJ56KL-MN78OP&#10;CD34EF-GH56IJ-KL78MN-OP90QR" required></textarea></div><div class="actions"><button class="inline warn" type="submit">批量删除卡密</button></div></form></div>';
    $body .= '<div class="card"><div class="section-title"><h3>给老用户补发卡密</h3><span class="badge">直接可用</span></div><p class="small">输入已存在用户的邮箱即可生成一张新的可用卡密。不会自动删除旧卡，如果要替换旧卡，可先或后使用上面的明文删除。</p><form method="post" action="/admin/cards/reissue-user" class="stack"><input type="hidden" name="csrf_token" value="' . app_h(app_issue_csrf_token('admin_cards')) . '"><div class="form-grid"><div class="field"><label>用户邮箱</label><input type="email" name="user_email" required></div><div class="field"><label>有效天数（0 表示不过期）</label><input type="number" name="expires_in_days" min="0" value="30"></div></div><div class="field"><label>备注</label><input type="text" name="note" placeholder="例如：补发卡密"></div><div class="actions"><button type="submit">生成新卡密</button></div></form></div>';
    $body .= app_settings_form_html($config, app_issue_csrf_token('admin_settings'));
    $statusMap = ['unused' => '未使用', 'used' => '已绑定', 'revoked' => '已吊销', 'expired' => '已过期'];
    $cardLookupResultHtml = '';
    if (app_query('card_lookup') === '1') {
        if ($cardLookupResult) {
            $cardStatus = isset($statusMap[$cardLookupResult['status']]) ? $statusMap[$cardLookupResult['status']] : $cardLookupResult['status'];
            $cardLookupResultHtml = '<div class="list"><div class="row">状态：' . app_h($cardStatus) . '</div><div class="row">绑定邮箱：' . app_h($cardLookupResult['user_email'] ? $cardLookupResult['user_email'] : '-') . '</div><div class="row">批次：' . app_h($cardLookupResult['batch_no']) . '</div><div class="row">过期时间：' . app_h($cardLookupResult['expires_at']) . '</div></div>';
        } else {
            $cardLookupResultHtml = '<div class="alert info">没有查到这张卡密。</div>';
        }
    }
    $body .= '</div><div><div class="card"><div class="section-title"><h3>卡密状态查询</h3></div><form method="get" action="/admin" class="stack"><input type="hidden" name="card_lookup" value="1"><div class="field"><label>完整卡密</label><input class="mono" type="text" name="card_key" placeholder="AB12CD-EF34GH-IJ56KL-MN78OP" value="' . app_h($cardLookupInput) . '" required></div><div class="actions"><button type="submit">查询是否使用</button></div></form>' . $cardLookupResultHtml . '</div><div class="card"><div class="section-title"><h3>OpenAI 配置复制值</h3></div><div class="code-panel mono">Issuer: ' . app_h($config['oidc_issuer']) . '<br>Discovery URL: ' . app_h($config['oidc_issuer']) . '/.well-known/openid-configuration<br>Authorization Endpoint: ' . app_h($config['oidc_issuer']) . '/authorize<br>Token Endpoint: ' . app_h($config['oidc_issuer']) . '/token<br>Userinfo Endpoint: ' . app_h($config['oidc_issuer']) . '/userinfo<br>JWKS URL: ' . app_h($config['oidc_issuer']) . '/jwks.json<br>Scopes: openid profile email</div><p class="small">把这些值填到 ChatGPT Business -> Identity -> Set up SSO -> Custom OIDC。OpenAI 向导里生成的 Login redirect URI 要填到系统设置里的“OpenAI 回调白名单”。联调期间请保持 SSO 为 Optional。</p></div><div class="card"><div class="section-title"><h3>运维提示</h3></div><div class="list"><div class="row">Business SSO 只覆盖 ChatGPT，不覆盖 API Platform。</div><div class="row">Business 没有 SCIM，因此工作区成员仍需在 OpenAI 后台手工处理。</div><div class="row">卡密生成后请立刻导出，因为数据库不保存明文卡密。</div></div></div></div></section>';
    $body .= '<section class="card"><div class="section-title"><h3>批次导出</h3></div><div class="table-wrap"><table><tr><th>批次</th><th>卡密数量</th><th>未绑定</th><th>已绑定</th><th>已吊销</th><th>导出状态</th><th>过期时间</th><th>操作</th></tr>';
    foreach ($batchRows as $row) {
        $exportable = app_export_batch_file_exists($row['batch_no']);
        $exportStatus = $exportable ? '可导出' : (!empty($row['exported_at']) ? '已导出' : '无明文文件');
        $action = $exportable ? '<form method="post" action="/admin/cards/export"><input type="hidden" name="csrf_token" value="' . app_h(app_issue_csrf_token('admin_cards_export')) . '"><input type="hidden" name="batch_no" value="' . app_h($row['batch_no']) . '"><button class="inline secondary" type="submit">导出整批</button></form>' : '-';
        $body .= '<tr><td>' . app_h($row['batch_no']) . '</td><td>' . app_h($row['card_count']) . '</td><td>' . app_h($row['unused_count']) . '</td><td>' . app_h($row['used_count']) . '</td><td>' . app_h($row['revoked_count']) . '</td><td>' . app_h($exportStatus) . '</td><td>' . app_h($row['expires_at']) . '</td><td>' . $action . '</td></tr>';
    }
    $body .= '</table></div><p class="small">这里按批次导出，一次导出整个批次，不需要在明细里逐条点击。</p></section>';
    $body .= '<section class="card"><div class="section-title"><h3>卡密列表</h3></div><div class="table-wrap"><table><tr><th>ID</th><th>批次</th><th>掩码卡密</th><th>状态</th><th>绑定用户</th><th>过期时间</th><th>操作</th></tr>';
    foreach ($cardsRows as $row) {
        $action = '-';
        if (app_export_batch_file_exists($row['batch_no']) || $row['status'] === 'unused') {
            $action = '<div class="actions">' . ($row['status'] === 'unused' ? '<form method="post" action="/admin/cards/revoke"><input type="hidden" name="csrf_token" value="' . app_h(app_issue_csrf_token('admin_cards')) . '"><input type="hidden" name="card_id" value="' . app_h($row['id']) . '"><button class="inline warn" type="submit">吊销</button></form>' : '') . '</div>';
        }
        $statusLabel = $row['status'] === 'unused' ? '未使用' : ($row['status'] === 'used' ? '已绑定' : ($row['status'] === 'revoked' ? '已吊销' : ($row['status'] === 'expired' ? '已过期' : $row['status'])));
        $body .= '<tr><td>' . app_h($row['id']) . '</td><td>' . app_h($row['batch_no']) . '</td><td class="mono">' . app_h(app_mask_card($row['card_prefix'], $row['card_suffix'])) . '</td><td>' . app_h($statusLabel) . '</td><td>' . app_h($row['user_email']) . '</td><td>' . app_h($row['expires_at']) . '</td><td>' . $action . '</td></tr>';
    }
    $body .= '</table></div></section>';
    $body .= '<section class="card"><div class="section-title"><h3>用户列表</h3></div><div class="table-wrap"><table><tr><th>ID</th><th>邮箱</th><th>名称</th><th>状态</th><th>最近登录</th><th>操作</th></tr>';
    foreach ($usersRows as $row) {
        $actions = '<div class="actions">';
        if ($row['status'] === 'active') {
            $actions .= '<form method="post" action="/admin/users/disable"><input type="hidden" name="csrf_token" value="' . app_h(app_issue_csrf_token('admin_users')) . '"><input type="hidden" name="user_id" value="' . app_h($row['id']) . '"><button class="inline warn" type="submit">禁用</button></form>';
        } else {
            $actions .= '<form method="post" action="/admin/users/enable"><input type="hidden" name="csrf_token" value="' . app_h(app_issue_csrf_token('admin_users')) . '"><input type="hidden" name="user_id" value="' . app_h($row['id']) . '"><button class="inline secondary" type="submit">恢复</button></form>';
        }
        $actions .= '</div>';
        $userStatusLabel = $row['status'] === 'active' ? '启用' : ($row['status'] === 'disabled' ? '停用' : ($row['status'] === 'locked' ? '锁定' : $row['status']));
        $body .= '<tr><td>' . app_h($row['id']) . '</td><td>' . app_h($row['email']) . '</td><td>' . app_h($row['full_name']) . '</td><td>' . app_h($userStatusLabel) . '</td><td>' . app_h($row['last_login_at']) . '</td><td>' . $actions . '</td></tr>';
    }
    $body .= '</table></div></section>';
    $body .= '<section class="card"><div class="section-title"><h3>审计日志</h3></div><div class="table-wrap"><table><tr><th>时间</th><th>操作人</th><th>动作</th><th>目标</th><th>详情</th><th>IP</th></tr>';
    foreach ($logsRows as $row) {
        $details = '';
        if (!empty($row['details_json'])) {
            $details = $row['details_json'];
        }
        $body .= '<tr><td>' . app_h($row['created_at']) . '</td><td>' . app_h($row['actor_type'] . '#' . $row['actor_id']) . '</td><td>' . app_h($row['action']) . '</td><td>' . app_h($row['target_type'] . '#' . $row['target_id']) . '</td><td class="mono small">' . app_h($details) . '</td><td>' . app_h($row['ip_address']) . '</td></tr>';
    }
    $body .= '</table></div></section>';
    app_render_page('管理后台', $body);
}

if ($path === '/authorize') {
    try {
        if (app_query('resume') === '1') {
            $params = app_oidc_pending_authorize();
            if (!$params) {
                throw new RuntimeException('缺少待处理的授权请求。');
            }
        } else {
            $params = [
                'client_id' => app_query('client_id'),
                'response_type' => app_query('response_type'),
                'redirect_uri' => app_query('redirect_uri'),
                'scope' => app_query('scope'),
                'state' => app_query('state'),
                'nonce' => app_query('nonce'),
                'code_challenge' => app_query('code_challenge'),
                'code_challenge_method' => app_query('code_challenge_method'),
                'login_hint' => app_query('login_hint'),
            ];
            app_oidc_validate_authorize_request($params);
            $params['allowed_domains'] = app_client_domains($params['client_id']);
            app_oidc_store_pending_authorize($params);
        }
    } catch (Exception $e) {
        app_audit('system', null, 'oidc_authorize_failed', 'client', (string) app_query('client_id'), ['error' => $e->getMessage()]);
        app_render_page('授权错误', '<section class="hero"><h1>授权请求被拒绝</h1><p>' . app_h($e->getMessage()) . '</p></section>', ['status' => 400]);
    }

    $user = app_current_user();
    if (!$user) {
        $_SESSION['post_login_redirect'] = '/authorize?resume=1';
        app_redirect('/sso');
    }

    app_close_session();

    $code = app_oidc_issue_code($user, $params);
    app_oidc_clear_pending_authorize();
    $separator = strpos($params['redirect_uri'], '?') === false ? '?' : '&';
    $target = $params['redirect_uri'] . $separator . 'code=' . rawurlencode($code) . '&state=' . rawurlencode($params['state']);
    $body = '<section class="hero"><span class="pill">跳转桥接页</span><h1>正在返回 OpenAI</h1><p>登录已确认，系统不会展示敏感协议参数。请稍候，浏览器将自动返回 OpenAI 完成登录。</p></section><section class="split"><div class="card"><div class="section-title"><h3>当前登录信息</h3></div><div class="list"><div class="row">当前用户：<span class="mono">' . app_h($user['email']) . '</span></div><div class="row">状态：正在回到 OpenAI</div></div><div class="actions" style="margin-top:18px"><a class="button-link inline" href="' . app_h($target) . '">立即继续</a></div></div><div class="card"><div class="section-title"><h3>后台兑换过程</h3></div><div class="steps"><div class="step"><div>浏览器把授权结果带回 OpenAI。</div></div><div class="step"><div>OpenAI 在后台调用 <code>/token</code> 完成兑换。</div></div><div class="step"><div>本系统返回令牌后，OpenAI 完成工作区登录。</div></div></div></div></section><script>setTimeout(function(){window.location=' . json_encode($target) . ';}, 1200);</script>';
    app_render_page('正在返回 OpenAI', $body);
}

app_render_page('页面不存在', '<section class="hero"><h1>页面不存在</h1><p>你访问的路径不存在。</p></section>', ['status' => 404]);
