const { execFile } = require('node:child_process');
const path = require('node:path');
const { getPermissionManager } = require('../permissions/PermissionManager');

class GitManager {
  constructor(permissionManager = getPermissionManager()) {
    this.permissions = permissionManager;
  }

  get cwd() {
    return this.permissions.workspaceRoot;
  }

  runGit(args, options = {}) {
    return new Promise((resolve, reject) => {
      execFile('git', args, { cwd: options.cwd || this.cwd, maxBuffer: 10 * 1024 * 1024 }, (err, stdout, stderr) => {
        if (err) {
          return resolve({
            success: false,
            exitCode: err.code || 1,
            stdout: stdout.toString(),
            stderr: stderr.toString(),
            error: err.message
          });
        }
        resolve({
          success: true,
          exitCode: 0,
          stdout: stdout.toString(),
          stderr: stderr.toString()
        });
      });
    });
  }

  async isGitRepo() {
    const res = await this.runGit(['rev-parse', '--is-inside-work-tree']);
    return res.success && res.stdout.trim() === 'true';
  }

  async getStatus() {
    const isRepo = await this.isGitRepo();
    if (!isRepo) {
      return { isRepo: false, message: 'Workspace is not a Git repository' };
    }

    const res = await this.runGit(['status', '--porcelain=v1', '-b']);
    if (!res.success) {
      throw new Error(`Git status failed: ${res.stderr}`);
    }

    const lines = res.stdout.split('\n').filter(Boolean);
    let branch = 'unknown';
    let ahead = 0;
    let behind = 0;
    const staged = [];
    const modified = [];
    const untracked = [];

    for (const line of lines) {
      if (line.startsWith('## ')) {
        const header = line.slice(3);
        const branchMatch = header.match(/^([^\s.]+)/);
        if (branchMatch) branch = branchMatch[1];

        const aheadMatch = header.match(/ahead (\d+)/);
        if (aheadMatch) ahead = parseInt(aheadMatch[1], 10);

        const behindMatch = header.match(/behind (\d+)/);
        if (behindMatch) behind = parseInt(behindMatch[1], 10);
        continue;
      }

      const x = line[0];
      const y = line[1];
      const filePath = line.slice(3).trim();

      if (x === '?' && y === '?') {
        untracked.push(filePath);
      } else {
        if (x !== ' ' && x !== '?') {
          staged.push({ path: filePath, status: x });
        }
        if (y !== ' ' && y !== '?') {
          modified.push({ path: filePath, status: y });
        }
      }
    }

    return {
      isRepo: true,
      branch,
      ahead,
      behind,
      isClean: staged.length === 0 && modified.length === 0 && untracked.length === 0,
      staged,
      modified,
      untracked,
      totalChanges: staged.length + modified.length + untracked.length
    };
  }

  async getBranches() {
    const res = await this.runGit(['branch', '-a', '--no-color']);
    if (!res.success) throw new Error(res.stderr);

    const lines = res.stdout.split('\n').filter(Boolean);
    const branches = [];
    let current = '';

    for (const raw of lines) {
      const line = raw.trim();
      const isCurrent = raw.startsWith('*');
      const name = line.replace(/^\*\s*/, '');
      if (isCurrent) current = name;
      branches.push({ name, isCurrent, isRemote: name.startsWith('remotes/') });
    }

    return { current, branches };
  }

  async createBranch(branchName) {
    const perm = this.permissions.checkPermission('git_ops');
    if (!perm.allowed) throw new Error(perm.reason);

    const res = await this.runGit(['checkout', '-b', branchName]);
    if (!res.success) throw new Error(res.stderr);
    return { success: true, branch: branchName };
  }

  async checkout(branchName) {
    const perm = this.permissions.checkPermission('git_ops');
    if (!perm.allowed) throw new Error(perm.reason);

    const res = await this.runGit(['checkout', branchName]);
    if (!res.success) throw new Error(res.stderr);
    return { success: true, branch: branchName };
  }

  async getDiff(filePath = null, staged = false) {
    const args = ['diff'];
    if (staged) args.push('--staged');
    if (filePath) args.push('--', filePath);

    const res = await this.runGit(args);
    return { success: res.success, diff: res.stdout, error: res.stderr };
  }

  async stage(files = ['.']) {
    const perm = this.permissions.checkPermission('git_ops');
    if (!perm.allowed) throw new Error(perm.reason);

    const fileList = Array.isArray(files) ? files : [files];
    const res = await this.runGit(['add', ...fileList]);
    if (!res.success) throw new Error(res.stderr);
    return { success: true, staged: fileList };
  }

  async unstage(files = ['.']) {
    const perm = this.permissions.checkPermission('git_ops');
    if (!perm.allowed) throw new Error(perm.reason);

    const fileList = Array.isArray(files) ? files : [files];
    const res = await this.runGit(['reset', 'HEAD', ...fileList]);
    if (!res.success) throw new Error(res.stderr);
    return { success: true, unstaged: fileList };
  }

  async commit(message) {
    const perm = this.permissions.checkPermission('git_ops');
    if (!perm.allowed) throw new Error(perm.reason);

    if (!message || typeof message !== 'string' || !message.trim()) {
      throw new Error('Commit message cannot be empty');
    }

    const res = await this.runGit(['commit', '-m', message]);
    if (!res.success) throw new Error(res.stderr || res.stdout);
    return { success: true, output: res.stdout };
  }

  async getLog(limit = 20) {
    const format = '%H|%h|%an|%ae|%ad|%ar|%s';
    const res = await this.runGit(['log', `-n${limit}`, `--pretty=format:${format}`, '--date=iso']);
    if (!res.success) {
      if (res.stderr.includes('does not have any commits yet')) {
        return [];
      }
      throw new Error(res.stderr);
    }

    const lines = res.stdout.split('\n').filter(Boolean);
    return lines.map(line => {
      const [hash, shortHash, author, email, date, relativeDate, ...subjectParts] = line.split('|');
      return {
        hash,
        shortHash,
        author,
        email,
        date,
        relativeDate,
        message: subjectParts.join('|')
      };
    });
  }
}

let instance = null;
function getGitManager(permissionManager) {
  if (!instance || permissionManager) {
    instance = new GitManager(permissionManager);
  }
  return instance;
}

module.exports = {
  GitManager,
  getGitManager
};
