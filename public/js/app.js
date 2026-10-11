// NEXO Terminal — Client-Side Application Engine
document.addEventListener('DOMContentLoaded', () => {
  // Global State
  const state = {
    currentView: 'view-agent',
    effort: 'MEDIUM',
    activeProvider: null,
    securityMode: 'approval',
    currentFile: null,
    currentDiff: null,
    abortController: null,
    pendingApproval: null
  };

  // DOM Elements
  const views = document.querySelectorAll('.view-panel');
  const navItems = document.querySelectorAll('.nav-item');
  const agentStatusText = document.getElementById('agent-status-text');
  const currentModeLabel = document.getElementById('current-mode-label');
  const currentProviderLabel = document.getElementById('current-provider-label');
  const activeModelTag = document.getElementById('active-model-tag');
  const workspacePath = document.getElementById('workspace-path');

  // Approval Banner Elements
  const approvalBanner = document.getElementById('pending-approval-banner');
  const bannerActionTitle = document.getElementById('banner-action-title');
  const bannerActionDesc = document.getElementById('banner-action-desc');
  const bannerApproveBtn = document.getElementById('banner-approve-btn');
  const bannerRejectBtn = document.getElementById('banner-reject-btn');
  const bannerViewBtn = document.getElementById('banner-view-btn');

  // Chat Elements
  const chatMessages = document.getElementById('chat-messages');
  const chatForm = document.getElementById('chat-form');
  const chatInput = document.getElementById('chat-input');
  const stopGenBtn = document.getElementById('stop-gen-btn');
  const sendMsgBtn = document.getElementById('send-msg-btn');
  const effortChips = document.querySelectorAll('.effort-chip');
  const taskStepsList = document.getElementById('task-steps-list');
  const taskStatusBadge = document.getElementById('task-status-badge');
  const affectedFilesList = document.getElementById('affected-files-list');

  // Filesystem Elements
  const filesTreeList = document.getElementById('files-tree-list');
  const codeEditorArea = document.getElementById('code-editor-area');
  const previewFileName = document.getElementById('preview-file-name');
  const previewFileDetails = document.getElementById('preview-file-details');
  const saveFileBtn = document.getElementById('save-file-btn');
  const deleteFileBtn = document.getElementById('delete-file-btn');
  const refreshFilesBtn = document.getElementById('refresh-files-btn');
  const newFileBtn = document.getElementById('new-file-btn');
  const newFolderBtn = document.getElementById('new-folder-btn');
  const fsSearchInput = document.getElementById('fs-search-input');
  const fsSearchBtn = document.getElementById('fs-search-btn');

  // Diff Elements
  const diffFileName = document.getElementById('diff-file-name');
  const diffViewport = document.getElementById('diff-viewport');
  const statAdd = document.getElementById('stat-add');
  const statDel = document.getElementById('stat-del');
  const diffConflictAlert = document.getElementById('diff-conflict-alert');
  const diffAcceptBtn = document.getElementById('diff-accept-btn');
  const diffRejectBtn = document.getElementById('diff-reject-btn');
  const diffRollbackBtn = document.getElementById('diff-rollback-btn');
  const diffUnifiedToggle = document.getElementById('diff-unified-toggle');
  const diffSplitToggle = document.getElementById('diff-split-toggle');

  // Terminal Elements
  const terminalOutput = document.getElementById('terminal-output');
  const terminalForm = document.getElementById('terminal-form');
  const terminalCmdInput = document.getElementById('terminal-cmd-input');
  const activeProcessesBadge = document.getElementById('active-processes-badge');
  const clearTermBtn = document.getElementById('clear-term-btn');
  const killProcessBtn = document.getElementById('kill-process-btn');

  // Git & GitHub Elements
  const gitCurrentBranch = document.getElementById('git-current-branch');
  const gitSyncStatus = document.getElementById('git-sync-status');
  const gitChangesList = document.getElementById('git-changes-list');
  const gitLogList = document.getElementById('git-log-list');
  const gitRefreshBtn = document.getElementById('git-refresh-btn');
  const gitStageAllBtn = document.getElementById('git-stage-all-btn');
  const gitCommitMsg = document.getElementById('git-commit-msg');
  const gitCommitBtn = document.getElementById('git-commit-btn');
  const gitNewBranchBtn = document.getElementById('git-new-branch-btn');
  const githubPushBtn = document.getElementById('github-push-btn');

  // Security Elements
  const secModeRadios = document.querySelectorAll('input[name="sec-mode"]');
  const granularSwitchesList = document.getElementById('granular-switches-list');
  const auditLogsList = document.getElementById('audit-logs-list');

  // Settings & Modals
  const providersList = document.getElementById('providers-list');
  const openSettingsBtn = document.getElementById('open-settings-btn');
  const quickModeBtn = document.getElementById('quick-mode-btn');
  const quickProviderBtn = document.getElementById('quick-provider-btn');
  const addProviderBtn = document.getElementById('add-provider-btn');
  const providerModal = document.getElementById('provider-modal');
  const closeProviderModal = document.getElementById('close-provider-modal');
  const providerForm = document.getElementById('provider-form');
  const testModalProviderBtn = document.getElementById('test-modal-provider-btn');
  const githubModal = document.getElementById('github-push-modal');
  const closeGithubModal = document.getElementById('close-github-modal');
  const cancelPushBtn = document.getElementById('cancel-push-btn');
  const confirmPushBtn = document.getElementById('confirm-push-btn');
  const pushSummaryContent = document.getElementById('push-summary-content');
  const pushSecretWarning = document.getElementById('push-secret-warning');

  // -------------------------------------------------------------
  // 1. Navigation Controller
  // -------------------------------------------------------------
  function switchView(targetViewId) {
    state.currentView = targetViewId;
    views.forEach(v => {
      v.classList.toggle('active', v.id === targetViewId);
    });

    navItems.forEach(n => {
      n.classList.toggle('active', n.dataset.view === targetViewId);
    });

    if (targetViewId === 'view-files') loadFilesTree();
    if (targetViewId === 'view-git') loadGitStatus();
    if (targetViewId === 'view-security') loadSecuritySettings();
    if (targetViewId === 'view-settings') loadProviders();
  }

  navItems.forEach(item => {
    item.addEventListener('click', () => {
      switchView(item.dataset.view);
    });
  });

  openSettingsBtn.addEventListener('click', () => switchView('view-settings'));
  quickModeBtn.addEventListener('click', () => switchView('view-security'));
  quickProviderBtn.addEventListener('click', () => switchView('view-settings'));

  // -------------------------------------------------------------
  // 2. Initial Status & Setup
  // -------------------------------------------------------------
  async function fetchStatus() {
    try {
      const res = await fetch('/api/status');
      const data = await res.json();
      if (data.ok) {
        state.activeProvider = data.activeProvider;
        state.securityMode = data.permissions.mode;

        currentProviderLabel.textContent = data.activeProvider?.name || 'Local';
        activeModelTag.textContent = data.activeProvider?.model || 'nexo-codex-v1';
        currentModeLabel.textContent = data.permissions.mode.toUpperCase();
        workspacePath.textContent = data.permissions.workspaceRoot.split('/').pop() || '/workspace';

        if (data.permissions.pendingApprovalsCount > 0) {
          checkPendingApprovals();
        }
      }
    } catch (err) {
      console.warn('Status poll failed:', err);
    }
  }

  // -------------------------------------------------------------
  // 3. Agent Chat & Streaming Controller
  // -------------------------------------------------------------
  effortChips.forEach(chip => {
    chip.addEventListener('click', () => {
      effortChips.forEach(c => c.classList.remove('active'));
      chip.classList.add('active');
      state.effort = chip.dataset.effort;
    });
  });

  // Prompt chips
  document.querySelectorAll('.chip[data-prompt]').forEach(chip => {
    chip.addEventListener('click', () => {
      chatInput.value = chip.dataset.prompt;
      chatForm.dispatchEvent(new Event('submit'));
    });
  });

  chatForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const prompt = chatInput.value.trim();
    if (!prompt) return;

    chatInput.value = '';
    appendUserMessage(prompt);
    startAgentStream(prompt);
  });

  function appendUserMessage(text) {
    const msg = document.createElement('div');
    msg.className = 'message user';
    msg.innerHTML = `
      <div class="message-header">
        <span class="message-author">TÚ</span>
        <span class="message-time">${new Date().toLocaleTimeString()}</span>
      </div>
      <div class="message-body">${escapeHtml(text)}</div>
    `;
    chatMessages.appendChild(msg);
    chatMessages.scrollTop = chatMessages.scrollHeight;
  }

  async function startAgentStream(instruction, options = {}) {
    state.abortController = new AbortController();
    stopGenBtn.classList.remove('hidden');
    agentStatusText.textContent = 'PENSANDO...';

    // Prepare assistant message bubble
    const assistantMsg = document.createElement('div');
    assistantMsg.className = 'message assistant';
    assistantMsg.innerHTML = `
      <div class="message-header">
        <span class="message-author">NEXO TERMINAL</span>
        <span class="message-time">${new Date().toLocaleTimeString()}</span>
      </div>
      <div class="message-body">
        <div class="thought-container"></div>
        <div class="tools-container"></div>
        <div class="text-content"></div>
      </div>
    `;
    chatMessages.appendChild(assistantMsg);
    chatMessages.scrollTop = chatMessages.scrollHeight;

    const thoughtContainer = assistantMsg.querySelector('.thought-container');
    const toolsContainer = assistantMsg.querySelector('.tools-container');
    const textContent = assistantMsg.querySelector('.text-content');

    let currentToolCard = null;

    try {
      const response = await fetch('/api/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          instruction,
          effort: state.effort,
          approved: options.approved,
          resumeTaskId: options.resumeTaskId
        }),
        signal: state.abortController.signal
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const events = buffer.split('\n\n');
        buffer = events.pop() || '';

        for (const evtBlock of events) {
          const lines = evtBlock.split('\n');
          let eventType = '';
          let dataStr = '';

          for (const line of lines) {
            if (line.startsWith('event:')) eventType = line.slice(6).trim();
            if (line.startsWith('data:')) dataStr = line.slice(5).trim();
          }

          if (!dataStr) continue;

          try {
            const data = JSON.parse(dataStr);
            handleAgentEvent(eventType, data, {
              thoughtContainer,
              toolsContainer,
              textContent,
              getCurrentToolCard: () => currentToolCard,
              setCurrentToolCard: (c) => { currentToolCard = c; }
            });
          } catch {
            // Parse error on stream event
          }
        }
      }
    } catch (err) {
      if (err.name === 'AbortError') {
        textContent.innerHTML += `<p class="text-dim"><em>[Generación cancelada por el usuario]</em></p>`;
      } else {
        textContent.innerHTML += `<p class="text-danger"><strong>Error del agente:</strong> ${escapeHtml(err.message)}</p>`;
      }
    } finally {
      stopGenBtn.classList.add('hidden');
      agentStatusText.textContent = 'LISTO';
      state.abortController = null;
      chatMessages.scrollTop = chatMessages.scrollHeight;
    }
  }

  function handleAgentEvent(eventType, data, ui) {
    if (eventType === 'agent_thought') {
      let box = ui.thoughtContainer.querySelector('.thought-box');
      if (!box) {
        box = document.createElement('div');
        box.className = 'thought-box';
        box.innerHTML = `<div class="thought-header">🧠 Razonamiento NEXO</div><div class="thought-text"></div>`;
        ui.thoughtContainer.appendChild(box);
      }
      box.querySelector('.thought-text').textContent += data.content + '\n';
    } else if (eventType === 'plan_created') {
      taskStatusBadge.textContent = 'En progreso';
      taskStatusBadge.className = 'badge text-success';
      taskStepsList.innerHTML = '';
      data.steps.forEach((s, idx) => {
        const card = document.createElement('div');
        card.className = `step-card ${idx === 0 ? 'in_progress' : ''}`;
        card.id = `sidebar-step-${idx}`;
        card.innerHTML = `
          <div class="step-status-row">
            <span class="font-bold">Paso ${idx + 1}</span>
            <span class="step-badge text-dim">${idx === 0 ? 'En curso' : 'Pendiente'}</span>
          </div>
          <span>${escapeHtml(s)}</span>
        `;
        taskStepsList.appendChild(card);
      });
    } else if (eventType === 'tool_call_start') {
      agentStatusText.textContent = 'EJECUTANDO HERRAMIENTA...';
      const card = document.createElement('div');
      card.className = 'tool-card';
      card.innerHTML = `
        <div class="tool-header">
          <span>⚙ ${escapeHtml(data.tool)}</span>
          <span class="tool-status text-dim">Ejecutando...</span>
        </div>
        <div class="tool-body">${escapeHtml(JSON.stringify(data.parameters, null, 2))}</div>
      `;
      ui.toolsContainer.appendChild(card);
      ui.setCurrentToolCard(card);
    } else if (eventType === 'tool_call_result') {
      const card = ui.getCurrentToolCard();
      if (card) {
        const statusSpan = card.querySelector('.tool-status');
        if (data.success) {
          statusSpan.textContent = '✔ Éxito';
          statusSpan.className = 'tool-status text-success';
        } else {
          statusSpan.textContent = '✘ Error';
          statusSpan.className = 'tool-status text-danger';
        }
      }
    } else if (eventType === 'approval_needed') {
      agentStatusText.textContent = 'APROBACIÓN REQUERIDA';
      showApprovalBanner(data);
    } else if (eventType === 'content_chunk') {
      ui.textContent.innerHTML += escapeHtml(data.content);
    } else if (eventType === 'task_complete') {
      taskStatusBadge.textContent = 'Completada';
      taskStatusBadge.className = 'badge text-success';
      agentStatusText.textContent = 'LISTO';
    }
    chatMessages.scrollTop = chatMessages.scrollHeight;
  }

  stopGenBtn.addEventListener('click', () => {
    if (state.abortController) {
      state.abortController.abort();
    }
  });

  // -------------------------------------------------------------
  // 4. Approval Banner Controller
  // -------------------------------------------------------------
  function showApprovalBanner(approval) {
    state.pendingApproval = approval;
    approvalBanner.classList.remove('hidden');
    bannerActionTitle.textContent = `Aprobación requerida: ${approval.tool || approval.action}`;
    bannerActionDesc.textContent = approval.reason || 'El agente solicita permiso para realizar una acción de modificación.';
  }

  function hideApprovalBanner() {
    approvalBanner.classList.add('hidden');
    state.pendingApproval = null;
  }

  bannerApproveBtn.addEventListener('click', async () => {
    if (!state.pendingApproval) return;
    const approvalId = state.pendingApproval.approvalId || state.pendingApproval.id;
    try {
      await fetch(`/api/permissions/approvals/${approvalId}/approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({})
      });
      hideApprovalBanner();
      // Resume task if agent was paused
      if (state.pendingApproval.taskId) {
        startAgentStream('', { resumeTaskId: state.pendingApproval.taskId, approved: true });
      }
    } catch (err) {
      alert(`Error al aprobar: ${err.message}`);
    }
  });

  bannerRejectBtn.addEventListener('click', async () => {
    if (!state.pendingApproval) return;
    const approvalId = state.pendingApproval.approvalId || state.pendingApproval.id;
    try {
      await fetch(`/api/permissions/approvals/${approvalId}/reject`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason: 'Rechazado por el usuario' })
      });
      hideApprovalBanner();
    } catch (err) {
      alert(`Error al rechazar: ${err.message}`);
    }
  });

  bannerViewBtn.addEventListener('click', () => {
    if (state.pendingApproval?.details?.content) {
      // Show proposed diff
      showDiffPreview(state.pendingApproval.details.path, state.pendingApproval.details.content);
      switchView('view-diff');
    } else {
      switchView('view-security');
    }
  });

  async function checkPendingApprovals() {
    try {
      const res = await fetch('/api/permissions/approvals');
      const data = await res.json();
      if (data.ok && data.approvals.length > 0) {
        showApprovalBanner(data.approvals[0]);
      }
    } catch {}
  }

  // -------------------------------------------------------------
  // 5. Filesystem Controller
  // -------------------------------------------------------------
  async function loadFilesTree(dir = '') {
    try {
      const res = await fetch(`/api/fs/tree?dir=${encodeURIComponent(dir)}`);
      const data = await res.json();
      if (data.ok) {
        renderFilesTree(data.entries);
      }
    } catch (err) {
      filesTreeList.innerHTML = `<div class="empty-state text-danger">Error: ${err.message}</div>`;
    }
  }

  function renderFilesTree(entries) {
    filesTreeList.innerHTML = '';
    if (!entries.length) {
      filesTreeList.innerHTML = `<div class="empty-state">Carpeta vacía</div>`;
      return;
    }

    entries.forEach(entry => {
      const item = document.createElement('div');
      item.className = 'tree-item';
      item.innerHTML = `
        <span class="tree-icon">${entry.isDirectory ? '📁' : '📄'}</span>
        <span class="tree-name">${escapeHtml(entry.name)}</span>
      `;

      item.addEventListener('click', () => {
        document.querySelectorAll('.tree-item').forEach(i => i.classList.remove('active'));
        item.classList.add('active');

        if (entry.isDirectory) {
          loadFilesTree(entry.relativePath);
        } else {
          loadFileContent(entry.relativePath);
        }
      });

      filesTreeList.appendChild(item);
    });
  }

  async function loadFileContent(filePath) {
    try {
      const res = await fetch(`/api/fs/read?path=${encodeURIComponent(filePath)}`);
      const data = await res.json();
      if (data.ok) {
        state.currentFile = data;
        previewFileName.textContent = data.relativePath;
        previewFileDetails.textContent = `${data.size} bytes | ${data.totalLines || 0} líneas`;
        codeEditorArea.value = data.content || '';
      }
    } catch (err) {
      alert(`Error al leer archivo: ${err.message}`);
    }
  }

  saveFileBtn.addEventListener('click', async () => {
    if (!state.currentFile) return;
    const content = codeEditorArea.value;
    try {
      const res = await fetch('/api/fs/write', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: state.currentFile.relativePath, content })
      });
      const data = await res.json();
      if (data.ok) {
        if (data.result?.pendingApproval) {
          showApprovalBanner(data.result);
        } else {
          alert('✔ Archivo guardado correctamente con copia de seguridad.');
        }
      }
    } catch (err) {
      alert(`Error al guardar: ${err.message}`);
    }
  });

  deleteFileBtn.addEventListener('click', async () => {
    if (!state.currentFile) return;
    if (!confirm(`¿Eliminar definitivamente '${state.currentFile.relativePath}'? Se creará una copia de seguridad.`)) return;

    try {
      const res = await fetch('/api/fs/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: state.currentFile.relativePath })
      });
      const data = await res.json();
      if (data.ok) {
        alert('✔ Archivo eliminado.');
        state.currentFile = null;
        codeEditorArea.value = '';
        previewFileName.textContent = 'Ningún archivo seleccionado';
        loadFilesTree();
      }
    } catch (err) {
      alert(`Error al eliminar: ${err.message}`);
    }
  });

  refreshFilesBtn.addEventListener('click', () => loadFilesTree());

  newFileBtn.addEventListener('click', async () => {
    const filename = prompt('Nombre del nuevo archivo (ej. index.js):');
    if (!filename) return;
    try {
      await fetch('/api/fs/write', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: filename, content: '// Creado en NEXO\n' })
      });
      loadFilesTree();
      loadFileContent(filename);
    } catch (err) {
      alert(`Error: ${err.message}`);
    }
  });

  newFolderBtn.addEventListener('click', async () => {
    const foldername = prompt('Nombre de la nueva carpeta:');
    if (!foldername) return;
    try {
      await fetch('/api/fs/mkdir', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: foldername })
      });
      loadFilesTree();
    } catch (err) {
      alert(`Error: ${err.message}`);
    }
  });

  fsSearchBtn.addEventListener('click', async () => {
    const query = fsSearchInput.value.trim();
    if (!query) return;
    try {
      const res = await fetch(`/api/fs/search?q=${encodeURIComponent(query)}`);
      const data = await res.json();
      if (data.ok) {
        renderSearchResults(data.results);
      }
    } catch (err) {
      alert(`Error al buscar: ${err.message}`);
    }
  });

  function renderSearchResults(results) {
    filesTreeList.innerHTML = `<div class="panel-heading" style="padding: 8px 14px;">Resultados (${results.count})</div>`;
    results.matches.forEach(m => {
      const item = document.createElement('div');
      item.className = 'tree-item';
      item.innerHTML = `
        <span class="tree-icon">🔍</span>
        <div style="display:flex; flex-direction:column; overflow:hidden;">
          <span class="font-bold">${escapeHtml(m.relativePath)}:${m.line}</span>
          <span class="text-dim" style="font-size:10.5px;">${escapeHtml(m.content)}</span>
        </div>
      `;
      item.addEventListener('click', () => loadFileContent(m.relativePath));
      filesTreeList.appendChild(item);
    });
  }

  // -------------------------------------------------------------
  // 6. Diff Engine & Version Review Controller
  // -------------------------------------------------------------
  async function showDiffPreview(filePath, proposedContent) {
    try {
      const res = await fetch('/api/diff/file', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: filePath, proposedContent })
      });
      const data = await res.json();
      if (data.ok) {
        state.currentDiff = {
          filePath,
          proposedContent,
          diff: data.diff
        };
        diffFileName.textContent = filePath;
        statAdd.textContent = `+${data.diff.additions}`;
        statDel.textContent = `-${data.diff.deletions}`;

        if (data.conflict?.hasConflict) {
          diffConflictAlert.classList.remove('hidden');
        } else {
          diffConflictAlert.classList.add('hidden');
        }

        renderDiffHunks(data.diff.hunks);
      }
    } catch (err) {
      alert(`Error al calcular diferencias: ${err.message}`);
    }
  }

  function renderDiffHunks(hunks) {
    diffViewport.innerHTML = '';
    if (!hunks || !hunks.length) {
      diffViewport.innerHTML = `<div class="empty-state">No se detectaron cambios entre versiones.</div>`;
      return;
    }

    hunks.forEach(hunk => {
      const block = document.createElement('div');
      block.className = 'hunk-block';
      block.innerHTML = `<div class="hunk-header">${escapeHtml(hunk.header)}</div>`;

      hunk.lines.forEach(l => {
        const lineEl = document.createElement('div');
        lineEl.className = `diff-line ${l.type}`;
        lineEl.innerHTML = `
          <span class="diff-gutter">${l.type === 'add' ? '+' : l.oldLine || ''}</span>
          <span class="diff-prefix">${l.prefix}</span>
          <span class="diff-content">${escapeHtml(l.text)}</span>
        `;
        block.appendChild(lineEl);
      });

      diffViewport.appendChild(block);
    });
  }

  diffAcceptBtn.addEventListener('click', async () => {
    if (!state.currentDiff) return;
    try {
      const res = await fetch('/api/fs/write', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          path: state.currentDiff.filePath,
          content: state.currentDiff.proposedContent,
          approved: true
        })
      });
      const data = await res.json();
      if (data.ok) {
        alert('✔ Cambios aceptados y aplicados correctamente.');
        state.currentDiff = null;
        diffViewport.innerHTML = `<div class="empty-state">Cambios aplicados con éxito.</div>`;
        diffFileName.textContent = 'Sin propuesta activa';
      }
    } catch (err) {
      alert(`Error al aplicar cambios: ${err.message}`);
    }
  });

  diffRejectBtn.addEventListener('click', () => {
    if (!state.currentDiff) return;
    if (confirm('¿Descartar esta propuesta de cambios?')) {
      state.currentDiff = null;
      diffViewport.innerHTML = `<div class="empty-state">Propuesta descartada.</div>`;
      diffFileName.textContent = 'Sin propuesta activa';
    }
  });

  diffRollbackBtn.addEventListener('click', async () => {
    if (!state.currentFile) {
      alert('Selecciona primero un archivo en el Explorador para ver sus copias de seguridad de reversión.');
      return;
    }
    try {
      const res = await fetch(`/api/backups?path=${encodeURIComponent(state.currentFile.relativePath)}`);
      const data = await res.json();
      if (data.ok && data.backups.length > 0) {
        const latest = data.backups[0];
        if (confirm(`¿Revertir '${state.currentFile.relativePath}' a la copia del ${new Date(latest.timestamp).toLocaleString()}?`)) {
          const rollRes = await fetch(`/api/backups/${latest.id}/rollback`, { method: 'POST' });
          const rollData = await rollRes.json();
          if (rollData.ok) {
            alert('✔ Archivo revertido a su versión anterior.');
            loadFileContent(state.currentFile.relativePath);
          }
        }
      } else {
        alert('No se encontraron copias de seguridad previas para este archivo.');
      }
    } catch (err) {
      alert(`Error al revertir: ${err.message}`);
    }
  });

  // -------------------------------------------------------------
  // 7. Terminal & Command Runner Controller
  // -------------------------------------------------------------
  terminalForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const cmd = terminalCmdInput.value.trim();
    if (!cmd) return;

    terminalCmdInput.value = '';
    appendTerminalLine(`user@nexo:~$ ${cmd}`, 'cmd-line');

    try {
      const res = await fetch('/api/terminal/exec', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ command: cmd })
      });
      const data = await res.json();
      if (data.ok) {
        if (data.pendingApproval) {
          appendTerminalLine(`[⚠ APROBACIÓN REQUERIDA] Acción '${cmd}' detenida esperando autorización.`, 'err-line');
          showApprovalBanner(data);
        } else if (data.result) {
          if (data.result.stdout) appendTerminalLine(data.result.stdout);
          if (data.result.stderr) appendTerminalLine(data.result.stderr, 'err-line');
          appendTerminalLine(`[Proceso finalizado. Código de salida: ${data.result.exitCode} (${data.result.durationMs}ms)]`, 'info-line');
        }
      } else {
        appendTerminalLine(`[ERROR]: ${data.error}`, 'err-line');
      }
    } catch (err) {
      appendTerminalLine(`[ERROR DE CONEXIÓN]: ${err.message}`, 'err-line');
    }
  });

  function appendTerminalLine(text, className = '') {
    const line = document.createElement('div');
    line.className = `term-line ${className}`;
    line.textContent = text;
    terminalOutput.appendChild(line);
    terminalOutput.scrollTop = terminalOutput.scrollHeight;
  }

  clearTermBtn.addEventListener('click', () => {
    terminalOutput.innerHTML = '';
  });

  killProcessBtn.addEventListener('click', async () => {
    try {
      const res = await fetch('/api/terminal/processes');
      const data = await res.json();
      if (data.ok && data.processes.length > 0) {
        const proc = data.processes[0];
        await fetch('/api/terminal/kill', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ processId: proc.id, signal: 'SIGTERM' })
        });
        appendTerminalLine(`[Señal SIGTERM enviada al proceso PID ${proc.pid}]`, 'info-line');
      } else {
        alert('No hay procesos en segundo plano ejecutándose actualmente.');
      }
    } catch (err) {
      alert(`Error: ${err.message}`);
    }
  });

  // -------------------------------------------------------------
  // 8. Git & GitHub Controller
  // -------------------------------------------------------------
  async function loadGitStatus() {
    try {
      const res = await fetch('/api/git/status');
      const data = await res.json();
      if (data.ok) {
        renderGitStatus(data.status);
      }
      loadGitLog();
    } catch (err) {
      gitChangesList.innerHTML = `<div class="empty-state text-danger">${err.message}</div>`;
    }
  }

  function renderGitStatus(status) {
    gitCurrentBranch.textContent = status.branch || 'desconocida';
    gitSyncStatus.textContent = status.ahead ? `+${status.ahead} por subir` : 'Sincronizado';

    gitChangesList.innerHTML = '';
    const allChanges = [
      ...status.staged.map(s => ({ ...s, isStaged: true })),
      ...status.modified.map(m => ({ ...m, isStaged: false })),
      ...status.untracked.map(u => ({ path: u, status: '?', isStaged: false }))
    ];

    if (!allChanges.length) {
      gitChangesList.innerHTML = `<div class="empty-state">Árbol de trabajo limpio. No hay cambios pendientes.</div>`;
      return;
    }

    allChanges.forEach(item => {
      const row = document.createElement('div');
      row.className = 'tree-item';
      row.innerHTML = `
        <span class="font-bold ${item.isStaged ? 'text-success' : 'text-danger'}">${item.status}</span>
        <span class="diff-file-tag">${escapeHtml(item.path)}</span>
      `;
      gitChangesList.appendChild(row);
    });
  }

  async function loadGitLog() {
    try {
      const res = await fetch('/api/git/log?limit=8');
      const data = await res.json();
      if (data.ok) {
        gitLogList.innerHTML = '';
        data.commits.forEach(c => {
          const item = document.createElement('div');
          item.className = 'commit-item';
          item.innerHTML = `
            <div class="commit-meta">
              <span class="commit-hash">${c.shortHash}</span>
              <span>${escapeHtml(c.author)} • ${c.relativeDate}</span>
            </div>
            <div class="font-bold" style="font-size:12px;">${escapeHtml(c.message)}</div>
          `;
          gitLogList.appendChild(item);
        });
      }
    } catch {}
  }

  gitRefreshBtn.addEventListener('click', () => loadGitStatus());

  gitStageAllBtn.addEventListener('click', async () => {
    try {
      await fetch('/api/git/stage', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ files: ['.'] })
      });
      loadGitStatus();
    } catch (err) {
      alert(`Error: ${err.message}`);
    }
  });

  gitCommitBtn.addEventListener('click', async () => {
    const msg = gitCommitMsg.value.trim();
    if (!msg) {
      alert('Ingresa un mensaje para el commit');
      return;
    }

    try {
      const res = await fetch('/api/git/commit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: msg, checkSecrets: true })
      });
      const data = await res.json();
      if (data.ok) {
        alert('✔ Commit creado con éxito. Escáner de secretos validado.');
        gitCommitMsg.value = '';
        loadGitStatus();
      } else {
        alert(`Error al crear commit: ${data.error}`);
      }
    } catch (err) {
      alert(`Error: ${err.message}`);
    }
  });

  gitNewBranchBtn.addEventListener('click', async () => {
    const branchName = prompt('Nombre de la nueva rama:');
    if (!branchName) return;
    try {
      await fetch('/api/git/branches', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: branchName })
      });
      loadGitStatus();
    } catch (err) {
      alert(`Error: ${err.message}`);
    }
  });

  githubPushBtn.addEventListener('click', async () => {
    try {
      const res = await fetch('/api/github/summary');
      const data = await res.json();
      if (data.ok) {
        showGitHubPushModal(data.summary);
      }
    } catch (err) {
      alert(`Error al consultar GitHub: ${err.message}`);
    }
  });

  function showGitHubPushModal(summary) {
    githubModal.classList.remove('hidden');
    pushSummaryContent.innerHTML = `
      <div style="font-family:var(--font-mono); font-size:12px; line-height:1.6;">
        <div><strong>Destino:</strong> ${summary.remote} / ${summary.branch}</div>
        <div><strong>Commits por subir:</strong> ${summary.ahead}</div>
        <div><strong>Archivos preparados:</strong> ${summary.stagedCount}</div>
      </div>
    `;

    if (summary.hasSecretFindings) {
      pushSecretWarning.classList.remove('hidden');
      confirmPushBtn.disabled = true;
    } else {
      pushSecretWarning.classList.add('hidden');
      confirmPushBtn.disabled = false;
    }
  }

  closeGithubModal.addEventListener('click', () => githubModal.classList.add('hidden'));
  cancelPushBtn.addEventListener('click', () => githubModal.classList.add('hidden'));

  confirmPushBtn.addEventListener('click', async () => {
    try {
      const res = await fetch('/api/github/push', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ approved: true })
      });
      const data = await res.json();
      if (data.ok) {
        alert('✔ Cambios publicados en GitHub correctamente.');
        githubModal.classList.add('hidden');
        loadGitStatus();
      } else {
        alert(`Error al publicar: ${data.error}`);
      }
    } catch (err) {
      alert(`Error al publicar: ${err.message}`);
    }
  });

  // -------------------------------------------------------------
  // 9. Security & Settings Controller
  // -------------------------------------------------------------
  async function loadSecuritySettings() {
    try {
      const res = await fetch('/api/permissions');
      const data = await res.json();
      if (data.ok) {
        renderSecuritySettings(data.status);
      }
      loadAuditLogs();
    } catch {}
  }

  function renderSecuritySettings(status) {
    secModeRadios.forEach(radio => {
      radio.checked = radio.value === status.mode;
    });

    granularSwitchesList.innerHTML = '';
    const flagLabels = {
      canReadFiles: 'Lectura de archivos',
      canWriteFiles: 'Creación y escritura de archivos',
      canDeleteFiles: 'Eliminación de archivos',
      canExecuteCommands: 'Ejecución de comandos',
      canInstallPackages: 'Instalación de paquetes',
      canAccessNetwork: 'Acceso a la red',
      canGitOps: 'Operaciones Git',
      canGitHubPublish: 'Publicación en GitHub'
    };

    for (const [key, val] of Object.entries(status.granular)) {
      const label = document.createElement('label');
      label.className = 'switch-label';
      label.innerHTML = `
        <span>${flagLabels[key] || key}</span>
        <input type="checkbox" data-flag="${key}" ${val ? 'checked' : ''}>
      `;
      label.querySelector('input').addEventListener('change', async (e) => {
        const update = { [key]: e.target.checked };
        await fetch('/api/permissions/granular', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(update)
        });
      });
      granularSwitchesList.appendChild(label);
    }
  }

  secModeRadios.forEach(radio => {
    radio.addEventListener('change', async () => {
      try {
        await fetch('/api/permissions/mode', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ mode: radio.value })
        });
        currentModeLabel.textContent = radio.value.toUpperCase();
      } catch (err) {
        alert(`Error: ${err.message}`);
      }
    });
  });

  async function loadAuditLogs() {
    try {
      const res = await fetch('/api/permissions/audit?limit=25');
      const data = await res.json();
      if (data.ok) {
        auditLogsList.innerHTML = '';
        data.logs.forEach(l => {
          const item = document.createElement('div');
          item.className = 'audit-item';
          item.innerHTML = `
            <span>[${new Date(l.timestamp).toLocaleTimeString()}] <strong>${escapeHtml(l.action)}</strong></span>
            <span class="${l.status === 'success' ? 'text-success' : 'text-danger'}">${l.status}</span>
          `;
          auditLogsList.appendChild(item);
        });
      }
    } catch {}
  }

  // -------------------------------------------------------------
  // 10. Providers Configuration Controller
  // -------------------------------------------------------------
  async function loadProviders() {
    try {
      const res = await fetch('/api/providers');
      const data = await res.json();
      if (data.ok) {
        renderProvidersList(data.providers);
      }
    } catch {}
  }

  function renderProvidersList(providers) {
    providersList.innerHTML = '';
    providers.forEach(p => {
      const row = document.createElement('div');
      row.className = `provider-row ${p.active ? 'active' : ''}`;
      row.innerHTML = `
        <div class="provider-info">
          <div style="display:flex; align-items:center; gap:8px;">
            <span class="provider-name">${escapeHtml(p.name)}</span>
            ${p.active ? '<span class="badge text-success">ACTIVO</span>' : ''}
          </div>
          <span class="provider-meta">${escapeHtml(p.type)} • ${escapeHtml(p.model)} • ${escapeHtml(p.baseUrl)}</span>
        </div>
        <div class="provider-row-actions">
          <button class="btn btn-sm btn-outline test-prov-btn" data-id="${p.id}">Probar</button>
          ${!p.active ? `<button class="btn btn-sm btn-primary activate-prov-btn" data-id="${p.id}">Activar</button>` : ''}
          ${p.id !== 'builtin-mock' ? `<button class="btn btn-sm btn-outline text-danger del-prov-btn" data-id="${p.id}">Eliminar</button>` : ''}
        </div>
      `;

      row.querySelector('.test-prov-btn').addEventListener('click', async () => {
        try {
          const res = await fetch(`/api/providers/${p.id}/test`, { method: 'POST' });
          const testData = await res.json();
          if (testData.result?.success) {
            alert(`✔ Conexión exitosa con ${p.name} (${testData.result.latencyMs}ms)`);
          } else {
            alert(`✘ Error al conectar: ${testData.result?.message}`);
          }
        } catch (err) {
          alert(`Error: ${err.message}`);
        }
      });

      const actBtn = row.querySelector('.activate-prov-btn');
      if (actBtn) {
        actBtn.addEventListener('click', async () => {
          await fetch(`/api/providers/${p.id}/activate`, { method: 'POST' });
          fetchStatus();
          loadProviders();
        });
      }

      const delBtn = row.querySelector('.del-prov-btn');
      if (delBtn) {
        delBtn.addEventListener('click', async () => {
          if (confirm(`¿Eliminar configuración de ${p.name}?`)) {
            await fetch(`/api/providers/${p.id}`, { method: 'DELETE' });
            loadProviders();
          }
        });
      }

      providersList.appendChild(row);
    });
  }

  addProviderBtn.addEventListener('click', () => {
    providerModal.classList.remove('hidden');
  });

  closeProviderModal.addEventListener('click', () => {
    providerModal.classList.add('hidden');
  });

  providerForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const payload = {
      name: document.getElementById('provider-name-input').value.trim(),
      type: document.getElementById('provider-type-input').value,
      baseUrl: document.getElementById('provider-url-input').value.trim(),
      apiKey: document.getElementById('provider-key-input').value.trim(),
      model: document.getElementById('provider-model-input').value.trim(),
      active: true
    };

    try {
      const res = await fetch('/api/providers', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (data.ok) {
        providerModal.classList.add('hidden');
        providerForm.reset();
        loadProviders();
        fetchStatus();
      }
    } catch (err) {
      alert(`Error al guardar proveedor: ${err.message}`);
    }
  });

  // Utility
  function escapeHtml(str) {
    if (typeof str !== 'string') return '';
    return str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  // Initial Run
  fetchStatus();
  loadFilesTree();
});
