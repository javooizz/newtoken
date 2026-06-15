<?php

if (PHP_SAPI !== 'cli') {
    exit("CLI only\n");
}

require_once __DIR__ . '/../app/bootstrap.php';

$privatePath = app_config('jwt_private_key_path');
$publicPath = app_config('jwt_public_key_path');
app_oidc_generate_keys($privatePath, $publicPath);

echo "Generated keys:\n{$privatePath}\n{$publicPath}\n";
