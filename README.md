# Research Agent Team (リサーチエージェントチーム)

Claude Agent SDK を使った調査レポート生成システムです。
5つの専門エージェントがチームとして協働し、高品質なリサーチレポートを自動生成します。

## エージェント構成

```
┌─────────────────────────────────────────────┐
│           Orchestrator (総指揮)              │
│         調査計画の策定と全体統括              │
└──────────┬──────────────────┬────────────────┘
           │                  │
    ┌──────▼──────┐   ┌──────▼──────────┐
    │ Web         │   │ Academic        │  ← Phase 2: 並列リサーチ
    │ Researcher  │   │ Researcher      │
    └──────┬──────┘   └──────┬──────────┘
           │                  │
    ┌──────▼──────────────────▼──────┐
    │         Analyst                │  ← Phase 3: 分析
    │    パターン発見・信頼性評価      │
    └──────────────┬─────────────────┘
                   │
    ┌──────────────▼─────────────────┐
    │       Fact Checker             │  ← Phase 4: 検証
    │    主張の裏付け・矛盾の発見     │
    └──────────────┬─────────────────┘
                   │
    ┌──────────────▼─────────────────┐
    │       Report Writer            │  ← Phase 5: レポート作成
    │    構造化レポート・引用付き      │
    └────────────────────────────────┘
```

## セットアップ

```bash
cd research-agents
pip install -r requirements.txt
```

Anthropic API キーが必要です:
```bash
export ANTHROPIC_API_KEY="your-key-here"
```

## 使い方

### 基本
```bash
python research_team.py "調査テーマを入力"
```

### オプション
```bash
# クイック調査（5-10ソース、速度重視）
python research_team.py "テーマ" --depth quick

# 標準調査（15-25ソース、デフォルト）
python research_team.py "テーマ" --depth standard

# 徹底調査（30+ソース、網羅性重視）
python research_team.py "テーマ" --depth deep

# 英語でレポート出力
python research_team.py "Topic" --lang en
```

### 例
```bash
python research_team.py "生成AIの教育への影響と今後の展望"
python research_team.py "日本の少子化対策の国際比較" --depth deep
python research_team.py "Impact of remote work on productivity" --lang en
```

## 出力

`research_output/` フォルダに以下のファイルが生成されます:

- `report.md` — 最終レポート（引用付き）
- `raw_findings.md` — 生データ・調査メモ

## レポート構成

1. エグゼクティブサマリー
2. 背景と目的
3. 調査手法
4. 主要な発見
5. 分析と考察
6. 結論と提言
7. 参考文献（URL・アクセス日付付き）
8. 付録
