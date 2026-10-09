// Pravidlá pre roboty: celý web je verejný okrem skriptu formulára.
export function GET({ site }) {
  const body = [
    'User-agent: *',
    'Allow: /',
    'Disallow: /dopyt.php',
    '',
    `Sitemap: ${new URL('/sitemap.xml', site).href}`,
    '',
  ].join('\n');
  return new Response(body, { headers: { 'Content-Type': 'text/plain; charset=utf-8' } });
}
