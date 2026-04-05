#!/bin/sh

# Automatically install and configure hooks
# This runs after every pull/merge, ensuring hooks are always active

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$REPO_ROOT" || exit 0

# Install hooks from .git-hooks to .git/hooks if needed
# NOTE: For submodules, .git is usually a FILE, not a directory
# We only create .git/hooks if .git is actually a directory
if [ -d ".git-hooks" ]; then
    # Only create .git/hooks if .git is actually a directory (not a file)
    if [ -d ".git" ] && [ ! -f ".git" ]; then
        mkdir -p .git/hooks
        for hook in .git-hooks/*; do
            if [ -f "$hook" ] && [ -x "$hook" ]; then
                hook_name=$(basename "$hook")
                # Only copy if missing or outdated
                if [ ! -f ".git/hooks/$hook_name" ] || [ ".git/hooks/$hook_name" -ot "$hook" ]; then
                    cp "$hook" ".git/hooks/$hook_name"
                    chmod +x ".git/hooks/$hook_name"
                fi
            fi
        done
    fi
fi

# Configure hooksPath to use .git-hooks
CURRENT_HOOKS_PATH="$(git config core.hooksPath)"
if [ -z "$CURRENT_HOOKS_PATH" ] || [ "$CURRENT_HOOKS_PATH" != ".git-hooks" ]; then
    git config core.hooksPath .git-hooks
    if [ -f ".git-hooks/pre-push" ]; then
        echo "🔧 Git hooks automatically configured (hooksPath = .git-hooks)"
        echo "✔ You are now protected from pushing to 'main' and 'master' branches"
    fi
fi

# Automatically sync hooks to all submodules
sync_hooks_to_submodule() {
    local submodule_path=$1
    local submodule_name=$2
    
    if [ ! -d "$submodule_path" ]; then
        return
    fi
    
    # Check if it's actually a git repository (submodule)
    # Submodules can have .git as either a directory (initialized) or a file (not fully initialized)
    if [ ! -d "$submodule_path/.git" ] && [ ! -f "$submodule_path/.git" ]; then
        return
    fi
    
    # Additional safety: verify git commands work in the submodule
    # If .git is a file but the submodule isn't properly initialized, git commands will fail
    if ! (cd "$submodule_path" && git rev-parse --git-dir >/dev/null 2>&1); then
        return
    fi
    
    # Create .git-hooks directory in submodule
    mkdir -p "$submodule_path/.git-hooks"
    
    # Copy all hooks from main repo to submodule
    for hook in .git-hooks/*; do
        if [ -f "$hook" ]; then
            hook_name=$(basename "$hook")
            cp "$hook" "$submodule_path/.git-hooks/$hook_name"
            chmod +x "$submodule_path/.git-hooks/$hook_name"
        fi
    done
    
    # Install hooks in submodule's .git/hooks ONLY if .git is a directory
    # For submodules, .git is usually a FILE pointing to parent's .git/modules
    # In that case, we only configure hooksPath, not .git/hooks
    cd "$submodule_path" || return
    
    # Only create .git/hooks if .git is actually a directory (not a file)
    # Check explicitly: .git must exist as a directory, not as a file
    if [ -d ".git" ] && [ ! -f ".git" ]; then
        mkdir -p .git/hooks 2>/dev/null || true
        for hook in .git-hooks/*; do
            if [ -f "$hook" ]; then
                hook_name=$(basename "$hook")
                cp "$hook" ".git/hooks/$hook_name" 2>/dev/null || true
                chmod +x ".git/hooks/$hook_name" 2>/dev/null || true
            fi
        done
    fi
    
    # Configure hooksPath for submodule (this works even if .git is a file)
    git config core.hooksPath .git-hooks 2>/dev/null || true
    
    # Copy .gitconfig to submodule if it exists in main repo
    # Make sure the submodule directory exists before copying
    cd "$REPO_ROOT" || return
    if [ -f "$REPO_ROOT/.gitconfig" ] && [ -d "$submodule_path" ]; then
        # Ensure the submodule directory exists and is writable
        if [ -w "$submodule_path" ] 2>/dev/null; then
        cp "$REPO_ROOT/.gitconfig" "$REPO_ROOT/$submodule_path/.gitconfig" 2>/dev/null || true
        fi
    fi
}

# Sync hooks to all submodules listed in .gitmodules
if [ -f ".gitmodules" ]; then
    # Extract submodule paths from .gitmodules (handles tabs and spaces)
    # This ensures we catch ALL submodules regardless of formatting
    grep -E "^\s*path\s*=\s*" .gitmodules | sed -E 's/^\s*path\s*=\s*//' | sed 's/[[:space:]]*$//' | while IFS= read -r submodule_path; do
        # Skip empty lines
        [ -z "$submodule_path" ] && continue
        
        submodule_name=$(basename "$submodule_path")
        sync_hooks_to_submodule "$submodule_path" "$submodule_name"
    done
else
    # If .gitmodules doesn't exist, this might be a submodule itself
    # In that case, we're done (hooks already installed by parent)
    :
fi
