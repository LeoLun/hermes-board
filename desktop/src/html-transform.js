// Card document transform (design §6.1). Pure: no DOM access; runs in Desktop and in node tests.
export const CARD_CSP = [
  "default-src 'none'",
  "script-src 'unsafe-inline'",
  "style-src 'unsafe-inline'",
  'img-src data: blob:',
  'font-src data:',
  'media-src data: blob:',
  "connect-src 'none'",
  "frame-src 'none'",
  "worker-src 'none'",
  "form-action 'none'",
  "base-uri 'none'",
].join('; ');

const HEAD_OPEN = /<head(?:\s[^>]*)?>/i;
const HTML_OPEN = /<html(?:\s[^>]*)?>/i;
const DOCTYPE = /^\s*<!doctype[^>]*>/i;

// `<!--`, `<script` and `</script` inside inline script text change how the HTML parser finds the
// closing tag ("script data double escaped" state). `\x3C` means `<` in JS strings, templates and
// regexes alike, but the parser no longer sees a tag.
export function escapeScript(text) {
  return String(text).replace(/<(!--|\/?script)/gi, '\\x3C$1');
}

export function escapeStyle(text) {
  return String(text).replace(/<\/(style)/gi, '<\\/$1');
}

export function serializeBoot(boot) {
  return JSON.stringify(boot)
    .replace(/</g, '\\u003c')
    .replace(/>/g, '\\u003e')
    .replace(/&/g, '\\u0026')
    .replace(/\u2028/g, '\\u2028')
    .replace(/\u2029/g, '\\u2029');
}

export function buildPrelude({ boot, runtimeJs, tokensCss }) {
  return [
    `<meta http-equiv="Content-Security-Policy" content="${CARD_CSP}">`,
    '<meta name="color-scheme" content="light dark">',
    `<style id="hb-tokens">${escapeStyle(tokensCss)}</style>`,
    `<script id="hb-runtime">window.__HB_BOOT__=${serializeBoot(boot)};${escapeScript(runtimeJs)}</script>`,
  ].join('');
}

/** Insert the prelude as the very first children of <head>, synthesizing <head> when absent. */
export function injectPrelude(html, prelude) {
  const source = String(html);
  const head = HEAD_OPEN.exec(source);
  if (head) {
    const at = head.index + head[0].length;
    return source.slice(0, at) + prelude + source.slice(at);
  }
  const root = HTML_OPEN.exec(source);
  if (root) {
    const at = root.index + root[0].length;
    return `${source.slice(0, at)}<head>${prelude}</head>${source.slice(at)}`;
  }
  const doctype = DOCTYPE.exec(source);
  if (doctype) {
    const at = doctype[0].length;
    return `${source.slice(0, at)}<head>${prelude}</head>${source.slice(at)}`;
  }
  return `<head>${prelude}</head>${source}`;
}

export function transformCardHtml(html, options) {
  return injectPrelude(html, buildPrelude(options));
}

export function toBase64Utf8(text) {
  const bytes = new TextEncoder().encode(String(text));
  let binary = '';
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
  }
  return btoa(binary);
}

export function toDataUrl(html) {
  return `data:text/html;charset=utf-8;base64,${toBase64Utf8(html)}`;
}

export function randomToken(cryptoImpl = globalThis.crypto) {
  const bytes = new Uint8Array(16);
  cryptoImpl.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
}

/** Build the data: URL for one mount of a card document. */
export function buildCardDocument(html, { token, card, size, pixel, theme, runtimeJs, tokensCss, locale = 'zh-CN' }) {
  const boot = {
    token,
    cardId: card.id,
    title: card.title,
    version: card.version,
    protocol: 1,
    theme,
    size,
    pixel,
    locale,
  };
  return toDataUrl(transformCardHtml(html, { boot, runtimeJs, tokensCss }));
}
