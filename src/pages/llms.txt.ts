// Stručný opis webu pre jazykové modely a AI vyhľadávače (formát llmstxt.org).
// Obsahuje len fakty, ktoré sú aj na stránkach webu.
import { faq } from '../data/faq.js';

export function GET({ site }) {
  const url = (p) => new URL(p, site).href;
  const body = `# GridFlow

> GridFlow s.r.o. je slovenská elektrofirma z Ivanky pri Nitre. Robí elektroinštalácie, fotovoltiku a revízie elektrických zariadení: od projektu cez montáž po revíznu správu, po častiach alebo celé na kľúč. Pôsobí na celom Slovensku.

Web je v slovenčine. Dopyt sa dá poslať cez formulár na stránke Kontakt alebo telefonicky.

## Služby

- Elektrické prípojky
- Fotovoltika pre domy a firmy (značky SolaX a Deye)
- Elektroinštalácie
- Bleskozvody (vonkajšia ochrana pred bleskom, LPS)
- Nabíjačky pre elektromobily (EVSE, AC nabíjací bod)
- Inteligentná domácnosť a riadenie energií: riadiace jednotky HomeMaster, Home Assistant a prvky Shelly, SMLIGHT, Sonoff, WaterGate, Somfy a ďalšie
- Projektová dokumentácia pre všetky uvedené riešenia
- Revízie: odborná prehliadka a odborná skúška (OPaOS) a revízna správa, aj keď montáž robil niekto iný

## Kontakt

- Telefón: +421 910 635 595
- E-mail: info@gridflow.sk
- Sídlo: Buková ulica 1309/23, 951 12 Ivanka pri Nitre
- GridFlow s.r.o., IČO: 57813329, DIČ: 2123216007
- Oblasť pôsobenia: celé Slovensko

## Stránky

- [Domov](${url('/')}): služby, postup (projekt, montáž, revízia), inteligentná domácnosť, partneri, o nás a časté otázky
- [Kontakt a nezáväzný dopyt](${url('/kontakt/')}): telefón, e-mail, fakturačné údaje a formulár

## Časté otázky

${faq.map((f) => `- ${f.q} ${f.a}`).join('\n')}

## Optional

- [Zásady ochrany osobných údajov](${url('/zasady-ochrany-osobnych-udajov/')}): spracúvanie údajov z dopytu, web nepoužíva cookies ani analytiku
`;
  return new Response(body, { headers: { 'Content-Type': 'text/plain; charset=utf-8' } });
}
