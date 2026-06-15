<?php

if (PHP_SAPI !== 'cli') {
    exit("CLI only\n");
}

require_once __DIR__ . '/../app/bootstrap.php';
app_require_configured();

$username = isset($argv[1]) ? trim($argv[1]) : '';
$email = isset($argv[2]) ? trim($argv[2]) : '';
$password = isset($argv[3]) ? (string) $argv[3] : '';

if ($username === '' || $email === '' || $password === '') {
    exit("Usage: php cli/init_admin.php <username> <email> <password>\n");
}

app_create_admin($username, $email, $password, 'owner');

echo "Admin created: {$username}\n";
