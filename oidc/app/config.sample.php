<?php

return [
    'app_env' => 'development',
    'app_debug' => true,
    'app_url' => 'https://sso.example.com',
    'app_name' => 'GPT OIDC',
    'app_key' => 'replace-with-32-byte-random-string',
    'app_pepper' => 'replace-with-another-32-byte-random-string',

    // API key for WebUI programmatic access (Bearer token auth)
    'api_key' => '',

    'db_host' => '127.0.0.1',
    'db_port' => 3306,
    'db_name' => 'gptoidc',
    'db_user' => 'gptoidc',
    'db_pass' => 'change-me',

    'session_name' => 'GPTOIDCSESSID',
    'allowed_email_domains' => ['example.com'],

    'oidc_issuer' => 'https://sso.example.com',
    'oidc_client_id' => 'replace-after-openai-setup',
    'oidc_client_secret' => 'replace-after-openai-setup',
    'oidc_allowed_redirect_uris' => [
        'https://chatgpt.com/',
    ],
    'oidc_access_token_ttl' => 600,
    'oidc_id_token_ttl' => 600,
    'oidc_auth_code_ttl' => 90,

    'jwt_private_key_path' => __DIR__ . '/../storage/keys/private.pem',
    'jwt_public_key_path' => __DIR__ . '/../storage/keys/public.pem',
];
