# BSUIR CI

Flask app with GitLab CI/CD: test and build on feature branches, promote on merge, deploy to dev/prod on a self-hosted runner. Application logs are shipped to an ELK stack (Filebeat → Logstash → Elasticsearch → Kibana) on the same host.

| Environment | URL | Access |
|---|---|---|
| prod | https://bsuir-app.tail65829d.ts.net | Public (Tailscale Funnel) |
| dev | https://dev-bsuir-app.tail65829d.ts.net | Tailnet admins only (Tailscale Service) |
| Kibana | https://kibana-bsuir-app.tail65829d.ts.net | Tailnet admins only (Tailscale Service) |

## Diagrams

### Deployment

```mermaid
flowchart TB
    dev["Developer workstation<br/>git + glab"]

    subgraph gitlab["GitLab.com"]
        repo["Repository<br/>Tsuyakashi/bsuir-ci"]
        ci["GitLab CI/CD engine"]
        shared["SaaS shared runners<br/>test: python:3.12-slim<br/>build: docker:27 + dind<br/>promote: alpine + skopeo"]
        registry[("Container Registry<br/>registry.gitlab.com/tsuyakashi/bsuir-ci")]
        envs["Environments<br/>dev / prod / observability"]
    end

    github["GitHub<br/>push mirror"]
    funnel["Tailscale Funnel relay"]

    subgraph host["pve-rog (Proxmox VE)"]
        subgraph ct["CT 230 bsuir-ci-ct (Ubuntu 24.04, unprivileged LXC)<br/>tailnet: bsuir-app"]
            runner["gitlab-runner<br/>shell executor, user deploy<br/>tag: bsuir-ci-ct"]
            docker["Docker Engine"]
            devapp["bsuir-ci-dev-app-1<br/>localhost:8081 → 80"]
            prodapp["bsuir-ci-prod-app-1<br/>localhost:8080 → 80"]
            subgraph obs["compose project bsuir-observability"]
                filebeat["filebeat"]
                logstash["logstash"]
                es[("elasticsearch<br/>localhost:9200")]
                kibana["kibana<br/>localhost:5601"]
            end
            ts["tailscaled<br/>Serve / Funnel, TLS termination"]
            runner -->|docker compose| docker
            docker --> devapp
            docker --> prodapp
            docker --> obs
            devapp -.->|container logs| filebeat
            prodapp -.->|container logs| filebeat
            filebeat --> logstash --> es
            kibana --> es
        end
    end

    internet["Internet clients"]
    tailnet["Tailnet clients"]

    dev -->|git push| repo
    dev -->|git push| github
    repo -->|push mirror| github
    repo --> ci
    ci --> shared
    ci --> runner
    shared -->|push / retag| registry
    docker -->|pull| registry
    runner -.->|deployment status| envs

    internet -->|"HTTPS<br/>bsuir-app.tail65829d.ts.net"| funnel
    funnel --> ts
    tailnet -->|"HTTPS<br/>dev-bsuir-app / kibana-bsuir-app"| ts
    ts -->|"localhost:8080"| prodapp
    ts -->|"localhost:8081"| devapp
    ts -->|"localhost:5601"| kibana
```

### Sequence

