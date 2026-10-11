const path = require('node:path');
const { getSafeFileSystem } = require('../fs/SafeFileSystem');
const { getTerminalManager } = require('../terminal/TerminalManager');
const { getGitManager } = require('../git/GitManager');
const { getBackupManager } = require('../permissions/BackupManager');

class ToolRegistry {
  constructor(options = {}) {
    this.fs = options.fs || getSafeFileSystem();
    this.terminal = options.terminal || getTerminalManager();
    this.git = options.git || getGitManager();
    this.backups = options.backups || getBackupManager();
  }

  getToolsDefinitions() {
    return [
      {
        name: 'list_directory',
        description: 'List contents of a directory in the workspace with metadata (size, type, permissions).',
        parameters: {
          dirPath: { type: 'string', description: 'Directory path relative to workspace root (empty for root)' },
          showHidden: { type: 'boolean', description: 'Whether to show hidden files (default false)' }
        }
      },
      {
        name: 'read_file',
        description: 'Read the contents of a text file with optional line offset and limit for large files.',
        parameters: {
          filePath: { type: 'string', description: 'Relative path to the file', required: true },
          offset: { type: 'number', description: 'Starting line number (1-indexed)' },
          limit: { type: 'number', description: 'Number of lines to read' }
        }
      },
      {
        name: 'write_file',
        description: 'Create or overwrite a file with full content. Automatically creates a backup for rollback.',
        parameters: {
          filePath: { type: 'string', description: 'Relative path to the file', required: true },
          content: { type: 'string', description: 'Complete content to write', required: true }
        }
      },
      {
        name: 'edit_file',
        description: 'Replace an existing block of code in a file with new code. Supports whitespace-tolerant matching.',
        parameters: {
          filePath: { type: 'string', description: 'Relative path to the file', required: true },
          searchText: { type: 'string', description: 'Exact or whitespace-similar block to replace', required: true },
          replacementText: { type: 'string', description: 'Replacement content', required: true }
        }
      },
      {
        name: 'create_directory',
        description: 'Create a new directory recursively.',
        parameters: {
          dirPath: { type: 'string', description: 'Relative directory path', required: true }
        }
      },
      {
        name: 'delete_file',
        description: 'Delete a file or directory. Automatically takes a backup first.',
        parameters: {
          filePath: { type: 'string', description: 'Relative path to delete', required: true }
        }
      },
      {
        name: 'search_files',
        description: 'Search for text or regex across project files.',
        parameters: {
          query: { type: 'string', description: 'Text or regex query', required: true },
          dir: { type: 'string', description: 'Subdirectory to search in' },
          extension: { type: 'string', description: 'File extension filter (e.g. .js, .py)' },
          isRegex: { type: 'boolean', description: 'Whether query is a regex' }
        }
      },
      {
        name: 'execute_command',
        description: 'Execute a safe shell command in Termux (e.g. npm test, git, node, python). Blocks dangerous operations.',
        parameters: {
          command: { type: 'string', description: 'The command line to run', required: true },
          timeoutMs: { type: 'number', description: 'Timeout in milliseconds (default 120000)' }
        }
      },
      {
        name: 'git_status',
        description: 'Get the current Git repository status (branch, modified, staged, untracked).',
        parameters: {}
      },
      {
        name: 'git_diff',
        description: 'View current Git diff for unstaged or staged changes.',
        parameters: {
          filePath: { type: 'string', description: 'Optional specific file to diff' },
          staged: { type: 'boolean', description: 'View staged diff if true' }
        }
      },
      {
        name: 'git_log',
        description: 'View recent Git commit history.',
        parameters: {
          limit: { type: 'number', description: 'Maximum commits to return (default 10)' }
        }
      },
      {
        name: 'git_commit',
        description: 'Stage files and commit with a message. Runs secret scanner before committing.',
        parameters: {
          message: { type: 'string', description: 'Commit message', required: true }
        }
      },
      {
        name: 'rollback_file',
        description: 'Restore a file to its previous backup version.',
        parameters: {
          filePath: { type: 'string', description: 'Path to restore', required: true }
        }
      }
    ];
  }

  async executeTool(toolName, params = {}, options = {}) {
    switch (toolName) {
      case 'list_directory':
        return this.fs.listDirectory(params.dirPath || '', { showHidden: Boolean(params.showHidden) });

      case 'read_file':
        if (!params.filePath) throw new Error('Missing parameter: filePath');
        return this.fs.readFile(params.filePath, { offset: params.offset, limit: params.limit });

      case 'write_file':
        if (!params.filePath || params.content === undefined) throw new Error('Missing filePath or content');
        return this.fs.writeFile(params.filePath, params.content, options);

      case 'edit_file':
        if (!params.filePath || !params.searchText || params.replacementText === undefined) {
          throw new Error('Missing filePath, searchText, or replacementText');
        }
        return this.fs.editFile(params.filePath, params.searchText, params.replacementText, options);

      case 'create_directory':
        if (!params.dirPath) throw new Error('Missing parameter: dirPath');
        return this.fs.createDirectory(params.dirPath, options);

      case 'delete_file':
        if (!params.filePath) throw new Error('Missing parameter: filePath');
        return this.fs.deleteFile(params.filePath, options);

      case 'search_files':
        if (!params.query) throw new Error('Missing parameter: query');
        return this.fs.searchFiles(params.query, params);

      case 'execute_command': {
        if (!params.command) throw new Error('Missing parameter: command');
        const execRes = this.terminal.execute(params.command, options);
        if (execRes.pendingApproval) {
          return execRes;
        }
        // Wait for command completion
        const completed = await execRes.promise;
        return {
          command: completed.command,
          exitCode: completed.exitCode,
          durationMs: completed.durationMs,
          status: completed.status,
          stdout: completed.stdout,
          stderr: completed.stderr
        };
      }

      case 'git_status':
        return await this.git.getStatus();

      case 'git_diff':
        return await this.git.getDiff(params.filePath, params.staged);

      case 'git_log':
        return await this.git.getLog(params.limit || 10);

      case 'git_commit':
        await this.git.stage(['.']);
        return await this.git.commit(params.message);

      case 'rollback_file':
        return this.backups.rollbackLatest(params.filePath);

      default:
        throw new Error(`Unknown tool: ${toolName}`);
    }
  }
}

let instance = null;
function getToolRegistry(options) {
  if (!instance || options) {
    instance = new ToolRegistry(options);
  }
  return instance;
}

module.exports = {
  ToolRegistry,
  getToolRegistry
};
