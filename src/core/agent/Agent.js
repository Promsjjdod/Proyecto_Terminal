const EventEmitter = require('node:events');
const { getToolRegistry } = require('./ToolRegistry');
const { getTaskManager } = require('./TaskManager');
const { getProviderManager } = require('../providers/ProviderManager');
const { getPermissionManager } = require('../permissions/PermissionManager');
const { PromptBuilder } = require('./PromptBuilder');

class Agent extends EventEmitter {
  constructor(options = {}) {
    super();
    this.tools = options.tools || getToolRegistry();
    this.tasks = options.tasks || getTaskManager();
    this.providers = options.providers || getProviderManager();
    this.permissions = options.permissions || getPermissionManager();
  }

  /**
   * Parses tool call blocks from LLM output.
   * Matches ```json { "tool": "...", "parameters": {...} } ```
   */
  extractToolCalls(text) {
    const regex = /```(?:json)?\s*(\{\s*"tool"[\s\S]*?\})\s*```/g;
    const calls = [];
    let match;
    while ((match = regex.exec(text)) !== null) {
      try {
        const parsed = JSON.parse(match[1]);
        if (parsed.tool && parsed.parameters !== undefined) {
          calls.push(parsed);
        }
      } catch {
        // Skip malformed JSON
      }
    }
    return calls;
  }