```mermaid
sequenceDiagram
    autonumber
    actor dev as Developer
    participant gl as GitLab
    participant sr as Shared runner
    participant reg as Registry
    participant ct as bsuir-ci-ct runner
    participant app as Docker (dev / prod)

    Note over dev,app: Feature branch (GitHub Flow)
    dev->>gl: git push feat/*
    opt changes in python/
        gl->>sr: test (pytest)
        sr-->>gl: JUnit report
        gl->>sr: build
        sr->>sr: docker build python/
        sr->>reg: push :<sha>, :src-<tree>, :dev
    end
    gl->>ct: deploy-dev
    ct->>reg: pull :src-<tree>
    ct->>app: compose up -d --wait (bsuir-ci-dev)
    app-->>ct: healthy
    Note over dev: verify on https://dev-bsuir-app.tail65829d.ts.net

    Note over dev,app: Merge into main
    dev->>gl: merge MR
    gl->>sr: promote
    sr->>sr: TREE = rev-parse HEAD:python
    sr->>reg: inspect :src-<tree>
    alt image exists
        sr->>reg: copy → :prod, :merged-<sha>
        gl->>ct: deploy-prod
        ct->>reg: pull :merged-<sha>
        ct->>app: compose up -d --wait (bsuir-ci-prod)
        app-->>ct: healthy
        Note over dev: live on https://bsuir-app.tail65829d.ts.net
    else no image
        sr-->>gl: fail (main diverged, rebase branch)
    end
```

### Pipeline rules

```mermaid
flowchart TD
    push([push event]) --> branch{"ref is a branch?"}
    branch -- "no (tag)" --> skip([no pipeline])
    branch -- yes --> main{"branch == main?"}

    main -- yes --> promote[promote] --> prod[deploy-prod]
    main -- yes --> obsmain{"changes in observability/?"}
    obsmain -- yes --> obsdeploy[deploy-observability]

    main -- no --> py{"changes in python/?"}
    py -- yes --> test[test] --> build[build] --> devdeploy["deploy-dev<br/>image :src-TREE"]
    py -- no --> cfg{"changes in compose.yml<br/>or .gitlab-ci.yml?"}
    cfg -- yes --> devdeploy
    cfg -- no --> skip2([no app jobs])

    main -- no --> obsbranch{"changes in observability/?"}
    obsbranch -- yes --> obsmanual["deploy-observability<br/>(manual)"]
```

### Promote

```mermaid
flowchart TD
    start([merge commit on main]) --> tree["TREE = git rev-parse HEAD:python"]
    tree --> check{"registry has :src-TREE?"}
    check -- no --> fail(["fail: main diverged in python/,<br/>rebase the branch"])
    check -- yes --> prodtag["copy :src-TREE → :prod"]
    prodtag --> mergedtag["copy :src-TREE → :merged-SHA"]
    mergedtag --> deploy(["deploy-prod pulls :merged-SHA"])
```

### Log pipeline

```mermaid
flowchart LR
    apps["bsuir-ci-dev / bsuir-ci-prod<br/>gunicorn JSON access log<br/>+ app log"] -->|"docker json-file logs"| fb["filebeat<br/>add_docker_metadata<br/>drop non-app containers"]
    fb -->|"beats 5044"| ls["logstash<br/>env from compose project<br/>JSON → access.*, grok for the rest<br/>drop /health"]
    ls --> es[("elasticsearch<br/>bsuir-app-{env}-YYYY.MM.dd")]
    es --> kb["kibana<br/>dashboard imported from repo"]
```

### Network flows

```mermaid
flowchart LR
    subgraph internet["Internet"]
        glcore["gitlab.com"]
        glreg[("registry.gitlab.com")]
        elreg[("docker.elastic.co")]
        gh["github.com"]
        public["Internet clients"]
        relay["Tailscale Funnel relay"]
    end

    subgraph lan["LAN 192.168.100.0/24"]
        subgraph ct["bsuir-ci-ct (tailnet: bsuir-app)"]
            runner["gitlab-runner"]
            dockerd["dockerd"]
            tsd["tailscaled<br/>Serve / Funnel"]
            prod["prod<br/>localhost:8080"]
            devapp["dev<br/>localhost:8081"]
            kibana["kibana<br/>localhost:5601"]
        end
    end

    ws["Workstation"]
    tailnet["Tailnet clients"]

    ws -->|"SSH 22<br/>git push"| glcore
    ws -->|"SSH 22<br/>git push"| gh
    glcore -->|"HTTPS 443<br/>push mirror"| gh
    runner -->|"HTTPS 443<br/>long polling"| glcore
    dockerd -->|"HTTPS 443<br/>app image pull"| glreg
    dockerd -->|"HTTPS 443<br/>ELK image pull"| elreg

    public -->|"HTTPS 443<br/>bsuir-app.tail65829d.ts.net"| relay
    relay -->|"WireGuard"| tsd
    tailnet -->|"HTTPS 443 over WireGuard<br/>dev-bsuir-app / kibana-bsuir-app"| tsd
    tsd -->|"HTTP"| prod
    tsd -->|"HTTP"| devapp
    tsd -->|"HTTP"| kibana
```

