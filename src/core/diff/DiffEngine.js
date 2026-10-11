const fs = require('node:fs');
const crypto = require('node:crypto');

class DiffEngine {
  /**
   * Computes LCS (Longest Common Subsequence) between two arrays of lines.
   */
  static lcs(linesA, linesB) {
    const m = linesA.length;
    const n = linesB.length;
    // DP matrix
    const dp = Array.from({ length: m + 1 }, () => new Int32Array(n + 1));

    for (let i = 0; i < m; i++) {
      for (let j = 0; j < n; j++) {
        if (linesA[i] === linesB[j]) {
          dp[i + 1][j + 1] = dp[i][j] + 1;
        } else {
          dp[i + 1][j + 1] = Math.max(dp[i + 1][j], dp[i][j + 1]);
        }
      }
    }

    // Backtrack to create diff ops
    const ops = [];
    let i = m;
    let j = n;

    while (i > 0 || j > 0) {
      if (i > 0 && j > 0 && linesA[i - 1] === linesB[j - 1]) {
        ops.unshift({
          type: 'unchanged',
          line: linesA[i - 1],
          oldLine: i,
          newLine: j
        });
        i--;
        j--;
      } else if (j > 0 && (i === 0 || dp[i][j - 1] >= dp[i - 1][j])) {
        ops.unshift({
          type: 'add',
          line: linesB[j - 1],
          oldLine: null,
          newLine: j
        });
        j--;
      } else if (i > 0 && (j === 0 || dp[i][j - 1] < dp[i - 1][j])) {
        ops.unshift({
          type: 'delete',
          line: linesA[i - 1],
          oldLine: i,
          newLine: null
        });
        i--;
      }
    }

    return ops;
  }

  /**
   * Computes structured diff between oldText and newText.
   */
  static computeDiff(oldText = '', newText = '', options = {}) {
    const linesOld = (oldText === '' ? [] : oldText.split(/\r?\n/));
    const linesNew = (newText === '' ? [] : newText.split(/\r?\n/));

    const rawOps = this.lcs(linesOld, linesNew);

    let additions = 0;
    let deletions = 0;

    for (const op of rawOps) {
      if (op.type === 'add') additions++;
      else if (op.type === 'delete') deletions++;
    }

    // Generate unified hunks
    const contextLines = options.context !== undefined ? options.context : 3;
    const hunks = this.buildHunks(rawOps, contextLines);
    const splitLines = this.buildSplitView(rawOps);

    return {
      additions,
      deletions,
      totalChanges: additions + deletions,
      hasChanges: additions > 0 || deletions > 0,
      oldLineCount: linesOld.length,
      newLineCount: linesNew.length,
      rawOps,
      hunks,
      splitLines
    };
  }

  /**
   * Builds unified diff hunks with context.
   */
  static buildHunks(ops, context = 3) {
    if (ops.length === 0) return [];

    // Find indices of changed lines
    const changeIndices = [];
    for (let i = 0; i < ops.length; i++) {
      if (ops[i].type !== 'unchanged') {
        changeIndices.push(i);
      }
    }

    if (changeIndices.length === 0) return [];

    // Group changes into clusters based on context
    const clusters = [];
    let currentCluster = [changeIndices[0]];

    for (let i = 1; i < changeIndices.length; i++) {
      const prevIdx = changeIndices[i - 1];
      const curIdx = changeIndices[i];
      if (curIdx - prevIdx <= context * 2) {
        currentCluster.push(curIdx);
      } else {
        clusters.push(currentCluster);
        currentCluster = [curIdx];
      }
    }
    clusters.push(currentCluster);

    // Build hunks from clusters
    const hunks = [];
    for (const cluster of clusters) {
      const firstChange = cluster[0];
      const lastChange = cluster[cluster.length - 1];

      const startIdx = Math.max(0, firstChange - context);
      const endIdx = Math.min(ops.length - 1, lastChange + context);

      const hunkOps = ops.slice(startIdx, endIdx + 1);

      // Determine header line numbers
      let oldStart = null;
      let newStart = null;
      let oldSpan = 0;
      let newSpan = 0;

      for (const op of hunkOps) {
        if (op.type === 'unchanged') {
          if (oldStart === null && op.oldLine !== null) oldStart = op.oldLine;
          if (newStart === null && op.newLine !== null) newStart = op.newLine;
          oldSpan++;
          newSpan++;
        } else if (op.type === 'delete') {
          if (oldStart === null && op.oldLine !== null) oldStart = op.oldLine;
          oldSpan++;
        } else if (op.type === 'add') {
          if (newStart === null && op.newLine !== null) newStart = op.newLine;
          newSpan++;
        }
      }

      oldStart = oldStart || 1;
      newStart = newStart || 1;

      const header = `@@ -${oldStart},${oldSpan} +${newStart},${newSpan} @@`;

      hunks.push({
        header,
        oldStart,
        oldSpan,
        newStart,
        newSpan,
        lines: hunkOps.map(op => ({
          type: op.type,
          prefix: op.type === 'add' ? '+' : op.type === 'delete' ? '-' : ' ',
          text: op.line,
          oldLine: op.oldLine,
          newLine: op.newLine
        }))
      });
    }

    return hunks;
  }

  /**
   * Builds split (side-by-side) diff lines.
   */
  static buildSplitView(ops) {
    const split = [];
    let i = 0;
    while (i < ops.length) {
      const op = ops[i];
      if (op.type === 'unchanged') {
        split.push({
          left: { line: op.oldLine, text: op.line, type: 'unchanged' },
          right: { line: op.newLine, text: op.line, type: 'unchanged' }
        });
        i++;
      } else if (op.type === 'delete') {
        // Look ahead for paired addition
        if (i + 1 < ops.length && ops[i + 1].type === 'add') {
          split.push({
            left: { line: op.oldLine, text: op.line, type: 'delete' },
            right: { line: ops[i + 1].newLine, text: ops[i + 1].line, type: 'add' }
          });
          i += 2;
        } else {
          split.push({
            left: { line: op.oldLine, text: op.line, type: 'delete' },
            right: null
          });
          i++;
        }
      } else if (op.type === 'add') {
        split.push({
          left: null,
          right: { line: op.newLine, text: op.line, type: 'add' }
        });
        i++;
      }
    }
    return split;
  }

  /**
   * Conflict Detection:
   * Compares the current content on disk with the original content expected by the agent.
   */
  static detectConflict(filePath, expectedOriginalContent) {
    if (!fs.existsSync(filePath)) {
      if (expectedOriginalContent !== null && expectedOriginalContent !== '') {
        return {
          hasConflict: true,
          reason: `File ${filePath} was deleted or does not exist on disk, but was expected to exist.`
        };
      }
      return { hasConflict: false };
    }

    const currentDiskContent = fs.readFileSync(filePath, 'utf-8');

    if (expectedOriginalContent === null) {
      // Expected new file, but file already exists on disk
      return {
        hasConflict: true,
        reason: `File ${filePath} already exists on disk, but the proposal expected to create a new file.`
      };
    }

    const expectedHash = crypto.createHash('sha256').update(expectedOriginalContent).digest('hex');
    const diskHash = crypto.createHash('sha256').update(currentDiskContent).digest('hex');

    if (expectedHash !== diskHash) {
      return {
        hasConflict: true,
        reason: `File ${filePath} has been modified on disk since the proposal was prepared.`,
        currentDiskContent,
        expectedHash,
        diskHash
      };
    }

    return { hasConflict: false };
  }
}

module.exports = {
  DiffEngine
};
