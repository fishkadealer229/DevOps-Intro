# Lab 3 submission


## Task 1

### 1. Path
I chose GitHub Actions, because I think GitHub is a more convenient tool, and simply more familiar for me

### 2. Green CI
Green CI run:
https://github.com/fishkadealer229/DevOps-Intro/actions/runs/35296299380

### 3. Failed CI run
Failed run:
![img.png](img.png)
![img_1.png](img_1.png)

Fix commit:
https://github.com/fishkadealer229/DevOps-Intro/commit/a50a3e19696e11d73684a3d761b4605b1a185407

### 4. Branch protection
Screenshot of branch protection:
![img_2.png](img_2.png)
![img_3.png](img_3.png)

### 5. Questions
- ### Why pin ubuntu-24.04 instead of ubuntu-latest?
    Because ubuntu-latest can change on other Ubuntu version over time which may cause the previously running pipeline to stop working or start behaving differently

- ### hWy split vet + test + lint?
    Because three independent jobs allow you to see separately which check failed

- ### What attack does SHA pinning prevent?
    SHA pinning prevents the action the workflow references from becoming unavailable. For example, in 2025 the tj-actions/changed-files GitHub Action was compromised: attackers rewrote its tags to a malicious version, which leaked secrets from thousands of public CI runs

- ### What is permissions:?
    permissions: defines which GITHUB_TOKEN rights workflow will get

- ### GitLab: stage vs job
    **_stage_** is pipeline stage which defines group order
    **_job_** is task inside stage which execute commands
    **_stages:_** define order of stages
    **_dependencies:_** manages the transfer of results between jobs


## Task 2

### 1. Measures
- Baseline
  - vet  = 22 s
  - test = 27 s
  - lint = 22 s
- With cache:
  - vet  = 12 s
  - test = 26 s
  - lint = 7 s
- With cache + matrix:
  - vet  = 12 s
  - test = 30 s
  - lint = 14 s

| Scenario | Wall-clock |
|----------|------------|
| Baseline (no cache, single Go version, no path filter) | 71 s       |
| With cache | 45 s       |
| With cache + matrix | 56 s       |

### 2. Optimizations
- **Go module and build cache:** The CI pipeline uses module caching and Go build data (actions/setup-go) to quickly retrieve them when needed again. This reduces the number of dependency reloads and compilation efforts.
- **Go version matrix:** The vet and test jobs run in parallel against Go 1.23 and Go 1.24. This helps detect problems that only appear according Go version.
- **fail-fast: false:** If one matrix combination fails, the remaining combinations continue running. This allows the CI results for both Go versions to be seen instead of cancelling the other jobs after the first failure.
- **Path filter:** The workflow is configured to run when files under app/** or the CI configuration .github/workflows/ci.yml change. This is necessary to avoid triggering the pipeline when changing documentation and other parts of the project that are not subject to testing.

### 3. Questions

#### f) Why cache `go.sum`-keyed inputs and not build outputs?

Dependency inputs are deterministic when they are pinned by the dependency files. A cache keyed by the dependency definition can therefore be reused when the same dependencies are required.

Build outputs are less suitable as cache keys because they can depend on the Go version, operating system, source code, compiler, and other details. 

#### g) What does `fail-fast: false` change in a matrix run, and when do you want `fail-fast: true`?

With `fail-fast: false`, a failed matrix cell does not cancel the other matrix jobs. This is useful for CI because it allows all Go-version combinations to finish

`fail-fast: true` is useful when the remaining matrix jobs are no longer useful after one failure for saving CI resources.

#### h) What's the risk of an attacker writing a cache from a malicious PR that protected branches later read?

A malicious PR could potentially place attacker-controlled data in a cache. If a protected branch later restored and trusted that data, the cached content could influence the build or execution of the protected workflow.

