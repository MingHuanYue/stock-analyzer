# 股票分析助手（stock-analyzer）

A股 / 港股 / 美股的联网 K 线与数据分析工具，同一套分析引擎的两个形态：

| 目录 | 形态 | 技术栈 |
|---|---|---|
| `desktop/` | Windows 单文件 exe（免安装） | Python 标准库（tkinter 自绘图表，零第三方依赖），PyInstaller 打包 |
| `mobile/` | 安卓 APK + 单文件网页 | 纯静态前端（原生 JS/Canvas，零依赖），WebView 壳，命令行直打 APK 不用 Gradle |

## 功能

- 行情：分时 / 日K / 周K / 月K，前复权 / 不复权 / 后复权，MACD / KDJ / RSI 副图
- 分析：综合评分（0~100）+ 白话结论、多空信号对照、趋势/动量/量能/位置四维评分、
  波动与风险（ATR / 年化波动率 / 布林带宽 / 最大回撤）、关键价位阶梯（支撑/压力）、
  六大段详细分析、情景应对参考
- 数据：盘口速览、估值与规模（市值/PE/PB）、资金流向、财务摘要（A股）、大盘基准对照
- 手机版另有：自选股（本地保存，批量刷价）、双指缩放 / 拖动平移 / 十字光标
- 涨红跌绿（中国习惯），全部中文界面

## 数据来源

- 主源：腾讯财经（K线 / 分时 / 快照 / 搜索）
- 辅源：东方财富（资金流 / 财务 / 大盘基准），被限流时自动重试与降级
- 已知坑：腾讯后复权序列最新一根（当日盘中）复权因子有误，
  `mobile/web/datasource.js` 的 `rebuildHfq()` 用 qfq×K 重建修正，详见代码注释

## 构建

### desktop/

```
pyinstaller --noconfirm --onefile --noconsole --name StockAnalyzer ^
  --icon icon.ico --exclude-module numpy --exclude-module PIL ^
  --exclude-module matplotlib --exclude-module pandas app.py
```

### mobile/

```
python dev/build_web.py     # 6 个前端文件内联成单文件 HTML
python dev/build_apk.py     # 打 APK（需 tools/ 下自备 JDK17 + Android SDK build-tools 34，
                            #   签名密码读环境变量 STOCK_KS_PASS，
                            #   keystore 放在 android/ 下、不随仓库分发）
```

## 质量保障

- `mobile/dev/_golden.py` + `_golden.js`：JS 引擎与 Python 引擎逐字对拍（7 用例，差异须为 0）
- `mobile/dev/_browser_check.js`：无头 Edge + CDP 全场景回归（取数/渲染/复权口径/自选股）
- `mobile/dev/_apk_verify.py`：APK 静态验收（badging / 签名 / 内置网页与构建产物逐字节比对）

## AI 参与声明

本项目为 **AI 辅助开发**：代码初稿与大部分实现由 AI 编程助手（WorkBuddy）生成，
需求定义、方案取舍、测试验收、数据口径修正与发布决策由人类主导完成。
代码为原创编写，未复制第三方开源项目实现；运行时仅调用公开行情接口
（腾讯财经 / 东方财富），不打包任何第三方代码或数据。

## 免责声明

本工具所有内容基于公开数据和量化分析，仅供参考，不构成投资建议。
市场有风险，投资需谨慎。任何投资决策应结合个人风险承受能力、资金状况和
投资目标独立判断，必要时咨询持牌专业机构。过往表现不预示未来收益。

## License

MIT（见 `LICENSE`）
