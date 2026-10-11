const crypto = require('node:crypto');
const { getStorageManager } = require('../storage/StorageManager');

class TaskManager {
  constructor(storageManager = getStorageManager()) {
    this.storage = storageManager;
  }

  createTask(goal, effort = 'MEDIUM') {
    const task = {
      id: crypto.randomUUID(),
      goal,
      effort,
      status: 'in_progress', // 'in_progress' | 'completed' | 'failed' | 'interrupted' | 'waiting_approval'
      steps: [],
      currentStepIndex: 0,
      filesInspected: [],
      filesModified: [],
      toolCallsCount: 0,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString()
    };

    const tasks = this.storage.read('tasks') || [];
    tasks.unshift(task);
    this.storage.write('tasks', tasks);
    return task;
  }

  setPlan(taskId, stepDescriptions) {
    const tasks = this.storage.read('tasks') || [];
    const task = tasks.find(t => t.id === taskId);
    if (!task) throw new Error(`Task not found: ${taskId}`);

    task.steps = stepDescriptions.map((desc, idx) => ({
      index: idx,
      id: `step-${idx + 1}`,
      description: desc,
      status: idx === 0 ? 'in_progress' : 'pending',
      result: null,
      error: null
    }));
    task.currentStepIndex = 0;
    task.updatedAt = new Date().toISOString();

    this.storage.write('tasks', tasks);
    return task;
  }

  updateStep(taskId, stepIndex, updates) {
    const tasks = this.storage.read('tasks') || [];
    const task = tasks.find(t => t.id === taskId);
    if (!task) return null;

    if (task.steps && task.steps[stepIndex]) {
      task.steps[stepIndex] = {
        ...task.steps[stepIndex],
        ...updates
      };
      if (updates.status === 'completed' && stepIndex + 1 < task.steps.length) {
        task.steps[stepIndex + 1].status = 'in_progress';
        task.currentStepIndex = stepIndex + 1;
      }
    }

    task.updatedAt = new Date().toISOString();
    this.storage.write('tasks', tasks);
    return task;
  }

  recordFileAction(taskId, filePath, actionType = 'inspect') {
    const tasks = this.storage.read('tasks') || [];
    const task = tasks.find(t => t.id === taskId);
    if (!task) return;

    if (actionType === 'modify') {
      if (!task.filesModified.includes(filePath)) task.filesModified.push(filePath);
    } else {
      if (!task.filesInspected.includes(filePath)) task.filesInspected.push(filePath);
    }

    task.updatedAt = new Date().toISOString();
    this.storage.write('tasks', tasks);
  }

  incrementToolCalls(taskId) {
    const tasks = this.storage.read('tasks') || [];
    const task = tasks.find(t => t.id === taskId);
    if (task) {
      task.toolCallsCount = (task.toolCallsCount || 0) + 1;
      task.updatedAt = new Date().toISOString();
      this.storage.write('tasks', tasks);
    }
  }

  setTaskStatus(taskId, status, extra = {}) {
    const tasks = this.storage.read('tasks') || [];
    const task = tasks.find(t => t.id === taskId);
    if (!task) return null;

    task.status = status;
    Object.assign(task, extra);
    task.updatedAt = new Date().toISOString();
    this.storage.write('tasks', tasks);
    return task;
  }

  getTask(taskId) {
    const tasks = this.storage.read('tasks') || [];
    return tasks.find(t => t.id === taskId) || null;
  }

  listTasks(limit = 20) {
    const tasks = this.storage.read('tasks') || [];
    return tasks.slice(0, limit);
  }

  getInterruptedTasks() {
    const tasks = this.storage.read('tasks') || [];
    return tasks.filter(t => t.status === 'interrupted' || t.status === 'in_progress' || t.status === 'waiting_approval');
  }
}

let instance = null;
function getTaskManager(storageManager) {
  if (!instance || storageManager) {
    instance = new TaskManager(storageManager);
  }
  return instance;
}

module.exports = {
  TaskManager,
  getTaskManager
};
