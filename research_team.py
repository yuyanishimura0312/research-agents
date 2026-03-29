#!/usr/bin/env python3
"""
最強リサーチエージェントチーム
Anthropic SDK + DuckDuckGo Search による調査レポート生成システム

使い方:
  python3 research_team.py "調査テーマ"
  python3 research_team.py "調査テーマ" --depth deep
  python3 research_team.py "調査テーマ" --lang en

環境変数:
  ANTHROPIC_API_KEY  — Anthropic APIキー（必須）
"""

import asyncio
import json
import sys
import argparse
import os
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path
from textwrap import dedent

import anthropic
from duckduckgo_search import DDGS


# === 設定 ===

MODEL = "claude-sonnet-4-20250514"  # Cost-effective for sub-agents
ORCHESTRATOR_MODEL = "claude-sonnet-4-20250514"  # Best reasoning for orchestrator
MAX_TOKENS = 8192


# === ウェブ検索ツール ===

def web_search(query: str, max_results: int = 10) -> list[dict]:
    """DuckDuckGo でウェブ検索"""
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        return [
            {
                "title": r.get("title", ""),
                "url": r.get("href", ""),
                "snippet": r.get("body", ""),
            }
            for r in results
        ]
    except Exception as e:
        return [{"error": str(e)}]


def web_search_news(query: str, max_results: int = 10) -> list[dict]:
    """DuckDuckGo でニュース検索"""
    try:
        with DDGS() as ddgs:
            results = list(ddgs.news(query, max_results=max_results))
        return [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("body", ""),
                "date": r.get("date", ""),
                "source": r.get("source", ""),
            }
            for r in results
        ]
    except Exception as e:
        return [{"error": str(e)}]


def fetch_page(url: str) -> str:
    """URLのページ内容をテキストで取得"""
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": "ResearchBot/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
        # Strip HTML tags for a rough text extraction
        text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        # Limit to avoid token explosion
        return text[:8000]
    except Exception as e:
        return f"Error fetching {url}: {e}"


# === ツール定義 ===

TOOLS = [
    {
        "name": "web_search",
        "description": "Search the web using DuckDuckGo. Returns titles, URLs, and snippets.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Max results (default 10)",
                    "default": 10,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "web_search_news",
        "description": "Search recent news articles. Good for current events and trends.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "News search query",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Max results (default 10)",
                    "default": 10,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "fetch_page",
        "description": "Fetch and extract text content from a URL. Use to read full articles.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL to fetch",
                },
            },
            "required": ["url"],
        },
    },
]


def execute_tool(name: str, input_data: dict) -> str:
    """ツール呼び出しを実行"""
    if name == "web_search":
        results = web_search(input_data["query"], input_data.get("max_results", 10))
        return json.dumps(results, ensure_ascii=False, indent=2)
    elif name == "web_search_news":
        results = web_search_news(input_data["query"], input_data.get("max_results", 10))
        return json.dumps(results, ensure_ascii=False, indent=2)
    elif name == "fetch_page":
        return fetch_page(input_data["url"])
    else:
        return f"Unknown tool: {name}"


# === エージェントクラス ===

class Agent:
    """Claude を使った専門エージェント"""

    def __init__(self, name: str, system_prompt: str, model: str = MODEL,
                 tools: list | None = None, max_turns: int = 30):
        self.name = name
        self.system_prompt = system_prompt
        self.model = model
        self.tools = tools or TOOLS
        self.max_turns = max_turns
        self.client = anthropic.Anthropic()

    def run(self, task: str) -> str:
        """タスクを実行して結果を返す"""
        print(f"\n  🔬 [{self.name}] 起動...")
        start = time.time()

        messages = [{"role": "user", "content": task}]

        for turn in range(self.max_turns):
            response = self.client.messages.create(
                model=self.model,
                max_tokens=MAX_TOKENS,
                system=self.system_prompt,
                tools=self.tools,
                messages=messages,
            )

            # Collect assistant content
            assistant_content = response.content
            messages.append({"role": "assistant", "content": assistant_content})

            # Check if done
            if response.stop_reason == "end_turn":
                break

            # Handle tool use
            if response.stop_reason == "tool_use":
                tool_results = []
                for block in assistant_content:
                    if block.type == "tool_use":
                        print(f"     [{self.name}] 🔧 {block.name}: {_truncate(json.dumps(block.input, ensure_ascii=False), 80)}")
                        result = execute_tool(block.name, block.input)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        })
                messages.append({"role": "user", "content": tool_results})

        elapsed = time.time() - start
        print(f"  ✅ [{self.name}] 完了 ({elapsed:.1f}秒)")

        # Extract final text
        final_text = ""
        for block in assistant_content:
            if hasattr(block, "text"):
                final_text += block.text
        return final_text


