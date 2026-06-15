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
