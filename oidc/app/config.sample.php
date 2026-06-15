<?php

return [
    'app_env' => 'production',
    'app_debug' => false,
    'app_url' => 'https://your-oidc-domain.com',
    'app_name' => 'GPT OIDC',

    // 32-byte random string — generate with: php -r "echo bin2hex(random_bytes(16));"
    'app_key' => 'replace-with-32-byte-random-hex-string',
    // Another 32-byte random string for admin password pepper
    'app_pepper' => 'replace-with-another-32-byte-random-hex-string',

    // API key for WebUI programmatic access (Bearer token auth)
    'api_key' => '',

    'db_host' => '127.0.0.1',
    'db_port' => 3306,
    'db_name' => 'gptoidc',
    'db_user' => 'gptoidc',
    'db_pass' => 'change-me',

    'session_name' => 'GPTOIDCSESSID',
    // Email domains allowed for SSO login (from ChatGPT Business configuration)
    'allowed_email_domains' => ['example.com'],

    // ==================== Sub2API Integration ====================
    // These keys allow the OIDC admin panel to query Sub2API for
    // account status and synchronize card keys with active accounts.
    'sub2api_base_url' => '',
    'sub2api_admin_api_key' => '',
    'sub2api_proxy_id' => '',

    // ==================== OpenAI OIDC (fill after OpenAI setup) ====================
    'oidc_issuer' => 'https://your-oidc-domain.com',
    'oidc_client_id' => 'replace-after-openai-setup',
    'oidc_client_secret' => 'replace-after-openai-setup',
    'oidc_allowed_redirect_uris' => [
        'https://chatgpt.com/',
    ],
    'oidc_access_token_ttl' => 600,
    'oidc_id_token_ttl' => 600,
    'oidc_auth_code_ttl' => 90,

    // RSA key paths for JWT signing
    'jwt_private_key_path' => __DIR__ . '/../storage/keys/private.pem',
    'jwt_public_key_path' => __DIR__ . '/../storage/keys/public.pem',
];
