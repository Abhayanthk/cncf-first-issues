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
import yaml

TOKEN = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
LOOKBACK_DAYS = 100
MAX_ISSUES = 100

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ORGS_FILE = os.path.join(BASE_DIR, "..", "orgs.json")
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

> 🔄 **Live Feed**: This list is currently updated manually. (GitHub Actions automation coming soon!)
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
        
        # Format labels nicely (case-insensitive filter, sanitize pipes/newlines)
        raw_labels = []
        for l in it.get("labels", []):
            name = l.get("name", "")
            if name.lower() != "good first issue":
                clean_name = name.replace("|", "-").replace("\n", " ")
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


def main():
    orgs = discover_cncf_orgs()
    if not orgs:
        print("Warning: no CNCF orgs discovered (landscape/cache unavailable). Proceeding without org filter.")
        orgs = None
        
    # Use YYYY-MM-DD format as required by GitHub Search qualifier syntax to avoid timezone ambiguity
    since = (datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    
    # Global search query
    q = f'is:issue is:open label:"good first issue" no:assignee created:>{since}'
    
    issues = []
    page = 1
    
    # Paginate through global results
    while len(issues) < MAX_ISSUES and page <= 10:
        url = f"{GH_API_URL}?q={urllib.parse.quote(q)}&sort=created&order=desc&per_page=100&page={page}"
        try:
            resp = gh_api_request(url)
            items = resp.get("items", [])
            
            for it in items:
                repo_url = it.get("repository_url", "")
                if "/repos/" not in repo_url:
                    continue
                    
                issue_org = repo_url.split("/repos/")[1].split("/")[0].lower()
                
                # Local filter: only keep if it's from a tracked CNCF org, or if orgs failed to load
                if orgs is None or issue_org in orgs:
                    issues.append(it)
                    if len(issues) >= MAX_ISSUES:
                        break
                        
            if len(items) < 100:
                break
            page += 1
            
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", errors="replace")
            except Exception:
                detail = str(getattr(e, "reason", ""))
            print(f"GitHub API error {e.code} on page {page}: {(detail or str(getattr(e, 'reason', ''))).strip()}")
            break
        except Exception as e:
            print(f"Unexpected error: {e}")
            break

    update_readme(issues)
    print(f"Successfully generated README.md with {len(issues)} issues.")


if __name__ == "__main__":
    main()
