# BSUIR CI

Flask app with GitLab CI/CD: build on feature branches, promote on merge, deploy to dev/prod on a self-hosted runner.

## Diagrams

### Deployment

```mermaid
flowchart TB
    dev["Developer workstation<br/>git + glab"]

    subgraph gitlab["GitLab.com"]
        repo["Repository<br/>Tsuyakashi/bsuir-ci"]
        ci["GitLab CI/CD engine"]
        shared["SaaS shared runners<br/>build: docker:27 + dind<br/>promote: alpine + skopeo"]
        registry[("Container Registry<br/>registry.gitlab.com/tsuyakashi/bsuir-ci")]
        envs["Environments<br/>dev / prod"]
    end

    github["GitHub<br/>push mirror"]
    funnel["Tailscale Funnel relay"]

    subgraph host["pve-rog (Proxmox VE)"]
        subgraph ct["CT 230 bsuir-ci-ct (Ubuntu 24.04, unprivileged LXC)<br/>tailnet: bsuir-app"]
            runner["gitlab-runner<br/>shell executor, user deploy<br/>tag: bsuir-ci-ct"]
            docker["Docker Engine"]
            devapp["bsuir-ci-dev-app-1<br/>localhost:8081 → 80"]
            prodapp["bsuir-ci-prod-app-1<br/>localhost:8080 → 80"]
            ts["tailscaled<br/>Serve / Funnel, TLS termination"]
            runner -->|docker compose| docker
            docker --> devapp
            docker --> prodapp
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
    tailnet -->|"HTTPS<br/>dev-bsuir-app.tail65829d.ts.net"| ts
    ts -->|"localhost:8080"| prodapp
    ts -->|"localhost:8081"| devapp
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
    gl->>sr: build (changes in python/)
    sr->>sr: docker build python/
    sr->>reg: push :<sha>, :src-<tree>, :dev
    gl->>ct: deploy-dev
    ct->>reg: pull :<sha>
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
    main -- no --> changes{"changes in python/?"}
    changes -- no --> skip2([no jobs])
    changes -- yes --> build[build] --> devdeploy[deploy-dev]
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

### Network flows

```mermaid
flowchart LR
    subgraph internet["Internet"]
        glcore["gitlab.com"]
        glreg[("registry.gitlab.com")]
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
        end
    end

    ws["Workstation"]
    tailnet["Tailnet clients"]

    ws -->|"SSH 22<br/>git push"| glcore
    ws -->|"SSH 22<br/>git push"| gh
    glcore -->|"HTTPS 443<br/>push mirror"| gh
    runner -->|"HTTPS 443<br/>long polling"| glcore
    dockerd -->|"HTTPS 443<br/>image pull"| glreg

    public -->|"HTTPS 443<br/>bsuir-app.tail65829d.ts.net"| relay
    relay -->|"WireGuard"| tsd
    tailnet -->|"HTTPS 443 over WireGuard<br/>dev-bsuir-app.tail65829d.ts.net"| tsd
    tsd -->|"HTTP"| prod
    tsd -->|"HTTP"| devapp
```

## Pipeline

| Event | Jobs | Result |
|---|---|---|
| Push to feature branch (changes in `python/`) | `build` → `deploy-dev` | Image built, deployed to dev (`:8081`) |
| Push to feature branch (docs only) | — | Nothing |
| MR merged into `main` | `promote` → `deploy-prod` | Image retagged, deployed to prod (`:8080`) |
| Direct push to `main` | — | Blocked by branch protection |

### Image tags

| Tag | Set by | Meaning |
|---|---|---|
| `<commit sha>` | `build` | Commit the image was built from |
| `src-<tree>` | `build` | Hash of `python/` tree — content-based lookup key for `promote` |
| `dev` | `build` | Latest feature branch build |
| `prod` | `promote` | Current production image |
| `merged-<sha>` | `promote` | Image released by this merge commit (immutable, used for rollback) |

`promote` finds the image by `python/` tree hash, so prod gets exactly the app content built on the feature branch, regardless of docs commits or merge method. If `main` diverged in `python/` while the MR was open, `promote` fails — rebase the branch.

### Rollback

Deployments → Environments → `prod` → Re-deploy an older deployment. Or manually:
```
skopeo copy --all docker://registry.gitlab.com/tsuyakashi/bsuir-ci:merged-<old_sha> docker://registry.gitlab.com/tsuyakashi/bsuir-ci:prod
```

## Infrastructure

Single LXC `bsuir-ci-ct` (CT 230 on `pve-rog`): GitLab runner (shell executor, user `deploy`) + Docker, dev and prod as separate compose projects (`bsuir-ci-dev`, `bsuir-ci-prod`). Reachable via Tailscale.

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
  --cores 1 --memory 1024 --swap 512 \
  --rootfs local-lvm:8 \
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

### Tailscale (in CT)
```
curl -fsSL https://tailscale.com/install.sh | sh
tailscale up --hostname bsuir-ci-ct --ssh
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