# === エージェント定義 ===

def create_web_researcher(language: str) -> Agent:
    lang = "日本語で回答してください。" if language == "ja" else "Respond in English."
    return Agent(
        name="Web Researcher",
        system_prompt=dedent(f"""\
            You are an elite web research specialist.

            Your mission:
            - Search the web thoroughly using multiple queries and diverse angles
            - Find authoritative, primary sources (government, academic, major publications)
            - Extract specific data: numbers, dates, statistics, quotes
            - ALWAYS record the URL and title of every source
            - Try at least 5 different search queries to cover the topic comprehensively
            - Search in both English and Japanese when relevant
            - Look for the LATEST information available

            Output format:
            For each finding, provide:
            - The key information found
            - Source: [Title](URL)
            - Date published (if available)
            - Reliability: High / Medium / Low

            At the end, list all sources used.
            {lang}"""),
    )


def create_academic_researcher(language: str) -> Agent:
    lang = "日本語で回答してください。" if language == "ja" else "Respond in English."
    return Agent(
        name="Academic Researcher",
        system_prompt=dedent(f"""\
            You are an academic and specialized research agent.

            Your mission:
            - Search for scholarly articles, research papers, expert analyses
            - Find systematic reviews, meta-analyses, authoritative reports
            - Look for data from reputable organizations (WHO, World Bank, OECD, UN, etc.)
            - Identify key researchers and thought leaders
            - Extract methodology details and statistical findings

            Search strategies:
            - Use queries like "[topic] research paper", "[topic] systematic review"
            - Search for "[topic] site:arxiv.org", "[topic] site:nature.com"
            - Look for government reports and institutional data
            - Search for conference proceedings and white papers

            Output format:
            For each finding:
            - Key data or insight
            - Source: [Title](URL)
            - Type: Paper / Report / Data / Expert opinion
            - Reliability: High / Medium / Low
            {lang}"""),
    )


def create_analyst(language: str) -> Agent:
    lang = "日本語で回答してください。" if language == "ja" else "Respond in English."
    return Agent(
        name="Analyst",
        system_prompt=dedent(f"""\
            You are a senior research analyst.

            Your mission:
            - Analyze research findings for patterns, trends, and anomalies
            - Identify agreements and contradictions across sources
            - Assess the strength of evidence for each claim
            - Quantify findings wherever possible
            - Highlight gaps and limitations

            Analysis framework:
            1. Key themes and categories
            2. Evidence strength: Strong / Moderate / Weak / Conflicting
            3. Timeline and trend analysis
            4. Stakeholder perspectives
            5. Knowledge gaps
            6. Surprising or counterintuitive findings

            You may also search the web to fill gaps you identify.
            {lang}"""),
    )


def create_fact_checker(language: str) -> Agent:
    lang = "日本語で回答してください。" if language == "ja" else "Respond in English."
    return Agent(
        name="Fact Checker",
        system_prompt=dedent(f"""\
            You are a rigorous fact-checker and source validator.

            Your mission:
            - Verify key claims by cross-referencing independent sources
            - Check if statistics and data points are accurate and current
            - Assess source credibility and potential biases
            - Identify logical fallacies or unsupported claims
            - Flag outdated information

            Verification protocol:
            1. Extract each major claim
            2. Find 2+ independent sources to verify
            3. Check original source of cited statistics
            4. Note unverifiable claims

            Output: For each checked claim, report:
            - Claim
            - Verdict: Verified / Partially Verified / Unverified / Disputed
            - Supporting sources
            - Notes
            {lang}"""),
    )


def create_report_writer(language: str) -> Agent:
    lang = "日本語で回答してください。" if language == "ja" else "Respond in English."
    return Agent(
        name="Report Writer",
        system_prompt=dedent(f"""\
            You are a world-class research report writer.

            Your mission:
            - Synthesize all findings into a clear, compelling report
            - Structure logically with proper sections
            - Include citations [1], [2] for every major claim
            - Write an executive summary capturing key insights
            - Balance depth with readability
            - Use clear, jargon-free language accessible to non-specialists

            CRITICAL WRITING STYLE:
            - レポートは必ず「文章（地の文・散文）」で記述すること
            - 箇条書きや表だけで構成してはならない
            - 分析・考察・説明はすべて文章として展開すること
            - 表は数値データの整理など、補助的な用途にのみ使用
            - 箇条書きは列挙が必要な場合に限定的に使用
            - 各セクションは複数の段落で構成し、論理の流れが文章で追えるようにする

            Report structure:
            # [テーマ]
            ## エグゼクティブサマリー
            ## 1. 背景と目的
            ## 2. 調査手法
            ## 3. 主要な発見
            ### 3.1 [サブテーマ1]
            ### 3.2 [サブテーマ2]
            ...
            ## 4. 分析と考察
            ## 5. 結論と提言
            ## 参考文献

            Important:
            - Every factual claim needs a citation
            - Tables are for numerical data only — analysis must be in prose
            - Note limitations honestly
            - Provide actionable recommendations
            {lang}"""),
        tools=[],  # Writer doesn't need web tools
    )


