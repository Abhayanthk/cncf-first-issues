#!/usr/bin/env python3
"""
Scrapes the CNCF landscape and GitHub API to build a markdown table
of fresh, unassigned 'good first issues' for beginners.
"""

import json
import os
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timedelta, timezone
import time
import sys
import yaml

TOKEN = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
LOOKBACK_DAYS = 100
MAX_ISSUES = 100

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ORGS_FILE = os.path.join(BASE_DIR, "..", "orgs.json")
DEAD_ORGS_FILE = os.path.join(BASE_DIR, "..", "dead_orgs.json")
README_FILE = os.path.join(BASE_DIR, "..", "README.md")

LANDSCAPE_URL = "https://raw.githubusercontent.com/cncf/landscape/master/landscape.yml"
GH_API_URL = "https://api.github.com/search/issues"


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def gh_api_request(url):
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "cncf-first-issues-hub",
    }
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
        
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def discover_cncf_orgs():
    """
    Fetches the live CNCF landscape YAML and extracts the GitHub
    organization names for all non-archived hosted projects.
    """
    try:
        with urllib.request.urlopen(LANDSCAPE_URL, timeout=60) as response:
            data = yaml.safe_load(response.read())
            
        orgs = set()
        for cat in (data.get("landscape") or []):
            for sub in (cat.get("subcategories") or []):
                for item in (sub.get("items") or []):
                    status = item.get("project")
                    
                    # Only include active CNCF-hosted projects
                    if not status or status == "archived":
                        continue
                        
                    urls = [item.get("repo_url")]
                    urls.extend([a.get("repo_url") for a in (item.get("additional_repos") or [])])
                    
                    for u in urls:
                        if u and "github.com/" in u:
                            org_name = u.split("github.com/", 1)[1].strip("/").split("/")[0].lower()
                            if org_name:
                                orgs.add(org_name)
                                
        # Cache for fallback
        with open(ORGS_FILE, "w", encoding="utf-8") as f:
            json.dump(sorted(list(orgs)), f)
        return orgs
        
    except Exception as e:
        print(f"Failed to fetch landscape: {e}. Falling back to cache.")
        return set(load_json(ORGS_FILE, []))


def update_readme(issues):
    """
    Generates the README.md content using the provided issues.
    """
    header = """# 🚀 CNCF Good First Issues Hub

Welcome to the **CNCF Beginners Hub**! This repository automatically scrapes the entire Cloud Native Computing Foundation (CNCF) ecosystem to find fresh, unassigned `good first issues`.

If you're looking to start your open-source journey in Kubernetes, Prometheus, Envoy, and other top-tier cloud-native projects, you're in the right place.

> 🔄 **Live Feed**: This list is automatically updated by GitHub Actions every 15 minutes.
> 🌟 **Star this repo** to keep it in your bookmarks!

## 🎯 Active Issues
*Sorted by newest first. Only unassigned issues are shown.*

| Project | Issue | Labels | Created |
|---------|-------|--------|---------|
"""

    rows = []
    for it in issues:
        repo_url = it.get("repository_url", "")
        repo_name = repo_url.split("/repos/")[1] if "/repos/" in repo_url else "Unknown"
        title = (
            it.get("title", "")
            .replace("\\", "\\\\")
            .replace("\r", " ")
            .replace("\n", " ")
            .replace("|", "-")
            .replace("[", "\\[")
            .replace("]", "\\]")
        ) # Prevent markdown table/link breaking
        url = it.get("html_url", "")
        
        # Format labels nicely (case-insensitive filter, sanitize pipes/newlines/brackets)
        raw_labels = []
        for l in it.get("labels", []):
            name = l.get("name", "")
            if name.lower() != "good first issue":
                clean_name = (
                    name.replace("\\", "\\\\")
                    .replace("\r", " ")
                    .replace("\n", " ")
                    .replace("|", "-")
                    .replace("[", "\\[")
                    .replace("]", "\\]")
                )
                raw_labels.append(clean_name)
                
        labels = ", ".join(raw_labels[:2]) # Show max 2 extra labels, without backticks to prevent markdown issues
        
        # Format date
        created_at = datetime.strptime(it["created_at"], "%Y-%m-%dT%H:%M:%SZ")
        date_str = created_at.strftime("%b %d, %Y")

        # Extract repo URL correctly even if API repository_url is missing
        repo_html_url = url.rsplit("/issues/", 1)[0] if "/issues/" in url else f"https://github.com/{repo_name}"
        labels_cell = labels if labels else "-"
        rows.append(f"| **[{repo_name}]({repo_html_url})** | [{title}]({url}) | {labels_cell} | {date_str} |")

    footer = """

---
*Built with ❤️ for the Cloud Native community.*
"""

    with open(README_FILE, "w", encoding="utf-8") as f:
        f.write(header + "\n".join(rows) + footer)


