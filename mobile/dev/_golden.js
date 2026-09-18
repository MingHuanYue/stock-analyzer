/* 金标准对拍：同一份输入，Python 引擎 vs JS 引擎，逐字段比对 */
'use strict';
const fs = require('fs');
const path = require('path');
const AN = require(path.join(__dirname, '..', 'web', 'analysis.js'));

const data = JSON.parse(fs.readFileSync(path.join(__dirname, '_golden.json'), 'utf-8'));
const OUT = path.join(__dirname, '_golden_diff.txt');
const lines = [];
const EPS = 1e-9;

function say(s) { lines.push(s); }

function isNum(v) { return typeof v === 'number' && isFinite(v); }

function diff(a, b, p, acc, limit) {
  if (acc.length >= limit) { return; }
  if (a === null || a === undefined) {
    if (b !== null && b !== undefined) { acc.push(p + ' 只存在于JS: ' + JSON.stringify(b)); }
    return;
  }
  if (b === null || b === undefined) {
    acc.push(p + ' 只存在于PY: ' + JSON.stringify(a));
    return;
  }
  if (isNum(a) && isNum(b)) {
    const d = Math.abs(a - b);
    const rel = d / Math.max(1e-12, Math.abs(a));
    if (d > EPS && rel > 1e-9) {
      acc.push(p + '  数值不同 PY=' + a + ' JS=' + b + ' (差 ' + d.toExponential(3) + ')');
    }
    return;
  }
  if (typeof a === 'string' || typeof b === 'string') {
    if (a !== b) {
      acc.push(p + '  文本不同\n      PY=[ ' + a + ' ]\n      JS=[ ' + b + ' ]');
    }
    return;
  }
  if (typeof a !== typeof b) {
    acc.push(p + '  类型不同 PY=' + typeof a + ' JS=' + typeof b);
    return;
  }
  if (Array.isArray(a) !== Array.isArray(b)) {
    acc.push(p + '  数组/对象不一致');
    return;
  }
  if (Array.isArray(a)) {
    if (a.length !== b.length) {
      acc.push(p + '  长度不同 PY=' + a.length + ' JS=' + b.length);
      return;
    }
    for (let i = 0; i < a.length; i++) { diff(a[i], b[i], p + '[' + i + ']', acc, limit); }
    return;
  }
  if (typeof a === 'object') {
    const ka = Object.keys(a).sort();
    const kb = Object.keys(b).sort();
    const onlyA = ka.filter(k => kb.indexOf(k) < 0);
    const onlyB = kb.filter(k => ka.indexOf(k) < 0);
    if (onlyA.length) { acc.push(p + '  PY 独有键: ' + onlyA.join(', ')); }
    if (onlyB.length) { acc.push(p + '  JS 独有键: ' + onlyB.join(', ')); }
    ka.filter(k => kb.indexOf(k) >= 0).forEach(k => {
      diff(a[k], b[k], p + '.' + k, acc, limit);
    });
    return;
  }
  if (a !== b) { acc.push(p + '  值不同 PY=' + a + ' JS=' + b); }
}

let totalDiff = 0, totalCases = 0, passCases = 0;
const MAXDIFF = 12;

data.cases.forEach(c => {
  if (!c.ok) { say('跳过（Python 侧失败）: ' + c.label + ' ' + (c.error || '')); return; }
  totalCases++;
  say('='.repeat(72));
  say('用例: ' + c.label + '   bars=' + c.bars.length + '  period=' + c.period);

  let ind, res;
  try {
    ind = AN.computeIndicators(c.bars);
    res = AN.buildAnalysis(c.quote, c.bars, ind, c.flow || [], c.finance || {},
                           (c.bench && c.bench.length) ? c.bench : null,
                           c.bench_name || '', c.period);
  } catch (err) {
    say('  !! JS 抛异常: ' + err.message);
    say(err.stack);
    totalDiff++;
    return;
  }

  const indDiff = [];
  diff(c.ind, ind, 'ind', indDiff, MAXDIFF);
  const resDiff = [];
  diff(c.expected, res, 'result', resDiff, MAXDIFF);

  const pyScore = c.expected.score, jsScore = res.score;
  say('  评分 PY=' + pyScore.toFixed(3) + '  JS=' + jsScore.toFixed(3));

  if (!indDiff.length && !resDiff.length) {
    passCases++;
    say('  ✓ 完全一致');
  } else {
    totalDiff += indDiff.length + resDiff.length;
    say('  指标差异 ' + indDiff.length + ' 处：');
    indDiff.forEach(d => say('    - ' + d));
    say('  分析差异 ' + resDiff.length + ' 处：');
    resDiff.forEach(d => say('    - ' + d));
  }
  say('  段落数 PY=' + (c.expected.sections || []).length +
      ' JS=' + (res.sections || []).length +
      '  看多 PY=' + (c.expected.bulls || []).length + '/JS=' + (res.bulls || []).length +
      '  看空 PY=' + (c.expected.bears || []).length + '/JS=' + (res.bears || []).length);
});

say('');
say('======== 汇总 ========');
say('用例总数 ' + totalCases + '，完全一致 ' + passCases + '，不一致 ' + (totalCases - passCases));
say('差异条目合计 ' + totalDiff);

fs.writeFileSync(OUT, lines.join('\n'), 'utf-8');
console.log(lines.join('\n'));
