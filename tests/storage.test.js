const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const { StorageManager } = require('../src/core/storage/StorageManager');

test('StorageManager: Initializes correctly and creates default files', (t) => {
  const testDir = path.join(process.cwd(), '.test_storage_' + Date.now());
  const storage = new StorageManager({ baseDir: testDir });

  try {
    assert.ok(fs.existsSync(testDir), 'Base directory should exist');
    assert.ok(fs.existsSync(path.join(testDir, 'data')), 'Data directory should exist');
    assert.ok(fs.existsSync(path.join(testDir, 'backups')), 'Backups directory should exist');

    const settings = storage.read('settings');
    assert.ok(settings, 'Default settings should exist');
    assert.strictEqual(settings.securityMode, 'approval');
    assert.strictEqual(settings.defaultEffort, 'MEDIUM');

    const providers = storage.read('providers');
    assert.ok(Array.isArray(providers), 'Providers should be an array');
    assert.ok(providers.some(p => p.id === 'builtin-mock'), 'Built-in mock provider should exist');
  } finally {
    fs.rmSync(testDir, { recursive: true, force: true });
  }
});

test('StorageManager: CRUD operations work atomically', (t) => {
  const testDir = path.join(process.cwd(), '.test_storage_crud_' + Date.now());
  const storage = new StorageManager({ baseDir: testDir });

  try {
    const item = storage.insert('conversations', { title: 'Test Chat 1', messages: [] });
    assert.ok(item.id, 'Item should have an ID');
    assert.strictEqual(item.title, 'Test Chat 1');

    const found = storage.find('conversations', c => c.id === item.id);
    assert.strictEqual(found.title, 'Test Chat 1');

    const updated = storage.update('conversations', item.id, { title: 'Updated Chat 1' });
    assert.strictEqual(updated.title, 'Updated Chat 1');

    const deleted = storage.delete('conversations', item.id);
    assert.strictEqual(deleted, true);

    const recheck = storage.find('conversations', c => c.id === item.id);
    assert.strictEqual(recheck, undefined);
  } finally {
    fs.rmSync(testDir, { recursive: true, force: true });
  }
});