## Pipeline

| Event | Jobs | Result |
|---|---|---|
| Push to feature branch (changes in `python/`) | `test` → `build` → `deploy-dev` | Tests passed, image built, deployed to dev |
| Push to feature branch (only `compose.yml` / `.gitlab-ci.yml`) | `deploy-dev` | Existing image (`src-<tree>`) redeployed to dev with new config |
| Push to feature branch (changes in `observability/`) | `deploy-observability` (manual) | Stack can be redeployed from the branch on demand |
| Push to feature branch (docs only) | — | Nothing |
| MR merged into `main` | `promote` → `deploy-prod` | Image retagged, deployed to prod |
| MR merged into `main` (changes in `observability/`) | `deploy-observability` | Stack redeployed, index template and Kibana objects applied |
| Direct push to `main` | — | Blocked by branch protection |

### Image tags

| Tag | Set by | Meaning |
|---|---|---|
| `<commit sha>` | `build` | Commit the image was built from (traceability) |
| `src-<tree>` | `build` | Hash of `python/` tree — content-based key used by `deploy-dev` and `promote` |
| `dev` | `build` | Latest feature branch build |
| `prod` | `promote` | Current production image |
| `merged-<sha>` | `promote` | Image released by this merge commit (immutable, deployed to prod, used for rollback) |

`promote` finds the image by `python/` tree hash, so prod gets exactly the app content built on the feature branch, regardless of docs commits or merge method. If `main` diverged in `python/` while the MR was open, `promote` fails — rebase the branch.

### Tests

`test` runs `pytest` in `python:3.12-slim` on feature branches with changes in `python/`, before `build`. A failed test stops the pipeline: no image, no dev deploy. Results are published as a JUnit report and shown in the MR widget.

Run locally:
```
cd python
docker run --rm -it -v "$PWD":/app -w /app python:3.12-slim sh -c "pip install -r requirements.txt pytest && python -m pytest -v"
```

### Deploy

Each environment is a separate compose project (`bsuir-ci-dev`, `bsuir-ci-prod`) from the same `compose.yml`, parametrized by `IMAGE_TAG` and `PORT`. Ports are published on `127.0.0.1` only — the apps are reachable solely through Tailscale.

`docker compose up --wait` blocks until the container healthcheck (`GET /health` inside the container) passes, so a container that fails to start fails the deploy job. Unused images are pruned after each deploy.

### Rollback

Deployments → Environments → `prod` → Re-deploy an older deployment. Or manually:
```
skopeo copy --all docker://registry.gitlab.com/tsuyakashi/bsuir-ci:merged-<old_sha> docker://registry.gitlab.com/tsuyakashi/bsuir-ci:prod
```

## Application

Flask app served by gunicorn (`python/gunicorn.conf.py`, 2 workers, non-root user). Endpoints: `/` (timestamp and 1-minute load average from `/proc/loadavg`) and `/health`.

Behind Tailscale Serve/Funnel the client IP arrives in `X-Forwarded-For`. The app trusts exactly one proxy hop (`ProxyFix(x_for=1)`), which is safe because ports are bound to localhost and only `tailscaled` can reach them.

