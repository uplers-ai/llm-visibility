#!/usr/bin/env python3
"""
LLM Visibility Audit Tool for Uplers
=====================================
Measures brand visibility for Uplers (AI-powered talent platform connecting 
global companies with pre-vetted developers from India) across multiple LLMs:
- ChatGPT (OpenAI)
- Claude (Anthropic)
- Gemini (Google)
- Grok (xAI)
- Perplexity

Features:
- Runs 50 prompts across 10 intent categories, 3x each for statistical reliability
- Generates HTML dashboard with visibility scores and competitor rankings
- Automatic screenshot capture of dashboard
- Email notifications with summary
- Historical comparison (week-over-week changes)
- Timestamped archives with configurable retention
- Error recovery with automatic retries
- Designed for weekly automated execution via cron

Usage:
    python visibility_audit2.0.py                    # Run audit
    python visibility_audit2.0.py --test-email      # Test email configuration
    python visibility_audit2.0.py --setup-cron      # Show cron setup instructions

Requirements:
    pip install openai anthropic google-generativeai requests python-dotenv playwright --break-system-packages
    playwright install chromium

Environment Variables (set in .env file or export):
    # LLM API Keys (set at least one)
    OPENAI_API_KEY=your_openai_key
    ANTHROPIC_API_KEY=your_anthropic_key
    GOOGLE_API_KEY=your_google_gemini_key
    XAI_API_KEY=your_xai_grok_key
    PERPLEXITY_API_KEY=your_perplexity_key
    
    # Email Configuration (optional, for notifications)
    SMTP_HOST=smtp.gmail.com
    SMTP_PORT=587
    SMTP_USER=your_email@gmail.com
    SMTP_PASSWORD=your_app_password
    EMAIL_TO=recipient@example.com
    
    # Archive Settings (optional)
    ARCHIVE_RETENTION_WEEKS=12
"""

import os
import sys
import json
import re
import time
import glob
import shutil
import smtplib
import logging
import argparse
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict
from urllib.parse import urlparse, urlsplit, urlunsplit, parse_qsl, urlencode
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from email.mime.base import MIMEBase
from email import encoders
import traceback
import requests

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
        logging.FileHandler('visibility_audit.log', mode='a')
    ]
)
logger = logging.getLogger(__name__)

# API Clients (will be initialized after checking keys)
openai_client = None
anthropic_client = None
gemini_model = None
xai_api_key = None
perplexity_api_key = None

# ============================================================================
# CONFIGURATION
# ============================================================================
TARGET_COMPANY = "Uplers"
TARGET_REGION = "USA"
RUNS_PER_PROMPT = 3

# Archive settings
ARCHIVE_DIR = "archives"
ARCHIVE_RETENTION_WEEKS = int(os.getenv("ARCHIVE_RETENTION_WEEKS", "12"))

# Retry settings for error recovery
MAX_RETRIES = 3
RETRY_DELAY = 5  # seconds

# Email settings
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
EMAIL_TO = os.getenv("EMAIL_TO", "")
EMAIL_ENABLED = bool(SMTP_USER and SMTP_PASSWORD and EMAIL_TO)

# LLM Enable/Disable settings (set to "false" to disable)
# Grok is disabled by default due to severe rate limits on free tier
ENABLE_CHATGPT = os.getenv("ENABLE_CHATGPT", "true").lower() == "true"
ENABLE_CLAUDE = os.getenv("ENABLE_CLAUDE", "true").lower() == "true"
ENABLE_GEMINI = os.getenv("ENABLE_GEMINI", "true").lower() == "true"
ENABLE_GROK = os.getenv("ENABLE_GROK", "true").lower() == "true"  # Enabled - paid API
ENABLE_PERPLEXITY = os.getenv("ENABLE_PERPLEXITY", "true").lower() == "true"  # Enabled - paid API

# Web-search-enabled variants. Real users frequently hit these modes (ChatGPT search,
# Gemini grounded, Claude with web search), and they produce different recommendations
# than the base chat models. Each adds API cost; default on but easy to disable.
ENABLE_CHATGPT_SEARCH = os.getenv("ENABLE_CHATGPT_SEARCH", "true").lower() == "true"
ENABLE_CLAUDE_SEARCH = os.getenv("ENABLE_CLAUDE_SEARCH", "true").lower() == "true"
ENABLE_GEMINI_SEARCH = os.getenv("ENABLE_GEMINI_SEARCH", "true").lower() == "true"

# Gemini-Search returns citations as opaque vertexaisearch redirect links. When enabled,
# each unique redirect is resolved (HTTP HEAD) once per run to recover the true page URL.
RESOLVE_GEMINI_REDIRECTS = os.getenv("RESOLVE_GEMINI_REDIRECTS", "true").lower() == "true"

# Target domain(s) used to flag "our" pages in citation/URL tracking.
TARGET_DOMAIN = "uplers.com"

# Auto-skip settings: Skip an LLM if it fails this many times consecutively
CONSECUTIVE_FAILURES_TO_SKIP = 3

# Track consecutive failures per LLM
llm_failure_counts = {}

# ============================================================================
# GOALS CONFIGURATION - Target visibility scores per LLM
# ============================================================================
GOALS = {
    "overall_visibility_score": 35,  # Target overall visibility (average of all LLMs)
    "overall_rank": 10,              # Target to be in top 10 ranking
    "by_llm": {
        "ChatGPT": 40,            # Target 40% visibility on ChatGPT
        "Claude": 25,             # Target 25% visibility on Claude
        "Gemini": 40,             # Target 40% visibility on Gemini
        "Grok": 25,               # Target 25% visibility on Grok
        "Perplexity": 40,         # Target 40% visibility on Perplexity
        "ChatGPT-Search": 40,     # Web-search variants
        "Claude-Search": 25,
        "Gemini-Search": 40,
    },
}

# Monthly comparison settings
MONTHS_TO_COMPARE = 3  # Compare last 3 months

# Known platform patterns to help with detection (will also find new ones dynamically)
KNOWN_PLATFORMS = [
    "Uplers", "Toptal", "Turing", "Andela", "Arc", "CloudDevs", 
    "Terminal", "Gun.io", "Lemon.io", "BairesDev", "Revelo",
    "Supersourcing", "Gigster", "Multiplier", "Remote", "Deel", 
    "Oyster", "Globalization Partners", "Fiverr", "Upwork", "Freelancer",
    "LinkedIn", "Indeed", "Hired", "Triplebyte", "Vettery", "Crossover",
    "X-Team", "Scalable Path", "Codementor", "RemoteOK", "We Work Remotely",
    "AngelList", "Stack Overflow", "GitHub Jobs", "Dice", "Naukri",
    "TalentScale", "Flexiple", "RemotePanda", "HackerRank", "CodeSignal"
]

# Intent categories with prompts
PROMPTS_BY_INTENT = {
    "Hiring Speed": [
        "Does hiring engineers fast mean I'm going to get bad candidates?",
        "What is the quickest way to hire software engineers in India?",
        "Speed vs quality trade-off in engineering hiring - how top startups solve it",
        "How do I hire an engineer fast?",
        "How long does it really take to hire a software engineer in 2026 in India?",
        "What's the most reliable way to go from job description to an engineer actually onboarded in two weeks as a US startup without going through a three-month recruiting process that kills your momentum?",
    ],
    "Founding Engineer": [
        "I am looking for startup-ready engineers who can actually build products from scratch - where do I find them?",
        "What is a founding engineer and what makes them different from a senior engineer?",
        "Founding engineer vs CTO - which do early-stage startups hire first?",
        "I'm a technical founder, we have three enterprise customers and revenue coming in, but it's just me building everything. I need someone who can own the codebase, make architectural decisions, and think like an owner not just someone who writes code when told to. How do I actually find that person?",
    ],
    "Product vs Service Background (India)": [
        "I want an India engineer who worked inside a product startup, not a services company - how do I filter for that?",
        "I'm a US startup, no Indian entity, I want two engineers in Bangalore who can work a couple hours of overlap with Eastern time. What's the simplest legal way?",
        "How to spot a product-minded engineer in a resume full of service-company experience",
        "How do I hire engineers from India as a US startup?",
        "Product vs service-background engineers - what is the difference?",
    ],
}

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def retry_with_backoff(func, max_retries=MAX_RETRIES, delay=RETRY_DELAY):
    """Decorator for retrying functions with exponential backoff."""
    def wrapper(*args, **kwargs):
        last_exception = None
        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_exception = e
                error_str = str(e).lower()
                
                # Longer wait for rate limit errors (429)
                if "429" in str(e) or "rate" in error_str or "exhausted" in error_str or "quota" in error_str:
                    wait_time = 30 * (2 ** attempt)  # Start with 30s for rate limits
                    logger.warning(f"Rate limit hit! Attempt {attempt + 1}/{max_retries}. Waiting {wait_time}s...")
                else:
                    wait_time = delay * (2 ** attempt)
                    logger.warning(f"Attempt {attempt + 1}/{max_retries} failed: {e}. Retrying in {wait_time}s...")
                
                time.sleep(wait_time)
        logger.error(f"All {max_retries} attempts failed for {func.__name__}: {last_exception}")
        return "", []
    return wrapper


def get_timestamp():
    """Get current timestamp for file naming."""
    return datetime.now().strftime("%Y-%m-%d")


def get_week_number():
    """Get ISO week number for weekly tracking."""
    return datetime.now().strftime("%Y-W%V")


def ensure_archive_dir():
    """Create archive directory if it doesn't exist."""
    Path(ARCHIVE_DIR).mkdir(parents=True, exist_ok=True)


def cleanup_old_archives():
    """Remove archives older than retention period."""
    ensure_archive_dir()
    cutoff_date = datetime.now() - timedelta(weeks=ARCHIVE_RETENTION_WEEKS)
    
    removed_count = 0
    for filepath in glob.glob(f"{ARCHIVE_DIR}/*"):
        try:
            # Extract date from filename
            filename = os.path.basename(filepath)
            date_match = re.search(r'(\d{4}-\d{2}-\d{2})', filename)
            if date_match:
                file_date = datetime.strptime(date_match.group(1), "%Y-%m-%d")
                if file_date < cutoff_date:
                    if os.path.isfile(filepath):
                        os.remove(filepath)
                    else:
                        shutil.rmtree(filepath)
                    removed_count += 1
                    logger.info(f"Removed old archive: {filename}")
        except Exception as e:
            logger.warning(f"Error processing archive {filepath}: {e}")
    
    if removed_count > 0:
        logger.info(f"Cleaned up {removed_count} old archive(s)")


def get_previous_results():
    """Load the most recent previous audit results for comparison."""
    ensure_archive_dir()
    
    # Find all previous result files
    result_files = sorted(glob.glob(f"{ARCHIVE_DIR}/audit_results_*.json"), reverse=True)
    
    if len(result_files) >= 1:
        # Get the most recent one (skip current if it exists)
        for filepath in result_files:
            try:
                with open(filepath, 'r') as f:
                    data = json.load(f)
                    # Extract date from filename
                    date_match = re.search(r'(\d{4}-\d{2}-\d{2})', os.path.basename(filepath))
                    if date_match:
                        data['_archive_date'] = date_match.group(1)
                    return data
            except Exception as e:
                logger.warning(f"Could not load {filepath}: {e}")
                continue
    
    return None


def get_monthly_results():
    """Load audit results from approximately 30 days ago for monthly comparison."""
    ensure_archive_dir()
    
    # Find all previous result files
    result_files = sorted(glob.glob(f"{ARCHIVE_DIR}/audit_results_*.json"), reverse=True)
    
    if not result_files:
        return None
    
    today = datetime.now().date()
    target_date = today - timedelta(days=30)
    
    best_match = None
    best_diff = float('inf')
    
    for filepath in result_files:
        try:
            # Extract date from filename
            date_match = re.search(r'(\d{4}-\d{2}-\d{2})', os.path.basename(filepath))
            if date_match:
                file_date = datetime.strptime(date_match.group(1), '%Y-%m-%d').date()
                diff = abs((file_date - target_date).days)
                
                # Look for files between 25-35 days ago (30 ± 5 days)
                if 25 <= (today - file_date).days <= 35 and diff < best_diff:
                    best_diff = diff
                    best_match = filepath
        except Exception as e:
            continue
    
    if best_match:
        try:
            with open(best_match, 'r') as f:
                data = json.load(f)
                date_match = re.search(r'(\d{4}-\d{2}-\d{2})', os.path.basename(best_match))
                if date_match:
                    data['_archive_date'] = date_match.group(1)
                logger.info(f"📅 Found monthly comparison data from {data.get('_archive_date', 'unknown')}")
                return data
        except Exception as e:
            logger.warning(f"Could not load monthly data {best_match}: {e}")
    
    return None


def get_historical_trend(days: int = 90):
    """Get historical data points for trend analysis over specified days."""
    ensure_archive_dir()
    
    result_files = sorted(glob.glob(f"{ARCHIVE_DIR}/audit_results_*.json"))
    
    if not result_files:
        return []
    
    today = datetime.now().date()
    cutoff_date = today - timedelta(days=days)
    
    trend_data = []
    
    for filepath in result_files:
        try:
            date_match = re.search(r'(\d{4}-\d{2}-\d{2})', os.path.basename(filepath))
            if date_match:
                file_date = datetime.strptime(date_match.group(1), '%Y-%m-%d').date()
                
                if file_date >= cutoff_date:
                    with open(filepath, 'r') as f:
                        data = json.load(f)
                        if "analysis" in data:
                            trend_data.append({
                                "date": date_match.group(1),
                                "visibility_score": data["analysis"]["overall"].get("visibility_score", 0),
                                "target_rank": data["analysis"]["overall"].get("target_rank", 999),
                                "mention_rate": data["analysis"]["overall"].get("mention_rate", 0)
                            })
        except Exception as e:
            continue
    
    return sorted(trend_data, key=lambda x: x["date"])


# ============================================================================
# GOALS TRACKING FUNCTIONS
# ============================================================================

def calculate_goal_progress(analysis: dict) -> dict:
    """Calculate progress toward visibility goals for each LLM."""
    progress = {
        "overall": {},
        "by_llm": {},
        "summary": {
            "achieved": 0,
            "in_progress": 0,
            "far": 0,
            "total": 0
        }
    }
    
    # Overall visibility score progress
    current_overall = analysis["overall"].get("visibility_score", 0)
    target_overall = GOALS.get("overall_visibility_score", 50)
    overall_percent = min(100, round((current_overall / target_overall) * 100, 1)) if target_overall > 0 else 0
    
    progress["overall"]["visibility_score"] = {
        "current": current_overall,
        "target": target_overall,
        "progress_percent": overall_percent,
        "remaining": max(0, target_overall - current_overall),
        "status": "achieved" if current_overall >= target_overall else "in_progress" if overall_percent >= 50 else "far"
    }
    
    # Overall rank progress
    current_rank = analysis["overall"].get("target_rank", 999)
    target_rank = GOALS.get("overall_rank", 10)
    # For rank, lower is better, so invert the calculation
    rank_progress = min(100, round((target_rank / current_rank) * 100, 1)) if current_rank > 0 else 0
    
    progress["overall"]["rank"] = {
        "current": current_rank,
        "target": target_rank,
        "progress_percent": rank_progress,
        "remaining": max(0, current_rank - target_rank),
        "status": "achieved" if current_rank <= target_rank else "in_progress" if current_rank <= target_rank * 2 else "far"
    }
    
    # Per-LLM visibility score progress
    llm_goals = GOALS.get("by_llm", {})
    for llm, data in analysis.get("by_llm", {}).items():
        current_score = data.get("visibility_score", 0)
        target_score = llm_goals.get(llm, 30)  # Default 30% if not specified
        percent_complete = min(100, round((current_score / target_score) * 100, 1)) if target_score > 0 else 0
        
        if current_score >= target_score:
            status = "achieved"
            progress["summary"]["achieved"] += 1
        elif percent_complete >= 50:
            status = "in_progress"
            progress["summary"]["in_progress"] += 1
        else:
            status = "far"
            progress["summary"]["far"] += 1
        
        progress["summary"]["total"] += 1
        
        progress["by_llm"][llm] = {
            "current": current_score,
            "target": target_score,
            "progress_percent": percent_complete,
            "remaining": max(0, round(target_score - current_score, 1)),
            "status": status,
            "mentions": data.get("mentions", 0),
            "queries": data.get("queries", 0)
        }
    
    return progress


