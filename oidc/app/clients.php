<?php

/**
 * 母号 client model：域名归一化、secret 加解密、CRUD、校验。
 */

function app_normalize_domain(string $raw): string
{
    $d = strtolower(trim($raw));
    $d = rtrim($d, '.');
    if ($d === '') {
        throw new RuntimeException('域名不能为空。');
    }
    if (function_exists('idn_to_ascii')) {
        $ascii = idn_to_ascii($d, IDNA_DEFAULT, INTL_IDNA_VARIANT_UTS46);
        if ($ascii !== false) {
            $d = $ascii;
        }
    }
    if (!preg_match('/^[a-z0-9-]+(\.[a-z0-9-]+)+$/', $d)) {
        throw new RuntimeException('域名格式非法：' . $raw);
    }
    return $d;
}

function app_secret_encrypt(string $plain, string $key): string
{
    $k = substr(hash('sha256', $key, true), 0, 32);
    $iv = random_bytes(12);
    $tag = '';
    $cipher = openssl_encrypt($plain, 'aes-256-gcm', $k, OPENSSL_RAW_DATA, $iv, $tag);
    if ($cipher === false) {
        throw new RuntimeException('secret 加密失败。');
    }
    return base64_encode($iv . $tag . $cipher);
}

function app_secret_decrypt(string $enc, string $key): string
{
    $k = substr(hash('sha256', $key, true), 0, 32);
    $raw = base64_decode($enc, true);
    if ($raw === false || strlen($raw) < 28) {
        throw new RuntimeException('secret 密文非法。');
    }
    $iv = substr($raw, 0, 12);
    $tag = substr($raw, 12, 16);
    $cipher = substr($raw, 28);
    $plain = openssl_decrypt($cipher, 'aes-256-gcm', $k, OPENSSL_RAW_DATA, $iv, $tag);
    if ($plain === false) {
        throw new RuntimeException('secret 解密失败。');
    }
    return $plain;
}
