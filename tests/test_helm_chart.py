"""The Helm chart in deploy/helm/fathom stays installable and in step with the app.

Version pins and file checks always run. The render checks need the `helm`
binary: they skip on a machine without it and fail on GitHub Actions, where the
runner image ships one, so the chart cannot rot unnoticed. `kubeconform`
(schema validation) is used when it is on PATH; the publish workflow runs it
on every image build.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import unittest
from typing import Dict, List

try:
    from _helpers import REPO, call, get_app, temp_data_dir
except ImportError:  # pragma: no cover
    from tests._helpers import REPO, call, get_app, temp_data_dir

CHART = REPO / "deploy" / "helm" / "fathom"
FULL_VALUES = CHART / "ci" / "full-values.yaml"
HELM = shutil.which("helm")
KUBECONFORM = shutil.which("kubeconform")
ON_CI = os.environ.get("GITHUB_ACTIONS") == "true"


def _version() -> str:
    text = (REPO / "fathom" / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r'^__version__ = "([^"]+)"$', text, re.M)
    assert m, "fathom/__init__.py has no __version__"
    return m.group(1)


def _chart_field(name: str) -> str:
    text = (CHART / "Chart.yaml").read_text(encoding="utf-8")
    m = re.search(r'^%s:\s*"?([^"\n]+?)"?\s*$' % re.escape(name), text, re.M)
    assert m, "Chart.yaml has no %s" % name
    return m.group(1)


def _helm(*args: str) -> "subprocess.CompletedProcess[str]":
    assert HELM
    return subprocess.run([HELM, *args], cwd=str(REPO), capture_output=True, text=True, timeout=120)


def _render(*args: str, hooks: bool = False) -> str:
    """`helm template` output; the `helm test` pod only with ``hooks``."""
    extra = [] if hooks else ["--skip-tests"]
    res = _helm("template", "fathom", str(CHART), "--namespace", "av", *extra, *args)
    if res.returncode != 0:
        raise AssertionError("helm template %s failed:\n%s" % (" ".join(args), res.stderr))
    return res.stdout


def _docs(rendered: str) -> Dict[str, List[str]]:
    """Rendered manifests grouped by kind."""
    out: Dict[str, List[str]] = {}
    for doc in re.split(r"^---\s*$", rendered, flags=re.M):
        m = re.search(r"^kind:\s*(\S+)\s*$", doc, re.M)
        if m:
            out.setdefault(m.group(1), []).append(doc)
    return out


def _one(docs: Dict[str, List[str]], kind: str) -> str:
    found = docs.get(kind) or []
    assert len(found) == 1, "expected one %s, got %d" % (kind, len(found))
    return found[0]


class ChartFiles(unittest.TestCase):
    def test_chart_versions_follow_the_app(self):
        version = _version()
        self.assertEqual(_chart_field("version"), version, "Chart.yaml version must equal fathom.__version__")
        self.assertEqual(_chart_field("appVersion"), version, "Chart.yaml appVersion must equal fathom.__version__")

    def test_expected_files(self):
        for rel in ("Chart.yaml", "values.yaml", "values.schema.json", "README.md", "templates/NOTES.txt",
                    "templates/deployment.yaml", "templates/service.yaml", "templates/ingress.yaml", "templates/pvc.yaml",
                    "templates/serviceaccount.yaml", "ci/full-values.yaml"):
            self.assertTrue((CHART / rel).is_file(), "missing deploy/helm/fathom/%s" % rel)

    def test_defaults_carry_no_credentials(self):
        text = (CHART / "values.yaml").read_text(encoding="utf-8")
        self.assertRegex(text, r"(?m)^  password: \"\"$", "admin.password must default to empty")
        self.assertRegex(text, r"(?m)^  values: \{\}$", "secrets.values must default to empty")
        self.assertRegex(text, r"(?m)^  existingSecret: \"\"$")
        for line in text.splitlines():
            if line.lstrip().startswith("#"):
                continue
            m = re.match(r"\s*(FATHOM_AUTH|FATHOM_\w*(?:API_KEY|PASSWORD|COMMUNITY|AUTH_KEY|PRIV_KEY))\s*:\s*(.*)$", line)
            if m:
                self.assertIn(m.group(2).strip(), ("", '""'), "values.yaml sets a credential: %s" % m.group(1))

    def test_probe_path_is_a_public_route(self):
        text = (CHART / "values.yaml").read_text(encoding="utf-8")
        m = re.search(r"(?m)^probes:\n  path: (\S+)$", text)
        self.assertTrue(m, "values.yaml probes.path")
        with temp_data_dir(FATHOM_AUTH="probe:probe-password-1"):
            st, _h, _body = call(get_app(), "GET", m.group(1))
        self.assertEqual(st, 200, "the probes must hit a route that answers 200 without a login")

    def test_image_and_chart_agree_on_user_and_entry_point(self):
        dockerfile = (REPO / "Dockerfile").read_text(encoding="utf-8")
        values = (CHART / "values.yaml").read_text(encoding="utf-8")
        deployment = (CHART / "templates" / "deployment.yaml").read_text(encoding="utf-8")
        self.assertIn("USER 10001:10001", dockerfile)
        self.assertRegex(values, r"(?m)^  runAsUser: 10001$")
        self.assertRegex(values, r"(?m)^  fsGroup: 10001$")
        self.assertIn("python-netraw", dockerfile, "discovery.rawSockets starts gunicorn through this interpreter")
        self.assertIn("python-netraw", deployment)
        self.assertIn("fathom.server:app", deployment)


@unittest.skipUnless(HELM or ON_CI, "helm is not installed")
class ChartRenders(unittest.TestCase):
    def setUp(self):
        self.assertTrue(HELM, "helm is missing on the CI runner; install it in .github/workflows/ci.yml (azure/setup-helm)")

    def test_lint(self):
        for extra in ([], ["-f", str(FULL_VALUES)]):
            res = _helm("lint", str(CHART), *extra)
            self.assertEqual(res.returncode, 0, res.stdout + res.stderr)

    def test_default_render(self):
        docs = _docs(_render())
        self.assertEqual(sorted(docs), ["Deployment", "PersistentVolumeClaim", "Secret", "Service", "ServiceAccount"])
        dep = _one(docs, "Deployment")
        self.assertRegex(dep, r"(?m)^  replicas: 1$")
        self.assertRegex(dep, r"(?m)^  strategy:\n    type: Recreate$")
        self.assertIn("image: ghcr.io/vader8480/fathom:%s" % _version(), dep)
        self.assertIn("enableServiceLinks: false", dep, "a Service named fathom would otherwise inject FATHOM_PORT")
        self.assertIn("automountServiceAccountToken: false", dep)
        self.assertNotIn("hostNetwork", dep)
        self.assertNotIn("NET_RAW", dep)
        self.assertNotIn("python-netraw", dep)
        for want in ("runAsNonRoot: true", "runAsUser: 10001", "fsGroup: 10001", "readOnlyRootFilesystem: true",
                     "allowPrivilegeEscalation: false", "type: RuntimeDefault", "name: admin-bootstrap",
                     "--password-stdin", "claimName: fathom", "mountPath: /data", "mountPath: /tmp"):
            self.assertIn(want, dep)
        self.assertRegex(dep, r"drop:\n\s+- ALL")
        self.assertEqual(len(re.findall(r"path: /healthz", dep)), 3, "startup, liveness and readiness probes")
        for name in ("requests:", "limits:"):
            self.assertIn(name, dep)
        self.assertRegex(dep, r"- name: FATHOM_DATA\n\s+value: /data")
        self.assertNotIn("envFrom", dep)

        pvc = _one(docs, "PersistentVolumeClaim")
        self.assertIn("helm.sh/resource-policy: keep", pvc)
        self.assertIn("ReadWriteOnce", pvc)
        self.assertNotIn("storageClassName", pvc, "the default must use the cluster's default class (local-path on k3s)")
        svc = _one(docs, "Service")
        self.assertIn("type: ClusterIP", svc)
        self.assertIn("targetPort: http", svc)
        secret = _one(docs, "Secret")
        self.assertRegex(secret, r"(?m)^  name: fathom-admin$")
        self.assertRegex(secret, r'(?m)^  password: "[A-Za-z0-9+/=]{32}"$', "a generated 24-character password")

    def test_generated_admin_password_is_random(self):
        first = re.search(r'password: "(.+)"', _one(_docs(_render()), "Secret"))
        second = re.search(r'password: "(.+)"', _one(_docs(_render()), "Secret"))
        self.assertTrue(first and second)
        self.assertNotEqual(first.group(1), second.group(1))

    def test_full_render(self):
        docs = _docs(_render("-f", str(FULL_VALUES)))
        self.assertEqual(sorted(docs), ["Deployment", "Ingress", "PersistentVolumeClaim", "Secret", "Service", "ServiceAccount"])
        dep = _one(docs, "Deployment")
        self.assertRegex(dep, r"(?m)^  replicas: 1$")
        self.assertRegex(dep, r"(?m)^  strategy:\n    type: Recreate$")
        for want in ("hostNetwork: true", "dnsPolicy: ClusterFirstWithHostNet", "- python-netraw", "- NET_RAW",
                     "allowPrivilegeEscalation: false", "- name: ghcr-pull", "name: fathom-admin-login",
                     "key: admin-password", "name: fathom-env", "name: fathom-existing-env", "name: fathom-extra",
                     "containerPort: 8081", '"0.0.0.0:8081"', "subPath: fathom", "medium: Memory",
                     "kubernetes.io/arch: arm64", "priorityClassName: system-cluster-critical", "name: TZ",
                     "mountPath: /plugins", "example.org/tier: tools"):
            self.assertIn(want, dep)
        self.assertRegex(dep, r'- name: FATHOM_PUBLIC_URL\n\s+value: "https://fathom.example.org"',
                         "the public URL defaults to the first ingress host")
        self.assertRegex(dep, r'- name: FATHOM_MAX_UPLOAD_MB\n\s+value: "100"')
        self.assertNotIn("placeholder", dep, "secret values must not appear in the pod spec")
        bootstrap = dep.split("containers:")[0]
        self.assertNotIn("NET_RAW", bootstrap, "only the server container gets the capability")

        secrets = docs["Secret"]
        self.assertEqual(len(secrets), 1, "admin.existingSecret means the chart creates no admin Secret")
        self.assertIn("FATHOM_LLM_API_KEY:", secrets[0])
        ingress = _one(docs, "Ingress")
        for want in ("ingressClassName: traefik", 'host: "fathom.example.org"', 'host: "av.example.org"',
                     "secretName: fathom-tls", "pathType: Prefix"):
            self.assertIn(want, ingress)
        pvc = _one(docs, "PersistentVolumeClaim")
        self.assertIn("storageClassName: longhorn", pvc)
        self.assertIn("storage: 20Gi", pvc)
        self.assertNotIn("resource-policy", pvc)
        svc = _one(docs, "Service")
        self.assertIn("type: NodePort", svc)
        self.assertIn("nodePort: 30880", svc)

    def test_switches(self):
        docs = _docs(_render("--set", "admin.enabled=false", "--set", "persistence.enabled=false",
                             "--set", "serviceAccount.create=false"))
        self.assertEqual(sorted(docs), ["Deployment", "Service"])
        dep = _one(docs, "Deployment")
        self.assertNotIn("initContainers", dep)
        self.assertRegex(dep, r"- name: data\n\s+emptyDir: \{\}")
        self.assertIn("serviceAccountName: default", dep)

        docs = _docs(_render("--set", "persistence.existingClaim=my-data", "--set", "persistence.storageClass=-"))
        self.assertNotIn("PersistentVolumeClaim", docs)
        self.assertIn("claimName: my-data", _one(docs, "Deployment"))
        pvc = _one(_docs(_render("--set", "persistence.storageClass=-")), "PersistentVolumeClaim")
        self.assertIn('storageClassName: ""', pvc)

        docs = _docs(_render("--set", "admin.password=a-long-enough-password"))
        self.assertNotIn("resource-policy", _one(docs, "Secret"), "only a generated password is kept on uninstall")
        self.assertNotIn("a-long-enough-password", _one(docs, "Deployment"))

    def test_bad_values_are_refused(self):
        cases = [
            (["--set", "config.FATHOM_AUTH=tech:change-me"], "secrets"),
            (["--set", "config.FATHOM_LLM_API_KEY=sk-x"], "secrets"),
            (["--set", "config.FATHOM_DATA=/elsewhere"], "FATHOM_DATA"),
            (["--set", "admin.password=short"], "admin"),
            (["--set", "replicaCount=2"], "replicaCount"),
            (["--set", "service.type=ExternalName"], "service"),
        ]
        for args, needle in cases:
            res = _helm("template", "fathom", str(CHART), *args)
            self.assertNotEqual(res.returncode, 0, "helm template %s should fail" % " ".join(args))
            self.assertIn(needle, res.stderr, " ".join(args))

    @unittest.skipUnless(KUBECONFORM, "kubeconform is not installed")
    def test_manifests_validate_against_the_kubernetes_schemas(self):
        rendered = _render(hooks=True) + "\n---\n" + _render("-f", str(FULL_VALUES), hooks=True)
        self.assertIn("helm.sh/hook: test", rendered)
        assert KUBECONFORM
        res = subprocess.run([KUBECONFORM, "-strict", "-summary", "-"], input=rendered, capture_output=True, text=True, timeout=180)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)

