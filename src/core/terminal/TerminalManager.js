const { spawn } = require('node:child_process');
const crypto = require('node:crypto');
const { getPermissionManager } = require('../permissions/PermissionManager');
const { getStorageManager } = require('../storage/StorageManager');

// Dangerous patterns that could wipe device or lock up Termux
const DANGEROUS_PATTERNS = [
  /\brm\s+-[a-zA-Z]*rf?\s+(?:[/~*]|\/\*|\.\.)(?:\s|$)/,
  /\bmkfs(?:\.[a-z0-9]+)?\b/,
  /\bdd\s+.*of=\/dev\/[a-z0-9]+/i,
  /:[\s]*\([\s]*\)[\s]*\{[\s]*:[\s]*\|[\s]*:[\s]*&[\s]*\}[\s]*;[\s]*:/, // fork bomb
  /\bchmod\s+-[a-zA-Z]*R\s+777\s+\/(?:\s|$)/,
  />\s*\/dev\/([a-z0-9]+)\b/
];

class TerminalManager {
  constructor(permissionManager = getPermissionManager(), storageManager = getStorageManager()) {
    this.permissions = permissionManager;
    this.storage = storageManager;
    this.activeProcesses = new Map();
  }

  isDangerousCommand(cmdStr) {
    if (!cmdStr || typeof cmdStr !== 'string') return true;
    for (const pattern of DANGEROUS_PATTERNS) {
      if (pattern.test(cmdStr)) {
        return true;
      }
    }
    return false;
  }

  execute(commandStr, options = {}) {
    const perm = this.permissions.checkPermission('execute_command', { command: commandStr });

    if (this.isDangerousCommand(commandStr)) {
      throw new Error(`CRITICAL: Dangerous command blocked by safety engine: '${commandStr}'`);
    }

    if (perm.requiresApproval && !options.approved) {
      const approval = this.permissions.requestApproval(
        'execute_command',
        { command: commandStr, cwd: options.cwd || this.permissions.workspaceRoot },
        'Agent requested to execute a shell command'
      );
      return {
        pendingApproval: true,
        approvalId: approval.id,
        reason: perm.reason
      };
    }

    if (!perm.allowed && !options.approved) {
      throw new Error(perm.reason || 'Permission denied to execute command');
    }

    const processId = crypto.randomUUID();
    const cwd = options.cwd || this.permissions.workspaceRoot;
    const timeoutMs = options.timeoutMs || 120000; // 2 minutes default

    const startTime = Date.now();
    let stdoutBuffer = '';
    let stderrBuffer = '';

    // Shell execution with fallback
    const shell = process.env.SHELL || '/bin/sh';
    const child = spawn(shell, ['-c', commandStr], {
      cwd,
      env: {
        ...process.env,
        ...(options.env || {}),
        TERM: 'xterm-256color'
      }
    });

    const processRecord = {
      id: processId,
      pid: child.pid,
      command: commandStr,
      cwd,
      startTime: new Date(startTime).toISOString(),
      status: 'running',
      stdout: '',
      stderr: '',
      exitCode: null,
      durationMs: 0
    };

    this.activeProcesses.set(processId, {
      record: processRecord,
      child,
      startTime
    });

    let timeoutTimer = null;
    if (timeoutMs > 0) {
      timeoutTimer = setTimeout(() => {
        if (processRecord.status === 'running') {
          processRecord.status = 'failed';
          processRecord.stderr += `\n[NEXO] Execution timed out after ${timeoutMs / 1000}s`;
          this.killProcess(processId, 'SIGTERM');
        }
      }, timeoutMs);
    }

    // Stream handlers
    child.stdout.on('data', chunk => {
      const text = chunk.toString();
      stdoutBuffer += text;
      // Keep last 100KB in memory to prevent blowing up Termux RAM
      if (stdoutBuffer.length > 100000) {
        stdoutBuffer = stdoutBuffer.slice(-100000);
      }
      processRecord.stdout = stdoutBuffer;
      if (options.onStdout) options.onStdout(text);
    });

    child.stderr.on('data', chunk => {
      const text = chunk.toString();
      stderrBuffer += text;
      if (stderrBuffer.length > 50000) {
        stderrBuffer = stderrBuffer.slice(-50000);
      }
      processRecord.stderr = stderrBuffer;
      if (options.onStderr) options.onStderr(text);
    });

    // Return promise if waiting for finish
    const promise = new Promise((resolve) => {
      child.on('close', (exitCode, signal) => {
        if (timeoutTimer) clearTimeout(timeoutTimer);
        const endTime = Date.now();
        const durationMs = endTime - startTime;

        processRecord.durationMs = durationMs;
        processRecord.exitCode = exitCode;

        if (processRecord.status === 'running') {
          processRecord.status = exitCode === 0 ? 'completed' : 'failed';
        }
        if (signal) {
          processRecord.status = 'terminated';
          processRecord.signal = signal;
        }

        this.permissions.logAudit('execute_command', {
          command: commandStr,
          exitCode,
          durationMs,
          status: processRecord.status
        }, processRecord.status);

        // Store in history
        this.saveCommandHistory(processRecord);
        resolve({ ...processRecord });
      });

      child.on('error', (err) => {
        if (timeoutTimer) clearTimeout(timeoutTimer);
        processRecord.status = 'failed';
        processRecord.stderr += `\n[NEXO Process Error]: ${err.message}`;
        processRecord.durationMs = Date.now() - startTime;
        this.saveCommandHistory(processRecord);
        resolve({ ...processRecord, error: err.message });
      });
    });

    return {
      processId,
      pid: child.pid,
      promise,
      record: processRecord
    };
  }

  killProcess(processId, signal = 'SIGTERM') {
    const entry = this.activeProcesses.get(processId);
    if (!entry) {
      return { success: false, message: 'Process not found or already terminated' };
    }

    try {
      entry.child.kill(signal);
      entry.record.status = 'terminated';
      return { success: true, processId, signal };
    } catch (err) {
      // Escalate to SIGKILL if SIGTERM failed
      try {
        entry.child.kill('SIGKILL');
        return { success: true, processId, signal: 'SIGKILL' };
      } catch (killErr) {
        return { success: false, message: killErr.message };
      }
    }
  }

  getActiveProcesses() {
    const list = [];
    for (const [id, entry] of this.activeProcesses.entries()) {
      if (entry.record.status === 'running') {
        entry.record.durationMs = Date.now() - entry.startTime;
        list.push({ ...entry.record });
      }
    }
    return list;
  }

  saveCommandHistory(record) {
    try {
      const history = this.storage.read('commands_history') || [];
      history.unshift({
        id: record.id,
        command: record.command,
        cwd: record.cwd,
        startTime: record.startTime,
        durationMs: record.durationMs,
        status: record.status,
        exitCode: record.exitCode,
        stdoutPreview: record.stdout.slice(0, 500),
        stderrPreview: record.stderr.slice(0, 500)
      });
      if (history.length > 200) history.length = 200;
      this.storage.write('commands_history', history);
    } catch (err) {
      console.error('[TerminalManager] Failed to record command history:', err.message);
    }
  }

  getCommandHistory(limit = 50) {
    const history = this.storage.read('commands_history') || [];
    return history.slice(0, limit);
  }
}

let instance = null;
function getTerminalManager(permissionManager, storageManager) {
  if (!instance || permissionManager || storageManager) {
    instance = new TerminalManager(permissionManager, storageManager);
  }
  return instance;
}

module.exports = {
  TerminalManager,
  getTerminalManager
};
