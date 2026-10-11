const { BaseProvider } = require('./BaseProvider');

class OpenAICompatibleProvider extends BaseProvider {
  constructor(config = {}) {
    super(config);
  }

  getHeaders() {
    const headers = {
      'Content-Type': 'application/json',
      'User-Agent': 'NEXO-Terminal/1.0'
    };
    if (this.apiKey) {
      headers['Authorization'] = `Bearer ${this.apiKey}`;
    }
    return headers;
  }

  async testConnection() {
    const startTime = Date.now();
    try {
      const url = `${this.baseUrl.replace(/\/+$/, '')}/models`;
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), Math.min(this.timeout, 10000));

      const response = await fetch(url, {
        method: 'GET',
        headers: this.getHeaders(),
        signal: controller.signal
      });
      clearTimeout(timer);

      const latencyMs = Date.now() - startTime;

      if (!response.ok) {
        const text = await response.text();
        return {
          success: false,
          status: 'error',
          statusCode: response.status,
          latencyMs,
          message: `Provider returned HTTP ${response.status}: ${text.slice(0, 200)}`
        };
      }

      const data = await response.json();
      const models = Array.isArray(data.data) ? data.data.map(m => m.id) : [];

      return {
        success: true,
        status: 'ready',
        latencyMs,
        modelsCount: models.length,
        availableModels: models.slice(0, 20),
        message: `Connected successfully (${latencyMs}ms)`
      };
    } catch (err) {
      return {
        success: false,
        status: 'error',
        latencyMs: Date.now() - startTime,
        message: err.name === 'AbortError' ? 'Connection timed out' : err.message
      };
    }
  }

  async *chatStream(messages, options = {}) {
    const url = `${this.baseUrl.replace(/\/+$/, '')}/chat/completions`;
    const controller = new AbortController();
    const timeoutTimer = setTimeout(() => controller.abort(), this.timeout);

    const body = {
      model: options.model || this.model,
      messages,
      temperature: options.temperature !== undefined ? options.temperature : this.parameters.temperature,
      max_tokens: options.maxTokens || this.parameters.maxTokens || 4096,
      stream: true
    };

    let response;
    try {
      response = await fetch(url, {
        method: 'POST',
        headers: this.getHeaders(),
        body: JSON.stringify(body),
        signal: controller.signal
      });
    } catch (err) {
      clearTimeout(timeoutTimer);
      if (err.name === 'AbortError') {
        throw new Error(`Request timed out after ${this.timeout / 1000}s`);
      }
      throw new Error(`Failed to reach ${this.name} (${this.baseUrl}): ${err.message}`);
    }

    clearTimeout(timeoutTimer);

    if (!response.ok) {
      const errText = await response.text();
      let errorMsg = `HTTP ${response.status}`;
      try {
        const parsed = JSON.parse(errText);
        if (parsed.error && parsed.error.message) {
          errorMsg = parsed.error.message;
        }
      } catch {
        errorMsg = errText.slice(0, 300);
      }
      throw new Error(`Provider Error (${this.name}): ${errorMsg}`);
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
          if (!trimmed || !trimmed.startsWith('data:')) continue;

          const dataStr = trimmed.slice(5).trim();
          if (dataStr === '[DONE]') {
            yield { type: 'done' };
            return;
          }

          try {
            const parsed = JSON.parse(dataStr);
            const choice = parsed.choices?.[0];
            if (!choice) continue;

            const delta = choice.delta || {};
            // DeepSeek-R1 reasoning content support
            if (delta.reasoning_content) {
              yield { type: 'thought', content: delta.reasoning_content };
            }
            if (delta.content) {
              yield { type: 'content', content: delta.content };
            }
            if (choice.finish_reason) {
              yield { type: 'finish', finishReason: choice.finish_reason };
            }
          } catch {
            // Non-fatal JSON parse error on stream line
          }
        }
      }
    } finally {
      reader.releaseLock();
    }
  }
}

module.exports = {
  OpenAICompatibleProvider
};
