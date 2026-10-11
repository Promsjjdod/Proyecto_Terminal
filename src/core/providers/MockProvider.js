const { BaseProvider } = require('./BaseProvider');

class MockProvider extends BaseProvider {
  constructor(config = {}) {
    super({
      id: 'builtin-mock',
      name: 'NEXO Built-in Agent (Local)',
      type: 'mock',
      baseUrl: 'http://localhost:3000/api/mock',
      apiKey: '',
      model: 'nexo-codex-v1',
      parameters: { temperature: 0.2, maxTokens: 4096 },
      ...config
    });
  }

  async testConnection() {
    return {
      success: true,
      status: 'ready',
      latencyMs: 1,
      modelsCount: 1,
      availableModels: ['nexo-codex-v1', 'nexo-architect-v1'],
      message: 'NEXO Local Engine active and ready (Offline mode)'
    };
  }

  async *chatStream(messages, options = {}) {
    const lastMessage = messages[messages.length - 1];
    const userPrompt = lastMessage ? lastMessage.content.toLowerCase() : '';
    const effort = options.effort || 'MEDIUM';

    // Simulate thinking process
    yield {
      type: 'thought',
      content: `[Análisis NEXO en modo ${effort}]\n1. Examinando solicitud del usuario: "${userPrompt.slice(0, 80)}..."\n2. Verificando árbol del proyecto y permisos asignados.\n3. Formulando plan de ejecución con herramientas estructuradas.`
    };

    // Small delay simulation using async sleep
    await new Promise(r => setTimeout(r, 60));

    // Determine intent from prompt
    let responseText = '';

    if (userPrompt.includes('hola') || userPrompt.includes('saludo') || userPrompt.includes('quien eres') || userPrompt.includes('status')) {
      responseText = `Hola, soy **NEXO Terminal**, tu agente de inteligencia artificial avanzado para Android y Termux.

Estoy conectado en modo **${effort}**, listo para programar, inspeccionar archivos, ejecutar comandos autorizados y gestionar tu repositorio Git.

¿En qué proyecto o tarea deseas que trabajemos hoy?`;
    } else if (userPrompt.includes('listar') || userPrompt.includes('archivos') || userPrompt.includes('tree')) {
      responseText = `Voy a inspeccionar la estructura del directorio de trabajo actual para analizar los archivos disponibles.

\`\`\`json
{
  "tool": "list_directory",
  "parameters": {
    "dirPath": ""
  }
}
\`\`\`

He solicitado examinar el directorio raíz para planificar las siguientes acciones.`;
    } else if (userPrompt.includes('crear') || userPrompt.includes('escribir') || userPrompt.includes('archivo')) {
      responseText = `Entendido. Procederé a preparar la creación del archivo solicitado respetando la política de permisos.

\`\`\`json
{
  "tool": "write_file",
  "parameters": {
    "filePath": "src/demo.js",
    "content": "// Creado por NEXO Terminal\\nconsole.log('NEXO Terminal activo');\\n"
  }
}
\`\`\`

El cambio ha sido propuesto y queda sujeto a tu modo de autorización actual.`;
    } else if (userPrompt.includes('git') || userPrompt.includes('commit') || userPrompt.includes('rama')) {
      responseText = `Consultando el estado actual del repositorio Git:

\`\`\`json
{
  "tool": "git_status",
  "parameters": {}
}
\`\`\`

Revisaré los cambios preparados y verificaré que no contengan credenciales ni secretos antes de cualquier confirmación.`;
    } else if (userPrompt.includes('test') || userPrompt.includes('prueba') || userPrompt.includes('ejecutar')) {
      responseText = `Ejecutando suite de pruebas autorizadas para validar la integridad del sistema:

\`\`\`json
{
  "tool": "execute_command",
  "parameters": {
    "command": "npm test"
  }
}
\`\`\`

Supervisando la salida en tiempo real.`;
    } else {
      responseText = `He analizado tu instrucción: "${lastMessage.content}".

**Plan de trabajo formulado:**
1. Inspeccionar archivos de origen pertinentes.
2. Identificar dependencias y requisitos técnicos.
3. Proponer modificaciones o ejecutar los comandos autorizados.
4. Validar el resultado mediante pruebas.

\`\`\`json
{
  "tool": "list_directory",
  "parameters": {
    "dirPath": ""
  }
}
\`\`\`

Procediendo con el análisis inicial del espacio de trabajo.`;
    }

    // Stream out chunks
    const chunks = responseText.split(' ');
    for (const chunk of chunks) {
      yield { type: 'content', content: chunk + ' ' };
      await new Promise(r => setTimeout(r, 15));
    }

    yield { type: 'done' };
  }
}

module.exports = {
  MockProvider
};
