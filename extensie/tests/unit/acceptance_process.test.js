// Teste pe procese Node inventate, fără browser, profil sau date eMAG.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { mkdtempSync, readFileSync, readdirSync, rmdirSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { setImmediate } from 'node:timers/promises';
import path from 'node:path';
import { runAcceptanceProcess } from '../../scripts/acceptance_process.mjs';

const TEST_TIMEOUT_MS = 1500;
// SIGKILL oprește execuția înainte ca reaper-ul POSIX să elimine PID-ul; acordăm separat timp pentru ESRCH.
const PROCESS_REAP_TIMEOUT_MS = 1500;

/** Așteaptă dispariția efectivă a PID-ului; Z/EPERM nu sunt succes și termenul nu lasă un proces viu acceptat. */
async function waitForProcessRemoval(pid) {
  const deadline = performance.now() + PROCESS_REAP_TIMEOUT_MS;
  for (;;) {
    try { process.kill(pid, 0); }
    catch (error) { if (error.code === 'ESRCH') return; throw error; }
    assert.ok(performance.now() < deadline, 'procesul probei nu a dispărut înainte de termen');
    await setImmediate(); // Cedăm planificatorului, fără o pauză fixă înaintea aserțiunii.
  }
}

test('subproces: succes, eșec și jurnal privat', async () => {
  const folder = mkdtempSync(path.join(tmpdir(), 'emag-process-test-'));
  try {
    const options = { executable: process.execPath, cwd: folder, env: process.env, logPath: path.join(folder, 'output.log'), timeoutMs: TEST_TIMEOUT_MS };
    assert.equal(await runAcceptanceProcess({ ...options, args: ['-e', 'console.log("inventat")'] }), true);
    assert.equal(readFileSync(options.logPath, 'utf8').trim(), 'inventat');
    assert.equal(await runAcceptanceProcess({ ...options, args: ['-e', 'process.exit(2)'] }), false);
    assert.equal(await runAcceptanceProcess({ ...options, executable: path.join(folder, 'inexistent'), args: [] }), false);
  } finally { for (const name of readdirSync(folder)) rmSync(path.join(folder, name)); rmdirSync(folder); }
});

test('timeout: dispar atât părintele cât și copilul său', async () => {
  const folder = mkdtempSync(path.join(tmpdir(), 'emag-process-test-'));
  let pids = [];
  try {
    const logPath = path.join(folder, 'output.log');
    const source = 'const {spawn}=require("node:child_process"); const child=spawn(process.execPath,["-e","setInterval(()=>{},1000)"],{stdio:"ignore",windowsHide:true}); console.log(JSON.stringify([process.pid,child.pid])); setInterval(()=>{},1000);';
    assert.equal(await runAcceptanceProcess({ executable: process.execPath, args: ['-e', source], cwd: folder, env: process.env, logPath, timeoutMs: TEST_TIMEOUT_MS }), false);
    pids = JSON.parse(readFileSync(logPath, 'utf8'));
    for (const pid of pids) {
      await waitForProcessRemoval(pid);
      assert.throws(() => process.kill(pid, 0), { code: 'ESRCH' });
    }
  } finally {
    // O mutație a cleanup-ului trebuie să pice fără să lase procesele sintetice ale testului active.
    for (const pid of pids) {
      try { process.kill(pid, 'SIGKILL'); }
      catch (error) { if (error.code !== 'ESRCH') throw error; }
      await waitForProcessRemoval(pid);
    }
    for (const name of readdirSync(folder)) rmSync(path.join(folder, name)); rmdirSync(folder);
  }
});
