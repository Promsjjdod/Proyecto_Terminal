const test = require('node:test');
const assert = require('node:assert');
const path = require('node:path');
const fs = require('node:fs');
const { GitManager } = require('../src/core/git/GitManager');
const { SecretScanner } = require('../src/core/git/GitHubManager');
const { PermissionManager, SECURITY_MODES } = require('../src/core/permissions/PermissionManager');
const { StorageManager } = require('../src/core/storage/StorageManager');

test('GitManager: Status, branches, and commit log', async () => {
  const testDir = path.join(process.cwd(), '.test_git_' + Date.now());
  const storage = new StorageManager({ baseDir: testDir });
  const pm = new PermissionManager(storage);
  pm.setMode(SECURITY_MODES.AUTHORIZED);
  const git = new GitManager(pm);

  try {
    const isRepo = await git.isGitRepo();
    assert.strictEqual(isRepo, true, 'Current workspace should be a git repo');

    const status = await git.getStatus();
    assert.ok(status.branch, 'Should identify current branch');

    const branches = await git.getBranches();
    assert.ok(branches.branches.length > 0, 'Should list branches');

    const logs = await git.getLog(5);
    assert.ok(Array.isArray(logs), 'Should return logs array');
    if (logs.length > 0) {
      assert.ok(logs[0].hash, 'Commit should have hash');
    }
  } finally {
    fs.rmSync(testDir, { recursive: true, force: true });
  }
});

test('SecretScanner: Detects API keys, tokens, and sensitive files', () => {
  const tempDir = path.join(process.cwd(), '.test_secrets_' + Date.now());
  fs.mkdirSync(tempDir, { recursive: true });

  const safeFile = path.join(tempDir, 'safe.js');
  fs.writeFileSync(safeFile, 'const port = 3000;\nconsole.log(port);\n');

  const secretFile = path.join(tempDir, 'secret.js');
  fs.writeFileSync(secretFile, 'const key = "sk-1234567890abcdef1234567890abcdef";\n');

  const envFile = path.join(tempDir, '.env');
  fs.writeFileSync(envFile, 'DB_PASSWORD=supersecret\n');

  try {
    // Safe file check
    const safeScan = SecretScanner.scanFile(safeFile);
    assert.strictEqual(safeScan.length, 0);

    // Secret key pattern check
    const secretScan = SecretScanner.scanFile(secretFile);
    assert.ok(secretScan.length > 0);
    assert.strictEqual(secretScan[0].type, 'secret_pattern');
    assert.strictEqual(secretScan[0].patternName, 'OpenAI API Key');

    // Sensitive filename check (.env)
    const envScan = SecretScanner.scanFile(envFile);
    assert.ok(envScan.length > 0);
    assert.strictEqual(envScan[0].type, 'sensitive_filename');
  } finally {
    fs.rmSync(tempDir, { recursive: true, force: true });
  }
});
