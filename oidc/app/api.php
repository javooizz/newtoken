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
    $db = app_db();
    app_json(['ok'=>true,'unused_cards'=>(int)$db->query("SELECT COUNT(*) FROM card_keys WHERE status='unused'")->fetchColumn(),
              'active_users'=>(int)$db->query("SELECT COUNT(*) FROM users WHERE status='active'")->fetchColumn()]);
}
