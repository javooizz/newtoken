<?php

/**
 * API endpoints for WebUI programmatic access.
 * Auth: Bearer <api_key> header matching config 'api_key'.
 */

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

function app_api_cards_generate(): void
{
    app_api_auth_cards();
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
    app_api_auth_cards();
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
    app_api_auth_cards();
    $db = app_db();
    app_json(['ok'=>true,'unused_cards'=>(int)$db->query("SELECT COUNT(*) FROM card_keys WHERE status='unused'")->fetchColumn(),
              'active_users'=>(int)$db->query("SELECT COUNT(*) FROM users WHERE status='active'")->fetchColumn()]);
}

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
