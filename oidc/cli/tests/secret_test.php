<?php

require_once __DIR__ . '/../../app/clients.php';

test('secret: encrypt/decrypt round-trip', function () {
    $key = 'test-app-key-1234567890';
    $plain = 'csk_abcdef0123456789';
    $enc = app_secret_encrypt($plain, $key);
    assert_true($enc !== $plain, '密文不应等于明文');
    assert_eq($plain, app_secret_decrypt($enc, $key));
});

test('secret: wrong key fails', function () {
    $enc = app_secret_encrypt('hello', 'key-A');
    assert_throws(function () use ($enc) { app_secret_decrypt($enc, 'key-B'); });
});

test('secret: tampered ciphertext fails', function () {
    $enc = app_secret_encrypt('hello', 'key-A');
    $bad = $enc . 'XX';
    assert_throws(function () use ($bad) { app_secret_decrypt($bad, 'key-A'); });
});
