const crypto = require('node:crypto');
const { getStorageManager } = require('../storage/StorageManager');
const { OpenAICompatibleProvider } = require('./OpenAICompatibleProvider');
const { OllamaProvider } = require('./OllamaProvider');
const { MockProvider } = require('./MockProvider');

class ProviderManager {
  constructor(storageManager = getStorageManager()) {
    this.storage = storageManager;
    this.instances = new Map();
  }

  maskKey(key) {
    if (!key) return '';
    if (key.length <= 8) return '****';
    return `${key.slice(0, 4)}...${key.slice(-4)}`;
  }

  listProviders() {
    const providers = this.storage.read('providers') || [];
    const settings = this.storage.read('settings') || {};
    const activeId = settings.activeProviderId;

    return providers.map(p => ({
      id: p.id,
      name: p.name,
      type: p.type,
      baseUrl: p.baseUrl,
      apiKeyMasked: this.maskKey(p.apiKey),
      hasKey: Boolean(p.apiKey),
      model: p.model,
      parameters: p.parameters,
      timeout: p.timeout,
      status: p.status || 'untested',
      active: p.id === activeId
    }));
  }

  getProviderConfig(id) {
    const providers = this.storage.read('providers') || [];
    return providers.find(p => p.id === id) || null;
  }

  getActiveProvider() {
    const settings = this.storage.read('settings') || {};
    const activeId = settings.activeProviderId || 'builtin-mock';
    let config = this.getProviderConfig(activeId);
    if (!config) {
      config = this.getProviderConfig('builtin-mock');
    }
    return config;
  }

  setActiveProvider(id) {
    const config = this.getProviderConfig(id);
    if (!config) {
      throw new Error(`Provider not found with ID: ${id}`);
    }

    const settings = this.storage.read('settings') || {};
    settings.activeProviderId = id;
    this.storage.write('settings', settings);

    // Update active flag in providers list
    const providers = this.storage.read('providers') || [];
    for (const p of providers) {
      p.active = p.id === id;
    }
    this.storage.write('providers', providers);

    return this.getProviderInstance(id);
  }

  getProviderInstance(id) {
    const config = this.getProviderConfig(id);
    if (!config) {
      throw new Error(`Provider config not found: ${id}`);
    }

    if (config.type === 'mock') {
      return new MockProvider(config);
    } else if (config.type === 'ollama') {
      return new OllamaProvider(config);
    } else {
      // Default to OpenAI-compatible
      return new OpenAICompatibleProvider(config);
    }
  }

  async testConnection(id) {
    const config = this.getProviderConfig(id);
    if (!config) {
      throw new Error(`Provider config not found for ID: ${id}`);
    }

    const instance = this.getProviderInstance(id);
    const result = await instance.testConnection();

    // Update status in storage
    const providers = this.storage.read('providers') || [];
    const target = providers.find(p => p.id === id);
    if (target) {
      target.status = result.status;
      target.lastTested = new Date().toISOString();
      target.lastTestResult = result;
      this.storage.write('providers', providers);
    }

    return result;
  }

  addProvider(newConfig) {
    if (!newConfig.name || !newConfig.type || !newConfig.baseUrl) {
      throw new Error('Missing required fields: name, type, baseUrl');
    }

    const id = newConfig.id || `provider-${crypto.randomBytes(4).toString('hex')}`;
    const entry = {
      id,
      name: newConfig.name,
      type: newConfig.type,
      baseUrl: newConfig.baseUrl,
      apiKey: newConfig.apiKey || '',
      model: newConfig.model || 'default',
      parameters: newConfig.parameters || { temperature: 0.2, maxTokens: 4096 },
      timeout: newConfig.timeout || 60000,
      status: 'untested',
      active: Boolean(newConfig.active)
    };

    const providers = this.storage.read('providers') || [];
    providers.push(entry);
    this.storage.write('providers', providers);

    if (entry.active) {
      this.setActiveProvider(id);
    }

    return {
      ...entry,
      apiKeyMasked: this.maskKey(entry.apiKey)
    };
  }

  updateProvider(id, updates) {
    const providers = this.storage.read('providers') || [];
    const index = providers.findIndex(p => p.id === id);
    if (index === -1) {
      throw new Error(`Provider not found: ${id}`);
    }

    // Do not overwrite apiKey with empty string if user didn't change it
    const existing = providers[index];
    const updatedKey = (updates.apiKey !== undefined && updates.apiKey !== '')
      ? updates.apiKey
      : existing.apiKey;

    providers[index] = {
      ...existing,
      ...updates,
      apiKey: updatedKey,
      id // preserve ID
    };

    this.storage.write('providers', providers);
    return {
      ...providers[index],
      apiKeyMasked: this.maskKey(providers[index].apiKey)
    };
  }

  deleteProvider(id) {
    if (id === 'builtin-mock') {
      throw new Error('Cannot delete the built-in offline provider');
    }

    const providers = this.storage.read('providers') || [];
    const filtered = providers.filter(p => p.id !== id);
    if (filtered.length === providers.length) {
      return false;
    }

    this.storage.write('providers', filtered);

    // If active was deleted, fallback to builtin-mock
    const settings = this.storage.read('settings') || {};
    if (settings.activeProviderId === id) {
      this.setActiveProvider('builtin-mock');
    }

    return true;
  }
}

let instance = null;
function getProviderManager(storageManager) {
  if (!instance || storageManager) {
    instance = new ProviderManager(storageManager);
  }
  return instance;
}

module.exports = {
  ProviderManager,
  getProviderManager
};
