const fs = require('node:fs');
const path = require('node:path');
const { getPermissionManager } = require('../permissions/PermissionManager');
const { getBackupManager } = require('../permissions/BackupManager');

class SafeFileSystem {
  constructor(permissionManager = getPermissionManager(), backupManager = getBackupManager()) {
    this.permissions = permissionManager;
    this.backups = backupManager;
  }

  resolvePath(userPath) {
    if (!userPath) return this.permissions.workspaceRoot;
    if (path.isAbsolute(userPath)) {
      return path.resolve(userPath);
    }
    return path.resolve(this.permissions.workspaceRoot, userPath);
  }

  isBinaryBuffer(buffer) {
    const checkLength = Math.min(buffer.length, 1024);
    for (let i = 0; i < checkLength; i++) {
      if (buffer[i] === 0) return true;
    }
    return false;
  }

  listDirectory(dirPath = '', options = {}) {
    const resolved = this.resolvePath(dirPath);
    const perm = this.permissions.checkPermission('list_directory', { path: resolved });
    if (!perm.allowed) {
      throw new Error(perm.reason || 'Permission denied to list directory');
    }

    if (!fs.existsSync(resolved)) {
      throw new Error(`Directory does not exist: ${dirPath}`);
    }

    const stat = fs.statSync(resolved);
    if (!stat.isDirectory()) {
      throw new Error(`Path is not a directory: ${dirPath}`);
    }

    const defaultIgnore = options.showHidden ? [] : ['.git', 'node_modules', '.nexo', '.cache'];
    const entries = fs.readdirSync(resolved, { withFileTypes: true });

    const results = [];
    for (const entry of entries) {
      if (defaultIgnore.includes(entry.name)) continue;

      const entryPath = path.join(resolved, entry.name);
      const relPath = path.relative(this.permissions.workspaceRoot, entryPath);

      try {
        const entryStat = fs.statSync(entryPath);
        results.push({
          name: entry.name,
          path: entryPath,
          relativePath: relPath || entry.name,
          isDirectory: entry.isDirectory(),
          isFile: entry.isFile(),
          isSymbolicLink: entry.isSymbolicLink(),
          size: entryStat.size,
          mtime: entryStat.mtime.toISOString(),
          mode: entryStat.mode.toString(8)
        });
      } catch (err) {
        // Unreadable file or permission error on specific entry (e.g. Android restricted storage)
        results.push({
          name: entry.name,
          path: entryPath,
          relativePath: relPath || entry.name,
          isDirectory: entry.isDirectory(),
          isFile: entry.isFile(),
          error: 'Unreadable or permission denied in Termux/Android'
        });
      }
    }

    // Sort: directories first, then alphabetical
    results.sort((a, b) => {
      if (a.isDirectory && !b.isDirectory) return -1;
      if (!a.isDirectory && b.isDirectory) return 1;
      return a.name.localeCompare(b.name);
    });

    return results;
  }

  readFile(filePath, options = {}) {
    const resolved = this.resolvePath(filePath);
    const perm = this.permissions.checkPermission('read_file', { path: resolved });
    if (!perm.allowed) {
      throw new Error(perm.reason || 'Permission denied to read file');
    }

    if (!fs.existsSync(resolved)) {
      throw new Error(`File does not exist: ${filePath}`);
    }

    const stat = fs.statSync(resolved);
    if (!stat.isFile()) {
      throw new Error(`Path is not a regular file: ${filePath}`);
    }

    // Read initial chunk to detect binary
    const fd = fs.openSync(resolved, 'r');
    try {
      const probeBuf = Buffer.alloc(1024);
      const bytesRead = fs.readSync(fd, probeBuf, 0, 1024, 0);
      if (this.isBinaryBuffer(probeBuf.subarray(0, bytesRead))) {
        return {
          path: resolved,
          relativePath: path.relative(this.permissions.workspaceRoot, resolved),
          isBinary: true,
          size: stat.size,
          content: null,
          message: 'Binary file detected; text content preview omitted'
        };
      }
    } finally {
      fs.closeSync(fd);
    }

    // Text file reading with chunking support (offset and limit by lines)
    const content = fs.readFileSync(resolved, 'utf-8');
    const lines = content.split('\n');
    const totalLines = lines.length;

    const offset = Math.max(1, parseInt(options.offset, 10) || 1);
    const limit = options.limit ? parseInt(options.limit, 10) : totalLines;

    const startIndex = offset - 1;
    const slicedLines = lines.slice(startIndex, startIndex + limit);
    const slicedContent = slicedLines.join('\n');

    return {
      path: resolved,
      relativePath: path.relative(this.permissions.workspaceRoot, resolved),
      isBinary: false,
      size: stat.size,
      totalLines,
      offset,
      limit,
      returnedLines: slicedLines.length,
      hasMore: startIndex + limit < totalLines,
      content: slicedContent,
      mtime: stat.mtime.toISOString()
    };
  }

