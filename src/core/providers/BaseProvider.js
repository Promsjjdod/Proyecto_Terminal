class BaseProvider {
  constructor(config = {}) {
    this.id = config.id;
    this.name = config.name;
    this.type = config.type;
    this.baseUrl = config.baseUrl;
    this.apiKey = config.apiKey || '';
    this.model = config.model;
    this.parameters = config.parameters || { temperature: 0.2, maxTokens: 4096 };
    this.timeout = config.timeout || 60000;
  }

  maskKey(key) {
    if (!key) return '';
    if (key.length <= 8) return '****';
    return `${key.slice(0, 4)}...${key.slice(-4)}`;
  }

  toJSON() {
    return {
      id: this.id,
      name: this.name,
      type: this.type,
      baseUrl: this.baseUrl,
      apiKeyMasked: this.maskKey(this.apiKey),
      hasKey: Boolean(this.apiKey),
      model: this.model,
      parameters: this.parameters,
      timeout: this.timeout
    };
  }

  async testConnection() {
    throw new Error('testConnection() must be implemented by subclass');
  }

  async *chatStream(messages, options = {}) {
    throw new Error('chatStream() must be implemented by subclass');
  }
}

module.exports = {
  BaseProvider
};
