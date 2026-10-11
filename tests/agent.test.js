const test = require('node:test');
const assert = require('node:assert');
const path = require('node:path');
const fs = require('node:fs');
const { StorageManager } = require('../src/core/storage/StorageManager');
const { PermissionManager, SECURITY_MODES } = require('../src/core/permissions/PermissionManager');
const { BackupManager } = require('../src/core/permissions/BackupManager');
const { SafeFileSystem } = require('../src/core/fs/SafeFileSystem');
const { TerminalManager } = require('../src/core/terminal/TerminalManager');
const { GitManager } = require('../src/core/git/GitManager');
const { ToolRegistry } = require('../src/core/agent/ToolRegistry');
const { TaskManager } = require('../src/core/agent/TaskManager');
const { ProviderManager } = require('../src/core/providers/ProviderManager');
const { Agent } = require('../src/core/agent/Agent');

test('Agent: Executes autonomous planning, tools, and streams events', async () => {
  const testDir = path.join(process.cwd(), '.test_agent_' + Date.now());
  const storage = new StorageManager({ baseDir: testDir });
  const permissions = new PermissionManager(storage);
  permissions.setMode(SECURITY_MODES.AUTHORIZED);
  const backups = new BackupManager(storage);
  const safeFs = new SafeFileSystem(permissions, backups);
  const terminal = new TerminalManager(permissions, storage);
  const git = new GitManager(permissions);
  const tools = new ToolRegistry({ fs: safeFs, terminal, git, backups });
  const tasks = new TaskManager(storage);
  const providers = new ProviderManager(storage);

  const agent = new Agent({ tools, tasks, providers, permissions });

  try {
    const events = [];
    const stream = agent.runInstruction('Hola NEXO, lista los archivos del proyecto', {
      effort: 'MEDIUM'
    });

    for await (const evt of stream) {
      events.push(evt);
    }

    // Assert that key events occurred
    const taskCreated = events.find(e => e.type === 'task_created');
    assert.ok(taskCreated, 'Should emit task_created');

    const planCreated = events.find(e => e.type === 'plan_created');
    assert.ok(planCreated, 'Should emit plan_created');
    assert.ok(planCreated.steps.length > 0, 'Plan should contain steps');

    const thought = events.find(e => e.type === 'agent_thought');
    assert.ok(thought, 'Should emit agent_thought');

    const content = events.filter(e => e.type === 'content_chunk');
    assert.ok(content.length > 0, 'Should stream text chunks');

    const complete = events.find(e => e.type === 'task_complete');
    assert.ok(complete, 'Should complete task');

    // Verify task state in TaskManager
    const savedTask = tasks.getTask(taskCreated.task.id);
    assert.strictEqual(savedTask.status, 'completed');
  } finally {
    fs.rmSync(testDir, { recursive: true, force: true });
  }
});

test('Agent: Approval interruption when security mode requires approval', async () => {
  const testDir = path.join(process.cwd(), '.test_agent_approval_' + Date.now());
  const storage = new StorageManager({ baseDir: testDir });
  const permissions = new PermissionManager(storage);
  permissions.setMode(SECURITY_MODES.APPROVAL); // Requires approval for writes/exec
  const backups = new BackupManager(storage);
  const safeFs = new SafeFileSystem(permissions, backups);
  const terminal = new TerminalManager(permissions, storage);
  const git = new GitManager(permissions);
  const tools = new ToolRegistry({ fs: safeFs, terminal, git, backups });
  const tasks = new TaskManager(storage);
  const providers = new ProviderManager(storage);

  const agent = new Agent({ tools, tasks, providers, permissions });

  try {
    const events = [];
    const stream = agent.runInstruction('Escribir un archivo demo.js', { effort: 'LOW' });

    for await (const evt of stream) {
      events.push(evt);
    }

    const approvalEvt = events.find(e => e.type === 'approval_needed');
    assert.ok(approvalEvt, 'Should request approval before writing in APPROVAL mode');
    assert.strictEqual(approvalEvt.tool, 'write_file');

    const pending = permissions.getPendingApprovals();
    assert.strictEqual(pending.length, 1);
  } finally {
    fs.rmSync(testDir, { recursive: true, force: true });
  }
});
