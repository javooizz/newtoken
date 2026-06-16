<?php

function app_generate_card_value()
{
    $raw = strtoupper(app_random_hex(12));

    return substr($raw, 0, 6) . '-' . substr($raw, 6, 6) . '-' . substr($raw, 12, 6) . '-' . substr($raw, 18, 6);
}

function app_normalize_card_value($value)
{
    $value = strtoupper(trim((string) $value));
    $value = str_replace([
        "\r",
        "\n",
        "\t",
        ' ',
        '　',
        '—',
        '–',
        '_'
    ], ['', '', '', '', '', '-', '-', '-'], $value);
    $value = preg_replace('/[^A-Z0-9-]/', '', $value);

    return $value;
}

function app_export_batch_file_path($batchNo)
{
    return dirname(__DIR__) . '/storage/exports/' . preg_replace('/[^A-Za-z0-9_-]/', '', (string) $batchNo) . '.json';
}

function app_export_batch_file_exists($batchNo)
{
    return is_file(app_export_batch_file_path($batchNo));
}

function app_create_card_batch($adminId, $count, $expiresAt, $note)
{
    $count = max(1, min(500, (int) $count));
    $batchNo = 'B' . gmdate('YmdHis') . strtoupper(substr(app_random_hex(4), 0, 6));
    $rows = [];
    $cards = [];
    $pdo = app_pdo();
    $pdo->beginTransaction();

    try {
        for ($i = 0; $i < $count; $i++) {
            $plain = app_generate_card_value();
            $cards[] = $plain;
            $rows[] = [
                'batch_no' => $batchNo,
                'card_prefix' => substr($plain, 0, 4),
                'card_suffix' => substr($plain, -4),
                'card_hash' => app_hash_secret($plain),
                'status' => 'unused',
                'expires_at' => $expiresAt ?: null,
                'note' => $note ?: null,
                'created_by_admin_id' => (int) $adminId,
                'created_at' => app_now(),
                'updated_at' => app_now(),
            ];
        }

        foreach ($rows as $row) {
            app_db_exec('INSERT INTO card_keys (batch_no, card_prefix, card_suffix, card_hash, status, expires_at, note, created_by_admin_id, created_at, updated_at) VALUES (:batch_no, :card_prefix, :card_suffix, :card_hash, :status, :expires_at, :note, :created_by_admin_id, :created_at, :updated_at)', $row);
        }

        $pdo->commit();
    } catch (Exception $e) {
        $pdo->rollBack();
        throw $e;
    }

    $path = app_export_batch_file_path($batchNo);
    if (!is_dir(dirname($path))) {
        mkdir(dirname($path), 0770, true);
    }
    if (file_put_contents($path, json_encode($cards, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE)) === false) {
        throw new RuntimeException('无法保存导出批次文件，请检查 storage/exports 目录权限。');
    }

    app_audit('admin', $adminId, 'card_batch_created', 'batch', $batchNo, ['count' => $count, 'expires_at' => $expiresAt]);

    return $batchNo;
}

function app_find_card_by_plain($plain)
{
    $plain = app_normalize_card_value($plain);

    return app_db_one('SELECT * FROM card_keys WHERE card_hash = :card_hash LIMIT 1', ['card_hash' => app_hash_secret($plain)]);
}

function app_export_batch_remove_plain_card($batchNo, $plainCard)
{
    $path = app_export_batch_file_path($batchNo);
    if (!is_file($path)) {
        return true;
    }

    $contents = file_get_contents($path);
    $cards = json_decode((string) $contents, true);
    if (!is_array($cards)) {
        return false;
    }

    $target = app_normalize_card_value($plainCard);
    $filtered = [];
    foreach ($cards as $card) {
        if (app_normalize_card_value($card) !== $target) {
            $filtered[] = $card;
        }
    }

    if (count($filtered) === count($cards)) {
        return true;
    }

    if (empty($filtered)) {
        return @unlink($path) || !is_file($path);
    }

    return file_put_contents($path, json_encode(array_values($filtered), JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE)) !== false;
}

function app_lookup_card_bound_email($plain)
{
    $card = app_find_card_by_plain($plain);
    if (!$card || empty($card['used_by_user_id'])) {
        return null;
    }

    $user = app_user_for_card($card);

    return $user && !empty($user['email']) ? (string) $user['email'] : null;
}

function app_card_is_usable(array $card)
{
    if (!in_array($card['status'], ['unused', 'used'], true)) {
        return false;
    }

    if (!empty($card['expires_at']) && strtotime($card['expires_at']) < time()) {
        return false;
    }

    return true;
}

function app_export_batch_csv($batchNo)
{
    $path = app_export_batch_file_path($batchNo);
    if (!is_file($path)) {
        return null;
    }

    $contents = file_get_contents($path);
    $cards = json_decode($contents, true);
    if (!is_array($cards) || empty($cards)) {
        return null;
    }

    @unlink($path);
    app_db_exec('UPDATE card_keys SET exported_at = :exported_at, updated_at = :updated_at WHERE batch_no = :batch_no AND exported_at IS NULL', [
        'exported_at' => app_now(),
        'updated_at' => app_now(),
        'batch_no' => $batchNo,
    ]);

    return $cards;
}

function app_mask_card($prefix, $suffix)
{
    return $prefix . '****-****-****' . $suffix;
}
