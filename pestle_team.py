#!/usr/bin/env python3
"""
PESTLE分析エージェントチーム
6つの専門エージェントが並列で各次元を調査し、統合レポートを生成

使い方:
  python3 pestle_team.py "分析対象（業界・企業・テーマ）"
  python3 pestle_team.py "日本のEV市場" --depth deep
  python3 pestle_team.py "Remote healthcare industry" --lang en

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


# === Config ===

MODEL = "claude-sonnet-4-20250514"
ORCHESTRATOR_MODEL = "claude-sonnet-4-20250514"
MAX_TOKENS = 8192


# === Web search tools (shared with research_team.py) ===

def web_search(query: str, max_results: int = 10) -> list[dict]:
    """DuckDuckGo web search"""
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        return [
            {"title": r.get("title", ""), "url": r.get("href", ""), "snippet": r.get("body", "")}
            for r in results
        ]
    except Exception as e:
        return [{"error": str(e)}]


def web_search_news(query: str, max_results: int = 10) -> list[dict]:
    """DuckDuckGo news search"""
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
    """Fetch page content as text"""
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": "ResearchBot/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
        text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:8000]
    except Exception as e:
        return f"Error fetching {url}: {e}"


TOOLS = [
    {
        "name": "web_search",
        "description": "Search the web using DuckDuckGo. Returns titles, URLs, and snippets.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "max_results": {"type": "integer", "description": "Max results (default 10)", "default": 10},
            },
            "required": ["query"],
        },
    },
    {
        "name": "web_search_news",
        "description": "Search recent news articles. Good for current events, policy changes, and trends.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "News search query"},
                "max_results": {"type": "integer", "description": "Max results (default 10)", "default": 10},
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
                "url": {"type": "string", "description": "URL to fetch"},
            },
            "required": ["url"],
        },
    },
]


def execute_tool(name: str, input_data: dict) -> str:
    if name == "web_search":
        return json.dumps(web_search(input_data["query"], input_data.get("max_results", 10)), ensure_ascii=False, indent=2)
    elif name == "web_search_news":
        return json.dumps(web_search_news(input_data["query"], input_data.get("max_results", 10)), ensure_ascii=False, indent=2)
    elif name == "fetch_page":
        return fetch_page(input_data["url"])
    else:
        return f"Unknown tool: {name}"


# === Agent class ===

class Agent:
    """Specialized Claude agent with web search capability"""

    def __init__(self, name: str, system_prompt: str, model: str = MODEL,
                 tools: list | None = None, max_turns: int = 30):
        self.name = name
        self.system_prompt = system_prompt
        self.model = model
        self.tools = tools if tools is not None else TOOLS
        self.max_turns = max_turns
        self.client = anthropic.Anthropic()

    def run(self, task: str) -> str:
        print(f"\n  [{self.name}] Starting...")
        start = time.time()

        messages = [{"role": "user", "content": task}]

        assistant_content = []
        for turn in range(self.max_turns):
            response = self.client.messages.create(
                model=self.model,
                max_tokens=MAX_TOKENS,
                system=self.system_prompt,
                tools=self.tools,
                messages=messages,
            )

            assistant_content = response.content
            messages.append({"role": "assistant", "content": assistant_content})

            if response.stop_reason == "end_turn":
                break

            if response.stop_reason == "tool_use":
                tool_results = []
                for block in assistant_content:
                    if block.type == "tool_use":
                        print(f"     [{self.name}] tool: {block.name}: {_truncate(json.dumps(block.input, ensure_ascii=False), 80)}")
                        result = execute_tool(block.name, block.input)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        })
                messages.append({"role": "user", "content": tool_results})

        elapsed = time.time() - start
        print(f"  [{self.name}] Done ({elapsed:.1f}s)")

        final_text = ""
        for block in assistant_content:
            if hasattr(block, "text"):
                final_text += block.text
        return final_text


# === PESTLE dimension agents ===

def _lang_instruction(language: str) -> str:
    return "日本語で回答してください。" if language == "ja" else "Respond in English."


def create_political_agent(language: str) -> Agent:
    return Agent(
        name="Political Analyst",
        system_prompt=dedent(f"""\
            You are a political environment analyst specializing in PESTLE analysis.

            Your focus: POLITICAL factors that affect the target industry/organization.

            Research areas:
            - Government stability and political direction
            - Trade policies, tariffs, and international agreements
            - Taxation policy changes (corporate tax, consumption tax, subsidies)
            - Regulatory bodies and their recent actions
            - Government spending priorities and public investment
            - Political party platforms relevant to the sector
            - Geopolitical risks and international relations
            - Election cycles and potential policy shifts
            - Lobbying activities and political influence

            Methodology:
            - Search for recent government announcements and policy papers
            - Check legislative changes in the past 12 months
            - Identify upcoming elections or political events
            - Assess political risk levels by region
            - Use both English and Japanese search queries when relevant

            Output format:
            For each finding:
            - Factor description (with specific details, dates, numbers)
            - Impact: High / Medium / Low
            - Direction: Positive / Negative / Neutral / Uncertain
            - Time horizon: Immediate / Short-term (1-2y) / Long-term (3-5y)
            - Source: [Title](URL)

            End with a summary of top 3-5 key political factors.
            {_lang_instruction(language)}"""),
    )


def create_economic_agent(language: str) -> Agent:
    return Agent(
        name="Economic Analyst",
        system_prompt=dedent(f"""\
            You are an economic environment analyst specializing in PESTLE analysis.

            Your focus: ECONOMIC factors that affect the target industry/organization.

            Research areas:
            - GDP growth rate, inflation, interest rates
            - Exchange rates and currency stability
            - Consumer spending and disposable income trends
            - Industry-specific economic indicators
            - Supply chain costs and commodity prices
            - Labor market conditions (unemployment, wage trends)
            - Capital availability and investment climate
            - Economic cycles and recession indicators
            - International trade flows and balance of payments
            - Industry growth rate and market size projections

            Methodology:
            - Search for latest economic data from central banks, OECD, IMF, World Bank
            - Find industry-specific market research reports
            - Check commodity and input cost trends
            - Analyze consumer confidence indices
            - Look for economic forecasts from major institutions

            Output format:
            For each finding:
            - Economic indicator or trend (with specific numbers)
            - Impact: High / Medium / Low
            - Direction: Positive / Negative / Neutral
            - Time horizon: Immediate / Short-term (1-2y) / Long-term (3-5y)
            - Source: [Title](URL)

            End with a summary of top 3-5 key economic factors.
            {_lang_instruction(language)}"""),
    )


def create_social_agent(language: str) -> Agent:
    return Agent(
        name="Social Analyst",
        system_prompt=dedent(f"""\
            You are a social environment analyst specializing in PESTLE analysis.

            Your focus: SOCIAL factors that affect the target industry/organization.

            Research areas:
            - Demographics: population growth, aging, urbanization
            - Cultural trends and lifestyle changes
            - Consumer attitudes, values, and preferences
            - Health consciousness and wellness trends
            - Education levels and skill availability
            - Work-life balance and remote work trends
            - Social media influence and digital behavior
            - Income distribution and social inequality
            - Diversity, equity, and inclusion trends
            - Migration patterns and labor mobility

            Methodology:
            - Search for census data and demographic projections
            - Find consumer behavior surveys and trend reports
            - Check social media trend analysis
            - Look for academic research on social changes
            - Identify cultural shifts relevant to the sector

            Output format:
            For each finding:
            - Social factor (with data points)
            - Impact: High / Medium / Low
            - Direction: Positive / Negative / Neutral
            - Time horizon: Immediate / Short-term (1-2y) / Long-term (3-5y)
            - Source: [Title](URL)

            End with a summary of top 3-5 key social factors.
            {_lang_instruction(language)}"""),
    )


def create_technological_agent(language: str) -> Agent:
    return Agent(
        name="Technology Analyst",
        system_prompt=dedent(f"""\
            You are a technology environment analyst specializing in PESTLE analysis.

            Your focus: TECHNOLOGICAL factors that affect the target industry/organization.

            Research areas:
            - Emerging technologies (AI, IoT, blockchain, quantum, etc.)
            - R&D activity and innovation trends in the sector
            - Technology adoption rates and digital transformation
            - Automation and its impact on the industry
            - Cybersecurity threats and data protection technology
            - Infrastructure development (5G, cloud, edge computing)
            - Technology transfer and open-source movements
            - Patent activity and intellectual property trends
            - Disruptive technologies and potential game-changers
            - Technology investment and venture capital flows

            Methodology:
            - Search for technology roadmaps and industry reports (Gartner, McKinsey, etc.)
            - Find patent filings and R&D spending data
            - Check startup activity and VC investment in the sector
            - Look for technology adoption case studies
            - Identify technology standards and platforms emerging

            Output format:
            For each finding:
            - Technology factor (with specifics)
            - Impact: High / Medium / Low
            - Maturity: Emerging / Growing / Mature / Declining
            - Disruption potential: High / Medium / Low
            - Source: [Title](URL)

            End with a summary of top 3-5 key technological factors.
            {_lang_instruction(language)}"""),
    )


def create_legal_agent(language: str) -> Agent:
    return Agent(
        name="Legal Analyst",
        system_prompt=dedent(f"""\
            You are a legal environment analyst specializing in PESTLE analysis.

            Your focus: LEGAL factors that affect the target industry/organization.

            Research areas:
            - Industry-specific regulations and compliance requirements
            - Consumer protection laws and recent enforcement
            - Employment law changes (labor standards, minimum wage, etc.)
            - Data protection and privacy regulations (GDPR, APPI, etc.)
            - Intellectual property law and patent protection
            - Antitrust and competition law
            - Environmental regulations and liability
            - International trade law and sanctions
            - Licensing and permit requirements
            - Pending legislation and regulatory proposals

            Methodology:
            - Search for recent legislation and regulatory changes
            - Find enforcement actions and court decisions
            - Check regulatory agency announcements
            - Look for legal industry analysis and commentary
            - Identify upcoming regulatory changes

            Output format:
            For each finding:
            - Legal factor (with specific law/regulation names)
            - Impact: High / Medium / Low
            - Compliance burden: High / Medium / Low
            - Timeline: Already in effect / Upcoming / Proposed
            - Source: [Title](URL)

            End with a summary of top 3-5 key legal factors.
            {_lang_instruction(language)}"""),
    )


def create_environmental_agent(language: str) -> Agent:
    return Agent(
        name="Environmental Analyst",
        system_prompt=dedent(f"""\
            You are an environmental analyst specializing in PESTLE analysis.

            Your focus: ENVIRONMENTAL factors that affect the target industry/organization.

            Research areas:
            - Climate change impacts on the industry
            - Carbon emissions regulations and carbon pricing
            - Sustainability requirements and ESG standards
            - Resource scarcity and raw material availability
            - Waste management and circular economy trends
            - Energy transition and renewable energy adoption
            - Natural disaster risks and climate resilience
            - Biodiversity and ecosystem impacts
            - Consumer demand for sustainable products
            - Green technology and clean-tech trends

            Methodology:
            - Search for environmental policy and regulation updates
            - Find ESG and sustainability reports for the industry
            - Check climate data and environmental impact assessments
            - Look for industry sustainability benchmarks
            - Identify green technology trends

            Output format:
            For each finding:
            - Environmental factor (with data)
            - Impact: High / Medium / Low
            - Urgency: Immediate / Short-term / Long-term
            - Opportunity/Threat: Opportunity / Threat / Both
            - Source: [Title](URL)

            End with a summary of top 3-5 key environmental factors.
            {_lang_instruction(language)}"""),
    )


def create_integration_agent(language: str) -> Agent:
    """Cross-dimension analysis agent that finds connections between PESTLE factors"""
    return Agent(
        name="Integration Analyst",
        system_prompt=dedent(f"""\
            You are a senior strategic analyst specializing in cross-dimensional PESTLE integration.

            Your mission:
            - Identify interconnections between Political, Economic, Social, Technological, Legal, and Environmental factors
            - Find reinforcing and conflicting trends across dimensions
            - Assess compound risks (when multiple factors combine)
            - Identify strategic opportunities at the intersection of factors
            - Prioritize factors by overall impact and likelihood
            - Create a risk/opportunity matrix

            Analysis framework:
            1. Cross-impact analysis: How does each dimension affect others?
            2. Scenario identification: What are the best-case, worst-case, and most-likely scenarios?
            3. Strategic windows: Where do factor combinations create opportunities?
            4. Compound risks: Where do negative factors reinforce each other?
            5. Key uncertainties: Which factors have the highest uncertainty?

            You may search the web to verify connections or find additional data.
            {_lang_instruction(language)}"""),
    )


def create_pestle_report_writer(language: str) -> Agent:
    return Agent(
        name="PESTLE Report Writer",
        system_prompt=dedent(f"""\
            You are a world-class strategic report writer specializing in PESTLE analysis.

            Your mission: Synthesize all PESTLE dimension analyses into a professional strategic report.

            CRITICAL WRITING STYLE:
            - Write in prose (narrative paragraphs), NOT just bullet points
            - Analysis, insights, and explanations must be full paragraphs
            - Tables are for summarizing factor ratings only
            - Each section should have narrative context before any structured data

            Report structure:

            # PESTLE分析: [対象]

            ## エグゼクティブサマリー
            Overview of the most critical findings across all dimensions.
            Top 3 opportunities and top 3 threats.

            ## 1. 分析の背景と目的
            Why this analysis was conducted and what decisions it informs.

            ## 2. Political（政治的要因）
            Narrative analysis with key factors, their interactions, and strategic implications.

            ## 3. Economic（経済的要因）
            Same format.

            ## 4. Social（社会的要因）
            Same format.

            ## 5. Technological（技術的要因）
            Same format.

            ## 6. Legal（法的要因）
            Same format.

            ## 7. Environmental（環境的要因）
            Same format.

            ## 8. クロスインパクト分析
            How factors across dimensions interact and compound.

            ## 9. シナリオ分析
            Best-case, worst-case, and most-likely scenarios based on the analysis.

            ## 10. 戦略的提言
            Actionable recommendations based on the analysis.
            Prioritized by urgency and impact.

            ## PESTLE要因サマリーテーブル
            | 次元 | 主要要因 | 影響度 | 方向性 | 時間軸 |
            Summary table of all key factors.

            ## 参考文献
            Numbered references with full URLs.

            Requirements:
            - Include citations [1], [2] for every factual claim
            - Note unverified claims
            - Be specific with data (numbers, dates, percentages)
            - Write accessibly for non-specialist executives
            {_lang_instruction(language)}"""),
        tools=[],  # Writer doesn't need web tools
    )


# === Orchestrator ===

async def run_pestle(topic: str, depth: str = "standard", language: str = "ja"):
    """Run the PESTLE analysis agent team"""

    output_dir = Path("research_output") / "pestle"
    output_dir.mkdir(parents=True, exist_ok=True)

    today = datetime.now().strftime("%Y-%m-%d")

    depth_config = {
        "quick":    {"queries": "3-5",  "sources_per_dim": "3-5",  "verify": False},
        "standard": {"queries": "5-8",  "sources_per_dim": "5-10", "verify": True},
        "deep":     {"queries": "8-12", "sources_per_dim": "10+",  "verify": True},
    }[depth]

    print(f"\n{'='*60}")
    print(f"  PESTLE Analysis Agent Team")
    print(f"{'='*60}")
    print(f"  Target:  {topic}")
    print(f"  Depth:   {depth} ({depth_config['sources_per_dim']} sources/dimension)")
    print(f"  Language: {'Japanese' if language == 'ja' else 'English'}")
    print(f"  Date:    {today}")
    print(f"  Output:  {output_dir.resolve()}/")
    print(f"{'='*60}")

    # --- Phase 1: Context Setting ---
    print(f"\n--- Phase 1: Context & Scope Definition ---")
    planner = Agent(
        name="PESTLE Planner",
        system_prompt="You are a strategic analysis planner. Define the scope and key questions for a PESTLE analysis.",
        tools=[],
    )
    plan = planner.run(dedent(f"""\
        PESTLE analysis target: {topic}
        Depth: {depth}
        Date: {today}

        Define the analysis scope:
        1. Clearly define what "{topic}" means in this context (industry boundaries, geography, time frame)
        2. For each PESTLE dimension, list 3-5 specific research questions most relevant to this target
        3. Identify key geographies and markets to focus on
        4. Note any known major events or changes in the past 12 months that are relevant
        5. Suggest specific search queries for each dimension (mix of English and Japanese)

        Be specific — generic questions like "what are economic trends" are not useful.
        {_lang_instruction(language)}"""))

    (output_dir / "plan.md").write_text(f"# PESTLE Analysis Plan\n\n{plan}", encoding="utf-8")

    # --- Phase 2: Parallel PESTLE Dimension Research ---
    print(f"\n--- Phase 2: Parallel PESTLE Research (6 agents) ---")

    agents = {
        "political":     create_political_agent(language),
        "economic":      create_economic_agent(language),
        "social":        create_social_agent(language),
        "technological": create_technological_agent(language),
        "legal":         create_legal_agent(language),
        "environmental": create_environmental_agent(language),
    }

    dimension_task_template = dedent(f"""\
        PESTLE analysis target: {topic}
        Date: {today}
        Depth: {depth} — aim for {depth_config['sources_per_dim']} sources

        Analysis plan:
        {{plan}}

        Conduct thorough research on your assigned dimension.
        Use {depth_config['queries']} different search queries.
        Search in both English and Japanese when relevant.
        Fetch and read full articles for the most important sources.
        Be specific: include numbers, dates, statistics, and concrete examples.
        {_lang_instruction(language)}""")

    # Run all 6 dimension agents in parallel
    loop = asyncio.get_event_loop()
    futures = {}
    for dim_name, agent in agents.items():
        task = dimension_task_template.replace("{plan}", plan)
        futures[dim_name] = loop.run_in_executor(None, agent.run, task)

    results = {}
    for dim_name, future in futures.items():
        results[dim_name] = await future

    # Save individual dimension results
    for dim_name, result in results.items():
        (output_dir / f"{dim_name}.md").write_text(
            f"# {dim_name.title()} Analysis\n\n{result}", encoding="utf-8"
        )

    # --- Phase 3: Integration Analysis ---
    print(f"\n--- Phase 3: Cross-Dimension Integration ---")
    integrator = create_integration_agent(language)

    all_findings = "\n\n".join(
        f"=== {dim.upper()} ===\n{text}" for dim, text in results.items()
    )

    integration = integrator.run(dedent(f"""\
        PESTLE analysis target: {topic}
        Date: {today}

        Below are the findings from 6 specialized analysts. Perform cross-dimensional integration:

        {all_findings}

        Deliver:
        1. Cross-impact matrix: How does each dimension affect the others?
        2. Top 5 compound risks (where multiple negative factors reinforce each other)
        3. Top 5 strategic opportunities (where positive factors combine)
        4. 3 scenarios: best-case, worst-case, most-likely
        5. Key uncertainties and what would resolve them
        6. Overall strategic assessment
        {_lang_instruction(language)}"""))

    (output_dir / "integration.md").write_text(
        f"# Cross-Dimension Integration\n\n{integration}", encoding="utf-8"
    )

    # --- Phase 4: Report Writing ---
    print(f"\n--- Phase 4: PESTLE Report Generation ---")
    writer = create_pestle_report_writer(language)

    report = writer.run(dedent(f"""\
        Write a comprehensive PESTLE analysis report on: {topic}
        Date: {today}

        Use ALL of the following materials:

        === ANALYSIS PLAN ===
        {plan}

        === POLITICAL ANALYSIS ===
        {results['political']}

        === ECONOMIC ANALYSIS ===
        {results['economic']}

        === SOCIAL ANALYSIS ===
        {results['social']}

        === TECHNOLOGICAL ANALYSIS ===
        {results['technological']}

        === LEGAL ANALYSIS ===
        {results['legal']}

        === ENVIRONMENTAL ANALYSIS ===
        {results['environmental']}

        === CROSS-DIMENSION INTEGRATION ===
        {integration}

        Requirements:
        - Write in prose, not just bullet points
        - Include ALL sources as numbered citations
        - Be specific with data (numbers, dates, %)
        - Include PESTLE summary table
        - Provide actionable strategic recommendations
        - Note any unverified claims
        {_lang_instruction(language)}"""))

    report_path = output_dir / "report.md"
    report_path.write_text(report, encoding="utf-8")

    print(f"\n{'='*60}")
    print(f"  PESTLE Analysis Complete!")
    print(f"{'='*60}")
    print(f"\n  Report: {report_path.resolve()}")
    print(f"  Files:")
    for f in sorted(output_dir.iterdir()):
        size = f.stat().st_size
        print(f"     - {f.name} ({size:,} bytes)")
    print(f"\n{'='*60}\n")

    # --- Phase 5: Convert to .docx ---
    print(f"\n--- Phase 5: Word document conversion ---")
    docx_path = convert_to_docx(report_path)

    # --- Phase 6: Dashboard Registration ---
    print(f"\n--- Phase 6: Research Dashboard registration ---")
    save_to_dashboard(topic, report, depth, language, docx_path)

    # Print preview
    preview_lines = report.split("\n")[:30]
    print("\n".join(preview_lines))
    if len(report.split("\n")) > 30:
        print(f"\n... (full report: {report_path})")


# === Dashboard integration (same as research_team.py) ===

DASHBOARD_DIR = Path.home() / "research-dashboard"
GOOGLE_DRIVE_DIR = Path(os.environ.get("GOOGLE_DRIVE_DIR", str(Path.home() / "Google Drive")))
GOOGLE_DRIVE_RESEARCH_DIR = GOOGLE_DRIVE_DIR / "Research Reports"


def convert_to_docx(report_path: Path):
    """Convert markdown report to .docx"""
    try:
        convert_script = Path(__file__).parent / "convert_report.py"
        docx_path = report_path.with_suffix(".docx")
        result = subprocess.run(
            ["python3", str(convert_script), str(report_path), str(docx_path)],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            print(f"  Word document: {docx_path}")
            gdocs_path = copy_to_google_drive(docx_path)
            if gdocs_path:
                subprocess.run(["open", str(gdocs_path)])
            else:
                subprocess.run(["open", str(docx_path)])
            return docx_path
        else:
            print(f"  Conversion error: {result.stderr.strip()}")
            return None
    except Exception as e:
        print(f"  Conversion skipped: {e}")
        return None


def copy_to_google_drive(docx_path: Path):
    """Copy docx to Google Drive"""
    import shutil
    if not GOOGLE_DRIVE_DIR.exists():
        print(f"  Google Drive not found: {GOOGLE_DRIVE_DIR}")
        return None
    try:
        GOOGLE_DRIVE_RESEARCH_DIR.mkdir(exist_ok=True)
        dest = GOOGLE_DRIVE_RESEARCH_DIR / docx_path.name
        shutil.copy2(str(docx_path), str(dest))
        print(f"  Copied to Google Drive: {dest.name}")
        return dest
    except Exception as e:
        print(f"  Google Drive copy failed: {e}")
        return None


def save_to_dashboard(topic: str, report: str, depth: str, language: str, docx_path=None):
    """Register results to Research Dashboard"""
    save_script = DASHBOARD_DIR / "save-research.sh"
    if not save_script.exists():
        print(f"  Dashboard not found: {DASHBOARD_DIR}")
        return

    summary = _extract_summary(report)
    tags = ["PESTLE", f"depth:{depth}", "auto-research"]
    tags.append("Japanese" if language == "ja" else "English")
    category = "PESTLE分析"

    if docx_path and docx_path.exists():
        source = f"file://{docx_path.resolve()}"
    else:
        report_path = Path("research_output/pestle/report.md").resolve()
        source = f"file://{report_path}"

    import tempfile
    content_file = None
    try:
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8")
        tmp.write(report)
        tmp.close()
        content_file = tmp.name
    except Exception as e:
        print(f"  Temp file creation failed: {e}")

    cmd = [
        "bash", str(save_script),
        "--title", f"PESTLE分析: {topic}",
        "--summary", summary,
        "--tags", ",".join(tags),
        "--category", category,
        "--source", source,
        "--status", "done",
    ]
    if content_file:
        cmd += ["--content-file", content_file]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if content_file:
        try:
            os.remove(content_file)
        except OSError:
            pass

    if result.returncode == 0:
        print(f"  Dashboard registered: {result.stdout.strip()}")
    else:
        print(f"  Dashboard registration error: {result.stderr.strip()}")


def _extract_summary(report: str, max_len: int = 600) -> str:
    lines = report.split("\n")
    in_summary = False
    summary_lines = []
    for line in lines:
        lower = line.lower()
        if "エグゼクティブサマリー" in line or "executive summary" in lower:
            in_summary = True
            continue
        if in_summary and line.startswith("## ") and "サマリー" not in line and "summary" not in lower:
            break
        if in_summary:
            summary_lines.append(line)
    summary = "\n".join(summary_lines).strip()
    if not summary:
        summary = report[:max_len]
    if len(summary) > max_len:
        summary = summary[:max_len] + "..."
    return summary


def _truncate(s: str, max_len: int) -> str:
    return s[:max_len] + "..." if len(s) > max_len else s


# === CLI ===

def main():
    parser = argparse.ArgumentParser(
        description="PESTLE Analysis Agent Team",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=dedent("""\
            Examples:
              python3 pestle_team.py "日本のEV市場"
              python3 pestle_team.py "日本の介護業界" --depth deep
              python3 pestle_team.py "Global AI chip industry" --lang en
              python3 pestle_team.py "日本のフィンテック市場" --depth quick
        """),
    )
    parser.add_argument("topic", help="Analysis target (industry, company, theme)")
    parser.add_argument(
        "--depth",
        choices=["quick", "standard", "deep"],
        default="standard",
        help="Analysis depth (default: standard)",
    )
    parser.add_argument(
        "--lang",
        choices=["ja", "en"],
        default="ja",
        help="Report language (default: ja)",
    )

    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY is not set.")
        print("  export ANTHROPIC_API_KEY='your-key-here'")
        sys.exit(1)

    asyncio.run(run_pestle(args.topic, args.depth, args.lang))


if __name__ == "__main__":
    main()
