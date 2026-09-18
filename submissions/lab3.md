# Lab 3 submission

## Task 1

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

