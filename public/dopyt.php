<?php
// Odoslanie nezáväzného dopytu z webu e-mailom na info@gridflow.sk.
// Volá ho formulár na domovskej stránke aj na stránke Kontakt (POST, JSON).
// Na Cloudflare sa nenahráva (.assetsignore), vyžaduje hosting s PHP.
//
// Odosielanie:
// 1. Ak vedľa leží súbor dopyt-nastavenia.php (vzor: dopyt-nastavenia.example.php), e-mail sa pošle
//    cez SMTP schránky info@gridflow.sk u poskytovateľa e-mailu. Toto je správna cesta, keď e-mail
//    beží inde ako web: správa prejde kontrolami SPF/DKIM/DMARC a neskončí v spame.
// 2. Inak (alebo keď SMTP zlyhá) sa použije PHP mail() hostingu. Ten funguje spoľahlivo len vtedy,
//    keď záznam SPF domény povoľuje servery hostingu.

declare(strict_types=1);

const MAIL_TO = 'info@gridflow.sk';
const MAIL_FROM = 'info@gridflow.sk'; // odosielateľ pre mail(); pri SMTP sa berie z nastavení
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

function mime_header(string $s): string
{
    return '=?UTF-8?B?' . base64_encode($s) . '?=';
}

// Jednoduchý SMTP klient: šifrované spojenie (465 = SSL, 587 = STARTTLS), prihlásenie AUTH LOGIN/PLAIN.
// Heslo sa nikdy neposiela nešifrovane. Vráti prázdny reťazec pri úspechu, inak dôvod chyby.
function smtp_send(array $c, string $from, string $to, string $message): string
{
    $host = (string) ($c['host'] ?? '');
    $port = (int) ($c['port'] ?? 587);
    $user = (string) ($c['user'] ?? '');
    $pass = (string) ($c['pass'] ?? '');
    if ($host === '') return 'chýba host';

    $implicit = $port === 465 || ($c['secure'] ?? '') === 'ssl';
    $ctx = stream_context_create(['ssl' => ['peer_name' => $host, 'verify_peer' => true, 'verify_peer_name' => true]]);
    $s = @stream_socket_client(($implicit ? 'ssl://' : 'tcp://') . $host . ':' . $port, $errno, $errstr, 8, STREAM_CLIENT_CONNECT, $ctx);
    if (!$s) return "spojenie zlyhalo ($errstr)";
    stream_set_timeout($s, 8); // formulár na webe čaká najviac 15 s

    $read = static function () use ($s): array {
        $text = '';
        while (($l = fgets($s, 2048)) !== false) {
            $text .= $l;
            if (strlen($l) < 4 || $l[3] !== '-') break; // posledný riadok odpovede
        }
        return [(int) substr($text, 0, 3), trim($text)];
    };
    $cmd = static function (string $out, array $ok, string $label = '') use ($s, $read): ?string {
        fwrite($s, $out . "\r\n");
        [$code, $text] = $read();
        if (in_array($code, $ok, true)) return $text;
        throw new RuntimeException(($label !== '' ? $label : strtok($out, ' ')) . ': ' . $text);
    };

    try {
        [$code, $text] = $read();
        if ($code !== 220) throw new RuntimeException('úvod: ' . $text);
        $name = preg_replace('/[^a-z0-9.\-]/i', '', (string) ($_SERVER['SERVER_NAME'] ?? '')) ?: 'localhost';
        $caps = $cmd('EHLO ' . $name, [250]);
        if (!$implicit) {
            if (stripos($caps, 'STARTTLS') === false) throw new RuntimeException('server neponúka STARTTLS');
            $cmd('STARTTLS', [220]);
            $method = STREAM_CRYPTO_METHOD_TLSv1_2_CLIENT;
            if (defined('STREAM_CRYPTO_METHOD_TLSv1_3_CLIENT')) $method |= STREAM_CRYPTO_METHOD_TLSv1_3_CLIENT;
            if (!@stream_socket_enable_crypto($s, true, $method)) throw new RuntimeException('TLS zlyhalo');
            $caps = $cmd('EHLO ' . $name, [250]);
        }
        if ($user !== '') {
            if (preg_match('/^250[ -]AUTH[ =].*\bLOGIN\b/mi', $caps)) {
                $cmd('AUTH LOGIN', [334]);
                $cmd(base64_encode($user), [334], 'AUTH meno');
                $cmd(base64_encode($pass), [235], 'AUTH heslo');
            } else {
                $cmd('AUTH PLAIN ' . base64_encode("\0" . $user . "\0" . $pass), [235], 'AUTH PLAIN');
            }
        }
        $cmd('MAIL FROM:<' . $from . '>', [250]);
        $cmd('RCPT TO:<' . $to . '>', [250, 251]);
        $cmd('DATA', [354]);
        // Riadky začínajúce bodkou sa zdvoja (RFC 5321), koniec správy je samostatná bodka.
        $cmd(preg_replace('/^\./m', '..', $message) . "\r\n.", [250], 'odoslanie');
        try { $cmd('QUIT', [221]); } catch (RuntimeException $e) { /* správa je už prijatá */ }
        return '';
    } catch (RuntimeException $e) {
        return $e->getMessage();
    } finally {
        fclose($s);
    }
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

// Jednoduchá ochrana proti opakovanému odosielaniu (ak hosting nedovolí zápis, preskočí sa).
$lockDir = '';
foreach ([sys_get_temp_dir(), (string) ini_get('session.save_path')] as $dir) {
    if ($dir !== '' && @is_dir($dir) && @is_writable($dir)) { $lockDir = $dir; break; }
}
$lock = $lockDir !== '' ? $lockDir . '/gridflow-dopyt-' . hash('sha256', $_SERVER['REMOTE_ADDR'] ?? 'unknown') : '';
if ($lock !== '' && @is_file($lock) && time() - (int) @filemtime($lock) < COOLDOWN) {
    reply(429, ['ok' => false, 'error' => 'rate']);
}
if ($lock !== '') @touch($lock);

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
// base64 zaručí krátke riadky aj pri dlhej poznámke; SMTP vyžaduje CRLF, mail() na Linuxe LF
$b64 = base64_encode(str_replace(["\r\n", "\r"], "\n", $body));
$bodySmtp = rtrim(chunk_split($b64, 76, "\r\n"));
$bodyMail = rtrim(chunk_split($b64, 76, "\n"));

$common = [
    'MIME-Version: 1.0',
    'Content-Type: text/plain; charset=UTF-8',
    'Content-Transfer-Encoding: base64',
];
if ($emailOk) {
    $common[] = 'Reply-To: ' . $email;
}

// 1. SMTP poskytovateľa e-mailu
$settingsFile = __DIR__ . '/dopyt-nastavenia.php';
$smtp = is_file($settingsFile) ? (include $settingsFile) : null;
if (is_array($smtp) && !empty($smtp['host'])) {
    $from = (string) ($smtp['from'] ?? $smtp['user'] ?? MAIL_FROM);
    $domain = substr(strrchr($from, '@') ?: '@gridflow.sk', 1);
    $headers = array_merge([
        'Date: ' . date('r'),
        'Message-ID: <' . bin2hex(random_bytes(12)) . '@' . $domain . '>',
        'From: ' . mime_header('GridFlow web') . ' <' . $from . '>',
        'To: <' . MAIL_TO . '>',
        'Subject: ' . mime_header($subject),
    ], $common);
    $error = smtp_send($smtp, $from, MAIL_TO, implode("\r\n", $headers) . "\r\n\r\n" . $bodySmtp);
    if ($error === '') {
        reply(200, ['ok' => true]);
    }
    error_log('dopyt.php: SMTP zlyhalo, skúšam mail(): ' . $error);
}

// 2. mail() hostingu
$headers = array_merge(['From: ' . mime_header('GridFlow web') . ' <' . MAIL_FROM . '>'], $common);
$sent = mail(MAIL_TO, mime_header($subject), $bodyMail, implode("\r\n", $headers), '-f' . MAIL_FROM);
if (!$sent) {
    // niektoré hostingy nepovoľujú parameter -f
    $sent = mail(MAIL_TO, mime_header($subject), $bodyMail, implode("\r\n", $headers));
}
if (!$sent) {
    if ($lock !== '') @unlink($lock);
    error_log('dopyt.php: mail() zlyhalo');
    reply(500, ['ok' => false, 'error' => 'mail']);
}

reply(200, ['ok' => true]);
