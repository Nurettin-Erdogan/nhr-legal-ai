// Rebuild downloadable artifacts only from the reviewed local source directories.
import { readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { zipSync } from 'fflate';

export const bundles = [
  ['jurisai-avukat.zip', 'jurisai-avukat'],
  ['uyap-dosya-cekici.zip', 'uyap-dosya-cekici'],
];

function entries(root, prefix = '') {
  const files = {};
  for (const item of readdirSync(root, { withFileTypes: true }).sort((a,b) => a.name.localeCompare(b.name))) {
    const name = prefix + item.name;
    if (item.isDirectory()) Object.assign(files, entries(join(root, item.name), name + '/'));
    else if (item.isFile()) {
      const raw = readFileSync(join(root, item.name));
      const data = /\.(js|json|css|html|md)$/.test(name) ? Buffer.from(raw.toString('utf8').replaceAll('\r\n', '\n')) : raw;
      files[name] = [data, { mtime: new Date(1980, 0, 1) }];
    }
  }
  return files;
}

for (const [archive, directory] of bundles) {
  writeFileSync(new URL('../public/' + archive, import.meta.url), zipSync(entries(fileURLToPath(new URL('../public/' + directory, import.meta.url))), { level: 9 }));
  console.log('Packaged', archive);
}
