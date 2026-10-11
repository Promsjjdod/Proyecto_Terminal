const { BaseProvider } = require('./BaseProvider');

class OllamaProvider extends BaseProvider {
  constructor(config = {}) {
    super(config);
  }

  async testConnection() {
    const startTime = Date.now();
    try {
      const url = `${this.baseUrl.replace(/\/+$/, '')}/api/tags`;
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), Math.min(this.timeout, 10000));

      const response = await fetch(url, {
        method: 'GET',
        headers: { 'Content-Type': 'application/json' },
        signal: controller.signal
      });
      clearTimeout(timer);

      const latencyMs = Date.now() - startTime;

      if (!response.ok) {
        return {
          success: false,
          status: 'error',
          statusCode: response.status,
          latencyMs,
          message: `Ollama returned HTTP ${response.status}`
        };
      }

      const data = await response.json();
      const models = Array.isArray(data.models) ? data.models.map(m => m.name) : [];

      return {
        success: true,
        status: 'ready',
        latencyMs,
        modelsCount: models.length,
        availableModels: models,
        message: `Ollama running with ${models.length} model(s) installed`
      };
    } catch (err) {
      return {
        success: false,
        status: 'error',
        latencyMs: Date.now() - startTime,
        message: err.name === 'AbortError' ? 'Ollama connection timed out' : `Ollama unreachable at ${this.baseUrl}: ${err.message}`
      };
    }
  }

  async *chatStream(messages, options = {}) {
    const url = `${this.baseUrl.replace(/\/+$/, '')}/api/chat`;
    const controller = new AbortController();
    const timeoutTimer = setTimeout(() => controller.abort(), this.timeout);

    const body = {
      model: options.model || this.model,
      messages,
      stream: true,
      options: {
        temperature: options.temperature !== undefined ? options.temperature : this.parameters.temperature,
        num_predict: options.maxTokens || this.parameters.maxTokens || 4096
      }
    };

    let response;
    try {
      response = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal: controller.signal
      });
    } catch (err) {
      clearTimeout(timeoutTimer);
      throw new Error(`Failed to reach Ollama at ${this.baseUrl}: ${err.message}`);
    }

    clearTimeout(timeoutTimer);

    if (!response.ok) {
      const errText = await response.text();
      throw new Error(`Ollama Error: HTTP ${response.status} - ${errText.slice(0, 200)}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed) continue;

          try {
            const parsed = JSON.parse(trimmed);
            if (parsed.message?.content) {
              yield { type: 'content', content: parsed.message.content };
            }
            if (parsed.done) {
              yield { type: 'done' };
              return;
            }
          } catch {
            // Non-fatal parse error
          }
        }
      }
    } finally {
      reader.releaseLock();
    }
  }
}

module.exports = {
  OllamaProvider
};
