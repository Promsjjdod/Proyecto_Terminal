const test = require('node:test');
const assert = require('node:assert');
const path = require('node:path');
const fs = require('node:fs');
const { StorageManager } = require('../src/core/storage/StorageManager');
const { ProviderManager } = require('../src/core/providers/ProviderManager');

test('ProviderManager: CRUD, key masking, and connection testing', async () => {
  const testDir = path.join(process.cwd(), '.test_providers_' + Date.now());
  const storage = new StorageManager({ baseDir: testDir });
  const pm = new ProviderManager(storage);

  try {
    // 1. List default providers
    const list = pm.listProviders();
    assert.ok(list.length >= 3);
    const mock = list.find(p => p.id === 'builtin-mock');
    assert.ok(mock);
    assert.strictEqual(mock.active, true);

    // 2. Add custom provider with secret key
    const added = pm.addProvider({
      name: 'Custom Team LLM',
      type: 'openai',
      baseUrl: 'https://llm.custom.example/v1',
      apiKey: 'sk-9876543210fedcba9876543210fedcba',
      model: 'qwen-coder-32b'
    });
    assert.strictEqual(added.name, 'Custom Team LLM');
    assert.strictEqual(added.apiKeyMasked, 'sk-9...dcba'); // Masked!

    // 3. Test mock provider connection
    const testResult = await pm.testConnection('builtin-mock');
    assert.strictEqual(testResult.success, true);
    assert.strictEqual(testResult.status, 'ready');

    // 4. Test unreachable provider (graceful failure)
    const badResult = await pm.testConnection(added.id);
    assert.strictEqual(badResult.success, false);
    assert.strictEqual(badResult.status, 'error');

    // 5. Update provider
    const updated = pm.updateProvider(added.id, { model: 'qwen-coder-72b' });
    assert.strictEqual(updated.model, 'qwen-coder-72b');

    // 6. Delete custom provider
    const deleted = pm.deleteProvider(added.id);
    assert.strictEqual(deleted, true);
    assert.strictEqual(pm.getProviderConfig(added.id), null);
  } finally {
    fs.rmSync(testDir, { recursive: true, force: true });
  }
});
