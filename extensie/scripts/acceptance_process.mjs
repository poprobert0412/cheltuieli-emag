// Subprocesul acceptanței, cu stdout/stderr în fișierul privat și timeout pe întregul arbore.
// Primește executabil, argumente, mediu, cwd, jurnal și durată; întoarce numai succes/eșec.
// Nu citește rezultatele sau profilurile și nu oprește procese din afara grupului pornit aici.
import { spawn, spawnSync } from 'node:child_process';
import { closeSync, openSync } from 'node:fs';

// taskkill are nevoie doar să finalizeze închiderea arborelui local deja identificat prin PID.
const TERMINATION_TIMEOUT_MS = 10_000;

/** Oprește copilul și descendenții lui înainte să dispară procesul părinte. */
function stopTree(child) {
  if (process.platform === 'win32') {
    const result = spawnSync('taskkill.exe', ['/PID', String(child.pid), '/T', '/F'], { windowsHide: true, stdio: 'ignore', timeout: TERMINATION_TIMEOUT_MS });
    return !result.error && result.status === 0;
  }
  try { process.kill(-child.pid, 'SIGKILL'); return true; }
  catch (error) { return error.code === 'ESRCH'; }
}

/** Rulează cu deadline; orice timeout, eroare de pornire sau cod nenul întoarce false. */
export async function runAcceptanceProcess({ executable, args, cwd, env, logPath, timeoutMs }) {
  const fd = openSync(logPath, 'w');
  try {
    return await new Promise((resolve, reject) => {
      const child = spawn(executable, args, { cwd, env, stdio: ['ignore', fd, fd], windowsHide: true, detached: process.platform !== 'win32' });
      let timedOut = false;
      const timer = setTimeout(() => {
        timedOut = true;
        if (!stopTree(child)) reject(new Error('acceptance_process_cleanup_failed'));
      }, timeoutMs);
      child.once('error', () => { clearTimeout(timer); resolve(false); });
      child.once('close', (code) => { clearTimeout(timer); resolve(!timedOut && code === 0); });
    });
  } finally { closeSync(fd); }
}
