<?php
// VZOR nastavení odosielania dopytov cez SMTP schránky info@gridflow.sk.
// Na hostingu: skopírujte tento súbor ako dopyt-nastavenia.php (v tom istom priečinku ako dopyt.php)
// a doplňte údaje od poskytovateľa e-mailu. Súbor s heslom nedávajte do gitu ani nikomu neposielajte.
//
// Bežné hodnoty:
//   Google Workspace (Gmail): smtp.gmail.com, port 465 alebo 587, heslo = heslo aplikácie (App Password)
//   Microsoft 365 / Outlook:  smtp.office365.com, port 587 (v správe M365 musí byť pre schránku povolené SMTP AUTH)
//   Iný poskytovateľ:         údaje z jeho návodu na nastavenie pošty v programe (Outlook, Thunderbird)

return [
    'host' => 'smtp.example.com',  // SMTP server poskytovateľa e-mailu
    'port' => 587,                 // 587 = STARTTLS, 465 = SSL
    'user' => 'info@gridflow.sk',  // prihlasovacie meno schránky
    'pass' => '',                  // heslo schránky alebo heslo aplikácie
    'from' => 'info@gridflow.sk',  // odosielateľ (zvyčajne rovnaký ako user)
];
