<?php

function app_random_hex($bytes = 16)
{
    return bin2hex(random_bytes($bytes));
}

function app_hash_secret($value)
{
    return hash_hmac('sha256', (string) $value, (string) app_config('app_key', 'fallback-key'));
}

function app_password_hash_value($password)
{
    $material = hash_hmac('sha256', (string) $password, (string) app_config('app_pepper', 'fallback-pepper'));

    return password_hash($material, PASSWORD_BCRYPT, ['cost' => 12]);
}

function app_password_verify_value($password, $hash)
{
    $material = hash_hmac('sha256', (string) $password, (string) app_config('app_pepper', 'fallback-pepper'));

    return password_verify($material, (string) $hash);
}

function app_issue_csrf_token($scope)
{
    app_start_session();
    if (!isset($_SESSION['csrf'])) {
        $_SESSION['csrf'] = [];
    }

    if (empty($_SESSION['csrf'][$scope])) {
        $_SESSION['csrf'][$scope] = app_random_hex(16);
    }

    return $_SESSION['csrf'][$scope];
}

function app_validate_csrf_token($scope, $value)
{
    app_start_session();
    return isset($_SESSION['csrf'][$scope]) && is_string($value) && hash_equals($_SESSION['csrf'][$scope], $value);
}

function app_allowed_email($email)
{
    $email = strtolower(trim((string) $email));
    if (!filter_var($email, FILTER_VALIDATE_EMAIL)) {
        return false;
    }

    $parts = explode('@', $email);
    $domain = end($parts);
    $allowed = (array) app_config('allowed_email_domains', []);

    return in_array($domain, $allowed, true);
}

function app_rate_limit_file_path($bucket)
{
    $safe = preg_replace('/[^A-Za-z0-9_.-]/', '_', (string) $bucket);
    return dirname(__DIR__) . '/storage/ratelimits/' . $safe . '.json';
}

function app_rate_limit_update($bucket, $windowSeconds, $appendNow)
{
    $path = app_rate_limit_file_path($bucket);
    if (!is_dir(dirname($path))) {
        mkdir(dirname($path), 0770, true);
    }

    $now = time();
    $handle = fopen($path, 'c+');
    if ($handle === false) {
        return [];
    }

    $events = [];
    if (flock($handle, LOCK_EX)) {
        $contents = stream_get_contents($handle);
        $originalPayload = trim((string) $contents);
        $decoded = json_decode((string) $contents, true);
        if (is_array($decoded)) {
            foreach ($decoded as $timestamp) {
                if ($timestamp > ($now - $windowSeconds)) {
                    $events[] = $timestamp;
                }
            }
        }

        if ($appendNow) {
            $events[] = $now;
        }

        $newPayload = json_encode($events);
        if ($appendNow || $newPayload !== $originalPayload) {
            ftruncate($handle, 0);
            rewind($handle);
            fwrite($handle, $newPayload);
            fflush($handle);
        }
        flock($handle, LOCK_UN);
    }

    fclose($handle);

    return $events;
}

function app_rate_limit_exceeded($bucket, $limit, $windowSeconds)
{
    $events = app_rate_limit_update($bucket, $windowSeconds, false);

    return count($events) >= $limit;
}

function app_rate_limit_record($bucket, $windowSeconds)
{
    app_rate_limit_update($bucket, $windowSeconds, true);
}

function app_rate_limit_hit($bucket, $limit, $windowSeconds)
{
    if (app_rate_limit_exceeded($bucket, $limit, $windowSeconds)) {
        return true;
    }

    app_rate_limit_record($bucket, $windowSeconds);

    return false;
}

function app_rate_limit_clear($bucket)
{
    $path = app_rate_limit_file_path($bucket);
    if (is_file($path)) {
        @unlink($path);
    }
}

function app_b64url_encode($data)
{
    return rtrim(strtr(base64_encode($data), '+/', '-_'), '=');
}

function app_b64url_decode($data)
{
    $padding = strlen($data) % 4;
    if ($padding) {
        $data .= str_repeat('=', 4 - $padding);
    }

    return base64_decode(strtr($data, '-_', '+/'));
}
