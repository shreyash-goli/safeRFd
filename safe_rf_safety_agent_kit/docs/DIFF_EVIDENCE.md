# DIFF_EVIDENCE: fork-only diff evidence matrix (task SR-01)

Labels: **SOURCE OBSERVED** = read directly from a GitHub API response or diff text; **INFERENCE** = reasoning from observed facts; **UNKNOWN** = not established. Nothing here asserts safety efficacy.

## 1. Audit metadata
- SOURCE OBSERVED: Audit date 2026-11-09. Auditor: fork-auditor (SR-01).
- SOURCE OBSERVED: Tools: curl 8.7.1 (libcurl/8.7.1 SecureTransport), Python 3.12.4 (`-I`, used only to parse JSON), shasum (macOS). No `gh`, no `timeout`.
- SOURCE OBSERVED: Merge base: `e22092420281c644b928e64d490044dfca4f9175`. API returned `merge_base_commit.sha` and `base_commit.sha` equal to it.
- SOURCE OBSERVED: Upstream `main` head at audit: `86507b6538f51fce57b5a72477165f03999ed7ae` (committer date 2026-07-15T18:07:55Z), matching `upstream_head_at_comparison` in SOURCE_SNAPSHOT.json.

| # | Endpoint (base `https://api.github.com/repos`) | HTTP | sha256 of saved body |
|---|---|---|---|
| A | `/RosettaCommons/RFdiffusion/compare/e22092420281c644b928e64d490044dfca4f9175...audited-fork:main` (JSON) | 200 | `4f5ae33593d644c760d9d6b24a1b0034a3d09397504b682c048b4810a9841999` |
| A-diff | same URL, `Accept: application/vnd.github.diff` | 200 | `fe3753f3037905b0b06a3e6eb0e0de6eed876d6e3701197302a85eedb1fb9e86` (1342 lines; byte-identical to orchestrator's `fork_only.diff`) |
| B | `/audited-fork/safeRFdiffusion/commits/12d5426de27bc6411126262cf3f29bac3a0ce0c1` | 200 | `34542255097abb327a72c2745327eed746cd514fb89e316d0ee81d98b34a1dae` |
| C | `/audited-fork/safeRFdiffusion/commits/5cbd18a39c4607d65bdbf6457be3f79b27a6c3c1` | 200 | `e1c68c4f6c2d50a64639bc31eb5c624cd4792f2b675aaa26655afc600d7a75ad` |
| D | `/RosettaCommons/RFdiffusion/compare/audited-fork:main...main` (fork head vs upstream main) | 200 | `acd5e3fc8762ac8411156ff20657c47bdacc6700595d0cf31a9fda3b72b350be` |
| E | `/RosettaCommons/RFdiffusion/commits/main` | 200 | `95b2306457f920a49f9a5c461928592b75f375049e59adb67b5a73a075e3f31b` |

SOURCE OBSERVED: Orchestrator's saved `erasure_teacher_student.py` has sha256 `1fef6383548419a1175b1732828d04105e384e7f8fc1759d19c7b6207090f17b` (not re-fetched by this auditor; the added file's diff in A-diff was used instead). Saved JSON bodies are time-varying API responses; hashes of B/C/D/E may differ on re-run (D and E certainly change when upstream moves).

