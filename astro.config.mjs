import { defineConfig } from 'astro/config';
import { readdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const NBSP = ' ';

// Jednopísmenové predložky a spojky (k, s, v, z, o, u, a, i) a „§“ sa nesmú zalomiť osamote.
// Spracúva sa len text medzi značkami (nie skripty, štýly ani atribúty).
function tieText(text) {
  let out = text;
  for (let i = 0; i < 2; i++) {
    out = out.replace(/(^|[\s(])([ksvzouaiKSVZOUAI])[ \t\n]+(?=[^\s<])/g, `$1$2${NBSP}`);
  }
  out = out.replace(/§[ \t\n]+(?=\d)/g, `§${NBSP}`);
  // Telefónne číslo sa nesmie zalomiť (0910 635 595)
  return out.replace(/(\d{4}) (\d{3}) (\d{3})/g, `$1${NBSP}$2${NBSP}$3`);
}

function tieHtml(html) {
  return html
    .split(/(<script[\s\S]*?<\/script>|<style[\s\S]*?<\/style>|<textarea[\s\S]*?<\/textarea>|<[^>]+>)/g)
    .map((part) => (part.startsWith('<') ? part : tieText(part)))
    .join('');
}

function walk(dir, files = []) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const p = join(dir, entry.name);
    if (entry.isDirectory()) walk(p, files);
    else if (entry.name.endsWith('.html')) files.push(p);
  }
  return files;
}

const nonBreakingSpaces = {
  name: 'nonbreaking-spaces',
  hooks: {
    'astro:build:done': ({ dir }) => {
      for (const file of walk(fileURLToPath(dir))) {
        writeFileSync(file, tieHtml(readFileSync(file, 'utf8')));
      }
    },
  },
};

// Adresu domény nastaví klient (premenná SITE_URL pri builde). Dovtedy ide o zástupnú hodnotu.
const site = process.env.SITE_URL || 'https://www.gridflow.example';

export default defineConfig({
  site,
  trailingSlash: 'always',
  integrations: [nonBreakingSpaces],
  build: { inlineStylesheets: 'never' },
  vite: {
    build: {
      assetsInlineLimit: 0,
      // Predvolený minifikátor (lightningcss) prepíše `animation` + `animation-timeline` na skrátený zápis,
      // ktorému staršie prehliadače nerozumejú, a scroll-driven animácie prestanú fungovať.
      cssMinify: 'esbuild',
    },
  },
});
