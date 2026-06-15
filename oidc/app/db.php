<?php

function app_pdo()
{
    static $pdo = null;

    if ($pdo instanceof PDO) {
        return $pdo;
    }

    $config = isset($GLOBALS['app_config']) ? $GLOBALS['app_config'] : [];
    $dsn = sprintf(
        'mysql:host=%s;port=%s;dbname=%s;charset=utf8mb4',
        isset($config['db_host']) ? $config['db_host'] : '127.0.0.1',
        isset($config['db_port']) ? $config['db_port'] : 3306,
        isset($config['db_name']) ? $config['db_name'] : ''
    );

    $pdo = new PDO($dsn, isset($config['db_user']) ? $config['db_user'] : '', isset($config['db_pass']) ? $config['db_pass'] : '', [
        PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
        PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
        PDO::ATTR_EMULATE_PREPARES => false,
    ]);

    return $pdo;
}

function app_make_pdo_from_config(array $config)
{
    $dsn = sprintf(
        'mysql:host=%s;port=%s;dbname=%s;charset=utf8mb4',
        isset($config['db_host']) ? $config['db_host'] : '127.0.0.1',
        isset($config['db_port']) ? $config['db_port'] : 3306,
        isset($config['db_name']) ? $config['db_name'] : ''
    );

    return new PDO($dsn, isset($config['db_user']) ? $config['db_user'] : '', isset($config['db_pass']) ? $config['db_pass'] : '', [
        PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
        PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
        PDO::ATTR_EMULATE_PREPARES => false,
    ]);
}

function app_make_server_pdo_from_config(array $config)
{
    $dsn = sprintf(
        'mysql:host=%s;port=%s;charset=utf8mb4',
        isset($config['db_host']) ? $config['db_host'] : '127.0.0.1',
        isset($config['db_port']) ? $config['db_port'] : 3306
    );

    return new PDO($dsn, isset($config['db_user']) ? $config['db_user'] : '', isset($config['db_pass']) ? $config['db_pass'] : '', [
        PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
        PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
        PDO::ATTR_EMULATE_PREPARES => false,
    ]);
}

function app_db_one($sql, array $params = [])
{
    $stmt = app_pdo()->prepare($sql);
    $stmt->execute($params);
    $row = $stmt->fetch();

    return $row ?: null;
}

function app_db_all($sql, array $params = [])
{
    $stmt = app_pdo()->prepare($sql);
    $stmt->execute($params);

    return $stmt->fetchAll();
}

function app_db_exec($sql, array $params = [])
{
    $stmt = app_pdo()->prepare($sql);
    $stmt->execute($params);

    return $stmt;
}

function app_import_schema(PDO $pdo, $schemaPath)
{
    if (!is_file($schemaPath)) {
        throw new RuntimeException('没有找到数据库表结构文件。');
    }

    $sql = file_get_contents($schemaPath);
    $parts = preg_split('/;\s*\n/', $sql);
    foreach ($parts as $part) {
        $statement = trim($part);
        if ($statement === '') {
            continue;
        }

        $pdo->exec($statement);
    }
}

function app_ensure_database_exists(array $config)
{
    $dbName = isset($config['db_name']) ? trim((string) $config['db_name']) : '';
    if ($dbName === '') {
        throw new RuntimeException('数据库名不能为空。');
    }

    $pdo = app_make_server_pdo_from_config($config);
    $quoted = str_replace('`', '``', $dbName);
    $pdo->exec('CREATE DATABASE IF NOT EXISTS `' . $quoted . '` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci');
}

function app_schema_ready()
{
    try {
        $row = app_db_one("SHOW TABLES LIKE 'admins'");
    } catch (Exception $e) {
        return false;
    }

    return !empty($row);
}