# === オーケストレーター ===

async def run_research(topic: str, depth: str = "standard", language: str = "ja"):
    """リサーチエージェントチームを起動"""

    output_dir = Path("research_output")
    output_dir.mkdir(exist_ok=True)

    today = datetime.now().strftime("%Y-%m-%d")

    depth_config = {
        "quick":    {"search_queries": "3-5", "sources": "5-10",  "verify_top": 3},
        "standard": {"search_queries": "5-8", "sources": "15-25", "verify_top": 5},
        "deep":     {"search_queries": "8-12", "sources": "30+",  "verify_top": 10},
    }[depth]

    print(f"\n{'='*60}")
    print(f"  🚀 リサーチエージェントチーム 起動")
    print(f"{'='*60}")
    print(f"  テーマ: {topic}")
    print(f"  深度:   {depth} ({depth_config['sources']} ソース目標)")
    print(f"  言語:   {'日本語' if language == 'ja' else 'English'}")
    print(f"  日付:   {today}")
    print(f"  出力先: {output_dir.resolve()}/")
    print(f"{'='*60}")

    # --- Phase 1: Planning ---
    print(f"\n📋 Phase 1: 調査計画の策定")
    planner = Agent(
        name="Planner",
        system_prompt="You are a research planning specialist. Break down topics into specific, searchable research questions.",
        tools=[],
    )
    plan = planner.run(dedent(f"""\
        Research topic: {topic}
        Depth: {depth} ({depth_config['search_queries']} search angles, {depth_config['sources']} sources target)
        Date: {today}

        Create a research plan:
        1. Break this topic into 5-7 specific research questions
        2. For each question, suggest 2-3 search queries (mix of English and Japanese if relevant)
        3. Identify what types of sources would be most valuable
        4. Note any potential biases or pitfalls to watch for

        Output the plan as a structured list.
        {"日本語で回答してください。" if language == "ja" else "Respond in English."}"""))

    # Save plan
    (output_dir / "plan.md").write_text(f"# 調査計画\n\n{plan}", encoding="utf-8")
    print(f"\n{plan[:500]}...")

    # --- Phase 2: Parallel Research ---
    print(f"\n🔍 Phase 2: 並列リサーチ（Web + Academic）")

    web_researcher = create_web_researcher(language)
    academic_researcher = create_academic_researcher(language)

    research_task = dedent(f"""\
        Research topic: {topic}
        Date: {today}

        Research plan:
        {plan}

        Execute the research plan. Search thoroughly using {depth_config['search_queries']} different query angles.
        Target: {depth_config['sources']} sources.
        Fetch and read full articles for the most important sources.
        {"日本語で回答してください。" if language == "ja" else "Respond in English."}""")

    # Run both researchers in parallel
    loop = asyncio.get_event_loop()
    web_future = loop.run_in_executor(None, web_researcher.run, research_task)
    academic_future = loop.run_in_executor(None, academic_researcher.run, research_task)

    web_findings, academic_findings = await asyncio.gather(web_future, academic_future)

    # Save raw findings
    raw = f"# Web Research Findings\n\n{web_findings}\n\n---\n\n# Academic Research Findings\n\n{academic_findings}"
    (output_dir / "raw_findings.md").write_text(raw, encoding="utf-8")

    # --- Phase 3: Analysis ---
    print(f"\n📊 Phase 3: 分析")
    analyst = create_analyst(language)
    analysis = analyst.run(dedent(f"""\
        Analyze the following research findings on: {topic}

        === Web Research Findings ===
        {web_findings}

        === Academic Research Findings ===
        {academic_findings}

        Provide a comprehensive analysis:
        1. Key themes and patterns
        2. Evidence strength for major claims
        3. Contradictions or debates
        4. Gaps that need further investigation
        5. Surprising or counterintuitive findings

        If you find gaps, use web search to fill them.
        {"日本語で回答してください。" if language == "ja" else "Respond in English."}"""))

    (output_dir / "analysis.md").write_text(f"# 分析結果\n\n{analysis}", encoding="utf-8")

    # --- Phase 4: Fact Checking ---
    print(f"\n✓ Phase 4: ファクトチェック")
    fact_checker = create_fact_checker(language)
    verification = fact_checker.run(dedent(f"""\
        Verify the top {depth_config['verify_top']} most important claims from this research on: {topic}

        === Analysis ===
        {analysis}

        For each claim:
        1. State the claim
        2. Search for independent verification
        3. Report: Verified / Partially Verified / Unverified / Disputed
        4. Cite verification sources
        {"日本語で回答してください。" if language == "ja" else "Respond in English."}"""))

    (output_dir / "fact_check.md").write_text(f"# ファクトチェック結果\n\n{verification}", encoding="utf-8")

    # --- Phase 5: Report Writing ---
    print(f"\n📝 Phase 5: レポート作成")
    writer = create_report_writer(language)
    report = writer.run(dedent(f"""\
        Write a comprehensive research report on: {topic}
        Date: {today}

        Use ALL of the following materials:

        === Research Plan ===
        {plan}

        === Web Research Findings ===
        {web_findings}

        === Academic Research Findings ===
        {academic_findings}

        === Analysis ===
        {analysis}

        === Fact Check Results ===
        {verification}

        Requirements:
        - Include ALL sources as numbered citations [1], [2], etc.
        - Reference list at the end with full URLs
        - Executive summary at the top
        - Clear section structure
        - Note any claims that could not be fully verified
        - Include data tables where appropriate
        - Provide actionable recommendations
        {"日本語で回答してください。" if language == "ja" else "Respond in English."}"""))

    # Save final report
    report_path = output_dir / "report.md"
    report_path.write_text(report, encoding="utf-8")

    print(f"\n{'='*60}")
    print(f"  🎉 調査完了!")
    print(f"{'='*60}")
    print(f"\n  📄 最終レポート: {report_path.resolve()}")
    print(f"  📁 全出力ファイル:")
    for f in sorted(output_dir.iterdir()):
        size = f.stat().st_size
        print(f"     - {f.name} ({size:,} bytes)")
    print(f"\n{'='*60}\n")

    # --- Phase 6: Convert to .docx ---
    print(f"\n📄 Phase 6: Word 文書に変換")
    docx_path = convert_to_docx(report_path)

    # --- Phase 7: Dashboard Registration ---
    print(f"\n📊 Phase 7: Research Dashboard に登録")
    save_to_dashboard(topic, report, depth, language, docx_path)

    # Print report preview
    preview_lines = report.split("\n")[:30]
    print("\n".join(preview_lines))
    if len(report.split("\n")) > 30:
        print(f"\n... (全文は {report_path} を参照)")