The access log is written by gunicorn as one JSON object per line:
```
{"time":"[03/Nov/2026:14:05:58 +0000]","remote":"100.75.99.19","method":"GET","path":"/","query":"","status":200,"bytes":297,"duration_ms":3,"user_agent":"curl/8.18.0"}
```
`remote` is the real client (from `X-Forwarded-For`), `-` for requests without a proxy (docker healthcheck, local curl).

## Observability

`observability/compose.yml`, compose project `bsuir-observability`, all images pinned to `9.5.6`:

| Service | Role | Limits |
|---|---|---|
| `filebeat` | Reads `/var/lib/docker/containers/*/*.log`, enriches with docker metadata, keeps only `bsuir-ci-dev` / `bsuir-ci-prod` containers | 256 MB |
| `logstash` | Sets `env` (`dev`/`prod`) from the compose project label, parses JSON access log into `access.*`, grok for other lines, drops `/health` | 768 MB, heap 256 MB |
| `elasticsearch` | Single node, daily indices `bsuir-app-{env}-YYYY.MM.dd`, `localhost:9200` | 2 GB, heap 1 GB |
| `kibana` | UI on `localhost:5601`, exposed via Tailscale Service `svc:kibana-bsuir-app` | 1.2 GB |

`deploy-observability` brings the stack up, then:
- applies index template `bsuir-app` with `number_of_replicas: 0` (single node — otherwise indices stay yellow) and updates existing indices;
- imports `observability/kibana/dashboards.ndjson` (data view `bsuir-app` + dashboard) with `overwrite=true`.

Dashboard panels: requests over time by environment, unique visitors (metric), unique visitors over time. A visitor is a unique `access.remote` — an IP address, so users behind one NAT count as one, one user with several networks counts as several.

To change the dashboard: edit it in Kibana, then export back into the repo:
```
ssh root@bsuir-app "curl -s -X POST localhost:5601/api/saved_objects/_export -H 'kbn-xsrf: true' -H 'Content-Type: application/json' -d '{\"type\":[\"dashboard\"],\"includeReferencesDeep\":true}'" > observability/kibana/dashboards.ndjson
```

Elasticsearch security is disabled on purpose: every port is bound to `127.0.0.1` and Kibana is reachable only by tailnet admins, so access is restricted at the network level.

## Infrastructure

Single LXC `bsuir-ci-ct` (CT 230 on `pve-rog`, tailnet node `bsuir-app`, `tag:bsuir`): GitLab runner (shell executor, user `deploy`), Docker, dev and prod as separate compose projects, plus the observability stack.

Prod is published to the internet via Tailscale Funnel on the node name. Dev and Kibana are tailnet-only Tailscale Services (`svc:dev-bsuir-app`, `svc:kibana-bsuir-app`) with their own names. Funnel does not support Services, hence the asymmetric setup.

## Run locally

```
docker build -t bsuir-app python/
docker run --rm -p 8080:80 bsuir-app
curl http://localhost:8080/health
```

## Cheatsheet

### Protect the main branch
```
glab api -X DELETE projects/:id/protected_branches/main
glab api -X POST projects/:id/protected_branches -f name=main -f push_access_level=0 -f merge_access_level=40
```

### Create LXC
```
pct create 230 local:vztmpl/ubuntu-24.04-standard_24.04-2_amd64.tar.zst \
  --hostname bsuir-ci-ct \
  --cores 3 --memory 5120 --swap 1024 \
  --rootfs local-lvm:24 \
  --net0 name=eth0,bridge=vmbr0,ip=dhcp \
  --nameserver 1.1.1.1 \
  --dev0 /dev/net/tun \
  --unprivileged 1 \
  --features nesting=1,keyctl=1 \
  --ssh-public-keys ~/.ssh/authorized_keys \
  --onboot 1 \
  --start 1
```
- `--nameserver` — otherwise the CT inherits host MagicDNS (`100.100.100.100`), unreachable before Tailscale is up
- `--dev0 /dev/net/tun` — required by Tailscale
- `nesting=1` — required by Docker
- 3 cores / 5 GB / 24 GB — sized for the apps plus the ELK stack
- Elasticsearch needs `vm.max_map_count >= 262144` on the Proxmox host (not settable from an unprivileged CT); current Proxmox defaults already exceed it, check with `sysctl vm.max_map_count`

