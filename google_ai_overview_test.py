#!/usr/bin/env python3
"""
Google AI Overview Test Script
===============================
Tests Google AI Overview visibility using SerpAPI.

This script queries Google search via SerpAPI to check if AI Overview results
appear for specific queries and extracts relevant information.

Usage:
    python google_ai_overview_test.py

Requirements:
    pip install serpapi python-dotenv requests

Environment Variables (set in .env file or export):
    SERPAPI_API_KEY=your_serpapi_key
"""

import os
import sys
import json
import time
import logging
from pathlib import Path
from datetime import datetime
from serpapi import GoogleSearch

# Load environment variables from .env file if it exists
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Configure logging
LOG_FORMAT = '%(asctime)s - %(levelname)s - %(message)s'
logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('google_ai_overview_test.log', mode='a')
    ]
)
logger = logging.getLogger(__name__)

# ============================================================================
# CONFIGURATION
# ============================================================================

# Test queries (only 3 as requested)
TEST_QUERIES = [
    "How to hire developers from India",
    "Best platforms for hiring remote software engineers",
    "AI-powered talent platforms connecting companies with developers"
]

# Maximum retries for API calls
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_timestamp():
    """Get current timestamp in ISO format."""
    return datetime.now().isoformat()

def retry_with_backoff(func, max_retries=MAX_RETRIES, delay=RETRY_DELAY):
    """Retry a function with exponential backoff."""
    for attempt in range(max_retries):
        try:
            return func()
        except Exception as e:
            if attempt == max_retries - 1:
                logger.error(f"❌ Failed after {max_retries} attempts: {e}")
                raise
            wait_time = delay * (2 ** attempt)
            logger.warning(f"⚠️  Attempt {attempt + 1} failed: {e}. Retrying in {wait_time}s...")
            time.sleep(wait_time)
    return None

# ============================================================================
# SERPAPI QUERY FUNCTION
# ============================================================================

def query_google_ai_overview(query: str) -> dict:
    """
    Query Google search via SerpAPI and extract AI Overview information.
    
    Args:
        query: Search query string
        
    Returns:
        Dictionary containing AI Overview data and search results
    """
    api_key = os.getenv("SERPAPI_API_KEY")
    if not api_key:
        logger.error("❌ SERPAPI_API_KEY not found in environment variables")
        return {}
    
    def _query():
        params = {
            "q": query,
            "api_key": api_key,
            "engine": "google",
            "gl": "us",  # Country code (US)
            "hl": "en"   # Language (English)
        }
        
        search = GoogleSearch(params)
        results = search.get_dict()
        
        return results
    
    try:
        results = retry_with_backoff(_query)
        
        # Extract AI Overview information
        ai_overview_data = {
            "query": query,
            "timestamp": get_timestamp(),
            "has_ai_overview": False,
            "ai_overview_text": "",
            "ai_overview_links": [],
            "organic_results": [],
            "total_results": 0
        }
        
        # Check for AI Overview
        if "ai_overview" in results:
            ai_overview = results["ai_overview"]
            ai_overview_data["has_ai_overview"] = True
            
            # Extract AI Overview text
            if "text" in ai_overview:
                ai_overview_data["ai_overview_text"] = ai_overview["text"]
            
            # Extract links from AI Overview
            if "links" in ai_overview:
                ai_overview_data["ai_overview_links"] = [
                    {
                        "title": link.get("title", ""),
                        "url": link.get("url", "")
                    }
                    for link in ai_overview["links"]
                ]
        
        # Extract organic search results
        if "organic_results" in results:
            organic_results = results["organic_results"]
            ai_overview_data["total_results"] = len(organic_results)
            ai_overview_data["organic_results"] = [
                {
                    "position": result.get("position", 0),
                    "title": result.get("title", ""),
                    "link": result.get("link", ""),
                    "snippet": result.get("snippet", "")
                }
                for result in organic_results[:10]  # Top 10 results
            ]
        
        # Check for search information
        if "search_information" in results:
            search_info = results["search_information"]
            ai_overview_data["total_results_count"] = search_info.get("total_results", 0)
        
        return ai_overview_data
        
    except Exception as e:
        logger.error(f"❌ Error querying Google AI Overview for '{query}': {e}")
        return {
            "query": query,
            "timestamp": get_timestamp(),
            "error": str(e),
            "has_ai_overview": False
        }

# ============================================================================
# DASHBOARD GENERATION
# ============================================================================