# === Dashboard 連携 ===

DASHBOARD_DIR = Path.home() / "research-dashboard"

GOOGLE_DRIVE_DIR = Path.home() / "Library" / "CloudStorage" / "GoogleDrive-REDACTED" / "マイドライブ"
GOOGLE_DRIVE_RESEARCH_DIR = GOOGLE_DRIVE_DIR / "Research Reports"


def convert_to_docx(report_path: Path):  # -> Optional[Path]
    """Markdown レポートを .docx に変換"""
    try:
        convert_script = Path(__file__).parent / "convert_report.py"
        docx_path = report_path.with_suffix(".docx")
        result = subprocess.run(
            ["python3", str(convert_script), str(report_path), str(docx_path)],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            print(f"  ✅ Word 文書: {docx_path}")
            # Google Drive に自動コピー → Google ドキュメントで開く
            gdocs_path = copy_to_google_drive(docx_path)
            if gdocs_path:
                subprocess.run(["open", str(gdocs_path)])
            else:
                subprocess.run(["open", str(docx_path)])
            return docx_path
        else:
            print(f"  ⚠️  変換エラー: {result.stderr.strip()}")
            return None
    except Exception as e:
        print(f"  ⚠️  変換スキップ: {e}")
        return None


def copy_to_google_drive(docx_path: Path):  # -> Optional[Path]
    """docx を Google Drive にコピーし、Google ドキュメントで開けるようにする"""
    import shutil

    if not GOOGLE_DRIVE_DIR.exists():
        print(f"  ⚠️  Google Drive が見つかりません: {GOOGLE_DRIVE_DIR}")
        return None

    try:
        # Research Reports フォルダを作成（なければ）
        GOOGLE_DRIVE_RESEARCH_DIR.mkdir(exist_ok=True)

        dest = GOOGLE_DRIVE_RESEARCH_DIR / docx_path.name
        shutil.copy2(str(docx_path), str(dest))
        print(f"  ✅ Google Drive にコピー: {dest.name}")
        print(f"     → Google ドキュメントで自動的に開きます")
        return dest
    except Exception as e:
        print(f"  ⚠️  Google Drive コピー失敗: {e}")
        return None


def save_to_dashboard(topic: str, report: str, depth: str, language: str, docx_path=None):
    """調査結果を Research Dashboard に自動登録"""
    save_script = DASHBOARD_DIR / "save-research.sh"
    if not save_script.exists():
        print(f"  ⚠️  Dashboard が見つかりません: {DASHBOARD_DIR}")
        return

    # Extract executive summary (first ~500 chars after the first heading)
    summary = _extract_summary(report)

    # Build tags from topic keywords + metadata
    tags = [f"depth:{depth}"]
    if language == "ja":
        tags.append("日本語")
    else:
        tags.append("English")
    tags.append("auto-research")

    # Guess a category from the topic
    category = _guess_category(topic)

    # Link to docx if available, otherwise markdown
    if docx_path and docx_path.exists():
        source = f"file://{docx_path.resolve()}"
    else:
        report_path = Path("research_output/report.md").resolve()
        source = f"file://{report_path}"

    result = subprocess.run(
        [
            "bash", str(save_script),
            "--title", topic,
            "--summary", summary,
            "--tags", ",".join(tags),
            "--category", category,
            "--source", source,
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        print(f"  ✅ Dashboard に登録完了: {result.stdout.strip()}")
    else:
        print(f"  ⚠️  Dashboard 登録エラー: {result.stderr.strip()}")


def _extract_summary(report: str, max_len: int = 600) -> str:
    """レポートからエグゼクティブサマリー部分を抽出"""
    lines = report.split("\n")
    in_summary = False
    summary_lines = []

    for line in lines:
        # Detect executive summary section
        lower = line.lower()
        if "エグゼクティブサマリー" in line or "executive summary" in lower:
            in_summary = True
            continue
        # Stop at next major heading
        if in_summary and line.startswith("## ") and "サマリー" not in line and "summary" not in lower:
            break
        if in_summary:
            summary_lines.append(line)

    summary = "\n".join(summary_lines).strip()
    if not summary:
        # Fallback: first 600 chars of report
        summary = report[:max_len]

    if len(summary) > max_len:
        summary = summary[:max_len] + "..."
    return summary


def _guess_category(topic: str) -> str:
    """トピックからカテゴリを推測"""
    topic_lower = topic.lower()
    keywords = {
        "テクノロジー": ["ai", "量子", "quantum", "コンピュータ", "tech", "ソフトウェア", "software", "デジタル", "プログラ"],
        "ビジネス": ["ibm", "経営", "企業", "ビジネス", "business", "戦略", "strategy", "マーケ", "market"],
        "社会": ["社会", "教育", "政策", "少子", "環境", "climate", "health", "医療"],
        "人類学": ["人類", "民族", "文化", "anthrop", "ethnograph", "フィールド"],
        "科学": ["科学", "science", "研究", "research", "生物", "物理", "化学"],
    }
    for category, words in keywords.items():
        if any(w in topic_lower for w in words):
            return category
    return "リサーチ"


# === ユーティリティ ===

def _truncate(s: str, max_len: int) -> str:
    return s[:max_len] + "..." if len(s) > max_len else s


# === CLI ===

def main():
    parser = argparse.ArgumentParser(
        description="最強リサーチエージェントチーム",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=dedent("""\
            例:
              python3 research_team.py "生成AIの教育への影響"
              python3 research_team.py "量子コンピュータの現状" --depth deep
              python3 research_team.py "Climate change adaptation" --lang en
        """),
    )
    parser.add_argument("topic", help="調査テーマ")
    parser.add_argument(
        "--depth",
        choices=["quick", "standard", "deep"],
        default="standard",
        help="調査の深さ (default: standard)",
    )
    parser.add_argument(
        "--lang",
        choices=["ja", "en"],
        default="ja",
        help="レポートの言語 (default: ja)",
    )

    args = parser.parse_args()

    # Check API key
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("❌ ANTHROPIC_API_KEY が設定されていません。")
        print("   export ANTHROPIC_API_KEY='your-key-here'")
        sys.exit(1)

    asyncio.run(run_research(args.topic, args.depth, args.lang))


if __name__ == "__main__":
    main()
