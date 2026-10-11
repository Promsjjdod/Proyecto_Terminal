const { execFile } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const { getGitManager } = require('./GitManager');
const { getPermissionManager } = require('../permissions/PermissionManager');

class SecretScanner {
  static SECRET_PATTERNS = [
    { name: 'OpenAI API Key', regex: /sk-[a-zA-Z0-9_-]{20,}/g },
    { name: 'GitHub Classic Token', regex: /ghp_[a-zA-Z0-9]{36}/g },
    { name: 'GitHub Fine-grained PAT', regex: /github_pat_[a-zA-Z0-9_]{82}/g },
    { name: 'AWS Access Key ID', regex: /AKIA[0-9A-Z]{16}/g },
    { name: 'Private Key Block', regex: /-----BEGIN (RSA|EC|OPENSSH|DSA|PGP) PRIVATE KEY-----/g },
    { name: 'Generic Secret Assignment', regex: /(?:api_key|apiKey|secret_key|secretKey|auth_token)\s*=\s*['"][a-zA-Z0-9_\-]{16,}['"]/gi }
  ];

  static SENSITIVE_FILENAMES = [
    /^\.env(\..+)?$/i,
    /^id_rsa$/i,
    /^id_ed25519$/i,
    /\.pem$/i,
    /\.key$/i,
    /\.pfx$/i
  ];

  /**
   * Scans a file on disk for sensitive patterns and sensitive filenames.
   */
  static scanFile(filePath) {
    const fileName = path.basename(filePath);
    const findings = [];

    for (const pattern of this.SENSITIVE_FILENAMES) {
      if (pattern.test(fileName)) {
        findings.push({
          type: 'sensitive_filename',
          description: `Filename matches sensitive file pattern (${fileName})`,
          line: 0
        });
      }
    }

    if (!fs.existsSync(filePath)) return findings;

    try {
      const stat = fs.statSync(filePath);
      if (stat.size > 2 * 1024 * 1024) return findings; // Skip huge files

      const content = fs.readFileSync(filePath, 'utf-8');
      const lines = content.split(/\r?\n/);

      for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        for (const pattern of this.SECRET_PATTERNS) {
          if (pattern.regex.test(line)) {
            findings.push({
              type: 'secret_pattern',
              patternName: pattern.name,
              description: `Potential secret found: ${pattern.name}`,
              line: i + 1,
              sample: line.slice(0, 100).replace(/./g, (c, idx) => (idx < 5 || idx > 25 ? c : '*'))
            });
          }
        }
      }
    } catch {
      // Ignore unreadable binary files
    }

    return findings;
  }

  /**
   * Scans an array of files.
   */
  static scanFiles(filePaths, workspaceRoot = process.cwd()) {
    const results = [];
    for (const file of filePaths) {
      const fullPath = path.isAbsolute(file) ? file : path.resolve(workspaceRoot, file);
      const findings = this.scanFile(fullPath);
      if (findings.length > 0) {
        results.push({
          file,
          relativePath: path.relative(workspaceRoot, fullPath),
          findings
        });
      }
    }
    return results;
  }
}

class GitHubManager {
  constructor(gitManager = getGitManager(), permissionManager = getPermissionManager()) {
    this.git = gitManager;
    this.permissions = permissionManager;
  }

