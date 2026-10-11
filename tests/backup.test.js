const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const { StorageManager } = require('../src/core/storage/StorageManager');
const { BackupManager } = require('../src/core/permissions/BackupManager');

test('BackupManager: Creates timestamped backup and restores via rollback', () => {
  const testDir = path.join(process.cwd(), '.test_backups_' + Date.now());
  const storage = new StorageManager({ baseDir: testDir });
  const bm = new BackupManager(storage);

  const sampleFile = path.join(testDir, 'sample.txt');
  fs.writeFileSync(sampleFile, 'Version 1 Content', 'utf-8');

  try {
    const backup = bm.createBackup(sampleFile, 'initial-backup');
    assert.ok(backup);
    assert.strictEqual(fs.existsSync(backup.backupPath), true);

    // Overwrite file
    fs.writeFileSync(sampleFile, 'Version 2 Overwritten Content', 'utf-8');
    assert.strictEqual(fs.readFileSync(sampleFile, 'utf-8'), 'Version 2 Overwritten Content');

    // Rollback to version 1
    const res = bm.rollback(backup.id);
    assert.strictEqual(res.success, true);
    assert.strictEqual(fs.readFileSync(sampleFile, 'utf-8'), 'Version 1 Content');
  } finally {
    fs.rmSync(testDir, { recursive: true, force: true });
  }
});