def get_monthly_aggregates(months: int = 3) -> list:
    """Get monthly aggregated data for the last N months."""
    ensure_archive_dir()
    
    result_files = sorted(glob.glob(f"{ARCHIVE_DIR}/audit_results_*.json"))
    
    if not result_files:
        return []
    
    # Group results by month
    monthly_data = defaultdict(lambda: {
        "dates": [],
        "by_llm": defaultdict(lambda: {"visibility_scores": [], "mentions": [], "queries": []}),
        "overall": {"visibility_scores": [], "ranks": []}
    })
    
    for filepath in result_files:
        try:
            date_match = re.search(r'(\d{4}-\d{2}-\d{2})', os.path.basename(filepath))
            if date_match:
                file_date = datetime.strptime(date_match.group(1), '%Y-%m-%d').date()
                month_key = file_date.strftime("%Y-%m")  # e.g., "2026-01"
                
                with open(filepath, 'r') as f:
                    data = json.load(f)
                    if "analysis" in data:
                        analysis = data["analysis"]
                        monthly_data[month_key]["dates"].append(date_match.group(1))
                        
                        # Overall metrics
                        monthly_data[month_key]["overall"]["visibility_scores"].append(
                            analysis["overall"].get("visibility_score", 0)
                        )
                        monthly_data[month_key]["overall"]["ranks"].append(
                            analysis["overall"].get("target_rank", 999)
                        )
                        
                        # Per-LLM metrics
                        for llm, llm_data in analysis.get("by_llm", {}).items():
                            monthly_data[month_key]["by_llm"][llm]["visibility_scores"].append(
                                llm_data.get("visibility_score", 0)
                            )
                            monthly_data[month_key]["by_llm"][llm]["mentions"].append(
                                llm_data.get("mentions", 0)
                            )
                            monthly_data[month_key]["by_llm"][llm]["queries"].append(
                                llm_data.get("queries", 0)
                            )
        except Exception as e:
            logger.warning(f"Error loading monthly data from {filepath}: {e}")
            continue
    
    # Calculate averages for each month
    aggregated = []
    sorted_months = sorted(monthly_data.keys(), reverse=True)[:months]  # Get last N months
    
    for month_key in sorted(sorted_months):  # Sort chronologically
        month_info = monthly_data[month_key]
        
        # Calculate overall averages
        avg_visibility = round(sum(month_info["overall"]["visibility_scores"]) / len(month_info["overall"]["visibility_scores"]), 1) if month_info["overall"]["visibility_scores"] else 0
        avg_rank = round(sum(month_info["overall"]["ranks"]) / len(month_info["overall"]["ranks"]), 1) if month_info["overall"]["ranks"] else 999
        
        month_result = {
            "month": month_key,
            "month_display": datetime.strptime(month_key, "%Y-%m").strftime("%b %Y"),  # e.g., "Jan 2026"
            "audit_count": len(month_info["dates"]),
            "dates": month_info["dates"],
            "overall": {
                "avg_visibility_score": avg_visibility,
                "avg_rank": avg_rank
            },
            "by_llm": {}
        }
        
        # Calculate per-LLM averages
        for llm, llm_data in month_info["by_llm"].items():
            if llm_data["visibility_scores"]:
                month_result["by_llm"][llm] = {
                    "avg_visibility_score": round(sum(llm_data["visibility_scores"]) / len(llm_data["visibility_scores"]), 1),
                    "total_mentions": sum(llm_data["mentions"]),
                    "avg_mentions": round(sum(llm_data["mentions"]) / len(llm_data["mentions"]), 1),
                    "total_queries": sum(llm_data["queries"])
                }
        
        aggregated.append(month_result)
    
    return aggregated


def calculate_monthly_changes(monthly_aggregates: list) -> dict:
    """Calculate month-over-month changes."""
    if len(monthly_aggregates) < 2:
        return {"has_comparison": False}
    
    changes = {
        "has_comparison": True,
        "months": [m["month_display"] for m in monthly_aggregates],
        "overall": {},
        "by_llm": {}
    }
    
    # Get current and previous month
    current = monthly_aggregates[-1] if monthly_aggregates else None
    previous = monthly_aggregates[-2] if len(monthly_aggregates) >= 2 else None
    
    if current and previous:
        # Overall changes
        current_vis = current["overall"]["avg_visibility_score"]
        prev_vis = previous["overall"]["avg_visibility_score"]
        changes["overall"]["visibility"] = {
            "current": current_vis,
            "previous": prev_vis,
            "change": round(current_vis - prev_vis, 1),
            "direction": "up" if current_vis > prev_vis else "down" if current_vis < prev_vis else "same"
        }
        
        current_rank = current["overall"]["avg_rank"]
        prev_rank = previous["overall"]["avg_rank"]
        rank_change = prev_rank - current_rank  # Positive = improvement
        changes["overall"]["rank"] = {
            "current": current_rank,
            "previous": prev_rank,
            "change": round(rank_change, 1),
            "direction": "up" if rank_change > 0 else "down" if rank_change < 0 else "same"
        }
        
        # Per-LLM changes
        all_llms = set(current.get("by_llm", {}).keys()) | set(previous.get("by_llm", {}).keys())
        for llm in all_llms:
            curr_llm = current.get("by_llm", {}).get(llm, {})
            prev_llm = previous.get("by_llm", {}).get(llm, {})
            
            curr_vis = curr_llm.get("avg_visibility_score", 0)
            prev_vis_llm = prev_llm.get("avg_visibility_score", 0)
            vis_change = round(curr_vis - prev_vis_llm, 1)
            
            curr_mentions = curr_llm.get("total_mentions", 0)
            prev_mentions = prev_llm.get("total_mentions", 0)
            mentions_change = curr_mentions - prev_mentions
            
            changes["by_llm"][llm] = {
                "visibility": {
                    "current": curr_vis,
                    "previous": prev_vis_llm,
                    "change": vis_change,
                    "direction": "up" if vis_change > 0 else "down" if vis_change < 0 else "same"
                },
                "mentions": {
                    "current": curr_mentions,
                    "previous": prev_mentions,
                    "change": mentions_change,
                    "direction": "up" if mentions_change > 0 else "down" if mentions_change < 0 else "same"
                }
            }
    
    return changes


# ============================================================================
# API CLIENT INITIALIZATION
# ============================================================================

def initialize_clients():
    """Initialize API clients based on available keys."""
    global openai_client, anthropic_client, gemini_model, xai_api_key, perplexity_api_key
    
    clients_available = []
    
    # OpenAI (ChatGPT)
    if os.getenv("OPENAI_API_KEY") and ENABLE_CHATGPT:
        try:
            from openai import OpenAI
            openai_client = OpenAI()
            clients_available.append("OpenAI")
            logger.info("✅ OpenAI client initialized")
        except ImportError:
            logger.warning("⚠️  OpenAI package not installed. Run: pip install openai")
    elif os.getenv("OPENAI_API_KEY") and not ENABLE_CHATGPT:
        logger.info("⏭️  ChatGPT disabled (ENABLE_CHATGPT=false)")
    
    # Anthropic (Claude)
    if os.getenv("ANTHROPIC_API_KEY") and ENABLE_CLAUDE:
        try:
            import anthropic
            anthropic_client = anthropic.Anthropic()
            clients_available.append("Anthropic")
            logger.info("✅ Anthropic client initialized")
        except ImportError:
            logger.warning("⚠️  Anthropic package not installed. Run: pip install anthropic")
    elif os.getenv("ANTHROPIC_API_KEY") and not ENABLE_CLAUDE:
        logger.info("⏭️  Claude disabled (ENABLE_CLAUDE=false)")
    
    # Google (Gemini)
    if os.getenv("GOOGLE_API_KEY") and ENABLE_GEMINI:
        try:
            import google.generativeai as genai
            from google.generativeai.types import HarmCategory, HarmBlockThreshold
            
            genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
            
            # Disable all safety filters to prevent business/entity queries from being blocked
            safety_settings = {
                HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
            }

            # Use the same conversational system prompt as the other LLMs so that
            # Gemini visibility is measured on equivalent footing (was previously
            # configured as a JSON entity extractor, which produced non-comparable data).
            system_instruction = (
                f"You are a helpful assistant. The user is based in {TARGET_REGION}. "
                "When recommending platforms or companies, please be specific and name them."
            )

            gemini_model = genai.GenerativeModel(
                model_name='gemini-2.5-flash',
                safety_settings=safety_settings,
                system_instruction=system_instruction,
            )
            clients_available.append("Google")
            logger.info("✅ Google Gemini client initialized with 2026 model (gemini-2.5-flash)")
        except ImportError:
            logger.warning("⚠️  Google GenAI package not installed. Run: pip install google-generativeai")
    elif os.getenv("GOOGLE_API_KEY") and not ENABLE_GEMINI:
        logger.info("⏭️  Gemini disabled (ENABLE_GEMINI=false)")
    
    # xAI (Grok) - Disabled by default due to severe rate limits
    if os.getenv("XAI_API_KEY") and ENABLE_GROK:
        xai_api_key = os.getenv("XAI_API_KEY")
        clients_available.append("xAI")
        logger.info("✅ xAI Grok client initialized")
    elif os.getenv("XAI_API_KEY") and not ENABLE_GROK:
        logger.info("⏭️  xAI Grok disabled (ENABLE_GROK=false) - severe rate limits on free tier")
    
    # Perplexity
    if os.getenv("PERPLEXITY_API_KEY") and ENABLE_PERPLEXITY:
        perplexity_api_key = os.getenv("PERPLEXITY_API_KEY")
        clients_available.append("Perplexity")
        logger.info("✅ Perplexity client initialized")
    elif os.getenv("PERPLEXITY_API_KEY") and not ENABLE_PERPLEXITY:
        logger.info("⏭️  Perplexity disabled (ENABLE_PERPLEXITY=false)")
    
    return clients_available


# ============================================================================
# LLM QUERY FUNCTIONS (with retry logic)
# ============================================================================