def fetch_chunk_with_bisect(chunk, base_query, dead_orgs):
    if not chunk:
        return []
        
    org_str = " ".join([f"org:{o}" for o in chunk])
    q = f"{base_query} {org_str}"

    url = f"{GH_API_URL}?q={urllib.parse.quote(q)}&sort=created&order=desc&per_page=100"
    
    # Sleep to strictly respect the 30 req/min rate limit
    time.sleep(2.1)
    
    try:
        resp = gh_api_request(url)
        if resp.get("incomplete_results"):
            print("Warning: GitHub returned incomplete results due to timeouts. Skipping chunk to preserve state.")
            return []
        return resp.get("items", [])
        
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", errors="replace")
        except Exception:
            detail = str(getattr(e, "reason", ""))
            
        # Only treat 422 as a dead org if the message explicitly confirms it
        if e.code == 422 and "cannot be searched" in detail:
            if len(chunk) > 1:
                print(f"422 Error on chunk of {len(chunk)} orgs. Bisecting to find the bad org...")
                mid = len(chunk) // 2
                return fetch_chunk_with_bisect(chunk[:mid], base_query, dead_orgs) + fetch_chunk_with_bisect(chunk[mid:], base_query, dead_orgs)
            else:
                dead_org = chunk[0]
                print(f"Isolated dead org: {dead_org}. Saving to cache to ignore forever.")
                dead_orgs.add(dead_org)
                return []
        else:
            raise RuntimeError(f"GitHub API error {e.code}: {detail.strip()}")
    except Exception as e:
        raise RuntimeError(f"Unexpected error during search: {e}")


def main():
    orgs = discover_cncf_orgs()
    if not orgs:
        print("Error: No CNCF orgs discovered (landscape fetch failed and cache empty). Aborting to preserve last valid state.")
        sys.exit(1)
        
    # Load dead orgs cache
    dead_orgs = set(load_json(DEAD_ORGS_FILE, []))
    
    # Filter out known dead orgs before chunking
    orgs = [o for o in orgs if o not in dead_orgs]
        
    # Use YYYY-MM-DD format as required by GitHub Search qualifier syntax to avoid timezone ambiguity
    since = (datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    
    # Base search query
    base_query = f'is:issue is:open label:"good first issue" no:assignee created:>{since}'
    
    # Partition orgs into chunks using disjunctive OR, staying under limits
    chunks = []
    current_orgs = []
    current_len = len(base_query) + 1 # space before qualifiers
    
    for org in sorted(orgs):
        addition = f"org:{org}" if not current_orgs else f" org:{org}"
        
        # Limit to 15 qualifiers (per review recommendation < 16) and under 256 characters
        if len(current_orgs) >= 15 or current_len + len(addition) > 250:
            chunks.append(current_orgs)
            current_orgs = [org]
            current_len = len(base_query) + 1 + len(f"org:{org}")
        else:
            current_orgs.append(org)
            current_len += len(addition)
            
    if current_orgs:
        chunks.append(current_orgs)
        
    all_issues = []
    
    # Execute partitioned searches with bisection logic
    for chunk in chunks:
        try:
            all_issues.extend(fetch_chunk_with_bisect(chunk, base_query, dead_orgs))
        except RuntimeError as e:
            print(f"Critical error: {e}")
            print("Aborting to preserve last valid state. The README will not be overwritten with partial data.")
            sys.exit(1)
    with open(DEAD_ORGS_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(list(dead_orgs)), f)
            
    # Deduplicate and sort newest-first
    unique_issues = {it["html_url"]: it for it in all_issues}.values()
    sorted_issues = sorted(unique_issues, key=lambda x: x.get("created_at", ""), reverse=True)
    
    issues = list(sorted_issues)[:MAX_ISSUES]

    if not issues:
        print("No issues fetched (network failure or empty results). Aborting README update to preserve last valid state.")
        sys.exit(1)

    update_readme(issues)
    print(f"Successfully generated README.md with {len(issues)} issues.")


if __name__ == "__main__":
    main()
