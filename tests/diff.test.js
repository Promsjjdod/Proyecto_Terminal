const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const { DiffEngine } = require('../src/core/diff/DiffEngine');

test('DiffEngine: Computes additions (+), deletions (-), and unified hunks', () => {
  const oldText = 'const a = 1;\nconsole.log("versión anterior");\nconst b = 2;';
  const newText = 'const a = 1;\nconsole.log("versión nueva");\nconst b = 2;\nconst c = 3;';

  const diff = DiffEngine.computeDiff(oldText, newText);

  assert.strictEqual(diff.hasChanges, true);
  assert.strictEqual(diff.deletions, 1, 'Should have 1 deletion (- console.log("versión anterior"))');
  assert.strictEqual(diff.additions, 2, 'Should have 2 additions (+ console.log("versión nueva") and + const c = 3)');
  assert.strictEqual(diff.totalChanges, 3);

  // Check hunks
  assert.ok(diff.hunks.length > 0);
  const firstHunk = diff.hunks[0];
  assert.ok(firstHunk.header.startsWith('@@'));

  const deletedLine = firstHunk.lines.find(l => l.type === 'delete');
  assert.ok(deletedLine);
  assert.strictEqual(deletedLine.prefix, '-');
  assert.ok(deletedLine.text.includes('versión anterior'));

  const addedLine = firstHunk.lines.find(l => l.type === 'add');
  assert.ok(addedLine);
  assert.strictEqual(addedLine.prefix, '+');
  assert.ok(addedLine.text.includes('versión nueva'));
});

test('DiffEngine: Split view produces left and right columns', () => {
  const oldText = 'alpha\nbeta\ngamma';
  const newText = 'alpha\nbeta_mod\ngamma\ndelta';

  const diff = DiffEngine.computeDiff(oldText, newText);
  assert.ok(Array.isArray(diff.splitLines));
  assert.ok(diff.splitLines.length >= 3);
});

test('DiffEngine: Conflict detection warns if disk file changed', () => {
  const tempFile = path.join(process.cwd(), '.temp_conflict_test.txt');
  fs.writeFileSync(tempFile, 'Initial Disk Content', 'utf-8');

  try {
    // 1. No conflict when expected matches disk
    const check1 = DiffEngine.detectConflict(tempFile, 'Initial Disk Content');
    assert.strictEqual(check1.hasConflict, false);

    // 2. Conflict detected when expected differs from disk
    const check2 = DiffEngine.detectConflict(tempFile, 'Stale Content From Previous Turn');
    assert.strictEqual(check2.hasConflict, true);
    assert.ok(check2.reason.includes('modified on disk'));
  } finally {
    if (fs.existsSync(tempFile)) fs.unlinkSync(tempFile);
  }
});
