const test = require('node:test');
const assert = require('node:assert');
const path = require('node:path');
const fs = require('node:fs');
const { StorageManager } = require('../src/core/storage/StorageManager');
const { PermissionManager, SECURITY_MODES } = require('../src/core/permissions/PermissionManager');
const { TerminalManager } = require('../src/core/terminal/TerminalManager');

test('TerminalManager: Safe command execution and output capture', async () => {
  const testDir = path.join(process.cwd(), '.test_term_' + Date.now());
  const storage = new StorageManager({ baseDir: testDir });
  const pm = new PermissionManager(storage);
  pm.setMode(SECURITY_MODES.AUTHORIZED);
  const tm = new TerminalManager(pm, storage);

  try {
    const res = tm.execute('echo "NEXO_TEST_STDOUT"');
    const result = await res.promise;

    assert.strictEqual(result.status, 'completed');
    assert.strictEqual(result.exitCode, 0);
    assert.ok(result.stdout.includes('NEXO_TEST_STDOUT'));
    assert.ok(result.durationMs >= 0);
  } finally {
    fs.rmSync(testDir, { recursive: true, force: true });
  }
});

test('TerminalManager: Blocks dangerous destructive commands', () => {
  const testDir = path.join(process.cwd(), '.test_term_dang_' + Date.now());
  const storage = new StorageManager({ baseDir: testDir });
  const pm = new PermissionManager(storage);
  pm.setMode(SECURITY_MODES.AUTHORIZED);
  const tm = new TerminalManager(pm, storage);

  try {
    assert.throws(() => {
      tm.execute('rm -rf /');
    }, /Dangerous command blocked/);

    assert.throws(() => {
      tm.execute(':(){ :|:& };:');
    }, /Dangerous command blocked/);
  } finally {
    fs.rmSync(testDir, { recursive: true, force: true });
  }
});

test('TerminalManager: Kill running process with SIGTERM', async () => {
  const testDir = path.join(process.cwd(), '.test_term_kill_' + Date.now());
  const storage = new StorageManager({ baseDir: testDir });
  const pm = new PermissionManager(storage);
  pm.setMode(SECURITY_MODES.AUTHORIZED);
  const tm = new TerminalManager(pm, storage);

  try {
    const execRes = tm.execute('sleep 10');
    assert.strictEqual(execRes.record.status, 'running');

    // Kill process
    const killRes = tm.killProcess(execRes.processId, 'SIGTERM');
    assert.strictEqual(killRes.success, true);

    const completed = await execRes.promise;
    assert.strictEqual(completed.status, 'terminated');
  } finally {
    fs.rmSync(testDir, { recursive: true, force: true });
  }
});