  runGh(args, options = {}) {
    return new Promise((resolve) => {
      execFile('gh', args, { cwd: options.cwd || this.git.cwd, maxBuffer: 10 * 1024 * 1024 }, (err, stdout, stderr) => {
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

  async checkAuth() {
    const res = await this.runGh(['auth', 'status']);
    if (res.success || (res.stderr && res.stderr.includes('Logged in to github.com'))) {
      const matchUser = (res.stdout + res.stderr).match(/account\s+([a-zA-Z0-9_\-]+)/i);
      const username = matchUser ? matchUser[1] : 'Authenticated User';
      return {
        authenticated: true,
        user: username,
        details: res.stdout || res.stderr
      };
    }

    // Check environment token
    if (process.env.GITHUB_TOKEN || process.env.GH_TOKEN) {
      return {
        authenticated: true,
        user: 'Token User',
        details: 'Authenticated via environment variable GITHUB_TOKEN'
      };
    }

    return {
      authenticated: false,
      user: null,
      message: 'GitHub CLI is not authenticated. Run `gh auth login` in Termux or configure a Personal Access Token (PAT).'
    };
  }

  async listRepos(limit = 30) {
    const auth = await this.checkAuth();
    if (!auth.authenticated) {
      throw new Error(`GitHub not authenticated: ${auth.message}`);
    }

    const res = await this.runGh(['repo', 'list', '--limit', limit.toString(), '--json', 'name,nameWithOwner,isPrivate,url,updatedAt,description']);
    if (!res.success) {
      throw new Error(`Failed to list GitHub repos: ${res.stderr || res.stdout}`);
    }

    try {
      return JSON.parse(res.stdout);
    } catch {
      return [];
    }
  }

  async createRepo(name, description = '', isPrivate = true) {
    const perm = this.permissions.checkPermission('github_publish');
    if (!perm.allowed) {
      throw new Error(perm.reason || 'GitHub repository creation requires permission.');
    }

    const auth = await this.checkAuth();
    if (!auth.authenticated) {
      throw new Error(`GitHub not authenticated: ${auth.message}`);
    }

    const args = ['repo', 'create', name, description ? `--description=${description}` : '', isPrivate ? '--private' : '--public', '--source=.', '--remote=origin'];
    const filteredArgs = args.filter(Boolean);

    const res = await this.runGh(filteredArgs);
    if (!res.success) {
      throw new Error(`Failed to create GitHub repo: ${res.stderr || res.stdout}`);
    }

    return {
      success: true,
      output: res.stdout || res.stderr,
      repoName: name
    };
  }

  async getPublishSummary(remote = 'origin', branch = null) {
    const status = await this.git.getStatus();
    const targetBranch = branch || status.branch;

    // Secret check on staged and untracked files
    const allChangedFiles = [
      ...status.staged.map(s => s.path),
      ...status.modified.map(m => m.path),
      ...status.untracked
    ];

    const secretFindings = SecretScanner.scanFiles(allChangedFiles, this.permissions.workspaceRoot);

    return {
      remote,
      branch: targetBranch,
      ahead: status.ahead,
      behind: status.behind,
      stagedCount: status.staged.length,
      modifiedCount: status.modified.length,
      untrackedCount: status.untracked.length,
      hasSecretFindings: secretFindings.length > 0,
      secretFindings
    };
  }

  async push(remote = 'origin', branch = null, options = {}) {
    const perm = this.permissions.checkPermission('github_publish');

    if (perm.requiresApproval && !options.approved) {
      const summary = await this.getPublishSummary(remote, branch);
      const approval = this.permissions.requestApproval(
        'github_publish',
        { remote, branch, summary },
        'Agent requested to push changes to GitHub'
      );
      return {
        pendingApproval: true,
        approvalId: approval.id,
        summary,
        reason: perm.reason
      };
    }

    if (!perm.allowed && !options.approved) {
      throw new Error(perm.reason || 'Permission denied to push to GitHub');
    }

    // Strict Secret Scan before push!
    const summary = await this.getPublishSummary(remote, branch);
    if (summary.hasSecretFindings && !options.ignoreSecrets) {
      throw new Error(
        `CRITICAL SAFETY CHECK: Secret scanner detected credentials/tokens in files before push! Push aborted.\n` +
        JSON.stringify(summary.secretFindings, null, 2)
      );
    }

    const targetBranch = branch || (await this.git.getStatus()).branch;
    const res = await this.git.runGit(['push', remote, targetBranch]);

    if (!res.success) {
      throw new Error(`Git push failed: ${res.stderr || res.stdout}`);
    }

    this.permissions.logAudit('github_publish', { remote, branch: targetBranch }, 'success');

    return {
      success: true,
      remote,
      branch: targetBranch,
      output: res.stdout || res.stderr
    };
  }
}

let instance = null;
function getGitHubManager(gitManager, permissionManager) {
  if (!instance || gitManager || permissionManager) {
    instance = new GitHubManager(gitManager, permissionManager);
  }
  return instance;
}

module.exports = {
  SecretScanner,
  GitHubManager,
  getGitHubManager
};
