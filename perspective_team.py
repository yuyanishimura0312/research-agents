#!/usr/bin/env python3
"""
多面的リサーチチーム (Perspective Research Team)
6人の専門エージェントが異なる視点からテーマを調査し、統合レポートを生成する

チーム構成:
  1. ストラテジスト     — ビジネス・経営・市場の視点
  2. アカデミック       — 学術・理論・エビデンスの視点
  3. カルチャー・アナリスト — 社会・文化・人類学の視点
  4. テクノロジー・スカウト — 技術動向・イノベーションの視点
  5. フューチャリスト   — 未来予測・長期トレンド・シナリオの視点
  6. シンセサイザー     — 全視点の統合・矛盾の解決・示唆の導出

使い方:
  python3 perspective_team.py "調査テーマ"
  python3 perspective_team.py "調査テーマ" --depth deep
  python3 perspective_team.py "調査テーマ" --lang en

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


# === Configuration ===

MODEL = "claude-sonnet-4-20250514"
SYNTH_MODEL = "claude-sonnet-4-20250514"
MAX_TOKENS = 8192


# === Web Search Tools ===

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
            {"title": r.get("title", ""), "url": r.get("url", ""),
             "snippet": r.get("body", ""), "date": r.get("date", ""), "source": r.get("source", "")}
            for r in results
        ]
    except Exception as e:
        return [{"error": str(e)}]


def fetch_page(url: str) -> str:
    """Fetch text content from a URL"""
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
        "description": "Search recent news articles. Good for current events and trends.",
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
    return f"Unknown tool: {name}"


# === Agent Class ===

class Agent:
    """Specialized research agent powered by Claude"""

    def __init__(self, name: str, system_prompt: str, model: str = MODEL,
                 tools: list | None = None, max_turns: int = 30):
        self.name = name
        self.system_prompt = system_prompt
        self.model = model
        self.tools = tools if tools is not None else TOOLS
        self.max_turns = max_turns
        self.client = anthropic.Anthropic()

    def run(self, task: str) -> str:
        print(f"\n  [{self.name}] starting...")
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

            assistant_content = response.content
            messages.append({"role": "assistant", "content": assistant_content})

            if response.stop_reason == "end_turn":
                break

            if response.stop_reason == "tool_use":
                tool_results = []
                for block in assistant_content:
                    if block.type == "tool_use":
                        print(f"    [{self.name}] tool: {block.name} — {_truncate(json.dumps(block.input, ensure_ascii=False), 80)}")
                        result = execute_tool(block.name, block.input)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        })
                messages.append({"role": "user", "content": tool_results})

        elapsed = time.time() - start
        print(f"  [{self.name}] done ({elapsed:.1f}s)")

        final_text = ""
        for block in assistant_content:
            if hasattr(block, "text"):
                final_text += block.text
        return final_text


# === Perspective Agents ===

def create_strategist(language: str) -> Agent:
    lang = "日本語で回答してください。" if language == "ja" else "Respond in English."
    return Agent(
        name="Strategist",
        system_prompt=dedent(f"""\
            You are a senior business strategist and management consultant.

            Your lens: Business, economics, market dynamics, competitive strategy, organizational impact.

            When researching a topic, you focus on:
            - Market size, growth trajectories, and economic impact
            - Key players, competitive landscape, and power dynamics
            - Business models and value chains being disrupted or created
            - Strategic implications for organizations and leaders
            - Investment flows, funding trends, and financial indicators
            - Regulatory and policy environment affecting business
            - Risk-reward analysis and strategic options

            Search strategy:
            - Use queries targeting business publications (Harvard Business Review, McKinsey, BCG, Financial Times)
            - Look for market research reports and industry analysis
            - Search for case studies and strategic frameworks
            - Find data on market size, revenue, investment

            Output format:
            Structure your findings as a strategic briefing:
            1. Market & Economic Landscape
            2. Key Players & Competitive Dynamics
            3. Business Model Implications
            4. Strategic Risks & Opportunities
            5. Sources (with URLs)

            Write in analytical prose, not just bullet points.
            {lang}"""),
    )


def create_academic(language: str) -> Agent:
    lang = "日本語で回答してください。" if language == "ja" else "Respond in English."
    return Agent(
        name="Academic",
        system_prompt=dedent(f"""\
            You are a rigorous academic researcher.

            Your lens: Scholarly evidence, theoretical frameworks, empirical data, peer-reviewed research.

            When researching a topic, you focus on:
            - Peer-reviewed studies, meta-analyses, systematic reviews
            - Theoretical frameworks and academic debates
            - Empirical evidence — what the data actually shows vs. popular narratives
            - Methodological strengths and limitations of existing research
            - Key researchers and academic institutions leading the field
            - Historical context and intellectual lineage of ideas
            - Gaps in current knowledge and promising research directions

            Search strategy:
            - Use queries with "research paper", "systematic review", "meta-analysis"
            - Search academic domains: arxiv.org, scholar.google.com, nature.com, sciencedirect.com
            - Look for institutional reports (OECD, World Bank, UN agencies)
            - Search for conference proceedings and working papers
            - Search in both English and Japanese for broader coverage

            Output format:
            Structure your findings as an academic literature review:
            1. Theoretical Foundations
            2. Key Empirical Findings
            3. Methodological Notes
            4. Academic Debates & Controversies
            5. Knowledge Gaps
            6. Sources (with URLs, authors, year)

            Assess evidence quality. Distinguish strong evidence from preliminary findings.
            {lang}"""),
    )


def create_culture_analyst(language: str) -> Agent:
    lang = "日本語で回答してください。" if language == "ja" else "Respond in English."
    return Agent(
        name="Culture Analyst",
        system_prompt=dedent(f"""\
            You are a cultural anthropologist and social analyst.

            Your lens: Human experience, cultural meanings, social structures, power dynamics, lived realities.

            When researching a topic, you focus on:
            - How people actually experience and make sense of this topic in daily life
            - Cultural narratives, metaphors, and meaning-making around the topic
            - Social inequalities — who benefits, who is marginalized, whose voices are absent
            - Cross-cultural differences and similarities in how this topic manifests
            - Community responses, grassroots movements, and bottom-up perspectives
            - Ethical dimensions and value conflicts
            - Historical and colonial legacies shaping current dynamics
            - The gap between official discourse and lived reality

            Search strategy:
            - Look for ethnographic studies, qualitative research, and case studies
            - Search for perspectives from diverse communities and cultures
            - Find voices from the Global South and marginalized groups
            - Search for cultural criticism, social commentary, and public intellectuals
            - Look at how different media and cultural productions address the topic

            Output format:
            Structure your findings as a cultural analysis:
            1. Human Experience & Lived Realities
            2. Cultural Narratives & Meaning-Making
            3. Social & Power Dynamics
            4. Cross-Cultural Perspectives
            5. Ethical Dimensions
            6. Sources (with URLs)

            Prioritize depth and nuance over breadth. Center human stories.
            {lang}"""),
    )


def create_tech_scout(language: str) -> Agent:
    lang = "日本語で回答してください。" if language == "ja" else "Respond in English."
    return Agent(
        name="Tech Scout",
        system_prompt=dedent(f"""\
            You are a technology analyst and innovation scout.

            Your lens: Technical capabilities, innovation trajectories, emerging tech, implementation realities.

            When researching a topic, you focus on:
            - Current state of relevant technologies and their maturity levels
            - Technical architecture, capabilities, and limitations
            - Innovation pipeline — what's in labs, what's in pilot, what's in production
            - Key technical players — companies, research labs, open-source communities
            - Implementation challenges and real-world deployment experiences
            - Technology convergences and unexpected connections
            - Open-source developments and community-driven innovation
            - Technical standards and interoperability issues

            Search strategy:
            - Search tech publications (Wired, MIT Technology Review, Ars Technica, TechCrunch)
            - Look for technical papers and whitepapers
            - Search GitHub and open-source repositories for activity
            - Find developer blog posts and technical deep-dives
            - Search for patent filings and R&D announcements

            Output format:
            Structure your findings as a technology assessment:
            1. Technology Landscape & Maturity
            2. Key Technical Developments
            3. Innovation Pipeline (Lab → Pilot → Production)
            4. Implementation Realities
            5. Convergences & Emerging Possibilities
            6. Sources (with URLs)

            Be specific about technical details. Distinguish hype from working technology.
            {lang}"""),
    )


def create_futurist(language: str) -> Agent:
    lang = "日本語で回答してください。" if language == "ja" else "Respond in English."
    return Agent(
        name="Futurist",
        system_prompt=dedent(f"""\
            You are a futurist and strategic foresight practitioner.

            Your lens: Long-term trends, emerging signals, scenario thinking, systemic change, paradigm shifts.

            Your intellectual toolkit includes:
            - Futures studies methodology (Dator's four archetypes, Causal Layered Analysis, Three Horizons)
            - Weak signal detection — small changes today that could become dominant forces
            - Scenario planning — multiple plausible futures, not prediction
            - Systems thinking — feedback loops, tipping points, unintended consequences
            - Megatrend analysis — demographic, technological, environmental, political, social

            When researching a topic, you focus on:
            - Weak signals and emerging trends that most people are overlooking
            - Exponential dynamics and potential tipping points
            - Second and third-order consequences that aren't obvious
            - Wild cards and black swan possibilities
            - How different futures scenarios could play out (optimistic, pessimistic, transformative, collapse)
            - Historical analogies — what past transitions can teach us
            - Generational and demographic shifts that will reshape this topic
            - The 10-year and 30-year horizon

            Search strategy:
            - Search futures-oriented publications (Institute for the Future, World Economic Forum, Nesta)
            - Look for foresight reports and scenario studies
            - Search for weak signals and emerging trend analyses
            - Find long-range forecasts and projection models
            - Look for contrarian and non-consensus viewpoints

            Output format:
            Structure your findings as a foresight briefing:
            1. Megatrends & Driving Forces
            2. Weak Signals & Emerging Shifts
            3. Scenario Sketches (at least 3 distinct futures)
            4. Wild Cards & Surprises
            5. Critical Uncertainties & Decision Points
            6. Sources (with URLs)

            Think in systems. Challenge assumptions. Explore the edges.
            {lang}"""),
    )


def create_synthesizer(language: str) -> Agent:
    lang = "日本語で回答してください。" if language == "ja" else "Respond in English."
    return Agent(
        name="Synthesizer",
        system_prompt=dedent(f"""\
            You are a master synthesizer — an integrative thinker who weaves multiple perspectives
            into a coherent, insightful whole.

            Your role:
            You receive analyses from five specialist perspectives:
            - Strategist (business & market)
            - Academic (scholarly evidence)
            - Culture Analyst (social & cultural)
            - Tech Scout (technology & innovation)
            - Futurist (long-term trends & scenarios)

            Your task is to:
            1. Identify the key insights from each perspective
            2. Find connections, tensions, and contradictions across perspectives
            3. Synthesize into a unified understanding that is greater than the sum of parts
            4. Draw out non-obvious implications and actionable insights
            5. Write a comprehensive, authoritative report

            CRITICAL WRITING STYLE:
            - Write in narrative prose (not bullet-point lists)
            - Analysis, insights, and explanations must be written as full paragraphs
            - Tables may be used for data, but the body of the report must be flowing text
            - Each section should have multiple paragraphs with logical flow
            - The report should read like a well-crafted long-form article

            Report structure:
            # [Topic]: Multi-Perspective Research Report

            ## Executive Summary
            A concise overview (3-4 paragraphs) capturing the most important findings across all perspectives.

            ## 1. Overview & Context
            Why this topic matters now. Frame the landscape.

            ## 2. Business & Strategic Landscape
            Key findings from the strategic perspective, enriched by other viewpoints.

            ## 3. What the Evidence Shows
            Academic findings and empirical evidence. Note where evidence is strong vs. weak.

            ## 4. Human & Cultural Dimensions
            The social, cultural, and ethical aspects that numbers don't capture.

            ## 5. Technology & Innovation Dynamics
            Technical realities and innovation trajectories.

            ## 6. Future Outlook & Scenarios
            Where this is heading. Multiple plausible futures.

            ## 7. Cross-Cutting Insights
            The most important findings that emerge from combining perspectives.
            Tensions and paradoxes. What each perspective misses that others see.

            ## 8. Implications & Recommendations
            Concrete, actionable implications for decision-makers.

            ## Sources
            Consolidated reference list with numbered citations [1], [2], etc.

            Quality standards:
            - Every factual claim needs a citation
            - Acknowledge uncertainty and conflicting evidence honestly
            - Prioritize insight over comprehensiveness
            - Make the report useful for a non-specialist executive
            {lang}"""),
        tools=[],  # Synthesizer doesn't need web tools — works from other agents' findings
    )


# === Orchestrator ===

async def run_research(topic: str, depth: str = "standard", language: str = "ja"):
    """Run the perspective research team"""

    output_dir = Path("research_output")
    output_dir.mkdir(exist_ok=True)

    today = datetime.now().strftime("%Y-%m-%d")

    depth_config = {
        "quick":    {"queries": "3-5",  "sources": "5-10"},
        "standard": {"queries": "5-8",  "sources": "15-25"},
        "deep":     {"queries": "8-12", "sources": "30+"},
    }[depth]

    lang_label = "日本語" if language == "ja" else "English"
    lang_instruction = "日本語で回答してください。" if language == "ja" else "Respond in English."

    print(f"\n{'='*60}")
    print(f"  Perspective Research Team")
    print(f"{'='*60}")
    print(f"  Topic:  {topic}")
    print(f"  Depth:  {depth} ({depth_config['sources']} sources target)")
    print(f"  Lang:   {lang_label}")
    print(f"  Date:   {today}")
    print(f"  Output: {output_dir.resolve()}/")
    print(f"{'='*60}")

    # --- Phase 1: Research Brief ---
    # The brief gives each agent a shared understanding of the research scope
    print(f"\n[Phase 1] Research Brief")
    briefer = Agent(
        name="Briefer",
        system_prompt="You are a research director. Create concise, actionable research briefs that guide specialist analysts.",
        tools=[],
    )
    brief = briefer.run(dedent(f"""\
        Topic: {topic}
        Date: {today}
        Depth: {depth}

        Create a research brief that will be shared with 5 specialist analysts:
        1. Strategist (business/market), 2. Academic (scholarly), 3. Culture Analyst (social/anthropological),
        4. Tech Scout (technology), 5. Futurist (long-term trends/scenarios)

        The brief should:
        - Define the scope clearly
        - List 5-7 key questions each specialist should investigate
        - Identify any time-sensitive or context-specific considerations
        - Note potential blind spots to watch for

        Keep it to under 500 words — this is a briefing, not a report.
        {lang_instruction}"""))

    (output_dir / "brief.md").write_text(f"# Research Brief\n\n{brief}", encoding="utf-8")

    # --- Phase 2: Parallel Perspective Research ---
    # All 5 perspective agents run simultaneously
    print(f"\n[Phase 2] Parallel Perspective Research (5 agents)")

    agents = {
        "strategist": create_strategist(language),
        "academic": create_academic(language),
        "culture": create_culture_analyst(language),
        "tech": create_tech_scout(language),
        "futurist": create_futurist(language),
    }

    task_template = dedent(f"""\
        Research topic: {topic}
        Date: {today}

        Research Brief:
        {{brief}}

        Instructions:
        - Search thoroughly using {depth_config['queries']} different query angles
        - Target {depth_config['sources']} sources
        - Read full articles for the most important sources
        - Provide specific data, examples, and evidence
        - Include all source URLs
        {lang_instruction}""").replace("{brief}", brief)

    loop = asyncio.get_event_loop()
    futures = {
        name: loop.run_in_executor(None, agent.run, task_template)
        for name, agent in agents.items()
    }

    results = {}
    for name, future in futures.items():
        results[name] = await future

    # Save each perspective's findings
    for name, findings in results.items():
        (output_dir / f"perspective_{name}.md").write_text(
            f"# {agents[name].name} Perspective\n\n{findings}", encoding="utf-8"
        )

    # --- Phase 3: Synthesis ---
    print(f"\n[Phase 3] Synthesis")

    synthesizer = create_synthesizer(language)
    report = synthesizer.run(dedent(f"""\
        Write a comprehensive multi-perspective research report on: {topic}
        Date: {today}

        You have received analyses from 5 specialist perspectives:

        === STRATEGIST (Business & Market) ===
        {results['strategist']}

        === ACADEMIC (Scholarly Evidence) ===
        {results['academic']}

        === CULTURE ANALYST (Social & Cultural) ===
        {results['culture']}

        === TECH SCOUT (Technology & Innovation) ===
        {results['tech']}

        === FUTURIST (Long-term Trends & Scenarios) ===
        {results['futurist']}

        Synthesize all perspectives into a unified report.
        Highlight where perspectives agree, where they conflict, and what emerges from their combination.
        Include numbered citations [1], [2], etc. and a consolidated reference list.
        {lang_instruction}"""))

    # Save final report
    report_path = output_dir / "report.md"
    report_path.write_text(report, encoding="utf-8")

    print(f"\n{'='*60}")
    print(f"  Research Complete")
    print(f"{'='*60}")
    print(f"\n  Report: {report_path.resolve()}")
    print(f"  Files:")
    for f in sorted(output_dir.iterdir()):
        size = f.stat().st_size
        print(f"    - {f.name} ({size:,} bytes)")
    print(f"\n{'='*60}\n")

    # --- Phase 4: Convert to .docx ---
    print(f"\n[Phase 4] Word document conversion")
    docx_path = convert_to_docx(report_path)

    # --- Phase 5: Dashboard Registration ---
    print(f"\n[Phase 5] Research Dashboard registration")
    save_to_dashboard(topic, report, depth, language, docx_path)

    # Print preview
    preview = "\n".join(report.split("\n")[:30])
    print(preview)
    if len(report.split("\n")) > 30:
        print(f"\n... (full report: {report_path})")


# === Dashboard Integration ===

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
    tags = [f"depth:{depth}", "perspective-team", "auto-research"]
    tags.append("日本語" if language == "ja" else "English")
    category = _guess_category(topic)

    if docx_path and docx_path.exists():
        source = f"file://{docx_path.resolve()}"
    else:
        source = f"file://{Path('research_output/report.md').resolve()}"

    # Write report to temp file to avoid shell arg length limits
    import tempfile
    content_file = None
    try:
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8")
        tmp.write(report)
        tmp.close()
        content_file = tmp.name
    except Exception as e:
        print(f"  Temp file error: {e}")

    cmd = [
        "bash", str(save_script),
        "--title", topic,
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
        print(f"  Dashboard error: {result.stderr.strip()}")


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


def _guess_category(topic: str) -> str:
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


def _truncate(s: str, max_len: int) -> str:
    return s[:max_len] + "..." if len(s) > max_len else s


# === CLI ===

def main():
    parser = argparse.ArgumentParser(
        description="Perspective Research Team — 6 agents, multiple viewpoints, one integrated report",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=dedent("""\
            Examples:
              python3 perspective_team.py "生成AIの教育への影響"
              python3 perspective_team.py "量子コンピュータの現状" --depth deep
              python3 perspective_team.py "Climate change adaptation" --lang en
        """),
    )
    parser.add_argument("topic", help="Research topic")
    parser.add_argument("--depth", choices=["quick", "standard", "deep"], default="standard",
                        help="Research depth (default: standard)")
    parser.add_argument("--lang", choices=["ja", "en"], default="ja",
                        help="Report language (default: ja)")

    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY is not set.")
        print("  export ANTHROPIC_API_KEY='your-key-here'")
        sys.exit(1)

    asyncio.run(run_research(args.topic, args.depth, args.lang))


if __name__ == "__main__":
    main()
