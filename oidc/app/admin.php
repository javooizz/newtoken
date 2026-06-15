<?php

function app_audit($actorType, $actorId, $action, $targetType = null, $targetId = null, array $details = [])
{
    app_db_exec('INSERT INTO audit_logs (actor_type, actor_id, action, target_type, target_id, details_json, ip_address, created_at) VALUES (:actor_type, :actor_id, :action, :target_type, :target_id, :details_json, :ip_address, :created_at)', [
        'actor_type' => $actorType,
        'actor_id' => $actorId,
        'action' => $action,
        'target_type' => $targetType,
        'target_id' => $targetId,
        'details_json' => $details ? json_encode($details, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE) : null,
        'ip_address' => app_ip(),
        'created_at' => app_now(),
    ]);
}

function app_create_admin($username, $email, $password, $role = 'owner')
{
    app_db_exec('INSERT INTO admins (username, email, password_hash, role, status, created_at, updated_at) VALUES (:username, :email, :password_hash, :role, :status, :created_at, :updated_at)', [
        'username' => trim($username),
        'email' => strtolower(trim($email)),
        'password_hash' => app_password_hash_value($password),
        'role' => $role,
        'status' => 'active',
        'created_at' => app_now(),
        'updated_at' => app_now(),
    ]);

    return app_find_admin_by_username($username);
}

function app_admin_exists()
{
    try {
        $row = app_db_one('SELECT COUNT(*) AS c FROM admins');
    } catch (Exception $e) {
        return false;
    }

    return !empty($row['c']);
}

function app_admin_cards($limit = 100)
{
    return app_db_all('SELECT c.*, a.username AS admin_username, u.email AS user_email FROM card_keys c LEFT JOIN admins a ON a.id = c.created_by_admin_id LEFT JOIN users u ON u.id = c.used_by_user_id ORDER BY c.id DESC LIMIT ' . (int) $limit);
}

function app_admin_find_card_by_plain($plain)
{
    $plain = app_normalize_card_value($plain);
    if ($plain === '') {
        return null;
    }

    return app_db_one('SELECT c.*, a.username AS admin_username, u.email AS user_email FROM card_keys c LEFT JOIN admins a ON a.id = c.created_by_admin_id LEFT JOIN users u ON u.id = c.used_by_user_id WHERE c.card_hash = :card_hash LIMIT 1', [
        'card_hash' => app_hash_secret($plain),
    ]);
}

function app_admin_delete_plain_cards($adminId, array $plainCards)
{
    $normalized = [];
    foreach ($plainCards as $plainCard) {
        $plainCard = app_normalize_card_value($plainCard);
        if ($plainCard !== '') {
            $normalized[$plainCard] = $plainCard;
        }
    }

    if (empty($normalized)) {
        throw new RuntimeException('请至少填写一张要删除的卡密。');
    }

    $deleted = 0;
    $missing = 0;
    $syncFailed = 0;
    foreach ($normalized as $plainCard) {
        $card = app_find_card_by_plain($plainCard);
        if (!$card) {
            $missing++;
            continue;
        }

        app_db_exec('DELETE FROM card_keys WHERE id = :id', ['id' => (int) $card['id']]);
        if (!app_export_batch_remove_plain_card($card['batch_no'], $plainCard)) {
            $syncFailed++;
        }
        $deleted++;
    }

    app_audit('admin', $adminId, 'card_deleted_by_plaintext', 'card', null, [
        'input_count' => count($normalized),
        'deleted_count' => $deleted,
        'missing_count' => $missing,
        'export_sync_failed_count' => $syncFailed,
    ]);

    return [
        'deleted_count' => $deleted,
        'missing_count' => $missing,
        'export_sync_failed_count' => $syncFailed,
    ];
}

