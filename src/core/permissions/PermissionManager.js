const path = require('node:path');
const fs = require('node:fs');
const crypto = require('node:crypto');
const { getStorageManager } = require('../storage/StorageManager');

const SECURITY_MODES = {
  READ_ONLY: 'read-only',
  APPROVAL: 'approval',
  AUTHORIZED: 'authorized'
};

class PermissionManager {
  constructor(storageManager = getStorageManager()) {
    this.storage = storageManager;
    this.reloadConfig();
  }

  reloadConfig() {
    const settings = this.storage.read('settings') || {};
    this.mode = settings.securityMode || SECURITY_MODES.APPROVAL;
    this.workspaceRoot = path.resolve(settings.workspaceRoot || process.cwd());
    this.granular = {
      canReadFiles: true,
      canWriteFiles: true,
      canDeleteFiles: false,
      canExecuteCommands: true,
      canInstallPackages: false,
      canAccessNetwork: true,
      canGitOps: true,
      canGitHubPublish: false,
      ...(settings.granularPermissions || {})
    };
  }

  saveConfig() {
    const settings = this.storage.read('settings') || {};
    settings.securityMode = this.mode;
    settings.workspaceRoot = this.workspaceRoot;
    settings.granularPermissions = this.granular;
    this.storage.write('settings', settings);
  }

  setMode(newMode) {
    if (!Object.values(SECURITY_MODES).includes(newMode)) {
      throw new Error(`Invalid security mode: ${newMode}. Must be one of: ${Object.values(SECURITY_MODES).join(', ')}`);
    }
    this.mode = newMode;
    this.saveConfig();
    this.logAudit('change_security_mode', { newMode }, 'success');
    return this.mode;
  }

  setGranular(permissions) {
    this.granular = {
      ...this.granular,
      ...permissions
    };
    this.saveConfig();
    this.logAudit('change_granular_permissions', permissions, 'success');
    return this.granular;
  }

  setWorkspaceRoot(newRoot) {
    const resolved = path.resolve(newRoot);
    if (!fs.existsSync(resolved)) {
      throw new Error(`Workspace root does not exist: ${resolved}`);
    }
    this.workspaceRoot = resolved;
    this.saveConfig();
    this.logAudit('change_workspace_root', { newRoot: resolved }, 'success');
    return this.workspaceRoot;
  }

  isPathAllowed(targetPath) {
    if (!targetPath || typeof targetPath !== 'string') return false;
    // Disallow null bytes
    if (targetPath.includes('\0')) return false;

    try {
      const resolved = path.resolve(this.workspaceRoot, targetPath);
      const relative = path.relative(this.workspaceRoot, resolved);
      // Path must be inside workspace root (relative does not start with .. and is not absolute)
      if (relative.startsWith('..') || path.isAbsolute(relative)) {
        return false;
      }

      // Check realpath if file/dir already exists to prevent symlink traversal outside workspace
      if (fs.existsSync(resolved)) {
        const real = fs.realpathSync(resolved);
        const realRel = path.relative(this.workspaceRoot, real);
        if (realRel.startsWith('..') || path.isAbsolute(realRel)) {
          return false;
        }
      }
      return true;
    } catch {
      return false;
    }
  }