def query_openai(prompt: str) -> tuple:
    """Query OpenAI GPT-4.1. Returns (text, citations). Base model has no citations."""
    if not openai_client:
        return "", []

    def _query():
        response = openai_client.chat.completions.create(
            model="gpt-4.1",
            messages=[
                {"role": "system", "content": f"You are a helpful assistant. The user is based in {TARGET_REGION}. When recommending platforms or companies, please be specific and name them."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=1500,
            temperature=0.7
        )
        return response.choices[0].message.content, []

    return retry_with_backoff(_query)()


def query_anthropic(prompt: str) -> tuple:
    """Query Anthropic Claude. Returns (text, citations). Base model has no citations."""
    if not anthropic_client:
        return "", []

    def _query():
        response = anthropic_client.messages.create(
            model="claude-sonnet-5",
            max_tokens=1500,
            system=f"You are a helpful assistant. The user is based in {TARGET_REGION}. When recommending platforms or companies, please be specific and name them.",
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        return response.content[0].text, []

    return retry_with_backoff(_query)()


def query_gemini(prompt: str) -> tuple:
    """Query Google Gemini. Returns (text, citations). Base model has no citations."""
    if not gemini_model:
        return "", []

    def _query():
        # Add delay to avoid rate limiting (Google free tier has strict limits)
        time.sleep(2)

        try:
            response = gemini_model.generate_content(prompt)

            # Check if the model actually returned a candidate
            if not response.candidates:
                logger.warning("⚠️  Gemini: No candidates returned. Prompt may have been blocked.")
                return "", []

            # Check the finish reason (1 = STOP/success, 3 = SAFETY, etc.)
            finish_reason = response.candidates[0].finish_reason
            if finish_reason != 1:  # 1 corresponds to 'STOP' (Success)
                logger.warning(f"⚠️  Gemini: Response incomplete. Finish reason: {finish_reason}")
                # Log safety ratings if it was blocked by a filter
                if finish_reason == 3:  # SAFETY
                    safety_ratings = response.candidates[0].safety_ratings
                    logger.warning(f"⚠️  Gemini: Safety Ratings: {safety_ratings}")
                return "", []

            if response.candidates[0].content.parts:
                return response.text, []
            else:
                logger.warning("⚠️  Gemini: Response parts are empty.")
                return "", []

        except Exception as e:
            logger.error(f"❌ Error querying Gemini: {e}")
            return "", []

    return retry_with_backoff(_query)()


def query_grok(prompt: str) -> tuple:
    """Query xAI Grok. Returns (text, citations). Base model has no citations."""
    if not xai_api_key:
        return "", []

    def _query():
        headers = {
            "Authorization": f"Bearer {xai_api_key}",
            "Content-Type": "application/json"
        }
        data = {
            "model": "grok-4-latest",
            "messages": [
                {"role": "system", "content": f"You are a helpful assistant. The user is based in {TARGET_REGION}. When recommending platforms or companies, please be specific and name them."},
                {"role": "user", "content": prompt}
            ],
            "max_tokens": 1500,
            "temperature": 0.7
        }
        response = requests.post(
            "https://api.x.ai/v1/chat/completions",
            headers=headers,
            json=data,
            timeout=120  # Increased timeout for Grok API
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"], []

    return retry_with_backoff(_query)()


def query_perplexity(prompt: str) -> tuple:
    """Query Perplexity AI. Returns (text, citations) — Perplexity always cites sources."""
    if not perplexity_api_key:
        return "", []

    def _query():
        headers = {
            "Authorization": f"Bearer {perplexity_api_key}",
            "Content-Type": "application/json"
        }
        data = {
            "model": "sonar-pro",
            "messages": [
                {"role": "system", "content": f"You are a helpful assistant. The user is based in {TARGET_REGION}. When recommending platforms or companies, please be specific and name them."},
                {"role": "user", "content": prompt}
            ],
            "max_tokens": 1500,
            "temperature": 0.7
        }
        response = requests.post(
            "https://api.perplexity.ai/chat/completions",
            headers=headers,
            json=data,
            timeout=60
        )
        response.raise_for_status()
        body = response.json()
        text = body["choices"][0]["message"]["content"]
        citations = []
        # Newer API: structured search_results [{title, url, date}]
        for sr in body.get("search_results") or []:
            if isinstance(sr, dict) and sr.get("url"):
                citations.append({"url": sr["url"], "title": sr.get("title")})
        # Legacy/also-present: citations is a flat list of URL strings
        for c in body.get("citations") or []:
            if isinstance(c, str):
                citations.append({"url": c, "title": None})
        return text, citations

    return retry_with_backoff(_query)()

# Curated platform patterns. Each value is a list of regex fragments that are
# anchored with \b...\b and matched case-insensitively. Brand names that collide
# with common English words (Arc, Remote, Indeed, Hired, Crossover, Shine, Monster,
# Dice, Lever, Multiplier, Greenhouse, Workable, Karat) are restricted to
# domain-anchored variants so we don't count incidental English usage.
_PLATFORM_PATTERN_SOURCES = {
    "Uplers": [r"uplers(?:\.com)?"],
    "Toptal": [r"toptal(?:\.com)?"],
    "Turing": [r"turing(?:\.com)?"],
    "Andela": [r"andela(?:\.com)?"],
    "CloudDevs": [r"clouddevs(?:\.com)?", r"cloud devs"],
    "Terminal.io": [r"terminal\.io"],
    "Gun.io": [r"gun\.io", r"gunio"],
    "Lemon.io": [r"lemon\.io"],
    "BairesDev": [r"bairesdev(?:\.com)?", r"baires dev"],
    "Revelo": [r"revelo(?:\.com)?"],
    "Supersourcing": [r"supersourcing", r"super sourcing"],
    "Gigster": [r"gigster(?:\.com)?"],
    "Deel": [r"deel\.com"],
    "Oyster": [r"oysterhr", r"oyster hr", r"oyster\.com"],
    "Globalization Partners": [r"globalization partners", r"g-p\.com"],
    "Fiverr": [r"fiverr(?:\.com)?"],
    "Upwork": [r"upwork(?:\.com)?"],
    "Freelancer.com": [r"freelancer\.com", r"freelancer\.in"],
    "LinkedIn": [r"linkedin(?:\.com)?"],
    "Triplebyte": [r"triplebyte"],
    "Vettery": [r"vettery"],
    "X-Team": [r"x-team", r"xteam"],
    "Scalable Path": [r"scalable ?path"],
    "Codementor": [r"codementor(?:x)?"],
    "RemoteOK": [r"remoteok", r"remote ok"],
    "We Work Remotely": [r"we work remotely", r"weworkremotely"],
    "AngelList / Wellfound": [r"angellist", r"angel list", r"wellfound"],
    "Naukri": [r"naukri(?:\.com)?"],
    "TalentScale": [r"talentscale", r"talent scale"],
    "Flexiple": [r"flexiple"],
    "RemotePanda": [r"remotepanda", r"remote panda"],
    "HackerRank": [r"hackerrank", r"hacker rank"],
    "CodeSignal": [r"codesignal", r"code signal"],
    "Talent500": [r"talent500", r"talent 500"],
    "Pesto": [r"pesto\.tech"],
    "GeeksforGeeks Jobs": [r"geeksforgeeks", r"gfg jobs"],
    "Instahyre": [r"instahyre"],
    "Hirect": [r"hirect"],
    "Cutshort": [r"cutshort"],
    "Hirist": [r"hirist"],
    "iimjobs": [r"iimjobs"],
    "Freshersworld": [r"freshersworld"],
    "Glassdoor": [r"glassdoor"],
    "ZipRecruiter": [r"ziprecruiter", r"zip recruiter"],
    "SimplyHired": [r"simplyhired", r"simply hired"],
    "CareerBuilder": [r"careerbuilder", r"career builder"],
    "Snaphunt": [r"snaphunt"],
    "Recruiterflow": [r"recruiterflow"],
    "Zoho Recruit": [r"zoho recruit"],
    "BambooHR": [r"bamboohr", r"bamboo hr"],
    "JazzHR": [r"jazzhr", r"jazz hr"],
    # Domain-anchored only — bare name is a common English word
    "Arc.dev": [r"arc\.dev"],
    "Remote.com": [r"remote\.com", r"remote\.co"],
    "Indeed.com": [r"indeed\.com"],
    "Hired.com": [r"hired\.com"],
    "Crossover": [r"crossover\.com"],
    "Shine.com": [r"shine\.com"],
    "Monster.com": [r"monster\.com", r"monster india"],
    "Dice.com": [r"dice\.com"],
    "Lever": [r"lever\.co"],
    "Multiplier": [r"multiplier\.com"],
    "Greenhouse": [r"greenhouse\.io"],
    "Workable": [r"workable\.com"],
    "Karat": [r"karat\.com", r"karat\.io"],
    "Stack Overflow Jobs": [r"stack overflow jobs", r"stackoverflow jobs"],
    "GitHub Jobs": [r"github jobs"],
}

PLATFORM_PATTERNS = {
    name: [re.compile(r"\b(?:" + p + r")\b", re.IGNORECASE) for p in patterns]
    for name, patterns in _PLATFORM_PATTERN_SOURCES.items()
}


def query_openai_search(prompt: str) -> tuple:
    """Query OpenAI GPT-4.1 with web_search. Returns (text, citations)."""
    if not openai_client:
        return "", []

    def _query():
        instructions = (
            f"You are a helpful assistant. The user is based in {TARGET_REGION}. "
            "When recommending platforms or companies, please be specific and name them."
        )
        response = openai_client.responses.create(
            model="gpt-4.1",
            tools=[{"type": "web_search_preview"}],
            instructions=instructions,
            input=prompt,
            max_output_tokens=1500,
        )
        # Text
        text = getattr(response, "output_text", None)
        if not text:
            chunks = []
            for item in getattr(response, "output", []) or []:
                for piece in getattr(item, "content", []) or []:
                    t = getattr(piece, "text", None)
                    if t:
                        chunks.append(t)
            text = "\n".join(chunks)
        # Citations: message content blocks carry url_citation annotations
        citations = []
        for item in getattr(response, "output", []) or []:
            for piece in getattr(item, "content", []) or []:
                for ann in getattr(piece, "annotations", []) or []:
                    url = getattr(ann, "url", None) or (ann.get("url") if isinstance(ann, dict) else None)
                    title = getattr(ann, "title", None) or (ann.get("title") if isinstance(ann, dict) else None)
                    if url:
                        citations.append({"url": url, "title": title})
        return text, citations

    return retry_with_backoff(_query)()


def query_anthropic_search(prompt: str) -> tuple:
    """Query Claude with web_search. Returns (text, citations)."""
    if not anthropic_client:
        return "", []

    def _query():
        response = anthropic_client.messages.create(
            model="claude-sonnet-5",
            max_tokens=1500,
            system=(
                f"You are a helpful assistant. The user is based in {TARGET_REGION}. "
                "When recommending platforms or companies, please be specific and name them."
            ),
            messages=[{"role": "user", "content": prompt}],
            tools=[{
                "type": "web_search_20260209",
                "name": "web_search",
                "max_uses": 5,
            }],
        )
        chunks = []
        citations = []
        for block in response.content:
            btype = getattr(block, "type", None)
            # Text blocks (and their inline citations)
            text = getattr(block, "text", None)
            if text:
                chunks.append(text)
            for cit in getattr(block, "citations", []) or []:
                url = getattr(cit, "url", None)
                title = getattr(cit, "title", None)
                if url:
                    citations.append({"url": url, "title": title})
            # web_search_tool_result blocks list the fetched sources
            if btype == "web_search_tool_result":
                inner = getattr(block, "content", None) or []
                for r in inner:
                    url = getattr(r, "url", None)
                    title = getattr(r, "title", None)
                    if url:
                        citations.append({"url": url, "title": title})
        return "\n".join(chunks), citations

    return retry_with_backoff(_query)()


def query_gemini_search(prompt: str) -> tuple:
    """Query Gemini with Google Search grounding (new google-genai SDK).

    Returns (text, citations). Citations come from grounding_metadata; their URLs
    are vertexaisearch redirects that get resolved downstream.
    """
    if not gemini_model:  # base Gemini must be available (shares the same key)
        return "", []

    def _query():
        time.sleep(2)  # Google free tier rate limits
        try:
            from google import genai as google_genai
            from google.genai import types as genai_types
        except ImportError:
            logger.warning("⚠️  google-genai package not installed; skipping Gemini-Search. "
                           "Run: pip install google-genai")
            return "", []

        try:
            client = google_genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    system_instruction=(
                        f"You are a helpful assistant. The user is based in {TARGET_REGION}. "
                        "When recommending platforms or companies, please be specific and name them."
                    ),
                    tools=[genai_types.Tool(google_search=genai_types.GoogleSearch())],
                ),
            )
            text = response.text or ""
            citations = []
            for cand in getattr(response, "candidates", []) or []:
                gm = getattr(cand, "grounding_metadata", None)
                for chunk in getattr(gm, "grounding_chunks", []) or []:
                    web = getattr(chunk, "web", None)
                    if web is None:
                        continue
                    uri = getattr(web, "uri", None)
                    title = getattr(web, "title", None)  # usually the real domain
                    if uri:
                        citations.append({"url": uri, "title": title})
            return text, citations
        except Exception as e:
            logger.error(f"❌ Error querying Gemini-Search: {e}")
            return "", []

    return retry_with_backoff(_query)()


def extract_companies(text: str) -> dict:
    """Return {platform_name: mention_count} for the curated platform list.

    Word-boundary regex matching; ambiguous brand names (Arc, Remote, Indeed, etc.)
    are restricted to domain-anchored variants to avoid false positives.
    """
    if not text:
        return {}
    mentions = {}
    for name, patterns in PLATFORM_PATTERNS.items():
        count = sum(len(p.findall(text)) for p in patterns)
        if count > 0:
            mentions[name] = count
    return mentions


def extract_company_positions(text: str) -> list:
    """Return platforms in order of first appearance in the response.

    Drives the position-weighted Share of Voice metric — earlier mention = stronger
    signal that the LLM is recommending that platform first.
    """
    if not text:
        return []
    first_offsets = {}
    for name, patterns in PLATFORM_PATTERNS.items():
        earliest = None
        for p in patterns:
            m = p.search(text)
            if m and (earliest is None or m.start() < earliest):
                earliest = m.start()
        if earliest is not None:
            first_offsets[name] = earliest
    return [name for name, _ in sorted(first_offsets.items(), key=lambda x: x[1])]


# ============================================================================
# URL / CITATION TRACKING
# ============================================================================
# Cache of resolved Gemini redirect URLs, deduped across a run (thread-safe enough:
# worst case a redirect is resolved twice, which is harmless).
_redirect_cache = {}

# Match full URLs and bare domains in prose. TLD list kept tight to limit noise.
_URL_RE = re.compile(
    r'(https?://[^\s<>"\')\]]+'                          # full URLs
    r'|\b(?:[a-z0-9-]+\.)+(?:com|io|dev|co|ai|tech|in|org|net)\b'  # bare domains
    r'(?:/[^\s<>"\')\]]*)?)',                            # optional path on bare domains
    re.IGNORECASE,
)

_TRACKING_PARAMS = {"ref", "fbclid", "gclid", "msclkid", "mc_cid", "mc_eid", "igshid"}


def extract_urls(text: str) -> list:
    """Extract candidate URLs / bare domains typed in prose."""
    if not text:
        return []
    out = []
    for m in _URL_RE.finditer(text):
        raw = m.group(0).rstrip('.,);:]\'"')
        # Skip obvious non-links (e.g. "e.g", version numbers handled by TLD list)
        if len(raw) < 4:
            continue
        out.append(raw)
    return out


def normalize_url(raw: str) -> dict:
    """Return {'url': canonical, 'domain': registrable-ish host} or None if unusable.

    Lowercases host, drops www., strips tracking params, removes trailing slash,
    keeps the full path (page-level is the goal), and adds a scheme to bare domains.
    """
    if not raw or not isinstance(raw, str):
        return None
    raw = raw.strip()
    if not raw:
        return None
    if not re.match(r'^https?://', raw, re.IGNORECASE):
        raw = "https://" + raw
    try:
        parts = urlsplit(raw)
    except Exception:
        return None
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if not host or "." not in host:
        return None
    # Strip tracking query params
    query = urlencode([
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=False)
        if k.lower() not in _TRACKING_PARAMS and not k.lower().startswith("utm_")
    ])
    path = parts.path or ""
    if path == "/":
        path = ""
    elif path.endswith("/"):
        path = path.rstrip("/")
    canonical = urlunsplit(("https", host, path, query, ""))
    return {"url": canonical, "domain": host}


def resolve_redirect(url: str) -> str:
    """Resolve a Gemini vertexaisearch redirect to its true destination URL.

    Deduped/cached per run; best-effort with a short timeout. Returns the original
    URL on any failure so callers can still fall back to domain-level data.
    """
    if not url:
        return url
    if "vertexaisearch.cloud.google.com" not in url and "grounding-api-redirect" not in url:
        return url
    if not RESOLVE_GEMINI_REDIRECTS:
        return url
    if url in _redirect_cache:
        return _redirect_cache[url]
    final = url
    try:
        resp = requests.head(url, allow_redirects=True, timeout=8)
        if resp.url:
            final = resp.url
    except Exception:
        try:
            # Some redirects only fire on GET
            resp = requests.get(url, allow_redirects=True, timeout=8, stream=True)
            if resp.url:
                final = resp.url
            resp.close()
        except Exception:
            final = url
    _redirect_cache[url] = final
    return final


def _is_target_domain(domain: str) -> bool:
    return bool(domain) and (domain == TARGET_DOMAIN or domain.endswith("." + TARGET_DOMAIN))


def build_url_records(response_text: str, citations: list) -> list:
    """Merge structured citations + inline prose URLs into normalized, deduped records.

    Each record: {url, domain, title, source ('citation'|'inline'), is_target}.
    Citations win over inline duplicates. Gemini redirects are resolved to real pages.
    """
    records = {}  # canonical url -> record

    def _add(raw_url, title, source):
        if not raw_url:
            return
        # Resolve Gemini redirect links to their true destination first
        if "grounding-api-redirect" in raw_url or "vertexaisearch.cloud.google.com" in raw_url:
            resolved = resolve_redirect(raw_url)
            if "vertexaisearch.cloud.google.com" in resolved or "grounding-api-redirect" in resolved:
                # Resolution failed/disabled — fall back to the title, which Gemini
                # populates with the real domain (e.g. "uplers.com").
                if title and re.match(r'^(?:[a-z0-9-]+\.)+[a-z]{2,}$', title.strip().lower()):
                    raw_url = title.strip().lower()
                else:
                    return  # opaque redirect with no usable domain — skip
            else:
                raw_url = resolved
        norm = normalize_url(raw_url)
        if not norm:
            return
        key = norm["url"]
        existing = records.get(key)
        if existing is None:
            records[key] = {
                "url": norm["url"],
                "domain": norm["domain"],
                "title": (title or "").strip() or None,
                "source": source,
                "is_target": _is_target_domain(norm["domain"]),
            }
        else:
            # citation beats inline; fill in a title if we now have one
            if source == "citation" and existing["source"] == "inline":
                existing["source"] = "citation"
            if title and not existing.get("title"):
                existing["title"] = title.strip()

    for c in citations or []:
        if isinstance(c, dict):
            _add(c.get("url"), c.get("title"), "citation")
        elif isinstance(c, str):
            _add(c, None, "citation")

    for raw in extract_urls(response_text):
        _add(raw, None, "inline")

    return list(records.values())


_SENTIMENT_POSITIVE = {
    "best", "top", "leading", "excellent", "strong", "recommended", "recommend",
    "great", "trusted", "reliable", "premier", "preferred", "rigorous", "robust",
    "high-quality", "vetted", "proven", "popular", "outstanding", "favourite",
    "favorite", "go-to", "ideal", "powerful", "innovative",
}
_SENTIMENT_NEGATIVE = {
    "avoid", "poor", "weak", "slow", "expensive", "unreliable", "limited",
    "lacking", "outdated", "inferior", "questionable", "spotty", "shaky",
    "mediocre", "subpar", "concerns", "concern", "issues", "downside", "cons",
}


def _rule_based_sentiment(response_text: str) -> str:
    """Cheap keyword-window fallback when no LLM is available for classification."""
    if not response_text:
        return None
    lower = response_text.lower()
    needle = TARGET_COMPANY.lower()
    pos_score = neg_score = 0
    start = 0
    while True:
        idx = lower.find(needle, start)
        if idx == -1:
            break
        window = lower[max(0, idx - 150):idx + 150]
        for w in _SENTIMENT_POSITIVE:
            pos_score += window.count(w)
        for w in _SENTIMENT_NEGATIVE:
            neg_score += window.count(w)
        start = idx + len(needle)
    if pos_score > neg_score:
        return "positive"
    if neg_score > pos_score:
        return "negative"
    return "neutral"


def classify_target_sentiment(response_text: str) -> str:
    """Classify how the response talks about the target brand (positive/neutral/negative).

    Uses a cheap OpenAI call when available, otherwise falls back to a keyword-window
    heuristic. Returns None if no signal can be derived.
    """
    if not response_text or TARGET_COMPANY.lower() not in response_text.lower():
        return None

    if openai_client:
        try:
            classification = openai_client.chat.completions.create(
                model="gpt-4.1-mini",
                temperature=0,
                max_tokens=4,
                messages=[
                    {"role": "system", "content": (
                        f"Classify how the following text discusses '{TARGET_COMPANY}'. "
                        "Reply with exactly one word: positive, neutral, or negative."
                    )},
                    {"role": "user", "content": response_text[:4000]},
                ],
            )
            label = (classification.choices[0].message.content or "").strip().lower()
            if label in ("positive", "neutral", "negative"):
                return label
        except Exception as e:
            logger.debug(f"Sentiment LLM call failed, falling back to heuristic: {e}")

    return _rule_based_sentiment(response_text)


def run_single_query(llm_name: str, prompt: str, intent: str, run_num: int):
    """Run a single query and return results."""
    global llm_failure_counts
    
    query_funcs = {
        "ChatGPT": query_openai,
        "Claude": query_anthropic,
        "Gemini": query_gemini,
        "Grok": query_grok,
        "Perplexity": query_perplexity,
        "ChatGPT-Search": query_openai_search,
        "Claude-Search": query_anthropic_search,
        "Gemini-Search": query_gemini_search,
    }
    
    # Check if this LLM should be skipped due to consecutive failures
    if llm_failure_counts.get(llm_name, 0) >= CONSECUTIVE_FAILURES_TO_SKIP:
        # Return empty result - LLM is being skipped
        return {
            "llm": llm_name,
            "intent": intent,
            "prompt": prompt,
            "run": run_num,
            "response": "",
            "companies_mentioned": {},
            "companies_ranked": [],
            "target_mentioned": False,
            "target_rank_in_response": None,
            "target_sentiment": None,
            "urls": [],
            "citations": [],
            "timestamp": datetime.now().isoformat(),
            "skipped": True
        }

    response, citations = query_funcs[llm_name](prompt)
    companies = extract_companies(response)
    ranked = extract_company_positions(response)
    urls = build_url_records(response, citations)

    # Track failures for auto-skip
    if not response:
        llm_failure_counts[llm_name] = llm_failure_counts.get(llm_name, 0) + 1
        if llm_failure_counts[llm_name] == CONSECUTIVE_FAILURES_TO_SKIP:
            logger.warning(f"⏭️  Skipping {llm_name} for remaining queries ({CONSECUTIVE_FAILURES_TO_SKIP} consecutive failures)")
    else:
        # Reset failure count on success
        llm_failure_counts[llm_name] = 0

    target_mentioned = TARGET_COMPANY in companies
    target_rank_in_response = (ranked.index(TARGET_COMPANY) + 1) if TARGET_COMPANY in ranked else None
    target_sentiment = classify_target_sentiment(response) if target_mentioned else None

    return {
        "llm": llm_name,
        "intent": intent,
        "prompt": prompt,
        "run": run_num,
        "response": response,
        "companies_mentioned": companies,
        "companies_ranked": ranked,
        "target_mentioned": target_mentioned,
        "target_rank_in_response": target_rank_in_response,
        "target_sentiment": target_sentiment,
        "urls": urls,
        "citations": citations,
        "timestamp": datetime.now().isoformat()
    }

def run_audit():
    """Run the complete visibility audit."""
    print("\n" + "="*60)
    print("🔍 LLM VISIBILITY AUDIT FOR UPLERS")
    print("="*60)
    
    # Initialize clients
    available_clients = initialize_clients()
    if not available_clients:
        print("\n❌ No API clients available. Please set at least one environment variable:")
        print("   export OPENAI_API_KEY=your_key       # For ChatGPT")
        print("   export ANTHROPIC_API_KEY=your_key    # For Claude")
        print("   export GOOGLE_API_KEY=your_key       # For Gemini")
        print("   export XAI_API_KEY=your_key          # For Grok")
        print("   export PERPLEXITY_API_KEY=your_key   # For Perplexity")
        return None
    
    print(f"\n✅ Available LLMs: {', '.join(available_clients)}")
    
    # Determine which LLMs to query
    llms_to_query = []
    if "OpenAI" in available_clients:
        llms_to_query.append("ChatGPT")
        if ENABLE_CHATGPT_SEARCH:
            llms_to_query.append("ChatGPT-Search")
    if "Anthropic" in available_clients:
        llms_to_query.append("Claude")
        if ENABLE_CLAUDE_SEARCH:
            llms_to_query.append("Claude-Search")
    if "Google" in available_clients:
        llms_to_query.append("Gemini")
        if ENABLE_GEMINI_SEARCH:
            llms_to_query.append("Gemini-Search")
    if "xAI" in available_clients:
        llms_to_query.append("Grok")
    if "Perplexity" in available_clients:
        llms_to_query.append("Perplexity")
    
    # Flatten prompts
    all_prompts = []
    for intent, prompts in PROMPTS_BY_INTENT.items():
        for prompt in prompts:
            all_prompts.append((intent, prompt))
    
    total_queries = len(all_prompts) * len(llms_to_query) * RUNS_PER_PROMPT
    print(f"📊 Running {total_queries} queries ({len(all_prompts)} prompts × {len(llms_to_query)} LLMs × {RUNS_PER_PROMPT} runs)")
    print(f"⏱️  Estimated time: {total_queries * 2 // 60} - {total_queries * 4 // 60} minutes\n")
    
    # Fan out across LLMs (per-LLM rate limits are independent) while keeping
    # runs for the same LLM serial — sequential runs help respect each provider's
    # rate window and preserve the auto-skip-on-consecutive-failures logic.
    from concurrent.futures import ThreadPoolExecutor, as_completed

    results = []
    completed = 0
    lock_print = __import__('threading').Lock()

    def _run_llm_sequence(llm, intent, prompt):
        rows = []
        for run_num in range(1, RUNS_PER_PROMPT + 1):
            try:
                rows.append(run_single_query(llm, prompt, intent, run_num))
            except Exception as e:
                with lock_print:
                    print(f"Error in {llm} for '{prompt[:40]}...': {e}")
                    traceback.print_exc()
        return rows

    with ThreadPoolExecutor(max_workers=max(1, len(llms_to_query))) as pool:
        for intent, prompt in all_prompts:
            futures = {
                pool.submit(_run_llm_sequence, llm, intent, prompt): llm
                for llm in llms_to_query
            }
            for fut in as_completed(futures):
                llm = futures[fut]
                rows = fut.result()
                results.extend(rows)
                with lock_print:
                    for result in rows:
                        completed += 1
                        target_status = "✓" if result["target_mentioned"] else "✗"
                        platforms_found = list(result["companies_mentioned"].keys())[:5]
                        platforms_str = ", ".join(platforms_found) if platforms_found else "None"
                        print(f"[{completed}/{total_queries}] {llm:16} | {intent[:20]:20} | Target: {target_status} | Found: {platforms_str}")

    return results

def analyze_results(results: list) -> dict:
    """Analyze results and compute metrics."""
    if not results:
        return {}
    
    analysis = {
        "meta": {
            "target_company": TARGET_COMPANY,
            "total_queries": len(results),
            "unique_prompts": len(set(r["prompt"] for r in results)),
            "llms_tested": list(set(r["llm"] for r in results)),
            "runs_per_prompt": RUNS_PER_PROMPT,
            "generated_at": datetime.now().isoformat()
        },
        "overall": {},
        "by_llm": {},
        "by_intent": {},
        "company_rankings": {},
        "weak_spots": []
    }
    
    # Overall metrics
    target_mentions = sum(1 for r in results if r["target_mentioned"])
    analysis["overall"]["visibility_score"] = round(target_mentions / len(results) * 100, 1)
    analysis["overall"]["target_mentions"] = target_mentions
    analysis["overall"]["total_queries"] = len(results)
    
    # By LLM
    for llm in analysis["meta"]["llms_tested"]:
        llm_results = [r for r in results if r["llm"] == llm]
        mentions = sum(1 for r in llm_results if r["target_mentioned"])
        analysis["by_llm"][llm] = {
            "visibility_score": round(mentions / len(llm_results) * 100, 1) if llm_results else 0,
            "mentions": mentions,
            "queries": len(llm_results)
        }
    
    # By Intent
    intents = set(r["intent"] for r in results)
    for intent in intents:
        intent_results = [r for r in results if r["intent"] == intent]
        mentions = sum(1 for r in intent_results if r["target_mentioned"])
        visibility = round(mentions / len(intent_results) * 100, 1) if intent_results else 0
        analysis["by_intent"][intent] = {
            "visibility_score": visibility,
            "mentions": mentions,
            "queries": len(intent_results)
        }
        
        # Identify weak spots (visibility < 20%)
        if visibility < 20:
            analysis["weak_spots"].append({
                "intent": intent,
                "visibility": visibility,
                "sample_prompts": list(set(r["prompt"] for r in intent_results))[:3]
            })
    
    # Sentiment aggregation for target mentions
    sentiment_counts = defaultdict(int)
    for r in results:
        s = r.get("target_sentiment")
        if s:
            sentiment_counts[s] += 1
    total_with_sentiment = sum(sentiment_counts.values())
    analysis["overall"]["sentiment"] = {
        "positive": sentiment_counts.get("positive", 0),
        "neutral": sentiment_counts.get("neutral", 0),
        "negative": sentiment_counts.get("negative", 0),
        "scored_mentions": total_with_sentiment,
    }

    def _aggregate_company_metrics(rows):
        counts = defaultdict(int)
        sov_score = defaultdict(float)
        for row in rows:
            for company, count in row["companies_mentioned"].items():
                counts[company] += count
            for rank, company in enumerate(row.get("companies_ranked") or [], start=1):
                # Position decay: 1/rank — first mention = 1.0, second = 0.5, etc.
                sov_score[company] += 1.0 / rank
        total_sov = sum(sov_score.values()) or 1.0
        ranked = sorted(
            counts.keys() | sov_score.keys(),
            key=lambda c: (sov_score[c], counts[c]),
            reverse=True,
        )
        return [
            {
                "company": c,
                "mentions": counts[c],
                "sov_score": round(sov_score[c], 3),
                "sov_share": round(sov_score[c] / total_sov * 100, 2),
                "rank": i + 1,
            }
            for i, c in enumerate(ranked)
        ]

    overall_rankings = _aggregate_company_metrics(results)
    analysis["company_rankings"]["overall"] = overall_rankings

    target_rank = next(
        (entry["rank"] for entry in overall_rankings if entry["company"] == TARGET_COMPANY),
        len(overall_rankings) + 1,
    )
    target_sov = next(
        (entry["sov_share"] for entry in overall_rankings if entry["company"] == TARGET_COMPANY),
        0.0,
    )
    analysis["overall"]["target_rank"] = target_rank
    analysis["overall"]["target_sov_share"] = target_sov
    analysis["overall"]["total_companies_mentioned"] = len(overall_rankings)

    # Average rank-when-mentioned (lower = better, only counts responses where target appeared)
    ranks_when_mentioned = [
        r["target_rank_in_response"]
        for r in results
        if r.get("target_rank_in_response")
    ]
    analysis["overall"]["avg_rank_when_mentioned"] = (
        round(sum(ranks_when_mentioned) / len(ranks_when_mentioned), 2)
        if ranks_when_mentioned else None
    )

    # Per-LLM rankings + SoV
    for llm in analysis["meta"]["llms_tested"]:
        llm_results = [r for r in results if r["llm"] == llm]
        llm_rankings = _aggregate_company_metrics(llm_results)
        analysis["company_rankings"][llm] = llm_rankings

        llm_sov = next(
            (e["sov_share"] for e in llm_rankings if e["company"] == TARGET_COMPANY),
            0.0,
        )
        analysis["by_llm"][llm]["sov_share"] = llm_sov

        llm_ranks = [
            r["target_rank_in_response"]
            for r in llm_results
            if r.get("target_rank_in_response")
        ]
        analysis["by_llm"][llm]["avg_rank_when_mentioned"] = (
            round(sum(llm_ranks) / len(llm_ranks), 2) if llm_ranks else None
        )

    # ------------------------------------------------------------------
    # URL / page citation aggregation
    # ------------------------------------------------------------------
    def _aggregate_urls(rows):
        """Aggregate per-result url records into url-level and domain-level views."""
        by_url = {}      # canonical url -> aggregate
        by_domain = {}   # domain -> aggregate
        for row in rows:
            llm = row.get("llm")
            prompt = row.get("prompt")
            seen_this_row = set()  # count once per response, not per duplicate
            for rec in row.get("urls") or []:
                url = rec.get("url")
                domain = rec.get("domain")
                if not url or url in seen_this_row:
                    continue
                seen_this_row.add(url)
                u = by_url.setdefault(url, {
                    "url": url, "domain": domain, "title": rec.get("title"),
                    "count": 0, "channels": set(), "sources": set(),
                    "sample_queries": [], "is_target": rec.get("is_target", False),
                })
                u["count"] += 1
                if llm:
                    u["channels"].add(llm)
                if rec.get("source"):
                    u["sources"].add(rec["source"])
                if prompt and len(u["sample_queries"]) < 3 and prompt not in u["sample_queries"]:
                    u["sample_queries"].append(prompt)
                if not u.get("title") and rec.get("title"):
                    u["title"] = rec["title"]

                d = by_domain.setdefault(domain, {
                    "domain": domain, "count": 0, "channels": set(),
                    "is_target": rec.get("is_target", False),
                })
                d["count"] += 1
                if llm:
                    d["channels"].add(llm)

        def _finalize(d):
            out = dict(d)
            out["channels"] = sorted(d["channels"])
            if "sources" in d:
                out["sources"] = sorted(d["sources"])
            return out

        urls_sorted = sorted(by_url.values(), key=lambda x: x["count"], reverse=True)
        domains_sorted = sorted(by_domain.values(), key=lambda x: x["count"], reverse=True)
        return [_finalize(u) for u in urls_sorted], [_finalize(d) for d in domains_sorted]

    all_urls, all_domains = _aggregate_urls(results)
    target_pages = [u for u in all_urls if u.get("is_target")]
    analysis["pages"] = {
        "target": target_pages,
        "all_urls": all_urls,
        "domains": all_domains,
    }
    analysis["overall"]["unique_target_pages"] = len(target_pages)

    # Per-LLM count of distinct Uplers pages cited
    for llm in analysis["meta"]["llms_tested"]:
        llm_urls, _ = _aggregate_urls([r for r in results if r["llm"] == llm])
        analysis["by_llm"][llm]["target_pages"] = len([u for u in llm_urls if u.get("is_target")])

    return analysis

def generate_html_dashboard(analysis: dict, results: list, weekly_changes: dict = None, monthly_changes: dict = None, trend_data: list = None, goal_progress: dict = None, monthly_aggregates: list = None) -> str:
    """Generate an interactive HTML dashboard with weekly/monthly comparison, trends, goals, and monthly comparisons."""
    
    # Default empty values if not provided
    weekly_changes = weekly_changes or {}
    monthly_changes = monthly_changes or {}
    trend_data = trend_data or []
    goal_progress = goal_progress or {}
    monthly_aggregates = monthly_aggregates or []
    
    # Get target rank for each LLM
    target_ranks = {}
    for llm in analysis["meta"]["llms_tested"]:
        rankings = analysis["company_rankings"].get(llm, [])
        rank = next((r["rank"] for r in rankings if r["company"] == TARGET_COMPANY), "N/A")
        target_ranks[llm] = rank
    
    # Prepare intent data for chart
    intent_data = []
    for intent, data in sorted(analysis["by_intent"].items(), key=lambda x: x[1]["visibility_score"], reverse=True):
        intent_data.append({
            "intent": intent,
            "score": data["visibility_score"],
            "mentions": data["mentions"],
            "queries": data["queries"]
        })
    
    # Prepare LLM comparison data
    llm_scores = {llm: data["visibility_score"] for llm, data in analysis["by_llm"].items()}
    
    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>LLM Visibility Audit - {TARGET_COMPANY}</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
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
            max-width: 1400px;
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
        
        /* Section Headers */
        .section-header {{
            display: flex;
            align-items: center;
            gap: 16px;
            margin: 48px 0 24px;
        }}
        
        .section-header h2 {{
            font-size: 24px;
            font-weight: 600;
        }}
        
        .section-header .line {{
            flex: 1;
            height: 1px;
            background: var(--border);
        }}
        
        /* LLM Comparison */
        .llm-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 24px;
            margin-bottom: 48px;
        }}
        
        .llm-card {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 16px;
            padding: 28px;
        }}
        
        .llm-card .llm-name {{
            font-size: 20px;
            font-weight: 600;
            margin-bottom: 20px;
            display: flex;
            align-items: center;
            gap: 12px;
        }}
        
        .llm-card .llm-icon {{
            width: 32px;
            height: 32px;
            border-radius: 8px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 700;
            font-size: 14px;
        }}
        
        .llm-icon.chatgpt {{ background: #10a37f; }}
        .llm-icon.claude {{ background: #d97757; }}
        .llm-icon.gemini {{ background: linear-gradient(135deg, #4285f4, #ea4335, #fbbc04, #34a853); }}
        .llm-icon.grok {{ background: #1a1a1a; border: 1px solid #333; }}
        .llm-icon.perplexity {{ background: #20b8cd; }}
        
        .llm-stats {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 16px;
        }}
        
        .llm-stat {{
            background: var(--bg-secondary);
            padding: 16px;
            border-radius: 10px;
        }}
        
        .llm-stat .stat-label {{
            font-size: 12px;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        
        .llm-stat .stat-value {{
            font-size: 28px;
            font-weight: 600;
            margin-top: 4px;
        }}
        
        /* Rankings Table */
        .rankings-container {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
            gap: 24px;
            margin-bottom: 48px;
        }}
        
        .rankings-card {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 16px;
            overflow: hidden;
        }}
        
        .rankings-card .card-header {{
            padding: 20px 24px;
            border-bottom: 1px solid var(--border);
            font-weight: 600;
            font-size: 16px;
        }}
        
        .rankings-list {{
            max-height: 600px;
            overflow-y: auto;
        }}
        
        .ranking-item {{
            display: flex;
            align-items: center;
            padding: 14px 24px;
            border-bottom: 1px solid var(--border);
            transition: background 0.15s;
        }}
        
        .ranking-item:hover {{
            background: var(--bg-secondary);
        }}
        
        .ranking-item:last-child {{
            border-bottom: none;
        }}
        
        .ranking-item.target {{
            background: rgba(0, 255, 136, 0.1);
        }}
        
        .rank-num {{
            width: 32px;
            height: 32px;
            border-radius: 8px;
            background: var(--bg-secondary);
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 600;
            font-size: 14px;
            margin-right: 16px;
        }}
        
        .ranking-item.target .rank-num {{
            background: var(--accent);
            color: var(--bg-primary);
        }}
        
        .company-name {{
            flex: 1;
            font-weight: 500;
        }}
        
        .mention-count {{
            font-family: 'JetBrains Mono', monospace;
            color: var(--text-muted);
            font-size: 14px;
        }}
        
        /* Intent Analysis */
        .intent-chart-container {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 16px;
            padding: 32px;
            margin-bottom: 48px;
        }}
        
        .chart-wrapper {{
            height: 400px;
            position: relative;
        }}
        
        /* Weak Spots */
        .weak-spots {{
            background: linear-gradient(135deg, rgba(255, 71, 87, 0.1) 0%, var(--bg-card) 100%);
            border: 1px solid rgba(255, 71, 87, 0.3);
            border-radius: 16px;
            padding: 32px;
            margin-bottom: 48px;
        }}
        
        .weak-spots h3 {{
            color: var(--danger);
            margin-bottom: 20px;
            display: flex;
            align-items: center;
            gap: 12px;
        }}
        
        .weak-spot-item {{
            background: var(--bg-secondary);
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 16px;
        }}
        
        .weak-spot-item:last-child {{
            margin-bottom: 0;
        }}
        
        .weak-spot-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 12px;
        }}
        
        .weak-spot-intent {{
            font-weight: 600;
        }}
        
        .weak-spot-score {{
            color: var(--danger);
            font-family: 'JetBrains Mono', monospace;
        }}
        
        .weak-spot-prompts {{
            font-size: 14px;
            color: var(--text-muted);
        }}
        
        .weak-spot-prompts li {{
            margin: 8px 0;
            padding-left: 16px;
            position: relative;
        }}
        
        .weak-spot-prompts li::before {{
            content: '→';
            position: absolute;
            left: 0;
            color: var(--text-muted);
        }}
        
        /* Footer */
        footer {{
            text-align: center;
            padding: 40px 0;
            color: var(--text-muted);
            font-size: 14px;
            border-top: 1px solid var(--border);
            margin-top: 60px;
        }}
        
        /* Goals Section */
        .goals-section {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 16px;
            padding: 32px;
            margin-bottom: 48px;
        }}
        
        .goals-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 20px;
            margin-top: 24px;
        }}
        
        .goal-card {{
            background: var(--bg-secondary);
            border-radius: 12px;
            padding: 20px;
            position: relative;
            overflow: hidden;
        }}
        
        .goal-card.achieved {{
            border-left: 4px solid var(--success);
        }}
        
        .goal-card.in_progress {{
            border-left: 4px solid var(--warning);
        }}
        
        .goal-card.far {{
            border-left: 4px solid var(--danger);
        }}
        
        .goal-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 12px;
        }}
        
        .goal-llm {{
            font-weight: 600;
            font-size: 16px;
        }}
        
        .goal-status {{
            font-size: 12px;
            padding: 4px 10px;
            border-radius: 12px;
            font-weight: 500;
        }}
        
        .goal-status.achieved {{
            background: rgba(0, 255, 136, 0.2);
            color: var(--success);
        }}
        
        .goal-status.in_progress {{
            background: rgba(255, 165, 2, 0.2);
            color: var(--warning);
        }}
        
        .goal-status.far {{
            background: rgba(255, 71, 87, 0.2);
            color: var(--danger);
        }}
        
        .goal-progress {{
            margin: 16px 0;
        }}
        
        .progress-bar {{
            height: 8px;
            background: var(--bg-primary);
            border-radius: 4px;
            overflow: hidden;
        }}
        
        .progress-fill {{
            height: 100%;
            border-radius: 4px;
            transition: width 0.5s ease;
        }}
        
        .progress-fill.achieved {{ background: var(--success); }}
        .progress-fill.in_progress {{ background: var(--warning); }}
        .progress-fill.far {{ background: var(--danger); }}
        
        .goal-metrics {{
            display: flex;
            justify-content: space-between;
            font-size: 14px;
            color: var(--text-muted);
            margin-top: 8px;
        }}
        
        .goal-current {{
            font-weight: 600;
            color: var(--text-primary);
        }}
        
        /* Monthly Comparison Table */
        .monthly-table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 20px;
        }}
        
        .monthly-table th,
        .monthly-table td {{
            padding: 14px 16px;
            text-align: left;
            border-bottom: 1px solid var(--border);
        }}
        
        .monthly-table th {{
            background: var(--bg-secondary);
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            color: var(--text-muted);
        }}
        
        .monthly-table td {{
            font-family: 'JetBrains Mono', monospace;
            font-size: 14px;
        }}
        
        .monthly-table tr:hover {{
            background: var(--bg-secondary);
        }}
        
        .change-positive {{
            color: var(--success);
        }}
        
        .change-negative {{
            color: var(--danger);
        }}
        
        .change-neutral {{
            color: var(--text-muted);
        }}
        
        /* Responsive */
        @media (max-width: 768px) {{
            h1 {{ font-size: 32px; }}
            .score-card .value {{ font-size: 40px; }}
            .container {{ padding: 24px 16px; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="logo">LLM Visibility Audit</div>
            <h1>{TARGET_COMPANY}</h1>
            <p class="subtitle">Brand visibility analysis across AI assistants</p>
            <div class="meta-info">
                <div class="meta-item">Generated: <span>{analysis["meta"]["generated_at"][:10]}</span></div>
                <div class="meta-item">Queries: <span>{analysis["meta"]["total_queries"]}</span></div>
                <div class="meta-item">Prompts: <span>{analysis["meta"]["unique_prompts"]}</span></div>
                <div class="meta-item">Runs/Prompt: <span>{analysis["meta"]["runs_per_prompt"]}</span></div>
            </div>
            <div style="margin-top:20px;">
                <a href="responses.html" style="color:var(--accent);text-decoration:none;border:1px solid var(--border);padding:10px 20px;border-radius:8px;font-size:14px;">📝 View full responses per query →</a>
            </div>
        </header>
        
        <!-- Overall Scores -->
        <div class="score-grid">
            <div class="score-card primary">
                <div class="label">Overall Visibility Score</div>
                <div class="value accent">{analysis["overall"]["visibility_score"]}%</div>
                <div class="detail">{analysis["overall"]["target_mentions"]} mentions across {analysis["overall"]["total_queries"]} queries</div>
            </div>
            <div class="score-card">
                <div class="label">Overall Ranking</div>
                <div class="value {'accent' if analysis["overall"]["target_rank"] <= 3 else 'warning' if analysis["overall"]["target_rank"] <= 10 else 'danger'}">#{analysis["overall"]["target_rank"]}</div>
                <div class="detail">out of {analysis["overall"]["total_companies_mentioned"]} companies mentioned</div>
            </div>
            <div class="score-card">
                <div class="label">Share of Voice</div>
                <div class="value accent">{analysis["overall"].get("target_sov_share", 0)}%</div>
                <div class="detail">Position-weighted (1/rank) across all responses</div>
            </div>
            <div class="score-card">
                <div class="label">Avg Rank When Mentioned</div>
                <div class="value">{analysis["overall"].get("avg_rank_when_mentioned") or "—"}</div>
                <div class="detail">Lower is better — where Uplers lands in lists</div>
            </div>
            <div class="score-card">
                <div class="label">Uplers Pages Cited</div>
                <div class="value accent">{analysis["overall"].get("unique_target_pages", 0)}</div>
                <div class="detail">distinct {TARGET_DOMAIN} pages appearing in LLM answers</div>
            </div>
            <div class="score-card">
                <div class="label">Intent Categories</div>
                <div class="value">{len(analysis["by_intent"])}</div>
                <div class="detail">{len(analysis["weak_spots"])} weak spots identified</div>
            </div>
        </div>

        <!-- Weekly/Monthly Changes Section -->
        <div class="changes-section" style="display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 24px; margin-bottom: 48px;">
'''
    
    # Add weekly changes card if available
    if weekly_changes.get("has_previous"):
        weekly_score_change = weekly_changes.get("overall", {}).get("visibility_score", {}).get("change", 0)
        weekly_rank_change = weekly_changes.get("overall", {}).get("target_rank", {}).get("change", 0)
        weekly_direction = "📈" if weekly_score_change > 0 else "📉" if weekly_score_change < 0 else "➡️"
        weekly_color = "var(--success)" if weekly_score_change > 0 else "var(--danger)" if weekly_score_change < 0 else "var(--text-secondary)"
        
        html += f'''
            <div class="score-card" style="border-left: 4px solid {weekly_color};">
                <div class="label">📊 Weekly Change</div>
                <div class="value" style="color: {weekly_color}; font-size: 32px;">
                    {weekly_direction} {'+' if weekly_score_change > 0 else ''}{weekly_score_change}%
                </div>
                <div class="detail">Compared to {weekly_changes.get('previous_date', 'last week')}</div>
                <div class="detail" style="margin-top: 8px;">
                    Rank: {'↑' if weekly_rank_change > 0 else '↓' if weekly_rank_change < 0 else '→'}{abs(weekly_rank_change)} position{'s' if abs(weekly_rank_change) != 1 else ''}
                </div>
            </div>
'''
    else:
        html += '''
            <div class="score-card" style="border-left: 4px solid var(--text-muted);">
                <div class="label">📊 Weekly Change</div>
                <div class="value" style="color: var(--text-secondary); font-size: 24px;">No prior data</div>
                <div class="detail">First run - comparison available next week</div>
            </div>
'''
    
    # Add monthly changes card if available
    if monthly_changes.get("has_previous"):
        monthly_score_change = monthly_changes.get("overall", {}).get("visibility_score", {}).get("change", 0)
        monthly_rank_change = monthly_changes.get("overall", {}).get("target_rank", {}).get("change", 0)
        monthly_direction = "📈" if monthly_score_change > 0 else "📉" if monthly_score_change < 0 else "➡️"
        monthly_color = "var(--success)" if monthly_score_change > 0 else "var(--danger)" if monthly_score_change < 0 else "var(--text-secondary)"
        
        html += f'''
            <div class="score-card" style="border-left: 4px solid {monthly_color};">
                <div class="label">📅 Monthly Change</div>
                <div class="value" style="color: {monthly_color}; font-size: 32px;">
                    {monthly_direction} {'+' if monthly_score_change > 0 else ''}{monthly_score_change}%
                </div>
                <div class="detail">Compared to {monthly_changes.get('previous_date', '~30 days ago')}</div>
                <div class="detail" style="margin-top: 8px;">
                    Rank: {'↑' if monthly_rank_change > 0 else '↓' if monthly_rank_change < 0 else '→'}{abs(monthly_rank_change)} position{'s' if abs(monthly_rank_change) != 1 else ''}
                </div>
            </div>
'''
    else:
        html += '''
            <div class="score-card" style="border-left: 4px solid var(--text-muted);">
                <div class="label">📅 Monthly Change</div>
                <div class="value" style="color: var(--text-secondary); font-size: 24px;">No prior data</div>
                <div class="detail">Monthly comparison available after 30 days</div>
            </div>
'''
    
    html += '''
        </div>
'''
    
    # Add Goals Section if goal_progress is available
    if goal_progress and goal_progress.get("by_llm"):
        summary = goal_progress.get("summary", {})
        achieved = summary.get("achieved", 0)
        total = summary.get("total", 0)
        
        html += f'''
        <!-- Goals Progress Section -->
        <div class="section-header">
            <h2>🎯 Goals Progress</h2>
            <div class="line"></div>
        </div>
        
        <div class="goals-section">
            <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 16px;">
                <div>
                    <span style="font-size: 14px; color: var(--text-muted);">Goal Achievement:</span>
                    <span style="font-size: 20px; font-weight: 600; margin-left: 8px; color: var(--accent);">{achieved}/{total} LLMs</span>
                </div>
                <div style="display: flex; gap: 16px;">
                    <span style="color: var(--success);">🟢 {summary.get("achieved", 0)} Achieved</span>
                    <span style="color: var(--warning);">🟡 {summary.get("in_progress", 0)} In Progress</span>
                    <span style="color: var(--danger);">🔴 {summary.get("far", 0)} Far</span>
                </div>
            </div>
            
            <div class="goals-grid">
'''
        
        for llm, data in goal_progress.get("by_llm", {}).items():
            status = data.get("status", "far")
            status_label = "✓ Achieved" if status == "achieved" else "In Progress" if status == "in_progress" else "Needs Work"
            
            html += f'''
                <div class="goal-card {status}">
                    <div class="goal-header">
                        <span class="goal-llm">{llm}</span>
                        <span class="goal-status {status}">{status_label}</span>
                    </div>
                    <div class="goal-progress">
                        <div class="progress-bar">
                            <div class="progress-fill {status}" style="width: {min(100, data.get('progress_percent', 0))}%;"></div>
                        </div>
                    </div>
                    <div class="goal-metrics">
                        <span>Current: <span class="goal-current">{data.get('current', 0)}%</span></span>
                        <span>Target: {data.get('target', 0)}%</span>
                    </div>
                    <div style="font-size: 12px; color: var(--text-muted); margin-top: 8px;">
                        {f"🎉 Goal achieved!" if status == "achieved" else f"📈 {data.get('remaining', 0)}% more to reach goal"}
                    </div>
                </div>
'''
        
        html += '''
            </div>
        </div>
'''
    
    # Add Monthly Comparison Section if monthly_aggregates is available
    if monthly_aggregates and len(monthly_aggregates) >= 2:
        html += '''
        <!-- Monthly Comparison Section -->
        <div class="section-header">
            <h2>📅 Monthly Comparison</h2>
            <div class="line"></div>
        </div>
        
        <div class="goals-section">
            <table class="monthly-table">
                <thead>
                    <tr>
                        <th>LLM</th>
'''
        
        # Add month headers
        for month_data in monthly_aggregates:
            html += f'                        <th>{month_data["month_display"]}</th>\n'
        
        html += '''                        <th>Change</th>
                    </tr>
                </thead>
                <tbody>
'''
        
        # Get all LLMs from the aggregates
        all_llms = set()
        for month_data in monthly_aggregates:
            all_llms.update(month_data.get("by_llm", {}).keys())
        
        # Add rows for each LLM
        for llm in sorted(all_llms):
            html += f'                    <tr>\n                        <td style="font-weight: 600;">{llm}</td>\n'
            
            values = []
            for month_data in monthly_aggregates:
                llm_data = month_data.get("by_llm", {}).get(llm, {})
                visibility = llm_data.get("avg_visibility_score", 0)
                mentions = llm_data.get("total_mentions", 0)
                values.append((visibility, mentions))
                html += f'                        <td>{visibility}% <span style="color: var(--text-muted); font-size: 12px;">({mentions} mentions)</span></td>\n'
            
            # Calculate change between last two months
            if len(values) >= 2:
                change = values[-1][0] - values[-2][0]
                mention_change = values[-1][1] - values[-2][1]
                change_class = "change-positive" if change > 0 else "change-negative" if change < 0 else "change-neutral"
                change_arrow = "↑" if change > 0 else "↓" if change < 0 else "→"
                mention_arrow = "↑" if mention_change > 0 else "↓" if mention_change < 0 else "→"
                html += f'                        <td class="{change_class}">{change_arrow} {abs(change)}% <span style="font-size: 12px;">({mention_arrow}{abs(mention_change)} mentions)</span></td>\n'
            else:
                html += '                        <td class="change-neutral">—</td>\n'
            
            html += '                    </tr>\n'
        
        # Add overall row
        html += '                    <tr style="background: var(--bg-primary); font-weight: 600;">\n                        <td>Overall</td>\n'
        
        overall_values = []
        for month_data in monthly_aggregates:
            overall = month_data.get("overall", {})
            visibility = overall.get("avg_visibility_score", 0)
            rank = overall.get("avg_rank", 999)
            overall_values.append((visibility, rank))
            html += f'                        <td>{visibility}% <span style="color: var(--text-muted); font-size: 12px;">(Rank #{rank:.0f})</span></td>\n'
        
        if len(overall_values) >= 2:
            change = overall_values[-1][0] - overall_values[-2][0]
            rank_change = overall_values[-2][1] - overall_values[-1][1]  # Positive = improvement
            change_class = "change-positive" if change > 0 else "change-negative" if change < 0 else "change-neutral"
            change_arrow = "↑" if change > 0 else "↓" if change < 0 else "→"
            rank_arrow = "↑" if rank_change > 0 else "↓" if rank_change < 0 else "→"
            html += f'                        <td class="{change_class}">{change_arrow} {abs(change)}% <span style="font-size: 12px;">(Rank {rank_arrow}{abs(rank_change):.0f})</span></td>\n'
        else:
            html += '                        <td class="change-neutral">—</td>\n'
        
        html += '''                    </tr>
                </tbody>
            </table>
        </div>
'''
    
    # Add trend chart if we have historical data
    if len(trend_data) >= 2:
        trend_dates = [d["date"] for d in trend_data]
        trend_scores = [d["visibility_score"] for d in trend_data]
        trend_ranks = [d["target_rank"] for d in trend_data]
        
        html += f'''
        <!-- Historical Trend Chart -->
        <div class="section-header">
            <h2>Visibility Trend (Last 90 Days)</h2>
            <div class="line"></div>
        </div>
        
        <div class="chart-container" style="margin-bottom: 48px;">
            <canvas id="trendChart" height="250"></canvas>
        </div>
        
        <script>
            // Trend Chart
            const trendCtx = document.getElementById('trendChart').getContext('2d');
            new Chart(trendCtx, {{
                type: 'line',
                data: {{
                    labels: {json.dumps(trend_dates)},
                    datasets: [{{
                        label: 'Visibility Score (%)',
                        data: {json.dumps(trend_scores)},
                        borderColor: '#00ff88',
                        backgroundColor: 'rgba(0, 255, 136, 0.1)',
                        fill: true,
                        tension: 0.3,
                        pointRadius: 6,
                        pointHoverRadius: 8,
                        yAxisID: 'y'
                    }}, {{
                        label: 'Rank (lower is better)',
                        data: {json.dumps(trend_ranks)},
                        borderColor: '#ffa502',
                        backgroundColor: 'rgba(255, 165, 2, 0.1)',
                        fill: false,
                        tension: 0.3,
                        pointRadius: 6,
                        pointHoverRadius: 8,
                        yAxisID: 'y1'
                    }}]
                }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: false,
                    interaction: {{
                        mode: 'index',
                        intersect: false,
                    }},
                    plugins: {{
                        legend: {{
                            labels: {{ color: '#8b8b9e', font: {{ family: "'Space Grotesk'" }} }}
                        }},
                        tooltip: {{
                            backgroundColor: '#1a1a24',
                            titleColor: '#fff',
                            bodyColor: '#8b8b9e',
                            borderColor: '#2a2a3a',
                            borderWidth: 1
                        }}
                    }},
                    scales: {{
                        x: {{
                            grid: {{ color: '#2a2a3a' }},
                            ticks: {{ color: '#8b8b9e' }}
                        }},
                        y: {{
                            type: 'linear',
                            display: true,
                            position: 'left',
                            min: 0,
                            max: 100,
                            grid: {{ color: '#2a2a3a' }},
                            ticks: {{ 
                                color: '#00ff88',
                                callback: function(value) {{ return value + '%'; }}
                            }},
                            title: {{
                                display: true,
                                text: 'Visibility Score',
                                color: '#00ff88'
                            }}
                        }},
                        y1: {{
                            type: 'linear',
                            display: true,
                            position: 'right',
                            reverse: true,
                            min: 1,
                            grid: {{ drawOnChartArea: false }},
                            ticks: {{ 
                                color: '#ffa502',
                                callback: function(value) {{ return '#' + value; }}
                            }},
                            title: {{
                                display: true,
                                text: 'Rank',
                                color: '#ffa502'
                            }}
                        }}
                    }}
                }}
            }});
        </script>
'''
    
    html += '''
        <!-- LLM Comparison -->
        <div class="section-header">
            <h2>Performance by LLM</h2>
            <div class="line"></div>
        </div>
        
        <div class="llm-grid">
'''
    
    # Add LLM cards
    for llm, data in analysis["by_llm"].items():
        # Map LLM names to CSS icon classes
        icon_class_map = {
            "ChatGPT": "chatgpt",
            "Claude": "claude",
            "Gemini": "gemini",
            "Grok": "grok",
            "Perplexity": "perplexity"
        }
        icon_class = icon_class_map.get(llm, llm.lower().replace(" ", ""))
        rank = target_ranks.get(llm, "N/A")
        html += f'''
            <div class="llm-card">
                <div class="llm-name">
                    <div class="llm-icon {icon_class}">{llm[0]}</div>
                    {llm}
                </div>
                <div class="llm-stats">
                    <div class="llm-stat">
                        <div class="stat-label">Visibility</div>
                        <div class="stat-value" style="color: var(--accent)">{data["visibility_score"]}%</div>
                    </div>
                    <div class="llm-stat">
                        <div class="stat-label">Rank</div>
                        <div class="stat-value">#{rank}</div>
                    </div>
                    <div class="llm-stat">
                        <div class="stat-label">Mentions</div>
                        <div class="stat-value">{data["mentions"]}</div>
                    </div>
                    <div class="llm-stat">
                        <div class="stat-label">Queries</div>
                        <div class="stat-value">{data["queries"]}</div>
                    </div>
                </div>
            </div>
'''
    
    html += '''
        </div>
        
        <!-- Intent Analysis Chart -->
        <div class="section-header">
            <h2>Visibility by Intent Category</h2>
            <div class="line"></div>
        </div>
        
        <div class="intent-chart-container">
            <div class="chart-wrapper">
                <canvas id="intentChart"></canvas>
            </div>
        </div>
'''
    
    # Sentiment breakdown
    sentiment = analysis["overall"].get("sentiment") or {}
    if sentiment.get("scored_mentions"):
        total = max(1, sentiment["scored_mentions"])
        pos_pct = round(sentiment["positive"] / total * 100, 1)
        neu_pct = round(sentiment["neutral"] / total * 100, 1)
        neg_pct = round(sentiment["negative"] / total * 100, 1)
        html += f'''
        <div class="section-header">
            <h2>Sentiment of {TARGET_COMPANY} Mentions</h2>
            <div class="line"></div>
        </div>
        <div class="score-grid" style="margin-bottom: 48px;">
            <div class="score-card">
                <div class="label">Positive</div>
                <div class="value accent">{pos_pct}%</div>
                <div class="detail">{sentiment["positive"]} of {sentiment["scored_mentions"]} mentions</div>
            </div>
            <div class="score-card">
                <div class="label">Neutral</div>
                <div class="value">{neu_pct}%</div>
                <div class="detail">{sentiment["neutral"]} of {sentiment["scored_mentions"]} mentions</div>
            </div>
            <div class="score-card">
                <div class="label">Negative</div>
                <div class="value" style="color: var(--danger);">{neg_pct}%</div>
                <div class="detail">{sentiment["negative"]} of {sentiment["scored_mentions"]} mentions</div>
            </div>
        </div>
'''

    # Weak Spots Section
    if analysis["weak_spots"]:
        html += '''
        <div class="weak-spots">
            <h3>⚠️ Weak Spots (Visibility < 20%)</h3>
'''
        for spot in analysis["weak_spots"]:
            html += f'''
            <div class="weak-spot-item">
                <div class="weak-spot-header">
                    <span class="weak-spot-intent">{spot["intent"]}</span>
                    <span class="weak-spot-score">{spot["visibility"]}%</span>
                </div>
                <ul class="weak-spot-prompts">
'''
            for prompt in spot["sample_prompts"]:
                html += f'                    <li>{prompt}</li>\n'
            html += '''
                </ul>
            </div>
'''
        html += '        </div>\n'

    # Pages / URLs Cited Section
    pages = analysis.get("pages") or {}
    target_pages = pages.get("target") or []
    all_domains = pages.get("domains") or []
    all_urls = pages.get("all_urls") or []

    def _esc(s):
        return (str(s or "")).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def _short(url, n=70):
        url = str(url or "")
        return url if len(url) <= n else url[:n - 1] + "…"

    if all_urls:
        html += '''
        <div class="section-header">
            <h2>Pages Cited in LLM Answers</h2>
            <div class="line"></div>
        </div>

        <div class="rankings-container">
'''
        # --- Uplers pages (primary) ---
        html += f'''
            <div class="rankings-card">
                <div class="card-header">🎯 {TARGET_DOMAIN} Pages Cited</div>
                <div class="rankings-list">
'''
        if target_pages:
            for i, p in enumerate(target_pages[:30], start=1):
                src = "/".join(p.get("sources", []))
                chans = ", ".join(p.get("channels", []))
                html += f'''
                    <div class="ranking-item target">
                        <div class="rank-num">{i}</div>
                        <span class="company-name"><a href="{_esc(p["url"])}" target="_blank" style="color:inherit;text-decoration:none;">{_esc(_short(p["url"]))}</a><br><span style="font-size:11px;color:var(--text-muted);">{_esc(chans)} · {_esc(src)}</span></span>
                        <span class="mention-count">{p["count"]}×</span>
                    </div>
'''
        else:
            html += '<div class="ranking-item"><span class="company-name" style="color:var(--text-muted);">No Uplers pages were cited in this run.</span></div>\n'
        html += '''
                </div>
            </div>
'''
        # --- Top cited domains ---
        html += '''
            <div class="rankings-card">
                <div class="card-header">Top Cited Domains</div>
                <div class="rankings-list">
'''
        for i, d in enumerate(all_domains[:25], start=1):
            is_t = "target" if d.get("is_target") else ""
            tag = "us" if d.get("is_target") else "competitor"
            html += f'''
                    <div class="ranking-item {is_t}">
                        <div class="rank-num">{i}</div>
                        <span class="company-name">{_esc(d["domain"])} <span style="font-size:11px;color:var(--text-muted);">({tag})</span></span>
                        <span class="mention-count">{d["count"]}×</span>
                    </div>
'''
        html += '''
                </div>
            </div>
'''
        # --- Top cited URLs overall ---
        html += '''
            <div class="rankings-card">
                <div class="card-header">Top Cited URLs (All)</div>
                <div class="rankings-list">
'''
        for i, u in enumerate(all_urls[:25], start=1):
            is_t = "target" if u.get("is_target") else ""
            chans = ", ".join(u.get("channels", []))
            html += f'''
                    <div class="ranking-item {is_t}">
                        <div class="rank-num">{i}</div>
                        <span class="company-name"><a href="{_esc(u["url"])}" target="_blank" style="color:inherit;text-decoration:none;">{_esc(_short(u["url"]))}</a><br><span style="font-size:11px;color:var(--text-muted);">{_esc(chans)}</span></span>
                        <span class="mention-count">{u["count"]}×</span>
                    </div>
'''
        html += '''
                </div>
            </div>
        </div>
'''

    # Rankings
    html += '''
        <div class="section-header">
            <h2>Company Rankings</h2>
            <div class="line"></div>
        </div>

        <div class="rankings-container">
            <div class="rankings-card">
                <div class="card-header">Overall Rankings</div>
                <div class="rankings-list">
'''
    
    for item in analysis["company_rankings"]["overall"][:30]:
        is_target = "target" if item["company"] == TARGET_COMPANY else ""
        sov = item.get("sov_share", 0)
        html += f'''
                    <div class="ranking-item {is_target}">
                        <div class="rank-num">{item["rank"]}</div>
                        <span class="company-name">{item["company"]}</span>
                        <span class="mention-count">{sov}% SoV · {item["mentions"]} mentions</span>
                    </div>
'''

    html += '''
                </div>
            </div>
'''

    # Add per-LLM rankings
    for llm in analysis["meta"]["llms_tested"]:
        if llm in analysis["company_rankings"]:
            html += f'''
            <div class="rankings-card">
                <div class="card-header">{llm} Rankings</div>
                <div class="rankings-list">
'''
            for item in analysis["company_rankings"][llm][:20]:
                is_target = "target" if item["company"] == TARGET_COMPANY else ""
                sov = item.get("sov_share", 0)
                html += f'''
                    <div class="ranking-item {is_target}">
                        <div class="rank-num">{item["rank"]}</div>
                        <span class="company-name">{item["company"]}</span>
                        <span class="mention-count">{sov}% SoV · {item["mentions"]} mentions</span>
                    </div>
'''
            html += '''
                </div>
            </div>
'''
    
    html += '''
        </div>
        
        <footer>
            <p>LLM Visibility Audit Tool • Built for strategic brand monitoring</p>
        </footer>
    </div>
    
    <script>
        // Intent Chart
        const ctx = document.getElementById('intentChart').getContext('2d');
        new Chart(ctx, {
            type: 'bar',
            data: {
                labels: ''' + json.dumps([d["intent"] for d in intent_data]) + ''',
                datasets: [{
                    label: 'Visibility Score (%)',
                    data: ''' + json.dumps([d["score"] for d in intent_data]) + ''',
                    backgroundColor: function(context) {
                        const value = context.raw;
                        if (value >= 50) return '#00ff88';
                        if (value >= 20) return '#ffa502';
                        return '#ff4757';
                    },
                    borderRadius: 6,
                    borderSkipped: false,
                }]
            },
            options: {
                indexAxis: 'y',
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        backgroundColor: '#1a1a24',
                        borderColor: '#2a2a3a',
                        borderWidth: 1,
                        titleFont: { family: 'Space Grotesk' },
                        bodyFont: { family: 'JetBrains Mono' },
                    }
                },
                scales: {
                    x: {
                        max: 100,
                        grid: { color: '#2a2a3a' },
                        ticks: { 
                            color: '#8b8b9e',
                            font: { family: 'JetBrains Mono' },
                            callback: function(value) { return value + '%'; }
                        }
                    },
                    y: {
                        grid: { display: false },
                        ticks: { 
                            color: '#ffffff',
                            font: { family: 'Space Grotesk', size: 13 }
                        }
                    }
                }
            }
        });
    </script>
</body>
</html>
'''
    
    return html


# ============================================================================
# RESPONSE TRANSCRIPT VIEW (per-query, with highlighted mentions + citations)
# ============================================================================

def render_response_html(text: str) -> str:
    """Render a raw LLM response into safe HTML with brand mentions highlighted.

    Light markdown (bold, headers, line breaks) plus inline highlighting of every
    tracked platform — the target (Uplers) in accent green, competitors in amber.
    """
    import html as _html
    if not text:
        return '<em class="empty">— no response —</em>'
    esc = _html.escape(text)
    # Light markdown
    esc = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', esc)
    esc = re.sub(r'(?m)^\s*#{1,6}\s*(.+)$', r'<strong>\1</strong>', esc)
    esc = esc.replace('\n', '<br>')

    # Collect non-overlapping brand spans across all platform patterns
    spans = []
    for name, patterns in PLATFORM_PATTERNS.items():
        is_target = (name == TARGET_COMPANY)
        for p in patterns:
            for m in p.finditer(esc):
                spans.append((m.start(), m.end(), is_target))
    spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))

    out, last = [], 0
    for start, end, is_target in spans:
        if start < last:
            continue  # overlaps an already-wrapped span
        out.append(esc[last:start])
        cls = "mention target" if is_target else "mention competitor"
        out.append(f'<span class="{cls}">{esc[start:end]}</span>')
        last = end
    out.append(esc[last:])
    return ''.join(out)


def generate_responses_html(results: list) -> str:
    """Build a transcript page: each query, then each channel's answer with
    highlighted brand mentions and the citations it pulled from."""
    import html as _html

    # Order prompts as defined; group representative run per (prompt, llm)
    prompt_order = []
    seen = set()
    for intent, prompts in PROMPTS_BY_INTENT.items():
        for pr in prompts:
            if pr not in seen:
                seen.add(pr)
                prompt_order.append((intent, pr))
    # include any prompts present in results but not in config (safety)
    for r in results:
        if r["prompt"] not in seen:
            seen.add(r["prompt"])
            prompt_order.append((r.get("intent", ""), r["prompt"]))

    def representative(prompt, llm):
        rows = [r for r in results if r["prompt"] == prompt and r["llm"] == llm]
        for r in rows:
            if (r.get("response") or "").strip():
                return r
        return rows[0] if rows else None

    llms = [l for l in
            ["ChatGPT", "ChatGPT-Search", "Claude", "Claude-Search",
             "Gemini", "Gemini-Search", "Grok", "Perplexity"]
            if any(r["llm"] == l for r in results)]

    html_doc = f'''<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>LLM Responses — {TARGET_COMPANY}</title>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  :root {{
    --bg:#0a0a0f; --bg2:#12121a; --card:#1a1a24; --accent:#00ff88; --amber:#ffa502;
    --text:#e8e8f0; --muted:#8b8b9e; --border:#2a2a3a;
  }}
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family:'Space Grotesk',sans-serif; background:var(--bg); color:var(--text); line-height:1.65; }}
  .container {{ max-width:1200px; margin:0 auto; padding:40px 24px; }}
  header {{ text-align:center; margin-bottom:40px; }}
  .logo {{ font-size:13px; letter-spacing:4px; color:var(--accent); text-transform:uppercase; }}
  h1 {{ font-size:38px; margin:8px 0; }}
  .subtitle {{ color:var(--muted); }}
  .topnav {{ text-align:center; margin-bottom:32px; }}
  .topnav a {{ color:var(--accent); text-decoration:none; font-size:14px; border:1px solid var(--border); padding:8px 16px; border-radius:8px; }}
  .legend {{ display:flex; gap:16px; justify-content:center; margin:20px 0 28px; font-size:13px; color:var(--muted); flex-wrap:wrap; }}
  .picker {{ position:sticky; top:0; z-index:10; display:flex; align-items:center; gap:12px; flex-wrap:wrap;
       background:var(--bg2); border:1px solid var(--border); border-radius:14px; padding:16px 20px; margin-bottom:36px; }}
  .picker label {{ font-size:14px; color:var(--muted); font-weight:600; }}
  .picker select {{ flex:1; min-width:280px; background:var(--bg); color:var(--text); border:1px solid var(--border);
       border-radius:10px; padding:12px 14px; font-family:'Space Grotesk',sans-serif; font-size:15px; cursor:pointer; }}
  .picker select:focus {{ outline:none; border-color:var(--accent); }}
  .picker .qcount {{ font-size:12px; color:var(--muted); font-family:'JetBrains Mono',monospace; }}
  .mention {{ padding:1px 5px; border-radius:5px; font-weight:600; }}
  .mention.target {{ background:rgba(0,255,136,0.16); color:var(--accent); }}
  .mention.competitor {{ background:rgba(255,165,2,0.13); color:var(--amber); }}
  .qa {{ margin-bottom:56px; }}
  .query-bubble {{ background:var(--bg2); border:1px solid var(--border); border-radius:14px;
       padding:16px 20px; font-size:18px; font-weight:600; margin-bottom:8px; }}
  .query-meta {{ color:var(--muted); font-size:12px; margin-bottom:20px; padding-left:4px; }}
  .response-card {{ background:var(--card); border:1px solid var(--border); border-radius:14px;
       margin-bottom:18px; overflow:hidden; }}
  .resp-head {{ display:flex; align-items:center; gap:12px; padding:14px 20px; border-bottom:1px solid var(--border); background:var(--bg2); }}
  .chan {{ font-weight:600; }}
  .badge {{ font-size:11px; padding:3px 9px; border-radius:20px; font-family:'JetBrains Mono',monospace; }}
  .badge.yes {{ background:rgba(0,255,136,0.15); color:var(--accent); }}
  .badge.no {{ background:rgba(255,71,87,0.12); color:#ff6b7a; }}
  .badge.pos {{ background:rgba(0,255,136,0.12); color:var(--accent); }}
  .badge.neu {{ background:rgba(139,139,158,0.15); color:var(--muted); }}
  .badge.neg {{ background:rgba(255,71,87,0.12); color:#ff6b7a; }}
  .resp-body {{ display:grid; grid-template-columns: 1fr 300px; gap:0; }}
  @media (max-width:820px) {{ .resp-body {{ grid-template-columns:1fr; }} }}
  .resp-text {{ padding:20px 24px; font-size:15px; }}
  .resp-text .empty {{ color:var(--muted); }}
  .resp-cites {{ border-left:1px solid var(--border); padding:18px 18px; background:rgba(255,255,255,0.01); }}
  .resp-cites h4 {{ font-size:12px; text-transform:uppercase; letter-spacing:1px; color:var(--muted); margin-bottom:14px; }}
  .cite {{ display:block; padding:10px 12px; border:1px solid var(--border); border-radius:10px; margin-bottom:10px;
       text-decoration:none; color:var(--text); transition:border-color .15s; }}
  .cite:hover {{ border-color:var(--accent); }}
  .cite.target {{ border-color:rgba(0,255,136,0.4); background:rgba(0,255,136,0.05); }}
  .cite .dom {{ font-size:12px; color:var(--muted); font-family:'JetBrains Mono',monospace; }}
  .cite .ttl {{ font-size:13px; margin-top:3px; }}
  .nocite {{ color:var(--muted); font-size:13px; }}
</style></head>
<body><div class="container">
  <header>
    <div class="logo">LLM Responses</div>
    <h1>{TARGET_COMPANY}</h1>
    <p class="subtitle">What each AI assistant actually said, per query</p>
  </header>
  <div class="topnav"><a href="visibility_dashboard.html">← Back to dashboard</a></div>
  <div class="legend">
    <span><span class="mention target">{TARGET_COMPANY}</span> = our brand</span>
    <span><span class="mention competitor">Competitor</span> = tracked competitor</span>
    <span>Citations = pages the model pulled from</span>
  </div>
'''

    sent_badge = {"positive": ("pos", "positive"), "neutral": ("neu", "neutral"),
                  "negative": ("neg", "negative")}

    # Build each query's block, collecting (intent, prompt, html) so we can also
    # drive a dropdown selector and show one query at a time.
    qa_blocks = []
    for intent, prompt in prompt_order:
        cards = []
        for llm in llms:
            r = representative(prompt, llm)
            if r is None:
                continue
            mentioned = r.get("target_mentioned")
            ment_badge = f'<span class="badge yes">{TARGET_COMPANY} ✓</span>' if mentioned \
                else f'<span class="badge no">{TARGET_COMPANY} ✗</span>'
            sb = ""
            if r.get("target_sentiment") in sent_badge:
                cls, label = sent_badge[r["target_sentiment"]]
                sb = f'<span class="badge {cls}">{label}</span>'

            # Citations panel — only REAL web-search citations (not domains the
            # model merely typed in prose). Base models therefore show none.
            cite_urls = [u for u in (r.get("urls") or []) if u.get("source") == "citation"]
            if cite_urls:
                cites = ['<h4>Citations</h4>']
                for u in cite_urls[:12]:
                    tcls = "target" if u.get("is_target") else ""
                    title = _html.escape(u.get("title") or u["url"])
                    dom = _html.escape(u.get("domain") or "")
                    cites.append(
                        f'<a class="cite {tcls}" href="{_html.escape(u["url"])}" target="_blank">'
                        f'<div class="dom">{dom}</div><div class="ttl">{title}</div></a>')
                cites_html = "".join(cites)
            else:
                cites_html = '<h4>Citations</h4><div class="nocite">Answered from memory — no sources cited.</div>'

            cards.append(f'''
    <div class="response-card">
      <div class="resp-head"><span class="chan">{llm}</span>{ment_badge}{sb}</div>
      <div class="resp-body">
        <div class="resp-text">{render_response_html(r.get("response") or "")}</div>
        <div class="resp-cites">{cites_html}</div>
      </div>
    </div>''')

        if not cards:
            continue
        idx = len(qa_blocks)
        block = f'''
  <div class="qa" id="qa{idx}" style="{'' if idx == 0 else 'display:none;'}">
    <div class="query-bubble">{_html.escape(prompt)}</div>
    <div class="query-meta">{_html.escape(intent)}</div>
    {''.join(cards)}
  </div>
'''
        qa_blocks.append((intent, prompt, block))

    # Dropdown selector (grouped by intent via <optgroup>)
    if qa_blocks:
        select = ['<div class="picker"><label for="qpick">Select a query &nbsp;</label>',
                  '<select id="qpick" onchange="showQA(this.value)">']
        cur = None
        for i, (intent, prompt, _) in enumerate(qa_blocks):
            if intent != cur:
                if cur is not None:
                    select.append('</optgroup>')
                select.append(f'<optgroup label="{_html.escape(intent)}">')
                cur = intent
            label = prompt if len(prompt) <= 95 else prompt[:94] + '…'
            select.append(f'<option value="{i}">{_html.escape(label)}</option>')
        if cur is not None:
            select.append('</optgroup>')
        select.append('</select>')
        select.append(f'<span class="qcount">{len(qa_blocks)} queries</span></div>')
        html_doc += ''.join(select)

    html_doc += ''.join(b for _, _, b in qa_blocks)

    html_doc += '''
  <script>
    function showQA(i) {
      document.querySelectorAll('.qa').forEach(function(el){ el.style.display = 'none'; });
      var t = document.getElementById('qa' + i);
      if (t) t.style.display = 'block';
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }
  </script>
</div></body></html>'''
    return html_doc


# ============================================================================
# SCREENSHOT CAPTURE
# ============================================================================

def capture_screenshot(html_file: str, output_png: str) -> bool:
    """Capture a screenshot of the HTML dashboard using Playwright."""
    try:
        from playwright.sync_api import sync_playwright
        
        logger.info(f"📸 Capturing screenshot of {html_file}...")
        
        # Get absolute path
        html_path = os.path.abspath(html_file)
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1400, 'height': 900})
            
            # Load the HTML file
            page.goto(f"file://{html_path}")
            
            # Wait for chart to render
            page.wait_for_timeout(2000)
            
            # Capture full page screenshot
            page.screenshot(path=output_png, full_page=True)
            
            browser.close()
        
        logger.info(f"✅ Screenshot saved to {output_png}")
        return True
        
    except ImportError:
        logger.warning("⚠️  Playwright not installed. Run: pip install playwright && playwright install chromium")
        return False
    except Exception as e:
        logger.error(f"❌ Screenshot capture failed: {e}")
        return False


# ============================================================================
# HISTORICAL COMPARISON
# ============================================================================

def calculate_changes(current_analysis: dict, previous_data: dict, period_label: str = "week") -> dict:
    """Calculate changes in metrics compared to previous data."""
    changes = {
        "has_previous": False,
        "previous_date": None,
        "period": period_label,
        "overall": {},
        "by_llm": {},
        "summary": []
    }
    
    if not previous_data or "analysis" not in previous_data:
        return changes
    
    prev_analysis = previous_data["analysis"]
    changes["has_previous"] = True
    changes["previous_date"] = previous_data.get("_archive_date", "Unknown")
    
    # Overall visibility change
    current_score = current_analysis["overall"]["visibility_score"]
    prev_score = prev_analysis.get("overall", {}).get("visibility_score", 0)
    score_change = round(current_score - prev_score, 1)
    
    changes["overall"]["visibility_score"] = {
        "current": current_score,
        "previous": prev_score,
        "change": score_change,
        "direction": "up" if score_change > 0 else "down" if score_change < 0 else "same"
    }
    
    # Rank change
    current_rank = current_analysis["overall"]["target_rank"]
    prev_rank = prev_analysis.get("overall", {}).get("target_rank", 999)
    rank_change = prev_rank - current_rank  # Positive = improved (lower rank is better)
    
    changes["overall"]["target_rank"] = {
        "current": current_rank,
        "previous": prev_rank,
        "change": rank_change,
        "direction": "up" if rank_change > 0 else "down" if rank_change < 0 else "same"
    }
    
    # By LLM changes
    for llm, data in current_analysis.get("by_llm", {}).items():
        prev_llm_data = prev_analysis.get("by_llm", {}).get(llm, {})
        prev_llm_score = prev_llm_data.get("visibility_score", 0)
        current_llm_score = data["visibility_score"]
        llm_change = round(current_llm_score - prev_llm_score, 1)
        
        changes["by_llm"][llm] = {
            "current": current_llm_score,
            "previous": prev_llm_score,
            "change": llm_change,
            "direction": "up" if llm_change > 0 else "down" if llm_change < 0 else "same"
        }
    
    # Generate summary based on period
    period_text = "this week" if period_label == "week" else "this month"
    
    if score_change > 0:
        changes["summary"].append(f"📈 Visibility improved by {score_change}% {period_text}")
    elif score_change < 0:
        changes["summary"].append(f"📉 Visibility decreased by {abs(score_change)}% {period_text}")
    else:
        changes["summary"].append(f"➡️ Visibility unchanged {period_text}")
    
    if rank_change > 0:
        changes["summary"].append(f"🏆 Ranking improved by {rank_change} position(s)")
    elif rank_change < 0:
        changes["summary"].append(f"⬇️ Ranking dropped by {abs(rank_change)} position(s)")
    
    return changes


# ============================================================================
# EMAIL NOTIFICATIONS
# ============================================================================

def send_email_notification(analysis: dict, weekly_changes: dict, monthly_changes: dict = None, screenshot_path: str = None, dashboard_path: str = None, goal_progress: dict = None) -> bool:
    """Send email notification with audit summary including weekly and monthly changes and goals."""
    if not EMAIL_ENABLED:
        logger.info("📧 Email notifications disabled (no credentials configured)")
        return False
    
    # For backward compatibility
    monthly_changes = monthly_changes or {}
    goal_progress = goal_progress or {}
    
    try:
        logger.info(f"📧 Sending email notification to {EMAIL_TO}...")
        
        # Create message
        msg = MIMEMultipart('related')
        msg['Subject'] = f"🔍 LLM Visibility Audit Report - {TARGET_COMPANY} - {get_timestamp()}"
        msg['From'] = SMTP_USER
        msg['To'] = EMAIL_TO
        
        # Build HTML email body
        score = analysis["overall"]["visibility_score"]
        rank = analysis["overall"]["target_rank"]
        total_companies = analysis["overall"]["total_companies_mentioned"]
        
        # Determine score color
        if score >= 50:
            score_color = "#00ff88"
        elif score >= 20:
            score_color = "#ffa502"
        else:
            score_color = "#ff4757"
        
        # Build change indicators (weekly)
        change_html = ""
        if weekly_changes.get("has_previous"):
            weekly_score_change = weekly_changes.get("overall", {}).get("visibility_score", {}).get("change", 0)
            weekly_color = "#00ff88" if weekly_score_change > 0 else "#ff4757" if weekly_score_change < 0 else "#8b8b9e"
            
            change_html = f"""
            <div style="background: #1a1a24; border-radius: 8px; padding: 16px; margin: 16px 0; border-left: 4px solid {weekly_color};">
                <h3 style="color: #8b8b9e; margin: 0 0 12px 0; font-size: 14px;">📊 WEEKLY CHANGES</h3>
                <p style="color: #aaa; margin: 4px 0;">Compared to: {weekly_changes['previous_date']}</p>
            """
            for summary_item in weekly_changes.get("summary", []):
                change_html += f'<p style="color: #fff; margin: 8px 0;">{summary_item}</p>'
            change_html += "</div>"
        
        # Build monthly change indicators
        if monthly_changes.get("has_previous"):
            monthly_score_change = monthly_changes.get("overall", {}).get("visibility_score", {}).get("change", 0)
            monthly_color = "#00ff88" if monthly_score_change > 0 else "#ff4757" if monthly_score_change < 0 else "#8b8b9e"
            
            change_html += f"""
            <div style="background: #1a1a24; border-radius: 8px; padding: 16px; margin: 16px 0; border-left: 4px solid {monthly_color};">
                <h3 style="color: #8b8b9e; margin: 0 0 12px 0; font-size: 14px;">📅 MONTHLY CHANGES</h3>
                <p style="color: #aaa; margin: 4px 0;">Compared to: {monthly_changes['previous_date']}</p>
            """
            for summary_item in monthly_changes.get("summary", []):
                change_html += f'<p style="color: #fff; margin: 8px 0;">{summary_item}</p>'
            change_html += "</div>"
        
        # Build LLM breakdown
        llm_rows = ""
        for llm, data in analysis.get("by_llm", {}).items():
            llm_weekly_change = weekly_changes.get("by_llm", {}).get(llm, {})
            llm_monthly_change = monthly_changes.get("by_llm", {}).get(llm, {})
            
            weekly_indicator = ""
            if llm_weekly_change:
                if llm_weekly_change["direction"] == "up":
                    weekly_indicator = f'<span style="color: #00ff88;">↑{llm_weekly_change["change"]}%</span>'
                elif llm_weekly_change["direction"] == "down":
                    weekly_indicator = f'<span style="color: #ff4757;">↓{abs(llm_weekly_change["change"])}%</span>'
            
            monthly_indicator = ""
            if llm_monthly_change:
                if llm_monthly_change["direction"] == "up":
                    monthly_indicator = f'<span style="color: #00ff88;">↑{llm_monthly_change["change"]}%</span>'
                elif llm_monthly_change["direction"] == "down":
                    monthly_indicator = f'<span style="color: #ff4757;">↓{abs(llm_monthly_change["change"])}%</span>'
            
            llm_rows += f"""
            <tr>
                <td style="padding: 12px; border-bottom: 1px solid #2a2a3a; color: #fff;">{llm}</td>
                <td style="padding: 12px; border-bottom: 1px solid #2a2a3a; color: #00ff88;">{data['visibility_score']}%</td>
                <td style="padding: 12px; border-bottom: 1px solid #2a2a3a;">{data['mentions']}/{data['queries']}</td>
                <td style="padding: 12px; border-bottom: 1px solid #2a2a3a;">{weekly_indicator}</td>
                <td style="padding: 12px; border-bottom: 1px solid #2a2a3a;">{monthly_indicator}</td>
            </tr>
            """
        
        # Goals progress
        goals_html = ""
        if goal_progress and goal_progress.get("by_llm"):
            summary = goal_progress.get("summary", {})
            achieved = summary.get("achieved", 0)
            total = summary.get("total", 0)
            
            goals_html = f"""
            <div style="background: #1a1a24; border-radius: 8px; padding: 16px; margin: 16px 0; border-left: 4px solid #00ff88;">
                <h3 style="color: #8b8b9e; margin: 0 0 12px 0; font-size: 14px;">🎯 GOALS PROGRESS ({achieved}/{total} Achieved)</h3>
                <table style="width: 100%; border-collapse: collapse;">
            """
            for llm, data in goal_progress.get("by_llm", {}).items():
                status = data.get("status", "far")
                status_icon = "✅" if status == "achieved" else "🟡" if status == "in_progress" else "🔴"
                status_color = "#00ff88" if status == "achieved" else "#ffa502" if status == "in_progress" else "#ff4757"
                goals_html += f"""
                <tr>
                    <td style="padding: 8px; color: #fff;">{status_icon} {llm}</td>
                    <td style="padding: 8px; color: {status_color}; text-align: right;">{data.get('current', 0)}% / {data.get('target', 0)}%</td>
                    <td style="padding: 8px; color: #8b8b9e; text-align: right;">{data.get('progress_percent', 0)}%</td>
                </tr>
                """
            goals_html += "</table></div>"
        
        # Weak spots
        weak_spots_html = ""
        if analysis.get("weak_spots"):
            weak_spots_html = """
            <div style="background: rgba(255, 71, 87, 0.1); border: 1px solid rgba(255, 71, 87, 0.3); border-radius: 8px; padding: 16px; margin: 16px 0;">
                <h3 style="color: #ff4757; margin: 0 0 12px 0;">⚠️ Weak Spots (Visibility < 20%)</h3>
                <ul style="color: #aaa; margin: 0; padding-left: 20px;">
            """
            for spot in analysis["weak_spots"]:
                weak_spots_html += f'<li style="margin: 8px 0;">{spot["intent"]}: {spot["visibility"]}%</li>'
            weak_spots_html += "</ul></div>"
        
        html_body = f"""
        <html>
        <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0a0a0f; color: #fff; padding: 20px;">
            <div style="max-width: 600px; margin: 0 auto;">
                <div style="text-align: center; margin-bottom: 32px;">
                    <p style="color: #00ff88; font-size: 12px; letter-spacing: 2px; margin: 0;">LLM VISIBILITY AUDIT</p>
                    <h1 style="font-size: 28px; margin: 8px 0;">{TARGET_COMPANY}</h1>
                    <p style="color: #8b8b9e;">{get_timestamp()}</p>
                </div>
                
                <div style="display: flex; gap: 16px; margin-bottom: 24px;">
                    <div style="flex: 1; background: linear-gradient(135deg, rgba(0, 255, 136, 0.1) 0%, #1a1a24 100%); border: 1px solid #00ff88; border-radius: 12px; padding: 24px; text-align: center;">
                        <p style="color: #8b8b9e; font-size: 12px; margin: 0;">VISIBILITY SCORE</p>
                        <p style="font-size: 48px; font-weight: bold; margin: 8px 0; color: {score_color};">{score}%</p>
                    </div>
                    <div style="flex: 1; background: #1a1a24; border: 1px solid #2a2a3a; border-radius: 12px; padding: 24px; text-align: center;">
                        <p style="color: #8b8b9e; font-size: 12px; margin: 0;">RANKING</p>
                        <p style="font-size: 48px; font-weight: bold; margin: 8px 0; color: #fff;">#{rank}</p>
                        <p style="color: #5a5a6e; font-size: 12px; margin: 0;">of {total_companies} companies</p>
                    </div>
                </div>
                
                {change_html}
                
                <h3 style="color: #fff; margin: 24px 0 12px 0;">📊 Performance by LLM</h3>
                <table style="width: 100%; border-collapse: collapse; background: #1a1a24; border-radius: 8px; overflow: hidden;">
                    <thead>
                        <tr style="background: #12121a;">
                            <th style="padding: 12px; text-align: left; color: #8b8b9e; font-size: 12px;">LLM</th>
                            <th style="padding: 12px; text-align: left; color: #8b8b9e; font-size: 12px;">VISIBILITY</th>
                            <th style="padding: 12px; text-align: left; color: #8b8b9e; font-size: 12px;">MENTIONS</th>
                            <th style="padding: 12px; text-align: left; color: #8b8b9e; font-size: 12px;">WEEKLY</th>
                            <th style="padding: 12px; text-align: left; color: #8b8b9e; font-size: 12px;">MONTHLY</th>
                        </tr>
                    </thead>
                    <tbody>
                        {llm_rows}
                    </tbody>
                </table>
                
                {goals_html}
                
                {weak_spots_html}
                
                <div style="text-align: center; margin-top: 32px; padding-top: 24px; border-top: 1px solid #2a2a3a;">
                    <p style="color: #5a5a6e; font-size: 12px;">This is an automated report from the LLM Visibility Audit Tool.</p>
                    <p style="color: #5a5a6e; font-size: 12px;">Full dashboard attached.</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        # Attach HTML body
        msg_alternative = MIMEMultipart('alternative')
        msg.attach(msg_alternative)
        
        # Plain text version
        plain_text = f"""
LLM Visibility Audit Report - {TARGET_COMPANY}
Generated: {get_timestamp()}

OVERALL METRICS:
- Visibility Score: {score}%
- Ranking: #{rank} of {total_companies} companies

BY LLM:
"""
        for llm, data in analysis.get("by_llm", {}).items():
            plain_text += f"- {llm}: {data['visibility_score']}% ({data['mentions']}/{data['queries']} queries)\n"
        
        if analysis.get("weak_spots"):
            plain_text += "\nWEAK SPOTS:\n"
            for spot in analysis["weak_spots"]:
                plain_text += f"- {spot['intent']}: {spot['visibility']}%\n"
        
        msg_alternative.attach(MIMEText(plain_text, 'plain'))
        msg_alternative.attach(MIMEText(html_body, 'html'))
        
        # Attach screenshot if available
        if screenshot_path and os.path.exists(screenshot_path):
            with open(screenshot_path, 'rb') as f:
                img = MIMEImage(f.read())
                img.add_header('Content-Disposition', 'attachment', filename=os.path.basename(screenshot_path))
                msg.attach(img)
        
        # Attach dashboard HTML if available
        if dashboard_path and os.path.exists(dashboard_path):
            with open(dashboard_path, 'rb') as f:
                part = MIMEBase('text', 'html')
                part.set_payload(f.read())
                encoders.encode_base64(part)
                part.add_header('Content-Disposition', 'attachment', filename=os.path.basename(dashboard_path))
                msg.attach(part)
        
        # Send email
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
        
        logger.info(f"✅ Email sent successfully to {EMAIL_TO}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to send email: {e}")
        traceback.print_exc()
        return False


def test_email():
    """Send a test email to verify configuration."""
    if not EMAIL_ENABLED:
        print("❌ Email not configured. Set these environment variables:")
        print("   SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, EMAIL_TO")
        return False
    
    try:
        msg = MIMEMultipart()
        msg['Subject'] = f"🔍 LLM Visibility Audit - Test Email"
        msg['From'] = SMTP_USER
        msg['To'] = EMAIL_TO
        
        body = f"""
        This is a test email from the LLM Visibility Audit Tool.
        
        Configuration:
        - SMTP Host: {SMTP_HOST}
        - SMTP Port: {SMTP_PORT}
        - From: {SMTP_USER}
        - To: {EMAIL_TO}
        
        If you received this, your email configuration is working correctly!
        """
        
        msg.attach(MIMEText(body, 'plain'))
        
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
        
        print(f"✅ Test email sent successfully to {EMAIL_TO}")
        return True
        
    except Exception as e:
        print(f"❌ Failed to send test email: {e}")
        traceback.print_exc()
        return False


def show_cron_setup():
    """Display cron setup instructions."""
    script_path = os.path.abspath(__file__)
    python_path = sys.executable
    
    print("\n" + "="*60)
    print("📅 CRON SETUP INSTRUCTIONS")
    print("="*60)
    print("""
To run this script automatically every week, add a cron job:

1. Open your crontab:
   crontab -e

2. Add one of these lines (choose your preferred schedule):

   # Run every Sunday at 6:00 AM
   0 6 * * 0 cd {dir} && {python} {script} >> {dir}/cron.log 2>&1

   # Run every Monday at 9:00 AM
   0 9 * * 1 cd {dir} && {python} {script} >> {dir}/cron.log 2>&1

   # Run every Saturday at midnight
   0 0 * * 6 cd {dir} && {python} {script} >> {dir}/cron.log 2>&1

3. Make sure your .env file is in the same directory with your API keys.

4. (Optional) Set up a systemd service for more robust scheduling:

   Create /etc/systemd/system/visibility-audit.service:
   ---
   [Unit]
   Description=LLM Visibility Audit
   After=network.target

   [Service]
   Type=oneshot
   WorkingDirectory={dir}
   ExecStart={python} {script}
   User={user}
   Environment=PATH=/usr/local/bin:/usr/bin:/bin

   [Install]
   WantedBy=multi-user.target
   ---

   Create /etc/systemd/system/visibility-audit.timer:
   ---
   [Unit]
   Description=Run LLM Visibility Audit Weekly

   [Timer]
   OnCalendar=Sun 06:00
   Persistent=true

   [Install]
   WantedBy=timers.target
   ---

   Then enable: sudo systemctl enable visibility-audit.timer
""".format(
        dir=os.path.dirname(script_path),
        python=python_path,
        script=script_path,
        user=os.getenv('USER', 'your_user')
    ))


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

def main():
    """Main entry point."""
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='LLM Visibility Audit Tool')
    parser.add_argument('--test-email', action='store_true', help='Send a test email')
    parser.add_argument('--setup-cron', action='store_true', help='Show cron setup instructions')
    parser.add_argument('--no-email', action='store_true', help='Skip sending email notification')
    parser.add_argument('--no-screenshot', action='store_true', help='Skip screenshot capture')
    args = parser.parse_args()
    
    # Handle special commands
    if args.test_email:
        test_email()
        return
    
    if args.setup_cron:
        show_cron_setup()
        return
    
    # Start audit
    logger.info("\n" + "="*60)
    logger.info("🚀 STARTING LLM VISIBILITY AUDIT")
    logger.info("="*60)
    logger.info(f"Target Company: {TARGET_COMPANY}")
    logger.info(f"Target Region: {TARGET_REGION}")
    logger.info(f"Prompt Categories: {len(PROMPTS_BY_INTENT)}")
    logger.info(f"Total Prompts: {sum(len(p) for p in PROMPTS_BY_INTENT.values())}")
    logger.info(f"Runs per Prompt: {RUNS_PER_PROMPT}")
    logger.info(f"Archive Retention: {ARCHIVE_RETENTION_WEEKS} weeks")
    logger.info(f"Email Notifications: {'Enabled' if EMAIL_ENABLED else 'Disabled'}")
    
    # Get previous results for weekly comparison
    previous_data = get_previous_results()
    if previous_data:
        logger.info(f"📊 Found previous audit from {previous_data.get('_archive_date', 'unknown date')}")
    
    # Get monthly data for monthly comparison
    monthly_data = get_monthly_results()
    if monthly_data:
        logger.info(f"📅 Found monthly comparison data from {monthly_data.get('_archive_date', 'unknown date')}")
    
    # Get historical trend data (last 90 days)
    trend_data = get_historical_trend(days=90)
    if trend_data:
        logger.info(f"📈 Found {len(trend_data)} historical data points for trend analysis")
    
    # Run audit
    try:
        results = run_audit()
    except Exception as e:
        logger.error(f"❌ Audit failed with error: {e}")
        traceback.print_exc()
        return
    
    if not results:
        logger.error("❌ No results collected. Exiting.")
        return
    
    # Analyze
    logger.info("📊 Analyzing results...")
    analysis = analyze_results(results)
    
    # Calculate weekly changes
    weekly_changes = calculate_changes(analysis, previous_data, period_label="week")
    
    # Calculate monthly changes
    monthly_changes = calculate_changes(analysis, monthly_data, period_label="month")
    
    # Calculate goal progress
    logger.info("🎯 Calculating goal progress...")
    goal_progress = calculate_goal_progress(analysis)
    
    # Get monthly aggregates for comparison (last 3 months)
    logger.info(f"📅 Getting monthly aggregates (last {MONTHS_TO_COMPARE} months)...")
    monthly_aggregates = get_monthly_aggregates(months=MONTHS_TO_COMPARE)
    if monthly_aggregates:
        logger.info(f"📊 Found {len(monthly_aggregates)} months of historical data for comparison")
    
    # Create timestamp for this run
    timestamp = get_timestamp()
    ensure_archive_dir()
    
    # Save current results
    results_file = "audit_results.json"
    archive_results_file = f"{ARCHIVE_DIR}/audit_results_{timestamp}.json"
    
    results_data = {"analysis": analysis, "raw_results": results, "goal_progress": goal_progress}
    
    with open(results_file, "w") as f:
        json.dump(results_data, f, indent=2)
    shutil.copy(results_file, archive_results_file)
    logger.info(f"✅ Results saved to {results_file}")
    logger.info(f"📁 Archived to {archive_results_file}")
    
    # Generate dashboard with weekly, monthly changes, trend data, goals, and monthly comparison
    logger.info("🎨 Generating HTML dashboard...")
    dashboard_html = generate_html_dashboard(
        analysis, 
        results, 
        weekly_changes=weekly_changes,
        monthly_changes=monthly_changes,
        trend_data=trend_data,
        goal_progress=goal_progress,
        monthly_aggregates=monthly_aggregates
    )
    
    dashboard_file = "visibility_dashboard.html"
    archive_dashboard_file = f"{ARCHIVE_DIR}/visibility_dashboard_{timestamp}.html"
    
    with open(dashboard_file, "w") as f:
        f.write(dashboard_html)
    shutil.copy(dashboard_file, archive_dashboard_file)
    logger.info(f"✅ Dashboard saved to {dashboard_file}")
    logger.info(f"📁 Archived to {archive_dashboard_file}")

    # Generate the per-query response transcript page
    logger.info("📝 Generating response transcript page...")
    responses_html = generate_responses_html(results)
    responses_file = "responses.html"
    with open(responses_file, "w") as f:
        f.write(responses_html)
    shutil.copy(responses_file, f"{ARCHIVE_DIR}/responses_{timestamp}.html")
    logger.info(f"✅ Responses page saved to {responses_file}")
    
    # Capture screenshot
    screenshot_file = None
    if not args.no_screenshot:
        screenshot_file = f"visibility_dashboard_{timestamp}.png"
        archive_screenshot_file = f"{ARCHIVE_DIR}/visibility_dashboard_{timestamp}.png"
        
        if capture_screenshot(dashboard_file, screenshot_file):
            shutil.copy(screenshot_file, archive_screenshot_file)
            logger.info(f"📁 Screenshot archived to {archive_screenshot_file}")
    
    # Clean up old archives
    cleanup_old_archives()
    
    # Print summary
    logger.info("\n" + "="*60)
    logger.info("📈 AUDIT SUMMARY")
    logger.info("="*60)
    logger.info(f"🎯 Overall Visibility Score: {analysis['overall']['visibility_score']}%")
    logger.info(f"🏆 Overall Ranking: #{analysis['overall']['target_rank']} of {analysis['overall']['total_companies_mentioned']}")
    
    # Show goal progress
    if goal_progress and goal_progress.get("by_llm"):
        summary = goal_progress.get("summary", {})
        logger.info(f"\n🎯 GOALS PROGRESS: {summary.get('achieved', 0)}/{summary.get('total', 0)} LLMs achieved target")
        logger.info("   " + "-"*50)
        for llm, data in goal_progress.get("by_llm", {}).items():
            status_icon = "✅" if data["status"] == "achieved" else "🟡" if data["status"] == "in_progress" else "🔴"
            logger.info(f"   {status_icon} {llm}: {data['current']}% / {data['target']}% target ({data['progress_percent']}% progress)")
    
    # Show weekly changes if available
    if weekly_changes.get("has_previous"):
        logger.info(f"\n📊 Weekly Changes (since {weekly_changes['previous_date']}):")
        for summary in weekly_changes.get("summary", []):
            logger.info(f"   {summary}")
    
    # Show monthly changes if available
    if monthly_changes.get("has_previous"):
        logger.info(f"\n📅 Monthly Changes (since {monthly_changes['previous_date']}):")
        for summary in monthly_changes.get("summary", []):
            logger.info(f"   {summary}")
    
    # Show monthly comparison if available
    if monthly_aggregates and len(monthly_aggregates) >= 2:
        logger.info(f"\n📅 Monthly Comparison ({len(monthly_aggregates)} months):")
        for month_data in monthly_aggregates:
            logger.info(f"   {month_data['month_display']}: {month_data['overall']['avg_visibility_score']}% visibility (Rank #{month_data['overall']['avg_rank']:.0f})")
    
    logger.info("\n📊 By LLM:")
    for llm, data in analysis["by_llm"].items():
        change_str = ""
        goal_str = ""
        # Show weekly change
        if weekly_changes.get("by_llm", {}).get(llm):
            llm_change = weekly_changes["by_llm"][llm]
            if llm_change["direction"] == "up":
                change_str = f" (↑{llm_change['change']}% this week)"
            elif llm_change["direction"] == "down":
                change_str = f" (↓{abs(llm_change['change'])}% this week)"
        # Show goal status
        if goal_progress and goal_progress.get("by_llm", {}).get(llm):
            llm_goal = goal_progress["by_llm"][llm]
            if llm_goal["status"] == "achieved":
                goal_str = " ✅"
            elif llm_goal["status"] == "in_progress":
                goal_str = f" 🎯{llm_goal['remaining']}% to goal"
        logger.info(f"   {llm}: {data['visibility_score']}%{change_str}{goal_str} ({data['mentions']}/{data['queries']} queries)")
    
    if analysis["weak_spots"]:
        logger.info("\n⚠️  Weak Spots:")
        for spot in analysis["weak_spots"]:
            logger.info(f"   - {spot['intent']}: {spot['visibility']}%")
    
    # Send email notification with both weekly and monthly changes
    if not args.no_email and EMAIL_ENABLED:
        send_email_notification(analysis, weekly_changes, monthly_changes, screenshot_file, dashboard_file, goal_progress)
    
    logger.info("\n✅ Audit complete!")
    logger.info(f"   Dashboard: {dashboard_file}")
    logger.info(f"   Raw data: {results_file}")
    if screenshot_file:
        logger.info(f"   Screenshot: {screenshot_file}")
    logger.info(f"   Archives: {ARCHIVE_DIR}/")


if __name__ == "__main__":
    main()