function app_admin_issue_existing_user_card($adminId, $userEmail, $expiresAt, $note)
{
    $userEmail = strtolower(trim((string) $userEmail));
    if ($userEmail === '') {
        throw new RuntimeException('请输入已存在用户的邮箱。');
    }

    $user = app_find_user_by_email($userEmail);
    if (!$user) {
        throw new RuntimeException('没有找到这个已存在用户。');
    }

    if ($user['status'] !== 'active') {
        throw new RuntimeException('只能给启用状态的用户生成可用卡密。');
    }

    $batchNo = 'R' . gmdate('YmdHis') . strtoupper(substr(app_random_hex(4), 0, 6));
    $plainCard = null;
    for ($attempt = 0; $attempt < 5; $attempt++) {
        $plainCard = app_generate_card_value();
        try {
            app_db_exec('INSERT INTO card_keys (batch_no, card_prefix, card_suffix, card_hash, status, expires_at, used_by_user_id, used_at, note, created_by_admin_id, created_at, updated_at) VALUES (:batch_no, :card_prefix, :card_suffix, :card_hash, :status, :expires_at, :used_by_user_id, :used_at, :note, :created_by_admin_id, :created_at, :updated_at)', [
                'batch_no' => $batchNo,
                'card_prefix' => substr($plainCard, 0, 4),
                'card_suffix' => substr($plainCard, -4),
                'card_hash' => app_hash_secret($plainCard),
                'status' => 'used',
                'expires_at' => $expiresAt ?: null,
                'used_by_user_id' => (int) $user['id'],
                'used_at' => app_now(),
                'note' => trim((string) $note) !== '' ? trim((string) $note) : 'existing-user-reissue',
                'created_by_admin_id' => (int) $adminId,
                'created_at' => app_now(),
                'updated_at' => app_now(),
            ]);
            break;
        } catch (Exception $e) {
            if ($attempt === 4) {
                throw $e;
            }
        }
    }

    app_audit('admin', $adminId, 'existing_user_card_issued', 'user', (string) $user['id'], [
        'email' => $user['email'],
        'batch_no' => $batchNo,
        'expires_at' => $expiresAt,
    ]);

    return [
        'user' => $user,
        'card_key' => $plainCard,
        'batch_no' => $batchNo,
        'expires_at' => $expiresAt,
    ];
}

function app_admin_batches($limit = 100)
{
    return app_db_all('SELECT batch_no, COUNT(*) AS card_count, MIN(created_at) AS created_at, MIN(expires_at) AS expires_at, MIN(exported_at) AS exported_at, SUM(CASE WHEN status = "unused" THEN 1 ELSE 0 END) AS unused_count, SUM(CASE WHEN status = "used" THEN 1 ELSE 0 END) AS used_count, SUM(CASE WHEN status = "revoked" THEN 1 ELSE 0 END) AS revoked_count FROM card_keys GROUP BY batch_no ORDER BY MAX(id) DESC LIMIT ' . (int) $limit);
}

function app_admin_users($limit = 100)
{
    return app_db_all('SELECT * FROM users ORDER BY id DESC LIMIT ' . (int) $limit);
}

function app_admin_logs($limit = 200)
{
    return app_db_all('SELECT * FROM audit_logs ORDER BY id DESC LIMIT ' . (int) $limit);
}

function app_admin_revoke_card($adminId, $cardId)
{
    $card = app_db_one('SELECT * FROM card_keys WHERE id = :id LIMIT 1', ['id' => (int) $cardId]);
    if (!$card || $card['status'] !== 'unused') {
        throw new RuntimeException('只有未使用的卡密才能吊销。');
    }

    app_db_exec('UPDATE card_keys SET status = :status, updated_at = :updated_at WHERE id = :id', [
        'status' => 'revoked',
        'updated_at' => app_now(),
        'id' => (int) $cardId,
    ]);

    app_audit('admin', $adminId, 'card_revoked', 'card', (string) $cardId, ['batch_no' => $card['batch_no']]);
}

function app_admin_disable_user($adminId, $userId)
{
    app_db_exec('UPDATE users SET status = :status, updated_at = :updated_at WHERE id = :id', [
        'status' => 'disabled',
        'updated_at' => app_now(),
        'id' => (int) $userId,
    ]);

    app_audit('admin', $adminId, 'user_disabled', 'user', (string) $userId, []);
}

function app_admin_enable_user($adminId, $userId)
{
    app_db_exec('UPDATE users SET status = :status, updated_at = :updated_at WHERE id = :id', [
        'status' => 'active',
        'updated_at' => app_now(),
        'id' => (int) $userId,
    ]);

    app_audit('admin', $adminId, 'user_enabled', 'user', (string) $userId, []);
}

function app_admin_clients()
{
    return app_client_list();
}