  /**
   * Executes a full autonomous agent cycle for a user instruction.
   */
  async *runInstruction(instruction, options = {}) {
    const effort = options.effort || 'MEDIUM';
    const conversationId = options.conversationId || 'default-chat';
    const provider = this.providers.getActiveProvider();
    const providerInstance = this.providers.getProviderInstance(provider.id);

    // 1. Create or resume task
    let task;
    if (options.resumeTaskId) {
      task = this.tasks.getTask(options.resumeTaskId);
      if (!task) throw new Error(`Resume task ${options.resumeTaskId} not found`);
      yield { type: 'task_resumed', task };
    } else {
      task = this.tasks.createTask(instruction, effort);
      yield { type: 'task_created', task };
    }

    const taskId = task.id;

    // 2. Initial planning phase
    yield {
      type: 'agent_thought',
      content: `[NEXO ${effort}] Analizando objetivo: "${instruction}"\nProveedor activo: ${provider.name} (${provider.model})`
    };

    let planSteps = [];
    if (effort === 'LOW') {
      planSteps = [
        `Ejecutar consulta o modificación directa para: ${instruction}`
      ];
    } else if (effort === 'MAX') {
      planSteps = [
        'Inspeccionar estructura del repositorio y dependencias',
        'Leer archivos de código fuente pertinentes',
        'Analizar arquitectura e identificar cambios requeridos',
        'Crear o modificar archivos con copias de seguridad de reversión',
        'Ejecutar pruebas del proyecto y verificar registros',
        'Corregir anomalías detectadas en caso de fallo',
        'Verificar limpieza de secretos en Git y estado final'
      ];
    } else {
      // MEDIUM
      planSteps = [
        'Inspeccionar archivos relacionados en el proyecto',
        'Preparar cambios de código requeridos',
        'Verificar el funcionamiento y estado del sistema',
        'Presentar resumen de resultados'
      ];
    }

    this.tasks.setPlan(taskId, planSteps);
    yield {
      type: 'plan_created',
      taskId,
      steps: planSteps
    };

    // 3. Build messages context
    const systemPrompt = PromptBuilder.buildSystemPrompt({
      workspaceRoot: this.permissions.workspaceRoot,
      effort,
      securityMode: this.permissions.mode,
      tools: this.tools.getToolsDefinitions()
    });

    const messages = [
      { role: 'system', content: systemPrompt },
      ...(options.history || []),
      { role: 'user', content: instruction }
    ];

    let maxLoops = effort === 'MAX' ? 10 : effort === 'MEDIUM' ? 6 : 3;
    let loopCount = 0;
    let taskCompleted = false;

    while (loopCount < maxLoops && !taskCompleted) {
      loopCount++;

      let fullResponseText = '';
      let streamGenerator;

      try {
        streamGenerator = providerInstance.chatStream(messages, {
          effort,
          temperature: provider.parameters?.temperature ?? 0.2,
          maxTokens: provider.parameters?.maxTokens ?? 4096
        });
      } catch (err) {
        yield { type: 'error', message: `Error conectando con proveedor: ${err.message}` };
        this.tasks.setTaskStatus(taskId, 'failed', { error: err.message });
        return;
      }

      // Read stream chunks
      for await (const chunk of streamGenerator) {
        if (chunk.type === 'thought') {
          yield { type: 'agent_thought', content: chunk.content };
        } else if (chunk.type === 'content') {
          fullResponseText += chunk.content;
          yield { type: 'content_chunk', content: chunk.content };
        } else if (chunk.type === 'done') {
          yield { type: 'stream_done' };
        }
      }

      // Check for tool calls in response
      const toolCalls = this.extractToolCalls(fullResponseText);

      if (toolCalls.length === 0) {
        // No further tools needed, agent provided final answer
        taskCompleted = true;
        this.tasks.setTaskStatus(taskId, 'completed');
        yield {
          type: 'task_complete',
          taskId,
          summary: fullResponseText.slice(0, 300)
        };
        break;
      }

      // Execute each tool call
      for (const call of toolCalls) {
        this.tasks.incrementToolCalls(taskId);
        yield {
          type: 'tool_call_start',
          tool: call.tool,
          parameters: call.parameters
        };

        if (call.tool === 'read_file' || call.tool === 'list_directory') {
          this.tasks.recordFileAction(taskId, call.parameters.filePath || call.parameters.dirPath || '', 'inspect');
        } else if (call.tool === 'write_file' || call.tool === 'edit_file' || call.tool === 'delete_file') {
          this.tasks.recordFileAction(taskId, call.parameters.filePath || '', 'modify');
        }

        try {
          const toolResult = await this.tools.executeTool(call.tool, call.parameters, {
            approved: options.approved
          });

          // Check if tool resulted in a pending approval
          if (toolResult && toolResult.pendingApproval) {
            this.tasks.setTaskStatus(taskId, 'waiting_approval');
            yield {
              type: 'approval_needed',
              taskId,
              approvalId: toolResult.approvalId,
              tool: call.tool,
              parameters: call.parameters,
              reason: toolResult.reason
            };
            return; // Pause execution until user acts
          }

          yield {
            type: 'tool_call_result',
            tool: call.tool,
            success: true,
            result: toolResult
          };

          // Append tool execution back into message context for next cycle
          messages.push({ role: 'assistant', content: fullResponseText });
          messages.push({
            role: 'user',
            content: `Resultado de la herramienta \`${call.tool}\`:\n\`\`\`json\n${JSON.stringify(toolResult, null, 2)}\n\`\`\`\nContinúa con el siguiente paso.`
          });
        } catch (toolErr) {
          yield {
            type: 'tool_call_result',
            tool: call.tool,
            success: false,
            error: toolErr.message
          };

          // Inform agent of error so it can self-correct
          messages.push({ role: 'assistant', content: fullResponseText });
          messages.push({
            role: 'user',
            content: `La herramienta \`${call.tool}\` falló con el siguiente error: "${toolErr.message}". Por favor, analiza el fallo y propón una corrección.`
          });
        }
      }
    }

    if (!taskCompleted && loopCount >= maxLoops) {
      yield {
        type: 'task_interrupted',
        taskId,
        message: 'Límite de iteraciones alcanzado en este turno. La tarea puede reanudarse.'
      };
      this.tasks.setTaskStatus(taskId, 'interrupted');
    }
  }
}

let instance = null;
function getAgent(options) {
  if (!instance || options) {
    instance = new Agent(options);
  }
  return instance;
}

module.exports = {
  Agent,
  getAgent
};
