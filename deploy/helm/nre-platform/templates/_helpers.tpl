{{- define "nre.namespace" -}}
{{ .Values.global.namespace }}
{{- end }}

{{- define "nre.labels" -}}
app.kubernetes.io/part-of: nre-platform
app.kubernetes.io/managed-by: helm
{{- end }}
