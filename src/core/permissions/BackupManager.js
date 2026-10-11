const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { getStorageManager } = require('../storage/StorageManager');

class BackupManager {
  constructor(storageManager = getStorageManager()) {
    this.storage = storageManager;
    this.backupsDir = this.storage.backupsDir;
  }

  createBackup(filePath, reason = 'auto-backup') {
    if (!fs.existsSync(filePath)) {
      return null; // File doesn't exist yet, nothing to back up
    }

    try {
      const stats = fs.statSync(filePath);
      if (!stats.isFile()) {
        return null;
      }

      const content = fs.readFileSync(filePath);
      const hash = crypto.createHash('sha256').update(content).digest('hex');
      const ext = path.extname(filePath);
      const baseName = path.basename(filePath, ext);
      const timestamp = Date.now();
      const backupFileName = `${baseName}_${timestamp}_${crypto.randomBytes(3).toString('hex')}${ext}.bak`;
      const backupPath = path.join(this.backupsDir, backupFileName);

      fs.writeFileSync(backupPath, content);

      const backupEntry = {
        id: crypto.randomUUID(),
        filePath: path.resolve(filePath),
        relativePath: path.relative(process.cwd(), filePath),
        backupPath,
        backupFileName,
        timestamp: new Date().toISOString(),
        size: stats.size,
        hash,
        reason
      };

      const manifest = this.storage.read('backups_manifest') || [];
      manifest.unshift(backupEntry);
      // Keep manifest reasonably sized (e.g. max 500 backups)
      if (manifest.length > 500) {
        manifest.length = 500;
      }
      this.storage.write('backups_manifest', manifest);

      return backupEntry;
    } catch (err) {
      console.error(`[BackupManager] Failed to create backup for ${filePath}:`, err.message);
      return null;
    }
  }

  listBackups(filePath = null) {
    const manifest = this.storage.read('backups_manifest') || [];
    if (!filePath) {
      return manifest;
    }
    const resolved = path.resolve(filePath);
    return manifest.filter(b => b.filePath === resolved);
  }

  getBackup(backupId) {
    const manifest = this.storage.read('backups_manifest') || [];
    return manifest.find(b => b.id === backupId) || null;
  }

  rollback(backupId) {
    const backup = this.getBackup(backupId);
    if (!backup) {
      throw new Error(`Backup not found with ID: ${backupId}`);
    }

    if (!fs.existsSync(backup.backupPath)) {
      throw new Error(`Physical backup file missing at: ${backup.backupPath}`);
    }

    // Before rolling back, create a new backup of current state so rollback is also reversible
    if (fs.existsSync(backup.filePath)) {
      this.createBackup(backup.filePath, 'pre-rollback-snapshot');
    }

    const content = fs.readFileSync(backup.backupPath);
    // Ensure destination directory exists
    const dir = path.dirname(backup.filePath);
    if (!fs.existsSync(dir)) {
      fs.mkdirSync(dir, { recursive: true });
    }

    fs.writeFileSync(backup.filePath, content);
    return {
      success: true,
      filePath: backup.filePath,
      restoredFrom: backup.backupFileName,
      timestamp: new Date().toISOString()
    };
  }

  rollbackLatest(filePath) {
    const backups = this.listBackups(filePath);
    if (!backups.length) {
      throw new Error(`No backups found for file: ${filePath}`);
    }
    return this.rollback(backups[0].id);
  }
}

let instance = null;
function getBackupManager(storageManager) {
  if (!instance || storageManager) {
    instance = new BackupManager(storageManager);
  }
  return instance;
}

module.exports = {
  BackupManager,
  getBackupManager
};
