const express = require('express');
const path = require('node:path');
const { getStorageManager } = require('./core/storage/StorageManager');
const { getPermissionManager } = require('./core/permissions/PermissionManager');
const { getBackupManager } = require('./core/permissions/BackupManager');
const { getSafeFileSystem } = require('./core/fs/SafeFileSystem');
const { DiffEngine } = require('./core/diff/DiffEngine');
const { getTerminalManager } = require('./core/terminal/TerminalManager');
const { getGitManager } = require('./core/git/GitManager');
const { getGitHubManager, SecretScanner } = require('./core/git/GitHubManager');
const { getProviderManager } = require('./core/providers/ProviderManager');
const { getAgent } = require('./core/agent/Agent');
const { getTaskManager } = require('./core/agent/TaskManager');

function createServer(options = {}) {
  const app = express();
  const storage = options.storage || getStorageManager();
  const permissions = options.permissions || getPermissionManager(storage);
  const backups = options.backups || getBackupManager(storage);
  const fs = options.fs || getSafeFileSystem(permissions, backups);
  const terminal = options.terminal || getTerminalManager(permissions, storage);
  const git = options.git || getGitManager(permissions);
  const github = options.github || getGitHubManager(git, permissions);
  const providers = options.providers || getProviderManager(storage);
  const tasks = options.tasks || getTaskManager(storage);
  const agent = options.agent || getAgent({ permissions, providers, tasks });

  app.use(express.json({ limit: '10mb' }));
  app.use(express.urlencoded({ extended: true }));

  // CORS for local development and Termux webviews
  app.use((req, res, next) => {
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization');
    if (req.method === 'OPTIONS') return res.sendStatus(204);
    next();
  });

  // Serve static assets
  const publicDir = options.publicDir || path.join(__dirname, '../public');
  app.use(express.static(publicDir));

  // --- API ROUTES ---

  // 1. Status
  app.get('/api/status', async (req, res) => {
    try {
      const activeProvider = providers.getActiveProvider();
      const permStatus = permissions.getStatus();
      const gitStatus = await git.getStatus().catch(() => ({ isRepo: false }));
      const activeProcesses = terminal.getActiveProcesses();

      res.json({
        ok: true,
        name: 'NEXO Terminal',
        version: '1.0.0',
        environment: 'Termux / Android & Linux',
        activeProvider: {
          id: activeProvider?.id,
          name: activeProvider?.name,
          model: activeProvider?.model,
          type: activeProvider?.type
        },
        permissions: permStatus,
        git: gitStatus,
        runningProcessesCount: activeProcesses.length,
        timestamp: new Date().toISOString()
      });
    } catch (err) {
      res.status(500).json({ ok: false, error: err.message });
    }
  });

  // 2. Providers
  app.get('/api/providers', (req, res) => {
    res.json({ ok: true, providers: providers.listProviders() });
  });

  app.post('/api/providers', (req, res) => {
    try {
      const created = providers.addProvider(req.body);
      res.status(201).json({ ok: true, provider: created });
    } catch (err) {
      res.status(400).json({ ok: false, error: err.message });
    }
  });

  app.put('/api/providers/:id', (req, res) => {
    try {
      const updated = providers.updateProvider(req.params.id, req.body);
      res.json({ ok: true, provider: updated });
    } catch (err) {
      res.status(400).json({ ok: false, error: err.message });
    }
  });

  app.delete('/api/providers/:id', (req, res) => {
    try {
      const ok = providers.deleteProvider(req.params.id);
      res.json({ ok });
    } catch (err) {
      res.status(400).json({ ok: false, error: err.message });
    }
  });

  app.post('/api/providers/:id/test', async (req, res) => {
    try {
      const result = await providers.testConnection(req.params.id);
      res.json({ ok: true, result });
    } catch (err) {
      res.status(500).json({ ok: false, error: err.message });
    }
  });

  app.post('/api/providers/:id/activate', (req, res) => {
    try {
      providers.setActiveProvider(req.params.id);
      res.json({ ok: true, activeId: req.params.id });
    } catch (err) {
      res.status(400).json({ ok: false, error: err.message });
    }
  });

  // 3. Permissions & Security
  app.get('/api/permissions', (req, res) => {
    res.json({ ok: true, status: permissions.getStatus() });
  });

  app.post('/api/permissions/mode', (req, res) => {
    try {
      const newMode = permissions.setMode(req.body.mode);
      res.json({ ok: true, mode: newMode });
    } catch (err) {
      res.status(400).json({ ok: false, error: err.message });
    }
  });

  app.post('/api/permissions/granular', (req, res) => {
    try {
      const updated = permissions.setGranular(req.body);
      res.json({ ok: true, granular: updated });
    } catch (err) {
      res.status(400).json({ ok: false, error: err.message });
    }
  });

  app.post('/api/permissions/workspace', (req, res) => {
    try {
      const root = permissions.setWorkspaceRoot(req.body.workspaceRoot);
      res.json({ ok: true, workspaceRoot: root });
    } catch (err) {
      res.status(400).json({ ok: false, error: err.message });
    }
  });

  app.get('/api/permissions/approvals', (req, res) => {
    res.json({ ok: true, approvals: permissions.getPendingApprovals() });
  });

  app.post('/api/permissions/approvals/:id/approve', async (req, res) => {
    try {
      const approval = permissions.approve(req.params.id);

      // Optionally auto-execute the approved tool action if details provided
      let executionResult = null;
      if (approval.action === 'write_file') {
        executionResult = fs.writeFile(approval.details.path, req.body.content || approval.details.content, { approved: true });
      } else if (approval.action === 'execute_command') {
        const cmdRes = terminal.execute(approval.details.command, { approved: true });
        executionResult = await cmdRes.promise;
      } else if (approval.action === 'delete_file') {
        executionResult = fs.deleteFile(approval.details.path, { approved: true });
      } else if (approval.action === 'github_publish') {
        executionResult = await github.push(approval.details.remote, approval.details.branch, { approved: true });
      }

      res.json({ ok: true, approval, executionResult });
    } catch (err) {
      res.status(400).json({ ok: false, error: err.message });
    }
  });

  app.post('/api/permissions/approvals/:id/reject', (req, res) => {
    try {
      const rejected = permissions.reject(req.params.id, req.body.reason);
      res.json({ ok: true, approval: rejected });
    } catch (err) {
      res.status(400).json({ ok: false, error: err.message });
    }
  });

  app.get('/api/permissions/audit', (req, res) => {
    const limit = parseInt(req.query.limit, 10) || 100;
    res.json({ ok: true, logs: permissions.getAuditLogs(limit) });
  });

  // 4. Filesystem
  app.get('/api/fs/tree', (req, res) => {
    try {
      const dirPath = req.query.dir || '';
      const entries = fs.listDirectory(dirPath, { showHidden: req.query.showHidden === 'true' });
      res.json({ ok: true, dir: dirPath, entries });
    } catch (err) {
      res.status(400).json({ ok: false, error: err.message });
    }
  });

  app.get('/api/fs/read', (req, res) => {
    try {
      const filePath = req.query.path;
      if (!filePath) return res.status(400).json({ ok: false, error: 'Missing path query parameter' });

      const result = fs.readFile(filePath, {
        offset: req.query.offset,
        limit: req.query.limit
      });
      res.json({ ok: true, ...result });
    } catch (err) {
      res.status(400).json({ ok: false, error: err.message });
    }
  });

  app.post('/api/fs/write', (req, res) => {
    try {
      const { path: filePath, content, approved } = req.body;
      const result = fs.writeFile(filePath, content, { approved });
      res.json({ ok: true, result });
    } catch (err) {
      res.status(400).json({ ok: false, error: err.message });
    }
  });

  app.post('/api/fs/edit', (req, res) => {
    try {
      const { path: filePath, searchText, replacementText, approved } = req.body;
      const result = fs.editFile(filePath, searchText, replacementText, { approved });
      res.json({ ok: true, result });
    } catch (err) {
      res.status(400).json({ ok: false, error: err.message });
    }
  });

  app.post('/api/fs/delete', (req, res) => {
    try {
      const { path: filePath, approved } = req.body;
      const result = fs.deleteFile(filePath, { approved });
      res.json({ ok: true, result });
    } catch (err) {
      res.status(400).json({ ok: false, error: err.message });
    }
  });

  app.post('/api/fs/mkdir', (req, res) => {
    try {
      const { path: dirPath, approved } = req.body;
      const result = fs.createDirectory(dirPath, { approved });
      res.json({ ok: true, result });
    } catch (err) {
      res.status(400).json({ ok: false, error: err.message });
    }
  });

  app.get('/api/fs/search', (req, res) => {
    try {
      const query = req.query.q;
      if (!query) return res.status(400).json({ ok: false, error: 'Query parameter q is required' });
      const results = fs.searchFiles(query, {
        dir: req.query.dir,
        extension: req.query.extension,
        isRegex: req.query.regex === 'true'
      });
      res.json({ ok: true, results });
    } catch (err) {
      res.status(400).json({ ok: false, error: err.message });
    }
  });

  app.get('/api/fs/info', (req, res) => {
    const info = fs.getFileInfo(req.query.path);
    if (!info) return res.status(404).json({ ok: false, error: 'File not found' });
    res.json({ ok: true, info });
  });

  // 5. Diff Engine
  app.post('/api/diff/compare', (req, res) => {
    const { originalContent = '', proposedContent = '', context = 3 } = req.body;
    const diff = DiffEngine.computeDiff(originalContent, proposedContent, { context });
    res.json({ ok: true, diff });
  });

  app.post('/api/diff/file', (req, res) => {
    const { path: filePath, proposedContent = '', expectedOriginalContent = null } = req.body;
    try {
      const resolved = fs.resolvePath(filePath);
      const conflict = DiffEngine.detectConflict(resolved, expectedOriginalContent);

      let originalContent = '';
      if (require('node:fs').existsSync(resolved)) {
        originalContent = require('node:fs').readFileSync(resolved, 'utf-8');
      }

      const diff = DiffEngine.computeDiff(originalContent, proposedContent);
      res.json({ ok: true, conflict, diff, filePath: resolved });
    } catch (err) {
      res.status(400).json({ ok: false, error: err.message });
    }
  });

  // 6. Backups & Rollback
  app.get('/api/backups', (req, res) => {
    const list = backups.listBackups(req.query.path);
    res.json({ ok: true, backups: list });
  });

  app.post('/api/backups/:id/rollback', (req, res) => {
    try {
      const result = backups.rollback(req.params.id);
      res.json({ ok: true, result });
    } catch (err) {
      res.status(400).json({ ok: false, error: err.message });
    }
  });

  // 7. Terminal
  app.post('/api/terminal/exec', async (req, res) => {
    try {
      const { command, approved, timeoutMs } = req.body;
      const execRes = terminal.execute(command, { approved, timeoutMs });

      if (execRes.pendingApproval) {
        return res.json({ ok: true, pendingApproval: true, approvalId: execRes.approvalId });
      }

      // If user wants async response or wait for completion
      if (req.body.async) {
        return res.json({ ok: true, processId: execRes.processId, status: 'running' });
      }

      const completed = await execRes.promise;
      res.json({ ok: true, result: completed });
    } catch (err) {
      res.status(400).json({ ok: false, error: err.message });
    }
  });

  app.get('/api/terminal/processes', (req, res) => {
    res.json({ ok: true, processes: terminal.getActiveProcesses() });
  });

  app.post('/api/terminal/kill', (req, res) => {
    const { processId, signal } = req.body;
    const result = terminal.killProcess(processId, signal);
    res.json({ ok: result.success, result });
  });

  app.get('/api/terminal/history', (req, res) => {
    res.json({ ok: true, history: terminal.getCommandHistory() });
  });

  // 8. Git & GitHub
  app.get('/api/git/status', async (req, res) => {
    try {
      const status = await git.getStatus();
      res.json({ ok: true, status });
    } catch (err) {
      res.status(400).json({ ok: false, error: err.message });
    }
  });

  app.get('/api/git/branches', async (req, res) => {
    try {
      const branches = await git.getBranches();
      res.json({ ok: true, ...branches });
    } catch (err) {
      res.status(400).json({ ok: false, error: err.message });
    }
  });

  app.post('/api/git/branches', async (req, res) => {
    try {
      const result = await git.createBranch(req.body.name);
      res.json({ ok: true, result });
    } catch (err) {
      res.status(400).json({ ok: false, error: err.message });
    }
  });

  app.post('/api/git/checkout', async (req, res) => {
    try {
      const result = await git.checkout(req.body.name);
      res.json({ ok: true, result });
    } catch (err) {
      res.status(400).json({ ok: false, error: err.message });
    }
  });

  app.get('/api/git/diff', async (req, res) => {
    try {
      const result = await git.getDiff(req.query.path, req.query.staged === 'true');
      res.json({ ok: true, ...result });
    } catch (err) {
      res.status(400).json({ ok: false, error: err.message });
    }
  });

  app.post('/api/git/stage', async (req, res) => {
    try {
      const result = await git.stage(req.body.files || ['.']);
      res.json({ ok: true, result });
    } catch (err) {
      res.status(400).json({ ok: false, error: err.message });
    }
  });

  app.post('/api/git/commit', async (req, res) => {
    try {
      const { message, checkSecrets = true } = req.body;

      if (checkSecrets) {
        const status = await git.getStatus();
        const stagedFiles = status.staged.map(s => s.path);
        const secretFindings = SecretScanner.scanFiles(stagedFiles, permissions.workspaceRoot);
        if (secretFindings.length > 0) {
          return res.status(400).json({
            ok: false,
            error: 'CRITICAL: Secret scanner detected credentials or tokens in files staged for commit!',
            secretFindings
          });
        }
      }

      const result = await git.commit(message);
      res.json({ ok: true, result });
    } catch (err) {
      res.status(400).json({ ok: false, error: err.message });
    }
  });

  app.get('/api/git/log', async (req, res) => {
    try {
      const limit = parseInt(req.query.limit, 10) || 20;
      const commits = await git.getLog(limit);
      res.json({ ok: true, commits });
    } catch (err) {
      res.status(400).json({ ok: false, error: err.message });
    }
  });

  app.get('/api/github/auth', async (req, res) => {
    const auth = await github.checkAuth();
    res.json({ ok: true, auth });
  });

  app.get('/api/github/repos', async (req, res) => {
    try {
      const repos = await github.listRepos();
      res.json({ ok: true, repos });
    } catch (err) {
      res.status(400).json({ ok: false, error: err.message });
    }
  });

  app.post('/api/github/create-repo', async (req, res) => {
    try {
      const { name, description, isPrivate } = req.body;
      const result = await github.createRepo(name, description, isPrivate);
      res.json({ ok: true, result });
    } catch (err) {
      res.status(400).json({ ok: false, error: err.message });
    }
  });

  app.get('/api/github/summary', async (req, res) => {
    try {
      const summary = await github.getPublishSummary(req.query.remote || 'origin', req.query.branch);
      res.json({ ok: true, summary });
    } catch (err) {
      res.status(400).json({ ok: false, error: err.message });
    }
  });

  app.post('/api/github/push', async (req, res) => {
    try {
      const { remote = 'origin', branch, approved, ignoreSecrets } = req.body;
      const result = await github.push(remote, branch, { approved, ignoreSecrets });
      res.json({ ok: true, result });
    } catch (err) {
      res.status(400).json({ ok: false, error: err.message });
    }
  });

  // 9. Conversations & Tasks
  app.get('/api/chat/conversations', (req, res) => {
    const list = storage.read('conversations') || [];
    res.json({ ok: true, conversations: list });
  });

  app.post('/api/chat/conversations', (req, res) => {
    const title = req.body.title || 'Nueva conversación';
    const conversation = storage.insert('conversations', {
      title,
      messages: []
    });
    res.json({ ok: true, conversation });
  });

  app.delete('/api/chat/conversations/:id', (req, res) => {
    const deleted = storage.delete('conversations', req.params.id);
    res.json({ ok: deleted });
  });

  app.get('/api/tasks', (req, res) => {
    res.json({ ok: true, tasks: tasks.listTasks() });
  });

  app.get('/api/tasks/:id', (req, res) => {
    const task = tasks.getTask(req.params.id);
    if (!task) return res.status(404).json({ ok: false, error: 'Task not found' });
    res.json({ ok: true, task });
  });

  // 10. Agent SSE Streaming Endpoint
  app.post('/api/chat/stream', async (req, res) => {
    const { instruction, effort = 'MEDIUM', conversationId, history = [], resumeTaskId, approved } = req.body;

    if (!instruction && !resumeTaskId) {
      return res.status(400).json({ ok: false, error: 'instruction or resumeTaskId is required' });
    }

    // Set headers for Server-Sent Events (SSE)
    res.setHeader('Content-Type', 'text/event-stream');
    res.setHeader('Cache-Control', 'no-cache, no-transform');
    res.setHeader('Connection', 'keep-alive');
    res.setHeader('X-Accel-Buffering', 'no');
    res.flushHeaders?.();

    const sendEvent = (event, data) => {
      res.write(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
    };

    try {
      const generator = agent.runInstruction(instruction, {
        effort,
        conversationId,
        history,
        resumeTaskId,
        approved
      });

      for await (const evt of generator) {
        sendEvent(evt.type, evt);
      }

      sendEvent('stream_end', { ok: true });
      res.end();
    } catch (err) {
      sendEvent('agent_error', { message: err.message });
      res.end();
    }
  });

  return app;
}

// Standalone start if run directly
if (require.main === module) {
  const PORT = process.env.PORT || 3000;
  const HOST = '0.0.0.0';
  const app = createServer();

  app.listen(PORT, HOST, () => {
    console.log(`\n======================================================`);
    console.log(`  NEXO TERMINAL — ADVANCED AI AGENT FOR TERMUX`);
    console.log(`  TERMINAL INTELLIGENCE`);
    console.log(`======================================================`);
    console.log(`  Server listening on: http://${HOST}:${PORT}`);
    console.log(`  Local Termux URL:    http://localhost:${PORT}`);
    console.log(`  Working Directory:   ${process.cwd()}`);
    console.log(`======================================================\n`);
  });
}

module.exports = {
  createServer
};
