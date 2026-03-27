# Git Hooks Directory

This directory contains Git hooks that protect the `main` and `master` branches

## Protected Branches

- **main** - Production branch (exact match)
- **master** - Legacy production branch (exact match, protected for compatibility)

## Automatic Setup

**Git hooks are automatically configured when you clone the repository!**

The `core.hooksPath` is set to `.git-hooks` automatically, so you don't need to run any setup scripts.

## Manual Setup (If Needed)

If hooks aren't working (e.g., for existing clones before automatic setup was added), run:

```bash
./setup-hooks.sh
```

Or manually:
```bash
git config core.hooksPath .git-hooks
```

## Hooks

- **pre-push**: Blocks direct pushes to protected branches:
  - Exact matches: `main`, `master`
  - Allowed: `dev`, `name-dev`, `dev-something`, `my-dev-branch`
- **post-checkout**: Automatically configures hooksPath on checkout (if not already set)
- **post-merge**: Automatically syncs hooks to submodules on pull

## Testing

Try pushing to a protected branch - you should see an error:
```bash
git checkout main
git push origin main
# ❌ ERROR: You cannot push directly to 'main'.

git checkout master
git push origin master
# ❌ ERROR: You cannot push directly to 'master'.
```

These branches are allowed:
```bash
git checkout name-dev
git push origin name-dev
# ✅ Allowed (dev with dash prefix)

git checkout dev
git push origin dev
# ✅ Allowed

git checkout my-team-dev
git push origin my-team-dev
# ✅ Allowed

git checkout dev-something
git push origin dev-something
# ✅ Allowed (dev with dash suffix)
```

This confirms hooks are working!
