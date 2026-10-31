<?php
/**
 * Refresh button ka backend: password check karke GitHub Actions workflow shuru karta hai.
 * GitHub token yahin server par rehta hai (refresh_config.php mein), browser ko kabhi nahi dikhta.
 * Setup README mein hai.
 */
header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

function out($code, $arr) { http_response_code($code); echo json_encode($arr); exit; }

if ($_SERVER['REQUEST_METHOD'] !== 'POST') out(405, ['ok' => false, 'error' => 'Sirf POST']);

$cfgFile = __DIR__ . '/refresh_config.php';
if (!is_file($cfgFile)) out(500, ['ok' => false, 'error' => 'refresh_config.php server par nahi mili (README dekho)']);
$cfg = require $cfgFile;
foreach (['token', 'repo', 'password_hash'] as $k) {
    if (empty($cfg[$k])) out(500, ['ok' => false, 'error' => "Config mein '$k' khaali hai"]);
}

$in = json_decode(file_get_contents('php://input'), true);
if (!is_array($in)) $in = [];
$password = (string)($in['password'] ?? '');

// Rate limit: ek IP se 2 minute mein sirf ek baar (password guess aur spam rokne ke liye)
$lock = sys_get_temp_dir() . '/pbs_refresh_' . md5($_SERVER['REMOTE_ADDR'] ?? 'x');
if (is_file($lock) && time() - filemtime($lock) < 120) {
    out(429, ['ok' => false, 'error' => 'Thoda ruko, 2 minute baad dobara try karo']);
}
@touch($lock);

if (!password_verify($password, $cfg['password_hash'])) {
    sleep(1);
    out(403, ['ok' => false, 'error' => 'Password galat hai']);
}

$universe = (($in['universe'] ?? '') === 'nse') ? 'nse' : 'nse+bse';
$workflow = $cfg['workflow'] ?? 'scan.yml';
$ref      = $cfg['ref'] ?? 'main';
$url      = "https://api.github.com/repos/{$cfg['repo']}/actions/workflows/{$workflow}/dispatches";
$body     = json_encode(['ref' => $ref, 'inputs' => ['universe' => $universe]]);
$headers  = [
    'Authorization: Bearer ' . $cfg['token'],
    'Accept: application/vnd.github+json',
    'X-GitHub-Api-Version: 2022-11-28',
    'User-Agent: prebreakout-refresh',
    'Content-Type: application/json',
];

$status = 0; $resp = '';
if (function_exists('curl_init')) {
    $ch = curl_init($url);
    curl_setopt_array($ch, [CURLOPT_POST => true, CURLOPT_POSTFIELDS => $body, CURLOPT_HTTPHEADER => $headers,
        CURLOPT_RETURNTRANSFER => true, CURLOPT_TIMEOUT => 20]);
    $resp = curl_exec($ch);
    $status = (int)curl_getinfo($ch, CURLINFO_HTTP_CODE);
    $err = curl_error($ch);
    curl_close($ch);
    if ($resp === false) out(502, ['ok' => false, 'error' => 'GitHub se connect nahi hua: ' . $err . ' (host outgoing connection block kar raha ho sakta hai)']);
} else {
    $ctx = stream_context_create(['http' => ['method' => 'POST', 'header' => implode("\r\n", $headers),
        'content' => $body, 'timeout' => 20, 'ignore_errors' => true]]);
    $resp = @file_get_contents($url, false, $ctx);
    if ($resp === false) out(502, ['ok' => false, 'error' => 'GitHub se connect nahi hua (curl/allow_url_fopen band ho sakta hai)']);
    if (isset($http_response_header[0]) && preg_match('/\s(\d{3})\s/', $http_response_header[0], $m)) $status = (int)$m[1];
}

if ($status === 204) out(200, ['ok' => true, 'message' => 'Scan shuru ho gaya']);
$msg = json_decode($resp, true)['message'] ?? 'Unknown error';
out(502, ['ok' => false, 'error' => "GitHub ne mana kiya ($status): $msg"]);
