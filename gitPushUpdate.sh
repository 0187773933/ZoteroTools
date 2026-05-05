#!/bin/bash
set -euo pipefail

is_int() { [[ "${1:-}" =~ ^[0-9]+$ ]]; }

BRANCH="master"
REMOTE_NAME="origin"
REMOTE_URL="git@github-0187773933:0187773933/ZoteroTools.git"
SSH_KEY="/Users/morpheous/.ssh/githubWinStitch"

# Make sure this exact key is loaded
ssh-add -D >/dev/null 2>&1 || true
ssh-add -k "$SSH_KEY" >/dev/null 2>&1

[ -d .git ] || git init

git config user.name  "0187773933"
git config user.email "collincerbus@student.olympic.edu"

# Force origin to use the SSH config alias, not github.com
if git remote | grep -qx "$REMOTE_NAME"; then
	git remote set-url "$REMOTE_NAME" "$REMOTE_URL"
else
	git remote add "$REMOTE_NAME" "$REMOTE_URL"
fi

# Make sure current branch is master
CURRENT_BRANCH="$(git branch --show-current 2>/dev/null || true)"
if [ -z "$CURRENT_BRANCH" ]; then
	git checkout -B "$BRANCH"
elif [ "$CURRENT_BRANCH" != "$BRANCH" ]; then
	git branch -M "$BRANCH"
fi

# skip if no changes
if [ -z "$(git status --porcelain)" ]; then
	echo "Nothing to commit — working tree clean."
	exit 0
fi

LastCommit="$(git log -1 --pretty="%B" 2>/dev/null | xargs || echo "0")"

if is_int "$LastCommit"; then
	NextCommitNumber=$((LastCommit + 1))
else
	echo "Resetting commit number to 1"
	NextCommitNumber=1
fi

git add .

if [ -n "${1:-}" ]; then
	CommitMsg="$1"
	Tag="v1.0.$1"
else
	CommitMsg="$NextCommitNumber"
	Tag="v1.0.$NextCommitNumber"
fi

git commit -m "$CommitMsg"

# safely replace local tag
if git tag | grep -qx "$Tag"; then
	git tag -d "$Tag" >/dev/null 2>&1
fi

# safely replace remote tag
if git ls-remote --tags "$REMOTE_NAME" | grep -q "refs/tags/$Tag$"; then
	git push --delete "$REMOTE_NAME" "$Tag" >/dev/null 2>&1 || true
fi

git tag "$Tag"

# Verify GitHub sees the right identity
echo "Testing SSH identity..."
ssh -T github-0187773933 || true

# Push only current branch and current tag
git push "$REMOTE_NAME" "$BRANCH"
git push "$REMOTE_NAME" "$Tag"