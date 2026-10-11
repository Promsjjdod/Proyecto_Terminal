#!/usr/bin/env node

const { createServer } = require('../src/server');
const { getAgent } = require('../src/core/agent/Agent');
const { getPermissionManager } = require('../src/core/permissions/PermissionManager');
const { getProviderManager } = require('../src/core/providers/ProviderManager');
const { getGitManager } = require('../src/core/git/GitManager');
const { getTerminalManager } = require('../src/core/terminal/TerminalManager');

const args = process.argv.slice(2);
const command = args[0] || 'start';

const GREEN = '\x1b[38;2;0;230;118m';
const RESET = '\x1b[0m';
const CYAN = '\x1b[36m';
const YELLOW = '\x1b[33m';
const RED = '\x1b[31m';
const DIM = '\x1b[2m';
const BOLD = '\x1b[1m';

function printBanner() {
  console.log(`
${GREEN}${BOLD} ███╗   ██╗███████╗██╗  ██╗ ██████╗ 
 ████╗  ██║██╔════╝╚██╗██╔╝██╔═══██╗
 ██╔██╗ ██║█████╗   ╚███╔╝ ██║   ██║
 ██║╚██╗██║██╔══╝   ██╔██╗ ██║   ██║
 ██║ ╚████║███████╗██╔╝ ██╗╚██████╔╝
 ╚═╝  ╚═══╝╚══════╝╚═╝  ╚═╝ ╚═════╝ ${RESET}
 ${CYAN}TERMINAL INTELLIGENCE — AI CODING AGENT FOR TERMUX${RESET}
`);
}

async function handleStatus() {
  printBanner();
  const perms = getPermissionManager();
  const providers = getProviderManager();
  const git = getGitManager();
  const activeProvider = providers.getActiveProvider();
  const gitStatus = await git.getStatus().catch(() => ({ isRepo: false }));

  console.log(`${BOLD}── ESTADO DEL SISTEMA NEXO ──${RESET}`);
  console.log(`Modo de seguridad:   ${GREEN}${perms.mode.toUpperCase()}${RESET}`);
  console.log(`Directorio raíz:     ${CYAN}${perms.workspaceRoot}${RESET}`);
  console.log(`Proveedor activo:    ${BOLD}${activeProvider.name}${RESET} (${activeProvider.model})`);
  console.log(`Repositorio Git:     ${gitStatus.isRepo ? `${GREEN}Activo${RESET} (Rama: ${CYAN}${gitStatus.branch}${RESET}, Modificados: ${gitStatus.modified?.length || 0})` : `${YELLOW}No es repositorio Git${RESET}`}`);
  console.log(`Permisos granulares: Read: ${perms.granular.canReadFiles ? '✓' : '✗'}, Write: ${perms.granular.canWriteFiles ? '✓' : '✗'}, Exec: ${perms.granular.canExecuteCommands ? '✓' : '✗'}, Git: ${perms.granular.canGitOps ? '✓' : '✗'}`);
}

async function handleChat(promptText) {
  if (!promptText) {
    console.error(`${RED}Error: Especifica una instrucción para el agente.${RESET}`);
    console.log(`Uso: nexo chat "Analiza el proyecto y lista los archivos"`);
    process.exit(1);
  }

  printBanner();
  console.log(`${DIM}Iniciando agente con instrucción:${RESET} "${promptText}"\n`);

  const agent = getAgent();
  const stream = agent.runInstruction(promptText, { effort: 'MEDIUM' });

  for await (const evt of stream) {
    if (evt.type === 'agent_thought') {
      console.log(`${CYAN}[PENSAMIENTO]${RESET} ${evt.content}\n`);
    } else if (evt.type === 'plan_created') {
      console.log(`${YELLOW}[PLAN NEXO]${RESET}`);
      evt.steps.forEach((s, idx) => console.log(`  ${idx + 1}. ${s}`));
      console.log('');
    } else if (evt.type === 'tool_call_start') {
      console.log(`${GREEN}[HERRAMIENTA: ${evt.tool}]${RESET} Parámetros: ${JSON.stringify(evt.parameters)}`);
    } else if (evt.type === 'tool_call_result') {
      if (evt.success) {
        console.log(`${GREEN}[✓ RESULTADO]${RESET} Éxito`);
      } else {
        console.log(`${RED}[✗ ERROR HERRAMIENTA]${RESET} ${evt.error}`);
      }
    } else if (evt.type === 'content_chunk') {
      process.stdout.write(evt.content);
    } else if (evt.type === 'task_complete') {
      console.log(`\n\n${GREEN}${BOLD}✔ TAREA FINALIZADA CON ÉXITO${RESET}`);
    } else if (evt.type === 'approval_needed') {
      console.log(`\n${YELLOW}[⚠ APROBACIÓN REQUERIDA] Acción '${evt.tool}' detenida esperando confirmación.${RESET}`);
    }
  }
}

function handleStart() {
  printBanner();
  const PORT = process.env.PORT || 3000;
  const HOST = '0.0.0.0';
  const app = createServer();

  app.listen(PORT, HOST, () => {
    console.log(`${GREEN}${BOLD}✔ Servidor NEXO activo y escuchando:${RESET}`);
    console.log(`  ${BOLD}Red / Host:${RESET}      http://${HOST}:${PORT}`);
    console.log(`  ${BOLD}Termux Local:${RESET}    http://localhost:${PORT}`);
    console.log(`  ${BOLD}Directorio:${RESET}      ${process.cwd()}\n`);
    console.log(`${DIM}Presiona Ctrl+C para detener el servidor.${RESET}\n`);
  });
}

function handleHelp() {
  printBanner();
  console.log(`
${BOLD}COMANDOS DISPONIBLES:${RESET}
  ${GREEN}nexo start${RESET}               Inicia el servidor y la interfaz web en Termux (puerto 3000)
  ${GREEN}nexo status${RESET}              Muestra el estado de seguridad, proveedor y Git
  ${GREEN}nexo chat "<mensaje>"${RESET}    Ejecuta el agente de forma interactiva en la terminal
  ${GREEN}nexo help${RESET}                Muestra esta ayuda
`);
}

// Router
switch (command) {
  case 'start':
  case 'server':
  case 'web':
    handleStart();
    break;
  case 'status':
    handleStatus();
    break;
  case 'chat':
    handleChat(args.slice(1).join(' '));
    break;
  case 'help':
  case '--help':
  case '-h':
    handleHelp();
    break;
  default:
    console.error(`${RED}Comando desconocido: ${command}${RESET}`);
    handleHelp();
    process.exit(1);
}