def generate_html_dashboard(output_data: dict) -> str:
    """
    Generate a simplified HTML dashboard for Google AI Overview test results.
    
    Args:
        output_data: Dictionary containing test results
        
    Returns:
        HTML string for the dashboard
    """
    results = output_data.get("results", [])
    total_queries = output_data.get("total_queries", 0)
    queries_with_ai_overview = output_data.get("queries_with_ai_overview", 0)
    test_timestamp = output_data.get("test_timestamp", "")
    
    # Format timestamp for display
    try:
        dt = datetime.fromisoformat(test_timestamp.replace('Z', '+00:00'))
        formatted_date = dt.strftime("%B %d, %Y at %I:%M %p")
    except:
        formatted_date = test_timestamp
    
    # Calculate percentage
    ai_overview_percentage = (queries_with_ai_overview / total_queries * 100) if total_queries > 0 else 0
    
    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Google AI Overview Test Dashboard</title>
    <link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg-primary: #0a0a0f;
            --bg-secondary: #12121a;
            --bg-card: #1a1a24;
            --accent: #00ff88;
            --accent-dim: #00cc6a;
            --text-primary: #ffffff;
            --text-secondary: #8b8b9e;
            --text-muted: #5a5a6e;
            --border: #2a2a3a;
            --danger: #ff4757;
            --warning: #ffa502;
            --success: #00ff88;
        }}
        
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        
        body {{
            font-family: 'Space Grotesk', sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            min-height: 100vh;
            line-height: 1.6;
        }}
        
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            padding: 40px 24px;
        }}
        
        header {{
            text-align: center;
            margin-bottom: 60px;
            position: relative;
        }}
        
        header::before {{
            content: '';
            position: absolute;
            top: -100px;
            left: 50%;
            transform: translateX(-50%);
            width: 600px;
            height: 600px;
            background: radial-gradient(circle, rgba(0, 255, 136, 0.08) 0%, transparent 70%);
            pointer-events: none;
        }}
        
        .logo {{
            font-size: 14px;
            letter-spacing: 4px;
            color: var(--accent);
            text-transform: uppercase;
            margin-bottom: 16px;
        }}
        
        h1 {{
            font-size: 48px;
            font-weight: 700;
            margin-bottom: 12px;
            background: linear-gradient(135deg, #fff 0%, #00ff88 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }}
        
        .subtitle {{
            color: var(--text-secondary);
            font-size: 18px;
        }}
        
        .meta-info {{
            display: flex;
            justify-content: center;
            gap: 32px;
            margin-top: 24px;
            flex-wrap: wrap;
        }}
        
        .meta-item {{
            font-family: 'JetBrains Mono', monospace;
            font-size: 13px;
            color: var(--text-muted);
        }}
        
        .meta-item span {{
            color: var(--accent);
        }}
        
        /* Score Cards */
        .score-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 24px;
            margin-bottom: 48px;
        }}
        
        .score-card {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 16px;
            padding: 32px;
            position: relative;
            overflow: hidden;
            transition: transform 0.2s, border-color 0.2s;
        }}
        
        .score-card:hover {{
            transform: translateY(-4px);
            border-color: var(--accent);
        }}
        
        .score-card.primary {{
            border-color: var(--accent);
            background: linear-gradient(135deg, rgba(0, 255, 136, 0.1) 0%, var(--bg-card) 100%);
        }}
        
        .score-card .label {{
            font-size: 14px;
            color: var(--text-secondary);
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-bottom: 12px;
        }}
        
        .score-card .value {{
            font-size: 56px;
            font-weight: 700;
            line-height: 1;
            margin-bottom: 8px;
        }}
        
        .score-card .value.accent {{ color: var(--accent); }}
        .score-card .value.warning {{ color: var(--warning); }}
        .score-card .value.danger {{ color: var(--danger); }}
        
        .score-card .detail {{
            font-size: 14px;
            color: var(--text-muted);
        }}
        
        /* Query Results */
        .query-section {{
            margin-bottom: 48px;
        }}
        
        .query-card {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 16px;
            padding: 32px;
            margin-bottom: 24px;
        }}
        
        .query-header {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 24px;
            flex-wrap: wrap;
            gap: 16px;
        }}
        
        .query-text {{
            font-size: 20px;
            font-weight: 600;
            color: var(--text-primary);
            flex: 1;
        }}
        
        .ai-overview-badge {{
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 8px 16px;
            border-radius: 8px;
            font-size: 14px;
            font-weight: 500;
        }}
        
        .ai-overview-badge.success {{
            background: rgba(0, 255, 136, 0.1);
            color: var(--success);
            border: 1px solid rgba(0, 255, 136, 0.3);
        }}
        
        .ai-overview-badge.danger {{
            background: rgba(255, 71, 87, 0.1);
            color: var(--danger);
            border: 1px solid rgba(255, 71, 87, 0.3);
        }}
        
        .ai-overview-content {{
            background: var(--bg-secondary);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 24px;
            margin-bottom: 24px;
        }}
        
        .ai-overview-content h3 {{
            font-size: 16px;
            color: var(--accent);
            margin-bottom: 16px;
            text-transform: uppercase;
            letter-spacing: 1px;
        }}
        
        .ai-overview-text {{
            color: var(--text-secondary);
            line-height: 1.8;
            margin-bottom: 20px;
        }}
        
        .ai-overview-links {{
            margin-top: 20px;
        }}
        
        .ai-overview-links h4 {{
            font-size: 14px;
            color: var(--text-muted);
            margin-bottom: 12px;
            text-transform: uppercase;
            letter-spacing: 1px;
        }}
        
        .link-list {{
            list-style: none;
        }}
        
        .link-item {{
            margin-bottom: 12px;
        }}
        
        .link-item a {{
            color: var(--accent);
            text-decoration: none;
            font-size: 14px;
            transition: color 0.2s;
        }}
        
        .link-item a:hover {{
            color: var(--accent-dim);
            text-decoration: underline;
        }}
        
        .organic-results {{
            margin-top: 24px;
        }}
        
        .organic-results h3 {{
            font-size: 16px;
            color: var(--text-primary);
            margin-bottom: 16px;
            text-transform: uppercase;
            letter-spacing: 1px;
        }}
        
        .result-item {{
            background: var(--bg-secondary);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 16px;
            margin-bottom: 12px;
            transition: border-color 0.2s;
        }}
        
        .result-item:hover {{
            border-color: var(--accent);
        }}
        
        .result-position {{
            display: inline-block;
            width: 28px;
            height: 28px;
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 6px;
            text-align: center;
            line-height: 28px;
            font-family: 'JetBrains Mono', monospace;
            font-size: 12px;
            color: var(--text-muted);
            margin-right: 12px;
            vertical-align: top;
        }}
        
        .result-content {{
            display: inline-block;
            width: calc(100% - 45px);
            vertical-align: top;
        }}
        
        .result-title {{
            font-size: 16px;
            font-weight: 500;
            margin-bottom: 6px;
        }}
        
        .result-title a {{
            color: var(--accent);
            text-decoration: none;
        }}
        
        .result-title a:hover {{
            text-decoration: underline;
        }}
        
        .result-link {{
            font-size: 13px;
            color: var(--text-muted);
            font-family: 'JetBrains Mono', monospace;
            margin-bottom: 8px;
            word-break: break-all;
        }}
        
        .result-snippet {{
            font-size: 14px;
            color: var(--text-secondary);
            line-height: 1.6;
        }}
        
        .no-content {{
            color: var(--text-muted);
            font-style: italic;
            padding: 20px;
            text-align: center;
        }}
        
        @media (max-width: 768px) {{
            .container {{ padding: 24px 16px; }}
            h1 {{ font-size: 36px; }}
            .query-header {{ flex-direction: column; align-items: flex-start; }}
            .result-content {{ width: 100%; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="logo">Google AI Overview Test</div>
            <h1>Test Dashboard</h1>
            <p class="subtitle">AI Overview visibility analysis</p>
            <div class="meta-info">
                <div class="meta-item">Generated: <span>{formatted_date}</span></div>
                <div class="meta-item">Total Queries: <span>{total_queries}</span></div>
                <div class="meta-item">AI Overview Found: <span>{queries_with_ai_overview}</span></div>
            </div>
        </header>
        
        <!-- Summary Cards -->
        <div class="score-grid">
            <div class="score-card primary">
                <div class="label">AI Overview Coverage</div>
                <div class="value accent">{queries_with_ai_overview}/{total_queries}</div>
                <div class="detail">{ai_overview_percentage:.1f}% of queries show AI Overview</div>
            </div>
            <div class="score-card">
                <div class="label">Total Queries Tested</div>
                <div class="value">{total_queries}</div>
                <div class="detail">Queries analyzed</div>
            </div>
            <div class="score-card">
                <div class="label">Success Rate</div>
                <div class="value accent">{ai_overview_percentage:.0f}%</div>
                <div class="detail">Queries with AI Overview</div>
            </div>
        </div>
        
        <!-- Query Results -->
        <div class="query-section">
            <h2 style="font-size: 24px; margin-bottom: 24px; color: var(--text-primary);">Query Results</h2>
'''
    
    # Add each query result
    for i, result in enumerate(results, 1):
        query = result.get("query", "")
        has_ai_overview = result.get("has_ai_overview", False)
        ai_overview_text = result.get("ai_overview_text", "")
        ai_overview_links = result.get("ai_overview_links", [])
        organic_results = result.get("organic_results", [])
        total_results_count = result.get("total_results_count", 0)
        
        badge_class = "success" if has_ai_overview else "danger"
        badge_text = "✓ AI Overview Found" if has_ai_overview else "✗ No AI Overview"
        
        html += f'''
            <div class="query-card">
                <div class="query-header">
                    <div class="query-text">Query {i}: {query}</div>
                    <span class="ai-overview-badge {badge_class}">{badge_text}</span>
                </div>
'''
        
        # AI Overview content
        if has_ai_overview:
            html += '''
                <div class="ai-overview-content">
                    <h3>AI Overview</h3>
'''
            if ai_overview_text:
                html += f'<div class="ai-overview-text">{ai_overview_text}</div>'
            else:
                html += '<div class="no-content">AI Overview detected but no text content available</div>'
            
            if ai_overview_links:
                html += '''
                    <div class="ai-overview-links">
                        <h4>Sources ({len(ai_overview_links)})</h4>
                        <ul class="link-list">
'''
                for link in ai_overview_links:
                    title = link.get("title", "No title")
                    url = link.get("url", "#")
                    html += f'<li class="link-item"><a href="{url}" target="_blank">{title}</a></li>'
                html += '''
                        </ul>
                    </div>
'''
            html += '</div>'
        else:
            html += '''
                <div class="ai-overview-content">
                    <div class="no-content">No AI Overview was generated for this query</div>
                </div>
'''
        
        # Organic results
        if organic_results:
            html += f'''
                <div class="organic-results">
                    <h3>Top Organic Results ({len(organic_results)} shown)</h3>
'''
            for org_result in organic_results:
                position = org_result.get("position", 0)
                title = org_result.get("title", "No title")
                link = org_result.get("link", "#")
                snippet = org_result.get("snippet", "")
                
                html += f'''
                    <div class="result-item">
                        <span class="result-position">{position}</span>
                        <div class="result-content">
                            <div class="result-title"><a href="{link}" target="_blank">{title}</a></div>
                            <div class="result-link">{link}</div>
                            <div class="result-snippet">{snippet}</div>
                        </div>
                    </div>
'''
            html += '</div>'
        
        if total_results_count:
            html += f'<div style="margin-top: 16px; color: var(--text-muted); font-size: 13px;">Total search results: {total_results_count:,}</div>'
        
        html += '</div>'
    
    html += '''
        </div>
    </div>
</body>
</html>
'''
    
    return html

# ============================================================================
# MAIN EXECUTION
# ============================================================================

def main():
    """Main function to run Google AI Overview tests."""
    logger.info("=" * 60)
    logger.info("Google AI Overview Test Script")
    logger.info("=" * 60)
    
    # Check for API key
    if not os.getenv("SERPAPI_API_KEY"):
        logger.error("❌ SERPAPI_API_KEY not found. Please set it in your .env file or environment.")
        sys.exit(1)
    
    logger.info(f"✅ Starting tests with {len(TEST_QUERIES)} queries")
    logger.info("")
    
    # Run tests for each query
    all_results = []
    
    for i, query in enumerate(TEST_QUERIES, 1):
        logger.info(f"📝 Query {i}/{len(TEST_QUERIES)}: {query}")
        logger.info("-" * 60)
        
        result = query_google_ai_overview(query)
        all_results.append(result)
        
        # Log results
        if result.get("has_ai_overview"):
            logger.info("✅ AI Overview found!")
            if result.get("ai_overview_text"):
                preview = result["ai_overview_text"][:200] + "..." if len(result["ai_overview_text"]) > 200 else result["ai_overview_text"]
                logger.info(f"   Preview: {preview}")
            if result.get("ai_overview_links"):
                logger.info(f"   Links: {len(result['ai_overview_links'])}")
        else:
            logger.info("❌ No AI Overview found for this query")
        
        if result.get("total_results"):
            logger.info(f"   Organic results: {result['total_results']}")
        
        logger.info("")
        
        # Add delay between queries to avoid rate limiting
        if i < len(TEST_QUERIES):
            time.sleep(2)
    
    # Save results to JSON file
    output_data = {
        "test_timestamp": get_timestamp(),
        "total_queries": len(TEST_QUERIES),
        "queries_with_ai_overview": sum(1 for r in all_results if r.get("has_ai_overview")),
        "results": all_results
    }
    
    output_file = f"google_ai_overview_results_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json"
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)
    
    # Generate HTML dashboard
    logger.info("🎨 Generating HTML dashboard...")
    dashboard_html = generate_html_dashboard(output_data)
    
    dashboard_file = "google_ai_overview_dashboard.html"
    with open(dashboard_file, 'w', encoding='utf-8') as f:
        f.write(dashboard_html)
    
    logger.info(f"✅ Dashboard saved to {dashboard_file}")
    
    logger.info("=" * 60)
    logger.info("Test Summary")
    logger.info("=" * 60)
    logger.info(f"Total queries tested: {len(TEST_QUERIES)}")
    logger.info(f"Queries with AI Overview: {output_data['queries_with_ai_overview']}")
    logger.info(f"Results saved to: {output_file}")
    logger.info(f"Dashboard saved to: {dashboard_file}")
    logger.info("=" * 60)
    
    return output_data

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("\n⚠️  Test interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
