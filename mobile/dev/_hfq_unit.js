/* 用实测抓到的真实数据验证后复权末根修正逻辑（离线，不联网） */
const DS = require('../web/datasource.js');

function mk(rows) {
  return rows.map(r => ({
    d: r[0], o: r[1], c: r[2], h: r[3], l: r[4], v: r[5],
    amt: r[5] * 100 * (r[1] + r[2] + r[3] + r[4]) / 4,
    amp: null, pct: null, chg: null, turn: null
  }));
}

/* 数据来自 dev/_hfq.txt 的实测结果 */
const CASES = [
  {
    name: 'sh600519 茅台（末根因子 6.394，应为 ~7.05）',
    hfq: mk([
      ['2026-09-15', 9012.485, 8966.056, 9032.182, 8957.783, 13762],
      ['2026-09-16', 8972.697, 8883.047, 8978.606, 8861.098, 26235],
      ['2026-09-17', 8882.934, 8933.584, 8937.073, 8860.536, 17554],
      ['2026-09-18', 8075.75, 8038.72, 8094.22, 8034.31, 12123]
    ]),
    qfq: mk([
      ['2026-09-15', 1281.000, 1272.750, 1284.500, 1271.280, 13762],
      ['2026-09-16', 1273.930, 1258.000, 1274.980, 1254.100, 26235],
      ['2026-09-17', 1257.980, 1266.980, 1267.600, 1254.000, 17554],
      ['2026-09-18', 1262.99, 1257.20, 1265.88, 1256.51, 12123]
    ])
  },
  {
    name: 'sz300750 宁德时代（末根因子 1.0，完全没复权）',
    hfq: mk([
      ['2026-09-15', 642.932, 609.380, 644.246, 608.732, 480483],
      ['2026-09-16', 603.350, 589.796, 606.932, 578.132, 787163],
      ['2026-09-17', 590.732, 587.672, 595.520, 584.792, 344896],
      ['2026-09-18', 309.77, 301.68, 310.00, 300.27, 222839]
    ]),
    qfq: mk([
      ['2026-09-15', 335.000, 316.360, 335.730, 316.000, 480483],
      ['2026-09-16', 313.010, 305.480, 315.000, 299.000, 787163],
      ['2026-09-17', 306.000, 304.300, 308.660, 302.700, 344896],
      ['2026-09-18', 309.77, 301.68, 310.00, 300.27, 222839]
    ])
  }
];

let pass = 0;
const out = [];
CASES.forEach(c => {
  out.push('==== ' + c.name);
  const before = c.hfq.map(b => b.c);
  out.push('  修正前收盘: ' + before.map(x => x.toFixed(2)).join(', '));
  out.push('  修正前末根涨跌幅: ' +
           ((c.hfq[3].c / c.hfq[2].c - 1) * 100).toFixed(2) + '%');
  const ok = DS._rebuildHfq(c.hfq, c.qfq);
  out.push('  rebuildHfq 返回: ' + ok);
  const after = c.hfq.map(b => b.c);
  out.push('  修正后收盘: ' + after.map(x => x.toFixed(2)).join(', '));
  out.push('  修正后末根涨跌幅: ' + c.hfq[3].pct.toFixed(2) + '%');

  /* 判定：
   * 1) 前 3 根必须几乎不变（本来就对）
   * 2) 末根涨跌幅必须落在 ±10% 以内，且等于真实涨跌幅（qfq 口径） */
  const realPct = (c.qfq[3].c / c.qfq[2].c - 1) * 100;
  const drift = [0, 1, 2].map(i => Math.abs(after[i] / before[i] - 1));
  const maxDrift = Math.max.apply(null, drift);
  const pctErr = Math.abs(c.hfq[3].pct - realPct);
  out.push('  前3根最大偏移: ' + (maxDrift * 100).toFixed(3) + '%');
  out.push('  真实涨跌幅: ' + realPct.toFixed(2) + '%  误差: ' +
           pctErr.toFixed(4) + ' 个百分点');
  const good = ok && maxDrift < 0.005 && pctErr < 0.01;
  out.push('  ==> ' + (good ? '通过' : '未通过'));
  out.push('');
  if (good) { pass++; }
});

out.push('通过 ' + pass + '/' + CASES.length);
require('fs').writeFileSync(__dirname + '/_hfq_unit.txt', out.join('\n'), 'utf8');
console.log(out.join('\n'));
