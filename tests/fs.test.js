const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const { StorageManager } = require('../src/core/storage/StorageManager');
const { PermissionManager, SECURITY_MODES } = require('../src/core/permissions/PermissionManager');
const { BackupManager } = require('../src/core/permissions/BackupManager');
const { SafeFileSystem } = require('../src/core/fs/SafeFileSystem');

test('SafeFileSystem: Read, write, edit with fuzzy match, search, and delete', () => {
  const testDir = path.join(process.cwd(), '.test_sfs_' + Date.now());
  const storage = new StorageManager({ baseDir: testDir });
  const pm = new PermissionManager(storage);
  pm.setMode(SECURITY_MODES.AUTHORIZED);
  pm.setGranular({ canDeleteFiles: true });
  const bm = new BackupManager(storage);
  const sfs = new SafeFileSystem(pm, bm);

  const testFile = 'test_module.js';
  const fullPath = path.join(process.cwd(), testFile);

  try {
    // 1. Write file
    const initialContent = 'function hello() {\n  console.log("Hello NEXO");\n}\n';
    const writeRes = sfs.writeFile(testFile, initialContent);
    assert.strictEqual(writeRes.success, true);
    assert.ok(fs.existsSync(fullPath));

    // 2. Read with line limits
    const readRes = sfs.readFile(testFile, { offset: 1, limit: 2 });
    assert.strictEqual(readRes.isBinary, false);
    assert.strictEqual(readRes.returnedLines, 2);
    assert.strictEqual(readRes.hasMore, true);

    // 3. Edit file (fuzzy matching)
    const editRes = sfs.editFile(testFile, 'console.log("Hello NEXO");', 'console.log("NEXO Updated");');
    assert.strictEqual(editRes.success, true);
    const updatedContent = fs.readFileSync(fullPath, 'utf-8');
    assert.ok(updatedContent.includes('NEXO Updated'));

    // 4. Search files
    const searchRes = sfs.searchFiles('NEXO Updated');
    assert.ok(searchRes.count > 0);
    assert.ok(searchRes.matches.some(m => m.file === fullPath));

    // 5. Delete file
    const delRes = sfs.deleteFile(testFile);
    assert.strictEqual(delRes.success, true);
    assert.strictEqual(fs.existsSync(fullPath), false);
  } finally {
    if (fs.existsSync(fullPath)) fs.unlinkSync(fullPath);
    fs.rmSync(testDir, { recursive: true, force: true });
  }
});
