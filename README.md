# BSUIR CI

## Cheatsheet:

### Protect the main branch:
```
glab api -X DELETE projects/:id/protected_branches/main
glab api -X POST projects/:id/protected_branches -f name=main -f push_access_level=0 -f merge_access_level=40
```
### Creating LXC for runner & project:
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
