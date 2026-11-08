// Teste pe procese Node inventate, fără browser, profil sau date eMAG.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { mkdtempSync, readFileSync, readdirSync, rmdirSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { runAcceptanceProcess } from '../../scripts/acceptance_process.mjs';

const TEST_TIMEOUT_MS = 1500;

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
  try {
    const logPath = path.join(folder, 'output.log');
    const source = 'const {spawn}=require("node:child_process"); const child=spawn(process.execPath,["-e","setInterval(()=>{},1000)"],{stdio:"ignore",windowsHide:true}); console.log(JSON.stringify([process.pid,child.pid])); setInterval(()=>{},1000);';
    assert.equal(await runAcceptanceProcess({ executable: process.execPath, args: ['-e', source], cwd: folder, env: process.env, logPath, timeoutMs: TEST_TIMEOUT_MS }), false);
    const pids = JSON.parse(readFileSync(logPath, 'utf8'));
    for (const pid of pids) assert.throws(() => process.kill(pid, 0), { code: 'ESRCH' });
  } finally { for (const name of readdirSync(folder)) rmSync(path.join(folder, name)); rmdirSync(folder); }
});
