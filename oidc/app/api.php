<?php

/**
 * API endpoints for WebUI programmatic access.
 * Auth: Bearer <api_key> header matching config 'api_key'.
 */

function app_api_auth(): bool
{
    $key = app_config('api_key') ?: '';
    if (!$key) {
        app_json(['ok' => false, 'error' => 'API not configured'], 503);
    }

    $header = $_SERVER['HTTP_AUTHORIZATION'] ?? $_SERVER['REDIRECT_HTTP_AUTHORIZATION'] ?? '';
    $bearer = (stripos($header, 'Bearer ') === 0) ? substr($header, 7) : '';
    $xkey = $_SERVER['HTTP_X_API_KEY'] ?? '';
    $provided = trim($bearer ?: $xkey);
    if (!$provided || !hash_equals($key, $provided)) {
        app_json(['ok' => false, 'error' => 'invalid api key'], 401);
    }
    return true;
}

function app_api_cards_generate(): void
{
    app_api_auth();
    $body = json_decode(file_get_contents('php://input'), true) ?: [];
    $count = min(500, max(1, (int)($body['count'] ?? 5)));
    $days = max(1, (int)($body['expires_days'] ?? 30));
    $note = trim((string)($body['note'] ?? ''));
    $expiresAt = date('Y-m-d H:i:s', strtotime("+{$days} days"));
    try {
        $batch = app_create_card_batch(0, $count, $expiresAt, $note);
        $cards = app_export_batch_csv($batch);
        app_json(['ok'=>true,'batch_no'=>$batch,'count'=>$count,'cards'=>$cards]);
    } catch (Exception $e) {
        app_json(['ok'=>false,'error'=>$e->getMessage()], 500);
    }
}

function app_api_card_lookup(): void
{
    app_api_auth();
    $body = json_decode(file_get_contents('php://input'), true) ?: [];
    $plain = app_normalize_card_value((string)($body['card'] ?? ''));
    if (!$plain) { app_json(['error'=>'card required'], 400); return; }
    $card = app_find_card_by_plain($plain);
    if (!$card) { app_json(['ok'=>false,'found'=>false]); return; }
    $email = null;
    if ($card['used_by_user_id']) { $user = app_user_for_card($card); $email = $user['email'] ?? null; }
    app_json(['ok'=>true,'found'=>true,'status'=>$card['status'],'user_email'=>$email]);
}

function app_api_status(): void
{
    app_api_auth();
    $db = app_pdo();
    app_json(['ok'=>true,'unused_cards'=>(int)$db->query("SELECT COUNT(*) FROM card_keys WHERE status='unused'")->fetchColumn(),
              'active_users'=>(int)$db->query("SELECT COUNT(*) FROM users WHERE status='active'")->fetchColumn(),
              'allowed_email_domains'=>(array) app_config('allowed_email_domains', [])]);
}


function app_api_internal_auth(): void
{
    $key = trim((string) getenv('GPTOIDC_INTERNAL_BYPASS_KEY'));
    if ($key === '') {
        app_json(['ok' => false, 'error' => 'internal bypass not configured'], 503);
    }
    $header = $_SERVER['HTTP_AUTHORIZATION'] ?? $_SERVER['REDIRECT_HTTP_AUTHORIZATION'] ?? '';
    $bearer = (stripos($header, 'Bearer ') === 0) ? substr($header, 7) : '';
    $provided = trim($bearer ?: ($_SERVER['HTTP_X_API_KEY'] ?? ''));
    if ($provided === '' || !hash_equals($key, $provided)) {
        app_json(['ok' => false, 'error' => 'invalid internal bypass key'], 401);
    }
}

function app_api_internal_direct_authorize(): void
{
    app_api_internal_auth();
    $body = json_decode(file_get_contents('php://input'), true) ?: [];
    $authorizeUrl = trim((string) ($body['authorize_url'] ?? ''));
    $email = strtolower(trim((string) ($body['email'] ?? '')));
    $fullName = trim((string) ($body['full_name'] ?? ''));
    if ($authorizeUrl === '' || $email === '') {
        app_json(['ok' => false, 'error' => 'authorize_url and email are required'], 400);
    }
    $parsed = parse_url($authorizeUrl);
    if (!is_array($parsed)) {
        app_json(['ok' => false, 'error' => 'authorize_url is invalid'], 400);
    }
    $queryParams = [];
    parse_str((string) ($parsed['query'] ?? ''), $queryParams);
    $params = [
        'client_id' => trim((string) ($queryParams['client_id'] ?? '')),
        'response_type' => trim((string) ($queryParams['response_type'] ?? '')),
        'redirect_uri' => trim((string) ($queryParams['redirect_uri'] ?? '')),
        'scope' => trim((string) ($queryParams['scope'] ?? '')),
        'state' => trim((string) ($queryParams['state'] ?? '')),
        'nonce' => trim((string) ($queryParams['nonce'] ?? '')),
        'code_challenge' => trim((string) ($queryParams['code_challenge'] ?? '')),
        'code_challenge_method' => trim((string) ($queryParams['code_challenge_method'] ?? '')),
        'login_hint' => trim((string) ($queryParams['login_hint'] ?? $email)),
    ];
    app_oidc_validate_authorize_request($params);
    if (!app_allowed_email($email)) {
        app_json(['ok' => false, 'error' => 'email domain is not allowed'], 400);
    }
    $hint = strtolower(trim((string) ($params['login_hint'] ?? '')));
    if ($hint !== '' && filter_var($hint, FILTER_VALIDATE_EMAIL) && !hash_equals($hint, $email)) {
        app_json(['ok' => false, 'error' => 'email does not match login_hint'], 400);
    }
    $user = app_internal_provision_user($email, $fullName);
    app_touch_user_login($user['id']);
    $code = app_oidc_issue_code($user, $params);
    $separator = strpos($params['redirect_uri'], '?') === false ? '?' : '&';
    $target = $params['redirect_uri'] . $separator . 'code=' . rawurlencode($code) . '&state=' . rawurlencode($params['state']);
    app_json([
        'ok' => true,
        'email' => $user['email'],
        'user_id' => (int) $user['id'],
        'redirect_url' => $target,
        'code' => $code,
    ]);
}
