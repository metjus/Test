<?php
// Odoslanie nezáväzného dopytu z webu e-mailom na info@gridflow.sk.
// Volá ho formulár na domovskej stránke aj na stránke Kontakt (POST, JSON).
// Vyžaduje hosting s PHP a funkčnou funkciou mail(). Na Cloudflare sa nenahráva (.assetsignore).

declare(strict_types=1);

const MAIL_TO = 'info@gridflow.sk';
// Odosielateľ musí byť na doméne hostingu, inak môžu e-maily skončiť v spame.
const MAIL_FROM = 'web@gridflow.sk';
const MAX_BODY = 20000;   // bajtov
const COOLDOWN = 15;      // sekúnd medzi dopytmi z jednej IP adresy

date_default_timezone_set('Europe/Bratislava');
header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

function reply(int $code, array $data): void
{
    http_response_code($code);
    echo json_encode($data, JSON_UNESCAPED_UNICODE);
    exit;
}

// Text bez riadkov a riadiacich znakov (ochrana hlavičiek e-mailu).
function line($value, int $max = 200): string
{
    $s = is_string($value) ? $value : '';
    $s = preg_replace('/[\x00-\x1F\x7F]+/u', ' ', $s) ?? '';
    return mb_substr(trim($s), 0, $max);
}

// Viacriadkový text (poznámka).
function block($value, int $max = 2000): string
{
    $s = is_string($value) ? $value : '';
    $s = preg_replace('/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]+/u', '', $s) ?? '';
    return mb_substr(trim($s), 0, $max);
}

function items($value): array
{
    if (!is_array($value)) return [];
    $out = [];
    foreach (array_slice($value, 0, 20) as $v) {
        $v = line($v, 120);
        if ($v !== '') $out[] = $v;
    }
    return $out;
}

if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') {
    header('Allow: POST');
    reply(405, ['ok' => false, 'error' => 'method']);
}

// Len z vlastného webu.
$origin = $_SERVER['HTTP_ORIGIN'] ?? '';
$host = $_SERVER['HTTP_HOST'] ?? '';
if ($origin !== '' && parse_url($origin, PHP_URL_HOST) !== preg_replace('/:\d+$/', '', $host)) {
    reply(403, ['ok' => false, 'error' => 'origin']);
}

$raw = file_get_contents('php://input', false, null, 0, MAX_BODY + 1);
if ($raw === false || strlen($raw) > MAX_BODY) {
    reply(413, ['ok' => false, 'error' => 'size']);
}
$data = json_decode($raw, true);
if (!is_array($data)) {
    $data = $_POST; // záloha pre bežný formulár
}

// Robot vyplnil skryté pole: tvárime sa, že sa odoslalo.
if (line($data['website'] ?? '') !== '') {
    reply(200, ['ok' => true]);
}

$name = line($data['name'] ?? '', 100);
$phone = line($data['phone'] ?? '', 40);
$email = line($data['email'] ?? '', 150);
$phoneOk = preg_match('/^\+?[\d\s\-()\/]+$/', $phone) === 1 && strlen(preg_replace('/\D/', '', $phone)) >= 9;
$emailOk = $email !== '' && filter_var($email, FILTER_VALIDATE_EMAIL) !== false;

if (mb_strlen($name) < 2 || (!$phoneOk && !$emailOk)) {
    reply(422, ['ok' => false, 'error' => 'invalid']);
}

// Jednoduchá ochrana proti opakovanému odosielaniu.
$ip = $_SERVER['REMOTE_ADDR'] ?? 'unknown';
$lock = sys_get_temp_dir() . '/gridflow-dopyt-' . hash('sha256', $ip);
if (is_file($lock) && time() - (int) @filemtime($lock) < COOLDOWN) {
    reply(429, ['ok' => false, 'error' => 'rate']);
}
@touch($lock);

$services = items($data['services'] ?? []);
$purposes = items($data['purposes'] ?? []);
$town = line($data['town'] ?? '', 100);
$method = line($data['contactMethod'] ?? '', 60);
$time = line($data['contactTime'] ?? '', 60);
$note = block($data['note'] ?? '');
$page = line($data['page'] ?? '', 100);

$subject = 'Nový dopyt: ' . ($services ? implode(', ', $services) : 'poradiť') . ($town !== '' ? " ($town)" : '');

$rows = [
    'Meno' => $name,
    'Telefón' => $phoneOk ? $phone : '—',
    'E-mail' => $emailOk ? $email : '—',
    'Čo chce spraviť' => $services ? implode(', ', $services) : '—',
    'Čoho sa to týka' => $purposes ? implode(', ', $purposes) : '—',
    'Obec alebo mesto' => $town !== '' ? $town : '—',
    'Ako sa ozvať' => $method !== '' ? $method : '—',
    'Kedy sa ozvať' => $time !== '' ? $time : '—',
];
$body = "Nový nezáväzný dopyt z webu GridFlow\n\n";
foreach ($rows as $label => $value) {
    $body .= $label . ':' . str_repeat(' ', max(1, 19 - mb_strlen($label))) . $value . "\n";
}
$body .= "\nPoznámka:\n" . ($note !== '' ? $note : '—') . "\n\n";
$body .= '---' . "\nOdoslané zo stránky " . ($page !== '' ? $page : '/') . ' dňa ' . date('j. n. Y H:i') . "\n";

$headers = [
    'From: =?UTF-8?B?' . base64_encode('GridFlow web') . '?= <' . MAIL_FROM . '>',
    'MIME-Version: 1.0',
    'Content-Type: text/plain; charset=UTF-8',
    'Content-Transfer-Encoding: 8bit',
];
if ($emailOk) {
    $headers[] = 'Reply-To: ' . $email;
}

$sent = mail(
    MAIL_TO,
    '=?UTF-8?B?' . base64_encode($subject) . '?=',
    $body,
    implode("\r\n", $headers),
    '-f' . MAIL_FROM
);

if (!$sent) {
    // niektoré hostingy nepovoľujú parameter -f
    $sent = mail(MAIL_TO, '=?UTF-8?B?' . base64_encode($subject) . '?=', $body, implode("\r\n", $headers));
}
if (!$sent) {
    @unlink($lock);
    reply(500, ['ok' => false, 'error' => 'mail']);
}

reply(200, ['ok' => true]);
