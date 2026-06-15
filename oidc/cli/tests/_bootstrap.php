<?php

// 零依赖测试脚手架：注册用例 + 断言

$GLOBALS['__tests'] = [];

function test(string $name, callable $fn): void
{
    $GLOBALS['__tests'][$name] = $fn;
}

function assert_eq($expected, $actual, string $msg = ''): void
{
    if ($expected !== $actual) {
        throw new Exception('assert_eq 失败: 期望 ' . var_export($expected, true) . '，实际 ' . var_export($actual, true) . ($msg ? " — $msg" : ''));
    }
}

function assert_true($cond, string $msg = ''): void
{
    if ($cond !== true) {
        throw new Exception('assert_true 失败' . ($msg ? ": $msg" : ''));
    }
}

function assert_throws(callable $fn, string $msg = ''): void
{
    try {
        $fn();
    } catch (Throwable $e) {
        return;
    }
    throw new Exception('assert_throws 失败: 未抛出异常' . ($msg ? " — $msg" : ''));
}
