<?php

require_once __DIR__ . '/../../app/clients.php';

test('domain: lowercase + trim', function () {
    assert_eq('example.com', app_normalize_domain('  EXAMPLE.com  '));
});

test('domain: strip trailing dot', function () {
    assert_eq('example.com', app_normalize_domain('example.com.'));
});

test('domain: subdomain preserved + lowercased', function () {
    assert_eq('m1.example.com', app_normalize_domain('M1.Example.COM'));
});

test('domain: empty rejected', function () {
    assert_throws(function () { app_normalize_domain('   '); });
});

test('domain: spaces inside rejected', function () {
    assert_throws(function () { app_normalize_domain('bad domain.com'); });
});
