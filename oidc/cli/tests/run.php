<?php

require __DIR__ . '/_bootstrap.php';

foreach (glob(__DIR__ . '/*_test.php') as $file) {
    require $file;
}

$pass = 0;
$fail = 0;
foreach ($GLOBALS['__tests'] as $name => $fn) {
    try {
        $fn();
        echo "PASS  $name\n";
        $pass++;
    } catch (Throwable $e) {
        echo "FAIL  $name: " . $e->getMessage() . "\n";
        $fail++;
    }
}
echo "\n$pass passed, $fail failed\n";
exit($fail > 0 ? 1 : 0);
