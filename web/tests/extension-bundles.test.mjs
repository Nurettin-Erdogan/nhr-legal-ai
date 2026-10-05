import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { unzipSync } from 'fflate';

for (const [archive, dir] of [
  ['jurisai-avukat.zip', 'jurisai-avukat'],
  ['uyap-dosya-cekici.zip', 'uyap-dosya-cekici'],
]) {
  test(archive + ' matches reviewed source, with no stale files', () => {
    const files = unzipSync(readFileSync(new URL('../public/' + archive, import.meta.url)));
    const root = fileURLToPath(new URL('../public/' + dir, import.meta.url));
    const paths = readdirSync(root, { recursive: true, withFileTypes: true }).filter(x => x.isFile());
    assert.equal(Object.keys(files).length, paths.length);
    for (const item of paths) {
      const path = join(item.parentPath, item.name);
      const relative = path.slice(root.length + 1).replaceAll('\\', '/');
      const raw = readFileSync(path);
      const expected = /\.(js|json|css|html|md)$/.test(relative) ? Buffer.from(raw.toString('utf8').replaceAll('\r\n', '\n')) : raw;
      assert.deepEqual(Buffer.from(files[relative] ?? []), expected, relative);
    }
  });
}
