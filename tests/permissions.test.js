const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const { StorageManager } = require('../src/core/storage/StorageManager');
const { PermissionManager, SECURITY_MODES } = require('../src/core/permissions/PermissionManager');

test('PermissionManager: Path sandbox prevents traversal outside workspace', () => {
  const testDir = path.join(process.cwd(), '.test_perm_' + Date.now());
  const storage = new StorageManager({ baseDir: testDir });
  const pm = new PermissionManager(storage);

  try {
    const root = process.cwd();
    assert.strictEqual(pm.isPathAllowed('src/server.js'), true);
    assert.strictEqual(pm.isPathAllowed(path.join(root, 'package.json')), true);

    // Block path traversal
    assert.strictEqual(pm.isPathAllowed('../outside.txt'), false);
    assert.strictEqual(pm.isPathAllowed('/etc/passwd'), false);
    assert.strictEqual(pm.isPathAllowed('../../'), false);
    assert.strictEqual(pm.isPathAllowed('src/\0nullbyte'), false);

    const outsideCheck = pm.checkPermission('read_file', { path: '/etc/shadow' });
    assert.strictEqual(outsideCheck.allowed, false);
    assert.ok(outsideCheck.reason.includes('outside the authorized workspace'));
  } finally {
    fs.rmSync(testDir, { recursive: true, force: true });
  }
});

test('PermissionManager: 3 Security Modes enforce correct behavior', () => {
  const testDir = path.join(process.cwd(), '.test_perm_modes_' + Date.now());
  const storage = new StorageManager({ baseDir: testDir });
  const pm = new PermissionManager(storage);

  try {
    const validFilePath = path.join(process.cwd(), 'valid.txt');

    // 1. Read-only mode
    pm.setMode(SECURITY_MODES.READ_ONLY);
    const readInReadOnly = pm.checkPermission('read_file', { path: validFilePath });
    assert.strictEqual(readInReadOnly.allowed, true);

    const writeInReadOnly = pm.checkPermission('write_file', { path: validFilePath });
    assert.strictEqual(writeInReadOnly.allowed, false);
    assert.strictEqual(writeInReadOnly.requiresApproval, false);
    assert.ok(writeInReadOnly.reason.includes('READ_ONLY'));

    const execInReadOnly = pm.checkPermission('execute_command', { command: 'ls' });
    assert.strictEqual(execInReadOnly.allowed, false);

    // 2. Approval mode
    pm.setMode(SECURITY_MODES.APPROVAL);
    const writeInApproval = pm.checkPermission('write_file', { path: validFilePath });
    assert.strictEqual(writeInApproval.allowed, false);
    assert.strictEqual(writeInApproval.requiresApproval, true);

    const execInApproval = pm.checkPermission('execute_command', { command: 'ls' });
    assert.strictEqual(execInApproval.allowed, false);
    assert.strictEqual(execInApproval.requiresApproval, true);

    // 3. Authorized mode
    pm.setMode(SECURITY_MODES.AUTHORIZED);
    const writeInAuth = pm.checkPermission('write_file', { path: validFilePath });
    assert.strictEqual(writeInAuth.allowed, true);
    assert.strictEqual(writeInAuth.requiresApproval, false);

    const execInAuth = pm.checkPermission('execute_command', { command: 'ls' });
    assert.strictEqual(execInAuth.allowed, true);
  } finally {
    fs.rmSync(testDir, { recursive: true, force: true });
  }
});

test('PermissionManager: Approval request, accept and reject flow', () => {
  const testDir = path.join(process.cwd(), '.test_perm_queue_' + Date.now());
  const storage = new StorageManager({ baseDir: testDir });
  const pm = new PermissionManager(storage);

  try {
    const req = pm.requestApproval('execute_command', { command: 'npm install' }, 'Need to install dependencies');
    assert.ok(req.id);
    assert.strictEqual(req.status, 'pending');

    const pending = pm.getPendingApprovals();
    assert.strictEqual(pending.length, 1);

    const approved = pm.approve(req.id);
    assert.strictEqual(approved.status, 'approved');
    assert.strictEqual(pm.getPendingApprovals().length, 0);

    const req2 = pm.requestApproval('delete_file', { path: 'old.js' }, 'Cleaning up');
    const rejected = pm.reject(req2.id, 'User refused file deletion');
    assert.strictEqual(rejected.status, 'rejected');
    assert.strictEqual(rejected.rejectionReason, 'User refused file deletion');
  } finally {
    fs.rmSync(testDir, { recursive: true, force: true });
  }
});
