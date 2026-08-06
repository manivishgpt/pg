import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

# Configuration
REPO_PATH = Path(__file__).parent.resolve()  # Defaults to current script directory

# Co-Author Details (Replace with your co-author's GitHub Name and Email)
CO_AUTHOR_NAME = "Vishu"
CO_AUTHOR_EMAIL = "manvishgpt@gmail.com"

# GitHub Repository Remote URL (Optional: paste your GitHub repository URL here if not set)
# Example: "https://github.com/your-username/your-repo-name.git"
REMOTE_URL = ""


def run(cmd, cwd=REPO_PATH, check=True):
    """Helper function to run shell commands safely."""
    result = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True)
    if check and result.returncode != 0:
        print(f"Error running command {' '.join(cmd)}:\n{result.stderr}")
        sys.exit(result.returncode)
    return result


def automate_pair_extraordinaire():
    print(f"🚀 Starting automation in: {REPO_PATH}")

    # 1. Ensure directory is a Git repository
    git_dir = REPO_PATH / ".git"
    if not git_dir.exists():
        print("⚡ Local folder is not a Git repository. Initializing `git init`...")
        run(["git", "init", "-b", "main"])

    # 2. Check if an initial commit exists
    res = run(["git", "rev-parse", "HEAD"], check=False)
    if res.returncode != 0:
        print("📌 No commits found. Creating initial commit on 'main'...")
        readme_path = REPO_PATH / "README.md"
        if not readme_path.exists():
            with open(readme_path, "w", encoding="utf-8") as f:
                f.write("# Nine Project\n")
        run(["git", "add", "."])
        run(["git", "commit", "-m", "Initial commit"])

    # 3. Check for remote 'origin'
    remote_res = run(["git", "remote", "get-url", "origin"], check=False)
    if remote_res.returncode != 0:
        if REMOTE_URL.strip():
            print(f"🔗 Adding remote origin: {REMOTE_URL}")
            run(["git", "remote", "add", "origin", REMOTE_URL.strip()])
        else:
            print("\n❌ Error: No Git remote 'origin' found for this repository.")
            print("To push to GitHub and earn the badge, please either:")
            print("1) Set REMOTE_URL in main.py to your GitHub repo URL: e.g. REMOTE_URL = \"https://github.com/username/repo.git\"")
            print("2) Or run in terminal: git remote add origin https://github.com/<username>/<repo>.git")
            print("Then run `python main.py` again.\n")
            return

    # 4. Create a unique branch name
    branch_name = f"pair-extraordinaire-{uuid.uuid4().hex[:8]}"
    print(f"📌 Creating new branch: {branch_name}")
    run(["git", "checkout", "-b", branch_name])

    # 5. Make a small change to README.md
    readme_path = REPO_PATH / "README.md"
    update_text = f"\n<!-- Co-authored contribution: {branch_name} -->\n"
    with open(readme_path, "a", encoding="utf-8") as f:
        f.write(update_text)

    print("✍️ Updated README.md")

    # 6. Stage the change
    run(["git", "add", "README.md"])

    # 7. Prepare multi-line commit message with Co-authored-by trailer
    commit_msg = (
        f"docs: automated pair programming update\n\n"
        f"Co-authored-by: {CO_AUTHOR_NAME} <{CO_AUTHOR_EMAIL}>"
    )

    # 8. Commit change
    run(["git", "commit", "-m", commit_msg])
    print(f"✅ Created co-authored commit for: {CO_AUTHOR_NAME} <{CO_AUTHOR_EMAIL}>")

    # 9. Push branch to origin
    print(f"⬆️ Pushing branch '{branch_name}' to origin...")
    push_res = run(["git", "push", "-u", "origin", branch_name], check=False)
    if push_res.returncode != 0:
        print(f"❌ Push failed:\n{push_res.stderr}")
        print("Make sure you have created the repository on GitHub and your credentials are configured.")
        return

    print(f"🎉 Branch '{branch_name}' successfully pushed to GitHub!")

    # 10. Attempt to create PR via GitHub CLI (gh) if installed
    if shutil.which("gh"):
        print("🤖 GitHub CLI found! Creating Pull Request...")
        pr_res = run([
            "gh", "pr", "create",
            "--title", "Pair Extraordinaire Automated Contribution",
            "--body", f"Co-authored commit created automatically for badge requirement.\n\nCo-authored-by: {CO_AUTHOR_NAME} <{CO_AUTHOR_EMAIL}>"
        ], check=False)
        if pr_res.returncode == 0:
            print(f"🔗 Pull Request created: {pr_res.stdout.strip()}")
            return

    print("\n💡 Next Step: Open a Pull Request for this branch on GitHub and MERGE it to get your 'Pair Extraordinaire' badge!")


if __name__ == "__main__":
    automate_pair_extraordinaire()

