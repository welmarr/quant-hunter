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
35. `git status --short --branch` | READ-ONLY | Inspect Phase B checkpoint changes | Result: Succeeded; exact output retained in the conversation audit.
36. `git diff --check` | READ-ONLY | Check Phase B whitespace | Result: Succeeded; exact output retained in the conversation audit.
37. `git diff --stat` | READ-ONLY | Review Phase B tracked scope | Result: Succeeded; exact output retained in the conversation audit.
38. `git diff --check` | READ-ONLY | Verify final Phase B documentation and code whitespace | Result: Succeeded; exact output retained in the conversation audit.
39. `git add artifacts/status.json docs/DECISIONS.md docs/DEVELOPMENT.md docs/PROJECT_STATUS.md docs/REGRESSION_GUARD.md docs/RISK_REGISTER.md docs/v0 frontend src/quant_hunter/imports src/quant_hunter/sources src/quant_hunter/web tests/test_v0_backup.py tests/test_v0_data_access.py tests/test_v0_imports.py tests/test_v0_sources.py` | LOCAL WRITE | Stage verified Phase B source and documentation only | Result: Succeeded; exact output retained in the conversation audit.
40. `git diff --cached --stat` | READ-ONLY | Inspect staged files before preserving Phase B | Result: Succeeded; exact output retained in the conversation audit.
41. `git commit -m "feat: add immutable imports, bounded sources and verified private recovery"` | LOCAL WRITE | Save the fully tested Phase B checkpoint | Result: Saved checkpoint 5da83fd.
42. `git push origin version-0` | REMOTE WRITE | Back up Phase B progress on the authorized integration branch | Result: Pushed 5da83fd to origin/version-0.
43. `git rev-parse HEAD main work-before-v0` | READ-ONLY | Record new checkpoint and preserved local branches | Result: Confirmed version-0 5da83fd; main c350c26 and backup 7346cf4 unchanged.
44. `git ls-remote --heads origin version-0 work-before-v0 main` | READ-ONLY | Verify remote backup and unchanged protected branches | Result: Confirmed origin/version-0 5da83fd; remote main e0ba326 and backup 7346cf4 unchanged.
45. `git status --short --branch` | READ-ONLY | Inspect corrected Phase C checkpoint scope | Result: Succeeded; whitespace check had only line-ending notices.
46. `git diff --stat` | READ-ONLY | Review tracked Phase C changes | Result: Succeeded; whitespace check had only line-ending notices.
47. `git diff --check` | READ-ONLY | Check Phase C whitespace before staging | Result: Succeeded; whitespace check had only line-ending notices.
48. `git add artifacts/status.json docs/DECISIONS.md docs/DEVELOPMENT.md docs/PROJECT_STATUS.md docs/REGRESSION_GUARD.md docs/RISK_REGISTER.md docs/v0 frontend pyproject.toml uv.lock schemas/v1/common.schema.json schemas/v1/instrument.schema.json scripts/windows/start_v0.ps1 src/quant_hunter/config/schema.py src/quant_hunter/identity/ids.py src/quant_hunter/credentials src/quant_hunter/markets src/quant_hunter/sources src/quant_hunter/web tests/fixtures/schemas/valid_objects.json tests/test_schemas.py tests/test_v0_data_access.py tests/test_v0_connections.py tests/test_v0_credentials.py tests/test_v0_instruments.py tests/test_v0_markets.py tests/test_v0_source_equities.py` | LOCAL WRITE | Stage verified private configuration and market checkpoint | Result: Staged 57 scoped Phase C files; only line-ending notices.
49. `git diff --cached --stat` | READ-ONLY | Review staged Phase C scope | Result: Reviewed 57 files, 8,440 insertions and 91 deletions.
50. `git diff --cached --check` | READ-ONLY | Verify staged Phase C whitespace | Result: Passed with no whitespace errors.
51. `git commit -m "feat: add private source configuration and canonical market metadata"` | LOCAL WRITE | Save tested private configuration and market checkpoint | Result: Created 796771c81a7c49768ebe7040730c88707c98827b.
52. `git push origin version-0` | REMOTE WRITE | Back up verified Phase C progress | Result: Pushed version-0 from 5da83fd to 796771c.
53. `git rev-parse HEAD main work-before-v0` | READ-ONLY | Record saved Phase C and unchanged local branch tips | Result: Confirmed local 796771c / main c350c26 / backup 7346cf4.
54. `git ls-remote --heads origin version-0 work-before-v0 main` | READ-ONLY | Verify remote Phase C and preserved main/backup | Result: Confirmed remote 796771c / main e0ba326 / backup 7346cf4.
55. `git status --short --branch` | READ-ONLY | Inspect next V0 integration scope | Result: Confirmed version-0 with next integration changes; no branch divergence.
56. `git rev-parse HEAD main work-before-v0` | READ-ONLY | Reconcile local working and preserved branch tips | Result: Confirmed local working and preserved branch tips unchanged.
57. `git ls-remote --heads origin version-0 work-before-v0 main` | READ-ONLY | Reconcile remote V0 and preserved backup/main | Result: Confirmed remote working and preserved branch tips unchanged.
58. `git status --short --branch` | READ-ONLY | Inspect all preserved checkpoint changes before staging | Result: Confirmed version-0 without divergence and the next integration changes.
59. `git diff --stat` | READ-ONLY | Review tracked checkpoint scope | Result: 33 tracked files changed; expected LF-normalization warnings only; new files remain separately listed by status.
60. `git diff --check` | READ-ONLY | Check tracked patch whitespace before saving | Result: Passed; expected LF-normalization warnings only.
61. `git status --short --branch` | READ-ONLY | Confirm version-0 and checkpoint scope before staging | Result: Confirmed version-0 and expected checkpoint scope.
62. `git diff --check` | READ-ONLY | Validate final tracked patch whitespace | Result: Passed; LF normalization warnings only
63. `git add -- artifacts/status.json docs frontend pyproject.toml schemas src tests uv.lock` | LOCAL WRITE | Stage reviewed V0 code, tests and documentation while excluding private runtime data/caches | Result: Passed
64. `git diff --cached --name-only` | READ-ONLY | Inspect exact staged file membership | Result: 103 staged paths; no secrets, private datasets or caches.
65. `git diff --cached --check` | READ-ONLY | Verify staged patch whitespace | Result: Passed
66. `git commit -m "feat: integrate governed studies and priority source workflows"` | LOCAL WRITE | Save fully tested V0 source/research checkpoint | Result: Created 0541337699a246762fdaae1b83819b9ecbc18301; 103 files changed.
67. `git push origin version-0` | REMOTE WRITE | Back up the tested checkpoint on the authorized integration branch | Result: Pushed version-0 from 796771c to 0541337.
68. `git rev-parse HEAD main work-before-v0` | READ-ONLY | Record saved checkpoint and verify unchanged local protected tips | Result: HEAD 0541337; main c350c26 and work-before-v0 7346cf4 unchanged.
69. `git ls-remote --heads origin version-0 work-before-v0 main` | READ-ONLY | Verify remote backup and preserved branch tips | Result: Origin version-0 0541337; main e0ba326 and work-before-v0 7346cf4 unchanged.
70. `git diff -- .github/workflows/quality.yml` | READ-ONLY | Review the bounded Windows CI capacity correction | Result: Reviewed Windows-only 10→30 minute timeout; all test commands unchanged.
71. `git add -- .github/workflows/quality.yml docs/v0/CI_CAPACITY.md` | LOCAL WRITE | Stage only reviewed CI capacity correction and retained evidence | Result: Staged only workflow and CI_CAPACITY.md.
72. `git diff --cached --check` | READ-ONLY | Verify staged CI repair whitespace | Result: Passed.
73. `git commit -m "ci: allow expanded Windows regression suite to finish"` | LOCAL WRITE | Save reviewed CI capacity correction without omitting tests | Result: Created 8c6eabb808fdb45115d91e2c2287c479623c96f7; two scoped files.
74. `git push origin version-0` | REMOTE WRITE | Back up CI repair on the authorized integration branch | Result: Pushed version-0 from 0541337 to 8c6eabb.
75. `git rev-parse HEAD` | READ-ONLY | Record exact CI repair commit | Result: 8c6eabb808fdb45115d91e2c2287c479623c96f7.
76. `git ls-remote --heads origin version-0 work-before-v0 main` | READ-ONLY | Verify remote CI repair and preserved backup/main | Result: Remote version-0 8c6eabb; work-before-v0 7346cf4 and main e0ba326 unchanged.
77. `git status --short` | READ-ONLY | Inspect publication checkpoint before selective commit | Result: Publication source, tests, frontend and documentation modified; ignored private data excluded.
78. `git diff --check` | READ-ONLY | Check publication checkpoint whitespace | Result: Passed.
79. `git diff --stat` | READ-ONLY | Review publication checkpoint scope | Result: Reviewed publication runtime/API/frontend/tests and evidence documentation.
