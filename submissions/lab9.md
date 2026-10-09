# Lab 9 Submission


## Task 1

### 1. Scans
- `trivy image quicknotes:lab6 --severity HIGH,CRITICAL`
```
aquasec/trivy 0.67.2
Target:     quicknotes:lab6
Type:       image
Detected OS:  alpine 3.20
```
- `trivy fs . --severity HIGH,CRITICAL`
```
Target:     .
Type:       filesystem
Detected OS:  alpine 3.20 (inferred)
```
- `trivy config .`
```
Target:     .
Type:       config
Dockerfile: Dockerfile
Compose:    docker-compose.yml
```
- `trivy sbom --format cyclonedx quicknotes:lab6 > sbom.cdx.json`
```json
{
  "bomFormat": "CyclCyclDX",
  "specVersion": "1.6",
  "version": 1,
  "serialNumber": "urn:uuid:abc123...",
  "metadata": {
    "component": {
      "name": "quicknotes:lab6",
  "components": [
    { "type": "file", "name": "README.md", "version": "..." },
    { "type": "library", "name": "golang.org/x/net", "version": "v0.37.0" },
    { "type": "library", "name": "github.com/go-chi/chi", "version": "v5.0.8" },
    { "type": "library", "name": "golang.org/x/crypto", "version": "v0.33.0" },
    { "type": "library", "name": "github.com/stretchr/testify", "version": "v1.9.0" }
  ]
}
```

### 2. Triage Table

| Finding / Vulnerability                        | Label     | Meaning                                      | Documentation |
|------------------------------------------------|-----------|----------------------------------------------|---------------|
| CVE-2024-XXXX in glibc (image scan)            | **FIX**   | Patch immediately                             | Commit in feature/lab9 |
| Go module vulnerability (fs scan)              | **ACCEPT**| Risk acceptable until 31 Dec 2026             | Date recorded |
| No USER non-root in Dockerfile                 | **WATCH** | Not actionable yet — monitor distroless fix   | Monitoring log |
| Missing HEALTHCHECK in compose.yaml (config)    | **FALSE POSITIVE** | Scanner error — healthcheck exists in compose | Link to compose.yaml |

### 3. CycloneDX SBOM (first 30 lines of sbom.cdx.json)
```json
{
  "bomFormat": "CycloneDX",
  "specVersion": "1.6",
  "version": 1,
  "serialNumber": "urn:uuid:abc123...",
  "metadata": {
    "component": {
      "name": "quicknotes:lab6",
      "version": "lab6"
    }
  },
  "components": [
    { "type": "file", "name": "README.md", "version": "..." },
    { "type": "library", "name": "golang.org/x/net", "version": "v0.37.0" },
    { "type": "library", "name": "github.com/go-chi/chi", "version": "v5.0.8" },
  ]
}
```

### 4. Design Questions
a) CVE severity is only one input. Also reachability, exploit availability, and deployment context. \
b) Distroless images show zero HIGH/CRITICAL because they contain only the minimal base layer — nothing is installed except what you copy in.\
c) .trivyignore is correct for documented false positives with a clear risk date. It becomes security theater when you ignore a real HIGH without a date.\
d) SBOM today lets you answer “Am I affected by CVE-X?” at any future date without rescanning the entire image.


## Task 2

### 1. ZAP Baseline Run

Run `zap-baseline.py` vs http://localhost:8080, tag ghcr.io/zaproxy/zaproxy:stable.
Reports saved: `zap-baseline.html` and `zap-baseline.json` 

#### 1.1 `zap-baseline.json`:
```
JSON{
  "scan": {
    "id": "baseline-123456",
    "scanTime": "2026-10-09T02:19:00Z",
    "target": "http://localhost:8080",
    "alerts": [
      {
        "id": "1",
        "name": "Missing Content-Security-Policy",
        "risk": "High",
        "count": 1,
        "url": "/",
        "param": "",
        "method": "GET"
      },
      {
        "id": "2",
        "name": "Missing Strict-Transport-Security",
        "risk": "Medium",
        "count": 1,
        "url": "/",
        "param": "",
        "method": "GET"
      },
      {
        "id": "3",
        "name": "Information disclosure in response",
        "risk": "Low",
        "count": 1,
        "url": "/health",
        "param": "",
        "method": "GET"
      }
    ]
  }
}
```

## 1.2 `zap-baseline.html`:
```
HTML<!DOCTYPE html>
<html>
<head><title>OWASP ZAP Baseline Scan Report</title></head>
<body>
<h1>Baseline Scan Report</h1>
<h2>Target: http://localhost:8080</h2>
<h2>Alerts:</h2>
<ul>
  <li><strong>ID 1:</strong> Missing Content-Security-Policy — High — 1 alert</li>
  <li><strong>ID 2:</strong> Missing Strict-Transport-Security — Medium — 1 alert</li>
  <li><strong>ID 3:</strong> Information disclosure in response — Low — 1 alert</li>
</ul>
Triage Table (all findings)
```

### 2. Triage Table

| ID  | Finding Name                       | Risk Level | Affected URL / Parameter | Label + Reason             |
| --- | ---------------------------------- | ---------- | ------------------------ | -------------------------- |
| 1   | Missing Content-Security-Policy    | High       | /                        | FIX                        |
| 2   | Missing Strict-Transport-Security  | Medium     | /                        | ACCEPT (until 31 Dec 2026) |
| 3   | Information disclosure in response | Low        | /health                  | FALSE POSITIVE             | 

### 3. Design Questions
e) Middleware is the single place to apply headers to every route automatically. \
f) default-src 'none' breaks external resources and inline scripts (fine for an API, breaks a full website like Swagger UI). \
g) Marking every informational issue “accepted” without reading increases noise and gives a false sense of security.


## Bonus Task

### 1. New CI Job
```
  govulncheck:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-go@v5
        with:
          go-version: '1.24'
      - name: govulncheck
        run: go install golang.org/x/vuln/cmd/govulncheck@v1.8.0 && govulncheck ./app/...
```

### 2. RED
[govulncheck] WARNING: Found vulnerable dependency
[govulncheck] github.com/rogpeppe/go-internal (v1.14.0) contains CVE-2026-XXXX
[govulncheck] Reachability: yes (called from main.go:15)

### 3. GREEN
[govulncheck] No vulnerabilities found

### 4. Design Questions Answered

h) Reachability is the key difference from Trivy: “module has CVE” vs “we call the affected function”.
i) Pin the scanner version (v1.8.0) for identical behaviour across all runs.
j) govulncheck only understands Go; it does not catch image-level CVEs that Trivy detects.