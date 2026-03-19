#!/usr/bin/env python3
"""
Create a Jira Cloud issue safely using environment variables.

Required environment variables:
  JIRA_BASE_URL       Example: https://your-company.atlassian.net
  JIRA_EMAIL          Example: your.name@company.com
  JIRA_API_TOKEN      Atlassian API token

Optional environment variables:
  JIRA_PROJECT_KEY    Default project key if --project is not passed
  JIRA_ISSUE_TYPE     Default issue type if --issue-type is not passed (default: Task)

Examples:
  export JIRA_BASE_URL="https://your-company.atlassian.net"
  export JIRA_EMAIL="your.name@company.com"
  export JIRA_API_TOKEN="xxxxx"
  export JIRA_PROJECT_KEY="CS"

  python3 scripts/jira/create_ticket.py \
    --summary "Integrate Okta with Google for SSO + user/group provisioning" \
    --description "Implement SAML SSO and SCIM provisioning." \
    --issue-type "Task"

  python3 scripts/jira/create_ticket.py \
    --summary "Example with labels and priority" \
    --description "Ticket body" \
    --labels okta google identity \
    --priority High

  python3 scripts/jira/create_ticket.py \
    --summary "Child issue example" \
    --description "Create as sub-task under a parent issue" \
    --issue-type "Sub-task" \
    --parent "CS-10846"
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

import requests
from requests.auth import HTTPBasicAuth


def getenv_required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        print(f"ERROR: Missing required environment variable: {name}", file=sys.stderr)
        sys.exit(1)
    return value


def build_adf_description(text: str) -> dict[str, Any]:
    """
    Convert plain text into a simple Atlassian Document Format document.
    Each non-empty line becomes a paragraph.
    Blank lines are preserved as empty paragraphs.
    """
    lines = text.splitlines() or [text]
    content: list[dict[str, Any]] = []

    if not lines:
        lines = [""]

    for line in lines:
        if line.strip():
            content.append(
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": line}],
                }
            )
        else:
            content.append({"type": "paragraph", "content": []})

    return {
        "type": "doc",
        "version": 1,
        "content": content,
    }


def parse_custom_fields(custom_fields_raw: str | None) -> dict[str, Any]:
    """
    Accept a JSON object string for custom fields.
    Example:
      --custom-fields '{"customfield_12345":"abc","customfield_99999":{"value":"Blue"}}'
    """
    if not custom_fields_raw:
        return {}

    try:
        parsed = json.loads(custom_fields_raw)
    except json.JSONDecodeError as exc:
        print(f"ERROR: --custom-fields is not valid JSON: {exc}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(parsed, dict):
        print("ERROR: --custom-fields must be a JSON object.", file=sys.stderr)
        sys.exit(1)

    return parsed


def create_issue_payload(
    project_key: str,
    issue_type: str,
    summary: str,
    description: str,
    labels: list[str] | None = None,
    priority: str | None = None,
    parent: str | None = None,
    assignee_account_id: str | None = None,
    custom_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "project": {"key": project_key},
        "issuetype": {"name": issue_type},
        "summary": summary,
        "description": build_adf_description(description),
    }

    if labels:
        fields["labels"] = labels

    if priority:
        fields["priority"] = {"name": priority}

    if parent:
        fields["parent"] = {"key": parent}

    if assignee_account_id:
        fields["assignee"] = {"id": assignee_account_id}

    if custom_fields:
        fields.update(custom_fields)

    return {"fields": fields}


def create_issue(
    base_url: str,
    email: str,
    api_token: str,
    payload: dict[str, Any],
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}/rest/api/3/issue"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    response = requests.post(
        url,
        headers=headers,
        auth=HTTPBasicAuth(email, api_token),
        json=payload,
        timeout=timeout_seconds,
    )

    if response.status_code >= 400:
        print("ERROR: Jira API request failed.", file=sys.stderr)
        print(f"HTTP {response.status_code}", file=sys.stderr)
        try:
            print(json.dumps(response.json(), indent=2), file=sys.stderr)
        except ValueError:
            print(response.text, file=sys.stderr)
        sys.exit(1)

    try:
        return response.json()
    except ValueError:
        print("ERROR: Jira returned a non-JSON response.", file=sys.stderr)
        print(response.text, file=sys.stderr)
        sys.exit(1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create a Jira Cloud issue.")
    parser.add_argument("--summary", required=True, help="Issue summary/title")
    parser.add_argument(
        "--description",
        default="",
        help="Issue description as plain text; converted to ADF",
    )
    parser.add_argument(
        "--project",
        default=os.getenv("JIRA_PROJECT_KEY", "").strip(),
        help="Jira project key (defaults to JIRA_PROJECT_KEY)",
    )
    parser.add_argument(
        "--issue-type",
        default=os.getenv("JIRA_ISSUE_TYPE", "Task").strip() or "Task",
        help='Issue type name, e.g. "Task", "Story", "Bug", "Sub-task"',
    )
    parser.add_argument(
        "--labels",
        nargs="*",
        default=[],
        help="Optional labels separated by spaces",
    )
    parser.add_argument(
        "--priority",
        default=None,
        help='Optional priority name, e.g. "Highest", "High", "Medium"',
    )
    parser.add_argument(
        "--parent",
        default=None,
        help="Optional parent issue key for sub-tasks, e.g. CS-10846",
    )
    parser.add_argument(
        "--assignee-account-id",
        default=None,
        help="Optional Jira assignee account ID",
    )
    parser.add_argument(
        "--custom-fields",
        default=None,
        help='Optional custom fields as JSON object, e.g. \'{"customfield_12345":"abc"}\'',
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the payload and exit without creating the issue",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if not args.project:
        print(
            "ERROR: Missing project key. Pass --project or set JIRA_PROJECT_KEY.",
            file=sys.stderr,
        )
        sys.exit(1)

    base_url = getenv_required("JIRA_BASE_URL")
    email = getenv_required("JIRA_EMAIL")
    api_token = getenv_required("JIRA_API_TOKEN")

    custom_fields = parse_custom_fields(args.custom_fields)

    payload = create_issue_payload(
        project_key=args.project,
        issue_type=args.issue_type,
        summary=args.summary,
        description=args.description,
        labels=args.labels,
        priority=args.priority,
        parent=args.parent,
        assignee_account_id=args.assignee_account_id,
        custom_fields=custom_fields,
    )

    if args.dry_run:
        print(json.dumps(payload, indent=2))
        return

    result = create_issue(
        base_url=base_url,
        email=email,
        api_token=api_token,
        payload=payload,
    )

    issue_key = result.get("key", "<unknown>")
    issue_id = result.get("id", "<unknown>")
    self_url = result.get("self", "")

    print(f"Created Jira issue: {issue_key}")
    print(f"Issue ID: {issue_id}")
    if self_url:
        print(f"API URL: {self_url}")
    print(f"Browse URL: {base_url.rstrip('/')}/browse/{issue_key}")


if __name__ == "__main__":
    main()