# Milestone 11 portfolio checklist

The package reuses measured reference evidence and adds a local evidence collector. It does
not claim that verified AWS deployment already exists.

| Deliverable | Evidence / remaining action |
|---|---|
| README | Overview, quickstart, evidence links and limitations prepared |
| Architecture | Lifecycle, local and AWS diagrams; trade-offs prepared |
| Model card | Actual reference provenance, metrics and plots retained |
| Responsible AI | Intended use, subgroup limitations, harms and residual risks prepared |
| Monitoring | Reference simulations and reviewed 22 September local capture linked; no observed labels in current capture |
| Benchmarking | 200/200 local requests, zero errors, P95 227.17 ms, 20.49 requests/s; reference measurements retained separately |
| Focused checks | Owner reported 7 collector tests passed, Ruff passed, two files formatted, and a clean whitespace check |
| Screenshots | Capture/review the three local/CI views in the demo guide |
| AWS evidence | CloudFront verification declined; Milestone 10 incomplete; current resource inventory and cleanup unverified |

Milestone 11 is complete after current evidence is reviewed, genuine screenshots
are added, and the final commit passes CI. A local portfolio can be complete while
Milestone 10 remains explicitly blocked; do not represent the partial stack as deployed.

The three supplied aggregates are reviewed and included under `docs/verification/portfolio/`.
Keep their original 22 September capture timestamp and dirty-checkout provenance. Do not
edit the JSON to make it appear tied to the later documentation commit. The latest update
only links that evidence, documents the AWS decision and corrects the collector's final message;
there is no need to rerun the benchmark for these changes.

## Validate only the changed code

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests/unit -p test_portfolio_evidence.py
if ($LASTEXITCODE -ne 0) { throw 'Portfolio tests failed' }
.\.venv\Scripts\ruff.exe check scripts/collect_portfolio_evidence.py tests/unit/test_portfolio_evidence.py
if ($LASTEXITCODE -ne 0) { throw 'Lint failed' }
.\.venv\Scripts\ruff.exe format --check scripts/collect_portfolio_evidence.py tests/unit/test_portfolio_evidence.py
if ($LASTEXITCODE -ne 0) { throw 'Formatting failed' }
git diff --check
```

Application code and dependencies are unchanged. CI runs the broader existing suite; there
is no need for another training or upgrade cycle for this documentation/collector change.

## Stage and refresh the manifest

Review `git status --short`, then stage these intended files. Separately stage reviewed
screenshots if present. The explicit list below includes only the three reviewed evidence
files. The separately modified `storage.tf` is not included: inspect its diff and validate
any intended change before adding it to a commit.

```powershell
git add -- README.md docs/architecture.md docs/model_card.md docs/responsible_ai.md docs/milestone-10-report.md docs/benchmark-report.md docs/monitoring-report.md docs/demo-guide.md docs/milestone-11-report.md scripts/collect_portfolio_evidence.py tests/unit/test_portfolio_evidence.py
git add -- docs/verification/portfolio/evidence.json docs/verification/portfolio/benchmark.md docs/verification/portfolio/monitoring.md
```

Refresh only staged changes, using actual Git-index bytes so line-ending normalization is
respected. Untouched manifest entries are retained; this is not a re-verification of them.
The command also handles a separately staged RDS retention fix. Review staged names for
accidental private files before committing.

```powershell
@'
import hashlib, json, pathlib, subprocess
p = pathlib.Path('RELEASE-SHA256.json')
d = json.loads(p.read_text(encoding='utf-8'))
def git(*args):
    return subprocess.check_output(['git', *args])
for raw in git('diff', '--cached', '--name-only', '--diff-filter=D', '--no-renames', '-z').split(b'\0'):
    if raw:
        d.pop(raw.decode('utf-8'), None)
for raw in git('diff', '--cached', '--name-only', '--diff-filter=ACMRT', '--no-renames', '-z').split(b'\0'):
    if raw:
        name = raw.decode('utf-8')
        if name != p.name:
            d[name] = hashlib.sha256(git('show', ':' + name)).hexdigest()
p.write_text(json.dumps(d, indent=2, sort_keys=True) + '\n', encoding='utf-8', newline='\n')
print('Updated staged-file hashes; untouched entries retained.')
'@ | .\.venv\Scripts\python.exe -
if ($LASTEXITCODE -ne 0) { throw 'Manifest update failed' }
git add -- RELEASE-SHA256.json
git diff --cached --check
if ($LASTEXITCODE -ne 0) { throw 'Staged whitespace check failed' }
git diff --cached --stat
git diff --cached --name-only
git status --short
```

After reviewing the staged list:

```powershell
git commit -m "Add portfolio documentation and reproducible local evidence"
if ($LASTEXITCODE -ne 0) { throw 'Commit failed' }
git push origin main
if ($LASTEXITCODE -ne 0) { throw 'Push failed' }
gh run list --workflow ci.yml --branch main --limit 3
git status --short
```

Watch the actual new run with `gh run watch RUN_ID --exit-status`, replacing `RUN_ID` with
its ID. Investigate any separate manifest mismatch rather than blindly updating all hashes.
Historical failed runs remain historical evidence; the new commit must pass.
