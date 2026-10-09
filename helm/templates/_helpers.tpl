{{/*
apiblast app image (api, workers, beat, migrate).
*/}}
{{- define "apiblast.image" -}}
image: {{ printf "%s:%s" .Values.image.repository (.Values.image.tag | toString) | quote }}
imagePullPolicy: {{ .Values.image.pullPolicy }}
{{- end }}

{{/*
Pod-level security context. Pass the security-context map itself, e.g.
  include "apiblast.securityContext" .Values.defaultSecurityContext
OnRootMismatch skips the recursive fsGroup chown when the volume root already
has the right ownership.
*/}}
{{- define "apiblast.securityContext" -}}
securityContext:
  runAsUser: {{ .runAsUser }}
  runAsGroup: {{ .runAsGroup }}
  fsGroup: {{ .fsGroup }}
  runAsNonRoot: {{ .runAsNonRoot }}
  fsGroupChangePolicy: "OnRootMismatch"
{{- end }}

{{/*
Shared-team PVC volume.
*/}}
{{- define "apiblast.volumes" -}}
- name: shared-team
  persistentVolumeClaim:
    claimName: {{ .Values.volumes.sharedTeam.claimName }}
{{- end }}

{{/*
App pod volumes: shared-team plus the databases.yml ConfigMap key.
*/}}
{{- define "apiblast.appVolumes" -}}
{{ include "apiblast.volumes" . }}
- name: apiblast-config
  configMap:
    name: apiblast-config
    items:
      - key: databases.yml
        path: databases.yml
{{- end }}

{{/*
Volume mounts for app containers: MMseqs2 DBs read-only, results RW, and
databases.yml at /etc/apiblast/databases.yml (DB_CONFIG).
*/}}
{{- define "apiblast.appVolumeMounts" -}}
- name: shared-team
  mountPath: /data/db
  subPath: {{ .Values.volumes.sharedTeam.subPaths.db }}
  readOnly: true
- name: shared-team
  mountPath: /data/results
  subPath: {{ .Values.volumes.sharedTeam.subPaths.results }}
- name: apiblast-config
  mountPath: /etc/apiblast
  readOnly: true
{{- end }}

{{/*
App container env from the ConfigMap and Secret. Entries in a container's
`env:` take precedence over these.
*/}}
{{- define "apiblast.commonEnvFrom" -}}
envFrom:
  - configMapRef:
      name: apiblast-config
  - secretRef:
      name: apiblast-credentials
{{- end }}

{{/*
Restart app pods when config or credentials change.
*/}}
{{- define "apiblast.checksumAnnotations" -}}
checksum/config: {{ include (print .Template.BasePath "/configmap.yaml") . | sha256sum }}
checksum/secret: {{ include (print .Template.BasePath "/secret.yaml") . | sha256sum }}
{{- end }}

{{/*
Root initContainer that creates folders on the shared-team volume and chowns
them (non-recursively) to the pod's uid:gid; kubelet would create a missing
subPath root-owned.
Pass a dict: root (the chart context), subPaths (list of subPaths),
owner ("uid:gid").
Usage: include "apiblast.initDirsContainer" (dict "root" $ "subPaths" (list "apiblast/results") "owner" "1000:100") | nindent 8
*/}}
{{- define "apiblast.initDirsContainer" -}}
{{- $dirs := list -}}
{{- range .subPaths -}}
{{- $dirs = append $dirs (printf "/shared/team/%s" (. | trimSuffix "/")) -}}
{{- end -}}
- name: init-dirs
  image: {{ printf "%s:%s" .root.Values.initImage.repository (.root.Values.initImage.tag | toString) | quote }}
  imagePullPolicy: {{ .root.Values.initImage.pullPolicy }}
  securityContext:
    runAsUser: 0
    runAsNonRoot: false
  command:
    - sh
    - -c
    - "mkdir -p {{ join " " $dirs }} && chown {{ .owner }} {{ join " " $dirs }} && chmod 770 {{ join " " $dirs }}"
  volumeMounts:
    - name: shared-team
      mountPath: /shared/team
  {{- include "apiblast.resources" (dict "requests" (dict "memory" "64Mi" "cpu" "100m")) | nindent 2 }}
{{- end }}

{{/*
Resource requests and limits, as climb-gre-helm's roz.resources plus an
optional top-level .gpu (int) that adds nvidia.com/gpu to limits.

Pass a dict shaped:
  requests:
    cpu: <quantity, string or int>  (required)
    memory: <quantity string>       (required)
  limits:
    enabled: <bool>                 (optional)
    cpu: <quantity>                 (optional)
    memory: <quantity string>       (optional)
  gpu: <int>                        (optional)

Whether cpu/memory limits are emitted, in order:
  1. limits.enabled explicitly false -> never emit
  2. limits.enabled explicitly true  -> emit
  3. limits.enabled unset but limits.cpu/limits.memory present -> emit
  4. otherwise -> no cpu/memory limits

When emitted, any of limits.cpu/limits.memory left unset falls back to the
matching requests value. nvidia.com/gpu is emitted whenever .gpu is set,
independently of limits.enabled.

Usage: include "apiblast.resources" .Values.someSection.resources | nindent <N>
*/}}
{{- define "apiblast.resources" -}}
{{- if or (hasKey . "memory") (hasKey . "cpu") -}}
{{- fail "apiblast.resources: flat resources block (memory/cpu) is not supported — use resources.requests.{cpu,memory} and, optionally, resources.limits.{enabled,cpu,memory}" -}}
{{- end -}}
{{- $req := required "apiblast.resources: .requests is required" .requests -}}
{{- $reqMemory := required "apiblast.resources: .requests.memory is required" $req.memory -}}
{{- $reqCpu := required "apiblast.resources: .requests.cpu is required" $req.cpu | toString -}}
{{- $lim := .limits | default dict -}}
{{- $unknown := omit $lim "enabled" "cpu" "memory" -}}
{{- if $unknown -}}
{{- fail (printf "apiblast.resources: unknown key(s) in limits: %s" (join ", " (keys $unknown))) -}}
{{- end -}}
{{- $emit := or (hasKey $lim "cpu") (hasKey $lim "memory") -}}
{{- if hasKey $lim "enabled" -}}
{{- $emit = $lim.enabled -}}
{{- end -}}
{{- $gpu := .gpu -}}
resources:
  requests:
    memory: {{ $reqMemory | quote }}
    cpu: {{ $reqCpu | quote }}
{{- if or $emit $gpu }}
  limits:
{{- if $emit }}
    memory: {{ $lim.memory | default $reqMemory | quote }}
    cpu: {{ $lim.cpu | default $reqCpu | quote }}
{{- end }}
{{- if $gpu }}
    nvidia.com/gpu: {{ $gpu | toString | quote }}
{{- end }}
{{- end }}
{{- end }}