### Tailscale

Order matters: ACL → tagged node → service definitions → serve/funnel.

1. ACL (tailnet policy file, managed separately). Relevant parts:
```
"tagOwners": {
    "tag:bsuir": ["autogroup:admin"],
},
"grants": [
    {
        "src": ["autogroup:admin"],
        "dst": ["svc:dev-bsuir-app"],
        "ip":  ["tcp:443"],
    },
    {
        "src": ["autogroup:admin"],
        "dst": ["svc:kibana-bsuir-app"],
        "ip":  ["tcp:443"],
    },
],
"autoApprovers": {
    "services": {
        "svc:dev-bsuir-app":    ["tag:bsuir"],
        "svc:kibana-bsuir-app": ["tag:bsuir"],
    },
},
"nodeAttrs": [
    // tagged nodes are not autogroup:member, so funnel is granted separately
    {
        "target": ["tag:bsuir"],
        "attr":   ["funnel"],
    },
],
```

2. Join the tailnet with the tag (in CT):
```
curl -fsSL https://tailscale.com/install.sh | sh
tailscale up --hostname=bsuir-app --ssh --advertise-tags=tag:bsuir
```
For an already joined, user-owned node, changing tags requires re-authentication (`tailscale up` prints a login URL).

3. Define the services in the admin console: Services → Add service → `dev-bsuir-app` and `kibana-bsuir-app`, endpoint `tcp:443` for both.

4. Expose (in CT):
```
# prod: public via Funnel on the node name (bsuir-app.<tailnet>)
tailscale funnel --bg 8080

# dev: tailnet-only Tailscale Service (dev-bsuir-app.<tailnet>)
tailscale serve --service=svc:dev-bsuir-app --https=443 127.0.0.1:8081

# kibana: tailnet-only Tailscale Service (kibana-bsuir-app.<tailnet>)
tailscale serve --service=svc:kibana-bsuir-app --https=443 127.0.0.1:5601
```

If the host advertised a service before it was defined in the console, the service stays at 0 hosts. Re-advertise:
```
systemctl restart tailscaled
tailscale serve drain svc:<name> && sleep 3 && tailscale serve advertise svc:<name>
```

### Docker (in CT)
```
curl -fsSL https://get.docker.com | sh
docker run --rm hello-world
```

### Deploy user and runner (in CT, as root)
```
useradd -m -s /bin/bash deploy
usermod -aG docker deploy
rm -f /home/deploy/.bash_logout   # breaks shell executor on Ubuntu

curl -fsSL https://packages.gitlab.com/install/repositories/runner/gitlab-runner/script.deb.sh | bash
apt install -y gitlab-runner
gitlab-runner uninstall
gitlab-runner install --user deploy --working-directory /home/deploy
systemctl restart gitlab-runner
```

### Register runner
On the workstation:
```
glab api -X POST user/runners \
  -f runner_type=project_type \
  -F project_id=$(glab api projects/:id | jq .id) \
  -F 'tag_list=["bsuir-ci-ct"]' \
  -F run_untagged=false \
  -f description=bsuir-ci-ct | jq -r .token
```
In CT:
```
gitlab-runner register --non-interactive --url https://gitlab.com --token glrt-... --executor shell
gitlab-runner verify
```

### Useful checks
```
# observability stack and indices
ssh root@bsuir-app "docker compose -p bsuir-observability ps; curl -s 'localhost:9200/_cat/indices/bsuir-app-*?v'"

# app access log
ssh root@bsuir-app "docker logs bsuir-ci-prod-app-1 2>&1 | tail"

# tailscale serve/funnel config
ssh root@bsuir-app "tailscale serve status"
```