  checkPermission(action, details = {}) {
    // 1. Path check if target is a file or directory
    if (details.path) {
      if (!this.isPathAllowed(details.path)) {
        this.logAudit(action, details, 'denied', 'Path outside authorized workspace');
        return {
          allowed: false,
          requiresApproval: false,
          reason: `Access denied: Target path '${details.path}' is outside the authorized workspace (${this.workspaceRoot})`
        };
      }
    }

    // 2. Read operations
    if (action === 'read_file' || action === 'list_directory' || action === 'search_files') {
      if (!this.granular.canReadFiles) {
        this.logAudit(action, details, 'denied', 'Read permission disabled');
        return { allowed: false, requiresApproval: false, reason: 'File reading is disabled in granular permissions' };
      }
      return { allowed: true, requiresApproval: false };
    }

    // 3. Write / Create operations
    if (action === 'write_file' || action === 'edit_file' || action === 'create_directory') {
      if (this.mode === SECURITY_MODES.READ_ONLY) {
        this.logAudit(action, details, 'denied', 'Read-only mode active');
        return { allowed: false, requiresApproval: false, reason: 'Agent is in READ_ONLY mode. Modifying files is forbidden.' };
      }
      if (!this.granular.canWriteFiles) {
        this.logAudit(action, details, 'denied', 'Write permission disabled');
        return { allowed: false, requiresApproval: false, reason: 'File write permission is disabled in granular permissions' };
      }
      if (this.mode === SECURITY_MODES.APPROVAL) {
        return { allowed: false, requiresApproval: true, reason: 'Approval required before modifying files' };
      }
      return { allowed: true, requiresApproval: false };
    }

    // 4. Delete operations
    if (action === 'delete_file' || action === 'delete_directory') {
      if (this.mode === SECURITY_MODES.READ_ONLY) {
        return { allowed: false, requiresApproval: false, reason: 'Agent is in READ_ONLY mode. File deletion forbidden.' };
      }
      if (!this.granular.canDeleteFiles && this.mode !== SECURITY_MODES.APPROVAL) {
        return { allowed: false, requiresApproval: true, reason: 'File deletion requires explicit user approval' };
      }
      if (this.mode === SECURITY_MODES.APPROVAL) {
        return { allowed: false, requiresApproval: true, reason: 'Approval required before deleting files' };
      }
      return { allowed: true, requiresApproval: false };
    }

    // 5. Command execution
    if (action === 'execute_command') {
      if (this.mode === SECURITY_MODES.READ_ONLY) {
        return { allowed: false, requiresApproval: false, reason: 'Agent is in READ_ONLY mode. Command execution forbidden.' };
      }
      if (!this.granular.canExecuteCommands) {
        return { allowed: false, requiresApproval: false, reason: 'Command execution disabled in granular permissions' };
      }
      if (this.mode === SECURITY_MODES.APPROVAL) {
        return { allowed: false, requiresApproval: true, reason: 'Approval required before running commands' };
      }
      return { allowed: true, requiresApproval: false };
    }

    // 6. Package install
    if (action === 'install_package') {
      if (this.mode === SECURITY_MODES.READ_ONLY) {
        return { allowed: false, requiresApproval: false, reason: 'Package installation forbidden in READ_ONLY mode.' };
      }
      if (!this.granular.canInstallPackages) {
        return { allowed: false, requiresApproval: true, reason: 'Package installation requires approval' };
      }
      if (this.mode === SECURITY_MODES.APPROVAL) {
        return { allowed: false, requiresApproval: true, reason: 'Approval required before installing packages' };
      }
      return { allowed: true, requiresApproval: false };
    }

    // 7. Git Operations
    if (action === 'git_ops') {
      if (!this.granular.canGitOps) {
        return { allowed: false, requiresApproval: false, reason: 'Git operations disabled in granular permissions' };
      }
      return { allowed: true, requiresApproval: false };
    }

    // 8. GitHub publish
    if (action === 'github_publish') {
      if (!this.granular.canGitHubPublish) {
        return { allowed: false, requiresApproval: true, reason: 'Publishing to GitHub requires explicit approval' };
      }
      if (this.mode === SECURITY_MODES.APPROVAL) {
        return { allowed: false, requiresApproval: true, reason: 'Approval required before publishing to GitHub' };
      }
      return { allowed: true, requiresApproval: false };
    }

    return { allowed: true, requiresApproval: false };
  }

  // Pending Approvals Queue
  requestApproval(action, details, reason) {
    const approval = {
      id: crypto.randomUUID(),
      action,
      details,
      reason,
      status: 'pending', // 'pending' | 'approved' | 'rejected'
      requestedAt: new Date().toISOString()
    };

    const approvals = this.storage.read('approvals') || [];
    approvals.push(approval);
    this.storage.write('approvals', approvals);

    this.logAudit(action, details, 'approval_requested', reason);
    return approval;
  }

  getPendingApprovals() {
    const approvals = this.storage.read('approvals') || [];
    return approvals.filter(a => a.status === 'pending');
  }

  approve(approvalId) {
    const approvals = this.storage.read('approvals') || [];
    const item = approvals.find(a => a.id === approvalId);
    if (!item) {
      throw new Error(`Approval item not found: ${approvalId}`);
    }
    item.status = 'approved';
    item.resolvedAt = new Date().toISOString();
    this.storage.write('approvals', approvals);

    this.logAudit(item.action, item.details, 'approved_by_user');
    return item;
  }

  reject(approvalId, rejectionReason = 'Rejected by user') {
    const approvals = this.storage.read('approvals') || [];
    const item = approvals.find(a => a.id === approvalId);
    if (!item) {
      throw new Error(`Approval item not found: ${approvalId}`);
    }
    item.status = 'rejected';
    item.rejectionReason = rejectionReason;
    item.resolvedAt = new Date().toISOString();
    this.storage.write('approvals', approvals);

    this.logAudit(item.action, item.details, 'rejected_by_user', rejectionReason);
    return item;
  }

  logAudit(action, details, status, reason = '') {
    try {
      const logs = this.storage.read('audit_logs') || [];
      const entry = {
        id: crypto.randomUUID(),
        timestamp: new Date().toISOString(),
        action,
        details: typeof details === 'object' ? { ...details } : { raw: details },
        status,
        reason
      };
      logs.unshift(entry);
      if (logs.length > 500) logs.length = 500;
      this.storage.write('audit_logs', logs);
    } catch (err) {
      console.error('[PermissionManager] Audit logging failed:', err.message);
    }
  }

  getAuditLogs(limit = 100) {
    const logs = this.storage.read('audit_logs') || [];
    return logs.slice(0, limit);
  }

  getStatus() {
    return {
      mode: this.mode,
      workspaceRoot: this.workspaceRoot,
      granular: { ...this.granular },
      pendingApprovalsCount: this.getPendingApprovals().length
    };
  }
}

let instance = null;
function getPermissionManager(storageManager) {
  if (!instance || storageManager) {
    instance = new PermissionManager(storageManager);
  }
  return instance;
}

module.exports = {
  SECURITY_MODES,
  PermissionManager,
  getPermissionManager
};
