#!/bin/sh

# Pre-push hook to protect main and master branches
# This hook receives ref information via stdin in the format:
# <local_ref> <local_sha1> <remote_ref> <remote_sha1>

# Base protected branches (always protected) - EXACT MATCH ONLY
# These must match character-for-character with no prefix or suffix
protected_branches="main master"

# Read the refs being pushed from stdin
while read local_ref local_sha remote_ref remote_sha; do
  # Extract branch name from ref (e.g., refs/heads/main -> main)
  branch_name=$(echo "$remote_ref" | sed 's|refs/heads/||')
  
  # PROTECTION RULE 1: Exact match for "main" and "master"
  # Character-for-character matching - no prefix, no suffix, no variations
  for protected in $protected_branches; do
    if [ "$branch_name" = "$protected" ]; then
      echo "❌ ERROR: You cannot push directly to '$protected'."
      echo "   Branch name must match exactly (character-for-character)."
      echo "   Make a feature branch and use a Pull Request."
      echo "   Protected branches: $protected_branches"
      exit 1
    fi
  done
done

exit 0