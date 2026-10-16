// Pornește generatorul Python al fixturilor de paritate (tests/paritate_export.py) și iese cu codul lui.
// Primește: opțional calea folderului țintă (implicit extensie/build/paritate, ignorat de git). Python-ul vine din variabila
// de mediu PYTHON; implicit .venv-ul proiectului dacă există, altfel python3 (Linux, macOS) sau python (Windows).
// Setează PYTHONHASHSEED=0, PYTHONUTF8=1 și PYTHONDONTWRITEBYTECODE=1, ca fixturile să fie aceleași la orice rulare și să nu apară .pyc în depozit.
// Exportă runGenerator pentru testul de determinism (setari.test.js). Nu interpretează fixturile: asta fac testele.
import { spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const EXTENSION_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const PROJECT_ROOT = path.resolve(EXTENSION_DIR, '..');
export const DEFAULT_TARGET_DIR = path.join(EXTENSION_DIR, 'build', 'paritate');
// Sămânța implicită a hash-urilor de text din Python: fixă, ca ordinea seturilor să nu schimbe ieșirea de la o rulare la alta.
const DEFAULT_HASH_SEED = '0';

/** Calea interpretorului Python: variabila PYTHON, apoi .venv-ul proiectului, apoi comanda sistemului. */
export function findPython(env = process.env) {
  if (env.PYTHON) return env.PYTHON;
  const venvCandidates = process.platform === 'win32'
    ? [path.join(PROJECT_ROOT, '.venv', 'Scripts', 'python.exe')]
    : [path.join(PROJECT_ROOT, '.venv', 'bin', 'python')];
  for (const candidate of venvCandidates) {
    if (existsSync(candidate)) return candidate;
  }
  return process.platform === 'win32' ? 'python' : 'python3';
}

/** Rulează generatorul în `targetDir` cu sămânța de hash dată; întoarce rezultatul spawnSync (status, error). */
export function runGenerator(targetDir = DEFAULT_TARGET_DIR, { hashSeed = DEFAULT_HASH_SEED, stdio = 'inherit', env = process.env } = {}) {
  return spawnSync(findPython(env), ['-m', 'tests.paritate_export', targetDir], {
    cwd: PROJECT_ROOT,
    stdio,
    env: { ...env, PYTHONHASHSEED: String(hashSeed), PYTHONUTF8: '1', PYTHONDONTWRITEBYTECODE: '1' },
  });
}

/** Punctul de intrare din linia de comandă: rulează generatorul în folderul dat (sau cel implicit) și iese cu codul lui. */
function main() {
  const target = process.argv[2] ? path.resolve(process.argv[2]) : DEFAULT_TARGET_DIR;
  const result = runGenerator(target);
  if (result.error) {
    console.error(`Nu am putut porni Python (${findPython()}): ${result.error.message}. Setează variabila PYTHON.`);
    process.exit(1);
  }
  process.exit(result.status ?? 1);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) main();
