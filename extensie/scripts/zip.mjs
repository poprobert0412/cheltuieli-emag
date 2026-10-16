// zip.mjs — face arhiva ZIP a extensiei, fără dependențe (doar node:zlib), în formatul pe care îl cere Chrome Web Store: manifest.json în rădăcina arhivei, nume UTF-8, fără foldere goale.
// Primește: un folder (de obicei dist/) și calea arhivei de scris. Dă înapoi: lista fișierelor puse în arhivă; arhiva e DETERMINISTĂ (aceleași fișiere dau aceiași octeți: ordine sortată, dată fixă), ca două construiri să se poată compara.
// Fiecare fișier se comprimă cu deflate (nivel 9) sau, dacă nu se micșorează (PNG-uri), se stochează ca atare. ZIP standard, fără ZIP64 (arhiva are mult sub 65.535 de fișiere și 4 GB); `python -m zipfile -t` o verifică.
// Ce NU face: nu decide ce fișiere intră în extensie (build.mjs pregătește folderul) și nu semnează arhiva.
import { crc32, deflateRawSync } from 'node:zlib';
import { readFileSync, readdirSync, statSync, writeFileSync } from 'node:fs';
import path from 'node:path';

// Data fixă din antetele ZIP: 1 ianuarie 1980, 00:00:00 (cea mai veche dată pe care o poate scrie formatul DOS), ca arhiva să nu depindă de ora construirii.
const DOS_TIME = 0;
const DOS_DATE = (0 << 9) | (1 << 5) | 1;
// „Version made by”: gazda UNIX (3) și versiunea 2.0 (20), ca atributele de mai jos să fie citite ca permisiuni de fișier.
const VERSION_MADE_BY = (3 << 8) | 20;
const VERSION_NEEDED = 20;
// Bitul 11 al indicatorilor generali: numele fișierelor sunt UTF-8.
const FLAG_UTF8 = 0x0800;
const METHOD_STORE = 0;
const METHOD_DEFLATE = 8;
const DEFLATE_LEVEL = 9;
// Permisiunile fișierelor în arhivă: fișier obișnuit, rw-r--r--, în cei 16 biți de sus ai atributelor externe.
const EXTERNAL_ATTRIBUTES = (0o100644 << 16) >>> 0;
const LOCAL_HEADER_SIGNATURE = 0x04034b50;
const CENTRAL_HEADER_SIGNATURE = 0x02014b50;
const END_SIGNATURE = 0x06054b50;
const MAX_ENTRIES = 0xffff;

/** Toate fișierele de sub `directory`, ca căi relative cu `/`, sortate după punctele de cod; `skip` (opțional) e o funcție care scoate căi din listă. */
export function listFiles(directory, skip = () => false) {
  const found = [];
  const walk = (current, prefix) => {
    for (const entry of readdirSync(current, { withFileTypes: true })) {
      const relative = prefix ? `${prefix}/${entry.name}` : entry.name;
      if (skip(relative)) continue;
      if (entry.isDirectory()) walk(path.join(current, entry.name), relative);
      else if (entry.isFile()) found.push(relative);
    }
  };
  walk(directory, '');
  return found.sort((a, b) => (a < b ? -1 : a > b ? 1 : 0));
}

/** Arhiva ZIP (Buffer) pentru lista `entries` = [{ name, data }] (deja sortată de apelant). */
export function createZip(entries) {
  if (entries.length > MAX_ENTRIES) throw new RangeError(`prea multe fișiere pentru un ZIP fără ZIP64: ${entries.length}`);
  const chunks = [];
  const central = [];
  let offset = 0;
  for (const { name, data } of entries) {
    const nameBytes = Buffer.from(name, 'utf8');
    const deflated = deflateRawSync(data, { level: DEFLATE_LEVEL });
    const stored = deflated.length >= data.length;
    const body = stored ? data : deflated;
    const method = stored ? METHOD_STORE : METHOD_DEFLATE;
    const checksum = crc32(data);

    const local = Buffer.alloc(30);
    local.writeUInt32LE(LOCAL_HEADER_SIGNATURE, 0);
    local.writeUInt16LE(VERSION_NEEDED, 4);
    local.writeUInt16LE(FLAG_UTF8, 6);
    local.writeUInt16LE(method, 8);
    local.writeUInt16LE(DOS_TIME, 10);
    local.writeUInt16LE(DOS_DATE, 12);
    local.writeUInt32LE(checksum, 14);
    local.writeUInt32LE(body.length, 18);
    local.writeUInt32LE(data.length, 22);
    local.writeUInt16LE(nameBytes.length, 26);
    local.writeUInt16LE(0, 28);
    chunks.push(local, nameBytes, body);

    const header = Buffer.alloc(46);
    header.writeUInt32LE(CENTRAL_HEADER_SIGNATURE, 0);
    header.writeUInt16LE(VERSION_MADE_BY, 4);
    header.writeUInt16LE(VERSION_NEEDED, 6);
    header.writeUInt16LE(FLAG_UTF8, 8);
    header.writeUInt16LE(method, 10);
    header.writeUInt16LE(DOS_TIME, 12);
    header.writeUInt16LE(DOS_DATE, 14);
    header.writeUInt32LE(checksum, 16);
    header.writeUInt32LE(body.length, 20);
    header.writeUInt32LE(data.length, 24);
    header.writeUInt16LE(nameBytes.length, 28);
    header.writeUInt16LE(0, 30); // extra
    header.writeUInt16LE(0, 32); // comentariu
    header.writeUInt16LE(0, 34); // discul de start
    header.writeUInt16LE(0, 36); // atribute interne
    header.writeUInt32LE(EXTERNAL_ATTRIBUTES, 38);
    header.writeUInt32LE(offset, 42);
    central.push(header, nameBytes);

    offset += local.length + nameBytes.length + body.length;
  }
  const centralSize = central.reduce((sum, part) => sum + part.length, 0);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(END_SIGNATURE, 0);
  end.writeUInt16LE(0, 4);
  end.writeUInt16LE(0, 6);
  end.writeUInt16LE(entries.length, 8);
  end.writeUInt16LE(entries.length, 10);
  end.writeUInt32LE(centralSize, 12);
  end.writeUInt32LE(offset, 16);
  end.writeUInt16LE(0, 20);
  return Buffer.concat([...chunks, ...central, end]);
}

/** Arhivează tot ce e în `directory` (fără să existe încă `outFile` în el) în `outFile`; întoarce lista numelor din arhivă, în ordine. */
export function zipDirectory(directory, outFile) {
  const names = listFiles(directory);
  const entries = names.map((name) => ({ name, data: readFileSync(path.join(directory, name)) }));
  writeFileSync(outFile, createZip(entries));
  if (!statSync(outFile).isFile()) throw new Error(`arhiva nu s-a scris: ${outFile}`);
  return names;
}
