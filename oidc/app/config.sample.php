<?php

return [
    'app_env' => 'production',
    'app_debug' => false,
    'app_url' => 'https://your-oidc-domain.com',
    'app_name' => 'GPT OIDC',

    // 32-byte random hex; 用于 secret 加密与 hash 派生
    'app_key' => 'replace-with-32-byte-random-hex-string',
    'app_pepper' => 'replace-with-another-32-byte-random-hex-string',

    // 发卡/查询 API（WebUI 用）
    'cards_api_key' => '',
    // 母号管理 API（高权限，独立 key）
    'clients_admin_api_key' => '',
    // 母号管理 API 可选 IP 白名单（空数组=不限制）
    'clients_admin_ip_allowlist' => [],
    // 是否允许经 API 解密回显 client_secret（默认禁用）
    'clients_secret_reveal_enabled' => false,

    'db_host' => '127.0.0.1',
    'db_port' => 3306,
    'db_name' => 'gptoidc',
    'db_user' => 'gptoidc',
    'db_pass' => 'change-me',

    'session_name' => 'GPTOIDCSESSID',

    // Sub2API 集成（可选，沿用）
    'sub2api_base_url' => '',
    'sub2api_admin_api_key' => '',
    'sub2api_proxy_id' => '',

    // OIDC：母号 client 由 oidc_clients 表管理，这里不再写死单 client
    'oidc_issuer' => 'https://your-oidc-domain.com',
    'oidc_access_token_ttl' => 600,
    'oidc_id_token_ttl' => 600,
    'oidc_auth_code_ttl' => 90,

    'jwt_private_key_path' => __DIR__ . '/../storage/keys/private.pem',
    'jwt_public_key_path' => __DIR__ . '/../storage/keys/public.pem',
];
