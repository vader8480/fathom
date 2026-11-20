# Fathom Helm chart

Runs [Fathom](https://github.com/vader8480/fathom) on Kubernetes: one pod
(gunicorn, non-root, read-only root filesystem) with the data directory on a
persistent volume, a Service, and an optional Ingress. It is written for a
small k3s cluster on Raspberry Pis and works on any cluster with a default
StorageClass.

Kubernetes is an additional way to run Fathom. The reference deployment is
still the Ubuntu VM with systemd described in the main README.

| | |
| --- | --- |
| Image | `ghcr.io/vader8480/fathom` for `linux/arm64`, `linux/amd64` and `linux/arm/v7`. Tags: `X.Y.Z`, `X.Y` and `latest` for releases, `main` and `sha-<short sha>` for the main branch |
| Chart | `oci://ghcr.io/vader8480/charts/fathom`, published for every `vX.Y.Z` tag; chart version = app version |
| Needs | Kubernetes 1.23+, Helm 3.8+ or 4, a StorageClass (k3s ships `local-path`) |

## Quick start: k3s on Raspberry Pi

1. A 64-bit OS is recommended. On Raspberry Pi OS, k3s needs the memory
   cgroup: append `cgroup_memory=1 cgroup_enable=memory` to the single line in
   `/boot/firmware/cmdline.txt` and reboot. Then install k3s
   (`curl -sfL https://get.k3s.io | sh -`) and Helm on the machine you run
   `kubectl` from.

2. Install the chart. From a release:

   ```bash
   helm install fathom oci://ghcr.io/vader8480/charts/fathom \
     --namespace fathom --create-namespace
   ```

   Or from a checkout of this repository, following the `main` image:

   ```bash
   helm install fathom deploy/helm/fathom \
     --namespace fathom --create-namespace \
     --set image.tag=main --set image.pullPolicy=Always
   ```

   If either the image or the chart cannot be pulled, see
   [Private image or chart](#private-image-or-chart).

3. Wait for the pod and read the generated admin password:

   ```bash
   kubectl -n fathom rollout status deployment/fathom
   kubectl -n fathom get secret fathom-admin -o jsonpath='{.data.password}' | base64 -d; echo
   ```

4. Open it. Without an Ingress:

   ```bash
   kubectl -n fathom port-forward service/fathom 8080:8080     # http://127.0.0.1:8080/
   ```

   With the Traefik that k3s ships, put this in `fathom-values.yaml` and pass
   `-f fathom-values.yaml` to `helm install` / `helm upgrade` (the name must
   resolve to a node; add `ingress.tls` once you have a certificate):

   ```yaml
   ingress:
     enabled: true
     className: traefik
     hosts:
       - host: fathom.lan
   ```

   Sign in as `admin`, then change the password and add people under
   *Settings › Users*.

`helm test fathom -n fathom` checks `/healthz` through the Service.

## What you get

- **Deployment**, always one replica with the `Recreate` strategy. Fathom
  stores everything as files in one directory on a ReadWriteOnce volume, so
  two pods must never run against it; an upgrade stops the old pod first
  (a few seconds of downtime).
- **PersistentVolumeClaim** for `/data` (`FATHOM_DATA`), 5 Gi from the default
  StorageClass, kept when the release is uninstalled.
- **Service** (ClusterIP, port 8080), **ServiceAccount** (no API token
  mounted), optional **Ingress**.
- Startup, liveness and readiness probes on `GET /healthz`.
- An init container that creates the first admin user (below).

With k3s `local-path` the volume is a directory on the node the pod first ran
on (`/var/lib/rancher/k3s/storage/...`), so the pod stays on that node and the
data is only as safe as that node's disk: take [backups](#backup-and-restore).

## Values

`values.yaml` documents every value; `values.schema.json` rejects unknown or
mistyped ones. The ones you are most likely to set:

| Value | Default | Purpose |
| --- | --- | --- |
| `image.repository`, `image.tag`, `image.digest`, `image.pullPolicy` | `ghcr.io/vader8480/fathom`, chart appVersion, – , `IfNotPresent` | image to run |
| `imagePullSecrets` | `[]` | pull secrets for a private package |
| `config` | all empty | non-secret `FATHOM_*` settings as environment variables |
| `secrets.existingSecret`, `secrets.values` | none | credentials as environment variables (existing Secret, or one the chart creates) |
| `admin.enabled`, `admin.username`, `admin.existingSecret`, `admin.passwordKey`, `admin.password`, `admin.resetPassword` | `true`, `admin`, – , `password`, generated, `false` | first admin user |
| `persistence.enabled`, `.size`, `.storageClass`, `.existingClaim`, `.accessModes`, `.volumeName`, `.subPath`, `.retainOnUninstall` | `true`, `5Gi`, cluster default, – , `[ReadWriteOnce]`, – , – , `true` | the data volume |
| `service.type`, `service.port`, `service.nodePort` | `ClusterIP`, `8080`, – | Service |
| `ingress.enabled`, `.className`, `.annotations`, `.hosts`, `.tls` | `false` | Ingress |
| `discovery.hostNetwork`, `discovery.rawSockets` | `false`, `false` | layer-2 reach for network discovery (below) |
| `server.port`, `.workers`, `.threads`, `.timeout`, `.accessLog`, `.extraArgs` | `8080`, `2`, `4`, `180`, `true`, `[]` | gunicorn |
| `resources` | requests 100m / 160Mi, limits 1 CPU / 768Mi | sized for a Pi 4 / 5 |
| `podSecurityContext`, `securityContext` | uid/gid/fsGroup 10001, non-root, seccomp `RuntimeDefault`; no privilege escalation, read-only root, all capabilities dropped | pod and container security |
| `probes` | `/healthz` | probe path and timings |
| `extraEnv`, `extraEnvFrom`, `extraVolumes`, `extraVolumeMounts` | `[]` | extra environment and volumes |
| `nodeSelector`, `tolerations`, `affinity`, `priorityClassName`, `podAnnotations`, `podLabels` | empty | scheduling and metadata |
| `serviceAccount.create`, `.name`, `.annotations` | `true` | ServiceAccount |

### Settings and credentials

`config` takes the variable names from the main README's *Settings* table.
`FATHOM_DATA` is fixed to `/data`, and `FATHOM_PUBLIC_URL` defaults to the
first Ingress host when the Ingress is enabled.

```yaml
config:
  FATHOM_PUBLIC_URL: https://fathom.example.org
  FATHOM_PUBLIC_VIEW: "1"
  FATHOM_LLM_PROVIDER: openai
  FATHOM_LLM_MODEL: gpt-4o-mini
```

Credentials never go into `config` (the chart refuses `FATHOM_AUTH`,
`*_API_KEY`, `*_PASSWORD` and the SNMP secrets there, because they would show
up in the pod spec). Keep them in a Secret whose keys are the variable names:

```bash
kubectl -n fathom create secret generic fathom-env \
  --from-literal=FATHOM_LLM_API_KEY='sk-...' \
  --from-literal=FATHOM_UNIFI_API_KEY='...'
helm upgrade fathom oci://ghcr.io/vader8480/charts/fathom -n fathom \
  -f fathom-values.yaml --set secrets.existingSecret=fathom-env
```

or let the chart create it with `--set-string secrets.values.FATHOM_LLM_API_KEY=...`
(the value is then stored in the Helm release as well). Changing
`secrets.values` restarts the pod; after editing an existing Secret run
`kubectl -n fathom rollout restart deployment/fathom`. The LLM provider and the
per-project discovery credentials can also be set in the app, where they are
saved on the data volume.

### The first admin user

Until a user exists Fathom asks for no login and treats every visitor as an
admin. So by default (`admin.enabled=true`) an init container runs
`fathom user add <admin.username> --role admin --password-stdin` before the
server starts. It only acts when that user does not exist yet: a password you
change in the app survives restarts and upgrades, and the Secret then simply
no longer matches.

The password comes from, in this order:

1. `admin.existingSecret` (key `admin.passwordKey`, default `password`), the
   option to use with GitOps tools:

   ```bash
   kubectl -n fathom create secret generic fathom-admin-login --from-literal=password='at least 8 characters'
   helm install fathom ... --set admin.existingSecret=fathom-admin-login
   ```

2. `admin.password`, which the chart puts into the Secret `<release>-admin`;
3. otherwise a random 24-character password in that Secret, generated at
   install, kept across upgrades and kept on uninstall together with the data
   volume. (`helm template` and tools built on it cannot look up the existing
   Secret and would generate a new value on every render: use option 1 there.)

Lost the password? Set `admin.resetPassword=true` for one upgrade: the init
container then sets the password from the Secret again (and signs that user
out). Set `admin.enabled=false` to run without a login, or when you manage
users with `FATHOM_AUTH` or `kubectl exec ... -- fathom user add`.

## Private image or chart

A new GHCR package is private until its owner makes it public (GitHub →
profile → *Packages* → the package → *Package settings* → *Change
visibility*). While `ghcr.io/vader8480/fathom` is private the cluster needs a
pull secret, made from a GitHub personal access token (classic) with the
`read:packages` scope:

```bash
kubectl create namespace fathom
kubectl -n fathom create secret docker-registry ghcr-pull \
  --docker-server=ghcr.io \
  --docker-username=<github user> \
  --docker-password=<token with read:packages>

helm install fathom oci://ghcr.io/vader8480/charts/fathom -n fathom \
  --set 'imagePullSecrets[0].name=ghcr-pull'
```

While the chart package `charts/fathom` is private, log Helm in with the same
token first: `helm registry login ghcr.io -u <github user>`.

## Network discovery

Discovery runs only when someone presses *Run* in the app. What it can see
depends on where the pod sits on the network:

| Source | In an ordinary pod (default) | Needs |
| --- | --- | --- |
| UniFi controller, SNMP, Yamaha / Videohub / Q-SYS, Dante Domain Manager | works: plain unicast to addresses the cluster can route to | nothing |
| mDNS / Dante browsing | sees only the pod network | `discovery.hostNetwork` |
| ARP / neighbour table | sees only the pod's gateway | `discovery.hostNetwork` |
| LLDP / CDP listener | cannot open a raw socket | `discovery.rawSockets` and `discovery.hostNetwork` |

```yaml
discovery:
  hostNetwork: true
  rawSockets: true
nodeSelector:
  kubernetes.io/hostname: pi-av-1      # the node that is wired to the AV networks
```

Both are off by default because they trade isolation for reach:

- **`hostNetwork`** puts the pod in the node's network namespace. It sees
  every interface and VLAN the node has, which is the point: mDNS does not
  cross VLANs, so the node needs an interface (or 802.1Q sub-interface) on
  each AV VLAN, and the pod must be pinned to that node. The costs: the server
  port (`server.port`, 8080) is opened on the node itself, on all its
  addresses, so the app is reachable at `http://<node>:8080/` without the
  Ingress and its TLS, and the port must be free on that node; NetworkPolicies
  no longer apply to the pod; it can reach services that listen only on the
  node's loopback; and namespaces that enforce the Pod Security Standards need
  the `privileged` level
  (`kubectl label namespace fathom pod-security.kubernetes.io/enforce=privileged`).
- **`rawSockets`** adds the `NET_RAW` capability, which allows reading (and
  crafting) raw frames on every interface the pod can see; Fathom only
  listens for LLDP / CDP. The pod stays non-root with privilege escalation
  off: the server is started through `python-netraw`, a copy of the
  interpreter in the image that carries the file capability `cap_net_raw`, and
  `NET_RAW` is the only capability in the container's set. Like `hostNetwork`
  it is outside the *baseline* Pod Security level.

Check what the pod can see:

```bash
kubectl -n fathom exec deployment/fathom -c fathom -- python-netraw -m fathom discovery doctor
```

(with `rawSockets` off, use `python` instead of `python-netraw`). A secondary
network attachment (Multus with macvlan / ipvlan on the AV VLANs, set through
`podAnnotations`) is an alternative to `hostNetwork` that keeps the pod
network; it has not been tested with this chart.

## Upgrade

Keep your settings in a values file and pass it on every upgrade:

```bash
helm upgrade fathom oci://ghcr.io/vader8480/charts/fathom -n fathom -f fathom-values.yaml
kubectl -n fathom rollout status deployment/fathom
```

Add `--version X.Y.Z` to pick a release; without it Helm takes the newest.
Take a backup first: `helm rollback fathom -n fathom` brings back the previous
chart and image, not the previous data. When following `image.tag=main` with
`image.pullPolicy=Always`, `kubectl -n fathom rollout restart deployment/fathom`
pulls the current build.

## Backup and restore

**In the app** (recommended): *Settings › Backups › Back up now* downloads a
zip with every project, its history and attachments, the users, the session
key and the custom library; *Upload and restore* takes it back. The same from
a shell:

```bash
kubectl -n fathom exec deployment/fathom -c fathom -- fathom backup create     # prints /data/backups/<name>.zip
kubectl -n fathom exec deployment/fathom -c fathom -- fathom backup list
kubectl -n fathom exec deployment/fathom -c fathom -- cat /data/backups/<name>.zip > <name>.zip
```

Restore it into any release (a fresh install included):

```bash
kubectl -n fathom exec -i deployment/fathom -c fathom -- sh -c 'mkdir -p /data/backups && cat > /data/backups/<name>.zip' < <name>.zip
kubectl -n fathom exec deployment/fathom -c fathom -- fathom backup restore <name>.zip --yes
kubectl -n fathom rollout restart deployment/fathom
```

The restore first saves the current state as a `…-pre-restore.zip` backup. It
brings back the backup's users, so sign in with the passwords from that
backup (the `<release>-admin` Secret of a fresh install no longer applies).

**The whole volume** (everything under `/data`, including builds, backups and
the trash), as a tar stream:

```bash
kubectl -n fathom exec deployment/fathom -c fathom -- \
  sh -c 'cd /data && find . -mindepth 1 -maxdepth 1 -print0 | tar --null -T - -czf -' > fathom-data.tgz
```

To put it back, stop the server, unpack into the claim from a helper pod, and
start it again (use your image tag and claim name):

```bash
kubectl -n fathom scale deployment/fathom --replicas=0
kubectl -n fathom wait --for=delete pod -l app.kubernetes.io/name=fathom --timeout=120s
kubectl -n fathom run fathom-restore --rm -i --restart=Never --image=ghcr.io/vader8480/fathom:main --overrides='
{"spec":{"securityContext":{"runAsUser":10001,"runAsGroup":10001,"fsGroup":10001},
 "containers":[{"name":"fathom-restore","image":"ghcr.io/vader8480/fathom:main","stdin":true,"stdinOnce":true,
   "command":["sh","-c","find /data -mindepth 1 -delete && tar -C /data -xzf -"],
   "volumeMounts":[{"name":"data","mountPath":"/data"}]}],
 "volumes":[{"name":"data","persistentVolumeClaim":{"claimName":"fathom"}}]}}' < fathom-data.tgz
kubectl -n fathom scale deployment/fathom --replicas=1
```

Add `"imagePullSecrets":[{"name":"ghcr-pull"}]` to `spec` when the image is
private. To move to another cluster or volume, create the claim there first
and install with `persistence.existingClaim=<claim>`. Store backups off the
cluster and treat them like password files: they hold the password hashes and
the session key.

## Uninstall

```bash
helm uninstall fathom -n fathom
```

The data claim and a generated admin Secret are kept
(`helm.sh/resource-policy: keep`) and are picked up again by a later install
with the same release name and namespace. To delete the data for good:

```bash
kubectl -n fathom delete pvc fathom
kubectl -n fathom delete secret fathom-admin
```

Set `persistence.retainOnUninstall=false` to have the claim removed with the
release.

## Troubleshooting

- **Pod `Pending`, claim `Pending`**: no default StorageClass
  (`kubectl get storageclass`); set `persistence.storageClass`.
- **`ImagePullBackOff`**: the tag does not exist (`image.tag`; a chart taken
  from a checkout defaults to the release tag of its version) or the package
  is private.
- **`admin-bootstrap` fails with a permission error on `/data`**: the volume
  ignores `fsGroup` (some NFS and hostPath setups). Make the directory
  writable for uid/gid 10001 on the storage side.
- **`admin-bootstrap` fails with "password must be at least 8 characters"**:
  fix the Secret and delete the pod.
- **Uploads fail behind ingress-nginx**: raise its body limit, e.g.
  `nginx.ingress.kubernetes.io/proxy-body-size: 4096m` in `ingress.annotations`.

## Working on the chart

```bash
helm lint deploy/helm/fathom
helm lint deploy/helm/fathom -f deploy/helm/fathom/ci/full-values.yaml
helm template fathom deploy/helm/fathom | kubeconform -strict -summary -
python -m unittest discover -s tests -p test_helm_chart.py -v
```

`tests/test_helm_chart.py` runs in CI with the rest of the suite. The chart's
`version` and `appVersion` follow `fathom.__version__`; a release is a version
bump in `fathom/__init__.py` and `Chart.yaml`, then a `vX.Y.Z` tag, which
makes `.github/workflows/publish.yml` push the image and the chart.
