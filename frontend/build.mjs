import { cp, mkdir, writeFile } from 'node:fs/promises';

const raw = process.env.GORENT_API_BASE;
if (!raw) throw new Error('Set GORENT_API_BASE to the deployed Render HTTPS origin.');
const url = new URL(raw);
if (url.protocol !== 'https:' || url.username || url.password || url.pathname !== '/' || url.search || url.hash) {
  throw new Error('GORENT_API_BASE must be an HTTPS origin without a path.');
}
const base = url.origin;
await mkdir('dist', { recursive: true });
await Promise.all([
  cp('index.html', 'dist/index.html'),
  cp('css', 'dist/css', { recursive: true }),
  cp('js', 'dist/js', { recursive: true }),
  cp('media', 'dist/media', { recursive: true }),
]);
await writeFile('dist/config.js', `window.GORENT_API_BASE = ${JSON.stringify(base)};\n`);
console.log(`Built GoRent frontend for ${base}`);
