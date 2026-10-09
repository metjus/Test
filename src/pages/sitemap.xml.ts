// Mapa stránok pre vyhľadávače. lastmod je dátum buildu (web sa nasadzuje len pri zmene obsahu).
const pages = [
  { path: '/', priority: '1.0' },
  { path: '/kontakt/', priority: '0.8' },
  { path: '/zasady-ochrany-osobnych-udajov/', priority: '0.3' },
];

export function GET({ site }) {
  const lastmod = new Date().toISOString().slice(0, 10);
  const urls = pages
    .map(
      (p) =>
        `  <url>\n    <loc>${new URL(p.path, site).href}</loc>\n    <lastmod>${lastmod}</lastmod>\n    <priority>${p.priority}</priority>\n  </url>`,
    )
    .join('\n');
  const body = `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${urls}\n</urlset>\n`;
  return new Response(body, { headers: { 'Content-Type': 'application/xml; charset=utf-8' } });
}
