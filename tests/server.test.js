const test = require('node:test');
const assert = require('node:assert');
const path = require('node:path');
const fs = require('node:fs');
const http = require('node:http');
const { createServer } = require('../src/server');
const { StorageManager } = require('../src/core/storage/StorageManager');
const { PermissionManager, SECURITY_MODES } = require('../src/core/permissions/PermissionManager');

test('Server API: Status, Providers, Permissions, Diff and Filesystem endpoints', async (t) => {
  const testDir = path.join(process.cwd(), '.test_server_' + Date.now());
  const storage = new StorageManager({ baseDir: testDir });
  const permissions = new PermissionManager(storage);
  permissions.setMode(SECURITY_MODES.AUTHORIZED);

  const app = createServer({ storage, permissions });
  const server = http.createServer(app);

  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const port = server.address().port;
  const baseUrl = `http://127.0.0.1:${port}`;

  try {
    // 1. GET /api/status
    const statusRes = await fetch(`${baseUrl}/api/status`);
    assert.strictEqual(statusRes.status, 200);
    const statusData = await statusRes.json();
    assert.strictEqual(statusData.ok, true);
    assert.strictEqual(statusData.name, 'NEXO Terminal');
    assert.strictEqual(statusData.environment, 'Termux / Android & Linux');

    // 2. GET /api/providers
    const provRes = await fetch(`${baseUrl}/api/providers`);
    assert.strictEqual(provRes.status, 200);
    const provData = await provRes.json();
    assert.ok(provData.providers.length >= 3);

    // 3. POST /api/diff/compare
    const diffRes = await fetch(`${baseUrl}/api/diff/compare`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        originalContent: 'line1\nline2\n',
        proposedContent: 'line1\nline2_updated\nline3\n'
      })
    });
    assert.strictEqual(diffRes.status, 200);
    const diffData = await diffRes.json();
    assert.strictEqual(diffData.ok, true);
    assert.strictEqual(diffData.diff.hasChanges, true);
    assert.strictEqual(diffData.diff.additions, 2);
    assert.strictEqual(diffData.diff.deletions, 1);

    // 4. POST /api/terminal/exec
    const termRes = await fetch(`${baseUrl}/api/terminal/exec`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ command: 'echo "NEXO_API_OK"' })
    });
    assert.strictEqual(termRes.status, 200);
    const termData = await termRes.json();
    assert.strictEqual(termData.ok, true);
    assert.ok(termData.result.stdout.includes('NEXO_API_OK'));

    // 5. GET /api/fs/tree
    const treeRes = await fetch(`${baseUrl}/api/fs/tree`);
    assert.strictEqual(treeRes.status, 200);
    const treeData = await treeRes.json();
    assert.strictEqual(treeData.ok, true);
    assert.ok(Array.isArray(treeData.entries));

    // 6. POST /api/chat/stream
    const streamRes = await fetch(`${baseUrl}/api/chat/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ instruction: 'Hola NEXO' })
    });
    assert.strictEqual(streamRes.status, 200);
    const streamText = await streamRes.text();
    assert.ok(streamText.includes('agent_thought') || streamText.includes('content_chunk'));
    assert.ok(streamText.includes('stream_end'));

  } finally {
    server.close();
    fs.rmSync(testDir, { recursive: true, force: true });
  }
});
