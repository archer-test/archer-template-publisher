import os
import sys
import json
import re
from github import Github
from openai import OpenAI

# Initialize clients
g = Github(os.environ["GITHUB_TOKEN"])
client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

repo = g.get_repo(os.environ["GITHUB_REPOSITORY"])
issue_number = int(os.environ["ISSUE_NUMBER"])
issue = repo.get_issue(number=issue_number)
actor = os.environ["ACTOR"]

def sanitize_filename(title):
    # Convert "Feature: New Login" to "new-login"
    slug = title.lower().strip().replace(' ', '-')
    slug = re.sub(r'[^a-z0-9-]', '', slug)
    return slug

def get_ai_response(messages):
    response = client.chat.completions.create(
        model="gpt-4o", # Or gpt-3.5-turbo
        messages=messages,
        temperature=0.7
    )
    return response.choices[0].message.content

def main():
    # 1. Build Conversation History
    # We treat the issue body as the user prompt, and comments as the thread
    messages = [
        {"role": "system", "content": "You are a Senior Technical Architect. Your goal is to write detailed technical specifications based on GitHub Issues. The output must be valid Markdown."}
    ]
    
    messages.append({"role": "user", "content": f"Title: {issue.title}\n\nBody: {issue.body}"})

    comments = issue.get_comments()
    last_comment_body = ""
    
    for comment in comments:
        role = "assistant" if comment.user.type == "Bot" else "user"
        messages.append({"role": role, "content": comment.body})
        if role == "user":
            last_comment_body = comment.body.strip().lower()

    # 2. Check for Approval
    if last_comment_body == "approved":
        print("Status: Approved. Generating PR.")
        
        # Ask AI to generate the FINAL file content only
        messages.append({"role": "system", "content": "The user has approved the spec. Output ONLY the raw markdown content for the documentation file. Do not include conversational filler."})
        final_spec = get_ai_response(messages)
        
        # Prepare file details
        clean_title = sanitize_filename(issue.title)
        file_name = f"docs/{issue_number:03d}-{clean_title}.md"
        branch_name = f"feature/spec-{issue_number}"
        
        # Create Branch
        sb = repo.get_branch("main")
        try:
            repo.create_git_ref(ref=f"refs/heads/{branch_name}", sha=sb.commit.sha)
        except:
            print("Branch likely exists, updating...")

        # Create/Update File
        try:
            contents = repo.get_contents(file_name, ref=branch_name)
            repo.update_file(contents.path, f"Update spec for issue {issue_number}", final_spec, contents.sha, branch=branch_name)
        except:
            repo.create_file(file_name, f"Add spec for issue {issue_number}", final_spec, branch=branch_name)

        # Create PR
        pr_body = f"This PR adds the approved specification for Issue #{issue_number}."
        try:
            pr = repo.create_pull(title=f"Docs: Spec for {issue.title}", body=pr_body, head=branch_name, base="main")
            issue.create_comment(f"✅ Specification approved! I have created a Pull Request with the documentation: {pr.html_url}")
        except Exception as e:
            issue.create_comment(f"⚠️ Spec approved, but failed to create PR: {str(e)}")

    # 3. Handle Feedback / New Issue
    else:
        print("Status: Drafting/Refining.")
        messages.append({"role": "system", "content": "Based on the conversation, provide an updated Technical Specification. Include: 1. Summary, 2. Implementation Steps, 3. Tech Stack, 4. Edge Cases. ask the user to reply 'approved' if this looks good."})
        
        new_spec = get_ai_response(messages)
        issue.create_comment(new_spec)

if __name__ == "__main__":
    # Prevent bot loops
    if os.environ.get("ACTOR_TYPE") == "Bot":
        print("Skipping bot comment")
        sys.exit(0)
    main()