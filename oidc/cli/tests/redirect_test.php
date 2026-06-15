<?php

require_once __DIR__ . '/../../app/clients.php';

test('redirect: exact match allowed', function () {
    $client = ['redirect_uris' => json_encode(['https://external.auth.openai.com/sso/oidc/AAA/callback'])];
    assert_true(app_client_redirect_allowed($client, 'https://external.auth.openai.com/sso/oidc/AAA/callback'));
});

test('redirect: non-listed rejected', function () {
    $client = ['redirect_uris' => json_encode(['https://a/cb'])];
    assert_eq(false, app_client_redirect_allowed($client, 'https://evil/cb'));
});

test('redirect: empty/invalid json rejected', function () {
    assert_eq(false, app_client_redirect_allowed(['redirect_uris' => ''], 'https://a/cb'));
});
