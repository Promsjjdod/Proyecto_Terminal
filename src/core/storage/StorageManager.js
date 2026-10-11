const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');

class StorageManager {
  constructor(options = {}) {
    this.baseDir = options.baseDir || path.resolve(process.cwd(), '.nexo');
    this.dataDir = path.join(this.baseDir, 'data');
    this.backupsDir = path.join(this.baseDir, 'backups');
    this.init();
  }

  init() {
    if (!fs.existsSync(this.baseDir)) {
      fs.mkdirSync(this.baseDir, { recursive: true });
    }
    if (!fs.existsSync(this.dataDir)) {
      fs.mkdirSync(this.dataDir, { recursive: true });
    }
    if (!fs.existsSync(this.backupsDir)) {
      fs.mkdirSync(this.backupsDir, { recursive: true });
    }

    // Initialize default tables if not existing
    this.initCollection('settings', {
      theme: 'dark',
      activeProviderId: 'builtin-mock',
      defaultEffort: 'MEDIUM',
      workspaceRoot: process.cwd(),
      securityMode: 'approval', // 'read-only' | 'approval' | 'authorized'
      granularPermissions: {
        canReadFiles: true,
        canWriteFiles: true,
        canDeleteFiles: false,
        canExecuteCommands: true,
        canInstallPackages: false,
        canAccessNetwork: true,
        canGitOps: true,
        canGitHubPublish: false
      }
    });

    this.initCollection('providers', [
      {
        id: 'builtin-mock',
        name: 'NEXO Built-in Agent (Local)',
        type: 'mock',
        baseUrl: 'http://localhost:3000/api/mock',
        apiKey: '',
        model: 'nexo-codex-v1',
        parameters: { temperature: 0.2, maxTokens: 4096 },
        timeout: 30000,
        active: true,
        status: 'ready'
      },
      {
        id: 'ollama-local',
        name: 'Ollama Local (Termux / LAN)',
        type: 'ollama',
        baseUrl: 'http://127.0.0.1:11434',
        apiKey: '',
        model: 'qwen2.5-coder:7b',
        parameters: { temperature: 0.2, maxTokens: 8192 },
        timeout: 60000,
        active: false,
        status: 'untested'
      },
      {
        id: 'openai-standard',
        name: 'OpenAI (GPT-4o)',
        type: 'openai',
        baseUrl: 'https://api.openai.com/v1',
        apiKey: '',
        model: 'gpt-4o',
        parameters: { temperature: 0.2, maxTokens: 8192 },
        timeout: 60000,
        active: false,
        status: 'untested'
      },
      {
        id: 'deepseek-api',
        name: 'DeepSeek API',
        type: 'openai',
        baseUrl: 'https://api.deepseek.com/v1',
        apiKey: '',
        model: 'deepseek-coder',
        parameters: { temperature: 0.1, maxTokens: 8192 },
        timeout: 60000,
        active: false,
        status: 'untested'
      },
      {
        id: 'groq-api',
        name: 'Groq Cloud',
        type: 'openai',
        baseUrl: 'https://api.groq.com/openai/v1',
        apiKey: '',
        model: 'llama-3.3-70b-versatile',
        parameters: { temperature: 0.2, maxTokens: 8192 },
        timeout: 45000,
        active: false,
        status: 'untested'
      }
    ]);

    this.initCollection('conversations', []);
    this.initCollection('tasks', []);
    this.initCollection('approvals', []);
    this.initCollection('audit_logs', []);
    this.initCollection('backups_manifest', []);
    this.initCollection('commands_history', []);
  }

  getFilePath(collectionName) {
    return path.join(this.dataDir, `${collectionName}.json`);
  }

  initCollection(collectionName, defaultData) {
    const filePath = this.getFilePath(collectionName);
    if (!fs.existsSync(filePath)) {
      this.writeAtomic(filePath, defaultData);
    }
  }

  writeAtomic(filePath, data) {
    const tempPath = `${filePath}.${crypto.randomBytes(4).toString('hex')}.tmp`;
    const serialized = JSON.stringify(data, null, 2);
    fs.writeFileSync(tempPath, serialized, 'utf-8');
    fs.renameSync(tempPath, filePath);
  }

  read(collectionName) {
    const filePath = this.getFilePath(collectionName);
    try {
      if (!fs.existsSync(filePath)) {
        return null;
      }
      const raw = fs.readFileSync(filePath, 'utf-8');
      return JSON.parse(raw);
    } catch (err) {
      console.error(`Error reading collection ${collectionName}:`, err.message);
      return null;
    }
  }

  write(collectionName, data) {
    const filePath = this.getFilePath(collectionName);
    this.writeAtomic(filePath, data);
    return data;
  }

  // Array helpers
  find(collectionName, predicate) {
    const list = this.read(collectionName);
    if (!Array.isArray(list)) return null;
    return list.find(predicate);
  }

  filter(collectionName, predicate) {
    const list = this.read(collectionName);
    if (!Array.isArray(list)) return [];
    return list.filter(predicate);
  }

  insert(collectionName, item) {
    const list = this.read(collectionName) || [];
    if (!Array.isArray(list)) {
      throw new Error(`Collection ${collectionName} is not an array`);
    }
    const withId = {
      id: item.id || crypto.randomUUID(),
      createdAt: item.createdAt || new Date().toISOString(),
      ...item
    };
    list.push(withId);
    this.write(collectionName, list);
    return withId;
  }

  update(collectionName, id, updates) {
    const list = this.read(collectionName);
    if (!Array.isArray(list)) return null;
    const index = list.findIndex(item => item.id === id);
    if (index === -1) return null;
    list[index] = {
      ...list[index],
      ...updates,
      updatedAt: new Date().toISOString()
    };
    this.write(collectionName, list);
    return list[index];
  }

  delete(collectionName, id) {
    const list = this.read(collectionName);
    if (!Array.isArray(list)) return false;
    const initialLen = list.length;
    const filtered = list.filter(item => item.id !== id);
    if (filtered.length !== initialLen) {
      this.write(collectionName, filtered);
      return true;
    }
    return false;
  }
}

let instance = null;
function getStorageManager(options) {
  if (!instance || options) {
    instance = new StorageManager(options);
  }
  return instance;
}

module.exports = {
  StorageManager,
  getStorageManager
};