  writeFile(filePath, content, options = {}) {
    const resolved = this.resolvePath(filePath);
    const perm = this.permissions.checkPermission('write_file', { path: resolved });

    if (perm.requiresApproval && !options.approved) {
      const approval = this.permissions.requestApproval(
        'write_file',
        {
          path: resolved,
          relativePath: path.relative(this.permissions.workspaceRoot, resolved),
          contentLength: content.length,
          preview: content.slice(0, 300)
        },
        'Agent requested to write/overwrite a file'
      );
      return {
        pendingApproval: true,
        approvalId: approval.id,
        reason: perm.reason
      };
    }

    if (!perm.allowed && !options.approved) {
      throw new Error(perm.reason || 'Permission denied to write file');
    }

    // Backup existing file before overwriting
    if (fs.existsSync(resolved)) {
      this.backups.createBackup(resolved, 'pre-write-backup');
    }

    const dir = path.dirname(resolved);
    if (!fs.existsSync(dir)) {
      fs.mkdirSync(dir, { recursive: true });
    }

    // Atomic write
    const tempFile = `${resolved}.tmp.${Date.now()}`;
    fs.writeFileSync(tempFile, content, 'utf-8');
    fs.renameSync(tempFile, resolved);

    this.permissions.logAudit('write_file', { path: resolved, size: content.length }, 'success');

    const stat = fs.statSync(resolved);
    return {
      success: true,
      path: resolved,
      relativePath: path.relative(this.permissions.workspaceRoot, resolved),
      size: stat.size,
      mtime: stat.mtime.toISOString()
    };
  }

  editFile(filePath, searchText, replacementText, options = {}) {
    const resolved = this.resolvePath(filePath);
    if (!fs.existsSync(resolved)) {
      throw new Error(`File does not exist: ${filePath}`);
    }

    const originalContent = fs.readFileSync(resolved, 'utf-8');

    let newContent = '';
    // 1. Try exact match
    if (originalContent.includes(searchText)) {
      newContent = originalContent.replace(searchText, replacementText);
    } else {
      // 2. Fuzzy / whitespace-tolerant matching
      const normalize = str => str.replace(/\r\n/g, '\n').trim();
      const normSearch = normalize(searchText);
      const lines = originalContent.split(/\r?\n/);
      const searchLines = normSearch.split('\n');

      let matchIndex = -1;
      for (let i = 0; i <= lines.length - searchLines.length; i++) {
        let allMatch = true;
        for (let j = 0; j < searchLines.length; j++) {
          if (lines[i + j].trim() !== searchLines[j].trim()) {
            allMatch = false;
            break;
          }
        }
        if (allMatch) {
          matchIndex = i;
          break;
        }
      }

      if (matchIndex === -1) {
        throw new Error(`Could not find search block in ${filePath}`);
      }

      // Replace matched lines
      const before = lines.slice(0, matchIndex).join('\n');
      const after = lines.slice(matchIndex + searchLines.length).join('\n');
      newContent = [before, replacementText, after].filter(Boolean).join('\n');
    }

    return this.writeFile(filePath, newContent, options);
  }

  createDirectory(dirPath, options = {}) {
    const resolved = this.resolvePath(dirPath);
    const perm = this.permissions.checkPermission('create_directory', { path: resolved });

    if (perm.requiresApproval && !options.approved) {
      const approval = this.permissions.requestApproval(
        'create_directory',
        { path: resolved, relativePath: path.relative(this.permissions.workspaceRoot, resolved) },
        'Agent requested to create a directory'
      );
      return { pendingApproval: true, approvalId: approval.id, reason: perm.reason };
    }

    if (!perm.allowed && !options.approved) {
      throw new Error(perm.reason || 'Permission denied to create directory');
    }

    fs.mkdirSync(resolved, { recursive: true });
    this.permissions.logAudit('create_directory', { path: resolved }, 'success');

    return {
      success: true,
      path: resolved,
      relativePath: path.relative(this.permissions.workspaceRoot, resolved)
    };
  }

  deleteFile(filePath, options = {}) {
    const resolved = this.resolvePath(filePath);
    const perm = this.permissions.checkPermission('delete_file', { path: resolved });

    if (perm.requiresApproval && !options.approved) {
      const approval = this.permissions.requestApproval(
        'delete_file',
        { path: resolved, relativePath: path.relative(this.permissions.workspaceRoot, resolved) },
        'Agent requested to delete a file or directory'
      );
      return { pendingApproval: true, approvalId: approval.id, reason: perm.reason };
    }

    if (!perm.allowed && !options.approved) {
      throw new Error(perm.reason || 'Permission denied to delete file');
    }

    if (!fs.existsSync(resolved)) {
      throw new Error(`File or directory does not exist: ${filePath}`);
    }

    // Always create backup before deletion
    this.backups.createBackup(resolved, 'pre-delete-backup');

    const stat = fs.statSync(resolved);
    if (stat.isDirectory()) {
      fs.rmSync(resolved, { recursive: true, force: true });
    } else {
      fs.unlinkSync(resolved);
    }

    this.permissions.logAudit('delete_file', { path: resolved }, 'success');

    return {
      success: true,
      path: resolved,
      relativePath: path.relative(this.permissions.workspaceRoot, resolved)
    };
  }

