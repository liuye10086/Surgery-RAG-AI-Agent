---
name: git-commit
description: Use when the user wants to commit and push changes to GitHub — stages all files, asks user for commit message, pushes to current branch
---

# Git Commit & Push

## Overview

一键暂存全部文件、提交并推送到 GitHub 当前分支。

## 工作流

1. 执行 `git add -A` 暂存所有变更
2. 执行 `git status` 查看暂存区，向用户展示即将提交的文件清单
3. **向用户询问 commit message**（不要自动生成）
4. 执行 `git commit -m "<用户提供的 message>"`
5. 执行 `git push origin <当前分支>`
6. 向用户报告推送结果

## 注意事项

- commit message 必须由用户提供，不可自行生成
- 推送前确认当前分支名称
- 如果 push 被拒绝（如远程有新提交），先 `git pull --rebase` 再重新 push
