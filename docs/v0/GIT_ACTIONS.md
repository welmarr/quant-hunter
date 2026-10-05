# V0 Git command audit

Commands through the Phase A cold-clone verification are recorded below. Later
checkpoint commands are appended at the next documentary checkpoint; the full
turn-end report must include every command, including failures. No force-push,
history rewrite, main merge, branch deletion or destructive cleanup was used.

1. `git status --short --branch` | READ-ONLY | Inspect current work | Result: Failed before execution: sandbox ACL setup error
2. `git branch -avv` | READ-ONLY | Inspect existing branches | Result: Failed before execution: sandbox ACL setup error
3. `git remote -v` | READ-ONLY | Inspect backup remote | Result: Failed before execution: sandbox ACL setup error
4. `git status --short --branch` | READ-ONLY | Inspect backup preflight | Result: Succeeded; exact output retained in the conversation audit.
5. `git branch -avv` | READ-ONLY | Inspect backup preflight | Result: Succeeded; exact output retained in the conversation audit.
6. `git remote -v` | READ-ONLY | Inspect backup preflight | Result: Succeeded; exact output retained in the conversation audit.
7. `git ls-remote --heads origin` | READ-ONLY | Inspect branch and backup safety | Result: Succeeded; exact output retained in the conversation audit.
8. `git status --short --ignored` | READ-ONLY | Inspect branch and backup safety | Result: Succeeded; exact output retained in the conversation audit.
9. `git log -5 --oneline --decorate` | READ-ONLY | Inspect branch and backup safety | Result: Succeeded; exact output retained in the conversation audit.
10. `git switch -c work-before-v0 7346cf4f79ca5897777c0118f8cf4c2292be929e` | LOCAL WRITE | Preserve the clean pre-V0 commit | Result: Succeeded; exact output retained in the conversation audit.
11. `git push -u origin work-before-v0` | REMOTE WRITE | Back up all committed project work | Result: Succeeded; exact output retained in the conversation audit.
12. `git ls-remote --heads origin work-before-v0` | READ-ONLY | Verify remote backup SHA | Result: Succeeded; exact output retained in the conversation audit.
13. `git switch -c version-0 7346cf4f79ca5897777c0118f8cf4c2292be929e` | LOCAL WRITE | Start V0 from the saved commit | Result: Succeeded; exact output retained in the conversation audit.
14. `git push -u origin version-0` | REMOTE WRITE | Establish V0 integration branch | Result: Succeeded; exact output retained in the conversation audit.
15. `git diff --check` | READ-ONLY | Checkpoint V0 mission and isolate agent work | Result: Succeeded; exact output retained in the conversation audit.
16. `git add .gitignore docs/DECISIONS.md docs/PROJECT_STATUS.md docs/ROADMAP.md docs/WORKING_PROTOCOL.md docs/v0 artifacts/status.json` | LOCAL WRITE | Checkpoint V0 mission and isolate agent work | Result: Succeeded; exact output retained in the conversation audit.
17. `git commit -m "docs: preserve V0 mandate and reconcile continuous branch authority"` | LOCAL WRITE | Checkpoint V0 mission and isolate agent work | Result: Succeeded; exact output retained in the conversation audit.
18. `git push origin version-0` | REMOTE WRITE | Checkpoint V0 mission and isolate agent work | Result: Succeeded; exact output retained in the conversation audit.
19. `git worktree add -b codex/v0-simulation .tools/v0-worktrees/simulation version-0` | LOCAL WRITE | Checkpoint V0 mission and isolate agent work | Result: Succeeded; exact output retained in the conversation audit.
20. `git worktree add -b codex/v0-lifecycle .tools/v0-worktrees/lifecycle version-0` | LOCAL WRITE | Checkpoint V0 mission and isolate agent work | Result: Succeeded; exact output retained in the conversation audit.
21. `git worktree add -b codex/v0-ui .tools/v0-worktrees/ui version-0` | LOCAL WRITE | Isolate V0 frontend work | Result: Succeeded; exact output retained in the conversation audit.
22. `git rev-parse HEAD main work-before-v0` | READ-ONLY | Record V0 source parent and preserved branch tips | Result: Succeeded; exact output retained in the conversation audit.
23. `git status --short --branch` | READ-ONLY | Inspect the first V0 implementation checkpoint | Result: Succeeded; exact output retained in the conversation audit.
24. `git diff --stat` | READ-ONLY | Review checkpoint scope | Result: Succeeded; exact output retained in the conversation audit.
25. `git diff --check` | READ-ONLY | Check checkpoint whitespace | Result: Succeeded; exact output retained in the conversation audit.
26. `git diff --check` | READ-ONLY | Verify final checkpoint whitespace | Result: Succeeded; exact output retained in the conversation audit.
27. `git add .github/workflows/quality.yml README.md docs/DECISIONS.md docs/PROJECT_STATUS.md docs/REGRESSION_GUARD.md docs/RISK_REGISTER.md docs/v0 artifacts/status.json pyproject.toml uv.lock frontend scripts/windows/start_v0.ps1 scripts/windows/diagnose_v0.ps1 src/quant_hunter/lab src/quant_hunter/simulation src/quant_hunter/web tests/test_v0_lab.py tests/test_v0_runtime.py tests/test_v0_simulation.py tests/test_v0_web.py` | LOCAL WRITE | Stage verified first V0 workflow without local data or caches | Result: Succeeded; exact output retained in the conversation audit.
28. `git diff --cached --stat` | READ-ONLY | Review staged checkpoint scope | Result: Succeeded; exact output retained in the conversation audit.
29. `git commit -m "feat: deliver governed synthetic V0 workstation with verified accounting"` | LOCAL WRITE | Save the tested first executable V0 slice | Result: Succeeded; exact output retained in the conversation audit.
30. `git push origin version-0` | REMOTE WRITE | Back up tested V0 implementation | Result: Succeeded; exact output retained in the conversation audit.
31. `git rev-parse HEAD main work-before-v0` | READ-ONLY | Record checkpoint and preserved local branch tips | Result: Succeeded; exact output retained in the conversation audit.
32. `git ls-remote --heads origin version-0 work-before-v0 main` | READ-ONLY | Verify remote checkpoint and untouched backup/main | Result: Succeeded; exact output retained in the conversation audit.
33. `git clone --depth 1 --single-branch --branch version-0 https://github.com/welmarr/quant-hunter.git .tools/v0-cold-start` | LOCAL WRITE | Create independent clean-clone startup proof | Result: Succeeded; exact output retained in the conversation audit.
34. `git rev-parse HEAD` | READ-ONLY | Resolve commit inside the documented clean-clone launcher | Result: Succeeded; exact output retained in the conversation audit.
