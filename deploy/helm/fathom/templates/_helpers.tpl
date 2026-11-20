{{- define "fathom.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "fathom.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{- define "fathom.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "fathom.selectorLabels" -}}
app.kubernetes.io/name: {{ include "fathom.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "fathom.labels" -}}
helm.sh/chart: {{ include "fathom.chart" . }}
{{ include "fathom.selectorLabels" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "fathom.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "fathom.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{- define "fathom.image" -}}
{{- if .Values.image.digest }}
{{- printf "%s@%s" .Values.image.repository .Values.image.digest }}
{{- else }}
{{- printf "%s:%s" .Values.image.repository (default .Chart.AppVersion .Values.image.tag) }}
{{- end }}
{{- end }}

{{- define "fathom.envSecretName" -}}
{{- printf "%s-env" (include "fathom.fullname" .) }}
{{- end }}

{{- define "fathom.adminSecretName" -}}
{{- default (printf "%s-admin" (include "fathom.fullname" .)) .Values.admin.existingSecret }}
{{- end }}

{{- define "fathom.claimName" -}}
{{- default (include "fathom.fullname" .) .Values.persistence.existingClaim }}
{{- end }}

{{/* "true" when the data volume is still there after `helm uninstall`. */}}
{{- define "fathom.dataOutlivesRelease" -}}
{{- if and .Values.persistence.enabled (or .Values.persistence.existingClaim .Values.persistence.retainOnUninstall) -}}
true
{{- end }}
{{- end }}

{{/* http(s)://<first ingress host>, or nothing without an Ingress. */}}
{{- define "fathom.ingressUrl" -}}
{{- if and .Values.ingress.enabled .Values.ingress.hosts }}
{{- $host := (first .Values.ingress.hosts).host }}
{{- if $host }}
{{- printf "%s://%s" (ternary "https" "http" (not (empty .Values.ingress.tls))) $host }}
{{- end }}
{{- end }}
{{- end }}

{{/* Variables that carry credentials: refused in `config`, expected under `secrets`. */}}
{{- define "fathom.secretVariables" -}}
FATHOM_AUTH FATHOM_LLM_API_KEY FATHOM_UNIFI_API_KEY FATHOM_UNIFI_PASSWORD FATHOM_SNMP_COMMUNITY FATHOM_SNMP_AUTH_KEY FATHOM_SNMP_PRIV_KEY FATHOM_QSYS_PASSWORD FATHOM_DDM_API_KEY
{{- end }}

{{/* The `config` map as container env entries, after checking it. */}}
{{- define "fathom.configEnv" -}}
{{- $secret := splitList " " (include "fathom.secretVariables" .) }}
{{- $config := deepCopy .Values.config }}
{{- if and (not (get $config "FATHOM_PUBLIC_URL")) (include "fathom.ingressUrl" .) }}
{{- $_ := set $config "FATHOM_PUBLIC_URL" (include "fathom.ingressUrl" .) }}
{{- end }}
{{- range $name, $value := $config }}
{{- if eq $name "FATHOM_DATA" }}
{{- fail "config.FATHOM_DATA: the data directory is always /data (the persistent volume); remove it from config" }}
{{- end }}
{{- if has $name $secret }}
{{- fail (printf "config.%s is a credential: set it under secrets.values or in secrets.existingSecret instead" $name) }}
{{- end }}
{{- if not (regexMatch "^[A-Za-z_][A-Za-z0-9_]*$" $name) }}
{{- fail (printf "config.%s is not a valid environment variable name" $name) }}
{{- end }}
{{- if not (kindIs "invalid" $value) }}
{{- if ne (toString $value) "" }}
- name: {{ $name }}
  value: {{ toString $value | quote }}
{{- end }}
{{- end }}
{{- end }}
{{- end }}

{{/* Container securityContext of the server; NET_RAW is added for discovery.rawSockets. */}}
{{- define "fathom.serverSecurityContext" -}}
{{- $ctx := deepCopy .Values.securityContext }}
{{- if .Values.discovery.rawSockets }}
{{- $caps := default dict (get $ctx "capabilities") }}
{{- $add := default list (get $caps "add") }}
{{- if not (has "NET_RAW" $add) }}
{{- $add = append $add "NET_RAW" }}
{{- end }}
{{- $_ := set $caps "add" $add }}
{{- $_ := set $ctx "capabilities" $caps }}
{{- end }}
{{- toYaml $ctx }}
{{- end }}

{{- define "fathom.dnsPolicy" -}}
{{- if .Values.dnsPolicy }}
{{- .Values.dnsPolicy }}
{{- else if .Values.discovery.hostNetwork }}
{{- print "ClusterFirstWithHostNet" }}
{{- else }}
{{- print "ClusterFirst" }}
{{- end }}
{{- end }}
