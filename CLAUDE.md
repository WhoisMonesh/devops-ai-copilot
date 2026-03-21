# Claude Code Settings

## Commit Rules

- **Owner**: WhoisMonesh <moneshram7@gmail.com>
- **No co-authors**: `Co-Authored-By:` is strictly prohibited in any commit
- **No Claude attribution**: Do not add Claude Opus 4.6 or any Anthropic identity as contributor, co-author, or in commit messages
- **Single author only**: All commits must have only WhoisMonesh as author and committer

## Git Configuration

The following configurations are enforced locally:
- `user.name`: WhoisMonesh
- `user.email`: moneshрам7@gmail.com
- `commit.template`: .gitmessage

## Commit-Msg Hook

A hook at `.git/hooks/commit-msg` blocks any commit containing `Co-Authored-By:` from being created.