  renameFile(oldPath, newPath, options = {}) {
    const resolvedOld = this.resolvePath(oldPath);
    const resolvedNew = this.resolvePath(newPath);

    const permOld = this.permissions.checkPermission('delete_file', { path: resolvedOld });
    const permNew = this.permissions.checkPermission('write_file', { path: resolvedNew });

    if ((permOld.requiresApproval || permNew.requiresApproval) && !options.approved) {
      const approval = this.permissions.requestApproval(
        'rename_file',
        { oldPath: resolvedOld, newPath: resolvedNew },
        'Agent requested to rename/move a file'
      );
      return { pendingApproval: true, approvalId: approval.id };
    }

    if (!fs.existsSync(resolvedOld)) {
      throw new Error(`Source file does not exist: ${oldPath}`);
    }

    // Backup original
    this.backups.createBackup(resolvedOld, 'pre-rename-backup');

    const newDir = path.dirname(resolvedNew);
    if (!fs.existsSync(newDir)) {
      fs.mkdirSync(newDir, { recursive: true });
    }

    fs.renameSync(resolvedOld, resolvedNew);
    this.permissions.logAudit('rename_file', { oldPath: resolvedOld, newPath: resolvedNew }, 'success');

    return {
      success: true,
      oldPath: resolvedOld,
      newPath: resolvedNew
    };
  }

  searchFiles(query, options = {}) {
    const rootDir = this.resolvePath(options.dir || '');
    const maxResults = options.maxResults || 50;
    const isRegex = options.isRegex || false;
    let pattern;
    try {
      pattern = isRegex ? new RegExp(query, 'i') : null;
    } catch (e) {
      throw new Error(`Invalid regex: ${query}`);
    }

    const matches = [];
    const ignoreDirs = new Set(['.git', 'node_modules', '.nexo', '.cache', 'dist', 'build']);

    function traverse(currentDir) {
      if (matches.length >= maxResults) return;

      let entries;
      try {
        entries = fs.readdirSync(currentDir, { withFileTypes: true });
      } catch {
        return;
      }

      for (const entry of entries) {
        if (matches.length >= maxResults) break;
        if (entry.name.startsWith('.') && !options.includeHidden) continue;

        const fullPath = path.join(currentDir, entry.name);

        if (entry.isDirectory()) {
          if (!ignoreDirs.has(entry.name)) {
            traverse(fullPath);
          }
        } else if (entry.isFile()) {
          // Check file extension filters if any
          if (options.extension && !entry.name.endsWith(options.extension)) {
            continue;
          }

          try {
            // Read first chunk to check binary
            const fd = fs.openSync(fullPath, 'r');
            const buf = Buffer.alloc(512);
            const bytes = fs.readSync(fd, buf, 0, 512, 0);
            fs.closeSync(fd);
            let hasNull = false;
            for (let i = 0; i < bytes; i++) {
              if (buf[i] === 0) {
                hasNull = true;
                break;
              }
            }
            if (hasNull) continue;

            const content = fs.readFileSync(fullPath, 'utf-8');
            const lines = content.split('\n');

            for (let lineNum = 1; lineNum <= lines.length; lineNum++) {
              if (matches.length >= maxResults) break;
              const line = lines[lineNum - 1];

              const isMatch = pattern ? pattern.test(line) : line.includes(query);
              if (isMatch) {
                matches.push({
                  file: fullPath,
                  relativePath: path.relative(process.cwd(), fullPath),
                  line: lineNum,
                  content: line.trim().slice(0, 200)
                });
              }
            }
          } catch {
            // Skip unreadable files
          }
        }
      }
    }

    traverse(rootDir);
    return {
      query,
      count: matches.length,
      matches,
      truncated: matches.length >= maxResults
    };
  }

  getFileInfo(filePath) {
    const resolved = this.resolvePath(filePath);
    if (!fs.existsSync(resolved)) {
      return null;
    }
    const stat = fs.statSync(resolved);
    const ext = path.extname(resolved).toLowerCase();
    const rel = path.relative(this.permissions.workspaceRoot, resolved);

    let lineCount = null;
    let isText = true;
    if (stat.isFile() && stat.size < 5 * 1024 * 1024) {
      try {
        const raw = fs.readFileSync(resolved);
        isText = !this.isBinaryBuffer(raw.subarray(0, 1024));
        if (isText) {
          lineCount = raw.toString('utf-8').split('\n').length;
        }
      } catch {
        isText = false;
      }
    }

    return {
      name: path.basename(resolved),
      path: resolved,
      relativePath: rel,
      extension: ext,
      size: stat.size,
      isDirectory: stat.isDirectory(),
      isFile: stat.isFile(),
      isText,
      lineCount,
      mtime: stat.mtime.toISOString(),
      permissions: (stat.mode & 0o777).toString(8)
    };
  }
}

let instance = null;
function getSafeFileSystem(permissionManager, backupManager) {
  if (!instance || permissionManager || backupManager) {
    instance = new SafeFileSystem(permissionManager, backupManager);
  }
  return instance;
}

module.exports = {
  SafeFileSystem,
  getSafeFileSystem
};