## 2. Central methodological point: two different comparisons
- SOURCE OBSERVED (A): base = merge base `e220924`, head = fork `main`. `status: ahead`, `ahead_by: 2`, `behind_by: 0`, `total_commits: 2`. Behind is 0 because the base *is* the ancestor, so nothing in it can be missing from the fork.
- SOURCE OBSERVED (D): base = fork `main`, head = upstream `main`. `status: diverged`, `ahead_by: 36` (upstream commits the fork lacks), `behind_by: 2` (the fork's 2 commits), `merge_base_commit.sha` = `e22092420281c644b928e64d490044dfca4f9175`. Read from the fork's side this is "fork 2 ahead / 36 behind upstream main".
- INFERENCE: `behind_by=0` (A) and "36 behind" (D) are answers to different questions and do not conflict. The 36 upstream commits are *not* fork changes and must not be counted in the fork-only diff. Both comparisons agree on the same merge base and the same 2 fork commits.
- SOURCE OBSERVED: SOURCE_SNAPSHOT.json records `behind_by: 36`, which is the D figure, alongside `ahead_by: 2`. It is correct only when read as "vs current upstream main", not as a field of comparison A. (Reconciliation note in section 6.)
- UNKNOWN: the 36 figure is time-dependent; it was 36 on 2026-11-09 against head `86507b6`.

## 3. Changed files (comparison A)
Commit columns: 1 = `12d5426`, 2 = `5cbd18a` (from endpoints B and C). All statuses are as reported by the API.

| Path | Status | Add | Del | Commit 1 | Commit 2 | Description (SOURCE OBSERVED, from diff) |
|---|---|---:|---:|:-:|:-:|---|
| `config/inference/base.yaml` | modified | 1 | 1 | yes | no | One line changed: `model_runner` value `SelfConditioning` replaced by `default`. |
| `rfdiffusion/diffusion.py` | modified | 13 | 6 | yes | no | Edits within existing diffusion code (autograd-related lines changed; 13 added, 6 removed). |
| `rfdiffusion/inference/model_runners.py` | modified | 37 | 8 | yes | no | 37 lines added, 8 removed in existing model-runner code. |
| `rfdiffusion/inference/utils.py` | modified | 67 | 56 | yes | no | 67 added, 56 removed in existing inference utilities. |
| `rfdiffusion/kinematics.py` | modified | 33 | 38 | yes | no | 33 added, 38 removed in existing kinematics code. |
| `rfdiffusion/util.py` | modified | 71 | 28 | yes | no | 71 added, 28 removed in existing utility functions. |
| `rfdiffusion/util_module.py` | modified | 1 | 1 | yes | no | One line replaced. |
| `rfdiffusion_erasure_teacher_student.py` | added | 691 | 0 | yes (679 add) | yes (27 add, 15 del) | New Python file at repo root; created in commit 1 with 679 lines, then modified in commit 2. |
| **Total (8 files)** | | **914** | **138** | | | |

SOURCE OBSERVED: Per-file additions/deletions in A sum to 914 / 138. Commit 1 (902/138) plus commit 2 (27/15) = 929/153 gross; the difference from the net 914/138 is because commit 2 rewrote 15 lines that commit 1 had added (679+27-15 = 691). INFERENCE: this arithmetic explains why the new file is 679 lines in commit 1 but 691 in the net diff; no other file differs between per-commit and net views (each of the other 7 files was touched by commit 1 only, with identical counts).
SOURCE OBSERVED: More detailed per-file semantics (what the code does) are deliberately not recorded here; they belong to SR-02. Descriptions above are limited to what diff line counts and the one-line config change show.

## 4. Per-commit rows
| SHA | Author date (UTC) | Parent | Message (verbatim) | Files touched | Add / Del / Net |
|---|---|---|---|---|---|
| `12d5426de27bc6411126262cf3f29bac3a0ce0c1` | 2025-10-21T08:52:26Z | `e22092420281c644b928e64d490044dfca4f9175` | "Add concept erasure training with fixes to rfdiffusion to allow for changes. Concept erases allow for gradient flow, but gradient is high and needs to be looked at" | 8 (all files in section 3) | 902 / 138 / +764 (API `stats.total` 1040) |
| `5cbd18a39c4607d65bdbf6457be3f79b27a6c3c1` | 2025-10-23T07:15:57Z | `12d5426de27bc6411126262cf3f29bac3a0ce0c1` | "additions" | 1 (`rfdiffusion_erasure_teacher_student.py`, modified) | 27 / 15 / +12 (API `stats.total` 42) |

SOURCE OBSERVED: Committer dates equal the author dates for both commits. Commit 1's parent is the merge base; commit 2's parent is commit 1 (linear history, `total_commits: 2`). The compare `commits` array lists exactly these two SHAs in that order.
SOURCE OBSERVED: Net across both commits: 764 + 12 = 776 = 914 - 138, consistent with section 3.

## 5. Tests, benchmarks, evaluation harnesses, weights
Method: listed every `diff --git` header in the 1342-line diff (exactly 8, matching section 3) and grepped the diff for `test`, `benchmark`, `.pt`, `.pth`, `.ckpt`, `safetensors`.
- SOURCE OBSERVED: No changed path is a test file, benchmark, or evaluation-harness path; none is under a `tests/` directory. The only added file is `rfdiffusion_erasure_teacher_student.py`.
- SOURCE OBSERVED: No binary or weight file was added; all 8 entries are text diffs (`.py`, `.yaml`) and there are no binary-patch markers. No `.pt/.pth/.ckpt/.safetensors` path appears in the file list.
- SOURCE OBSERVED: The only grep hits are string literals inside the added script: `ckpt_override_path` config assignments (lines 710, 736 of the diff), checkpoint save paths `checkpoint_step_{step}.pt` and `checkpoint_final.pt` with a `torch.save(...)` call, and a hardcoded input path `"models/Base_ckpt.pt"` (diff line 1237). These are references to files the script would read or write at runtime, not files in the diff.
- INFERENCE: The fork-only diff adds no tests, benchmarks, evaluation harnesses, or model weights. This confirms the existing FORK_AUDIT.md claim from the diff itself.
- UNKNOWN: whether the repository contains such material outside the fork-only diff (not in scope; it would be unchanged from upstream). Whether the script's loss/plot output counts as an "evaluation" is a SR-02 question; this document makes no claim about it.
- Out of scope and unasserted: any claim about safety efficacy or capability reduction.

## 6. Reconciliation with docs/SOURCE_SNAPSHOT.json
| Field | Snapshot | Live | Match |
|---|---|---|---|
| audit_date | 2026-11-09 | 2026-11-09 | yes |
| merge_base | e22092420281c644b928e64d490044dfca4f9175 | same (A `merge_base_commit.sha`) | yes |
| upstream_head_at_comparison | 86507b6538f51fce57b5a72477165f03999ed7ae | same (E) | yes |
| fork_commits[0] | 12d5426de27b... | same (A, B) | yes |
| fork_commits[1] | 5cbd18a39c46... | same (A, C) | yes |
| ahead_by | 2 | 2 (A); 2 appears as `behind_by` in D | yes |
| behind_by | 36 | 0 in A; 36 in D as `ahead_by` | yes, **only as the D figure** (see section 2); a reader taking it as a field of A would find 0 |
| changed_files count | 8 | 8 | yes |
| config/inference/base.yaml | +1 / -1 | +1 / -1 | yes |
| rfdiffusion/diffusion.py | +13 / -6 | +13 / -6 | yes |
| rfdiffusion/inference/model_runners.py | +37 / -8 | +37 / -8 | yes |
| rfdiffusion/inference/utils.py | +67 / -56 | +67 / -56 | yes |
| rfdiffusion/kinematics.py | +33 / -38 | +33 / -38 | yes |
| rfdiffusion/util.py | +71 / -28 | +71 / -28 | yes |
| rfdiffusion/util_module.py | +1 / -1 | +1 / -1 | yes |
| rfdiffusion_erasure_teacher_student.py | +691 / -0 | +691 / -0 | yes |
| evidence_url | compare API URL | same URL, HTTP 200 | yes |

SOURCE OBSERVED: No numeric or SHA mismatch. One labeling caveat: SOURCE_SNAPSHOT.json's `behind_by: 36` sits next to `ahead_by: 2` as if from one comparison; they come from different comparisons relative to the merge-base compare (section 2). Recommend (not performed; this task owns only this file) renaming it, for example `behind_upstream_main_by`, or adding a note. FORK_AUDIT.md's phrasing "fork 2 ahead / 36 behind upstream main" is accurate as written.
**Orchestrator follow-up (applied 2026-11-09, after this audit was written):** the recommended relabel was performed. `docs/SOURCE_SNAPSHOT.json` no longer carries a bare `behind_by`; it now records `behind_by_vs_merge_base: 0`, `behind_by_vs_upstream_main: 36` and a `behind_by_field_note` explaining the two comparisons. References to `behind_by: 36` above describe the snapshot as it stood when SR-01 ran and are retained for the audit trail.

SOURCE OBSERVED: FORK_AUDIT.md file table matches the live add/delete counts for all 8 files. Its classifications and observations beyond counts are interpretation and were not evaluated in SR-01.

## 7. Source URLs
- https://github.com/RosettaCommons/RFdiffusion/compare/e22092420281c644b928e64d490044dfca4f9175...audited-fork:main
- https://github.com/audited-fork/safeRFdiffusion/commit/12d5426de27bc6411126262cf3f29bac3a0ce0c1
- https://github.com/audited-fork/safeRFdiffusion/commit/5cbd18a39c4607d65bdbf6457be3f79b27a6c3c1
- https://github.com/RosettaCommons/RFdiffusion/commit/86507b6538f51fce57b5a72477165f03999ed7ae

## 8. Remaining uncertainty
- UNKNOWN: Unauthenticated API responses were used; rate limits or later force-pushes of the fork could change results. The commit SHAs pin the content.
- UNKNOWN: Whether `audited-fork:main` will remain at `5cbd18a`; the compare used the branch name `main`, and the head was confirmed as `5cbd18a` only through the commit list (compare `permalink_url` ends at `audited-fork:5cbd18a`).
- UNKNOWN: The 36-commit upstream gap is not itemized here; it is irrelevant to the fork-only diff.

## 9. Reproduce this audit
Needs only `curl`, `python3`, `shasum`. Writes to a fresh directory.
```sh
set -e
D=$(mktemp -d) && cd "$D"
B=https://api.github.com/repos
MB=e22092420281c644b928e64d490044dfca4f9175
J='Accept: application/vnd.github+json'
curl -m 30 -s -o compare.json -w "A %{http_code}\n" -H "$J" "$B/RosettaCommons/RFdiffusion/compare/$MB...audited-fork:main"
curl -m 30 -s -o diff.txt     -w "A-diff %{http_code}\n" -H "Accept: application/vnd.github.diff" "$B/RosettaCommons/RFdiffusion/compare/$MB...audited-fork:main"
curl -m 30 -s -o c1.json      -w "B %{http_code}\n" -H "$J" "$B/audited-fork/safeRFdiffusion/commits/12d5426de27bc6411126262cf3f29bac3a0ce0c1"
curl -m 30 -s -o c2.json      -w "C %{http_code}\n" -H "$J" "$B/audited-fork/safeRFdiffusion/commits/5cbd18a39c4607d65bdbf6457be3f79b27a6c3c1"
curl -m 30 -s -o rev.json     -w "D %{http_code}\n" -H "$J" "$B/RosettaCommons/RFdiffusion/compare/audited-fork:main...main"
curl -m 30 -s -o head.json    -w "E %{http_code}\n" -H "$J" "$B/RosettaCommons/RFdiffusion/commits/main"
shasum -a 256 *.json diff.txt; wc -l diff.txt
python3 -I - <<'PY'
import json
c=json.load(open('compare.json'))
print(c['status'],'ahead',c['ahead_by'],'behind',c['behind_by'],c['merge_base_commit']['sha'])
for f in c['files']: print(f['filename'],f['status'],f['additions'],f['deletions'])
for k in ('c1','c2'):
    d=json.load(open(k+'.json')); print(d['sha'],d['commit']['author']['date'],repr(d['commit']['message']),d['stats'])
    for f in d['files']: print('  ',f['filename'],f['status'],f['additions'],f['deletions'])
r=json.load(open('rev.json')); print('fork...upstream:',r['status'],'ahead',r['ahead_by'],'behind',r['behind_by'])
print('upstream head',json.load(open('head.json'))['sha'])
PY
grep -c '^diff --git' diff.txt
grep -niE 'test|benchmark|\.pt\b|\.pth|\.ckpt|safetensors' diff.txt
```
Expected on 2026-11-09: A ahead 2 / behind 0, 8 files; D ahead 36 / behind 2; 8 `diff --git` headers; diff sha256 `fe3753f3...9e86`. The D numbers and upstream head will drift as upstream advances; the A numbers and diff hash should not.
